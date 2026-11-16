"""ORDEM 007 — "Cancelar": interrompe no fim da chamada em andamento ou entre etapas; status
CANCELADO com o aviso de que o custo não volta; "Reabrir" retoma sem refazer o que já foi
pago. Sem IA: as etapas são simuladas."""
import asyncio
from datetime import date

from lovable.avaliacao import db, orquestrador
from lovable.avaliacao.modelos import Trabalho
from tests.avaliacao.conftest import numero_unico


def _job() -> str:
    db.init()
    return db.criar_job(Trabalho(
        id="", numero=numero_unico(), modalidade="OV", finalidade="Venda", cliente="Teste",
        tipo="Sobrado", bairro="Jardim Vila Boa", cidade="Goiânia",
        pin_maps="https://maps.app.goo.gl/x", data_base=date(2026, 11, 11),
        data_vistoria=date(2026, 11, 11)))


def test_cancelar_no_fim_da_chamada_e_retomar(monkeypatch):
    jid = _job()
    chamadas = {"triagem": 0, "depois": 0}

    async def triagem(self):
        # o avaliador toca em "Cancelar" enquanto a "IA" da triagem roda
        chamadas["triagem"] += 1
        orquestrador._ativos.add(jid)
        assert orquestrador.pedir_cancelamento(jid) == "CANCELANDO"
        db.evento(jid, "triagem", "resultado", "triagem concluída", dados={"bloqueado": False})
        return {"bloqueado": False}   # (como o agente real, o resultado fica gravado)

    async def resto(self):
        chamadas["depois"] += 1

    monkeypatch.setattr(orquestrador._Pipeline, "_triagem", triagem)
    monkeypatch.setattr(orquestrador._Pipeline, "_ate_revisao", resto)
    st = asyncio.run(orquestrador.executar(jid))
    orquestrador._ativos.discard(jid)
    assert st == orquestrador.CANCELADO
    assert chamadas == {"triagem": 1, "depois": 0}          # parou no fim da chamada
    assert db.resultado(jid, "triagem") is not None          # o que foi pago fica guardado
    ent = db.resultado(jid, "entrega")
    assert ent["status"] == "CANCELADO" and ent["etapa_cancelada"] == "triagem"
    assert "custo de IA já gasto não volta" in ent["pendencias"][0]["texto"]
    assert db.job(jid)["status"] == "CANCELADO"

    # Reabrir (retomar): continua sem refazer a triagem
    db.arquivar_entrega(jid)
    db.set_etapa(jid, "triagem", "pendente")
    asyncio.run(orquestrador.executar(jid))
    assert chamadas == {"triagem": 1, "depois": 1}


def test_cancelar_parado_e_imediato():
    jid = _job()
    db.set_etapa(jid, "selecao", orquestrador.AGUARDANDO)   # esperando o avaliador
    assert orquestrador.pedir_cancelamento(jid) == orquestrador.CANCELADO
    ent = db.resultado(jid, "entrega")
    assert ent["status"] == "CANCELADO" and ent["etapa_cancelada"] == "selecao"
    # já finalizado: pedir de novo não muda nada
    assert orquestrador.pedir_cancelamento(jid) == "CANCELADO"
