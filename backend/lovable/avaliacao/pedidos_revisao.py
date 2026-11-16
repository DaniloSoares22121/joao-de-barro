"""114: o quadro único da revisão — cada par "Onde fica: / O que mudar:" vira um pedido separado.

"Onde fica" vazio com "O que mudar" preenchido = pedido geral; par vazio é ignorado; texto livre fora do modelo
continua aceito (vira um pedido, como antes).
"""
from __future__ import annotations

import re

_ONDE = re.compile(r"(?im)^\s*onde\s+fica\s*:\s*(.*)$")
_OQUE = re.compile(r"(?im)^\s*o\s+que\s+mudar\s*:\s*(.*)$")
_SEPARADOR = re.compile(r"(?m)^\s*[=\-_*~#]{3,}\s*$")


def local(onde: str) -> str:
    """"8" → "Na página 8: "; "7.4" ou "item 7.4" → "No item 7.4: "; outra coisa → "Em …: "; vazio → ""."""
    o = (onde or "").strip().rstrip(".:;")
    if not o:
        return ""
    if re.fullmatch(r"\d+", o):
        return f"Na página {o}: "
    if re.fullmatch(r"\d+(?:\.\d+)+", o):
        return f"No item {o}: "
    if re.match(r"(?i)item\b", o):
        return f"No {o}: "
    if re.match(r"(?i)p[aá]g(?:ina)?\.?\b", o):
        return f"Na {o}: "
    return f"Em {o}: "


def dividir(texto: str) -> list[str]:
    """Os pedidos do quadro, na ordem; [] se não houver nada escrito além do modelo."""
    t = (texto or "").replace("\r\n", "\n")
    if not _OQUE.search(t) and not _ONDE.search(t):
        # 117-1: texto livre com os pedidos separados por linhas "=====", "-----" ou "*****" → um pedido por bloco
        blocos = [b.strip() for b in _SEPARADOR.split(t)]
        return [b for b in blocos if b]
    pedidos: list[str] = []
    livre: list[str] = []
    onde = None            # "Onde fica" do par em aberto
    oque: list[str] | None = None

    def fechar():
        nonlocal onde, oque
        if oque is not None:
            corpo = "\n".join(x for x in oque).strip()
            if corpo:
                pedidos.append(local(onde or "") + corpo)
        onde, oque = None, None

    for linha in t.split("\n"):
        m_onde, m_oque = _ONDE.match(linha), _OQUE.match(linha)
        if m_onde:
            fechar()
            onde = m_onde.group(1).strip()
        elif m_oque:
            if oque is not None:
                fechar()
            oque = [m_oque.group(1).strip()]
        elif oque is not None and not linha.strip():
            fechar()                    # linha em branco encerra o pedido
        elif oque is not None:
            oque.append(linha)          # "O que mudar" de várias linhas
        elif linha.strip():
            livre.append(linha.strip()) # texto livre fora do modelo
    fechar()
    if livre:
        pedidos.append(" ".join(livre))
    return pedidos
