"""ORDEM 099 (d): com o relato da Volta 7 ("contrato já assinado, não precisa de proposta"), o entendimento do caso
NÃO é pulado, e nada abre o trabalho sem imóvel, modalidade e finalidade — sem modalidade, pergunta (nunca OV).
Cliente de teste, sem dado real."""
import asyncio

import pytest
from fastapi import HTTPException

from lovable.avaliacao import conversa as C
from lovable.avaliacao import rotas_conversa as R

RELATO = ("Quem contrata é o cliente de teste. O contrato já foi assinado, não precisa de proposta. "
          "Data da DITCD 28/10/2026 (data-base). Vistoria em 13/11/2026 às 12h30.")


def _cliente_como_na_volta_7() -> str:
    cid = C.criar("Cliente de Teste")
    # o que a 096-3/096-4 gravam pelo relato: proposta dispensada ("fora") e contrato assinado — sem o entendimento
    C.atualizar(cid, contexto={"proposta_status": "fora", "contrato_status": "assinado", "relato": RELATO,
                               "data_ditcd": "2026-10-28", "visita": "2026-11-13"})
    return cid


def test_entendimento_nao_e_pulado_com_proposta_dispensada():
    cid = _cliente_como_na_volta_7()
    assert R.precisa_entender(cid) is True


def test_nao_abre_trabalho_sem_imovel_modalidade_e_finalidade():
    cid = _cliente_como_na_volta_7()
    falta = C.falta_para_montar(C.obter(cid)["contexto"])
    assert len(falta) == 3 and any("modalidade" in f for f in falta)
    with pytest.raises(HTTPException) as e:
        asyncio.run(R.seguir_para_laudo(cid, _u={}))
    assert e.value.status_code == 409 and ("entendimento" in str(e.value.detail) or "modalidade" in str(e.value.detail))


def test_com_o_entendimento_confirmado_pode_montar_e_nunca_assume_ov():
    ctx = {"imovel_tipo": "Casa térrea", "modalidade": "AM", "finalidade": "Justificar o valor declarado no ITCD",
           "entendimento_status": "confirmado"}
    assert C.falta_para_montar(ctx) == []
    sem_mod = {**ctx, "modalidade": ""}
    assert any("modalidade" in f for f in C.falta_para_montar(sem_mod))      # pergunta; nunca vira OV calado
