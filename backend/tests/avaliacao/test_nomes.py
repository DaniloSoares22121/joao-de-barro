from datetime import date

from lovable.avaliacao import nomes
from lovable.avaliacao.modelos import Trabalho


def _t(**kw):
    base = dict(id="x", numero=120, modalidade="OV", finalidade="Venda", cliente="Marina",
                tipo="Sobrado", bairro="Jardim Vila Boa", cidade="Goiânia", pin_maps="",
                data_base=date(2026, 10, 16), data_vistoria=date(2026, 10, 16))
    base.update(kw)
    return Trabalho(**base)


def test_nome_d020():
    assert nomes.nome_arquivo(_t()) == "120 - Marina - Sobrado - Jardim Vila Boa - Goiânia"


def test_nome_remove_proibidos():
    n = nomes.nome_arquivo(_t(cliente='A/B\\C:D*E?F"G<H>I|J', bairro="  Setor  Sul "))
    assert n == "120 - ABCDEFGHIJ - Sobrado - Setor Sul - Goiânia"
