"""Agente Revisor: confere o PDF final em camadas. A camada matemática é em código
(recalcula o valor e procura os números no texto do PDF), assim como a diagramação
básica (`diagramacao`, com pymupdf); as demais (documental, jurídica,
redação, visual) ficam com a IA, que lê as páginas renderizadas em PNG + checklist P6."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Literal

import pymupdf
from pydantic import BaseModel

from .. import calculo, conhecimento, db, ia, imagens
from ..docx_partes import brl
from . import _comum
from .selecao import Selecao, area_construida

INSTRUCAO = """\
ETAPA ATUAL: REVISÃO FINAL DO LAUDO.
Leia as páginas do laudo (PNG) e confira com o checklist P6 (revisão e padrão visual):
camadas "documental" (dados batem com os documentos), "juridica" (modalidade/ressalvas),
"redacao" (texto, termos proibidos, D-012) e "visual" (padrão visual, imagens, tabelas).
A conferência matemática é feita em código — não a repita.
Para cada problema informe "etapa_responsavel": extracao (dado do imóvel errado), selecao
(amostra), redacao (texto) ou montagem (layout/imagens/tabelas).
"aprovado" = true somente se não houver problema. Não invente problemas.
"""

Camada = Literal["documental", "matematica", "juridica", "redacao", "visual"]
Responsavel = Literal["extracao", "selecao", "redacao", "montagem"]


class Problema(BaseModel):
    camada: Camada
    etapa_responsavel: Responsavel
    descricao: str


class Revisao(BaseModel):
    aprovado: bool
    problemas: list[Problema] = []


def _texto_pdf(pdf: Path) -> str:
    with pymupdf.open(pdf) as d:
        txt = "\n".join(p.get_text() for p in d)
    return " ".join(txt.replace(" ", " ").split())


def matematica(job_id: str, pdf: Path, r: calculo.Resultado) -> list[Problema]:
    probs: list[Problema] = []
    sel_d = db.resultado(job_id, "selecao")
    area = area_construida(job_id)
    if sel_d and area is not None:
        sel = Selecao.model_validate(sel_d)
        try:
            e = calculo.calcular(area, [x for x in sel.refs if x.escolhido],
                                 sel.unitario_adotado, sel.faixa_pct)
            for nome in ("valor_adotado", "valor_min", "valor_max", "unitario_adotado"):
                if getattr(e, nome) != getattr(r, nome):
                    probs.append(Problema(
                        camada="matematica", etapa_responsavel="montagem",
                        descricao=f"{nome} do laudo ({getattr(r, nome)}) difere do "
                                  f"recalculado ({getattr(e, nome)})"))
        except ValueError as ex:
            probs.append(Problema(camada="matematica", etapa_responsavel="selecao",
                                  descricao=f"recálculo impossível: {ex}"))
    texto = _texto_pdf(pdf)
    for rotulo, v in (("valor adotado", r.valor_adotado), ("valor mínimo", r.valor_min),
                      ("valor máximo", r.valor_max)):
        if brl(v) not in texto:
            probs.append(Problema(camada="matematica", etapa_responsavel="montagem",
                                  descricao=f"{rotulo} {brl(v)} não encontrado no PDF"))
    return probs


# ------------------------------------------------------------------ diagramação (código)
MIN_CHARS_PAGINA = 150  # texto além de cabeçalho/rodapé numa página sem imagem
# Rótulos (tabelas do imóvel/resumo) que não podem sair "n/i".
OBRIGATORIOS_IMOVEL = ("Área do terreno", "Área construída adotada", "Tipologia / padrão",
                       "Estado de conservação", "Terreno", "Construída total (adotada no cálculo)")
CAMPO_OBRIGATORIO_NI = "campo obrigatório do imóvel sem dado"
_LIXO = re.compile(r"\[PREENCHER|\bNone\b|\bnull\b")
_TOC = re.compile(r"^(.*?\S)\s*\.{3,}\s*(\d+)$")


def _linhas(pg) -> list[str]:
    return [ln.strip() for ln in pg.get_text().replace(" ", " ").splitlines() if ln.strip()]


def _cabecalho(paginas: list[list[str]]) -> set[str]:
    """Linhas repetidas (sem dígitos) em ≥ 60% das páginas: cabeçalho e rodapé."""
    if len(paginas) < 3:
        return set()
    cont: dict[str, int] = {}
    for ls in paginas:
        for k in {re.sub(r"\d+", "#", ln) for ln in ls}:
            cont[k] = cont.get(k, 0) + 1
    return {k for k, n in cont.items() if n >= 0.6 * len(paginas)}


MIN_AREA_IMAGEM = 0.20  # imagens isentam a página de texto só se cobrirem ≥ 20% dela
# "Foto NN" só isenta com uma foto de verdade, não ícone/logo. Não dá para usar 10% da
# página: a caixa FOTO do relatório fotográfico (7,6 × 5,7 cm) cobre ~7% da página Carta e
# uma foto em retrato encaixada nela ~5%; 4% fica abaixo disso e bem acima de um ícone.
MIN_AREA_FOTO = 0.04
_FECHO = re.compile(r"(\d+\.\s*)?(ASSINATURA|SUMÁRIO)")


def _area_imagens(pg) -> float:
    """Fração da página coberta por imagens (bboxes recortadas à página; sem descontar
    sobreposição, limitada a 1)."""
    pr = pg.rect
    if pr.is_empty:
        return 0.0
    tot = 0.0
    for i in pg.get_image_info():
        r = pymupdf.Rect(i["bbox"]) & pr
        if not r.is_empty:
            tot += r.width * r.height
    return min(tot / (pr.width * pr.height), 1.0)


def _maior_imagem(pg) -> float:
    """Fração da página coberta pela maior imagem (bbox recortada à página)."""
    pr = pg.rect
    if pr.is_empty:
        return 0.0
    areas = [(r.width * r.height) for i in pg.get_image_info()
             if not (r := pymupdf.Rect(i["bbox"]) & pr).is_empty]
    return max(areas, default=0.0) / (pr.width * pr.height)


def _visual(desc: str, etapa: Responsavel = "montagem") -> Problema:
    return Problema(camada="visual", etapa_responsavel=etapa, descricao=desc)


def _fotos_sem_legenda(d) -> list[Problema]:
    """Fotos da grade (entre "Relatório Fotográfico" e o título seguinte) x legendas "Foto NN"."""
    imgs = caps = 0
    dentro = False
    for pg in d:
        blocos = sorted(pg.get_text("blocks"), key=lambda b: b[1])
        ini, fim = None, None
        for b in blocos:
            t = b[4].strip()
            if not dentro and ini is None and re.match(r"^\d+(\.\d+)*\.\s+Relatório Fotográfico", t):
                ini = b[3]
            elif (dentro or ini is not None) and re.match(r"^\d+\.\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{3}", t):
                fim = b[1]
                break
        if ini is None and not dentro:
            continue
        y0, y1 = (ini if ini is not None else -1), (fim if fim is not None else 1e9)
        imgs += sum(1 for i in pg.get_image_info() if y0 <= i["bbox"][1] < y1)
        caps += sum(len(re.findall(r"(?m)^\s*Foto\s+\d+", b[4])) for b in blocos
                    if y0 <= b[1] < y1)
        dentro = fim is None
        if fim is not None:
            break
    if imgs > caps:
        return [_visual(f"relatório fotográfico: {imgs} foto(s) e só {caps} legenda(s)")]
    return []


def _sumario(paginas: list[list[str]]) -> list[Problema]:
    """Números do sumário x página real de cada título (1ª página onde a linha aparece)."""
    i_sum = next((i for i, ls in enumerate(paginas)
                  if any(re.fullmatch(r"(\d+\.\s*)?SUMÁRIO", ln) for ln in ls)), None)
    if i_sum is None:
        return []
    probs = []
    for ln in paginas[i_sum]:
        m = _TOC.match(ln)
        if not m:
            continue
        titulo, n = m.group(1), int(m.group(2))
        real = next((k for k, ls in enumerate(paginas, start=1)
                     if k - 1 != i_sum and titulo in ls), None)
        if real is not None and real != n:
            probs.append(_visual(f"sumário: \"{titulo}\" indicado na página {n}, está na {real}"))
    return probs


def _nao_informados(texto: list[str]) -> list[Problema]:
    probs = []
    for i, ln in enumerate(texto[:-1]):
        prox = texto[i + 1]
        if ln in OBRIGATORIOS_IMOVEL and (prox == "n/i" or prox.endswith("/ n/i")):
            # dado que falta é da extração (ou do avaliador), não da diagramação
            probs.append(_visual(f"{CAMPO_OBRIGATORIO_NI}: {ln} = n/i", "extracao"))
        if ln.startswith("Matrícula") and prox == "n/i":
            if not re.search(r"pend[eê]nci|pendente|não foi apresentada", " ".join(texto), re.I):
                probs.append(_visual("matrícula n/i sem pendência declarada"))
    return probs


def diagramacao(job_id: str, pdf: Path) -> list[Problema]:
    """Camada visual determinística (antes da IA): páginas quase vazias, fotos sem legenda,
    sumário x páginas reais, "composto por N páginas", n/i em campos obrigatórios e restos
    de modelo ("[PREENCHER", "None", "null")."""
    probs: list[Problema] = []
    with pymupdf.open(pdf) as d:
        paginas = [_linhas(pg) for pg in d]
        cab = _cabecalho(paginas)
        for k, (pg, ls) in enumerate(zip(d, paginas), start=1):
            corpo = sum(len(ln) for ln in ls if re.sub(r"\d+", "#", ln) not in cab)
            if corpo >= MIN_CHARS_PAGINA or _area_imagens(pg) >= MIN_AREA_IMAGEM:
                continue
            if k == len(paginas) and any(_FECHO.fullmatch(ln) for ln in ls):
                continue  # última página com a assinatura ou o sumário
            if (_maior_imagem(pg) >= MIN_AREA_FOTO
                    and any(re.match(r"Foto\s+\d+", ln) for ln in ls)):
                continue  # fim do relatório fotográfico (fotos legendadas; ver _fotos_sem_legenda)
            probs.append(_visual(f"página {k} quase vazia ({corpo} caracteres; imagens em "
                                 f"{_area_imagens(pg):.0%} da página)"))
        probs += _fotos_sem_legenda(d)
        n = d.page_count
    probs += _sumario(paginas)
    todo = [ln for ls in paginas for ln in ls]
    m = re.search(r"composto por\s+(\d+)\s+páginas", " ".join(todo))
    if m and int(m.group(1)) != n:
        probs.append(_visual(f"\"composto por {m.group(1)} páginas\" mas o PDF tem {n}"))
    probs += _nao_informados(todo)
    textos = " ".join((db.resultado(job_id, "redacao") or {}).get("secoes", {}).values())
    for achado in sorted({x.group(0) for x in _LIXO.finditer(" ".join(todo))}):
        etapa: Responsavel = "redacao" if achado in textos else "montagem"
        probs.append(Problema(camada="redacao" if etapa == "redacao" else "visual",
                              etapa_responsavel=etapa,
                              descricao=f"resto de modelo no texto do laudo: {achado!r}"))
    return probs


async def rodar(job_id: str, pdf: Path, r: calculo.Resultado) -> Revisao:
    t = _comum.trabalho(job_id)
    pasta = db.pasta(job_id)
    probs = matematica(job_id, pdf, r) + diagramacao(job_id, pdf)
    pngs = await asyncio.to_thread(imagens.pdf_paginas_png, pdf, pasta / "_revisao")
    campos = [c.model_dump(mode="json") for c in db.campos(job_id)]
    sistema = conhecimento.texto("P0", "P3", "P6", "P7") + "\n\n" + INSTRUCAO
    prompt = ("Trabalho:\n" + t.model_dump_json(indent=2, exclude={"contexto"})
              + f"\n\nCampos do imóvel:\n{campos}"
              + f"\n\nValores calculados: adotado {brl(r.valor_adotado)}; mínimo "
                f"{brl(r.valor_min)}; máximo {brl(r.valor_max)}."
              + "\n\nTexto do PDF:\n" + _texto_pdf(pdf)[:60000])
    resp: Revisao = await ia.perguntar(sistema, prompt, Revisao, arquivos=pngs, cwd=pasta)
    ia_probs = [p for p in resp.problemas if p.camada != "matematica"]
    if not resp.aprovado and not ia_probs:
        ia_probs = [Problema(camada="redacao", etapa_responsavel="redacao",
                             descricao="revisor reprovou sem apontar problema")]
    probs += ia_probs
    rev = Revisao(aprovado=not probs, problemas=probs)
    db.evento(job_id, "revisao", "resultado",
              "aprovado" if rev.aprovado else f"{len(probs)} problema(s)",
              dados=rev.model_dump(mode="json"))
    return rev
