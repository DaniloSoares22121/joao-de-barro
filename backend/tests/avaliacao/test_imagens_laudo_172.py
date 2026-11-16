"""172-3: mapa e capa aprovados antes da montagem — o contorno desenhado pelo avaliador é o que a montagem usa (e só
na mesma imagem); [Aprovar a imagem]; [Refazer o mapa] que falha mantém; [Baixar a imagem] só da lista."""
import asyncio
import random

import pytest
from PIL import Image

from lovable.avaliacao import db, imagens_laudo
from tests.avaliacao.test_pagina_enviada import _job


def _ruido(p, w, h, semente=1):
    r = random.Random(semente)
    im = Image.new("RGB", (w, h))
    im.putdata([(r.randrange(256), r.randrange(256), r.randrange(256)) for _ in range(w * h)])
    p.parent.mkdir(parents=True, exist_ok=True)
    im.save(p)


def _trabalho():
    jid = _job()
    pasta = db.pasta(jid)
    _ruido(pasta / "maps.png", 600, 420)
    db.evento(jid, "localizacao", "resultado", "teste", dados={"poligono": [[280, 180], [330, 180], [330, 230], [280, 230]]})
    _ruido(pasta / "foto" / "fachada.jpg", 400, 300, 2)
    db.evento(jid, "extracao", "resultado", "teste", dados={"fotos": [{"arquivo": "foto/fachada.jpg", "ordem": 1, "legenda": "Fachada"}]})
    db.evento(jid, "fachada", "resultado", "teste", dados={"arquivo": "foto/fachada.jpg", "poligono": [[100, 80], [300, 80], [300, 220], [100, 220]]})
    return jid


def test_previa_ajuste_aprovacao_e_montagem_usa_o_contorno():
    jid = _trabalho()
    e = imagens_laudo.estado(jid)
    assert e["mapa"]["existe"] and e["capa"]["existe"] and not e["mapa"]["do_avaliador"] and e["mapa"]["aprovada_em"] is None
    info = imagens_laudo.info(jid, "mapa")
    assert info["forma"] == "retangulo" and len(info["contorno"]) == 4
    pts = [[10, 10], [60, 10], [60, 50], [10, 50]]
    imagens_laudo.ajustar(jid, "mapa", pts)
    assert imagens_laudo.contorno_do_avaliador(jid, "mapa", imagens_laudo.chave_mapa(jid)) == [tuple(p) for p in pts]
    assert imagens_laudo.estado(jid)["mapa"]["do_avaliador"] is True
    assert imagens_laudo.aprovar(jid, "mapa")["aprovada_em"]
    assert imagens_laudo.estado(jid)["mapa"]["aprovada_em"]
    # mapa novo (outra captura): o contorno antigo e a aprovação não valem mais
    _ruido(db.pasta(jid) / "maps.png", 600, 420, 9)
    assert imagens_laudo.contorno_do_avaliador(jid, "mapa", imagens_laudo.chave_mapa(jid)) is None
    assert imagens_laudo.estado(jid)["mapa"]["aprovada_em"] is None


def test_capa_contorno_livre_vale_so_para_a_mesma_foto():
    jid = _trabalho()
    imagens_laudo.estado(jid)
    livre = [[20, 20], [120, 15], [160, 90], [40, 120]]
    imagens_laudo.ajustar(jid, "capa", livre)
    contorno = [[100, 80], [300, 80], [300, 220], [100, 220]]
    assert imagens_laudo.contorno_do_avaliador(jid, "capa", imagens_laudo.chave_capa("foto/fachada.jpg", contorno))
    assert imagens_laudo.contorno_do_avaliador(jid, "capa", imagens_laudo.chave_capa("foto/outra.jpg", contorno)) is None


def test_ajuste_sem_pontos_e_refazer_que_falha(monkeypatch):
    jid = _trabalho()
    imagens_laudo.estado(jid)
    with pytest.raises(ValueError):
        imagens_laudo.ajustar(jid, "mapa", [[1, 1]])
    from lovable.avaliacao import imagens_pedido

    async def falha(j, pedido=""):
        return {"ok": False, "motivo": "programa do mapa desligado"}
    monkeypatch.setattr(imagens_pedido, "refazer_demarcacao", falha)
    r = asyncio.run(imagens_laudo.refazer_mapa(jid))
    assert not r["ok"] and r["motivo"].startswith("Mantive o mapa atual")


def test_sem_mapa_diz_por_que():
    jid = _job()
    e = imagens_laudo.estado(jid)
    assert not e["mapa"]["existe"] and "Refazer o mapa" in e["mapa"]["motivo"]
    assert not e["capa"]["existe"]


