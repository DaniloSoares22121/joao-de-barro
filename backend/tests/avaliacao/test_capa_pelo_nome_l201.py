"""L201-4 (Caso M): sem fachada marcada, a capa saía com o hall interno (a IA o legendou "Fachada"). A foto que o
avaliador nomeou fachada/frente/portaria vai para a capa e para a foto de fachada."""
from types import SimpleNamespace as N

from lovable.avaliacao import db, docx_builder as B

from .test_docx import _img, _job


def _com(jid, *nomes):
    for n in nomes:
        _img(db.pasta(jid) / "fotos" / n, "blue", (1200, 800))
        db.adicionar_arquivo(jid, n, "foto", f"fotos/{n}")


def test_sem_nome_fica_a_escolha_da_extracao():
    jid, _, _ = _job()
    assert B._fachada(N(job=jid)) is None


def test_portaria_vai_para_a_capa():
    jid, _, _ = _job()
    _com(jid, "Hall 1.jpg", "Portaria.jpg")
    assert B._fachada(N(job=jid)) == "fotos/Portaria.jpg"


def test_fachada_antes_da_portaria_e_marcada_vale_mais():
    jid, _, _ = _job()
    _com(jid, "Portaria.jpg", "Fachada lateral.jpg")
    assert B._fachada(N(job=jid)) == "fotos/Fachada lateral.jpg"
    db.adicionar_arquivo(jid, "f3.jpg", "foto", "fotos/f3.jpg", "fachada")
    assert B._fachada(N(job=jid)) == "fotos/f3.jpg"
