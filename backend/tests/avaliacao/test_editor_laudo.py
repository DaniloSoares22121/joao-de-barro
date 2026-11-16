"""Editor do laudo dentro do sistema: salvar um parágrafo troca só o texto que mudou e mantém a formatação."""
import pytest
from docx import Document
from docx.shared import Pt, RGBColor

from lovable.avaliacao import editavel
from tests.avaliacao.test_pagina_enviada import _job


def _laudo(jid):
    f = editavel._finais(jid)
    f["docx"].parent.mkdir(parents=True, exist_ok=True)
    d = Document()
    p = d.add_paragraph()
    r = p.add_run("Imóvel Avaliado: ")
    r.bold = True
    r.font.size = Pt(12)
    r.font.color.rgb = RGBColor(0x18, 0x28, 0x3B)
    p.add_run("Casa – Rua X, Jardim Curitiba, Goiânia.")
    d.add_paragraph("Segundo parágrafo, sem formatação especial.")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "Área"
    t.cell(0, 1).text = "286,09 m²"
    d.add_paragraph("Último parágrafo.")
    d.save(f["docx"])
    return f


def _blocos(jid):
    return editavel.documento(jid)["blocos"]


def test_documento_traz_paragrafos_tabela_e_formatacao():
    jid = _job()
    _laudo(jid)
    b = _blocos(jid)
    assert [x["t"] for x in b] == ["p", "p", "tab", "p"]
    assert b[0]["runs"][0] == {"x": "Imóvel Avaliado: ", "b": 1, "sz": 12.0, "cor": "18283B"}
    assert b[0]["runs"][1]["x"].startswith("Casa") and "b" not in b[0]["runs"][1]
    cel = b[2]["linhas"][0][1]["ps"][0]
    assert cel["runs"][0]["x"] == "286,09 m²" and cel["id"] == 3 and b[3]["id"] == 4


def test_editar_o_resto_da_frase_mantem_o_rotulo_em_negrito():
    jid = _job()
    f = _laudo(jid)
    original = f["docx"].read_bytes()
    r = editavel.gravar(jid, 0, "Imóvel Avaliado: Casa – Rua X, Jardim Curitiba I, Goiânia.",
                        base="Imóvel Avaliado: Casa – Rua X, Jardim Curitiba, Goiânia.")
    runs = r["bloco"]["runs"]
    assert runs[0] == {"x": "Imóvel Avaliado: ", "b": 1, "sz": 12.0, "cor": "18283B"}
    assert runs[1]["x"] == "Casa – Rua X, Jardim Curitiba I, Goiânia." and "b" not in runs[1]
    assert f["docx"].read_bytes() == original                       # o laudo original não é tocado
    # mexer no rótulo mantém o negrito do rótulo
    r = editavel.gravar(jid, 0, "Imóvel avaliando: Casa – Rua X, Jardim Curitiba I, Goiânia.")
    assert r["bloco"]["runs"][0]["x"] == "Imóvel avaliando: " and r["bloco"]["runs"][0]["b"] == 1
    assert editavel.situacao(jid)["existe"]


def test_celula_de_tabela_conflito_novo_e_apagar():
    jid = _job()
    _laudo(jid)
    editavel.gravar(jid, 3, "286,10 m²", base="286,09 m²")
    assert _blocos(jid)[2]["linhas"][0][1]["ps"][0]["runs"][0]["x"] == "286,10 m²"
    with pytest.raises(LookupError, match="outra janela"):
        editavel.gravar(jid, 3, "300 m²", base="286,09 m²")            # a tela estava com o texto velho
    n = editavel.novo_paragrafo(jid, 1)
    assert n["id"] == 2
    editavel.gravar(jid, 2, "Parágrafo novo do avaliador.")
    textos = ["".join(r["x"] for r in b["runs"]) for b in _blocos(jid) if b["t"] == "p"]
    assert textos == ["Imóvel Avaliado: Casa – Rua X, Jardim Curitiba, Goiânia.", "Segundo parágrafo, sem formatação especial.",
                      "Parágrafo novo do avaliador.", "Último parágrafo."]
    r = editavel.gravar(jid, 2, "")                                    # apagou a frase inteira: a linha some
    assert r["removido"] and len([b for b in _blocos(jid) if b["t"] == "p"]) == 3
    assert editavel.gravar(jid, 3, "")["removido"] is False            # célula de tabela nunca é removida


def test_copia_velha_sem_mudancas_e_atualizada_sozinha():
    """Automático e seguro: o sistema refez o laudo e a cópia não tinha mudanças -> o editor abre o laudo novo."""
    import os
    import time
    jid = _job()
    f = _laudo(jid)
    editavel.documento(jid)
    d = Document(str(f["docx"]))
    d.add_paragraph("Parágrafo que só existe no laudo refeito.")
    d.save(f["docx"])
    depois = time.time() + 10
    os.utime(f["docx"], (depois, depois))
    b = _blocos(jid)
    assert any("laudo refeito" in "".join(r["x"] for r in x.get("runs", [])) for x in b)
    assert editavel.situacao(jid)["laudo_mudou"] is False


def test_copia_com_mudancas_nunca_e_trocada_e_avisa():
    import os
    import time
    jid = _job()
    f = _laudo(jid)
    editavel.documento(jid)
    c = editavel.caminho(jid)
    futuro = time.time() + 5
    editavel.gravar(jid, 1, "Mudança do avaliador.")
    os.utime(c, (futuro, futuro))
    os.utime(f["docx"], (futuro + 10, futuro + 10))
    doc = editavel.documento(jid)
    assert "Mudança do avaliador." in ["".join(r["x"] for r in x.get("runs", [])) for x in doc["blocos"]]
    assert doc["laudo_mudou"] and "refez o laudo" in doc["aviso"]
    s = editavel.descartar(jid)                                      # recomeça do laudo atual, guardando a cópia
    assert not s["alterado"] and not s["laudo_mudou"]


def test_usar_sem_mudanca_avisa_e_nao_refaz():
    jid = _job()
    f = _laudo(jid)
    editavel.documento(jid)
    f["pdf"].write_bytes(b"%PDF-1.4 de antes")
    with pytest.raises(ValueError, match="ainda não mudou nada"):
        editavel.usar(jid)
    assert f["pdf"].read_bytes() == b"%PDF-1.4 de antes"


def test_marcas_de_pagina_seguem_o_pdf(tmp_path):
    """142: a página N do editor é a página N do último PDF (o começo de cada página vira uma marca)."""
    import pymupdf
    pdf = tmp_path / "l.pdf"
    with pymupdf.open() as d:
        for txt in ("Capa do laudo", "1. FINALIDADE DA AVALIAÇÃO", "continuação do texto da finalidade", "10. VALOR DE MERCADO"):
            d.new_page().insert_text((40, 200), txt, fontsize=11)
        d.save(pdf)
    paragrafos = [(0, "Capa do laudo"), (1, "Texto qualquer"), (2, "1. FINALIDADE DA AVALIAÇÃO"),
                  (3, "Parágrafo longo que termina com a continuação do texto da finalidade e segue"), (4, "10. VALOR DE MERCADO")]
    m = editavel.marcas_de_pagina(pdf, paragrafos)
    assert m == {"1": 0, "2": 2, "3": 3, "4": 4}
    assert editavel.marcas_de_pagina(tmp_path / "nao-existe.pdf", paragrafos) == {}


def test_de_conta():
    assert editavel._de_conta("valor adotado") and editavel._de_conta("planilha: área do terreno")
    assert not editavel._de_conta("nome do bairro (como no documento)") and not editavel._de_conta("data-base")
