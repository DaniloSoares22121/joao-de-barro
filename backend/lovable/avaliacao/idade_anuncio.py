"""ORDEM 105-2b: idade aparente dos anúncios (referenciais do 9.1 e comparação do 9.3).

Regra do Capitão: "novo" é idade aparente válida. Ordem de leitura:
  1. o que o anúncio diz (título e descrição) — sem custo: anos, "novo"/"seminovo", "construída em 2015";
  2. se o anúncio não diz: a IA leve olha a foto principal e estima ("inferido pelas fotos"); o avaliador confirma com
     1 toque na tela dos anúncios (o cartão é do outro executor);
  3. sem foto que permita dizer: "n/i".
"excelente", "bom", "reformado" são ESTADO, nunca idade.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from . import db, ia

# "nova" sozinho pega bairro (Vila Nova, Nova Suíça): só vale depois de casa/sobrado/imóvel/apartamento/construção
_NOVO = re.compile(r"(?i)\b(?:(?:casa|sobrado|im[óo]vel|apartamento|apto|constru[çc][ãa]o|resid[êe]ncia)\s+(?:\w+\s+)?nov[ao]\b"
                   r"(?!\s+(?:su[íi]|esperan|vila|americ))|rec[ée]m[- ]constru[íi]d[ao]|"
                   r"nunca\s+habitad[ao]|entrega\s+(?:recente|imediata)|na\s+planta|lan[çc]amento|primeira\s+loca[çc][ãa]o)\b")
_SEMINOVO = re.compile(r"(?i)\bsemi[- ]?nov[ao]\b")
_ANOS = re.compile(r"(?i)\b(\d{1,2})\s*anos\s*(?:de\s+(?:constru[çc][ãa]o|constru[íi]d[ao]|idade|uso)|de\s+vida)")
_TEM_ANOS = re.compile(r"(?i)\b(?:tem|com|possui|idade(?:\s+aparente)?(?:\s+de)?:?)\s*(\d{1,2})\s*anos\b")
_ANO = re.compile(r"(?i)\bconstru[íi]d[ao]\s+em\s+((?:19|20)\d{2})\b")
_ESTADO = re.compile(r"(?i)^(?:excelente|[óo]timo|bom|boa|regular|ruim|reformad[ao]|conservad[ao])\b")


def idade_valida(v) -> str | None:
    """A idade aparente que vale no laudo: "N anos", "novo" ou "seminovo". Estado ("excelente") não é idade."""
    t = " ".join(str(v or "").split())
    if not t or t.lower() in ("n/i", "—", "-") or _ESTADO.match(t):
        return None
    m = re.match(r"(?i)^(?:cerca\s+de\s+)?(\d{1,2})\s*(?:anos?)?\b(.*)$", t)
    if m:
        return f"{int(m.group(1))} anos" + ((" " + m.group(2).strip()) if m.group(2).strip() else "")
    if _SEMINOVO.search(t):
        return "seminovo"
    if re.match(r"(?i)^nov[ao]\b", t) or _NOVO.search(t):
        return "novo"
    return None


def idade_do_texto(texto: str, hoje: date | None = None) -> str | None:
    """O que o próprio anúncio diz da idade (sem IA)."""
    t = texto or ""
    m = _ANO.search(t)
    if m:
        anos = (hoje or date.today()).year - int(m.group(1))
        return "novo" if anos <= 1 else f"{anos} anos"
    for rx in (_ANOS, _TEM_ANOS):
        m = rx.search(t)
        if m and 0 < int(m.group(1)) <= 80:
            return f"{int(m.group(1))} anos"
    if _SEMINOVO.search(t):
        return "seminovo"
    if _NOVO.search(t):
        return "novo"
    return None


class _Estimativa(BaseModel):
    idade: str = Field(description='"novo", "seminovo", "cerca de N anos" ou "n/i" se a foto não permite dizer')
    motivo: str = Field(default="", description="o que na foto indica a idade, em uma frase")


SISTEMA = """Você é avaliador de imóveis. Olhe a foto principal do anúncio e estime a IDADE APARENTE da construção
(não o estado de conservação): "novo" (obra recente, acabamento atual, sem desgaste), "seminovo", ou "cerca de N anos".
Se a foto não mostra a construção (fachada, cômodos), responda "n/i". Não invente: na dúvida, "n/i"."""


_RELATO_REFS = re.compile(r"(?i)\b(\d{1,2})\s*anos\s+(?:n[oa]s?|para\s+[oa]s|d[oa]s)\s+(?:referenciais|amostras|an[úu]ncios)\b")


def idade_do_relato(job_id: str) -> str | None:
    """110-2 (D-071): a idade que o avaliador deu aos referenciais no relato ("30 anos nos referenciais")."""
    try:
        from . import tela_trabalho
        ctx = (tela_trabalho._cliente(job_id) or {}).get("contexto") or {}
    except Exception:          # noqa: BLE001
        return None
    textos = [str(ctx.get("checklist") or "")] + [str(x) for x in db.instrucoes_avaliador(job_id)]
    for t in textos:
        m = _RELATO_REFS.search(t)
        if m and 0 < int(m.group(1)) <= 80:
            return f"{int(m.group(1))} anos"
    return None


def _da_amostra(ref) -> bool:
    return getattr(ref, "decisao", "") != "comparacao"


async def estimar(job_id: str, ref) -> tuple[str, str]:
    """(idade, fonte): fonte "relato" (o avaliador deu aos referenciais — vale sobre tudo, só na amostra do 9.1),
    "anúncio" (lido), "fotos" (estimado pela IA leve) ou "" (n/i)."""
    rel = idade_do_relato(job_id) if _da_amostra(ref) else None
    if rel:
        return rel, "relato"
    ja = idade_valida(getattr(ref, "idade_aparente", ""))
    if ja and getattr(ref, "idade_fonte", "") != "fotos":
        return ja, getattr(ref, "idade_fonte", "") or "anúncio"
    pelo_texto = idade_do_texto(" ".join(str(x or "") for x in (getattr(ref, "titulo", ""), ref.descricao)))
    if pelo_texto:
        return pelo_texto, "anúncio"
    foto = getattr(ref, "foto", "") or ""
    if not foto or foto.startswith(("http:", "https:")) or not (db.pasta(job_id) / foto).is_file():
        return "n/i", ""
    from .agentes.leitor_anuncio import modelo_leve
    try:
        ia.definir_contexto(job_id, "pesquisa")
        r: _Estimativa = await ia.perguntar(SISTEMA, "Idade aparente da construção nesta foto do anúncio.", _Estimativa,
                                            arquivos=[db.pasta(job_id) / foto], cwd=db.pasta(job_id), modelo=modelo_leve())
    except Exception:
        return "n/i", ""
    v = idade_valida(r.idade)
    return (v, "fotos") if v else ("n/i", "")


async def completar(job_id: str, n: int | None = None) -> list[dict]:
    """Preenche a idade dos anúncios do laudo (amostra e comparação; ou só o anúncio n) que não a têm. Devolve o que
    mudou, para a tela mostrar "inferido pelas fotos — confirmar". Não troca idade que o anúncio ou o avaliador já
    deram; relê o anúncio antes de gravar (o avaliador pode ter mexido enquanto a IA olhava a foto)."""
    mudou = []
    rel = idade_do_relato(job_id)

    def pode_trocar(x) -> bool:
        """Sem idade válida; ou estimada pela foto quando o relato dá a dos referenciais (110-2). A que o avaliador
        confirmou ("avaliador") ou deu no relato nunca é trocada."""
        f = getattr(x, "idade_fonte", "")
        if f in ("avaliador", "relato"):
            # 132-4: "o anúncio não informa" (avaliador, idade VAZIA) não é idade: estima pela foto e pede confirmação
            return f == "avaliador" and not str(x.idade_aparente or "").strip()
        if not idade_valida(x.idade_aparente):
            return True
        return bool(rel and _da_amostra(x) and f == "fotos" and idade_valida(x.idade_aparente) != rel)

    for r in db.candidatos(job_id):
        if n is not None and r.n != n:
            continue
        if not (n is not None or r.escolhido or r.decisao in ("entra", "comparacao")) or not pode_trocar(r):
            continue
        idade, fonte = await estimar(job_id, r)
        agora = next((x for x in db.candidatos(job_id) if x.n == r.n), None)
        if agora is None or not pode_trocar(agora):
            continue
        if idade == "n/i":
            if str(agora.idade_aparente or "").strip() and not idade_valida(agora.idade_aparente):
                # 110-2: texto de ESTADO no campo da idade ("excelente estado de conservação") sai — nunca é idade
                upd = {"idade_aparente": ""}
                if "idade_fonte" in type(agora).model_fields:
                    upd["idade_fonte"] = ""
                db.salvar_candidatos(job_id, [agora.model_copy(update=upd)])
                mudou.append({"n": r.n, "idade": "", "fonte": ""})
            continue
        upd = {"idade_aparente": idade}
        if "idade_fonte" in type(agora).model_fields:      # o campo é do outro executor (modelos.py)
            upd["idade_fonte"] = fonte
        db.salvar_candidatos(job_id, [agora.model_copy(update=upd)])
        mudou.append({"n": r.n, "idade": idade, "fonte": fonte})
        db.evento(job_id, "pesquisa", "info", f"anúncio {r.n:02d}: idade aparente {idade} "
                  + {"anúncio": "(lida no anúncio)", "relato": "(do seu relato)"}.get(fonte, "(inferida pela foto — confirmar)"))
    return mudou


_rodando: set[tuple[str, int | None]] = set()


def agendar(job_id: str, n: int | None = None) -> None:
    """109-5: depois que um anúncio chega (extensão, colar link), a idade é completada em segundo plano — sem
    travar a tela. Lida no texto: sem custo; pela foto: uma chamada da IA leve por anúncio sem idade."""
    import asyncio
    chave = (job_id, n)
    if chave in _rodando:
        return

    async def _vai():
        _rodando.add(chave)
        try:
            await completar(job_id, n)
        except Exception:          # noqa: BLE001 — a idade nunca derruba o envio do anúncio
            pass
        finally:
            _rodando.discard(chave)
    try:
        asyncio.get_running_loop().create_task(_vai())
    except RuntimeError:           # fora do servidor (sem loop): roda agora
        asyncio.run(_vai())


Fonte = Literal["anúncio", "fotos", ""]
