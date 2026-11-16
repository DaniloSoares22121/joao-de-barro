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


# ------------------------------------------------------------------ K0 / K2 (ORDEM 038)
# K0 = camada geral (igual para todo avaliador); K2 = camada do avaliador (Alan). No lugar do
# P0 inteiro, a IA recebe só "Como usar" + K0.1 (princípios) + as partes da ETAPA PRINCIPAL
# da chamada (a 1ª etapa pedida), para não subir o custo. K1 vira fichas (fichas.py); K3 fica
# guardado para a tela de entrada de avaliador novo (fase futura, não usado aqui).
IDENTIDADE = ("Você é o JOÃO DE BARRO, agente técnico de avaliação imobiliária. Trabalha para o "
              "avaliador descrito na camada do avaliador (K2). Nos documentos, tom 100% técnico e "
              "profissional, em português do Brasil. Use a base geral (K0) e as fichas abaixo; o que "
              "não estiver nelas e não vier de fonte oficial: diga que ainda não tem base.")
K0_DA_ETAPA = {
    "documentos": ("K0.3", "K0.4"), "áreas": ("K0.4",), "vistoria": ("K0.5",), "fotos": ("K0.5",),
    "localização": ("K0.5",), "pesquisa": ("K0.6",), "cálculo": ("K0.7",),
    "redação": ("K0.2", "K0.8"), "revisão": ("K0.9",), "proposta/contrato": ("K0.10",),
}
K2_DA_ETAPA = {"redação": ("Laudos",), "revisão": ("Laudos",), "cálculo": ("Laudos",),
               "proposta/contrato": ("Comercial",)}


def _secoes(md: str, padrao: str) -> dict[str, str]:
    """{título curto: texto} das seções "## ..." do markdown; "intro" = antes da 1ª seção."""
    partes = re.split(r"\n(?=## )", md)
    out = {"intro": partes[0].strip()}
    for p in partes[1:]:
        m = re.match(padrao, p)
        if m:
            out[m.group(1)] = p.strip()
    return out


def _principais(etapas) -> list[str]:
    """Etapa principal (a 1ª); a seleção (pesquisa + cálculo) leva também o cálculo."""
    if not etapas:
        return []
    out = [etapas[0]]
    if etapas[0] == "pesquisa" and "cálculo" in etapas:
        out.append("cálculo")
    return out


def k0_secoes() -> dict[str, str]:
    s = _secoes(_ler("K0"), r"## (K0\.\d+|Como usar)")
    return s


def k0(etapas: tuple[str, ...] | list[str] = ()) -> str:
    """K0 para a chamada: "Como usar" + K0.1 + as partes da etapa principal (etapas[0]).
    Sem etapa: o K0 inteiro."""
    s = k0_secoes()
    if not etapas:
        return _ler("K0").strip()
    pedidas = ["Como usar", "K0.1"] + [x for e in _principais(etapas) for x in K0_DA_ETAPA.get(e, ())]
    return "\n\n".join(s[k] for k in dict.fromkeys(pedidas) if k in s)


def k2(etapas: tuple[str, ...] | list[str] = ()) -> str:
    """Camada do avaliador (Alan): identificação sempre; padrões de laudo ou comercial conforme
    a etapa principal. Vale acima da K0, salvo conflito com fonte oficial."""
    s = _secoes(_ler("K2"), r"## (Identificação|Identidade visual|Laudos|Comercial|Rede|Como ele)")
    pedidas = ["Identificação"] + [x for e in _principais(etapas) for x in K2_DA_ETAPA.get(e, ())]
    return "\n\n".join(s[k] for k in pedidas if k in s)


def geral(etapas: tuple[str, ...] | list[str] = ()) -> str:
    """O que substitui o P0: identidade curta + K0 da etapa + K2 (camada do avaliador)."""
    return (f"===== IDENTIDADE =====\n{IDENTIDADE}\n\n===== K0 — BASE GERAL (partes da etapa) =====\n"
            f"{k0(etapas)}\n\n===== K2 — CAMADA DO AVALIADOR =====\n{k2(etapas)}")


def base(job_id: str, docs: tuple[str, ...], etapas: tuple[str, ...] = ()) -> str:
    """ORDEM 026-F1: o que a IA recebe — os documentos fixos pedidos SEM o P3 inteiro, mais as
    fichas do caso (tipo de imóvel, modalidade e etapa) na ordem de busca. Sem fichas
    importadas (base vazia), cai no P3 inteiro como antes.
    ORDEM 038: o P0 é trocado pelo K0 da etapa + K2 (`geral`)."""
    from . import fichas
    usa_k0 = "P0" in docs
    docs = tuple(d for d in docs if d != "P0")
    resto = tuple(d for d in docs if d != "P3")
    try:
        bloco = fichas.texto_ia_job(job_id, etapas) if fichas.todas(incluir_inativas=False) else ""
    except Exception:
        bloco = ""
    cab = geral(etapas) + "\n\n" if usa_k0 else ""
    if not bloco:
        return cab + texto(*docs) if docs else cab.strip()
    return cab + (texto(*resto) + "\n\n" if resto else "") + bloco
