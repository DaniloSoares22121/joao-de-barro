"""110-4: com o relato dizendo se as medidas batem, o portão da visita não pergunta da trena."""
from lovable.avaliacao import portoes


def _ids(ctx):
    return [q["id"] for q in portoes._perguntas("visita", ctx)]


def test_relato_respondeu_medidas_nao_pergunta():
    assert "medidas" not in _ids({"medidas_confere": True})
    assert "medidas" not in _ids({"medidas_confere": False})


def test_sem_relato_pergunta():
    assert "medidas" in _ids({})
