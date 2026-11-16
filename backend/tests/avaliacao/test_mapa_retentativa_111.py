"""111-3e: contorno do lote falhou → o sistema refaz pelo pin sozinho, uma vez; só pergunta se falhar de novo."""
import asyncio
from datetime import date

from lovable.avaliacao import coletor_fonte, db, orquestrador as O
from lovable.avaliacao.modelos import Trabalho

FALHA = "polígono da IA não contém o pino; demarcado quadrado em volta do pino"


def _job():
    db.init()
    return db.criar_job(Trabalho(id="", numero=1, modalidade="AM", finalidade="Garantia", cliente="F", tipo="Casa",
                                 bairro="Centro", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
                                 data_base=date(2026, 11, 15), data_vistoria=date(2026, 11, 14)))


def _avisos(jid):
    with db._conn() as c:
        return [r[0] for r in c.execute("SELECT msg FROM av_events WHERE job=? AND nivel='aviso'", (jid,))]


def test_refaz_sozinho_e_o_aviso_some(monkeypatch):
    jid = _job()
    chamadas = []

    async def maps(j, t):
        chamadas.append("1"); db.evento(j, "localizacao", "aviso", FALHA)

    async def refazer(j, t, refazer=False):
        chamadas.append("2" if refazer else "?")
    monkeypatch.setattr(coletor_fonte, "capturar_maps", refazer)
    asyncio.run(O._mapa_com_retentativa(jid, maps))
    assert chamadas == ["1", "2"] and FALHA not in _avisos(jid)


def test_falhou_de_novo_fica_o_aviso(monkeypatch):
    jid = _job()

    async def maps(j, t):
        db.evento(j, "localizacao", "aviso", FALHA)

    async def refazer(j, t, refazer=False):
        db.evento(j, "localizacao", "aviso", FALHA)
    monkeypatch.setattr(coletor_fonte, "capturar_maps", refazer)
    asyncio.run(O._mapa_com_retentativa(jid, maps))
    assert FALHA in _avisos(jid)


def test_deu_certo_de_primeira_nao_refaz(monkeypatch):
    jid = _job()
    chamadas = []

    async def maps(j, t):
        chamadas.append("1")

    async def refazer(j, t, refazer=False):
        chamadas.append("2")
    monkeypatch.setattr(coletor_fonte, "capturar_maps", refazer)
    asyncio.run(O._mapa_com_retentativa(jid, maps))
    assert chamadas == ["1"]
