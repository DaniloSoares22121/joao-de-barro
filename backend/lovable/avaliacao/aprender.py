"""ORDEM 026 v2 — F2: aprender no trabalho.

Quando o avaliador corrige um campo, um texto, a escolha de amostra ou de área, o sistema
pergunta "Vale só para este laudo ou para todos os seus?" (Só este | Todos os meus | Não é
regra). Em "Todos os meus" a IA escreve a ficha (situação → decisão → porquê), o avaliador
confere e confirma, e ela vira regra dele na hora (escopo avaliador); para os outros
avaliadores entra como "aprendido". Não pergunta em correção de digitação e não repete a
mesma pergunta no mesmo trabalho.
"""
from __future__ import annotations

import difflib
import json
import re
import unicodedata

from pydantic import BaseModel

from . import db, fichas

TIPOS_CORRECAO = ("campo", "texto", "amostra", "area", "pergunta")
ETAPA_DA_CORRECAO = {"campo": ["documentos", "áreas", "vistoria"], "texto": ["redação"],
                     "amostra": ["pesquisa", "cálculo"], "area": ["áreas", "cálculo"],
                     "pergunta": []}


def _n(s) -> str:
    s = unicodedata.normalize("NFKD", str(s if s is not None else "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.casefold()).strip()


def eh_digitacao(antes, depois) -> bool:
    """Correção de digitação: só muda maiúscula/acento/pontuação/espaço, ou 1–2 letras numa
    palavra (sem mudar número). Nesses casos não se pergunta nada."""
    a, d = _n(antes), _n(depois)
    if a == d:
        return True
    if re.findall(r"\d+", a) != re.findall(r"\d+", d):
        return False                      # número mudou: é correção de dado, não digitação
    if not a or not d:
        return False
    dist = sum(1 for op in difflib.ndiff(a, d) if op[0] in "+-")
    return dist <= 2 and len(a) > 4


def _chave_perguntas(job_id: str) -> str:
    return f"aprender_perguntado:{job_id}"


def _perguntadas(job_id: str) -> list[str]:
    try:
        return json.loads(db.setting(_chave_perguntas(job_id)) or "[]")
    except ValueError:
        return []


def deve_perguntar(job_id: str, tipo: str, chave: str, antes, depois) -> bool:
    """Pergunta só uma vez por (tipo, chave) no trabalho e nunca em digitação."""
    if tipo not in TIPOS_CORRECAO or eh_digitacao(antes, depois):
        return False
    return f"{tipo}:{chave}" not in _perguntadas(job_id)


def marcar_perguntada(job_id: str, tipo: str, chave: str) -> None:
    ps = _perguntadas(job_id)
    k = f"{tipo}:{chave}"
    if k not in ps:
        db.set_setting(_chave_perguntas(job_id), json.dumps(ps + [k], ensure_ascii=False))


class Rascunho(BaseModel):
    titulo: str
    situacao: str
    decisao: str
    porque: str
    tipo_imovel: list[str] = []
    modalidade: list[str] = []
    etapa: list[str] = []


INSTRUCAO = """\
Você escreve UMA ficha de conhecimento do avaliador a partir de uma correção que ele fez num
laudo e disse valer "para todos os laudos dele". Formato: título curto; situação (quando a regra
se aplica, em termos gerais); decisão (o que fazer); porquê (o motivo, como o avaliador
explicaria). Escreva em português simples, sem jargão de programação.
PROTEÇÃO: nunca escreva nome de pessoa ou empresa, CPF, CNPJ, RG, endereço (rua, quadra, lote,
número, CEP), matrícula, inscrição, links ou valores/áreas exatos — generalize ("galpão dentro
de lote maior", "área entre 1.500 e 2.500 m²"). Etiquetas: tipo_imovel (casa, sobrado,
apartamento, lote, galpão, sala/loja, rural), modalidade (OV, AM, AM garantia, AMJ) e etapa
(documentos, áreas, vistoria, fotos, pesquisa, cálculo, redação, revisão, proposta/contrato);
lista vazia = vale para todos."""


def _rascunho_simples(tipo: str, chave: str, antes, depois, contexto: dict) -> Rascunho:
    """Sem IA (ou se ela falhar): rascunho que o avaliador completa."""
    return Rascunho(
        titulo=fichas.titulo_curto(f"Correção de {chave}"),
        situacao=f"Quando {chave} aparecer num laudo de {contexto.get('tipo') or 'imóvel'}.",
        decisao=f"Usar o critério do avaliador: {str(depois)[:300]}",
        porque="Correção feita pelo avaliador num laudo e marcada para valer em todos os dele.",
        tipo_imovel=[fichas._classe_imovel(contexto.get("tipo", ""))] if contexto.get("tipo") else [],
        modalidade=[contexto["modalidade"]] if contexto.get("modalidade") else [],
        etapa=ETAPA_DA_CORRECAO.get(tipo, []))


async def rascunho(job_id: str, tipo: str, chave: str, antes, depois, motivo: str = "") -> Rascunho:
    """A IA escreve a ficha (já protegida, F3); o avaliador confere antes de gravar."""
    from . import ia
    from .agentes import _comum
    from .protecao import proteger_ficha
    t = _comum.trabalho(job_id)
    ctx = {"tipo": t.tipo, "modalidade": t.modalidade}
    prompt = (f"Trabalho: {t.modalidade}, {t.tipo}.\nTipo de correção: {tipo} ({chave}).\n"
              f"Antes: {str(antes)[:2000]}\nDepois (o que o avaliador decidiu): {str(depois)[:2000]}\n"
              f"Motivo dito pelo avaliador: {motivo[:1000] or '(não informado)'}")
    try:
        from .agentes.leitor_anuncio import modelo_leve
        r: Rascunho = await ia.perguntar(INSTRUCAO, prompt, Rascunho, modelo=modelo_leve())
    except Exception:
        r = _rascunho_simples(tipo, chave, antes, depois, ctx)
    return Rascunho.model_validate(proteger_ficha(r.model_dump(), job_id))


def proximo_id() -> str:
    nums = [int(f["id"][2:]) for f in fichas.todas() if re.fullmatch(r"F-\d{4}", f["id"])]
    return f"F-{max(nums, default=0) + 1:04d}"


def confirmar(job_id: str, r: Rascunho, avaliador_id: str = fichas.AVALIADOR_ALAN) -> dict:
    """Ficha confirmada pelo avaliador: regra DELE na hora (escopo avaliador) e, para os outros,
    "aprendido" (só sugestão, até a curadoria validar)."""
    from .protecao import proteger_ficha
    d = proteger_ficha(r.model_dump(), job_id)   # trava de novo: o avaliador pode ter editado
    return fichas.gravar({**d, "id": proximo_id(), "tipo": "regra", "nivel": "aprendido",
                          "escopo": "avaliador", "avaliador_id": avaliador_id,
                          "trabalho_id": job_id, "fonte": "trabalho"},
                         quem=avaliador_id, acao="criada no trabalho")


def minhas(avaliador_id: str = fichas.AVALIADOR_ALAN) -> list[dict]:
    """"Minhas regras": as fichas do avaliador, com o nº do trabalho de onde vieram."""
    out = []
    for f in fichas.todas():
        if f["escopo"] != "avaliador" or f["avaliador_id"] != avaliador_id:
            continue
        num = None
        if f.get("trabalho_id"):
            try:
                num = db.job(f["trabalho_id"])["numero"]
            except Exception:
                num = None
        out.append({**f, "trabalho_numero": num})
    return out
