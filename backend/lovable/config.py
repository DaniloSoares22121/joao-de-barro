"""Configuração do servidor do João de Barro (variáveis de ambiente; `.env` na raiz do repo)."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:  # sem python-dotenv: só o ambiente
    pass

DATA_DIR = Path(os.environ.get("LOVABLE_DATA_DIR", BASE_DIR / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

HOST = os.environ.get("JDB_HOST", "127.0.0.1")
PORT = int(os.environ.get("JDB_PORT", "8870"))

# IA: Claude pelo Agent SDK. Com ANTHROPIC_API_KEY no ambiente usa a chave; sem ela usa o
# login do Claude Code deste computador (`claude` → /login).
MODEL = os.environ.get("LOVABLE_MODEL", "claude-sonnet-5")
FALLBACK_MODEL = os.environ.get("LOVABLE_FALLBACK_MODEL", "claude-sonnet-5")
LIGHT_MODEL = os.environ.get("LOVABLE_LIGHT_MODEL", "claude-haiku-5-5").strip()
CLAUDE_CLI = os.environ.get("LOVABLE_CLAUDE_CLI", "").strip()
_e = os.environ.get("LOVABLE_EFFORT", "").strip().lower()
ESFORCO = _e if _e in ("low", "medium", "high") else ""
