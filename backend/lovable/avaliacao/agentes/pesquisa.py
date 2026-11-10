"""Agente de Pesquisa: a IA gera as consultas; a busca e a deduplicação são em código."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field

from .. import conhecimento, db, fonte_mercado, ia
from ..fonte_mercado import Consulta
from ..modelos import Referencial
from ..portais import slug
from . import _comum

MIN_RESULTADOS = 5

INSTRUCAO = """\
ETAPA ATUAL: PESQUISA DE REFERENCIAIS.
Gere de 3 a 6 consultas de anúncios de venda semelhantes ao imóvel avaliando
(mesma tipologia, bairro do avaliando primeiro; faixas de área e quartos compatíveis).
Se houver poucos resultados, relaxe o bairro para setores vizinhos/limítrofes da mesma
cidade, mantendo a tipologia. Responda com {"consultas": [...]}.
"""


class _Consultas(BaseModel):
    consultas: list[Consulta] = Field(default_factory=list)


def link_limpo(link: str) -> str:
    """Remove query string e fragmento (utm etc.) e a barra final."""
    p = urlsplit(link.strip())
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", ""))


def deduplicar(refs: list[Referencial]) -> list[Referencial]:
    """Por link limpo e por (preço, área, bairro)."""
    vistos_link: set[str] = set()
    vistos_chave: set[tuple] = set()
    out = []
    for r in refs:
        lk = link_limpo(r.link)
        tem_chave = r.preco is not None and r.area_m2 is not None
        chave = (r.preco, r.area_m2, " ".join(r.bairro.casefold().split()))
        if lk in vistos_link or (tem_chave and chave in vistos_chave):
            continue
        vistos_link.add(lk)
        if tem_chave:
            vistos_chave.add(chave)
        out.append(r)
    return out


@lru_cache(maxsize=1)
def vizinhos_goiania() -> dict[str, list[str]]:
    """assets/goiania_vizinhos.json: bairro normalizado -> setores limítrofes."""
    d = json.loads((Path(__file__).resolve().parent.parent / "assets" / "goiania_vizinhos.json")
                   .read_text(encoding="utf-8"))
    return {k: v for k, v in d.items() if not k.startswith("_")}


def consultas_vizinhos(bairro: str, cidade: str, base: list[Consulta]) -> list[Consulta]:
    """2ª rodada pela lista fixa de vizinhos (Goiânia): as consultas da 1ª rodada no bairro
    do avaliando repetidas em cada vizinho. [] se o bairro não estiver na lista."""
    if slug(cidade) != "goiania":
        return []
    viz = vizinhos_goiania().get(slug(bairro))
    if not viz:
        return []
    modelos = [c for c in base if slug(c.bairro) == slug(bairro)] or base[:1] or [
        Consulta(tipologia="", bairro=bairro, cidade=cidade)]
    out = []
    for v in viz:
        for c in modelos[:2]:
            out.append(c.model_copy(update={"bairro": v, "cidade": c.cidade or cidade}))
    return out[:12]


async def _consultas(sistema: str, prompt: str) -> list[Consulta]:
    r: _Consultas = await ia.perguntar(sistema, prompt, _Consultas)
    return r.consultas[:6]


async def rodar(job_id: str) -> list[Referencial]:
    t = _comum.trabalho(job_id)
    fonte = fonte_mercado.atual()
    sistema = conhecimento.texto("P0", "P3") + "\n\n" + INSTRUCAO
    campos = [c.model_dump(mode="json") for c in db.campos(job_id)]
    prompt = ("Trabalho:\n" + t.model_dump_json(indent=2)
              + f"\n\nCampos extraídos:\n{campos}")
    try:
        consultas = await _consultas(sistema, prompt)
        refs = deduplicar(await fonte.buscar(job_id, consultas))
        if len(refs) < MIN_RESULTADOS:
            mais = consultas_vizinhos(t.bairro, t.cidade, consultas)
            if mais:
                db.evento(job_id, "pesquisa", "info", "2ª rodada nos setores vizinhos: "
                          + ", ".join(sorted({c.bairro for c in mais})))
            else:  # bairro fora da lista de vizinhos: a IA sugere
                mais = await _consultas(sistema, prompt + (
                    f"\n\nAs consultas anteriores trouxeram só {len(refs)} anúncio(s): "
                    f"{[c.model_dump() for c in consultas]}. Relaxe o bairro para setores "
                    "vizinhos."))
            consultas += mais
            refs = deduplicar(refs + await fonte.buscar(job_id, mais))
    finally:
        fim = getattr(fonte, "encerrar", None)   # zera os limites por trabalho da fonte real
        if fim is not None:
            fim(job_id)
    refs = [r.model_copy(update={"n": i}) for i, r in enumerate(refs, 1)]
    db.salvar_candidatos(job_id, refs, substituir=True)
    maps = getattr(fonte, "capturar_maps", None)   # só a fonte real (Coletor) captura o Maps
    if maps is not None:
        try:
            await maps(job_id, t)
        except Exception as e:  # nunca joga fora uma pesquisa pronta
            from ..docx_builder import SEM_LOCALIZACAO
            db.evento(job_id, "pesquisa", "aviso", f"{SEM_LOCALIZACAO}: {e}")
    db.evento(job_id, "pesquisa", "resultado", f"{len(refs)} candidato(s)",
              dados={"consultas": [c.model_dump(mode="json") for c in consultas],
                     "candidatos": [r.model_dump(mode="json") for r in refs]})
    return refs
