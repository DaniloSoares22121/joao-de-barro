"""167-1: [Ajustar a demarcação] — o contorno desenhado pelo avaliador refaz a imagem demarcada e troca a figura no
Word editável, do mesmo tamanho; [Refazer o mapa] que falha mantém o mapa atual."""
import asyncio
import io

import pytest
from docx import Document
from docx.oxml.ns import qn
from PIL import Image

from lovable.avaliacao import db, editavel, editavel_imagem
from tests.avaliacao.test_pagina_enviada import _job


def _png(cor, w=300, h=200):
    b = io.BytesIO()
    Image.new("RGB", (w, h), cor).save(b, "PNG")
    b.seek(0)
    return b


def _laudo_com_mapa(jid):
    f = editavel._finais(jid)
    f["docx"].parent.mkdir(parents=True, exist_ok=True)
    d = Document()
    d.add_paragraph("Localização do imóvel.")
    d.add_paragraph().add_run().add_picture(_png((0, 128, 0)))
    d.add_paragraph("Imagem 02 – Localização do imóvel avaliando.")
    d.save(f["docx"])
    pasta = db.pasta(jid) / "_laudo"
    pasta.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (300, 200), (0, 128, 0)).save(pasta / "mapa_recorte.png")
    return f


def _figura(jid):
    d = Document(str(editavel.caminho(jid)))
    p = d.paragraphs[1]
    blip = p._p.find(f".//{{http://schemas.openxmlformats.org/drawingml/2006/main}}blip")
    parte = d.part.related_parts[blip.get(qn("r:embed"))]
    ext = p._p.find(f".//{{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}}extent")
    return Image.open(io.BytesIO(parte.blob)).convert("RGB"), (ext.get("cx"), ext.get("cy"))


def test_documento_marca_o_mapa_e_ajustar_troca_a_figura():
    jid = _job()
    _laudo_com_mapa(jid)
    doc = editavel.documento(jid)
    pid = doc["blocos"][1]["id"]
    assert doc["demarcaveis"] == {str(pid): "mapa"}
    info = editavel_imagem.limpa(jid, "mapa")
    assert info["largura"] == 300 and info["forma"] == "retangulo"
    _antes, tam = _figura(jid)
    r = editavel_imagem.ajustar(jid, "mapa", [[50, 40], [250, 40], [250, 160], [50, 160]])
    assert r["ok"] and r["id"] == pid
    img, tam2 = _figura(jid)
    assert tam2 == tam                                   # do mesmo tamanho no Word
    x, y = int(50 * img.width / 300), int(100 * img.height / 200)
    px = img.getpixel((x, y))
    assert px[0] > 180 and px[1] < 90                    # a linha vermelha passou ali
    assert img.getpixel((img.width // 2, img.height // 2))[1] > 100   # o meio continua o mapa


def test_ajustar_pede_contorno_de_verdade():
    jid = _job()
    _laudo_com_mapa(jid)
    editavel.documento(jid)
    with pytest.raises(ValueError):
        editavel_imagem.ajustar(jid, "mapa", [[1, 1], [2, 2]])
    with pytest.raises(LookupError):
        editavel_imagem.ajustar(jid, "capa", [[1, 1], [2, 2], [3, 1]])   # sem capa limpa guardada


def test_refazer_mapa_que_falha_mantem_o_atual(monkeypatch):
    jid = _job()
    _laudo_com_mapa(jid)
    editavel.documento(jid)
    from lovable.avaliacao import imagens_pedido

    async def falha(j, pedido=""):
        return {"ok": False, "motivo": "programa do mapa desligado"}
    monkeypatch.setattr(imagens_pedido, "refazer_demarcacao", falha)
    antes, _t = _figura(jid)
    r = asyncio.run(editavel_imagem.refazer_mapa(jid))
    assert not r["ok"] and "Mantive o mapa atual" in r["motivo"] and "desligado" in r["motivo"]
    depois, _t = _figura(jid)
    assert list(antes.getdata())[:50] == list(depois.getdata())[:50]
