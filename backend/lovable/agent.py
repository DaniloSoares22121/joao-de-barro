"""Modelos que sempre "pensam": neles o controle é o esforço, não max_thinking_tokens."""
_PENSA_SEMPRE = ("opus-5-5", "sonnet-5-5", "fable-5", "mythos-5")


def _pensa_sempre(modelo: str) -> bool:
    m = (modelo or "").lower()
    return any(k in m for k in _PENSA_SEMPRE)
