from pathlib import Path

import pymupdf
from PIL import Image

from lovable.avaliacao import imagens

VERMELHO = (224, 0, 0)


def _img(tmp_path: Path, cor=(255, 255, 255)) -> Path:
    p = tmp_path / "orig.png"
    Image.new("RGB", (200, 200), cor).save(p)
    return p


def test_demarcar_contorno_vermelho(tmp_path):
    src = _img(tmp_path)
    out = imagens.demarcar(src, [(50, 50), (150, 50), (150, 150), (50, 150)], tmp_path / "d.png")
    im = Image.open(out).convert("RGB")
    assert im.size == (200, 200)
    assert im.getpixel((100, 50)) == VERMELHO  # borda superior
    assert im.getpixel((50, 100)) == VERMELHO  # borda esquerda
    assert im.getpixel((100, 100)) == (255, 255, 255)  # interior intacto
    assert im.getpixel((5, 5)) == (255, 255, 255)


def test_recortar_tamanho_da_caixa(tmp_path):
    src = _img(tmp_path)
    out = imagens.recortar(src, (20, 30, 120, 90), tmp_path / "r.png")
    assert Image.open(out).size == (100, 60)


def test_tarjar_pixels_pretos(tmp_path):
    src = _img(tmp_path)
    out = imagens.tarjar(src, [(10, 10, 60, 40), (100, 100, 150, 150)], tmp_path / "t.png")
    im = Image.open(out).convert("RGB")
    assert im.getpixel((30, 20)) == (0, 0, 0)
    assert im.getpixel((120, 120)) == (0, 0, 0)
    assert im.getpixel((80, 80)) == (255, 255, 255)


def test_exif_orientation_preservada(tmp_path):
    p = tmp_path / "exif.jpg"
    im = Image.new("RGB", (200, 100), (255, 255, 255))
    exif = im.getexif()
    exif[0x0112] = 6  # rotacionar 90 graus
    im.save(p, exif=exif)
    out = imagens.recortar(p, (0, 0, 100, 200), tmp_path / "e.png")
    assert Image.open(out).size == (100, 200)


def test_pdf_paginas_png(tmp_path):
    pdf = tmp_path / "t.pdf"
    doc = pymupdf.open()
    for i in range(2):
        doc.new_page().insert_text((72, 72), f"pagina {i}")
    doc.save(pdf)
    doc.close()
    pngs = imagens.pdf_paginas_png(pdf, tmp_path / "pags")
    assert len(pngs) == 2
    assert all(p.exists() and p.suffix == ".png" for p in pngs)
    assert Image.open(pngs[0]).size[0] > 0
