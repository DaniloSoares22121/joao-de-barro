"""ORDEM 184: Configurações › Tabela de preços — o avaliador guarda o valor (e o prazo) de cada serviço,
e a proposta de um trabalho novo já vem preenchida por ela; o valor combinado só daquela proposta continua mandando."""
import asyncio

import pytest
from fastapi import HTTPException

from lovable.avaliacao import avaliadores as A
from lovable.avaliacao import conversa as C
from lovable.avaliacao import rotas_avaliadores as RA


def _u(av="AV-0001"):
    return {"avaliador_id": av}


def test_primeira_vez_vem_as_4_modalidades_e_nada_e_usado_antes_de_salvar():
    r = asyncio.run(RA.ver_tabela(_u=_u()))
    assert r["salva"] is False
    assert [l["servico"] for l in r["linhas"]][:4] == ["OV", "AM", "AM_GARANTIA", "AMJ"]
    assert C.sugerir_proposta({"modalidade": "OV", "imovel_tipo": "casa"})["valor"] == ""      # 071: sem piso sozinho


def test_salvar_e_a_proposta_vem_da_tabela_com_prazo():
    linhas = [{"servico": "OV", "valor": "500,00", "prazo_dias": 4},
              {"servico": "AMJ", "valor": "2.000", "prazo_dias": 15, "obs": "processo"},
              {"servico": "", "nome": "Galpão", "tipo": "galpão", "valor": "1.200,00"}]
    r = asyncio.run(RA.salvar_tabela({"linhas": linhas}, _u=_u()))
    assert r["salva"] and len(r["linhas"]) == 3 and r["linhas"][0]["nome"] == "Opinião de Valor"
    s = C.sugerir_proposta({"modalidade": "OV", "imovel_tipo": "casa"})
    assert s["valor"] == "500,00" and s["da_tabela"] and s["prazo"] == "em até 4 dias úteis após a visita técnica"
    assert C.sugerir_proposta({"modalidade": "OV", "imovel_tipo": "Galpão"})["valor"] == "1.200,00"
    assert C.sugerir_proposta({"modalidade": "AMJ", "imovel_tipo": "galpão"})["valor"] == "2.000,00"   # judicial: a linha dele
    assert C.sugerir_proposta({"modalidade": "AM", "imovel_tipo": "casa"})["valor"] == ""               # sem linha: em branco
    # mudar só nesta proposta: o valor combinado ganha da tabela
    s2 = C.sugerir_proposta({"modalidade": "OV", "imovel_tipo": "casa", "valor_combinado": "650"})
    assert s2["valor"] == "650,00" and not s2["da_tabela"]
    assert A.preco("AV-0001", "OV") == "500,00"


def test_remover_linha_e_valor_sem_numero():
    asyncio.run(RA.salvar_tabela({"linhas": [{"servico": "OV", "valor": "500"}]}, _u=_u()))
    r = asyncio.run(RA.salvar_tabela({"linhas": []}, _u=_u()))
    assert r["salva"] and r["linhas"] == []
    with pytest.raises(HTTPException) as e:
        asyncio.run(RA.salvar_tabela({"linhas": [{"servico": "OV", "valor": "quinhentos"}]}, _u=_u()))
    assert e.value.status_code == 400 and "sem número" in e.value.detail


def test_186_email_que_ja_existe_e_recusado_com_mensagem_clara():
    from lovable import auth
    auth.init()
    auth.criar_usuario("dono186@local", "senha-dono-186")
    with pytest.raises(HTTPException) as e:
        asyncio.run(RA.cadastrar(RA.Cadastro(email=" Dono186@LOCAL ", senha="outra-senha-1", nome="Teste"), _u=_u()))
    assert e.value.status_code == 409 and e.value.detail == "Já existe uma conta com este e-mail."


def test_revisao_tipo_por_palavra_inteira_e_linha_errada_da_400():
    asyncio.run(RA.salvar_tabela({"linhas": [{"servico": "AM", "valor": "1.200"},
                                             {"servico": "AM", "tipo": "sala comercial", "valor": "800"},
                                             {"servico": "AM", "tipo": "galpão", "valor": "1.500"}]}, _u=_u()))
    assert C.sugerir_proposta({"modalidade": "AM", "imovel_tipo": "Salão de festas"})["valor"] == "1.200,00"
    assert C.sugerir_proposta({"modalidade": "AM", "imovel_tipo": "Sala comercial no centro"})["valor"] == "800,00"
    assert C.sugerir_proposta({"modalidade": "AM", "imovel_tipo": "Galpão"})["valor"] == "1.500,00"
    with pytest.raises(HTTPException) as e:
        asyncio.run(RA.salvar_tabela({"linhas": ["texto"]}, _u=_u()))
    assert e.value.status_code == 400
