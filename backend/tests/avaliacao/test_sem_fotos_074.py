"""ORDEM 074-A2: trabalho sem foto de vistoria NÃO passa da redação (P5 §C) — para antes de escrever, em vez de
gerar o PDF vazio; e o "Montar o laudo" do cliente não abre o trabalho sem as fotos (o portão pergunta)."""
import asyncio

import pytest
from fastapi import HTTPException

from lovable.avaliacao import conversa as C
from lovable.avaliacao import db, orquestrador, portoes
from lovable.avaliacao import rotas_conversa as R
from tests.avaliacao.test_pagina_enviada import _job


def test_sem_foto_para_antes_da_redacao(monkeypatch):
    jid = _job()
    o = orquestrador._Pipeline(jid)
    chamadas = []

    async def passo(etapa, fn, valido=lambda d: True):
        chamadas.append(etapa)
        if etapa == "redacao":
            raise AssertionError("não podia escrever sem foto da vistoria")
        return {}
    monkeypatch.setattr(o, "passo", passo)
    monkeypatch.setattr(o, "_resultado", lambda: None)
    monkeypatch.setattr(o, "_sel", lambda: type("S", (), {"confirmado": True})())
    monkeypatch.setattr(orquestrador, "escolha_area", lambda jid_: {"base": "construida"})
    with pytest.raises(orquestrador._SemFotos):
        asyncio.run(o._ate_revisao())
    assert "redacao" not in chamadas
    assert any("Faltam as fotos da vistoria" in p.texto for p in o.pend)


def test_montar_o_laudo_pede_as_fotos():
    cid = C.criar("")
    C.juntar_contexto(cid, {"visita_feita": True, "entendimento_status": "confirmado", "solicitante_nome": "Maria Fictícia",
                            "imovel_tipo": "Casa", "visita": "2026-11-13T12:30", "data_base": "2026-10-28"})
    (C.pasta(cid) / "foto_cliente").mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (C.pasta(cid) / "foto_cliente" / f"IMG_{i}.jpg").write_bytes(b"\xff\xd8\xff" + b"x" * 50)
    with pytest.raises(HTTPException) as e:
        asyncio.run(R.seguir_para_laudo(cid, _u={}))
    assert e.value.status_code == 409 and "fotos da vistoria" in e.value.detail
    g = portoes.montar(cid, "visita")
    ids = [q["id"] for q in g["perguntas"]]
    assert ids[:3] == ["fotos", "pin", "medidas"]                # 117 / D-127: não há pergunta de data-base
    assert g["perguntas"][0]["pergunta"] == "Não tenho fotos da vistoria. As 3 fotos que você mandou são da vistoria?"
    portoes.confirmar(cid, "visita", "fotos", "sim")
    assert len(list((C.pasta(cid) / "foto").glob("*.jpg"))) == 3
    portoes.confirmar(cid, "visita", "pin", "https://maps.app.goo.gl/AbCdEf123")
    portoes.confirmar(cid, "visita", "medidas", "sim")          # 078-8
    portoes.confirmar(cid, "visita", "idade", "30 anos")         # 078-7
    assert portoes.montar(cid, "visita")["completo"]
    ctx = C.obter(cid)["contexto"]
    assert ctx["medidas_confere"] is True and ctx["idade_aparente"] == "30"
    d = C.trabalho_do_contexto(C.obter(cid)["contexto"], 1)
    assert d["data_base"] == d["data_vistoria"] == "2026-11-13"   # 117 / D-127: só a data da vistoria
    assert C.pin_do_contexto(C.obter(cid)["contexto"]) == "https://maps.app.goo.gl/AbCdEf123"
    assert db is not None
