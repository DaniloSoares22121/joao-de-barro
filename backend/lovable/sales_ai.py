"""Ambiente do CLI do Claude. Com ANTHROPIC_API_KEY (no .env ou no sistema) usa a chave;
sem ela, o CLI usa o login do Claude Code deste computador."""
import os


def _sub_env() -> dict:
    env = {}
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CONFIG_DIR"):
        v = (os.environ.get(k) or "").strip()
        if v:
            env[k] = v
    return env
