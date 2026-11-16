"""Detecção de limite de uso da IA (substitui o router do Brixly)."""
import re

_PADRAO = re.compile(r"rate.?limit|usage limit|hit your .*limit|limit reached|too many requests|\b429\b|overloaded",
                     re.I)


def is_rate_limit(texto: str) -> bool:
    return bool(_PADRAO.search(texto or ""))
