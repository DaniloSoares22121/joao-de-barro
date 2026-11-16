"""L201-3 (Caso W, +27,5%): o ref. com "indícios de padrão superior" e dois mais novos entraram para um sobrado de
~30 anos, padrão simples. Regra 6: os mais novos e os de padrão superior destoam — etiqueta, fim da lista, fora da
escolha automática, aviso ao marcar."""
from lovable.avaliacao import candidatos as C
from lovable.avaliacao.modelos import Referencial


def _r(**k):
    base = dict(n=1, link="https://x/1", portal="OLX", bairro="B", tipologia="sobrado", quartos=3, suites=1,
                lote_m2=None, area_m2=300.0, preco=900000.0, padrao="", idade_aparente="", descricao="Sobrado 3 quartos")
    base.update(k)
    return Referencial(**base)


AV = C.Avaliando(tipo="Sobrado", bairro="B", cidade="Goiânia", area=364.0, padrao="simples", antigo=True,
                 idade_anos=22.5)


def test_parecido_nao_destoa():
    assert C.destoa(_r(idade_aparente="20 anos"), AV) == []


def test_gourmet_e_padrao_superior_para_avaliando_simples():
    assert C.destoa(_r(descricao="Sobrado com espaço gourmet e porcelanato"), AV) == ["padrão superior"]


def test_mais_novo_por_idade_e_por_palavra():
    assert C.destoa(_r(idade_aparente="10 anos"), AV) == ["mais novo"]
    assert C.destoa(_r(idade_aparente="seminovo"), AV) == ["mais novo"]
    assert C.destoa(_r(idade_aparente="15 anos"), AV) == []


def test_avaliando_novo_nao_marca_mais_novo():
    novo = C.Avaliando(tipo="Sobrado", bairro="B", cidade="Goiânia", padrao="normal", antigo=False, idade_anos=3)
    assert C.destoa(_r(idade_aparente="seminovo"), novo) == []


def test_destaque_do_anuncio_aberto_conta():
    r = _r(idade_aparente="", descricao="Sobrado 3 quartos").model_copy(update={"destaque": "3 quartos, churrasqueira"})
    assert C.destoa(r, AV) == ["padrão superior"]
