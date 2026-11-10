"""Base de conhecimento do João de Barro: textos P0–P8/A/B e importação de P3 (decisões)
e P4 (normas) para o banco. Material C/H nunca entra aqui."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import db

PASTA = Path(__file__).parent / "assets" / "conhecimento"


def _arquivo(id_: str) -> Path:
    for p in sorted(PASTA.iterdir()):
        if p.stem == id_:
            return p
    raise KeyError(f"documento de conhecimento inexistente: {id_}")


@lru_cache(maxsize=None)
def _ler(id_: str) -> str:
    p = _arquivo(id_)
    if p.suffix.lower() == ".pdf":
        import pymupdf
        with pymupdf.open(p) as d:
            return "\n".join(pg.get_text() for pg in d)
    return p.read_text(encoding="utf-8")


def texto(*ids: str) -> str:
    """Concatena os documentos pedidos, cada um sob um cabeçalho com seu id."""
    return "\n\n".join(f"===== {i} =====\n{_ler(i).strip()}" for i in ids)


def _linhas_tabela(md: str) -> list[list[str]]:
    """Linhas de dados de tabelas markdown (ignora separadores |---|)."""
    out = []
    for ln in md.splitlines():
        ln = ln.strip()
        if not (ln.startswith("|") and ln.endswith("|")):
            continue
        cels = [c.strip() for c in ln[1:-1].split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cels if c):
            continue
        out.append(cels)
    return out


def importar_decisoes() -> int:
    """P3 → av_decisions (insere só códigos D-xxx ausentes; edições feitas na config ficam). Devolve quantas decisões leu."""
    db.init()
    regs = []
    for c in _linhas_tabela(_ler("P3")):
        if len(c) < 8 or not re.fullmatch(r"D-\d{3,}", c[0]):
            continue
        regs.append((c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7]))
    # só insere códigos ausentes: o que foi editado em tempo de execução (config) prevalece
    db.upsert_decisoes([dict(zip(db._DEC, r)) for r in regs], sobrescrever=False)
    return len(regs)


def importar_normas() -> int:
    """P4 → av_norms (insere só códigos ausentes, N1, N5a...). Revogadas/removidas ficam vigente=0."""
    db.init()
    linhas = _linhas_tabela(_ler("P4"))
    cab = None
    regs = []
    for c in linhas:
        if c and c[0] == "#":
            cab = c
            continue
        if cab is None or not re.fullmatch(r"N\d+[a-z]?", c[0]):
            continue
        item = dict(zip(cab[1:], c[1:]))
        status = (item.get("Status verificado", "") + " " + item.get("Ação", "")).upper()
        vigente = 0 if ("REVOGAD" in status or "REMOVID" in status) else 1
        regs.append((c[0], c[1] if len(c) > 1 else "", json.dumps(item, ensure_ascii=False), vigente))
    db.upsert_normas([{"codigo": c, "titulo": t, "itens": json.loads(i), "vigente": bool(v)}
                      for c, t, i, v in regs], sobrescrever=False)
    return len(regs)


def normas_todas() -> list[dict]:
    """Todas as normas (vigentes ou não), com `vigente` booleano — para a tela de configuração."""
    with db._conn() as con:
        rows = con.execute("SELECT * FROM av_norms ORDER BY rowid").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["itens"] = json.loads(d.pop("itens_json"))
        d["vigente"] = bool(d["vigente"])
        out.append(d)
    return out


def normas_vigentes() -> list[dict]:
    with db._conn() as con:
        rows = con.execute("SELECT * FROM av_norms WHERE vigente=1 ORDER BY rowid").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["itens"] = json.loads(d.pop("itens_json"))
        out.append(d)
    return out
