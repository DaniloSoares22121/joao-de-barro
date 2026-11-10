import pytest

from lovable.avaliacao import db


def numero_unico() -> int:
    """Número de trabalho ainda não usado (negativo: nunca colide com os números fixos dos
    testes nem mexe em proximo_numero). Contador lido do banco: vale mesmo se este módulo
    for importado duas vezes (como conftest e como tests.avaliacao.conftest)."""
    with db._conn() as c:
        r = c.execute("SELECT MIN(numero) AS m FROM av_jobs").fetchone()
    return min(int(r["m"] or 0), 0) - 1


def numero_livre(preferido: int) -> int:
    """`preferido` (ex.: 120, o caso-modelo) se ainda livre neste teste; senão um único."""
    return numero_unico() if db.numero_usado(preferido) else preferido


@pytest.fixture(autouse=True)
def _numeros_livres():
    """O app.db é compartilhado e o índice único de av_jobs(numero) fica ligado: antes de
    cada teste, os trabalhos dos testes anteriores ganham números únicos do contador, e o
    teste pode usar os números do caso-modelo (120, 121…) sem colidir. (Negativos não
    mexem em proximo_numero.)"""
    db.init()
    with db._conn() as c:
        base = min(int(c.execute("SELECT MIN(numero) FROM av_jobs").fetchone()[0] or 0), 0)
        ids = [r["id"] for r in c.execute("SELECT id FROM av_jobs WHERE numero > 0")]
        c.executemany("UPDATE av_jobs SET numero=? WHERE id=?",
                      [(base - k, i) for k, i in enumerate(ids, start=1)])
    yield


@pytest.fixture(autouse=True)
def _sem_whatsapp_real(monkeypatch):
    """Nenhum teste fala com o wa-bridge de verdade."""
    from lovable.avaliacao import aviso
    enviados = []
    monkeypatch.setattr(aviso, "_enviar", lambda tel, corpo, chave: (enviados.append(
        (tel, corpo, chave)) or (False, "teste")))
    monkeypatch.setattr(aviso, "_situacao_wa", lambda: {"conectado": False, "numero": ""})
    return enviados
