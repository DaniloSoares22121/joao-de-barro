"""L200 (Caso W): a idade que o avaliador confirma depois da escolha vale na tabela do laudo (antes saía n/i,
porque a escolha gravada guardava a idade "pelas fotos"; a planilha já mostrava a confirmada)."""
from docx import Document

from lovable.avaliacao import db, docx_builder

from .test_docx import _job, _textos


def test_idade_confirmada_depois_da_escolha_sai_no_laudo():
    jid, sel, r = _job()
    escolhidos = [x for x in sel.refs if x.escolhido]
    alvo = escolhidos[0]
    sel = sel.model_copy(update={"refs": [x.model_copy(update={"idade_aparente": "15 anos", "idade_fonte": "fotos"})
                                          if x.n == alvo.n else x for x in sel.refs]})
    db.salvar_candidatos(jid, [x.model_copy(update={"idade_aparente": "15 anos", "idade_fonte": "avaliador"})
                               if x.n == alvo.n else x for x in sel.refs])
    d = Document(str(docx_builder.montar(jid, _textos(), r, sel)))
    textos = " ".join(c.text for t in d.tables for row in t.rows for c in row.cells)
    assert "15 anos" in textos


def test_mapa_digital_so_em_goiania():
    """L200 (Caso M): "Aparecida de Goiânia" contém "goiania" e o laudo pedia o Mapa Digital Fácil (só de Goiânia)."""
    import inspect
    src = inspect.getsource(docx_builder._anexos)
    assert 'r"^goiania\s*[-/–]?\s*(?:go)?$"' in src
