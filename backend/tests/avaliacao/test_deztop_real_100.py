"""ORDEM 100 (2 e 3): área construída e lote lidos do texto REAL das 4 páginas da Deztop do gabarito (trechos da
página como a extensão manda; sem nome de anunciante nem telefone). Depois do anúncio vem "Imóveis próximos", com
números de outros anúncios — nunca valem."""
import pytest

from lovable.avaliacao import leitura_pagina as L

PROXIMOS = ("Imóveis próximos\nImagem: Casa com 3 Dormitórios À Venda, 170 M²\n"
            "A casa possui 3 Dormitórios, 1 Suíte, 2 Banheiros, 4 Vagas na garagem, 170m² de Área\n"
            "Sobrado em terreno de 500 m²\nA casa possui 3 Dormitórios, 1 Banheiro, 300m² de Área\n")

VF21 = ("Aceita Troca Brasilia Sob Análise\nRua Vf , Vila Finsocial, Goiânia - GO\n3 Dormitórios\n300m² de Área\n"
        "PREÇO\nR$ 200.000\nA casa possui 3 Dormitórios, 2 Banheiros, 3 Vagas na garagem, 300m² de Área e está localizado "
        "em Rua Vf, Goiânia, Go à venda por R$200.000.\nFinsocial (Go)\n- Rua VF 21 Qd. 17\n- lote 10 X 30 = 300 m2, "
        "contendo uma casa (110m2), sendo 02 quartos, sala, cozinha, wc, area de serviços (coberta) + 1 comodo com wc ), "
        "piso cerâmica, telhado com forro pvc, garagem 3 vagas.\nCONTINUE LENDO\nAnunciante\n")
ANGLO = ("Casa Finsocial ( Goiânia. Goiás\nPREÇO\nR$ 200.000\nA casa possui 3 Dormitórios, 1 Banheiro, 3 Vagas na garagem, "
         "80m² de Área, Área de serviço e está localizado em Avenida Anglo, Goiânia, Go à venda por R$200.000.\n"
         "uma Casa no Finsocial Com 03 Quartos ,Sala ,Cozinha e 01 Banheiro Social ,área Na frente e Lateral Cabem 3 Carros ,"
         "Com 2 Barracões no Fundo estão alugados.\nCONTINUE LENDO\nAnunciante\n")
JC17A = ("Casa Jardim Curitiba\nPREÇO\nR$ 230.000\nA casa possui 3 Dormitórios, 1 Banheiro, 2 Vagas na garagem, 230m² de "
         "Área e está localizado em Rua Jc17A, Goiânia, Go à venda por R$230.000.\nse casa no Jardim Curitiba , três quarto , "
         "sala , copa , cozinha , 1 banheiro , garagem , área no fundo , portão elétrico , lote 12 por 30.\nCONTINUE LENDO\n")
JC18 = ("Casa Jardim Curitiba\nPREÇO\nR$ 240.000\nA casa possui 2 Dormitórios, 1 Suíte, 2 Banheiros, 2 Vagas na garagem, "
        "125m² de Área, Área de serviço, Churrasqueira e está localizado em Rua Jc18, Goiânia, Go à venda por R$240.000.\n"
        "casa linda 2qt sendo 1 suíte mais banheiro social, sala com pé direito duplo cozinha americana área de serviço "
        "garagem coberta para 1 carro, churrasqueira.\nCONTINUE LENDO\n")


@pytest.mark.parametrize("texto,area,lote", [(VF21, 110, 300), (ANGLO, 80, None), (JC17A, 230, 360), (JC18, 125, None)])
def test_area_e_lote_das_paginas_reais(texto, area, lote):
    t = texto + PROXIMOS
    assert L.area_confirmada("", "", None, None, texto=t)[0] == area
    assert L.lote_confirmado(t, "") == lote            # o "terreno de 500 m²" de outro anúncio nunca vale


def test_lote_no_formato_do_zap():
    """100-3: o lote do VF-9 no ZAP ("300 m² área total" / "300 m² de terreno") volta a ser lido."""
    assert L.lote_confirmado("Casa à venda com 3 quartos\n150 m² área útil\n300 m² área total\nR$ 180.000", "") == 300
    assert L.lote_confirmado("Casa térrea com 150 m² construídos em 300 m² de terreno.", "") == 300
    assert L.area_confirmada("", "", None, None, texto="Casa térrea com 150 m² construídos em 300 m² de terreno.")[0] == 150
