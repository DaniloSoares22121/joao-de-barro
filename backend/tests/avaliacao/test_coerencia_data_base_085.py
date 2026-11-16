"""ORDEM 085-1: a data-base do laudo é a que o avaliador informou (em ITCD, a da DITCD), nunca a da vistoria calada."""
from datetime import date

import pymupdf

from lovable.avaliacao import coerencia as C


def _pdf(tmp_path, data):
    arq = tmp_path / "laudo.pdf"
    with pymupdf.open() as d:
        d.new_page().insert_text((40, 60), f"Data-base: {data}", fontsize=9)
        d.save(arq)
    return arq


def test_data_base_da_vistoria_no_lugar_da_ditcd(tmp_path):
    esp = C.Esperado(data_base=date(2026, 11, 13), data_base_informada=date(2026, 10, 28), data_vistoria=date(2026, 11, 13), itcd=True)
    difs = C.conferir(_pdf(tmp_path, "13/11/2026"), None, esp).diferencas
    assert any(d.dado.startswith("data-base") and d.esperado == "28/10/2026" for d in difs), difs


def test_itcd_sem_data_informada_e_base_igual_a_vistoria(tmp_path):
    esp = C.Esperado(data_base=date(2026, 11, 13), data_vistoria=date(2026, 11, 13), itcd=True)
    difs = C.conferir(_pdf(tmp_path, "13/11/2026"), None, esp).diferencas
    assert any("DITCD" in d.esperado for d in difs), difs


def test_data_certa_nao_acusa(tmp_path):
    esp = C.Esperado(data_base=date(2026, 10, 28), data_base_informada=date(2026, 10, 28), data_vistoria=date(2026, 11, 13), itcd=True)
    assert not [d for d in C.conferir(_pdf(tmp_path, "28/10/2026"), None, esp).diferencas if d.dado.startswith("data-base")]


def test_como_data():
    assert C._como_data("2026-10-28") == date(2026, 10, 28) and C._como_data("Data da DITCD 28/10/2026") == date(2026, 10, 28)
