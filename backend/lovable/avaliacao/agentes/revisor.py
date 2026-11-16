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

from .. import imagens_ia, calculo, conhecimento, db, ia, imagens
from ..docx_partes import brl
from . import _comum
from . import selecao as _sel_mod
from .selecao import refs_na_base, Selecao, area_construida
from ..plural import pl

INSTRUCAO = """\
ETAPA ATUAL: REVISÃO FINAL DO LAUDO.
Leia as páginas do laudo (PNG) e confira com o checklist P6 (revisão e padrão visual):
camadas "documental" (dados batem com os documentos), "juridica" (modalidade/ressalvas),
"redacao" (texto, termos proibidos, D-012) e "visual" (padrão visual, imagens, tabelas).
A conferência matemática é feita em código — não a repita.
Para cada problema informe "etapa_responsavel": extracao (dado do imóvel errado), selecao
(amostra), redacao (texto) ou montagem (layout/imagens/tabelas).
"aprovado" = true somente se não houver problema. Não invente problemas.
TARJA (D-062): este é o laudo do CLIENTE FINAL — TODOS os documentos (escritura, matrícula, IPTU,
certidões, cartão CNPJ e também RG, CNH e OAB do solicitante) entram SEM tarja. Nunca peça tarja.
Prazo, número ou data no texto SEM fonte (documento do trabalho, norma da P4 ou decisão do P3)
é problema da camada "redacao" (etapa_responsavel "redacao"): a frase deve sair (§2.1).
Referenciais, unitário adotado e faixa CONFIRMADOS PELO AVALIADOR (informado no pedido) são
decisão dele: não reprove por isso. Se tiver uma ressalva sobre a amostra ou o unitário,
registre-a com etapa_responsavel "selecao" (vira aviso ao avaliador, não reprovação).
Campo "pendente" na extração que o avaliador preencheu como vistoria NÃO é problema: o laudo
usa o dado do avaliador.
Regras do Alan que NÃO são problema:
- Arredondamento (D-065): o valor adotado é área × unitário arredondado ao MILHAR mais próximo,
  em toda modalidade. A diferença entre o valor calculado e o adotado por esse arredondamento
  NÃO é divergência (ex.: R$ 6.071.724,37 → R$ 6.072.000,00).
- Apartamento: capa com a foto do condomínio SEM demarcação e legenda "Fachada do condomínio
  onde se localiza a unidade avalianda" é o correto quando a foto não permite identificar a
  torre com segurança (o avaliador confirma a torre). Não peça demarcação adivinhada.
- Documento sem tarja no laudo do cliente é o CORRETO (D-062, ORDEM 045): tarja só existe em
  material para OUTRAS pessoas (laudo de exemplo, base comum, outros avaliadores), que o sistema
  gera à parte. Não aponte "documento/escritura/anexo sem tarja" como problema.
- Pessoa ou placa pixelizada (desfocada) numa foto da vistoria é proteção de privacidade.
- Foto de documento já cortada na origem (borda da página fora da foto) não é erro de montagem.
- Referencial SEM foto principal porque o portal bloqueou o anúncio (o sistema já avisou o
  avaliador) não se corrige refazendo o laudo: registre como ressalva com etapa_responsavel
  "selecao" (vira aviso), nunca "montagem".
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
            e = calculo.calcular(area, refs_na_base(job_id, [x for x in sel.refs if x.escolhido]),
                                 _sel_mod.unitario_valido(sel)[0], sel.faixa_pct)
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
MAX_PAGINAS_OV = 19     # D-039: OV enxuta, com anexos
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
        # fotos de verdade: fora do cabeçalho/rodapé (a logo do cabeçalho não é foto)
        topo, base = 75, pg.rect.height - 60
        imgs += sum(1 for i in pg.get_image_info()
                    if y0 <= i["bbox"][1] < y1 and topo <= i["bbox"][1] <= base
                    and (i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]) > 2500)
        caps += sum(len(re.findall(r"(?m)^\s*Foto\s+\d+", b[4])) for b in blocos
                    if y0 <= b[1] < y1)
        dentro = fim is None
        if fim is not None:
            break
    if imgs > caps:
        return [_visual(f"relatório fotográfico: {pl(imgs, 'foto', 'fotos')} e só {pl(caps, 'legenda', 'legendas')}")]
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
        # P9/P6 camada E: A4 (595 × 842 pt) e OV enxuta (D-039)
        tams = {(round(pg.rect.width), round(pg.rect.height)) for pg in d}
        if any(abs(w - 595) > 3 or abs(h - 842) > 3 for w, h in tams):
            probs.append(_visual(f"página fora do A4: {sorted(tams)} pt (A4 = 595 × 842)"))
        if _comum.trabalho(job_id).modalidade == "OV" and d.page_count > MAX_PAGINAS_OV:
            # D-057: sem limite de páginas — só informa (nunca reprova nem volta etapa)
            db.evento(job_id, "revisao", "info", f"laudo com {d.page_count} páginas (sem limite: D-057)")
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


_ANEXO_FIXO = re.compile(r"Anexo (?:I|II) – Tabela de (?:Fatores de Depreciação Ross-Heidecke|"
                         r"Vida Útil Estimada)", re.I)


def paginas_fixas(pdf: Path) -> list[bool]:
    """ORDEM 008 (custo, corte "seguro"): páginas que são só as tabelas fixas do modelo
    (Anexo I Ross-Heidecke e Anexo II Vida Útil — imagens do modelo, iguais em todo laudo)
    não vão à IA como imagem; a diagramação em código continua conferindo essas páginas.
    Página com a lista de anexos (item 16) ou outro conteúdo continua indo."""
    with pymupdf.open(pdf) as d:
        out = []
        for pg in d:
            t = " ".join(pg.get_text().split())
            corpo = re.sub(r"Alan Soares.*?Pág\.\s*\d+", "", t)   # cabeçalho/rodapé
            fixa = bool(_ANEXO_FIXO.search(t)) and not re.search(r"\b\d+\.\s+ANEXOS\b", t) \
                and len(corpo) < 4000 and "Anexo III" not in t
            out.append(fixa)
    return out


def decisoes_do_trabalho(job_id: str) -> tuple[list[str], set[str]]:
    """083-B6: as decisões e respostas do avaliador neste trabalho (são a FONTE) e os temas que elas calam."""
    import json as _json
    from .. import tela_trabalho
    linhas: list[str] = []
    temas: set[str] = set()
    aceitas = set(_json.loads(db.setting(f"pendencias_aceitas:{job_id}") or "[]"))
    # 106-5 (D-068, regra do projeto, todo laudo): nada sobre dispersão dos referenciais no laudo
    temas.add("cv")
    linhas.append("D-068 (regra do projeto): o laudo NÃO traz nenhuma frase sobre dispersão, espalhamento, heterogeneidade "
                  "ou variação entre os valores dos referenciais, nem coeficiente de variação ou desvio-padrão — a conta fica "
                  "só na planilha. Aponte como problema qualquer frase desse tipo; nunca peça para incluí-la.")
    if "decisao:amostra" in aceitas:
        temas.add("amostra")
        linhas.append("Amostra: o avaliador decidiu manter o referencial de localização diferente (falta de anúncios compatíveis).")
    linhas.append("Datas de documentos (136, decisão do Capitão): o laudo NÃO traz data de emissão de documento (nem "
                  "coluna no item 6, nem no texto, nem em legenda); não peça essa data — aponte como erro se aparecer.")
    ctx = ((tela_trabalho._cliente(job_id) or {}).get("contexto") or {})
    if ctx.get("idade_aparente"):
        temas.add("idade")
        linhas.append(f"Idade aparente: {ctx['idade_aparente']} anos, resposta do avaliador na vistoria (é a fonte); "
                      "o laudo diz só \"idade aparente de cerca de N anos\", sem dizer como foi estimada (113-4).")
    if ctx.get("medidas_confere"):
        temas.add("medidas")
        linhas.append("Medidas: o avaliador mediu na vistoria e confirmou que batem com a escritura e o cadastro "
                      "(D-055, é a fonte da frase de compatibilidade).")
    if ctx.get("pontos_negativos"):          # 090-5: o que o avaliador informou no relato é a fonte
        temas.add("vizinhanca")
        linhas.append("Pontos negativos informados pelo avaliador no relato da vistoria (são a fonte): "
                      + "; ".join(ctx["pontos_negativos"]) + ".")
    if ctx.get("estado_conservacao"):
        temas.add("estado")
        linhas.append(f"Estado de conservação: \"{ctx['estado_conservacao']}\", classificação do avaliador no relato "
                      "(prevalece sobre a leitura das fotos).")
    # 090-6: confirmou o valor apesar do aviso de dispersão → decidido
    with db._conn() as c:
        rows = c.execute("SELECT dados_json FROM av_events WHERE job=? AND etapa='selecao' AND msg LIKE "
                         "'avaliador confirmou mesmo assim:%'", (job_id,)).fetchall()
    if any(re.search(r"(?i)dispers|coeficiente de varia", r[0] or "") for r in rows) and "cv" not in temas:
        temas.add("cv")
        linhas.append("Dispersão: o avaliador confirmou o valor mesmo com o aviso de dispersão alta (decisão dele).")
    for x in db.instrucoes_avaliador(job_id):
        linhas.append(f"Instrução do avaliador ao confirmar o valor: {x}")
    return linhas, temas


def _norm(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def contra_decisao(descricao: str, temas: set[str]) -> str:
    """Tema decidido pelo avaliador que o problema contesta ("" se nenhum)."""
    t = _norm(descricao)
    if "cv" in temas and re.search(r"desvio[- ]padrao|coeficiente de variacao|\bcv\b|estatistica", t):
        return "cv"
    if "idade" in temas and re.search(r"\bidade (?:aparente|estimada)", t) and re.search(
            r"sem fonte|nao tem fonte|n/i|nao informad|sem origem|de onde|fonte da idade|nao consta|sem base", t):
        return "idade"
    if "medidas" in temas and re.search(r"(?:medidas|trena|medicao)\b.*(?:compativ|escritura|cadastro|fonte|vistoria)"
                                        r"|compativ\w* com a escritura", t) and re.search(
            r"sem fonte|nao tem fonte|nao consta|sem origem|de onde|nenhum campo|sem base|nao ha registro", t):
        return "medidas"
    if "vizinhanca" in temas and re.search(r"festa|vizinhan|entorno", t) and re.search(
            r"nenhum campo|sem fonte|nao tem fonte|nao consta|nao registr|sem origem|de onde", t):
        return "vizinhanca"
    if "estado" in temas and "estado" in t and re.search(r"nao bate|diverge|diferente|extracao registrou|registrou", t):
        return "estado"
    if "amostra" in temas and re.search(r"localizacao (?:diferente|distinta)|outra regiao|anglo", t):
        return "amostra"
    return ""


async def rodar(job_id: str, pdf: Path, r: calculo.Resultado) -> Revisao:
    t = _comum.trabalho(job_id)
    pasta = db.pasta(job_id)
    probs = matematica(job_id, pdf, r) + diagramacao(job_id, pdf)
    pngs = await asyncio.to_thread(imagens.pdf_paginas_png, pdf, pasta / "_revisao")
    pngs = [p for p, fixa in zip(pngs, paginas_fixas(pdf)) if not fixa]
    todos = db.campos(job_id)
    campos = [c.model_dump(mode="json") for c in todos if c.origem != "pendente"]
    pendentes = [c.nome for c in todos if c.origem == "pendente"]
    sel_d = db.resultado(job_id, "selecao") or {}
    confirmado = bool(sel_d.get("confirmado") or sel_d.get("manual"))
    decisoes, temas = decisoes_do_trabalho(job_id)
    sistema = conhecimento.base(job_id, ("P0", "P3", "P6", "P7", "P9"),
                                ("revisão", "redação", "documentos", "fotos", "cálculo")) + "\n\n" + INSTRUCAO
    prompt = ("Trabalho:\n" + t.model_dump_json(indent=2, exclude={"contexto"})
              + f"\n\nCampos do imóvel (documento/vistoria):\n{campos}"
              + f"\nCampos sem fonte na extração automática: {pendentes}"
              + ("\n\nAmostra, unitário e faixa CONFIRMADOS PELO AVALIADOR." if confirmado else "")
              + (("\n\nDECISÕES E RESPOSTAS DO AVALIADOR NESTE TRABALHO (são a fonte; não aponte problema "
                  "contra elas):\n" + "\n".join(f"- {x}" for x in decisoes)) if decisoes else "")
              + f"\n\nValores calculados: adotado {brl(r.valor_adotado)}; mínimo "
                f"{brl(r.valor_min)}; máximo {brl(r.valor_max)}."
              + "\n\nTexto do PDF:\n" + _texto_pdf(pdf)[:60000])
    # ORDEM 013 b: no máximo MAX_IMAGENS páginas por chamada; laudo maior vai em lotes (o
    # texto inteiro vai em todos) e os problemas se somam
    lotes = [pngs[i:i + imagens_ia.MAX_IMAGENS] for i in range(0, len(pngs), imagens_ia.MAX_IMAGENS)] or [[]]
    vistos: set[str] = set()
    probs_ia: list[Problema] = []
    aprovado = True
    for i, lote in enumerate(lotes, start=1):
        extra = (f"\n\nPáginas em imagem: lote {i} de {len(lotes)} (as demais páginas são "
                 "conferidas em outra chamada; julgue o laudo pelo texto inteiro e pelas "
                 "páginas deste lote).") if len(lotes) > 1 else ""
        r_lote: Revisao = await ia.perguntar(sistema, prompt + extra, Revisao, arquivos=lote, cwd=pasta)
        aprovado = aprovado and r_lote.aprovado
        for p in r_lote.problemas:
            if p.descricao not in vistos:
                vistos.add(p.descricao)
                probs_ia.append(p)
    resp = Revisao(aprovado=aprovado, problemas=probs_ia)
    ia_probs = [p for p in resp.problemas if p.camada != "matematica"]
    # 083-B6: decisão gravada cala o revisor naquele ponto (vira aviso, não pendência)
    calados = [p for p in ia_probs if contra_decisao(p.descricao, temas)]
    for p in calados:
        db.evento(job_id, "revisao", "aviso", f"revisor (contra decisão do avaliador, ignorado): {p.descricao}")
    ia_probs = [p for p in ia_probs if p not in calados]
    if calados and not ia_probs and not resp.aprovado:
        resp = Revisao(aprovado=True, problemas=[])
    if confirmado:
        # escolha do avaliador: ressalva da IA sobre a amostra/unitário vira aviso
        for p in [p for p in ia_probs if p.etapa_responsavel == "selecao"]:
            db.evento(job_id, "selecao", "aviso", f"revisor (ressalva, decisão do avaliador): "
                                                  f"{p.descricao}")
        ia_probs = [p for p in ia_probs if p.etapa_responsavel != "selecao"]
        if not ia_probs:
            resp = Revisao(aprovado=True, problemas=[])
    if not resp.aprovado and not ia_probs:
        ia_probs = [Problema(camada="redacao", etapa_responsavel="redacao",
                             descricao="revisor reprovou sem apontar problema")]
    probs += ia_probs
    rev = Revisao(aprovado=not probs, problemas=probs)
    db.evento(job_id, "revisao", "resultado",
              "aprovado" if rev.aprovado else pl(len(probs), "problema", "problemas"),
              dados=rev.model_dump(mode="json"))
    return rev
