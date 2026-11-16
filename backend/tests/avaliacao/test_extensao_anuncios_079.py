"""ORDEM 079-1: a lista que a extensão abre ("Abrir os anúncios") e a contagem "N de 6 recebidos"."""
import asyncio

from lovable.avaliacao import db, rotas_extensao as X
from lovable.avaliacao.modelos import Referencial
from tests.avaliacao.test_pagina_enviada import ZAP, _job


def _ref(n, **kw):
    base = dict(n=n, link=f"{ZAP}casa-{n}/", portal="ZAP Imóveis", bairro="Centro", tipologia="Casa", padrao="",
                idade_aparente="", descricao="", preco=300_000, area_m2=150)
    return Referencial(**{**base, **kw})


def test_so_os_anuncios_do_laudo_sem_foto_ou_data_entram_na_lista():
    jid = _job()
    db.salvar_candidatos(jid, [
        _ref(1, decisao="entra", foto="f1.jpg", acessado_em="2026-11-14T22:00:00-03:00"),   # recebido
        _ref(2, decisao="entra", foto="f2.jpg"),                                           # sem data de acesso
        _ref(3, escolhido=True),                                                           # sem foto
        _ref(4, decisao="descarta"),                                                       # fora do laudo
        _ref(5, decisao="entra", link="(anúncio sem endereço)"),                           # sem link: não abre
    ])
    r = asyncio.run(X.ver_anuncios(jid, _u={}))
    assert r["total"] == 4 and r["recebidos"] == 1
    assert [a["n"] for a in r["faltam"]] == [2, 3]
    assert r["sem_link"] == [5]
