"""ORDEM 025 / D-057: sem limite de páginas — o tamanho do laudo vem da ESCOLHA.

O avaliador sobe todas as fotos e todos os documentos; o sistema escolhe, como o João faz:
- fotos: uma por ambiente/ângulo, sem repetidas nem quase iguais (fica a mais nítida), fachada
  sempre e primeiro, ordem fachada → externas → internas → detalhes; prints de medição por
  satélite (D-027) saem do relatório fotográfico e vão para o item de áreas;
- anexo de documentos: de um PDF de várias páginas só entram as que importam (1ª página, que
  identifica o documento, as páginas citadas como fonte de dado do laudo e as que a extração
  rotulou à parte ou indicou em "paginas_anexo"); o resto fica citado em "Documentação
  analisada".
Funções puras (sem IA), testadas em test_escolha_laudo.py.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PurePosixPath

from PIL import Image, ImageFilter, ImageOps, ImageStat

DIST_QUASE_IGUAL = 6          # bits de diferença no dHash de 64 bits
_PAGINA = re.compile(r"(?:#p|\bp\.?\s*|\bp[áa]g(?:ina)?\.?\s*)(\d{1,3})\b", re.I)


def _n(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.casefold().split())


# ------------------------------------------------------------------ anexo: páginas
def paginas_citadas(rel: str, fontes: list[str]) -> set[int]:
    """Páginas do arquivo `rel` citadas nas fontes ("x.pdf#p12", "x.pdf (p.1)", "x.pdf, pág. 3")."""
    nome = PurePosixPath(rel).name.casefold()
    out: set[int] = set()
    for fonte in fontes:
        for trecho in re.split(r"[;\n]", fonte or ""):
            if nome not in trecho.casefold():
                continue
            depois = trecho.casefold().split(nome, 1)[1]
            m = _PAGINA.search(depois[:40])
            if m:
                out.add(int(m.group(1)))
    return out


# Campos que fazem a página "importar" (título/identificação do imóvel). CEP, valor de imposto e
# afins citados numa guia não puxam a página para o anexo.
_PRINCIPAL = ("matricula", "area", "propriet", "registro", "titulo", "aquisic", "confront", "medida",
              "quadra", "lote", "endereco", "logradouro", "inscric", "onus", "escritura", "transmit")
SALTO_BLOCO = 1   # página do meio sem citação ainda conta no mesmo bloco


def paginas_anexo(rel: str, n_paginas: int, fontes, documentos: list[dict]) -> list[int]:
    """Páginas (1…n) do PDF `rel` que entram no anexo (ORDEM 028-3, regra comparada com o laudo
    oficial do Alan). Até 2 páginas: todas. Pacote de vários documentos num PDF só: entra o
    DOCUMENTO DE TÍTULO — o 1º bloco contínuo a partir da página 1 com as páginas citadas como
    fonte de campo principal (ou rotuladas à parte pela extração); o que vem depois (guias, ITCD,
    certidões, cópias de matrícula) fica só citado. "paginas_anexo" da extração manda.
    `fontes`: [(nome_do_campo, fonte)] (ou só as fontes, que contam como principais)."""
    if n_paginas <= 2:
        return list(range(1, n_paginas + 1))
    nome = PurePosixPath(rel).name
    indicadas: set[int] = set()
    rotuladas: set[int] = set()
    for d in documentos or []:
        arq = str(d.get("arquivo") or "").replace("\\", "/")
        base, _, pag = arq.partition("#p")
        if PurePosixPath(base).name != nome:
            continue
        if pag.isdigit():
            rotuladas.add(int(pag))
        for p in d.get("paginas_anexo") or []:
            try:
                indicadas.add(int(p))
            except (TypeError, ValueError):
                pass
    if indicadas:
        return sorted(p for p in ({1} | indicadas) if 1 <= p <= n_paginas)
    pares = [(f, "") if isinstance(f, str) else (f[1], f[0]) for f in fontes]
    principais: set[int] = set()
    for fonte, campo in pares:
        pags = paginas_citadas(rel, [fonte])
        if not campo or any(k in _n(campo) for k in _PRINCIPAL):
            principais |= pags
    marcadas = {1} | principais | rotuladas
    bloco = [1]
    p = 2
    while p <= n_paginas:
        if p in marcadas:
            bloco.append(p)
        elif not any(q in marcadas for q in range(p + 1, p + 1 + SALTO_BLOCO + 1)):
            break
        else:
            bloco.append(p)        # lacuna curta dentro do mesmo documento
        p += 1
    while len(bloco) > 1 and bloco[-1] not in marcadas:
        bloco.pop()
    return [p for p in bloco if 1 <= p <= n_paginas]


# ------------------------------------------------------------------ fotos
def prints_medicao(campos) -> set[str]:
    """Fotos citadas como fonte de ÁREA/medida (prints do Google Earth/Maps, D-027).
    ORDEM 030: só campo de medida que fala de satélite/Google — "Área de serviço" com foto da
    vistoria NÃO é print de medição (saía com a legenda de satélite na OV 120)."""
    out: set[str] = set()
    for c in campos:
        nome = _n(getattr(c, "nome", ""))
        if not ("area" in nome or "medid" in nome or "satelit" in nome or "frente" in nome
                or "comprimento" in nome):
            continue
        # nome ou fonte (não a observação: "a piscina aparece na imagem do Google" no PTAM 116
        # fazia as fotos das áreas comuns saírem como "medição por satélite")
        tudo = _n(f"{nome} {getattr(c, 'fonte', '') or ''}")
        if not re.search(r"satelit|google|earth|\bmaps\b", tudo):
            continue
        for m in re.finditer(r"(foto/[^;,()\s]+\.(?:jpe?g|png|webp))", getattr(c, "fonte", "") or "", re.I):
            if _CAMERA.match(Path(m.group(1)).name):
                continue   # ORDEM 031: foto de chão (arquivo de câmera) nunca é print de medição
            out.add(m.group(1))
    return out


_CAMERA = re.compile(r"(?i)(?:img|dsc|pxl|vid|photo|foto)[_-]?\d{6,}")
_MEDIDAS = (("frente", "da frente"), ("comprimento", "do comprimento"), ("largura", "da largura"),
            ("profundidade", "da profundidade"), ("fundo", "dos fundos"), ("lateral", "da lateral"),
            ("altura", "da altura"))


def legenda_print(rel: str, campos) -> str:
    """ORDEM 031: legenda do print de medição pela descrição, nunca pelo nome do arquivo.
    Ex.: "Medição da frente do Galpão 01 por imagem de satélite (Google Maps) – 30,54 m"."""
    nome_arq = _n(Path(rel).stem.replace("_", " "))
    objeto, medida = "", ""
    for c in campos:
        fonte = getattr(c, "fonte", "") or ""
        if rel not in fonte:
            continue
        m = re.search(re.escape(rel) + r"\s*\(([\d.,]+\s*m)\)", fonte)
        if m:
            medida = m.group(1)
        o = re.search(r"(?i)\bd[oa]\s+(.+?)\s+[–-]\s+medid", getattr(c, "nome", "") or "")
        if o:
            objeto = o.group(1).strip()
        break
    do_obj = f" do {objeto}" if objeto and not objeto.lower().startswith(("a ", "o ")) else (f" {objeto}" if objeto else " do imóvel")
    if re.search(r"mapa|localiza|implanta", nome_arq):
        return f"Localização e contorno{do_obj} em imagem de satélite (Google Maps)"
    qual = next((d for k, d in _MEDIDAS if k in nome_arq), "")
    base = f"Medição {qual}{do_obj}" if qual else f"Medição{do_obj}"
    return f"{base} por imagem de satélite (Google Maps)" + (f" – {medida}" if medida else "")


def dhash(p: Path) -> int | None:
    try:
        with Image.open(p) as im:
            g = ImageOps.exif_transpose(im).convert("L").resize((9, 8), Image.LANCZOS)
    except Exception:
        return None
    px = list(g.getdata())
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (px[y * 9 + x] > px[y * 9 + x + 1])
    return bits


def cor_media(p: Path) -> tuple[float, float, float] | None:
    try:
        with Image.open(p) as im:
            r, g, b = ImageStat.Stat(im.convert("RGB").resize((16, 16))).mean
            return r, g, b
    except Exception:
        return None


DIST_COR = 30.0   # quase iguais também têm cor média parecida (blocos lisos de cores diferentes não são)


def _quase_iguais(a: tuple, b: tuple) -> bool:
    (h1, c1), (h2, c2) = a, b
    if h1 is None or h2 is None or bin(h1 ^ h2).count("1") > DIST_QUASE_IGUAL:
        return False
    if c1 is None or c2 is None:
        return True
    return sum((x - y) ** 2 for x, y in zip(c1, c2)) ** 0.5 <= DIST_COR


def nitidez(p: Path) -> float:
    """Variância das bordas (quanto maior, mais nítida)."""
    try:
        with Image.open(p) as im:
            g = ImageOps.exif_transpose(im).convert("L")
            g.thumbnail((640, 640))
            return float(ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).var[0])
    except Exception:
        return 0.0


_EXTERNAS = ("fachada", "frente", "rua", "lateral", "fundo", "patio", "portao", "acesso", "entorno",
             "calcada", "externa", "doca", "estacionamento", "muro", "cobertura externa", "vista")
_DETALHES = ("detalhe", "quadro", "medidor", "relogio", "forro", "trinca", "infiltr", "instala",
             "equipamento", "placa", "inversor", "aquecedor")


def grupo_legenda(leg: str) -> int:
    """0 fachada, 1 externas, 2 internas, 3 detalhes."""
    n = _n(leg)
    if "fachada" in n:
        return 0
    if any(k in n for k in _DETALHES):
        return 3
    if any(k in n for k in _EXTERNAS) and "interior" not in n and "intern" not in n:
        return 1
    return 2


def escolher_fotos(itens: list[dict], caminho, marcada: str | None = None,
                   excluir: set[str] = frozenset()) -> list[dict]:
    """Fotos do relatório. `itens` = [{"arquivo", "legenda", "ordem"}] (da extração);
    `caminho(rel)` -> Path no disco. Tira prints de medição e quase iguais (fica a mais nítida),
    fachada primeiro, depois externas → internas → detalhes (na ordem da extração dentro do
    grupo). Sem limite fixo de quantidade (D-057)."""
    lista = [f for f in sorted(itens, key=lambda f: f.get("ordem", 0))
             if f.get("arquivo") and f.get("arquivo") not in excluir]
    if marcada and marcada not in excluir:
        lista = ([f for f in lista if f["arquivo"] == marcada]
                 or [{"arquivo": marcada, "legenda": "Fachada frontal – vista da rua", "ordem": 0}]) + \
                [f for f in lista if f["arquivo"] != marcada]
    escolhidas: list[tuple[dict, tuple, float]] = []
    for f in lista:
        p = caminho(f["arquivo"])
        h = (dhash(p), cor_media(p)) if p else (None, None)
        nit = nitidez(p) if p else 0.0
        igual = next((k for k, (_, h2, _) in enumerate(escolhidas) if _quase_iguais(h, h2)), None)
        if igual is None:
            escolhidas.append((f, h, nit))
        elif nit > escolhidas[igual][2] and escolhidas[igual][0]["arquivo"] != marcada:
            # fica a mais nítida (a fachada marcada pelo avaliador nunca é trocada)
            escolhidas[igual] = ({**f, "legenda": escolhidas[igual][0].get("legenda") or f.get("legenda")}, h, nit)
    fotos = [f for f, _, _ in escolhidas]
    primeira = fotos[:1] if fotos and (fotos[0]["arquivo"] == marcada or grupo_legenda(fotos[0].get("legenda", "")) == 0) else []
    resto = [f for f in fotos if f not in primeira]
    resto.sort(key=lambda f: grupo_legenda(f.get("legenda", "")))   # estável: mantém a ordem no grupo
    return primeira + resto
