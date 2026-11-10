"""Geração da planilha P2 (cálculo) preenchida, mantendo as fórmulas do modelo."""
from __future__ import annotations

import os
import shutil
from decimal import Decimal
from pathlib import Path

import openpyxl

from .calculo import Resultado
from .modelos import Referencial, Trabalho

MODELO = Path(__file__).parent / "assets" / "P2_Planilha_Mestre_Calculo.xlsx"
_SOFFICE_WINDOWS = r"C:\Program Files\LibreOffice\program\soffice.exe"
_LINHA_INI, _LINHA_FIM = 2, 21  # Amostras!A2:L21 (20 linhas)
# origem do Campo -> vocabulário da coluna Status (Imovel!E, lista de validação do modelo)
STATUS_ORIGEM = {"documento": "Comprovado", "vistoria": "Observado", "pesquisa": "Pesquisa",
                 "inferido": "Inferido", "pendente": "Pendente"}
INFORMADO = "Informado"  # campos do formulário do trabalho


def soffice_path() -> str | None:
    """Caminho do LibreOffice (soffice) ou None se não instalado."""
    achado = shutil.which("soffice")
    if achado:
        return achado
    if os.path.exists(_SOFFICE_WINDOWS):
        return _SOFFICE_WINDOWS
    return None


def _num(v: Decimal | float | int) -> float:
    return float(v)


def gerar(
    destino: Path,
    trabalho: Trabalho,
    area: Decimal,
    refs: list[Referencial],
    r: Resultado,
    origem_area: str = "pendente",
) -> Path:
    """Preenche as células de ENTRADA da P2; as fórmulas do modelo são preservadas."""
    if len(refs) > _LINHA_FIM - _LINHA_INI + 1:
        raise ValueError("a planilha P2 comporta no máximo 20 referenciais")
    wb = openpyxl.load_workbook(MODELO)

    im = wb["Imovel"]
    entradas = {
        2: trabalho.cliente,
        3: f"{trabalho.bairro}, {trabalho.cidade}",
        5: trabalho.finalidade,
        6: trabalho.data_base,
        7: trabalho.data_vistoria,
        9: _num(area),
        10: trabalho.tipo,
    }
    for lin, valor in entradas.items():
        im.cell(lin, 2, valor)
        im.cell(lin, 5, STATUS_ORIGEM.get(origem_area, "Pendente") if lin == 9 else INFORMADO)

    am = wb["Amostras"]
    excluidos = {n for n, _ in r.excluidos}
    for i, ref in enumerate(refs):
        lin = _LINHA_INI + i
        am.cell(lin, 1, ref.n)
        am.cell(lin, 2, "N" if ref.n in excluidos else "S")
        am.cell(lin, 3, ref.portal)
        am.cell(lin, 4, ref.link)
        am.cell(lin, 5, ref.bairro)
        am.cell(lin, 6, ref.lote_m2)
        am.cell(lin, 7, ref.area_m2)
        am.cell(lin, 8, ref.idade_aparente)
        am.cell(lin, 9, ref.preco)
        am.cell(lin, 11, trabalho.data_base)
        # J (R$/m²) mantém a fórmula do modelo
    for lin in range(_LINHA_INI + len(refs), _LINHA_FIM + 1):
        am.cell(lin, 2, "N")  # linhas não usadas ficam fora da estatística

    calc = wb["Calculo"]
    if r.unitario_adotado != r.media:
        calc["B10"] = _num(r.unitario_adotado)  # entrada manual (senão fica =B6)
    calc["B14"] = 1000
    calc["B17"] = _num(r.faixa_pct / Decimal(100))

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return destino
