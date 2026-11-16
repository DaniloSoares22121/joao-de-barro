"""138: o avaliador corrige direto numa cópia editável; [Usar este documento] gera o PDF e roda só a conferência por regra."""
import pytest
from docx import Document

from lovable.avaliacao import db, editavel
from lovable.avaliacao.planilha import soffice_path
from tests.avaliacao.test_pagina_enviada import _job


def _laudo(jid):
    f = editavel._finais(jid)
    f["docx"].parent.mkdir(parents=True, exist_ok=True)
    d = Document()
    d.add_paragraph("LAUDO DE TESTE")
    d.add_paragraph("O valor de mercado do imóvel avaliando, na data-base da avaliação, é de R$ 100.000,00.")
    d.save(f["docx"])
    return f


def test_abrir_cria_a_copia_uma_vez_e_nao_toca_no_original():
    jid = _job()
    f = _laudo(jid)
    antes = f["docx"].read_bytes()
    r = editavel.abrir(jid)
    assert r["criado"] and r["existe"] and not r["alterado"] and r["aberto"] is False      # nos testes não abre na tela
    assert editavel.caminho(jid).read_bytes() == antes
    assert editavel.abrir(jid)["criado"] is False                                              # reabre a mesma cópia
    assert f["docx"].read_bytes() == antes


def test_sem_copia_usar_pede_para_abrir():
    jid = _job()
    _laudo(jid)
    with pytest.raises(ValueError, match="Abrir o laudo editável"):
        editavel.usar(jid)


@pytest.mark.skipif(soffice_path() is None, reason="sem LibreOffice")
def test_usar_gera_o_pdf_e_confere_por_regra():
    jid = _job()
    f = _laudo(jid)
    editavel.abrir(jid)
    c = editavel.caminho(jid)
    d = Document(str(c))
    d.add_paragraph("Parágrafo acrescentado pelo avaliador no editável.")
    d.save(str(c))
    r = editavel.usar(jid)
    assert f["pdf"].is_file() and r["pdf"] == f["pdf"].name
    import pymupdf
    with pymupdf.open(f["pdf"]) as p:
        txt = " ".join(pg.get_text() for pg in p)
    assert "acrescentado pelo avaliador" in txt
    assert (db.pasta(jid) / "revisoes" / r["guardado_em"]).is_dir()
    assert isinstance(r["diferencas"], list)
