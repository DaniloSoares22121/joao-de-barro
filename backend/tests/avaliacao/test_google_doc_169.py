"""169-4/6 com o Google simulado: o [Concluir] traz o documento do Google Docs (e gera o PDF pela nossa montagem); o
cartão vira link para a âncora do Docs mais próxima antes da frase."""
import io

import pytest
from docx import Document

from lovable.avaliacao import editavel, google_doc
from lovable.avaliacao import google_drive as G
from tests.avaliacao.test_editor_laudo import _laudo
from tests.avaliacao.test_pagina_enviada import _job

HTML = (b'<html><head><style>p{color:red}</style></head><body>'
        b'<p class="c1"><span>PARECER T\xc3\xa9CNICO</span></p>'
        b'<h1 id="h.abc123"><span>1. FINALIDADE DA AVALIA\xc3\x87\xc3\x83O</span></h1>'
        b'<p><span>A finalidade do presente parecer \xc3\xa9 a determina\xc3\xa7\xc3\xa3o do valor.</span></p>'
        b'<p><a id="id.xyz789"></a><span>7.3. \xc3\x81reas e Dimens\xc3\xb5es</span></p>'
        b'<table><tr><td><p><span>Terreno 286,10</span></p></td></tr></table></body></html>')


def _docx(texto):
    d = Document()
    d.add_paragraph(texto)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


@pytest.fixture()
def gdoc(monkeypatch):
    estado = {"docx": _docx("Laudo editado no Google: Imóvel Avaliado mudado."), "exportou": []}

    def exportar(jid, fmt):
        estado["exportou"].append(fmt)
        return {"docx": estado["docx"], "html": HTML, "pdf": b"%PDF"}[fmt]
    monkeypatch.setattr(G, "arquivo_do_trabalho", lambda jid: "doc1")
    monkeypatch.setattr(G, "exportar", exportar)
    google_doc._CACHE.clear()
    return estado


def test_ancora_mais_proxima_antes_da_frase(gdoc):
    jid = _job()
    assert google_doc.ancora(jid, "determinação do valor") == {"ancora": "#heading=h.abc123", "achou": True}
    assert google_doc.ancora(jid, "Terreno 286,10")["ancora"] == "#bookmark=id.xyz789"
    assert google_doc.ancora(jid, "PARECER TÉCNICO") == {"ancora": "", "achou": True}     # nada antes: o começo
    assert google_doc.ancora(jid, "frase que não existe no laudo")["achou"] is False
    assert gdoc["exportou"].count("html") == 1                                            # os cartões usam o mesmo HTML


def test_sem_google_nao_ha_ancora(monkeypatch):
    monkeypatch.setattr(G, "arquivo_do_trabalho", lambda jid: None)
    assert google_doc.ancora(_job(), "qualquer") == {"ancora": "", "achou": False}


def test_concluir_traz_o_documento_do_google(gdoc, monkeypatch):
    jid = _job()
    f = _laudo(jid)
    f["pdf"].write_bytes(b"%PDF-1.4 velho")
    editavel.abrir(jid)
    gerou = []
    monkeypatch.setattr(editavel, "_gerar_pdf", lambda finais: gerou.append(Document(str(finais["docx"])).paragraphs[0].text))

    class _Co:
        ok, diferencas = True, []
    monkeypatch.setattr(editavel, "_conferir", lambda j, finais: (_Co(), ""))
    from lovable.avaliacao import coerencia
    monkeypatch.setattr(coerencia, "substituicoes", lambda co: [])
    r = editavel.usar(jid, concluir=True)
    assert r["ok"] and r["mudou"] is True
    assert gerou == ["Laudo editado no Google: Imóvel Avaliado mudado."]     # o PDF saiu do documento do Google
    assert any(p.name.startswith("edit-google-") for p in (editavel.db.pasta(jid) / "revisoes").iterdir())


def test_google_devolve_lixo_nao_gera_pdf(gdoc, monkeypatch):
    jid = _job()
    _laudo(jid)
    editavel.abrir(jid)
    gdoc["docx"] = b"PK-nao-e-word"
    monkeypatch.setattr(editavel, "_gerar_pdf", lambda finais: pytest.fail("não podia gerar PDF"))
    with pytest.raises(ValueError, match="não devolveu o laudo em Word"):
        editavel.usar(jid, concluir=True)
