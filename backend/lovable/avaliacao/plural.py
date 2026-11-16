"""ORDEM 029-6: plural certo nas mensagens do servidor e no laudo (nada de "anúncio(s)")."""


def pl(n: int, um: str, varios: str) -> str:
    """pl(1, "anúncio novo", "anúncios novos") -> "1 anúncio novo"; pl(3, ...) -> "3 anúncios novos"."""
    return f"{n} {um if n == 1 else varios}"


def sv(n: int, um: str, varios: str) -> str:
    """Só a palavra, sem o número: sv(1, "escolhido", "escolhidos")."""
    return um if n == 1 else varios
