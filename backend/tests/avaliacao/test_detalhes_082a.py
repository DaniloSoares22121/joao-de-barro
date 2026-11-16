"""ORDEM 082-A (1, 2 e 4): o cartão do anúncio traz rua, bairro, lote e se tem foto; o "Corrigir" muda a rua e o lote;
depois de salvar, a resposta diz o que ficou (área e R$/m²) e a média nova."""
import asyncio

from lovable.avaliacao import rotas_amostra as A
from tests.avaliacao.test_amostra_076 import _laudo_pronto


def test_cartao_e_corrigir_com_rua_e_lote():
    jid = _laudo_pronto()
    e0 = A.estado(jid)
    assert e0["refs"]["2"]["area_m2"] == 1600 and "rua" in e0["refs"]["2"] and "lote_m2" in e0["refs"]["2"]
    e1 = asyncio.run(A.corrigir_anuncio(jid, 2, preco="", area_m2="1.700", lote_m2="3000", rua="Rua  VF-21", foto=None, _u={}))
    assert e1["salvo"]["n"] == 2 and e1["salvo"]["area_m2"] == 1700 and e1["salvo"]["lote_m2"] == 3000
    assert e1["salvo"]["rua"] == "Rua VF-21"
    assert e1["salvo"]["unitario"] == round(3_200_000 / 1700, 2)
    assert e1["agora"]["media"] != e0["agora"]["media"]          # a média nova aparece na hora


def test_cartao_mostra_a_pergunta_da_pagina():
    from lovable.avaliacao import db
    jid = _laudo_pronto()
    r = next(x for x in db.candidatos(jid) if x.n == 3)
    db.salvar_candidatos(jid, [r.model_copy(update={"divergencia_pagina": {"area_m2": 290}})])
    assert A.estado(jid)["refs"]["3"]["divergencia"] == {"area_m2": 290}


def test_ultimo_envio_da_extensao_na_tela():
    """086-5: a tela do JdB diz qual anúncio chegou por último pela extensão (e quando)."""
    from lovable.avaliacao import db
    jid = _laudo_pronto()
    db.evento(jid, "pesquisa", "edicao_manual", "anúncio nº 5 completado pelo avaliador (Chrome): foto, dados da página")
    u = A.estado(jid)["ultimo_envio"]
    assert u["n"] == 5 and u["quando"]
