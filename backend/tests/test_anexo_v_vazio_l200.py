"""L200 (Caso M): Anexo V de avaliador sem contato/formação cadastrados saía com "Site: " vazio e o curso do Alan."""
from types import SimpleNamespace as N

from docx import Document

from lovable.avaliacao import avaliadores, docx_builder as B


def _laudo(monkeypatch, dados):
    monkeypatch.setattr(avaliadores, "identidade_avaliador", lambda av: dados)
    d = Document()
    for t in ("Nome: Avaliador Teste", "Formação: ", B._CURSO_ALAN, "", "Contato: ", "Telefone / WhatsApp: ",
              "Site: ", "Instagram: "):
        d.add_paragraph(t)
    B._anexo_v_sem_vazios(N(body=d.element.body))
    return [p.text for p in d.paragraphs]


def test_sem_nada_cadastrado(monkeypatch):
    out = _laudo(monkeypatch, {"formacao": "", "telefone": "", "site": "", "instagram": ""})
    assert out == ["Nome: Avaliador Teste", ""]


def test_com_telefone_fica_o_contato(monkeypatch):
    out = _laudo(monkeypatch, {"formacao": "Engenharia Civil", "telefone": "62 99999-0000", "site": "", "instagram": ""})
    assert "Contato: " in out and B._CURSO_ALAN not in out


def test_curso_do_alan_com_grafia_do_modelo_sai(monkeypatch):
    monkeypatch.setattr(avaliadores, "identidade_avaliador", lambda av: {"formacao": "", "telefone": "", "site": "", "instagram": ""})
    d = Document()
    d.add_paragraph("Curso Técnico em Transações Imobiliárias – CEP-SINDIMOVEIS/GO.")
    B._anexo_v_sem_vazios(N(body=d.element.body))
    assert [p.text for p in d.paragraphs] == []


def test_cidade_sem_acento_no_cadastro():
    import inspect
    src = inspect.getsource(B)
    assert 'r"' + chr(92) + 'bGoiania' + chr(92) + 'b", "Goiânia"' in src and chr(8) not in src
