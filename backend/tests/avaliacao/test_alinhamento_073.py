"""ORDEM 073-1: "O laudo avalia o imóvel inteiro ou só uma parte?" — responder "Imóvel inteiro" tira o ponto
"objeto" e leva ao passo 3 (antes a pergunta voltava sempre, porque "inteiro" gravava a parte vazia)."""
import asyncio

from lovable.avaliacao import rotas_conversa as R
from tests.avaliacao.test_pagina_enviada import _job


def _pontos(jid):
    return [p["id"] for p in asyncio.run(R.alinhamento(jid, _u={}))["pontos"]]


def test_imovel_inteiro_tira_o_ponto():
    jid = _job()
    assert "objeto" in _pontos(jid)
    r = asyncio.run(R.responder_alinhamento(jid, R.Resposta(id="objeto", resposta="Imóvel inteiro", texto=""), _u={}))
    assert "objeto" not in [p["id"] for p in r["pontos"]]
    assert "objeto" not in _pontos(jid)                        # recarregar não traz a pergunta de volta


def test_so_uma_parte_guarda_a_parte():
    jid = _job()
    asyncio.run(R.responder_alinhamento(jid, R.Resposta(id="objeto", resposta="Só uma parte", texto="Galpão 01"), _u={}))
    assert "objeto" not in _pontos(jid)
    from lovable.avaliacao import db
    assert db.job(jid)["dados"]["objeto_parte"] == "Galpão 01"
