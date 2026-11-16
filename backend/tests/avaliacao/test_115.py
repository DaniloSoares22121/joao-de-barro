"""115-b/d: pedido que muda um dado do trabalho muda o DADO (e refaz do cálculo); "O que mudou" diz onde muda."""
import asyncio
from datetime import date

from lovable.avaliacao import db, ia, orquestrador, revisoes, routes
from lovable.avaliacao.modelos import Trabalho


def _job():
    db.init()
    return db.criar_job(Trabalho(id="", numero=1, modalidade="AM", finalidade="ITCD", cliente="F", tipo="Casa",
                                 bairro="Centro", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
                                 data_base=date(2026, 10, 28), data_vistoria=date(2026, 11, 13)))


def test_pedido_de_data_base_muda_o_dado_e_refaz_do_calculo(monkeypatch):
    jid = _job()

    async def fake(sistema, prompt, esquema, **kw):
        return esquema(etapa="redacao", instrucao="usar a data da vistoria como data-base",
                       dados=[{"campo": "data_base", "valor": "2026-11-13"}])
    monkeypatch.setattr(ia, "perguntar", fake)
    monkeypatch.setattr(orquestrador, "enfileirar", lambda j: None)
    r = asyncio.run(routes.corrigir(jid, routes.Correcao(texto="Onde fica: capa\nO que mudar: data-base = data da vistoria"), _u={}))
    assert r["etapa"] == "redacao"                      # 129: nunca volta ao cálculo nem à extração por dado sem conta
    assert db.job(jid)["dados"]["data_base"] == "2026-11-13"
    linhas = revisoes.dados_trocados(jid, 0, 1 << 62)
    assert linhas == ["Dado trocado — data-base: de 28/10/2026 para 13/11/2026 (muda em: capa, cabeçalho de todas as "
                      "páginas, itens 1 e 4, resumo (item 12) e planilha)."]


def test_sem_dado_novo_nao_mexe(monkeypatch):
    jid = _job()

    async def fake(sistema, prompt, esquema, **kw):
        return esquema(etapa="redacao", instrucao="trocar a vírgula", dados=[{"campo": "data_base", "valor": "28/10/2026"}])
    monkeypatch.setattr(ia, "perguntar", fake)
    monkeypatch.setattr(orquestrador, "enfileirar", lambda j: None)
    r = asyncio.run(routes.corrigir(jid, routes.Correcao(texto="trocar a vírgula do item 2"), _u={}))
    assert r["etapa"] == "redacao" and revisoes.dados_trocados(jid, 0, 1 << 62) == []
