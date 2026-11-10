"""Contas e sessão do servidor do João de Barro.

Senha com PBKDF2-SHA256; sessão = token HMAC-SHA256 (id.expira.assinatura) assinado com um
segredo gerado na primeira subida e guardado no banco. Sem JWT, sem dependência externa."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone

from . import config

VALIDADE_S = 30 * 24 * 3600
_ITER = 240_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, pwd TEXT NOT NULL,
    blocked INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.DATA_DIR / "app.db", timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA)


def _segredo() -> bytes:
    with _conn() as c:
        r = c.execute("SELECT v FROM kv WHERE k='secret'").fetchone()
        if r:
            return r["v"].encode()
        s = secrets.token_urlsafe(48)
        c.execute("INSERT OR IGNORE INTO kv (k, v) VALUES ('secret', ?)", (s,))
        return c.execute("SELECT v FROM kv WHERE k='secret'").fetchone()["v"].encode()


# ------------------------------------------------------------------ senha
def _hash_pwd(pwd: str, sal: bytes | None = None) -> str:
    sal = sal or os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pwd.encode(), sal, _ITER)
    return f"pbkdf2${_ITER}${sal.hex()}${h.hex()}"


def _confere(pwd: str, guardado: str) -> bool:
    try:
        _, it, sal, h = guardado.split("$")
        novo = hashlib.pbkdf2_hmac("sha256", pwd.encode(), bytes.fromhex(sal), int(it))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(novo.hex(), h)


# ------------------------------------------------------------------ usuários
def _row_to_user(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "email": r["email"], "blocked": bool(r["blocked"])}


def get_user(user_id: int) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return _row_to_user(r) if r else None


def user_by_email(email: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM users WHERE email=?", ((email or "").strip().lower(),)).fetchone()
    return _row_to_user(r) if r else None


def criar_ou_trocar_senha(email: str, pwd: str) -> int:
    """Cria a conta (ou troca a senha da existente). Devolve o id."""
    email = (email or "").strip().lower()
    if "@" not in email or len(pwd or "") < 6:
        raise ValueError("E-mail inválido ou senha muito curta (mín. 6).")
    init()
    with _conn() as c:
        c.execute("INSERT INTO users (email, pwd, created_at) VALUES (?,?,?) "
                  "ON CONFLICT(email) DO UPDATE SET pwd=excluded.pwd",
                  (email, _hash_pwd(pwd), datetime.now(timezone.utc).isoformat()))
        return c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]


def entrar(email: str, pwd: str) -> str | None:
    """Token da sessão, ou None se e-mail/senha não conferem."""
    with _conn() as c:
        r = c.execute("SELECT * FROM users WHERE email=?", ((email or "").strip().lower(),)).fetchone()
    if not r or r["blocked"] or not _confere(pwd or "", r["pwd"]):
        return None
    return token_de(r["id"])


# ------------------------------------------------------------------ token
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def token_de(user_id: int) -> str:
    corpo = f"{user_id}.{int(time.time()) + VALIDADE_S}"
    return f"{corpo}.{_b64(hmac.new(_segredo(), corpo.encode(), hashlib.sha256).digest())}"


make_token = token_de


def user_id_from_token(token: str) -> int | None:
    try:
        uid, exp, sig = (token or "").split(".")
        corpo = f"{uid}.{exp}"
        bom = _b64(hmac.new(_segredo(), corpo.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, bom) or int(exp) < time.time():
            return None
        return int(uid)
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------------ limite de tentativas
def rate_limit(key: str, limit: int, window_s: int) -> bool:
    """Janela fixa. True se permitido (e conta), False se estourou. Incremento atômico."""
    win = int(time.time()) // max(1, window_s)
    k = f"rl:{key}:{win}"
    with _conn() as c:
        c.execute("INSERT INTO kv (k, v) VALUES (?, '1') "
                  "ON CONFLICT(k) DO UPDATE SET v = CAST(v AS INTEGER) + 1", (k,))
        n = int(c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()["v"])
        if n == 1:  # janela nova: limpa as antigas
            c.execute("DELETE FROM kv WHERE k LIKE 'rl:%' AND k != ? AND "
                      "CAST(substr(k, length(rtrim(k, '0123456789')) + 1) AS INTEGER) < ?",
                      (k, win - 2))
    return n <= limit
