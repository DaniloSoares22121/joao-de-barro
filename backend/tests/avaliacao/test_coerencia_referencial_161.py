"""ORDEM 161: a conferência por regra não confunde o PREÇO de um referencial (tabela de amostras) com o valor do laudo,
mesmo quando ele fica a menos de 1% do valor adotado (área 106,24 → 110,00: valor R$ 179.000,00; referencial 02 a
R$ 180.000,00). E o valor do laudo errado de verdade continua dando alarme."""
from decimal import Decimal

import pymupdf

from lovable.avaliacao import coerencia

TABELA = [
    "9.3. Amostras",
    "02 Localização: Rua X, Jardim Curitiba I, Goiânia – GO.",
    "Anúncio do site ZAP IMÓVEIS no link:",
    "https://www.zapimoveis.com.br/imovel/exemplo",
    "300,00 m² 150,00 m² 30 anos R$ 180.000,00 R$ 1.200,00 /m²",
]


def _pdf(tmp_path, *paginas):
    arq = tmp_path / "laudo.pdf"
    with pymupdf.open() as d:
        for linhas in paginas:
            pg = d.new_page()
            for i, ln in enumerate(linhas):
                pg.insert_text((40, 60 + 16 * i), ln, fontsize=9)
        d.save(arq)
    return arq


def _esp():
    return coerencia.Esperado(valor_adotado=Decimal("179000.00"), valor_min=Decimal("161100.00"),
                              valor_max=Decimal("196900.00"), faixa_pct=Decimal("10"),
                              amostras=[(Decimal("180000"), Decimal("150"))])


def _valor(difs):
    return [d for d in difs if d.dado == "valor adotado"]


def test_preco_de_referencial_perto_do_valor_nao_e_alarme(tmp_path):
    bloco = ["VALOR DE MERCADO ADOTADO R$ 179.000,00 (Cento e setenta e nove mil reais)",
             "Valor mínimo (-10%) R$ 161.100,00", "Valor máximo (+10%) R$ 196.900,00"]
    r = coerencia.conferir(_pdf(tmp_path, TABELA, bloco), None, _esp())
    assert _valor(r.diferencas) == []


def test_referencial_sem_preco_na_lista_mas_na_linha_do_anuncio_nao_e_alarme(tmp_path):
    bloco = ["VALOR DE MERCADO ADOTADO R$ 179.000,00 (Cento e setenta e nove mil reais)"]
    esp = _esp()
    esp.amostras = []                                   # só pela linha "Anúncio do site … no link:"
    r = coerencia.conferir(_pdf(tmp_path, TABELA, bloco), None, esp)
    assert _valor(r.diferencas) == []


def test_valor_do_laudo_errado_de_verdade_da_alarme(tmp_path):
    bloco = ["VALOR DE MERCADO ADOTADO R$ 179.500,00 (Cento e setenta e nove mil e quinhentos reais)",
             "Valor mínimo (-10%) R$ 161.100,00", "Valor máximo (+10%) R$ 196.900,00"]
    r = coerencia.conferir(_pdf(tmp_path, TABELA, bloco), None, _esp())
    assert _valor(r.diferencas), "o valor errado no bloco do valor tem de ser apontado"
