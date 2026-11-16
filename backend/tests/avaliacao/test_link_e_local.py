"""ORDEM 035: link com id na query e localização com abreviação ("Av.")."""
from lovable.avaliacao import docx_builder
from lovable.avaliacao.agentes.pesquisa import link_limpo
from lovable.avaliacao.modelos import Referencial


def test_link_mantem_id_e_tira_rastreio():
    assert link_limpo("https://imoby.com.br/detalhes.php?id=83&utm_source=chatgpt.com") == \
        "https://imoby.com.br/detalhes.php?id=83"
    assert link_limpo("https://www.zapimoveis.com.br/imovel/x-id-1/?source=ranking%2Crp#fotos") == \
        "https://www.zapimoveis.com.br/imovel/x-id-1"


def test_localizacao_com_abreviacao():
    r = Referencial(n=1, link="https://x", portal="", bairro="All Park", tipologia="", padrao="", idade_aparente="",
                    descricao="Localização: Av. Antônio F. Pacheco – All Park Polo Empresarial. Galpão novo com doca.")
    assert docx_builder._local_manual(r) == ("Av. Antônio F. Pacheco – All Park Polo Empresarial", "Galpão novo com doca.")