def test_baixar_a_imagem_so_da_lista():
    jid = _trabalho()
    imagens_laudo.estado(jid)
    ids = [x["id"] for x in imagens_laudo.lista(jid)]
    assert ids == ["capa", "capa_limpa", "mapa", "mapa_limpa", "foto1"]
    assert imagens_laudo.miniatura(jid, "foto1", 120)[:2] == bytes([0xFF, 0xD8])
    dados, tipo, nome = imagens_laudo.baixar(jid, "foto1")
    assert tipo == "image/jpeg" and nome == "fachada.jpg" and dados[:2] == b"\xff\xd8"
    assert imagens_laudo.baixar(jid, "mapa")[2] == "mapa.png"
    assert imagens_laudo.baixar(jid, "mapa_limpa")[2] == "mapa_limpa.png"
    for ruim in ("../app.db", "foto9", "x"):
        with pytest.raises(LookupError):
            imagens_laudo.baixar(jid, ruim)


def test_refazer_que_falha_devolve_o_mapa_de_antes(monkeypatch):
    jid = _trabalho()
    antes = (db.pasta(jid) / "maps.png").read_bytes()
    from lovable.avaliacao import imagens_pedido

    async def estraga(j, pedido=""):
        _ruido(db.pasta(j) / "maps.png", 600, 420, 77)          # a captura grava o arquivo e depois falha
        return {"ok": False, "motivo": "o Google Maps não desenhou o mapa agora"}
    monkeypatch.setattr(imagens_pedido, "refazer_demarcacao", estraga)
    r = asyncio.run(imagens_laudo.refazer_mapa(jid))
    assert not r["ok"] and (db.pasta(jid) / "maps.png").read_bytes() == antes


def test_aprovacao_cai_se_o_contorno_mudar_e_o_anterior_fica_guardado():
    jid = _trabalho()
    imagens_laudo.estado(jid)
    imagens_laudo.ajustar(jid, "mapa", [[10, 10], [60, 10], [60, 50], [10, 50]])
    imagens_laudo.aprovar(jid, "mapa")
    assert imagens_laudo.estado(jid)["mapa"]["aprovada_em"]
    imagens_laudo.ajustar(jid, "mapa", [[20, 20], [80, 20], [80, 70], [20, 70]])
    assert imagens_laudo.estado(jid)["mapa"]["aprovada_em"] is None
    assert list((db.pasta(jid) / "revisoes").glob("contorno-mapa-*.json"))


def test_montando_nao_mexe(monkeypatch):
    jid = _trabalho()
    from lovable.avaliacao import orquestrador
    monkeypatch.setattr(orquestrador, "ocupado", lambda j: True)
    with pytest.raises(RuntimeError):
        imagens_laudo.ajustar(jid, "mapa", [[10, 10], [60, 10], [60, 50]])
    with pytest.raises(RuntimeError):
        asyncio.run(imagens_laudo.refazer_mapa(jid))


def test_capa_foto_inteira_grava_a_previa_limpa():
    jid = _trabalho()
    db.evento(jid, "fachada", "resultado", "teste", dados={"arquivo": "foto/fachada.jpg", "poligono": [[2, 2], [398, 2], [398, 298], [2, 298]]})
    e = imagens_laudo.estado(jid)
    assert e["capa"]["existe"] and (db.pasta(jid) / "_laudo" / "previa_capa_limpa.jpg").is_file()


def test_foto_nova_aparece_na_lista():
    jid = _trabalho()
    _ruido(db.pasta(jid) / "foto" / "nova.jpg", 200, 150, 5)
    _ruido(db.pasta(jid) / "foto" / "fora.jpg", 200, 150, 6)
    db.adicionar_arquivo(jid, "fora.jpg", "foto", "foto/fora.jpg")      # ficou fora do laudo: não é "nova"
    db.adicionar_arquivo(jid, "nova.jpg", "foto", "foto/nova.jpg")
    assert not [x for x in imagens_laudo.lista(jid) if x.get("nova")]   # sem foto chegada depois: nada de "nova"
    db.set_setting(f"fotos_novas:{jid}", "1")
    imagens_laudo.estado(jid)
    novas = [x for x in imagens_laudo.lista(jid) if x.get("nova")]
    assert [x["arquivo"] for x in novas] == ["nova.jpg"]
    assert imagens_laudo.baixar(jid, novas[0]["id"])[2] == "nova.jpg"
