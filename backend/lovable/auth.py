"""Autenticação local mínima (substitui a do Brixly): usuários no app.db, senha com PBKDF2
e token Bearer assinado com HMAC."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time

from . import config

TOKEN_DIAS = 30


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.DATA_DIR / "app.db", timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _segredo() -> bytes:
    p = config.DATA_DIR / "segredo.key"
    if not p.exists():
        p.write_bytes(secrets.token_bytes(32))
    return p.read_bytes()


def init() -> None:
    with _conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                  "email TEXT NOT NULL UNIQUE, senha TEXT NOT NULL, blocked INTEGER NOT NULL DEFAULT 0)")


def _hash(senha: str, sal: bytes | None = None) -> str:
    sal = sal or secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, 200_000)
    return f"{sal.hex()}${h.hex()}"


def _confere(senha: str, guardado: str) -> bool:
    sal, _, h = guardado.partition("$")
    return hmac.compare_digest(_hash(senha, bytes.fromhex(sal)).split("$")[1], h)


def criar_usuario(email: str, senha: str) -> int:
    with _conn() as c:
        cur = c.execute("INSERT INTO users (email, senha) VALUES (?, ?)",
                        (email.strip().casefold(), _hash(senha)))
        return int(cur.lastrowid)


def _linha(r) -> dict | None:
    return {"id": r["id"], "email": r["email"], "blocked": bool(r["blocked"])} if r else None


def get_user(uid: int) -> dict | None:
    with _conn() as c:
        return _linha(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


def user_by_email(email: str) -> dict | None:
    with _conn() as c:
        return _linha(c.execute("SELECT * FROM users WHERE email=?",
                                (email.strip().casefold(),)).fetchone())


def login(email: str, senha: str) -> str | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM users WHERE email=?", (email.strip().casefold(),)).fetchone()
    if not r or r["blocked"] or not _confere(senha, r["senha"]):
        return None
    return make_token(r["id"])


def _assinar(corpo: str) -> str:
    return base64.urlsafe_b64encode(hmac.new(_segredo(), corpo.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def make_token(uid: int) -> str:
    corpo = f"{uid}.{int(time.time()) + TOKEN_DIAS * 86400}"
    return f"{corpo}.{_assinar(corpo)}"


def user_id_from_token(token: str) -> int | None:
    try:
        uid, exp, sig = token.split(".")
        if not hmac.compare_digest(sig, _assinar(f"{uid}.{exp}")) or int(exp) < time.time():
            return None
        return int(uid)
    except (ValueError, TypeError):
        return None


def admin_make_token() -> str:
    corpo = f"admin.{int(time.time()) + 3600}"
    return f"{corpo}.{_assinar(corpo)}"


def admin_ok(token: str) -> bool:
    try:
        a, exp, sig = token.split(".")
        return a == "admin" and hmac.compare_digest(sig, _assinar(f"{a}.{exp}")) and int(exp) >= time.time()
    except ValueError:
        return False


_lock = threading.Lock()
_janelas: dict[str, list[float]] = {}


def rate_limit(chave: str, maximo: int, janela_s: int) -> bool:
    """True se ainda cabe mais uma tentativa na janela (e registra a tentativa)."""
    agora = time.time()
    with _lock:
        ts = [t for t in _janelas.get(chave, []) if agora - t < janela_s]
        if len(ts) >= maximo:
            _janelas[chave] = ts
            return False
        ts.append(agora)
        _janelas[chave] = ts
        return True
