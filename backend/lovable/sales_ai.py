"""Substituto local de lovable.sales_ai: variáveis de ambiente extras do CLI do Claude."""


def _sub_env() -> dict:
    # Sem extras: o CLI usa o login do Claude Code desta máquina ou a ANTHROPIC_API_KEY.
    return {}
