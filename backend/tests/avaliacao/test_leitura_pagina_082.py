"""ORDEM 082-3: a área lida da página tem que ser a do anúncio — ou "não achei", nunca um chute.
Os 4 casos do 9120 (títulos e links reais dos anúncios; o número errado é o que a página trouxe de outro anúncio)."""
import pytest

from lovable.avaliacao import leitura_pagina as L

CASOS = [
    # n, título, link, área lida pela extensão, área lida do texto, certo
    (2, "Casa para Venda Possui 110 Metros Quadrados com 3 Quartos em Vila Finsocial",
     "https://deztop.com/br/imovel/296628655/casa-3-dormitorios-goiania", 290, None, 110),
    (3, "Casa Jardim Curitiba - Deztop", "https://deztop.com/br/imovel/299970092/casa-3-dormitorios-goiania", 139, None, None),
    (5, "Casa Finsocial ( Goiânia. Goiás - Deztop", "https://deztop.com/br/imovel/293212933/casa-3-dormitorios-goiania", 300, 80, None),
    (6, "Aceita Troca Brasilia Sob Análise - Deztop", "https://deztop.com/br/imovel/297399676/casa-3-dormitorios-goiania", 170, 110, None),
]


@pytest.mark.parametrize("n,titulo,link,ext,txt,certo", CASOS)
def test_area_do_anuncio_ou_nao_achei(n, titulo, link, ext, txt, certo):
    area, motivo = L.area_confirmada(titulo, link, ext, txt)
    assert area == certo, (n, area, motivo)
    assert area in (110, 80, 230, None) and area not in (290, 139, 300, 170)   # nunca o número de outro anúncio
    if area is None:
        assert "não achei" in motivo


def test_zap_area_no_link_e_concordancia():
    link = "https://www.zapimoveis.com.br/imovel/venda-casa-3-quartos-jardim-curitiba-goiania-go-139m2-id-2845551234/"
    assert L.area_confirmada("Casa à venda", link, 139, None)[0] == 139
    assert L.area_confirmada("Casa à venda", link, 290, None)[0] is None     # o link sozinho não decide (pode ser o terreno)
    assert L.area_confirmada("", ".../galpao-1650m2-id-1/", None, 1061.39)[0] is None    # F-S003: 1650 é o terreno
    assert L.areas_do_anuncio("Galpão 2.100 m²", "") == [2100.0]
    assert L.areas_do_titulo("Casa 110 m² em lote 360 m²") == [110.0]
    assert L.area_confirmada("Casa", "https://x.com/imovel/1", 95, 95)[0] == 95   # extensão e texto concordam


def test_lote_de_30_m2_em_casa_e_leitura_errada():
    assert L.lote_plausivel(30, 290, "Casa") is None
    assert L.lote_plausivel(300, 110, "Casa") == 300


def test_091_rua_e_bairro_pelo_caminho_da_pagina():
    t = "Deztop\nVenda › Goiânia › Vila Finsocial › Casa › Avenida Anglo\nCasa 3 quartos\nR$ 200.000"
    assert L.local_da_pagina(t) == ("Avenida Anglo", "Vila Finsocial")
    assert L.local_da_pagina("Rua Vf, Vila Finsocial, Goiânia - GO\nCasa à venda") == ("Rua Vf", "Vila Finsocial")
    assert L.local_da_pagina("Casa à venda em ótima região") == ("", "")
    assert L.bairro_ruim("GO") and L.bairro_ruim("Deztop") and L.bairro_ruim("Rua Vf, Vila Finsocial, G")
    assert not L.bairro_ruim("Jardim Curitiba")


def test_091_texto_so_do_anuncio():
    t = ("menu\nCasa 3 quartos Vila Finsocial\nCasa antiga, 110 m², escriturada. " + "x" * 300
         + "\nImóveis semelhantes\nCasa nova em acabamento, várias unidades")
    so = L.texto_do_anuncio(t, "Casa 3 quartos Vila Finsocial")
    assert "Casa antiga" in so and "acabamento" not in so and "várias unidades" not in so


def test_091_rua_grudada():
    assert L.separar_rua("Rua Vf, Vila Finsocial, Goiânia - GO") == ("Rua Vf", "Vila Finsocial")
    assert L.separar_rua("Rua Jc17A, Jardim Curitiba, Goiânia - GO") == ("Rua Jc17A", "Jardim Curitiba")
    assert L.separar_rua("Avenida Anglo") == ("Avenida Anglo", "")


ZAP_BRUTO = ("Pular para o conteúdo principal Alugar Comprar Lançamentos Simular consórcio Entrar Criar conta\n"
             "Casa com 3 quartos à venda, 220 m² por R$ 295.000\n"
             "Favorite o anúncio e anote aqui\n"
             "Casa ampla com 3 quartos, sendo 1 suíte, espaço gourmet com churrasqueira e quintal. "
             "Documentação em dia, aceita financiamento.\n"
             "Imóveis semelhantes\nCasa nova em acabamento")


