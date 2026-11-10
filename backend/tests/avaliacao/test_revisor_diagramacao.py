"""Camada visual determinística do revisor (pymupdf sobre PDFs gerados)."""
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from lovable.avaliacao import db, docx_builder, pdf, planilha
from lovable.avaliacao.agentes import revisor
from lovable.avaliacao.modelos import Campo

from . import test_docx as T


def _pdf(tmp: Path, paginas: list[tuple[list[str], int]]) -> Path:
    """PDF com cabeçalho/rodapé repetidos; cada página = (linhas, nº de fotos)."""
    img = tmp / "f.png"
    Image.new("RGB", (40, 30), "green").save(img)
    out = tmp / "laudo.pdf"
    with pymupdf.open() as d:
        for k, (linhas, fotos) in enumerate(paginas, start=1):
            pg = d.new_page()
            pg.insert_text((40, 30), "Opinião Profissional de Valor N.º 120", fontsize=8)
            y = 60
            for ln in linhas:
                if ln == "<FOTO>":
                    pg.insert_image(pymupdf.Rect(40, y, 120, y + 50), filename=str(img))
                    y += 60
                    continue
                pg.insert_text((40, y), ln, fontsize=9)
                y += 14
            pg.insert_text((40, 820), f"Alan Soares da Silva | Página {k}", fontsize=8)
        d.save(out)
    return out


def _descrs(jid, p):
    return [x.descricao for x in revisor.diagramacao(jid, p)]


def test_diagramacao_aponta_cada_falha(tmp_path):
    texto = "Texto de corpo suficiente para não ser considerado página vazia. " * 4
    p = _pdf(tmp_path, [
        (["1. FINALIDADE DA AVALIAÇÃO", texto, "7.5. Relatório Fotográfico",
          "Foto 01 – Fachada", "<FOTO>", "<FOTO>", "8. PESQUISA DE IMÓVEIS", texto], 0),
        (["Área construída adotada", "n/i", "Tipologia / padrão", "Sobrado / n/i", texto], 0),
        (["curta"], 0),
        (["O presente parecer é composto por 9 páginas, incluindo anexos.", "[PREENCHER: x]",
          "Valor None", texto], 0),
        (["15. SUMÁRIO", "1. FINALIDADE DA AVALIAÇÃO..........3", "8. PESQUISA DE IMÓVEIS....1"],
         0),
    ])
    jid = T._job()[0]
    ds = _descrs(jid, p)
    assert any("página 3 quase vazia" in x for x in ds), ds
    assert any("2 foto(s) e só 1 legenda" in x for x in ds), ds
    assert any("FINALIDADE DA AVALIAÇÃO\" indicado na página 3, está na 1" in x for x in ds), ds
    assert not any("PESQUISA" in x and "sumário" in x for x in ds), ds
    assert any("composto por 9 páginas\" mas o PDF tem 5" in x for x in ds), ds
    assert any("Área construída adotada = n/i" in x for x in ds), ds
    assert any("Tipologia / padrão = n/i" in x for x in ds), ds
    ni = [x for x in revisor.diagramacao(jid, p) if "= n/i" in x.descricao]
    assert ni and all(x.etapa_responsavel == "extracao" for x in ni)
    lixo = [x for x in revisor.diagramacao(jid, p) if "resto de modelo" in x.descricao]
    assert {x.descricao.split(": ", 1)[1] for x in lixo} == {"'[PREENCHER'", "'None'"}
    assert all(x.etapa_responsavel == "montagem" for x in lixo)


def test_resto_de_modelo_vindo_da_redacao_volta_para_redacao(tmp_path):
    jid = T._job()[0]
    db.evento(jid, "redacao", "resultado", "ok",
              dados={"secoes": {"9": "Valor null adotado."}, "legendas": {}})
    p = _pdf(tmp_path, [(["Valor null adotado. " * 10], 0)])
    x = next(x for x in revisor.diagramacao(jid, p) if "resto de modelo" in x.descricao)
    assert x.etapa_responsavel == "redacao"


