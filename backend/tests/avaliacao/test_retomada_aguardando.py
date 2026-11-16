"""ORDEM 034: reiniciar o servidor não pode fazer andar um trabalho que espera o avaliador
(o 9118 seguiu sozinho até a revisão depois de um "Só salvar" + reinício)."""
import asyncio
from datetime import date

from lovable.avaliacao import db, orquestrador
from lovable.avaliacao.modelos import Trabalho
from tests.avaliacao.conftest import numero_unico


def _job() -> str:
    db.init()
    return db.criar_job(Trabalho(
        id="", numero=numero_unico(), modalidade="OV", finalidade="Venda", cliente="Teste", tipo="Galpão",
        bairro="Centro", cidade="Goiânia", pin_maps="", data_base=date(2026, 11, 13),
        data_vistoria=date(2026, 11, 13)))


def test_partida_nao_enfileira_quem_espera_o_avaliador(monkeypatch):
    esperando, rodando = _job(), _job()
    db.set_etapa(esperando, "selecao", orquestrador.AGUARDANDO)
    db.set_etapa(rodando, "redacao", "executando")
    fila = []
    monkeypatch.setattr(orquestrador, "enfileirar", lambda jid: fila.append(jid))

    async def partida():
        orquestrador._worker = None
        w = orquestrador.iniciar_fila()
        w.cancel()
    asyncio.run(partida())
    assert esperando not in fila and rodando in fila
