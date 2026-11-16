"""Substituto local de lovable.evolution."""
import re


def normalize_phone(tel: str) -> str:
    return re.sub(r"\D", "", tel or "")