@pytest.mark.skipif(planilha.soffice_path() is None, reason="LibreOffice ausente")
def test_diagramacao_aprova_laudo_ov120_real():
    jid, sel, r = T._job([Campo(nome="area_terreno", valor=360.0, unidade="m2",
                                origem="documento", fonte="docs/iptu.png")], com_maps=True)
    out = pdf.converter(docx_builder.montar(jid, T._textos(), r, sel))
    assert revisor.diagramacao(jid, out) == []


def _pdf_imagem(tmp: Path, paginas: list[tuple[list[str], float]]) -> Path:
    """Cada página = (linhas, fração da página coberta por uma imagem; 0 = sem imagem)."""
    img = tmp / "g.png"
    Image.new("RGB", (40, 30), "blue").save(img)
    out = tmp / "laudo_img.pdf"
    with pymupdf.open() as d:
        for k, (linhas, frac) in enumerate(paginas, start=1):
            pg = d.new_page()
            pg.insert_text((40, 30), "Opinião Profissional de Valor N.º 120", fontsize=8)
            y = 60
            for ln in linhas:
                pg.insert_text((40, y), ln, fontsize=9)
                y += 14
            if frac:
                w = pg.rect.width
                h = frac * pg.rect.width * pg.rect.height / w
                pg.insert_image(pymupdf.Rect(0, 100, w, 100 + h), filename=str(img),
                                keep_proportion=False)
            pg.insert_text((40, 820), f"Alan Soares da Silva | Página {k}", fontsize=8)
        d.save(out)
    return out


def test_imagem_pequena_nao_isenta_pagina_quase_vazia(tmp_path):
    texto = "Texto de corpo suficiente para não ser considerado página vazia. " * 4
    p = _pdf_imagem(tmp_path, [(_L(texto), 0), (["curta"], 0.05), (["curta"], 0.3),
                               (_L(texto), 0)])
    ds = _descrs(T._job()[0], p)
    assert any("página 2 quase vazia" in x for x in ds), ds
    assert not any("página 3 quase vazia" in x for x in ds), ds


def test_ultima_pagina_com_assinatura_ou_sumario_isenta(tmp_path):
    texto = "Texto de corpo suficiente para não ser considerado página vazia. " * 4
    outro = "Outro parágrafo de corpo, diferente do primeiro, longo o bastante. " * 4
    jid = T._job()[0]
    for fecho in ("14. ASSINATURA", "15. SUMÁRIO"):
        p = _pdf_imagem(tmp_path, [(_L(texto), 0), (_L(outro), 0), ([fecho, "Alan"], 0)])
        assert not any("quase vazia" in x for x in _descrs(jid, p)), fecho
    p = _pdf_imagem(tmp_path, [(_L(texto), 0), (["14. ASSINATURA"], 0), (_L(outro), 0)])
    assert any("página 2 quase vazia" in x for x in _descrs(jid, p))
    p = _pdf_imagem(tmp_path, [(_L(texto), 0), (_L(outro), 0), (["Anexo"], 0)])
    assert any("página 3 quase vazia" in x for x in _descrs(jid, p))


def _L(t: str) -> list[str]:
    """Texto longo em linhas que cabem na página (insert_text não quebra linha)."""
    return [t[i:i + 90] for i in range(0, len(t), 90)]


def test_isencao_foto_nn_exige_foto_de_verdade(tmp_path):
    texto = "Texto de corpo suficiente para não ser considerado página vazia. " * 4
    jid = T._job()[0]
    p = _pdf_imagem(tmp_path, [(_L(texto), 0), (["Foto 07 – Quarto"], 0.01), (_L(texto + "x"), 0)])
    assert any("página 2 quase vazia" in x for x in _descrs(jid, p))     # ícone não isenta
    p = _pdf_imagem(tmp_path, [(_L(texto), 0), (["Foto 07 – Quarto"], 0.05), (_L(texto + "x"), 0)])
    assert not any("página 2 quase vazia" in x for x in _descrs(jid, p))
