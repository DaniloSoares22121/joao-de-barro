import os
from pathlib import Path

import pytest

# ORDEM 046: a mesma trava do tests/conftest.py, aqui também (vale se o pytest for chamado de
# dentro desta pasta): sem pasta temporária, para ANTES de importar o app e abrir o banco.
_REAL = (Path(__file__).resolve().parents[2] / "data").resolve()
_D = os.environ.get("LOVABLE_DATA_DIR", "").strip()
if not _D or Path(_D).resolve() == _REAL or _REAL in Path(_D).resolve().parents:
    pytest.exit("TRAVA DOS TESTES (ORDEM 046): LOVABLE_DATA_DIR ausente ou apontando para o banco "
                "real. Rode com uma pasta temporária vazia. Nada foi aberto nem alterado.", returncode=3)

from lovable.avaliacao import db  # noqa: E402


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
def _coletor_sessao_limpa():
    """Cada teste começa com o banco pronto (112: o bloqueio de portal e o ritmo de busca saíram com a busca
    automática; o Coletor só captura o mapa)."""
    db.init()
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


def pytest_configure(config):
    # ORDEM 071-D: o teste de calibragem do caso 122 (IA de verdade) só roda quando chamado
    config.addinivalue_line("markers", "caso122: calibragem com o caso 122 (IA de verdade; JDB_CASO122=1)")


@pytest.fixture(autouse=True)
def _sem_ia_na_checagem_de_arte(monkeypatch):
    """093-A-10: o envio de anúncio confere se a foto é arte de propaganda (IA leve). Nos testes isso nunca vai à IA
    de verdade (custa); o teste que precisa troca por cima."""
    from lovable.avaliacao import routes

    async def _nao_e_arte(jid, rel):
        return False
    monkeypatch.setattr(routes, "_foto_e_arte", _nao_e_arte)
    monkeypatch.setattr(routes, "_idade_em_segundo_plano", lambda jid, n: None)   # 109-5: nada de IA nos testes
