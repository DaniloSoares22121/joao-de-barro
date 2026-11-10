"""D3: registro de custo/tempo por chamada de IA e limite de chamadas por trabalho."""
from tests.avaliacao.test_routes import dono  # noqa: F401  (fixture)
import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from lovable.avaliacao import db, ia, orquestrador
from tests.avaliacao import test_orquestrador as T


class Esq(BaseModel):
    valor: int


def _com_ctx(jid, etapa, coro):
    async def run():
        tok = ia.definir_contexto(jid, etapa)
        try:
            return await coro
        finally:
            ia._ctx.reset(tok)
    return asyncio.run(run())


def test_cada_chamada_registra_tokens_custo_e_tempo(monkeypatch):
    jid = T._job()

    async def chamar(sistema, prompt, opts):
        ia._anotar_uso(SimpleNamespace(usage={"input_tokens": 100, "cache_read_input_tokens": 20,
                                              "output_tokens": 7}, total_cost_usd=0.0125))
        return '{"valor": 1}'
    monkeypatch.setattr(ia, "_chamar", chamar)
    _com_ctx(jid, "selecao", ia.perguntar("s", "p", Esq, modelo="claude-haiku-4-5"))
    _com_ctx(jid, "selecao", ia.perguntar("s", "p", Esq))
    with db._conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM av_ia_chamadas WHERE job=?", (jid,))]
    assert len(rows) == 2 and rows[0]["etapa"] == "selecao"
    assert rows[0]["modelo"] == "claude-haiku-4-5" and rows[1]["modelo"]
    assert rows[0]["tokens_in"] == 120 and rows[0]["tokens_out"] == 7
    r = db.ia_resumo(jid)
    assert r["chamadas"] == 2 and r["custo_usd"] == pytest.approx(0.025) and r["tempo_s"] >= 0


def test_sem_contexto_nao_registra(monkeypatch):
    async def chamar(sistema, prompt, opts):
        return '{"valor": 1}'
    monkeypatch.setattr(ia, "_chamar", chamar)
    with db._conn() as c:
        antes = c.execute("SELECT COUNT(*) FROM av_ia_chamadas").fetchone()[0]
    asyncio.run(ia.perguntar("s", "p", Esq))
    with db._conn() as c:
        assert c.execute("SELECT COUNT(*) FROM av_ia_chamadas").fetchone()[0] == antes


def test_limite_de_chamadas_por_trabalho(monkeypatch):
    jid = T._job()
    db.set_setting("ia_max_chamadas", "2")
    try:
        async def chamar(sistema, prompt, opts):
            return '{"valor": 1}'
        monkeypatch.setattr(ia, "_chamar", chamar)
        for _ in range(2):
            _com_ctx(jid, "pesquisa", ia.perguntar("s", "p", Esq))
        with pytest.raises(ia.IAFalhou, match=ia.LIMITE_JOB):
            _com_ctx(jid, "pesquisa", ia.perguntar("s", "p", Esq))
    finally:
        db.set_setting("ia_max_chamadas", str(ia.MAX_CHAMADAS_PADRAO))


def test_limite_excedido_no_pipeline_vira_parcial(monkeypatch):
    T._mock(monkeypatch)
    mock = ia.perguntar

    async def com_limite(*a, **k):
        ia._checar_limite()
        return await mock(*a, **k)
    monkeypatch.setattr(ia, "perguntar", com_limite)
    jid = T._job()
    for _ in range(ia.MAX_CHAMADAS_PADRAO):
        db.registrar_ia(jid, "triagem", "m", 1, 1, None, 1)
    assert T._rodar(jid) == orquestrador.PARCIAL
    pend = [p["texto"] for p in db.resultado(jid, "entrega")["pendencias"]]
    assert any(ia.LIMITE_JOB in p for p in pend), pend


def test_detalhe_do_trabalho_traz_resumo_ia(client, dono):
    from tests.avaliacao.test_controle import API, _novo
    h, _ = dono
    jid = _novo(client, h)
    db.registrar_ia(jid, "extracao", "m", 10, 5, 0.5, 1500)
    r = client.get(f"{API}/jobs/{jid}", headers=h).json()
    assert r["resumo_ia"]["chamadas"] == 1 and r["resumo_ia"]["custo_usd"] == 0.5
    assert r["resumo_ia"]["tempo_s"] == 1.5


def test_reabrir_da_nova_cota_de_ia():
    jid = T._job()
    for _ in range(ia.MAX_CHAMADAS_PADRAO):
        db.registrar_ia(jid, "triagem", "m", 1, 1, None, 1)

    async def checar():
        tok = ia.definir_contexto(jid, "pesquisa")
        try:
            ia._checar_limite()
        finally:
            ia._ctx.reset(tok)
    with pytest.raises(ia.IAFalhou, match=ia.LIMITE_JOB):
        asyncio.run(checar())
    orquestrador.reabrir(jid, "pesquisa")
    asyncio.run(checar())                      # nova cota a partir da reabertura
    assert db.ia_resumo(jid)["chamadas"] == ia.MAX_CHAMADAS_PADRAO   # o total não some


def test_limite_atomico_com_chamadas_em_paralelo(monkeypatch):
    jid = T._job()
    db.set_setting("ia_max_chamadas", "2")
    try:
        async def chamar(sistema, prompt, opts):
            await asyncio.sleep(0.02)
            return '{"valor": 1}'
        monkeypatch.setattr(ia, "_chamar", chamar)

        async def varias():
            tok = ia.definir_contexto(jid, "pesquisa")
            try:
                return await asyncio.gather(*(ia.perguntar("s", "p", Esq) for _ in range(5)),
                                            return_exceptions=True)
            finally:
                ia._ctx.reset(tok)
        out = asyncio.run(varias())
        assert sum(isinstance(x, Esq) for x in out) == 2
        assert sum(isinstance(x, ia.IAFalhou) and ia.LIMITE_JOB in str(x) for x in out) == 3
        assert db.ia_resumo(jid)["chamadas"] == 2
    finally:
        db.set_setting("ia_max_chamadas", str(ia.MAX_CHAMADAS_PADRAO))


def test_limite_na_leitura_paralela_de_anuncios_propaga(monkeypatch):
    from lovable.avaliacao import coletor_fonte, coletor_hub
    from lovable.avaliacao.agentes import leitor_anuncio
    from lovable.avaliacao.coletor_hub import Captura
    from lovable.avaliacao.fonte_mercado import Consulta
    zap = "https://www.zapimoveis.com.br/imovel/"

    async def executar(job_id, acao, url, timeout=120):
        if "zapimoveis" not in url:
            return Captura(bloqueado=True)
        if acao == "busca":
            return Captura(ok=True, links=[f"{zap}l-{i}/" for i in range(3)])
        return Captura(ok=True, url_final=url, texto="t")

    async def ler(job_id, cap, portal, comuns=frozenset()):
        raise ia.IAFalhou(ia.LIMITE_JOB)

    async def sleep(s):
        pass
    monkeypatch.setattr(coletor_fonte, "_sleep", sleep)
    monkeypatch.setattr(coletor_hub, "executar", executar)
    monkeypatch.setattr(leitor_anuncio, "ler", ler)
    with pytest.raises(ia.IAFalhou, match=ia.LIMITE_JOB):
        asyncio.run(coletor_fonte.ColetorFonte().buscar(
            T._job(), [Consulta(tipologia="Sobrado", bairro="Bairro Lim", cidade="Goiânia")]))
