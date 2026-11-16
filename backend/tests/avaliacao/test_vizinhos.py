"""D4: a lista de setores vizinhos de Goiânia (usada na avaliação dos anúncios). 112: a 2ª rodada da busca automática
nos vizinhos saiu com a busca automática."""
from lovable.avaliacao.agentes import pesquisa
from lovable.avaliacao.portais import slug


def test_lista_de_vizinhos_valida():
    viz = pesquisa.vizinhos_goiania()
    assert len(viz) >= 25 and "jardim-vila-boa" in viz
    assert set(viz["jardim-vila-boa"]) == {"Parque Anhanguera", "Setor Faiçalville",
                                           "Jardim Planalto"}
    for k, vs in viz.items():
        assert k == slug(k) and vs and slug(k) not in {slug(v) for v in vs}