def test_092_descricao_limpa_e_destaque():
    d = L.descricao_limpa(ZAP_BRUTO, "Casa com 3 quartos à venda, 220 m² por R$ 295.000")
    assert d.startswith("Casa ampla com 3 quartos") and len(d) <= 300
    for lixo in ("Pular para o conteúdo", "Criar conta", "Entrar", "Simular", "Favorite", "acabamento", "financiamento"):
        assert lixo not in d, lixo
    assert L.destaque(ZAP_BRUTO, "Casa com 3 quartos à venda, 220 m² por R$ 295.000") == \
        "3 quartos, 1 suíte, espaço gourmet, churrasqueira, 220 m²"
    assert L.descricao_limpa("Pular para o conteúdo principal Entrar Criar conta") == ""


def test_096_7_mesma_foto_em_varios_tamanhos():
    import base64
    def dz(tam, nome):
        b = base64.b64encode(f"https://img.olx.com.br/images/76/{nome}.jpg".encode()).decode().rstrip("=")
        return f"https://proxy.deztop.com/image/{tam}/{b}.jpg"
    urls = [dz("1200x630", "760207001"), dz("1200x900", "760207001"), dz("1200x630", "769229002"),
            dz("200x150", "769229002"), dz("1200x900", "761228003")]
    assert L.fotos_unicas(urls) == [urls[0], urls[2], urls[4]]
    zap = ["https://resizedimgs.zapimoveis.com.br/img/vr-listing/abc/casa.webp?action=fit-in&dimension=1920x1080",
           "https://resizedimgs.zapimoveis.com.br/img/vr-listing/abc/casa.webp?action=fit-in&dimension=614x297",
           "https://resizedimgs.zapimoveis.com.br/img/vr-listing/abc/sala.webp?action=fit-in&dimension=1920x1080"]
    assert L.fotos_unicas(zap) == [zap[0], zap[2]]


def test_097_2_area_rotulada_no_texto_do_anuncio():
    t = ("Deztop › Goiânia › Jardim Curitiba\nCasa Jardim Curitiba - Deztop\nR$ 240.000\n"
         "Características: 2 quartos, Área construída: 125 m², Terreno 300 m²\n" + "x" * 250
         + "\nImóveis semelhantes\nCasa 170 m² construídos no Jardim Vizinho")
    assert L.area_rotulada(t, "Casa Jardim Curitiba - Deztop") == 125
    assert L.area_confirmada("Casa Jardim Curitiba - Deztop", "https://deztop.com/br/imovel/301959200/casa", 170, None, texto=t)[0] == 125
    assert L.area_rotulada("Casa com 110 m² construídos em lote de 300 m².", "") == 110
    assert L.area_rotulada("Área construída 110 m². Área útil 95 m².", "") is None        # dois números: não decide
    # sem texto, a regra antiga continua
    assert L.area_confirmada("Casa Jardim Curitiba - Deztop", "https://deztop.com/br/imovel/1/casa", 139, None)[0] is None


def test_097_2_milhar_com_ponto():
    t = "Galpão com 1.061,39 m² construídos em terreno de 1.650 m²"
    assert L.area_rotulada(t) == 1061.39
    assert L.area_confirmada("", "https://x.com/galpao-1650m2-id-1/", 1650, 1061.39, texto=t)[0] == 1061.39
    assert L.area_rotulada("Área construída: 2.100,00 m²") == 2100.0


def test_098_3_grafia_da_rua():
    assert L.logradouro("Rua Jc18") == "Rua JC-18"
    assert L.logradouro("Rua JC58") == "Rua JC-58"
    assert L.logradouro("Rua VF 9") == "Rua VF-9"
    assert L.logradouro("Rua Vf") == "Rua VF"
    assert L.logradouro("Rua Jc17A") == "Rua JC-17A"
    assert L.logradouro("Avenida Anglo") == "Avenida Anglo"
    assert L.logradouro("Rua das Flores, 10") == "Rua das Flores, 10"


def test_098_2_lote_so_do_anuncio():
    t = ("Casa Jardim Curitiba - Deztop\nCasa com 2 quartos, 125 m² construídos, lote de 10x30.\n" + "x" * 250
         + "\nImóveis semelhantes\nSobrado em terreno de 500 m²")
    assert L.lote_confirmado(t, "Casa Jardim Curitiba - Deztop") == 300
    assert L.lote_confirmado(t, "Casa Jardim Curitiba - Deztop", lido=500) == 300   # 500 é de outro anúncio
    assert L.lote_confirmado("Casa térrea, 3 quartos. " + "x" * 250 + "\nVeja também\nTerreno 500 m²", "") is None


def test_102_8_sem_zero_suites():
    assert "suíte" not in L.destaque("Casa com 3 quartos, 0 suítes, espaço gourmet e piscina, 220 m²", "")
