import json
from decimal import Decimal
from pathlib import Path

import pytest

from lovable.avaliacao import calculo
from lovable.avaliacao.modelos import Referencial

FIX = Path(__file__).parent / "fixtures" / "ov120.json"
AREA = Decimal("364.00")


def _refs():
    return [Referencial(**d) for d in json.loads(FIX.read_text(encoding="utf-8"))]


def test_ov120():
    r = calculo.calcular(AREA, _refs(), Decimal("2735.85"))
    assert r.unitarios == [Decimal(x) for x in
                           ("3282.83", "3632.48", "3663.87", "2950.00", "2735.85")]
    assert r.minimo == Decimal("2735.85")
    assert r.maximo == Decimal("3663.87")
    assert r.media == Decimal("3253.01")
    assert r.unitario_adotado == Decimal("2735.85")
    assert r.valor_calculado == Decimal("995849.40")
    assert r.valor_adotado == Decimal("996000")
    assert r.faixa_pct == Decimal("10")
    assert r.valor_min == Decimal("896400")
    assert r.valor_max == Decimal("1095600")
    assert r.extenso == "Novecentos e noventa e seis mil reais"
    assert r.excluidos == []


def test_default_usa_media():
    r = calculo.calcular(AREA, _refs())
    assert r.unitario_adotado == Decimal("3253.01")


def test_unitario_fora_do_intervalo():
    with pytest.raises(ValueError):
        calculo.calcular(AREA, _refs(), Decimal("4000"))
    with pytest.raises(ValueError):
        calculo.calcular(AREA, _refs(), Decimal("2000"))


def test_area_ausente_excluida():
    refs = _refs()
    refs[0].area_m2 = None
    refs[1].area_m2 = 0
    r = calculo.calcular(AREA, refs)
    assert r.excluidos == [(1, "área construída ausente"), (2, "área construída ausente")]
    assert len(r.unitarios) == 3
    assert r.media == Decimal("3116.57")  # (3663.87+2950+2735.85)/3


def test_sem_referenciais_validos():
    with pytest.raises(ValueError):
        calculo.calcular(AREA, [])


@pytest.mark.parametrize("v,esperado", [
    (Decimal("996000"), "Novecentos e noventa e seis mil reais"),
    (Decimal("1095600"), "Um milhão e noventa e cinco mil e seiscentos reais"),
    (Decimal("1000000"), "Um milhão de reais"),
    (Decimal("1000"), "Mil reais"),
    (Decimal("1"), "Um real"),
    (Decimal("100"), "Cem reais"),
    (Decimal("101"), "Cento e um reais"),
    (Decimal("250000"), "Duzentos e cinquenta mil reais"),
    (Decimal("2500000"), "Dois milhões e quinhentos mil reais"),
    (Decimal("300000000"), "Trezentos milhões de reais"),
    (Decimal("1234567"),
     "Um milhão, duzentos e trinta e quatro mil, quinhentos e sessenta e sete reais"),
])
def test_por_extenso(v, esperado):
    assert calculo.por_extenso(v) == esperado
