"""ORDEM 018 (12/11/2026): pesquisa de galpão e portal bloqueado que o avaliador libera.

URLs conferidas ao vivo no Chrome do Alan em 12/11/2026 (Polo Empresarial Goiás, Aparecida de
Goiânia): ZAP e Viva Real com 4 galpões no bairro e 206 na cidade; Imovelweb reconhece o bairro;
OLX só acha por texto ("galpao aparecida de goiania" = 16 resultados).
"""
from types import SimpleNamespace

from lovable.avaliacao import candidatos as C
from lovable.avaliacao import portais
from lovable.avaliacao.agentes import pesquisa
from lovable.avaliacao.fonte_mercado import Consulta

BAIRRO = Consulta(tipologia="galpao", bairro="Polo Empresarial Goiás", cidade="Aparecida de Goiânia")
CIDADE = Consulta(tipologia="galpao", bairro="", cidade="Aparecida de Goiânia")


def test_galpao_no_bairro():
    P = portais.PORTAIS
    assert P["zap"].url_busca(BAIRRO) == ("https://www.zapimoveis.com.br/venda/galpao-deposito-armazem/"
                                          "go+aparecida-de-goiania++polo-empresarial-goias/")
    assert P["vivareal"].url_busca(BAIRRO) == ("https://www.vivareal.com.br/venda/goias/aparecida-de-goiania/"
                                               "bairros/polo-empresarial-goias/galpao_comercial/")
    assert P["imovelweb"].url_busca(BAIRRO) == ("https://www.imovelweb.com.br/comerciais-galpao-deposito-"
                                                "barracao-venda-polo-empresarial-goias-aparecida-de-goiania-go.html")
    assert P["olx"].url_busca(BAIRRO) == ("https://www.olx.com.br/imoveis/venda/estado-go"
                                          "?q=galpao+polo+empresarial+goias+aparecida+de+goiania")


def test_galpao_na_cidade_inteira():
    P = portais.PORTAIS
    assert P["zap"].url_busca(CIDADE) == ("https://www.zapimoveis.com.br/venda/galpao-deposito-armazem/"
                                          "go+aparecida-de-goiania/")
    assert P["vivareal"].url_busca(CIDADE) == ("https://www.vivareal.com.br/venda/goias/aparecida-de-goiania/"
                                               "galpao_comercial/")
    assert P["imovelweb"].url_busca(CIDADE) == ("https://www.imovelweb.com.br/comerciais-galpao-deposito-"
                                                "barracao-venda-aparecida-de-goiania-go.html")
    assert P["olx"].url_busca(CIDADE) == "https://www.olx.com.br/imoveis/venda/estado-go?q=galpao+aparecida+de+goiania"


def test_sobrado_continua_igual():
    c = Consulta(tipologia="Sobrado", bairro="Jardim Vila Boa", cidade="Goiânia")
    assert portais.PORTAIS["olx"].url_busca(c) == \
        "https://www.olx.com.br/imoveis/venda/casas/estado-go?q=jardim+vila+boa+goiania"
    assert portais.PORTAIS["vivareal"].url_busca(c) == \
        "https://www.vivareal.com.br/venda/goias/goiania/bairros/jardim-vila-boa/sobrado_residencial/"


def test_tipologia_de_busca_do_galpao():
    assert pesquisa._tip_busca("Galpão") == "galpao"
    assert pesquisa._tip_busca("Galpão comercial") == "galpao"
    assert pesquisa._tip_busca("Barracão") == "galpao"
    assert pesquisa._tip_busca("Sobrado") == "sobrado"


def test_galpao_busca_o_bairro_e_a_cidade_na_primeira_rodada():
    t = SimpleNamespace(tipo="Galpão", cidade="Aparecida de Goiânia",
                        bairro="Polo Empresarial Goiás – Etapa III")
    a = C.Avaliando(tipo="Galpão", bairro="Polo Empresarial Goiás", cidade="Aparecida de Goiânia")
    out, _ = pesquisa.consultas_da_orientacao(t, a, "", set(), True)
    assert [(c.tipologia, c.bairro) for c in out] == [("galpao", "Polo Empresarial Goiás"), ("galpao", "")]


