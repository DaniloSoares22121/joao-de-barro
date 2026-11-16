"""ORDEM 077-A item 2 (D-084): a conferência do "mínimo da faixa" olha o número do campo da faixa,
não qualquer valor parecido no texto (ex.: o valor declarado do comunicado do ITCD, R$ 155.694,94)."""
from decimal import Decimal

import pymupdf

from lovable.avaliacao import coerencia

FAIXA = [
    "VALOR DE MERCADO DO IMOVEL R$ 173.000,00 (Cento e setenta e três mil reais)",
    "FAIXA DE VARIACAO MERCADOLOGICA (10%)",
    "Valor mínimo (-10%) R$ 155.700,00",
    "Valor máximo (+10%) R$ 190.300,00",
]
# o anexo do ITCD numa tabela: o rótulo "Valor declarado" fica longe do número (cabeçalho, outra linha)
ITCD = [
    "Documentos analisados",
    "Documento | Emitente | Data | Valor declarado | Valor de referência",
    "Anexo III - Comunicado de Divergência ou Inconsistência em Malha Fiscal nº 02010-2026 GITCD,",
    "com o respectivo anexo, emitido pela Secretaria da Economia do Estado de Goiás | SEFAZ-GO | 28/10/2026 |",
    "R$ 155.694,94 | R$ 448.335,57",
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
    return coerencia.Esperado(valor_adotado=Decimal("173000.00"), valor_min=Decimal("155700.00"),
                              valor_max=Decimal("190300.00"), faixa_pct=Decimal("10"))


def test_valor_declarado_do_itcd_nao_e_minimo_da_faixa(tmp_path):
    r = coerencia.conferir(_pdf(tmp_path, FAIXA, ITCD, ["Valor declarado R$ 155.694,94; valor de referência R$ 448.335,57"]),
                           None, _esp())
    assert r.diferencas == []


def test_minimo_errado_no_campo_da_faixa_continua_sendo_pego(tmp_path):
    errado = [x.replace("Valor mínimo (-10%) R$ 155.700,00", "Valor mínimo (-10%) R$ 155.701,00") for x in FAIXA]
    r = coerencia.conferir(_pdf(tmp_path, errado + ["Faixa admitida: R$ 155.700,00 a R$ 190.300,00"], ITCD), None, _esp())
    assert any(d.encontrado == "R$ 155.701,00" for d in r.diferencas), r.diferencas


def test_faixa_resumida_com_um_real_a_mais_continua_sendo_pega(tmp_path):
    r = coerencia.conferir(_pdf(tmp_path, FAIXA + ["Faixa de variação admitida 10% - R$ 155.700,00 a R$ 190.301,00"]),
                           None, _esp())
    assert any(d.encontrado == "R$ 190.301,00" for d in r.diferencas), r.diferencas
