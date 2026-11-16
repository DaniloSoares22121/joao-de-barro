"""ORDEM 077-1(b) / D-077: anexo do Mapa Digital Fácil (Goiânia), feito sozinho pelo JdB.

1. Dados do lote na própria Prefeitura (serviço público do Mapa Digital Fácil, sem a tela dele no laudo — D-075):
   - "Cadastro Imobiliário" pela inscrição: quadra, lote, bairro, logradouro, área do terreno e o desenho;
   - "Divisas de Lote": o polígono do lote (área e os quatro lados).
2. O print (coletor/mapa_digital.py, Playwright no PC do JdB): lote marcado, quadro de detalhe ligado por uma linha,
   com a área e os quatro lados, e a faixa com o endereço do site e a data da consulta.
3. Grava no contrato do anexo (1(a)): mapa_digital/mapa_digital_facil.png + arquivo do tipo "mapa_digital" + evento
   ("localizacao", "mapa_digital", dados={imagem, inscricao, quadra, lote, area, lados, url}).
Imóvel fora de Goiânia ou sem inscrição: devolve o motivo (o avaliador manda o print, 1(a)).
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import Depends, HTTPException

from . import db
from .routes import _dono, _job, _livre, router

SERVICO = "https://portalmapa.goiania.go.gov.br/servicogyn/rest/services/MapaServer/Feature_Base/MapServer"
SITE = "https://portalmapa.goiania.go.gov.br/mapafacil/"
COLETOR_PY = Path(__file__).resolve().parents[3] / "coletor" / ".venv" / "Scripts" / "python.exe"
COLETOR_SCRIPT = Path(__file__).resolve().parents[3] / "coletor" / "mapa_digital.py"
ARQ = "mapa_digital/mapa_digital_facil.png"
BASICO = "https://portalmapa.goiania.go.gov.br/servicogyn/rest/services/MapaServer/Mapa_Basico3/MapServer"
ESCALAS = (1000, 2000)          # 107-d: 1:1.000 (a do PTAM 122); 1:2.000 se os nomes das ruas não couberem
LARG, ALT = 1366, 860           # a tela do print (a mesma do coletor/mapa_digital.py)
CAIXA = (500, 470)              # o quadro de zoom do imóvel (107-3)


def br(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _consulta(camada: int, params: dict) -> list[dict]:
    r = httpx.get(f"{SERVICO}/{camada}/query", params={**params, "outSR": "31982", "f": "json"}, timeout=40)
    r.raise_for_status()
    d = json.loads(r.text)
    if "error" in d:
        raise RuntimeError(d["error"].get("message") or "erro no serviço do Mapa Digital Fácil")
    return d.get("features") or []


def lados(anel: list[list[float]], tol_graus: float = 12.0) -> list[dict]:
    """Os lados do lote: arestas seguidas quase alinhadas viram um lado só (o desenho tem pontos no meio)."""
    pts = [tuple(p) for p in anel]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)
    if n < 3:
        return []
    ang = lambda a, b: math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    segs = [(pts[i], pts[(i + 1) % n]) for i in range(n)]
    # começa num canto de verdade, para não partir um lado ao meio
    def curva(i):
        a, b = segs[i - 1], segs[i]
        d = abs((ang(*b) - ang(*a) + 180) % 360 - 180)
        return d
    ini = max(range(n), key=curva)
    segs = segs[ini:] + segs[:ini]
    out = [[segs[0][0], segs[0][1]]]
    for a, b in segs[1:]:
        u = out[-1]
        d = abs((ang(a, b) - ang(u[0], u[1]) + 180) % 360 - 180)
        if d <= tol_graus:
            u[1] = b
        else:
            out.append([a, b])
    return [{"a": list(a), "b": list(b), "m": math.dist(a, b)} for a, b in out]


def area_poligono(anel: list[list[float]]) -> float:
    """Área do desenho do lote (fórmula do polígono, em m², coordenadas UTM)."""
    return abs(sum(anel[i][0] * anel[i - 1][1] - anel[i - 1][0] * anel[i][1] for i in range(len(anel)))) / 2


def dados_lote(inscricao: str) -> dict:
    """Cadastro + Divisas de Lote pela inscrição (só números)."""
    ci = re.sub(r"\D", "", inscricao or "")
    if not ci:
        raise ValueError("sem inscrição imobiliária")
    cad = _consulta(3, {"where": f"nrinscr='{ci}'", "outFields": "nrquadra,nrlote,nmbairro,tplogradou,nmlogradou,areaterr",
                        "returnGeometry": "true"})
    if not cad:
        raise ValueError("inscrição não encontrada no Mapa Digital Fácil")
    at = cad[0]["attributes"]
    anel = cad[0]["geometry"]["rings"][0]
    xs, ys = [p[0] for p in anel], [p[1] for p in anel]
    centro = {"x": (min(xs) + max(xs)) / 2, "y": (min(ys) + max(ys)) / 2, "spatialReference": {"wkid": 31982}}
    ci10 = ci[:10]                                # 107-c: o desenho do lote pelo código dele (como no PTAM 122)
    try:
        div = _consulta(0, {"where": f"ci='{ci10}'", "outFields": "nm_lot,ci,shape.STArea()", "returnGeometry": "true"})
    except (httpx.HTTPError, RuntimeError, ValueError):
        div = []
    if not div:
        try:                                      # sem o código: o polígono que tem o centro do cadastro
            div = _consulta(0, {"geometry": json.dumps(centro), "geometryType": "esriGeometryPoint", "inSR": "31982",
                                "spatialRel": "esriSpatialRelIntersects", "outFields": "nm_lot,ci,shape.STArea()",
                                "returnGeometry": "true"})
        except (httpx.HTTPError, RuntimeError, ValueError):
            div = []
    if div:
        nm = (div[0].get("attributes") or {}).get("nm_lot")
        if nm not in (None, "") and not mesmo_lote(nm, at.get("nrlote")):
            raise ValueError(f"O desenho do Mapa Digital Fácil é do lote {str(nm).strip()}, mas o cadastro diz lote "
                             f"{str(at.get('nrlote') or '').strip()}. Não gerei o print: confira a inscrição ou mande o print.")
        anel = div[0]["geometry"]["rings"][0]
    # 077-B: a área do quadro é a do DESENHO do lote (Divisas de Lote, D-055); a do cadastro (= IPTU) vai à parte
    cadastro = float(at.get("areaterr") or 0)
    area = round(area_poligono(anel), 2) if div or not cadastro else cadastro
    ls = lados(anel)
    limpo = lambda v: " ".join(str(v or "").split())
    rua = limpo(at.get("nmlogradou")) or limpo(at.get("tplogradou"))   # o nome já traz o tipo ("R  XV9")
    return {"inscricao": ci, "quadra": limpo(at.get("nrquadra")), "lote": limpo(at.get("nrlote")),
            "bairro": limpo(at.get("nmbairro")).title(), "logradouro": rua, "area": br(area),
            "area_origem": "planta" if div or not cadastro else "cadastro",
            "area_planta": br(area) if div or not cadastro else "",
            "area_cadastro": br(cadastro) if cadastro else "",
            "lados": [br(x["m"]) for x in ls], "lados_seg": [{"a": x["a"], "b": x["b"], "txt": f"{br(x['m'])} m"} for x in ls],
            "anel": anel, "url": SITE, "fonte": fonte_lote(ci10) if div else f"{SERVICO}/3"}


def mesmo_lote(a, b) -> bool:
    """107-c: "2" do desenho = "02" do cadastro (sem zeros à esquerda, sem espaços)."""
    n = lambda v: re.sub(r"\s+", "", str(v or "")).upper().lstrip("0") or "0"
    return n(a) == n(b)


def fonte_lote(ci10: str) -> str:
    """O link da fonte dos dados do lote, no formato do PTAM 122 (camada de lotes do mapa básico, pelo código)."""
    return (f"{BASICO}/311/query?where=ci%3D{ci10}&outFields=nm_lot%2Cci%2Cci_qdr%2Cshape.STArea%28%29"
            f"%2Cshape.STLength%28%29&returnGeometry=true&f=html")


# ------------------------------------------------------------------ 107-d: enquadramento pelo nome das ruas
def chave_rua(t: str) -> str:
    """"R  XV9" (cadastro) e "R XV 9" (rótulo do mapa) -> "RJC4"."""
    return re.sub(r"[^A-Z0-9]", "", str(t or "").upper())


def _camadas_rotulo() -> dict[int, dict[str, list[int]]]:
    """No mapa básico, as camadas de rótulo (nome de rua e de bairro) que aparecem em cada escala do site."""
    d = json.loads(httpx.get(f"{BASICO}/layers", params={"f": "json"}, timeout=60).text)
    por = {x["id"]: x for x in d.get("layers") or []}
    out: dict[int, dict[str, list[int]]] = {}
    for x in por.values():
        nome = x.get("name") or ""
        tipo = "rua" if "Logradouro" in nome else "bairro" if ("Bairro" in nome and x.get("type") == "Annotation Layer") else ""
        if not tipo or x.get("type") != "Annotation Layer":
            continue
        mn, mx, p = x.get("minScale") or 0, x.get("maxScale") or 0, x.get("parentLayer")
        while p and not (mn or mx):
            g = por[p["id"]]
            mn, mx, p = g.get("minScale") or 0, g.get("maxScale") or 0, g.get("parentLayer")
        for esc in ESCALAS:
            if (mx or 0) <= esc <= (mn or 10 ** 9) and (mn or mx):
                out.setdefault(esc, {}).setdefault(tipo, []).append(x["id"])
    return out


def rotulos(cx: float, cy: float, escala: int, raio: float, camadas: dict) -> list[dict]:
    """Os nomes de rua e de bairro escritos no mapa, nessa escala, perto do lote: texto e retângulo (UTM)."""
    env = {"xmin": cx - raio, "ymin": cy - raio, "xmax": cx + raio, "ymax": cy + raio, "spatialReference": {"wkid": 31982}}
    out = []
    for tipo, ids in (camadas.get(escala) or {}).items():
        for i in ids:
            r = json.loads(httpx.get(f"{BASICO}/{i}/query", params={
                "geometry": json.dumps(env), "geometryType": "esriGeometryEnvelope", "inSR": "31982",
                "spatialRel": "esriSpatialRelIntersects", "outFields": "TextString", "returnGeometry": "true",
                "outSR": "31982", "f": "json"}, timeout=60).text)
            for f in r.get("features") or []:
                g = f.get("geometry") or {}
                pts = [p for parte in (g.get("rings") or g.get("paths") or []) for p in parte] or \
                      ([[g["x"], g["y"]]] if "x" in g else [])
                if not pts:
                    continue
                out.append({"txt": " ".join(str(f["attributes"].get("TextString") or "").split()), "tipo": tipo,
                            "bbox": [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]})
    return out


def enquadrar(anel, rots: list[dict], rua: str, res: float, larg: int = LARG, alt: int = ALT,
              caixa: tuple[int, int] = CAIXA) -> dict:
    """107-d: o centro do print e o canto do quadro de zoom. Quer, nesta ordem: o nome da rua do avaliando, o de uma
    rua vizinha e, se couber, o do setor — todos dentro da tela e fora do quadro; o lote fora do quadro e longe da
    borda. Devolve também quais nomes ficaram (para a resposta dizer o que não coube)."""
    xs, ys = [p[0] for p in anel], [p[1] for p in anel]
    lx, ly = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    lw, lh = (max(xs) - min(xs)) / res, (max(ys) - min(ys)) / res
    minha = chave_rua(rua)
    cw, ch = caixa
    M = 16

    def cruza(a, b, folga=0):
        return not (a[2] + folga <= b[0] or b[2] + folga <= a[0] or a[3] + folga <= b[1] or b[3] + folga <= a[1])

    melhor = None
    for u in range(int(larg * 0.15), int(larg * 0.85) + 1, 24):
        for v in range(int(alt * 0.18), int(alt * 0.82) + 1, 24):
            X, Y = lx - (u - larg / 2) * res, ly + (v - alt / 2) * res
            px = lambda x, y: ((x - X) / res + larg / 2, (Y - y) / res + alt / 2)
            lote = (u - lw / 2, v - lh / 2, u + lw / 2, v + lh / 2)
            if lote[0] < 40 or lote[1] < 40 or lote[2] > larg - 40 or lote[3] > alt - 40:
                continue
            for canto in ("se", "sd", "ie", "id"):
                bx = M if canto[1] == "e" else larg - M - cw
                by = M if canto[0] == "s" else alt - M - ch
                cx_ = (bx, by, bx + cw, by + ch)
                if cruza(lote, cx_, 60):
                    continue
                vistos = []
                for r in rots:
                    a, b = px(r["bbox"][0], r["bbox"][3]), px(r["bbox"][2], r["bbox"][1])
                    rr = (a[0], a[1], b[0], b[1])
                    if rr[0] >= 4 and rr[1] >= 4 and rr[2] <= larg - 4 and rr[3] <= alt - 4 and not cruza(rr, cx_, 4):
                        vistos.append(r)
                ruas = [r for r in vistos if r["tipo"] == "rua" and not chave_rua(r["txt"]).startswith("VIAPEDESTRE")]
                tem_rua = any(chave_rua(r["txt"]) == minha for r in ruas)
                viz = sorted({r["txt"] for r in ruas if chave_rua(r["txt"]) != minha})
                setor = sorted({r["txt"] for r in vistos if r["tipo"] == "bairro"})
                nota = (4 * tem_rua + 2 * bool(viz) + bool(setor),
                        -(abs(u - larg / 2) + abs(v - alt / 2)))       # empate: o lote mais perto do meio
                if melhor is None or nota > melhor[0]:
                    melhor = (nota, {"centro": [X, Y], "canto": canto, "res": res, "rua": tem_rua, "vizinhas": viz,
                                     "setor": setor})
    return melhor[1] if melhor else {"centro": [lx, ly], "canto": "sd", "res": res, "rua": False, "vizinhas": [], "setor": []}


def planejar(d: dict) -> dict | None:
    """O enquadramento do print: primeiro na escala 1:1.000 (a do PTAM 122); se aí não couberem o nome da rua do
    avaliando e o de uma vizinha, tenta 1:2.000. Sem resposta do mapa: None (o print sai centrado no lote)."""
    xs, ys = [p[0] for p in d["anel"]], [p[1] for p in d["anel"]]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    try:
        camadas = _camadas_rotulo()
        lods = json.loads(httpx.get(BASICO, params={"f": "json"}, timeout=60).text)["tileInfo"]["lods"]
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    res_de = {round(x["scale"]): x["resolution"] for x in lods}
    plano = None
    for esc in ESCALAS:
        if esc not in res_de:
            continue
        res = res_de[esc]
        try:
            rs = rotulos(cx, cy, esc, max(LARG, ALT) * res, camadas)
        except (httpx.HTTPError, ValueError):
            rs = []
        p = {**enquadrar(d["anel"], rs, d.get("logradouro") or "", res), "escala": esc}
        if plano is None or (p["rua"], bool(p["vizinhas"])) > (plano["rua"], bool(plano["vizinhas"])):
            plano = p
        if p["rua"] and p["vizinhas"]:
            break
    return plano


def _inscricao(jid: str) -> str:
    for c in db.campos(jid):
        if re.search(r"inscri", c.nome, re.I) and re.sub(r"\D", "", str(c.valor or "")):
            return str(c.valor)
    return ""


def aplicar_medidas(d: dict, medidas: dict | None) -> dict:
    """108-2 (preparado; a ordem que escolhe a fonte ainda vem): as quatro medidas e a área do quadro vindas de uma
    fonte escolhida — {"lados": ["11,72", "24,49", "24,62", "11,58"] (na ordem dos lados do desenho), "area": "286,09",
    "fonte": "escritura"}. Sem isso, ficam as da planta da Prefeitura. A fonte vai para a legenda (medidas_fonte)."""
    if not medidas:
        d.setdefault("medidas_fonte", "planta da Prefeitura" if d.get("area_origem") == "planta"
                     else "cadastro imobiliário da Prefeitura")
        return d
    lados = [str(x).strip() for x in medidas.get("lados") or []]
    if lados and len(lados) != len(d.get("lados_seg") or []):
        raise ValueError(f"O quadro tem {len(d.get('lados_seg') or [])} lados no desenho, mas vieram {len(lados)} medidas.")
    if lados:
        d["lados"] = lados
        d["lados_seg"] = [{**s, "txt": f"{v} m"} for s, v in zip(d["lados_seg"], lados)]
    if medidas.get("area"):
        d["area"] = str(medidas["area"]).strip()
        d["area_origem"] = "planta"            # o quadro escreve "Área: X m²"; de onde veio, a legenda diz
    d["medidas_fonte"] = str(medidas.get("fonte") or "").strip() or "informada pelo avaliador"
    return d


_NUM = r"(\d{1,4}(?:[.,]\d{1,3})?)"
_LADOS_TIT = (("frente", r"frente"), ("direito", r"lado\s+direito|direit[ao]"), ("fundo", r"fundos?"),
              ("esquerdo", r"lado\s+esquerdo|esquerd[ao]"))


def _f(v) -> float | None:
    t = str(v or "").strip()
    if not t:
        return None
    t = t.replace(".", "").replace(",", ".") if "," in t else t
    try:
        return float(t)
    except ValueError:
        return None


def medidas_do_titulo(campos) -> dict | None:
    """109-1: as quatro medidas e a área do TÍTULO adotadas no laudo (campos lidos da escritura/matrícula):
    {"frente": 11.58, "direito": 24.49, "fundo": 11.72, "esquerdo": 24.62, "area": 286.1}. Sem as quatro: None."""
    med: dict[str, float] = {}
    area = None
    for c in campos:
        nome, valor, fonte = str(c.nome or ""), str(c.valor or ""), str(getattr(c, "fonte", "") or "")
        doc = re.search(r"(?i)escritur|matr[íi]cul|t[íi]tulo|registr", nome + " " + fonte)
        if not doc:
            continue
        if re.search(r"(?i)area_terreno_(?:titulo|escritura|matricula)|[áa]rea do terreno.*(?:escritura|t[íi]tulo|matr)", nome):
            area = area or _f(re.sub(r"[^\d.,]", "", valor))
        lados_no_texto = sum(bool(re.search(rf"(?i)\b(?:{rx})\b", valor)) for _, rx in _LADOS_TIT)
        if re.search(r"(?i)confront", nome) and lados_no_texto >= 2:
            # um texto com as quatro: "Frente para a Rua XV-9: 11,58 m; lado direito, com o Lt. 03: 24,49 m; …"
            for k, rx in _LADOS_TIT:
                m = re.search(rf"(?i)\b(?:{rx})\b[^:;]{{0,80}}?:\s*{_NUM}\s*m", valor)
                if m and k not in med:
                    med[k] = _f(m.group(1))
            continue
        # um campo por lado (111-1): "confrontacao_frente" = "Rua XV-9 – 11,58 m";
        # "Frente do terreno – Rua XV-9 (escritura)" = 11.58
        nome_l = nome.replace("_", " ")
        for k, rx in _LADOS_TIT:
            if k in med or not re.search(rf"(?i)\b(?:{rx})\b", nome_l):
                continue
            ms = re.findall(rf"{_NUM}\s*m\b", valor)
            v = _f(ms[-1]) if ms else _f(valor)
            if v is not None:
                med[k] = v
            break
    if len(med) < 4 or any(v is None or v <= 0 for v in med.values()):
        return None
    return {**med, "area": area}


def casar_lados(planta: list[float], tit: dict, tol: float = 0.10) -> list[float] | None:
    """Põe cada medida do título no lado certo do desenho: a volta do lote é frente, um lado, fundo, o outro lado;
    das 8 voltas possíveis fica a de menor diferença. Se algum lado diferir mais de 10% (o desenho não é o do
    título), None — o quadro fica com a planta."""
    if len(planta) != 4:
        return None
    volta = [tit["frente"], tit["direito"], tit["fundo"], tit["esquerdo"]]
    melhor = None
    for seq in (volta, volta[::-1]):
        for i in range(4):
            cand = seq[i:] + seq[:i]
            dif = sum(abs(a - b) for a, b in zip(planta, cand))
            if melhor is None or dif < melhor[0]:
                melhor = (dif, cand)
    cand = melhor[1]
    if any(abs(a - b) > tol * max(a, b) for a, b in zip(planta, cand)):
        return None
    return cand


def medidas_adotadas(jid: str, d: dict) -> dict | None:
    """109-1: o quadro mostra o que o laudo adota — as medidas e a área da escritura registrada, se o título as tem e
    elas casam com o desenho; senão None (fica a planta da Prefeitura)."""
    tit = medidas_do_titulo(db.campos(jid))
    if not tit:
        return None
    planta = [float(s["m"]) if "m" in s else _f(s["txt"].replace(" m", "")) for s in d.get("lados_seg") or []]
    lados = casar_lados([x for x in planta if x is not None], tit)
    if not lados:
        db.evento(jid, "localizacao", "aviso", "Mapa Digital Fácil: as medidas da escritura não casam com o desenho do "
                  "lote na planta da Prefeitura; o quadro ficou com as da planta (confira).")
        return None
    return {"lados": [br(x) for x in lados], "area": br(tit["area"]) if tit.get("area") else "",
            "fonte": "escritura registrada"}


def gerar(jid: str, medidas: dict | None = None) -> dict:
    """Gera o print e grava no contrato do anexo. Erros viram ValueError com a frase para o avaliador."""
    t = db.job(jid)["dados"]
    if (t.get("cidade") or "Goiânia").strip().lower() not in ("goiânia", "goiania"):
        raise ValueError("O Mapa Digital Fácil é só de Goiânia. Para outra cidade, mande o print do cadastro da prefeitura.")
    insc = _inscricao(jid)
    if not insc:
        raise ValueError("Não achei a inscrição imobiliária nos documentos. Mande o print do Mapa Digital Fácil.")
    try:
        d = dados_lote(insc)
    except (httpx.HTTPError, RuntimeError) as e:
        raise ValueError(f"O Mapa Digital Fácil não respondeu ({e}). Tente de novo mais tarde ou mande o print.")
    # 078-2: a hora da consulta é uma só, no horário de Brasília (carimbo da imagem = legenda do laudo)
    adot = medidas or medidas_adotadas(jid, d)                  # 108-2 / 109-1: o que o laudo adota (escritura)
    aplicar_medidas(d, adot)
    d["titulo_recusado"] = adot is None and bool(medidas_do_titulo(db.campos(jid)))   # não casou com o desenho
    agora = datetime.now(timezone(timedelta(hours=-3)))
    d["consultado_em"] = agora.strftime("%d/%m/%Y %H:%M")
    d["plano"] = planejar(d) if ATIVO else None
    d["setor_no_titulo"] = not (d["plano"] or {}).get("setor")      # 109-1: "Quadra 59 – Lote 2 · Jd Curitiba"   # 107-d (nos testes automáticos não vai ao site): o zoom em que aparecem os nomes das ruas (e do setor)
    destino = db.pasta(jid) / ARQ
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        ent = Path(tmp) / "entrada.json"
        ent.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([str(COLETOR_PY if COLETOR_PY.exists() else sys.executable), str(COLETOR_SCRIPT), str(ent), str(destino)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)
    if r.returncode == 3:
        raise ValueError("O Mapa Digital Fácil pediu uma verificação de pessoa. Abra o site, resolva e mande o print.")
    if r.returncode != 0 or not destino.exists():
        raise ValueError("Não consegui tirar o print do Mapa Digital Fácil. Mande o print.")
    if not any(a.get("caminho") == ARQ for a in db.arquivos(jid)):
        db.adicionar_arquivo(jid, "mapa_digital_facil.png", "mapa_digital", ARQ, "", "")
    dados = {k: d[k] for k in ("inscricao", "quadra", "lote", "area", "area_origem", "area_planta", "area_cadastro", "lados", "url",
                               "bairro", "logradouro", "consultado_em")}
    dados["consulta_interna"] = d["fonte"]      # 108-1: o endereço do servidor fica só por dentro, nunca no laudo
    dados["consultado_em_iso"] = agora.isoformat(timespec="seconds")     # com -03:00
    dados["imagem"] = ARQ
    dados["titulo_recusado"] = d.get("titulo_recusado", False)
    dados["medidas_fonte"] = d.get("medidas_fonte", "")     # 108-2: a legenda diz de onde vêm as medidas do quadro
    p = d.get("plano") or {}
    dados["enquadramento"] = {"escala": p.get("escala"), "rua": p.get("rua"), "vizinhas": p.get("vizinhas"),
                              "setor": p.get("setor")}
    db.evento(jid, "localizacao", "mapa_digital",
              f"Mapa Digital Fácil: quadra {d['quadra']}, lote {d['lote']}, área do lote (planta) {d['area']} m² "
              f"(lados {' · '.join(d['lados'])} m)"
              + (f"; cadastro imobiliário {d['area_cadastro']} m²" if d["area_cadastro"] and d["area_cadastro"] != d["area"] else ""),
              dados=dados)
    return dados


@router.post("/jobs/{jid}/mapa-digital")
async def mapa_digital(jid: str, _u: dict = Depends(_dono)):
    """"Gerar o print do Mapa Digital Fácil" (o JdB faz sozinho; sem inscrição ou fora de Goiânia, diz o que mandar)."""
    import asyncio
    _livre(jid)
    _job(jid)
    try:
        return await asyncio.to_thread(gerar, jid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# nos testes automáticos a montagem não vai ao site da Prefeitura (o teste do garantir liga isto à mão)
ATIVO = "pytest" not in sys.modules


def _ultimo_gerado(jid: str) -> dict:
    with db._conn() as c:
        r = c.execute("SELECT dados_json FROM av_events WHERE job=? AND etapa='localizacao' AND nivel='mapa_digital' "
                      "ORDER BY id DESC LIMIT 1", (jid,)).fetchone()
    try:
        return json.loads(r["dados_json"] or "{}") if r else {}
    except ValueError:
        return {}


def desatualizado(jid: str) -> bool:
    """111-1: o print que existe foi feito com a planta, mas agora o laudo tem as medidas da escritura (ou o print é
    de antes da 109-1, sem dizer a fonte): tem de ser refeito. Sem rede: só compara com os campos do trabalho."""
    if not medidas_do_titulo(db.campos(jid)):
        return False
    u = _ultimo_gerado(jid)
    return u.get("medidas_fonte") != "escritura registrada" and not u.get("titulo_recusado")


def ja_tem(jid: str) -> bool:
    return (any(a.get("caminho") == ARQ for a in db.arquivos(jid)) and (db.pasta(jid) / ARQ).is_file()
            and not desatualizado(jid))


def garantir(jid: str) -> dict | None:
    """085-4: em TODO trabalho de Goiânia, o anexo do Mapa Digital Fácil sai sozinho antes da montagem.
    Já existe, fora de Goiânia ou sem inscrição: não faz nada. Falha (site fora, verificação): fica um aviso no
    histórico e a montagem segue — o avaliador manda o print (1(a)). Nunca derruba a montagem."""
    if not ATIVO:
        return None
    try:
        t = db.job(jid)["dados"]
        if (t.get("cidade") or "").strip().lower() not in ("goiânia", "goiania") or ja_tem(jid) or not _inscricao(jid):
            return None
        return gerar(jid)
    except ValueError as e:
        db.evento(jid, "localizacao", "aviso", f"Mapa Digital Fácil não gerado: {e}")
    except Exception as e:      # noqa: BLE001 — o mapa nunca para o laudo
        db.evento(jid, "localizacao", "aviso", f"Mapa Digital Fácil não gerado ({type(e).__name__})")
    return None
