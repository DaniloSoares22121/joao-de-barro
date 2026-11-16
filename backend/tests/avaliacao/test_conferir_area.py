"""ORDEM 034-1 / F-S003: área do cartão do portal x área construída do texto do anúncio."""
import asyncio

from lovable.avaliacao import candidatos as C
from lovable.avaliacao import db, routes
from lovable.avaliacao.agentes import leitor_anuncio
from lovable.avaliacao.modelos import Referencial
from tests.avaliacao.test_pagina_enviada import ZAP, _job


def test_cartao_com_area_do_terreno():
    m = C.conferir_area(1650, 1061.39, 1650)
    assert "1.650" in m and "1.061,39" in m and "TERRENO" in m


def test_contraditorio_sem_terreno_igual():
    m = C.conferir_area(3400, 2400, 11840)
    assert m and "TERRENO" not in m


def test_iguais_ou_sem_dado_nao_avisa():
    assert C.conferir_area(1300, 1300, 3887.59) == ""
    assert C.conferir_area(1040, 1060, None) == ""        # 2%: arredondamento
    assert C.conferir_area(None, 1000) == "" and C.conferir_area(1000, None) == ""


def test_extensao_completa_e_avisa(monkeypatch):
    jid = _job()
    link = f"{ZAP}venda-galpao-real-grandeza-1650m2-id-1/"
    db.salvar_candidatos(jid, [Referencial(
        n=1, link=link, portal="ZAP Imóveis", bairro="Real Grandeza", tipologia="Galpão", padrao="",
        idade_aparente="", area_m2=1650, preco=5_100_000, escolhido=True, decisao="entra", descricao="")])

    async def leitor(job_id, captura, portal, comuns=frozenset()):
        return Referencial(n=0, link=captura.url_final, portal=portal, bairro="", tipologia="", padrao="",
                           idade_aparente="", area_m2=1061.39, lote_m2=1650, preco=5_100_000, descricao="")
    monkeypatch.setattr(leitor_anuncio, "ler", leitor)
    body = routes.AnuncioEnviado(link=link, texto="Galpão com 1.061,39 m² construídos em terreno de 1.650 m²")
    asyncio.run(routes.anuncio_enviado(jid, body, _u={}))
    c = db.candidatos(jid)[0]
    # 082-2: o guardado não muda sozinho; a área do texto vira pergunta, com o aviso do terreno
    assert c.area_m2 == 1650 and c.divergencia_pagina == {"area_m2": 1061.39} and "TERRENO" in c.observacao
    with db._conn() as cc:
        av = [x[0] for x in cc.execute("SELECT msg FROM av_events WHERE job=? AND nivel='aviso'", (jid,))]
    assert any("área do cartão" in x for x in av)
