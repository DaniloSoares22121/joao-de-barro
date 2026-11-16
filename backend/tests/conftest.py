"""ORDEM 046: trava — a bateria de testes NUNCA abre o banco real.

Roda antes de qualquer teste (este conftest é o primeiro que o pytest carrega em tests/):
sem LOVABLE_DATA_DIR, ou com ela apontando para a pasta de dados real (backend/data), o pytest
para com erro ANTES de importar o app e de abrir o app.db.
Uso certo: LOVABLE_DATA_DIR=<pasta temporária vazia> python -m pytest tests -q
(Em 14/11/2026 a bateria rodou no banco real: renumerou trabalhos, apagou fichas e
configurações e criou 200 trabalhos de teste. Ver RESPOSTA 038.)"""
import os
from pathlib import Path

import pytest

REAL = (Path(__file__).resolve().parent.parent / "data").resolve()


def _motivo() -> str:
    d = os.environ.get("LOVABLE_DATA_DIR", "").strip()
    if not d:
        return "LOVABLE_DATA_DIR não definida"
    try:
        alvo = Path(d).resolve()
    except OSError:
        return f"LOVABLE_DATA_DIR inválida: {d!r}"
    if alvo == REAL or REAL in alvo.parents or alvo in REAL.parents:
        return f"LOVABLE_DATA_DIR aponta para a pasta de dados REAL ({alvo})"
    return ""


_m = _motivo()
if _m:
    pytest.exit(
        "TRAVA DOS TESTES (ORDEM 046): " + _m + ".\n"
        "Os testes apagam e renumeram dados. Rode com uma pasta temporária vazia, por exemplo:\n"
        "  LOVABLE_DATA_DIR=%TEMP%\\jdb_teste_123 python -m pytest tests -q\n"
        "Nada foi aberto nem alterado no banco real.", returncode=3)


# ------------------------------------------------------------------ ORDEM 165: peças que os testes de rota usam
# (importadas só aqui embaixo, DEPOIS da trava: o app nunca abre o banco real)
def make_user(email: str, senha: str = "senha-de-teste-165") -> tuple[int, str]:
    """Usuário de teste no banco TEMPORÁRIO: (id, token). Se já existe, reaproveita."""
    from lovable import auth
    auth.init()
    u = auth.user_by_email(email)
    uid = u["id"] if u else auth.criar_usuario(email, senha)
    return uid, auth.make_token(uid)


@pytest.fixture()
def client():
    """Cliente HTTP do app inteiro (sem abrir porta), no banco temporário."""
    from fastapi.testclient import TestClient
    from lovable import main
    with TestClient(main.app) as c:
        yield c
    # ao fechar, o TestClient roda o desligamento do app, que liga "encerrando" no orquestrador (falha de IA vira
    # "interrupção"); num processo de teste isso vazaria para os testes seguintes — volta ao normal aqui
    from lovable.avaliacao import orquestrador
    orquestrador._encerrando = False
