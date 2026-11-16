"""090: um gerador só para a comparação D-069; avisos antigos de área desmentidos somem; correção automática é aviso;
o relato do avaliador (vizinhança, estado) cala o revisor; emissão nunca antes da última consulta."""
from datetime import date

from lovable.avaliacao import db, docx_builder, orquestrador as O, pendencias_simples as PS
from lovable.avaliacao.agentes import _comum, revisor
from lovable.avaliacao.modelos import Campo, Referencial
from tests.avaliacao.test_pagina_enviada import _job


def test_contestacao_da_malha_nao_cria_passo_com_numero_errado():
    jid = _job()
    db.salvar_campos(jid, [Campo(nome="itcd_valor_referencia", valor=448335.57, origem="documento", fonte="comunicado")])
    r = PS.classificar(jid, [{"texto": "contestação simulada (D-083), gravidade alta — pág. 10: o laudo de R$ 173.000,00 não discute a "
                                       "referência da malha da SEFAZ. Como reforçar: comparar."}])
    assert not any(c["chave"] == "referencia_malha" for c in r["cards"])
    d069 = [c for c in r["cards"] if c["chave"] == "comparacao_d069"]
    assert len(d069) == 1 and "448.335,57" in d069[0]["titulo"] and "173.000" not in d069[0]["titulo"]
    db.salvar_candidatos(jid, [Referencial(n=7, link="https://x/7", portal="p", bairro="b", tipologia="Casa", padrao="",
                                           idade_aparente="", descricao="", preco=240000, area_m2=125, decisao="comparacao")])
    assert not any(c["chave"] == "comparacao_d069" for c in PS.classificar(jid, [])["cards"])


def test_area_do_cartao_antiga_e_bairro_padronizado():
    jid = _job()
    r = PS.classificar(jid, [{"texto": "pesquisa: anúncio nº 2: área do cartão (110,00 m²) diferente da construída no texto do anúncio "
                                       "(290,00 m²): o R$/m² usa a do texto"},
                             {"texto": "orquestrador: bairro padronizado: \"Jardim Curitiba I\" → \"Jardim Curitiba\" (o nome do título/IPTU)"}])
    assert r["cards"] == []
    assert not any("cartão" in a for a in r["avisos"]) and any("padronizado" in a for a in r["avisos"])


def test_relato_cala_o_revisor_na_vizinhanca_e_no_estado():
    T = {"vizinhanca", "estado"}
    assert revisor.contra_decisao("Os itens 7.1 e 8 falam das casas de festas. Nenhum campo da extração traz isso.", T) == "vizinhanca"
    assert revisor.contra_decisao("O estado 'Entre regular e reparos simples' não bate com o que a extração registrou.", T) == "estado"


def test_comparativo_sem_localizacao_repetida():
    assert docx_builder._sem_localizacao("Casa de 2 quartos. Localização: Rua JC-18. Boa área.") == "Casa de 2 quartos. Boa área."


def test_emissao_anterior_a_ultima_consulta_e_limpa():
    jid = _job()
    t = _comum.trabalho(jid)
    db.atualizar_dados(jid, t.model_copy(update={"data_emissao": date(2026, 11, 14)}))
    db.salvar_candidatos(jid, [Referencial(n=1, link="https://x/1", portal="p", bairro="b", tipologia="Casa", padrao="",
                                           idade_aparente="", descricao="", preco=1, area_m2=1, escolhido=True,
                                           acessado_em="2026-11-15T01:02:00-03:00")])
    assert O.limpar_emissao_velha(jid) and _comum.trabalho(jid).data_emissao is None
    assert not O.limpar_emissao_velha(jid)
