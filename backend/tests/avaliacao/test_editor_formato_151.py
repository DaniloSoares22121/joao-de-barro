"""151-3: a barra de ferramentas do editor (fonte, tamanho, negrito, cor, realce, alinhamento, lista, recuo, quebra de
página) grava a formatação no Word editável sem estragar o resto; 151-5: [Concluir a revisão humana] sem mudança."""
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from lovable.avaliacao import editavel
from tests.avaliacao.test_editor_laudo import _blocos, _laudo
from tests.avaliacao.test_pagina_enviada import _job


def _p(jid, k):
    return Document(str(editavel.caminho(jid))).paragraphs[k]


def test_trechos_com_formatacao_nova_partem_o_trecho_e_guardam_o_resto():
    jid = _job()
    _laudo(jid)
    b = _blocos(jid)[0]
    base = "".join(r["x"] for r in b["runs"])
    runs = [{"x": "Imóvel Avaliado: ", "b": 1},                       # igual: fica como está (12 pt, cor)
            {"x": "Casa", "b": 1, "fonte": "Georgia", "sz": 14, "cor": "C00000", "realce": "FFFF00"},
            {"x": " – Rua X, Jardim Curitiba, Goiânia.", "b": 0}]
    r = editavel.gravar(jid, b["id"], "", base, runs)
    assert not r["removido"]
    p = _p(jid, 0)
    assert p.text == base
    rs = p.runs
    assert rs[0].text == "Imóvel Avaliado: " and rs[0].bold and rs[0].font.size.pt == 12
    assert rs[0].font.color.rgb is not None and str(rs[0].font.color.rgb) == "18283B"
    casa = rs[1]
    assert casa.text == "Casa" and casa.bold and casa.font.name == "Georgia" and casa.font.size.pt == 14
    assert str(casa.font.color.rgb) == "C00000"
    assert casa._r.find(qn("w:rPr")).find(qn("w:highlight")).get(qn("w:val")) == "yellow"
    assert rs[2].text.startswith(" – Rua X") and not rs[2].bold and rs[2].font.name is None
    tela = r["bloco"]["runs"]
    assert tela[1] == {"x": "Casa", "b": 1, "sz": 14.0, "cor": "C00000", "fonte": "Georgia", "realce": "FFFF00"}


def test_desfazer_volta_ao_estilo_do_word():
    jid = _job()
    _laudo(jid)
    b = _blocos(jid)[1]
    t = "Segundo parágrafo, sem formatação especial."
    editavel.gravar(jid, b["id"], "", t, [{"x": t, "sz": 16, "cor": "C00000", "realce": "00FF00", "fonte": "Verdana"}])
    r = editavel.gravar(jid, b["id"], "", t, [{"x": t, "b": 0, "i": 0, "u": 0, "sz": 0, "cor": "", "realce": "", "fonte": ""}])
    assert r["bloco"]["runs"] == [{"x": t}]


def test_formato_do_paragrafo_alinha_recuo_lista_e_quebra():
    jid = _job()
    _laudo(jid)
    b = _blocos(jid)[1]
    t = "Segundo parágrafo, sem formatação especial."
    r = editavel.gravar(jid, b["id"], t, t, None, {"al": "center", "recuo": 36, "lista": 2, "quebra": 1})
    assert r["bloco"]["al"] == "center" and r["bloco"]["recuo"] == 36 and r["bloco"]["lista"] == 2 and r["bloco"]["quebra"] == 1
    p = _p(jid, 1)
    assert p.alignment == WD_ALIGN_PARAGRAPH.CENTER and p.style.style_id == "ListNumber" and p.paragraph_format.page_break_before
    r = editavel.gravar(jid, b["id"], t, t, None, {"al": "justify", "recuo": 0, "lista": 0, "quebra": 0})
    blk = r["bloco"]
    assert blk["al"] == "justify" and "recuo" not in blk and "lista" not in blk and "quebra" not in blk
    assert _p(jid, 1).text == t


def test_paragrafo_vazio_com_quebra_nao_some():
    jid = _job()
    _laudo(jid)
    b = _blocos(jid)[1]
    t = "Segundo parágrafo, sem formatação especial."
    r = editavel.gravar(jid, b["id"], "", t, None, {"quebra": 1})
    assert not r["removido"]


