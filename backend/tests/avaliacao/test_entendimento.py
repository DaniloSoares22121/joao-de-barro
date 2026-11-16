"""ORDEM 062: antes de começar, o JdB resume o caso e pergunta "É isso?" (IA simulada: não gasta)."""
import asyncio

import pytest
from fastapi import HTTPException

from lovable.avaliacao import conversa as C
from lovable.avaliacao import entendimento as E
from lovable.avaliacao import ia, rotas_conversa as R

RESUMO = {"campos": {"solicitante_nome": "Maria Teste", "imovel_tipo": "Casa", "cidade": "Goiânia",
                     "modalidade": "AMJ", "finalidade": "não deve entrar"},
          "entendi": "Entendi: a Maria precisa de um laudo para o ITCMD e está com pressa. Vamos fazer um PTAM não judicial. É isso?",
          "modalidade_sugerida": "AM", "finalidade": "ITCMD", "prazo": "até o fim do mês",
          "ainda_nao_sei": ["o endereço do imóvel"],
          "nao_fecha": "o ITCMD é estadual: o processo é na Secretaria da Economia, não na prefeitura. Foi lá mesmo?"}


@pytest.fixture
def ia_falsa(monkeypatch):
    chamadas = []

    async def fake(sistema, prompt, esquema, **k):
        chamadas.append((sistema, prompt))
        assert esquema is E.Resumo
        return esquema.model_validate(RESUMO)
    monkeypatch.setattr(ia, "perguntar", fake)
    return chamadas


def test_primeira_mensagem_vira_resumo_sem_decidir(ia_falsa):
    cid = C.criar("")
    st = asyncio.run(R.nova_mensagem(cid, R.Entrada(texto="Cliente Maria, ITCMD, processo na prefeitura", tipo="texto"), _u={}))
    msg = [m for m in st["mensagens"] if m["tipo"] == "entendimento"][-1]
    assert msg["texto"].startswith("Entendi: a Maria") and "É isso?" in msg["texto"]
    assert "Uma coisa não fecha: o ITCMD é estadual" in msg["texto"]
    assert "Ainda não sei: o endereço do imóvel." in msg["texto"]
    assert msg["texto"].endswith("Quer me explicar mais alguma coisa sobre este caso antes de eu começar?")
    ctx = C.obter(cid)["contexto"]
    assert ctx["entendimento_status"] == "aguardando" and ctx["modalidade_sugerida"] == "AM"
    assert "modalidade" not in ctx and "finalidade" not in ctx            # sugere, mas não decide
    assert ctx["solicitante_nome"] == "Maria Teste"
    assert st["etapas"][0] == {"etapa": "proposta", "status": "falta", "falta": ["confirmar o que o JdB entendeu do caso"]}
    assert "Cliente Maria, ITCMD" in ia_falsa[0][1]


def test_quero_explicar_mais_refaz_o_resumo(ia_falsa):
    cid = C.criar("")
    asyncio.run(R.nova_mensagem(cid, R.Entrada(texto="primeira", tipo="texto"), _u={}))
    asyncio.run(R.nova_mensagem(cid, R.Entrada(texto="na verdade o processo é na Sefaz", tipo="texto"), _u={}))
    assert len([m for m in C.mensagens(cid) if m["tipo"] == "entendimento"]) == 2
    assert "primeira" in ia_falsa[1][1] and "na verdade o processo é na Sefaz" in ia_falsa[1][1]   # lê tudo de novo


def test_e_isso_pode_comecar(ia_falsa):
    cid = C.criar("")
    asyncio.run(R.nova_mensagem(cid, R.Entrada(texto="caso", tipo="texto"), _u={}))
    with pytest.raises(HTTPException):                                     # sem confirmar, não abre o trabalho
        asyncio.run(R.seguir_para_laudo(cid, _u={}))
    st = asyncio.run(R.confirmar_entendimento(cid, _u={}))
    ctx = C.obter(cid)["contexto"]
    assert ctx["entendimento_status"] == "confirmado" and ctx["modalidade"] == "AM" and ctx["finalidade"] == "ITCMD"
    assert ctx["entendimento"].startswith("Entendi: a Maria")
    assert "É isso?" not in ctx["entendimento"] and "Quer me explicar" not in ctx["entendimento"]
    assert st["etapas"][0]["status"] == "revisar"                          # só agora a proposta para revisar
    assert "Nada foi enviado ao cliente" in st["mensagens"][-2]["texto"]
    assert st["mensagens"][-1]["texto"].startswith("Como é ITCD em Goiás")       # 069-B2: as regras, logo no começo
    assert "data da declaração (DITCD)" in st["mensagens"][-1]["texto"] and "gol contra" in st["mensagens"][-1]["texto"]
    with pytest.raises(HTTPException):                                     # não confirma duas vezes
        asyncio.run(R.confirmar_entendimento(cid, _u={}))


def test_cliente_antigo_segue_como_estava():
    cid = C.criar("")
    C.juntar_contexto(cid, {"proposta_status": "aprovada"})
    assert not R.precisa_entender(cid)


def test_montar_texto_completa_o_que_faltar():
    r = E.Resumo(entendi="a Maria quer vender a casa", ainda_nao_sei=["a", "b", "c", "d"])
    t = E.montar_texto(r)
    assert t.startswith("Entendi: a Maria quer vender a casa. É isso?") and "Ainda não sei: a; b; c." in t
