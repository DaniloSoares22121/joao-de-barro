"""L200 (Caso M): a conferência de coerência trocava o CNAI de qualquer avaliador pelo do Alan (053569)."""
from pathlib import Path

from lovable.avaliacao import coerencia as C


def _pags(monkeypatch, texto):
    monkeypatch.setattr(C, "paginas", lambda pdf: [texto])


def _cnai(res):
    return [d for d in res.diferencas if d.dado == "CNAI"]


def test_cnai_do_outro_avaliador_nao_vira_o_do_alan(monkeypatch):
    _pags(monkeypatch, "Avaliador Teste – CRECI 00000-GO – CNAI nº 00000")
    assert _cnai(C.conferir(Path("x.pdf"), None, C.Esperado(cnai="00000"))) == []


def test_cnai_errado_volta_para_o_do_avaliador_do_trabalho(monkeypatch):
    _pags(monkeypatch, "CNAI nº 053569")
    d = _cnai(C.conferir(Path("x.pdf"), None, C.Esperado(cnai="00000")))
    assert [(x.encontrado, x.esperado) for x in d] == [("053569", "00000")]


def test_sem_cnai_nao_confere(monkeypatch):
    _pags(monkeypatch, "CNAI nº 053569")
    assert _cnai(C.conferir(Path("x.pdf"), None, C.Esperado(cnai=""))) == []


def test_sem_informar_continua_o_do_alan(monkeypatch):
    _pags(monkeypatch, "CNAI nº 12345")
    assert [x.esperado for x in _cnai(C.conferir(Path("x.pdf"), None, C.Esperado()))] == ["053569"]
