"""085-1 (GRAVE): no 9121 o avaliador escreveu "Data da DITCD 28/10/2026 (data-base)" e o laudo saiu com a data da
vistoria (13/11/2026). A DITCD vai para o trabalho; laudo de ITCD sem ela não começa (o portão pergunta)."""
import pytest

from lovable.avaliacao import conversa as C, portoes


def test_117_d127_data_do_laudo_e_a_da_vistoria_mesmo_com_ditcd():
    """117 / D-127 (troca a 085-1): a DITCD é só fato do processo; a data de referência do laudo é a da vistoria."""
    cid = C.criar("")
    C.juntar_contexto(cid, {"finalidade": "ITCD – justificar o valor declarado na malha fiscal", "visita": "2026-11-13T09:00",
                            "data_ditcd": "2026-10-28"})
    ctx = C.obter(cid)["contexto"]
    assert C.trabalho_do_contexto(ctx, 9121)["data_base"] == "2026-11-13"


def test_117_itcd_nao_pergunta_data_base():
    cid = C.criar("")
    C.juntar_contexto(cid, {"finalidade": "ITCD – malha fiscal", "visita": "2026-11-13T09:00"})
    g = portoes.montar(cid, "visita")
    assert not any(x["id"] == "data_base" for x in g["perguntas"])
    assert C.trabalho_do_contexto(C.obter(cid)["contexto"], 1)["data_base"] == "2026-11-13"


def test_venda_sem_ditcd_nao_pergunta():
    cid = C.criar("")
    C.juntar_contexto(cid, {"finalidade": "Venda", "visita": "2026-11-13T09:00"})
    assert not any(x["id"] == "data_base" for x in portoes.montar(cid, "visita")["perguntas"])


def test_117_trabalho_com_outra_data_volta_para_a_da_vistoria(monkeypatch):
    from datetime import date
    from lovable.avaliacao import db, orquestrador as O
    from lovable.avaliacao.agentes import _comum
    from tests.avaliacao.test_pagina_enviada import _job
    jid = _job()
    t = _comum.trabalho(jid)
    db.atualizar_dados(jid, t.model_copy(update={"data_base": date(2026, 10, 28)}))
    assert O.corrigir_data_base(jid)
    assert _comum.trabalho(jid).data_base == _comum.trabalho(jid).data_vistoria
    assert not O.corrigir_data_base(jid)                      # já certa: não mexe de novo


def test_086_7_dispersao_confirmada_no_valor_vira_decisao():
    from lovable.avaliacao import pendencias_simples as PS
    assert PS._tema(PS._n("amostra dispersa: coeficiente de variação de 39,6% (acima de 15%)")) == "cv"


def test_117_d131_bairro_com_o_nome_completo_do_documento():
    """117 / D-131 (troca a 088-3): "Jardim Curitiba I" da conta de água vale sobre "Jardim Curitiba"."""
    from lovable.avaliacao import db, orquestrador as O
    from lovable.avaliacao.agentes import _comum
    from lovable.avaliacao.modelos import Campo
    from tests.avaliacao.test_pagina_enviada import _job
    jid = _job()
    t = _comum.trabalho(jid)
    db.atualizar_dados(jid, t.model_copy(update={"bairro": "Jardim Curitiba"}))
    db.salvar_campos(jid, [Campo(nome="bairro", valor="Jardim Curitiba", origem="documento", fonte="documento/Escritura.pdf#p2"),
                           Campo(nome="comprovante_endereco", valor="Fatura Saneago, Jardim Curitiba I", origem="documento",
                                 fonte="documento/COMPROVANTE.pdf#p1")])
    assert O.padronizar_bairro(jid) and _comum.trabalho(jid).bairro == "Jardim Curitiba I"
    assert not O.padronizar_bairro(jid)
    db.atualizar_dados(jid, _comum.trabalho(jid).model_copy(update={"bairro": "Setor Oeste"}))
    assert not O.padronizar_bairro(jid)                      # nome diferente de verdade: não troca sozinho


def test_099_1_relato_que_dispensa_proposta_nao_pula_o_entendimento():
    from lovable.avaliacao import rotas_conversa as RC
    cid = C.criar("")
    C.juntar_contexto(cid, {"proposta_status": "fora", "visita_feita": True})
    assert RC.precisa_entender(cid)                         # "fora" pelo relato não dispensa o entendimento
    falta = C.falta_para_montar(C.obter(cid)["contexto"])
    assert any("imóvel" in f for f in falta) and any("modalidade" in f for f in falta) and any("finalidade" in f for f in falta)
    C.juntar_contexto(cid, {"imovel_tipo": "Casa", "modalidade": "AM", "finalidade": "ITCD – malha fiscal"})
    assert C.falta_para_montar(C.obter(cid)["contexto"]) == []


def test_100_4_contrato_assinado_pelo_relato_nao_pede_revisao():
    cid = C.criar("")
    C.juntar_contexto(cid, {"proposta_status": "fora", "contrato_assinado_relato": True})
    et = {e["etapa"]: e for e in C.etapas(C.obter(cid))}
    assert et["contrato"]["status"] == "feito" and not et["contrato"]["falta"]
