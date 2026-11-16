"""D-065 (ORDEM 037-2): valor adotado = área × unitário arredondado ao MILHAR mais próximo,
em toda modalidade, e o revisor não trata o arredondamento como divergência."""
from decimal import Decimal

import pytest

from lovable.avaliacao import calculo
from lovable.avaliacao.agentes import revisor
from lovable.avaliacao.modelos import Referencial

MODALIDADES = ("OV", "AM", "AM_GARANTIA", "AMJ", "PTAM")


def _ref(n, preco, area):
    return Referencial(n=n, link="https://exemplo.test/a", portal="teste", bairro="Bairro Teste",
                       tipologia="galpão", padrao="normal", idade_aparente="", descricao="",
                       preco=float(preco), area_m2=float(area))


@pytest.mark.parametrize("area,unit,calc,adot", [
    ("1982.96", "3061.95", "6071724.37", "6072000"),  # 9118 (Galpão 01)
    ("364.00", "2735.85", "995849.40", "996000"),     # OV 120
    ("100.00", "15.00", "1500.00", "2000"),           # meio milhar sobe
    ("100.00", "14.99", "1499.00", "1000"),           # abaixo do meio desce
    ("1.00", "1000.40", "1000.40", "1000"),
])
def test_milhar_mais_proximo(area, unit, calc, adot):
    u = Decimal(unit)
    r = calculo.calcular(Decimal(area), [_ref(1, u * Decimal(area), area)], u)
    assert r.valor_calculado == Decimal(calc)
    assert r.valor_adotado == Decimal(adot)
    assert r.valor_adotado % 1000 == 0


@pytest.mark.parametrize("modalidade", MODALIDADES)
def test_toda_modalidade_mesma_regra(modalidade):
    """O cálculo não depende da modalidade: todas passam pela mesma conta (calculo.calcular)."""
    refs = [_ref(1, Decimal("6000000"), "2760.46"), _ref(2, Decimal("4500000"), "1300")]
    r = calculo.calcular(Decimal("1982.96"), refs, Decimal("3061.95"))
    assert (modalidade, r.valor_adotado) == (modalidade, Decimal("6072000"))
    assert r.extenso == "Seis milhões e setenta e dois mil reais"
    assert (r.valor_min, r.valor_max) == (Decimal("5464800"), Decimal("6679200"))


def test_revisor_sabe_que_arredondamento_nao_e_divergencia():
    assert "D-065" in revisor.INSTRUCAO
    assert "NÃO é divergência" in revisor.INSTRUCAO
