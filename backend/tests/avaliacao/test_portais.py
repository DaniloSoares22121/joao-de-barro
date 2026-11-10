from urllib.parse import urlsplit

from lovable.avaliacao import portais
from lovable.avaliacao.fonte_mercado import Consulta

C = Consulta(tipologia="Sobrado", bairro="Jardim Vila Boa", cidade="Goiânia")


def test_slug():
    assert portais.slug("Jardim Vila Boa") == "jardim-vila-boa"
    assert portais.slug("Goiânia") == "goiania"


def test_url_busca_dominio_certo():
    assert set(portais.PORTAIS) == {"zap", "vivareal", "olx", "imovelweb"}
    for p in portais.PORTAIS.values():
        u = urlsplit(p.url_busca(C))
        assert u.scheme == "https" and (u.hostname == p.dominio or u.hostname.endswith("." + p.dominio))
        assert "boa" in p.url_busca(C)
    assert portais.PORTAIS["zap"].url_busca(C) == \
        "https://www.zapimoveis.com.br/venda/sobrados/go+goiania++jd-vl-boa/"


def test_eh_anuncio():
    P = portais.PORTAIS
    assert P["zap"].eh_anuncio("https://www.zapimoveis.com.br/imovel/venda-sobrado-3-quartos-id-123/")
    assert not P["zap"].eh_anuncio("https://www.zapimoveis.com.br/venda/sobrados/go+goiania/")
    assert not P["zap"].eh_anuncio("https://evil.com/imovel/x")
    assert not P["zap"].eh_anuncio("https://zapimoveis.com.br.evil.com/imovel/x")
    assert P["vivareal"].eh_anuncio("https://www.vivareal.com.br/imovel/sobrado-3-quartos-id-9/")
    assert P["olx"].eh_anuncio("https://go.olx.com.br/grande-goiania/imoveis/sobrado-3-quartos-1234567890")
    assert P["olx"].eh_anuncio("https://www.olx.com.br/d/anuncio/sobrado-1234567890")
    assert not P["olx"].eh_anuncio("https://www.olx.com.br/imoveis/venda/estado-go")
    assert P["imovelweb"].eh_anuncio("https://www.imovelweb.com.br/propriedades/sobrado-goiania-2999.html")
    assert not P["imovelweb"].eh_anuncio("https://www.imovelweb.com.br/casas-venda-goiania.html")


def test_zap_abrevia_bairro():
    assert portais._zap_bairro("Residencial Granville") == "resid-granville"
    assert portais._zap_bairro("Setor Jaó") == "setor-jao"
