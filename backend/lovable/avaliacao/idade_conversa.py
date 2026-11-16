"""111-3b: a idade dos anúncios que o avaliador escreve na conversa vale nos anúncios e fecha os cartões.

Lê frases como "os referenciais 1, 2, 3, 4, 5 e 8 têm 30 anos", "o anúncio 6 é novo", "o 7 não informa".
Sem IA: só número de anúncio + idade explícita; o que não for claro fica como está.
"""
from __future__ import annotations

import re

from . import db

_LISTA = re.compile(r"(?i)\b(?:referenciais|referencial|an[uú]ncios?|refs?\.?|n[ºo°]|n\.º|o|os|e o)\s+"
                    r"((?:\d{1,2}\s*(?:,|\be\b)\s*)*\d{1,2})\b(?!\s*(?:anos|m²|m2|%))")
_ANOS = re.compile(r"(?i)\b(\d{1,3})\s*anos\b")
_NOVO = re.compile(r"(?i)\b(seminov[oa]|nov[oa]|rec[eé]m[- ]constru[ií]d[oa])\b")
_SEM = re.compile(r"(?i)n[aã]o\s+(?:informa|diz|tem|traz)|sem\s+idade|\bn/i\b")


def ler(texto: str) -> dict[int, str]:
    """{nº do anúncio: idade}; idade "" = o anúncio não informa (sai n/i)."""
    out: dict[int, str] = {}
    limpo = re.sub(r"\([^)]*\)", " ", texto or "")          # "(Rua JC-18, só comparação)" não é número de anúncio
    if not re.search(r"(?i)idade|anos|nov[oa]|n[aã]o\s+informa", limpo):
        return out
    for frase in re.split(r"(?<=[.;!?\n])\s+", limpo):
        nums: list[int] = []
        for m in _LISTA.finditer(frase):
            nums += [int(x) for x in re.findall(r"\d{1,2}", m.group(1))]
        if not nums:
            continue
        if _SEM.search(frase):
            idade = ""
        elif (a := _ANOS.search(frase)):
            idade = f"{int(a.group(1))} anos"
        elif (nv := _NOVO.search(frase)):
            idade = "seminovo" if nv.group(1).lower().startswith("semi") else "novo"
        else:
            continue
        for n in nums:
            out.setdefault(n, idade)
    return out


def aplicar(job_id: str, texto: str) -> list[int]:
    """Grava as idades lidas nos anúncios do trabalho (fonte "avaliador") e fecha os cartões. Devolve os nº gravados."""
    idades = ler(texto)
    if not idades:
        return []
    from . import pendencias_simples as PS
    from .routes import _salvar_ref
    feitos = []
    for r in db.candidatos(job_id):
        if r.n not in idades:
            continue
        _salvar_ref(job_id, r.model_copy(update={"idade_aparente": idades[r.n], "idade_fonte": "avaliador"}),
                    "idade dita na conversa")
        PS.aceitar(job_id, f"idade_foto:{r.n}")
        feitos.append(r.n)
    if feitos:
        db.evento(job_id, "pesquisa", "edicao_manual", "idade aparente dita pelo avaliador na conversa: "
                  + "; ".join(f"anúncio {n}: {idades[n] or 'não informa'}" for n in feitos))
    return feitos
