"""ORDEM 077-A: as pendências que chegam ao avaliador — uma por assunto; decisão já tomada (CV, amostra) só como
aviso; anúncios sem foto/data num card só, com os links."""
from lovable.avaliacao import pendencias_simples as PS
from tests.avaliacao.test_pagina_enviada import _job

CV = [
    "selecao: revisor (ressalva): o CV da amostra é de 32,9%, acima de 15%.",
    "contestação simulada (D-083), gravidade alta — pág. 9: coeficiente de variação alto. Como reforçar: explicar.",
    "revisor (redação/redação): desvio padrão elevado na amostra (pág. 10).",
]
OUTROS = [
    "revisor (jurídica/extração): divergência de área entre matrícula e IPTU na pág. 4.",
    "revisor (jurídica/extração): divergência de área entre matrícula e IPTU na pág. 9.",
    "referencial 01 sem foto principal do anúncio",
    "referencial 02 sem foto principal do anúncio",
    "referencial 01: data de acesso não registrada (D-082)",
]


def _p(ts):
    return [{"texto": x, "grave": True} for x in ts]


def test_cv_vira_uma_decisao_e_depois_so_aviso():
    jid = _job()
    r = PS.classificar(jid, _p(CV))
    # 106 (D-068, regra do projeto): a dispersão nunca vira passo — já está decidida em todo trabalho
    assert not any(c["chave"] == "decisao:cv" or "coeficiente" in c["titulo"].lower() for c in r["cards"])
    PS.gravar_decisao(jid, "cv", "D-068 / caso 122")
    r = PS.classificar(jid, _p(CV))
    assert not any(c["chave"] == "decisao:cv" or "contestacao" in c["chave"] for c in r["cards"])
    assert sum("Dispersão alta" in a for a in r["avisos"]) == 1


def test_repetidas_viram_uma_e_extensao_um_card():
    jid = _job()
    r = PS.classificar(jid, _p(OUTROS))
    conc = [c for c in r["cards"] if "divergência de área" in c["titulo"].lower()]
    assert len(conc) == 1
    ext = [c for c in r["cards"] if c["chave"] == "extensao"]
    assert len(ext) == 1 and "Enviar ao JdB" in ext[0]["titulo"]
    assert not any("sem foto principal" in c["titulo"] and c["chave"] != "extensao" for c in r["cards"])


def test_077_c1_titulo_nunca_artigo_solto():
    import re
    jid = _job()
    txts = ["Pág. 3, item 6 (Documentação analisada): a P9 pede uma data por documento.", "O K0 exige foto da fachada.",
            "revisor (redação/montagem): A D-057 determina a ordem dos anexos."]
    for c in PS.classificar(jid, [{"texto": t, "grave": True} for t in txts])["cards"]:
        assert not re.match(r"^(?:[AaOo]s?)\s+(?:pede|exige|determina|manda|diz)\b", c["titulo"]), c["titulo"]