def test_desfazer_nao_apaga_a_linha_vazia():
    jid = _job()
    _laudo(jid)
    b = _blocos(jid)[1]
    t = "Segundo parágrafo, sem formatação especial."
    r = editavel.gravar(jid, b["id"], "", t, [{"x": ""}], None, manter=True)
    assert not r["removido"] and r["bloco"]["id"] == b["id"]


def test_concluir_sem_mudanca_so_confere(monkeypatch):
    jid = _job()
    f = _laudo(jid)
    f["pdf"].write_bytes(b"%PDF-1.4 teste")
    editavel.abrir(jid)
    gerou = []
    monkeypatch.setattr(editavel, "_gerar_pdf", lambda finais: gerou.append(1))

    class _Co:
        ok, diferencas = True, []
    monkeypatch.setattr(editavel, "_conferir", lambda j, finais: (_Co(), ""))
    from lovable.avaliacao import coerencia
    monkeypatch.setattr(coerencia, "substituicoes", lambda co: [])
    import pytest
    with pytest.raises(ValueError):
        editavel.usar(jid)
    r = editavel.usar(jid, concluir=True)
    assert r["ok"] and r["mudou"] is False and not gerou and r["concluida_em"]
    assert editavel.situacao(jid)["revisao_concluida_em"] == r["concluida_em"]


def _pdf(caminho, paginas):
    import pymupdf
    doc = pymupdf.open()
    for t in paginas:
        pg = doc.new_page(width=595, height=842)
        pg.insert_text((60, 30), "CABEÇALHO DO LAUDO")
        pg.insert_text((60, 200), t)
        pg.insert_text((60, 830), "Pág. rodapé")
    doc.save(caminho)


def test_folhas_vem_do_pdf_e_a_previa_mais_nova_vale(monkeypatch):
    jid = _job()
    f = _laudo(jid)
    _pdf(f["pdf"], ["Imóvel Avaliado: Casa", "Último parágrafo."])
    d = editavel.documento(jid)
    assert d["total_paginas"] == 2 and d["folhas_de"] == "laudo" and d["pagina"]["altura"] > 250
    assert d["paginas"]["2"] == d["blocos"][3]["id"]
    from lovable.avaliacao import pdf as _pdfmod

    def conv(docx):
        out = docx.with_suffix(".pdf")
        _pdf(out, ["Imóvel Avaliado: Casa", "Segundo parágrafo", "Último parágrafo."])
        return out
    monkeypatch.setattr(_pdfmod, "converter", conv)
    r = editavel.paginar(jid)
    assert r["total_paginas"] == 3
    d = editavel.documento(jid)
    assert d["folhas_de"] == "previa" and d["total_paginas"] == 3 and d["paginas"]["2"] == d["blocos"][1]["id"]
    png = editavel.faixa(jid, 1, "cab")
    assert png[:4] == b"\x89PNG"
    assert editavel.faixa(jid, 3, "rod")[:4] == b"\x89PNG"
    import pytest
    with pytest.raises(LookupError):
        editavel.faixa(jid, 9, "cab")


def test_alinhar_linha_de_imagem():
    import io
    jid = _job()
    f = _laudo(jid)
    from docx import Document as D
    d = D(str(f["docx"]))
    import pymupdf
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4), False)
    d.add_paragraph().add_run().add_picture(io.BytesIO(pix.tobytes("png")))
    d.save(str(f["docx"]))
    b = _blocos(jid)[-1]
    assert b["imgs"] and not b["runs"]
    r = editavel.gravar(jid, b["id"], "", "", None, {"al": "right"})
    assert r["bloco"]["al"] == "right" and r["bloco"]["imgs"] and not r["removido"]


def test_dois_pedidos_ao_mesmo_tempo_o_segundo_volta_409(monkeypatch):
    import threading
    import pytest
    jid = _job()
    _laudo(jid)
    entrou, solta = threading.Event(), threading.Event()

    def devagar(j, concluir=False):
        entrou.set()
        solta.wait(5)
        return {"ok": True}
    monkeypatch.setattr(editavel, "_usar", devagar)
    r = {}
    th = threading.Thread(target=lambda: r.update(a=editavel.usar(jid, True)))
    th.start()
    assert entrou.wait(5)
    with pytest.raises(ValueError, match="Já estou gerando"):
        editavel.usar(jid, True)
    solta.set()
    th.join(5)
    assert r["a"] == {"ok": True}
    assert editavel.usar(jid, True) == {"ok": True}          # terminou: o próximo pedido passa
