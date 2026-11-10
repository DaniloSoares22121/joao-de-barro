"""Normalização de telefone brasileiro (só dígitos, com DDI 55)."""
import re


def normalize_phone(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if not d:
        return ""
    return d if d.startswith("55") and len(d) >= 12 else "55" + d
