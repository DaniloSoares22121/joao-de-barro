import json
import shutil
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from lovable.avaliacao import calculo, planilha
from lovable.avaliacao.modelos import Referencial, Trabalho

FIX = Path(__file__).parent / "fixtures" / "ov120.json"
AREA = Decimal("364.00")


def _refs():
    return [Referencial(**d) for d in json.loads(FIX.read_text(encoding="utf-8"))]


def _trabalho():
    return Trabalho(
        id="ov120", numero=120, modalidade="OV", finalidade="Venda",
        cliente="Marina", tipo="Sobrado", bairro="Jardim Vila Boa",
        cidade="Goiânia", pin_maps="", data_base=date(2026, 10, 20),
        data_vistoria=date(2026, 10, 15),
    )


def _gerar(tmp_path):
    refs = _refs()
    r = calculo.calcular(AREA, refs, Decimal("2735.85"))
    return planilha.gerar(tmp_path / "p2.xlsx", _trabalho(), AREA, refs, r)


def test_planilha_formulas(tmp_path):
    destino = _gerar(tmp_path)
    wb = openpyxl.load_workbook(destino, data_only=False)
    am, calc, im = wb["Amostras"], wb["Calculo"], wb["Imovel"]
    for lin in range(2, 7):
        assert str(am.cell(lin, 10).value).startswith("=")
        assert am.cell(lin, 2).value == "S"
    assert am["I2"].value == 650000 and am["G2"].value == 198
    assert str(calc["B6"].value).startswith("=")   # média
    assert str(calc["B13"].value).startswith("=")  # valor exato
    assert str(calc["B15"].value).startswith("=")  # valor adotado
    assert calc["B10"].value == pytest.approx(2735.85)  # adotado diferente da média
    assert calc["B14"].value == 1000
    assert calc["B17"].value == pytest.approx(0.10)
    assert im["B9"].value == pytest.approx(364.0)
    assert im["B2"].value == "Marina"


@pytest.mark.skipif(planilha.soffice_path() is None, reason="LibreOffice ausente")
def test_planilha_recalculo_libreoffice(tmp_path):
    destino = _gerar(tmp_path)
    saida = tmp_path / "out"
    saida.mkdir()
    subprocess.run(
        [planilha.soffice_path(), "--headless", "--convert-to", "xlsx",
         "--outdir", str(saida), str(destino)],
        check=True, capture_output=True, timeout=180,
    )
    wb = openpyxl.load_workbook(saida / destino.name, data_only=True)
    calc = wb["Calculo"]
    assert calc["B2"].value == 5
    assert calc["B3"].value == pytest.approx(2735.85)
    assert calc["B4"].value == pytest.approx(3663.87)
    assert calc["B6"].value == pytest.approx(3253.01)
    assert calc["B13"].value == pytest.approx(995849.40)
    assert calc["B15"].value == 996000
    assert calc["B18"].value == pytest.approx(896400)
    assert calc["B19"].value == pytest.approx(1095600)


@pytest.mark.parametrize("origem,esperado", [
    ("documento", "Comprovado"), ("vistoria", "Observado"), ("pesquisa", "Pesquisa"),
    ("inferido", "Inferido"), ("pendente", "Pendente")])
def test_planilha_status_da_origem(tmp_path, origem, esperado):
    refs = _refs()
    r = calculo.calcular(AREA, refs, Decimal("2735.85"))
    d = planilha.gerar(tmp_path / "p2.xlsx", _trabalho(), AREA, refs, r, origem_area=origem)
    im = openpyxl.load_workbook(d)["Imovel"]
    assert im["E9"].value == esperado
    for lin in (2, 3, 5, 6, 7, 10):
        assert im.cell(lin, 5).value == "Informado"
