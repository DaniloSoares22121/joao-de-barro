"""Reconhece, no texto de um erro, o que é limite de uso de verdade."""
import re

# Só o que é limite DE VERDADE: "Maximum call stack size exceeded" ou "insufficient
# permissions" não são conta esgotada.
_RATE_RE = re.compile(
    r"rate.?limit|rate_limit|usage limit|limit reached|(?:reached|hit) your .{0,30}limit|"
    r"weekly limit|"
    r"exceeded your .{0,30}limit|too many requests|overloaded|429|"
    r"quota (?:exceeded|exhausted|reached)|out of (?:quota|credits?)|"
    r"insufficient (?:quota|credits?|balance|funds)|(?:over|at) capacity",
    re.IGNORECASE,
)


def is_rate_limit(text: str | None) -> bool:
    return bool(text) and bool(_RATE_RE.search(text or ""))
