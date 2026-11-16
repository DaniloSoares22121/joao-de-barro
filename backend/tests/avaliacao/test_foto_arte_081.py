"""ORDEM 081-5: a 1ª imagem do anúncio nº 4 (Rua VF-9) era um banner "À VENDA – Casa Escriturada… R$ 180.000".
O JdB percebe, sugere a próxima foto da galeria ([Usar] [Manter]) e cada referencial tem [Trocar foto]."""
import asyncio

import pytest
from fastapi import HTTPException

from lovable.avaliacao import db, pendencias_simples as PS, routes
from lovable.avaliacao.agentes import leitor_anuncio
from tests.avaliacao.test_enviado_mesmo_link_077 import ENVIADOS, PNG, _manuais
from tests.avaliacao.test_pagina_enviada import _job

GALERIA = ["https://resizedimgs.exemplo.com/foto-1.jpg", "https://resizedimgs.exemplo.com/fachada.jpg",
           "https://resizedimgs.exemplo.com/sala.jpg"]


def test_foto_arte_vira_card_e_troca(monkeypatch):
    jid = _job()
    _manuais(jid)

    async def sem_ia(*a, **k):
        return None

    async def arte(j, rel):
        return True

    async def baixar(url):
        return b"\xff\xd8\xff fachada", "jpg"
    monkeypatch.setattr(leitor_anuncio, "ler", sem_ia)
    monkeypatch.setattr(routes, "_foto_e_arte", arte)
    monkeypatch.setattr(routes, "_baixar_imagem", baixar)
    n, link = ENVIADOS[1]
    body = routes.AnuncioEnviado(link=link, titulo="Casa", texto="Casa", imagem=PNG, foto_principal=PNG,
                                 acessado_em="2026-11-15T02:20:00Z", fotos_url=GALERIA + ["javascript:alert(1)"])
    asyncio.run(routes.anuncio_enviado(jid, body, _u={}))
    c = next(x for x in db.candidatos(jid) if x.n == n)
    assert c.fotos_url == GALERIA and c.foto_arte
    for x in db.candidatos(jid):                         # o anúncio entra no laudo
        if x.n == n:
            db.salvar_candidatos(jid, [x.model_copy(update={"decisao": "entra"})])
    cards = PS.classificar(jid, [])["cards"]
    card = next(k for k in cards if k["chave"] == f"foto_arte:{n}")
    assert "arte de anúncio" in card["titulo"] and card["imagem"] == GALERIA[1]
    assert [o["rotulo"] for o in card["opcoes"]] == ["Usar a sugerida", "Manter"]
    assert card["galeria"]["fotos"] == GALERIA[1:]
    with pytest.raises(HTTPException) as e:              # só foto do próprio anúncio
        asyncio.run(routes.trocar_foto(jid, n, routes.TrocarFoto(url="https://outro.site/x.jpg"), _u={}))
    assert e.value.status_code == 400
    antes = c.foto
    r = asyncio.run(routes.trocar_foto(jid, n, routes.TrocarFoto(url=GALERIA[1]), _u={}))
    c2 = next(x for x in db.candidatos(jid) if x.n == n)
    assert c2.foto == r["foto"] != antes and not c2.foto_arte
    assert (db.pasta(jid) / c2.foto).read_bytes().endswith(b"fachada")
    assert (db.pasta(jid) / antes).is_file()             # a foto de antes fica guardada
    assert not any(k["chave"] == f"foto_arte:{n}" for k in PS.classificar(jid, [])["cards"])


def test_manter_tira_o_aviso(monkeypatch):
    jid = _job()
    _manuais(jid)
    n = db.candidatos(jid)[0].n
    db.salvar_candidatos(jid, [db.candidatos(jid)[0].model_copy(update={"foto_arte": True, "fotos_url": GALERIA, "decisao": "entra"})])
    asyncio.run(routes.trocar_foto(jid, n, routes.TrocarFoto(manter=True), _u={}))
    assert not next(x for x in db.candidatos(jid) if x.n == n).foto_arte


def test_088_1_sugerida_que_tambem_e_arte_pula_para_a_proxima(monkeypatch):
    jid = _job()
    _manuais(jid)
    n = db.candidatos(jid)[0].n
    db.salvar_candidatos(jid, [db.candidatos(jid)[0].model_copy(update={"foto_arte": True, "fotos_url": GALERIA, "decisao": "entra"})])
    vistos = []

    async def baixar(url):
        vistos.append(url)
        return (b"arte" if "fachada" in url else b"casa"), "jpg"

    async def arte(j, rel):
        return (db.pasta(j) / rel).read_bytes() == b"arte"
    monkeypatch.setattr(routes, "_baixar_imagem", baixar)
    monkeypatch.setattr(routes, "_foto_e_arte", arte)
    r = asyncio.run(routes.trocar_foto(jid, n, routes.TrocarFoto(url=GALERIA[1], sugerida=True), _u={}))
    assert vistos == GALERIA[1:3] and (db.pasta(jid) / r["foto"]).read_bytes() == b"casa"
