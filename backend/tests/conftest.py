"""Testes rodam num banco e numa pasta de dados temporários (nunca nos dados de verdade)."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["LOVABLE_DATA_DIR"] = tempfile.mkdtemp(prefix="jdb-testes-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from lovable import auth  # noqa: E402
from lovable.main import app  # noqa: E402


def make_user(email: str = "t@test.local") -> tuple[int, str]:
    """Usuário direto no banco; devolve (id, token)."""
    auth.init()
    with auth._conn() as c:
        c.execute("INSERT OR IGNORE INTO users (email, pwd, created_at) VALUES (?,?,datetime('now'))",
                  (email, "x"))
        uid = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
    return uid, auth.make_token(uid)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
