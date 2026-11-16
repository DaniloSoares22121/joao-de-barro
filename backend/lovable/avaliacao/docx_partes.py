"""Peças de baixo nível do Word (OOXML via python-docx) usadas pelo docx_builder:
formatação pt-BR, troca de texto preservando estilo, imagens, hiperlinks e campos."""
from __future__ import annotations

import copy
import re
import unicodedata
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from PIL import Image

def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.casefold().replace("_", " ").split())


# ------------------------------------------------------------------ formatação
_MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro")


def num(v, casas: int = 2) -> str:
    d = Decimal(str(v)).quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    s = f"{d:,.{casas}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def brl(v) -> str:
    return "R$ " + num(v)


def pct(v) -> str:
    d = Decimal(str(v)).normalize()
    return format(d, "f").replace(".", ",")


def data_extenso(d: date) -> str:
    return f"{d.day} de {_MESES[d.month - 1]} de {d.year}"


# ------------------------------------------------------------------ parágrafos
def texto(el) -> str:
    return "".join(t.text or "" for t in el.iter(qn("w:t")))


def runs_texto(p) -> list:
    return [r for r in p.iter(qn("w:r")) if r.find(qn("w:t")) is not None]


_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def limpo(s) -> str:
    """Texto sem caracteres que o XML do Word recusa. Um form feed vindo de um PDF, num
    campo ou no texto da IA, derrubava a montagem inteira ("All strings must be XML
    compatible") e o trabalho fechava sem laudo."""
    return _CONTROLE.sub(" ", "" if s is None else str(s))


def _set_t(r, s: str) -> None:
    ts = r.findall(qn("w:t"))
    for t in ts[1:]:
        r.remove(t)
    for tab in r.findall(qn("w:tab")):
        r.remove(tab)
    ts[0].text = limpo(s)
    ts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def definir(p, s: str) -> None:
    """Texto do parágrafo inteiro no 1º run com texto (mantém sua formatação)."""
    rs = runs_texto(p)
    if not rs:
        r = OxmlElement("w:r")
        r.append(OxmlElement("w:t"))
        p.append(r)
        rs = [r]
    _set_t(rs[0], s)
    for r in rs[1:]:
        r.getparent().remove(r)


def definir_valor(p, s: str) -> None:
    """Mantém o 1º run (rótulo em negrito) e põe `s` no 2º, removendo os demais."""
    rs = runs_texto(p)
    if len(rs) < 2:
        definir(p, s)
        return
    _set_t(rs[1], s)
    for r in rs[2:]:
        r.getparent().remove(r)


def subst(el, velho: str, novo: str) -> bool:
    achou = False
    for t in el.iter(qn("w:t")):
        if t.text and velho in t.text:
            t.text = t.text.replace(velho, limpo(novo))
            achou = True
    return achou


def rpr_base(p):
    rs = runs_texto(p)
    rpr = rs[-1].find(qn("w:rPr")) if rs else None
    return copy.deepcopy(rpr) if rpr is not None else OxmlElement("w:rPr")


def novo_run(s: str, rpr=None, negrito: bool | None = None):
    r = OxmlElement("w:r")
    rp = copy.deepcopy(rpr) if rpr is not None else OxmlElement("w:rPr")
    if negrito is not None:
        for b in rp.findall(qn("w:b")):
            rp.remove(b)
        b = OxmlElement("w:b")
        if not negrito:
            b.set(qn("w:val"), "0")
        rp.insert(0, b)
    r.append(rp)
    t = OxmlElement("w:t")
    t.text = limpo(s)
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r.append(t)
    return r


def limpar_runs(p) -> None:
    for ch in list(p):
        if ch.tag != qn("w:pPr"):
            p.remove(ch)


def remover(el) -> None:
    if el is not None and el.getparent() is not None:
        el.getparent().remove(el)


def inserir_apos(ref, novo):
    ref.addnext(novo)
    return novo


def tem_imagem(el) -> bool:
    return el.find(".//" + qn("w:drawing")) is not None


def set_outline(p, nivel: int) -> None:
    ppr = p.get_or_add_pPr()
    for o in ppr.findall(qn("w:outlineLvl")):
        ppr.remove(o)
    o = OxmlElement("w:outlineLvl")
    o.set(qn("w:val"), str(nivel))
    ppr.insert_element_before(o, "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")


# ------------------------------------------------------------------ imagens
def caber(img: Path, max_cx: int, max_cy: int) -> tuple[int, int]:
    with Image.open(img) as im:
        w, h = im.size
    esc = min(max_cx / w, max_cy / h)
    return int(w * esc), int(h * esc)


DPI_IMAGEM = 200          # resolução final das imagens no Word (impressão boa, arquivo leve)
QUALIDADE_JPEG = 82


def comprimir(img: Path, cx: int, cy: int) -> Path:
    """Cópia da imagem reduzida ao tamanho em que aparece (DPI_IMAGEM) e em JPEG: fotos de
    celular de 3–4 MB deixavam o .docx com 20+ MB. PNG com transparência fica como está.
    Cache em %TEMP%/jdb-img (chave = caminho + data + tamanho + caixa)."""
    import hashlib
    import tempfile
    img = Path(img)
    alvo_w = max(1, int(cx / 914400 * DPI_IMAGEM))
    alvo_h = max(1, int(cy / 914400 * DPI_IMAGEM))
    try:
        st = img.stat()
        with Image.open(img) as im:
            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                return img
            if im.width <= alvo_w * 1.15 and st.st_size <= 400_000:
                return img
            chave = hashlib.sha1(f"{img.resolve()}|{st.st_mtime_ns}|{st.st_size}|{alvo_w}x{alvo_h}"
                                 .encode()).hexdigest()[:20]
            pasta = Path(tempfile.gettempdir()) / "jdb-img"
            pasta.mkdir(exist_ok=True)
            destino = pasta / f"{chave}.jpg"
            if not destino.is_file():
                im2 = im.convert("RGB")
                im2.thumbnail((alvo_w, alvo_h), Image.LANCZOS)
                im2.save(destino, "JPEG", quality=QUALIDADE_JPEG, optimize=True)
            return destino
    except (OSError, ValueError):
        return img


def trocar_imagem(container, part, img: Path, max_cx: int, max_cy: int) -> None:
    """Troca a imagem do 1º w:drawing de `container`, ajustando o tamanho à caixa."""
    cx, cy = caber(img, max_cx, max_cy)
    img = comprimir(img, cx, cy)
    rid, _ = part.get_or_add_image(str(img))
    dr = container.find(".//" + qn("w:drawing"))
    dr.find(".//" + qn("a:blip")).set(qn("r:embed"), rid)
    for tag in ("wp:extent", "a:ext"):
        for e in dr.iter(qn(tag)):
            e.set("cx", str(cx))
            e.set("cy", str(cy))


def medida_imagem(container) -> tuple[int, int]:
    e = container.find(".//" + qn("wp:extent"))
    return int(e.get("cx")), int(e.get("cy"))


def remover_imagens(container) -> None:
    for dr in list(container.iter(qn("w:drawing"))):
        r = dr.getparent()
        remover(r)


def renumerar_docpr(body) -> None:
    for i, e in enumerate(body.iter(qn("wp:docPr")), start=1):
        e.set("id", str(i))


# ------------------------------------------------------------------ hiperlinks e campos
def apontar_hyperlink(h, part, url: str, rotulo: str | None = None) -> None:
    """Aponta um w:hyperlink existente para `url` (nova relação externa)."""
    h.set(qn("r:id"), part.relate_to(url, RT.HYPERLINK, is_external=True))
    rs = runs_texto(h)
    if rs:
        _set_t(rs[0], rotulo if rotulo is not None else url)
        for r in rs[1:]:
            remover(r)


def novo_hyperlink(part, url: str, rotulo: str, rpr=None):
    h = OxmlElement("w:hyperlink")
    h.set(qn("r:id"), part.relate_to(url, RT.HYPERLINK, is_external=True))
    rp = copy.deepcopy(rpr) if rpr is not None else OxmlElement("w:rPr")
    for tag in ("w:color", "w:u"):
        for e in rp.findall(qn(tag)):
            rp.remove(e)
    cor = OxmlElement("w:color")
    cor.set(qn("w:val"), "0563C1")
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rp.append(cor)
    rp.append(u)
    h.append(novo_run(rotulo, rp))
    return h


def _fld(tipo: str, rpr=None, dirty=False):
    r = OxmlElement("w:r")
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    f = OxmlElement("w:fldChar")
    f.set(qn("w:fldCharType"), tipo)
    if dirty:
        f.set(qn("w:dirty"), "true")
    r.append(f)
    return r


def _instr(instr: str, rpr=None):
    r = OxmlElement("w:r")
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    t = OxmlElement("w:instrText")
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = f" {instr} "
    r.append(t)
    return r


def campo_runs(instr: str, cache: str, rpr=None, dirty=False) -> list:
    """Runs de um campo simples (begin/instr/separate/cache/end)."""
    return [_fld("begin", rpr, dirty), _instr(instr, rpr), _fld("separate", rpr),
            novo_run(cache, rpr), _fld("end", rpr)]


def _negrito(rpr):
    r = copy.deepcopy(rpr)
    r.insert(0, OxmlElement("w:b"))
    return r


def estilos_sumario(doc, compacto: bool = False) -> None:
    """Cria os estilos "toc 1" (negrito, como no P8) e "toc 2" se o modelo não os tiver —
    o LibreOffice/Word aplicam esses estilos ao refazer o campo TOC."""
    from docx.enum.style import WD_STYLE_TYPE
    from docx.shared import Pt
    nomes = {s.name.lower() for s in doc.styles}
    for nivel in (1, 2):
        nome = f"toc {nivel}"
        if nome in nomes:
            st = next(s for s in doc.styles if s.name.lower() == nome)
        else:
            st = doc.styles.add_style(nome, WD_STYLE_TYPE.PARAGRAPH)
            st.base_style = doc.styles["Normal"]
            st.element.set(qn("w:styleId"), f"TOC{nivel}")
        st.font.bold = nivel == 1
        st.font.size = Pt(10)
        if compacto:
            # ORDEM 030: o LibreOffice/Word refazem o sumário com ESTE estilo — sumário longo
            # (ex.: PTAM judicial) deixava 1 linha sozinha na página seguinte
            st.paragraph_format.space_before = Pt(0)
            st.paragraph_format.space_after = Pt(1)
            st.paragraph_format.line_spacing = 1.05


SUMARIO_LONGO = 29   # linhas a partir das quais o sumário fica compacto (cabem ~29 por página)


def sumario(modelo_ppr, entradas: list[tuple[str, str, int]]) -> list:
    """Parágrafos de um campo TOC clicável (\\h). `entradas` = (título, bookmark, nível) e
    forma o resultado em cache: cada linha é hiperlink interno + PAGEREF (calculado na
    paginação pelo Word/LibreOffice). O campo vai marcado como dirty para ser refeito."""
    rpr = OxmlElement("w:rPr")
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), "20")
    rpr.append(sz)
    pars = []
    for i, (titulo, bm, nivel) in enumerate(entradas):
        p = OxmlElement("w:p")
        ppr = copy.deepcopy(modelo_ppr) if modelo_ppr is not None else OxmlElement("w:pPr")
        for ind in ppr.findall(qn("w:ind")):
            ppr.remove(ind)
        for st in ppr.findall(qn("w:pStyle")):
            ppr.remove(st)
        st = OxmlElement("w:pStyle")
        st.set(qn("w:val"), f"TOC{nivel + 1}")  # estilos do sumário (nível 1 em negrito)
        ppr.insert(0, st)
        if nivel:
            ind = OxmlElement("w:ind")
            ind.set(qn("w:left"), "908" if re.match(r"^\d+\.\d+\s+–\s", titulo) else "454")   # D-133
            ppr.append(ind)
        if len(entradas) >= SUMARIO_LONGO:
            # ORDEM 030: sumário longo (PTAM judicial com quesitos) passava 1 linha para outra
            # página, quase vazia — linhas mais juntas para caber numa página só
            for sp in ppr.findall(qn("w:spacing")):
                ppr.remove(sp)
            sp = OxmlElement("w:spacing")
            sp.set(qn("w:before"), "0")
            sp.set(qn("w:after"), "20")
            sp.set(qn("w:line"), "252")
            sp.set(qn("w:lineRule"), "auto")
            ppr.append(sp)
        p.append(ppr)
        rpr_e = rpr if nivel else _negrito(rpr)
        if i == 0:
            p.append(_fld("begin", rpr, dirty=True))
            p.append(_instr('TOC \\o "1-2" \\h \\z \\u', rpr))
            p.append(_fld("separate", rpr))
        h = OxmlElement("w:hyperlink")
        h.set(qn("w:anchor"), bm)
        h.set(qn("w:history"), "1")
        h.append(novo_run(titulo, rpr_e))
        tab = OxmlElement("w:r")
        tab.append(copy.deepcopy(rpr_e))
        tab.append(OxmlElement("w:tab"))
        h.append(tab)
        for r in campo_runs(f"PAGEREF {bm} \\h", "", rpr_e):
            h.append(r)
        p.append(h)
        pars.append(p)
    if pars:
        pars[-1].append(_fld("end", rpr))
    return pars


def texto_por_partes(t: str) -> list[str]:
    """Parágrafos separados por linha em branco; dentro de um parágrafo, linhas de lista ("- …", "• …") viram um
    parágrafo cada (087: no 9120 o item 10 saiu numa linha só, "- casa térrea…; - idade aparente…")."""
    out: list[str] = []
    for bloco in re.split(r"\n\s*\n", t.strip()):
        linhas = [ln.strip() for ln in bloco.splitlines() if ln.strip()]
        itens = [ln for ln in linhas if re.match(r"^[-•*–]\s+", ln)]
        if len(itens) >= 2:
            for ln in linhas:
                out.append("• " + re.sub(r"^(?:[-•*–—]\s+)+", "", ln) if re.match(r"^[-•*–]\s+", ln) else ln)
        elif bloco.strip():
            out.append(bloco.strip())
    return out


# ------------------------------------------------------------------ estrutura (títulos, seções, sumário)
_RE_TITULO = re.compile(r"^(\d+(?:\.\d+)*)\.\s")
PLACEHOLDER = "[PREENCHER"


def linhas_rotulo(t: str) -> dict[str, str]:
    out = {}
    for ln in t.splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            out[norm(k)] = v.strip()
    return out


def titulos(ctx) -> list:
    return [p for p in ctx.pars()
            if any((b.get(qn("w:name")) or "").startswith("sec")
                   for b in p.iter(qn("w:bookmarkStart")))]


def _parecido(a: str, b: str) -> bool:
    """Mesmo parágrafo em outra redação: igualdade, um contém o outro, ou ≥ 70% iguais."""
    import difflib
    a, b = norm(a).strip(" .;-•*"), norm(b).strip(" .;-•*")
    if not a or not b:
        return False
    if a == b or (len(a) > 40 and a[:60] in b) or (len(b) > 40 and b[:60] in a):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.7


def escrever(ctx, alvo, conteudo: str, fixos: list[str] = ()) -> list:
    """Substitui o parágrafo-modelo `alvo` pelos parágrafos de `conteudo`. Parágrafo que
    repete um texto fixo da mesma seção (`fixos`) ou outro já escrito é descartado: a IA
    reescrevia a definição de valor de mercado e as ressalvas genéricas, que o modelo já tem."""
    ppr = alvo.find(qn("w:pPr"))
    lista = ppr is not None and ppr.find(qn("w:pStyle")) is not None and \
        "List" in (ppr.find(qn("w:pStyle")).get(qn("w:val")) or "")
    partes = [ln.strip() for ln in conteudo.splitlines() if ln.strip()] if lista \
        else texto_por_partes(conteudo)
    unicos: list[str] = []
    for parte in partes:
        if any(_parecido(parte, f) for f in fixos) or any(_parecido(parte, u) for u in unicos):
            if hasattr(ctx, "aviso"):
                ctx.aviso(f"parágrafo repetido descartado: {parte[:80]}")
            continue
        unicos.append(parte)
    partes = unicos
    rpr = rpr_base(alvo)
    ref, novos = alvo, []
    sub = False                     # 105-4: os pontos abaixo de "Estado de conservação:" são subitens (recuados)
    for parte in partes:
        p = copy.deepcopy(alvo)
        limpar_runs(p)
        if lista:
            marcado = bool(re.match(r"^[-•*–—]", parte))
            if re.match(r"(?i)^[-•*–— ]*estado de conserva", parte):
                sub = True
                recua = False
            else:
                topico = bool(re.match(r"^[-•*–— ]*[^:]{2,40}:\s+\S", parte))
                recua = sub and marcado and not topico
                if topico or not marcado:
                    sub = False                 # o tópico seguinte (ou a frase final) encerra os subitens
            if recua:
                pp = p.find(qn("w:pPr"))
                if pp is None:
                    pp = OxmlElement("w:pPr")
                    p.insert(0, pp)
                for e in pp.findall(qn("w:ind")):
                    pp.remove(e)
                ind = OxmlElement("w:ind")
                ind.set(qn("w:left"), "1080")
                ind.set(qn("w:hanging"), "360")
                pp.append(ind)
        parte = parte.lstrip("-•*–— ").strip() if lista else parte      # 093-A-12: um marcador só
        m = re.match(r"^([^:]{2,40}):\s+(.*)$", parte) if lista else None
        if m:
            p.append(novo_run(m.group(1) + ": ", rpr, negrito=True))
            p.append(novo_run(m.group(2), rpr, negrito=False))
        else:
            p.append(novo_run(parte, rpr))
        ref = inserir_apos(ref, p)
        novos.append(p)
    remover(alvo)
    return novos


def secoes(ctx) -> None:
    chave, grupos, tits = None, {}, set(titulos(ctx))
    fixos: dict[str, list[str]] = {}
    so_amj: set[str] = set()
    for el in list(ctx.body):
        if el.tag == qn("w:p"):
            m = _RE_TITULO.match(texto(el).strip())
            if m and el in tits:
                chave = m.group(1)
                if "(somente AMJ)" in texto(el):
                    so_amj.add(chave)
                continue
            if PLACEHOLDER in texto(el) and chave:
                grupos.setdefault(chave, []).append(el)
            elif chave and texto(el).strip():
                fixos.setdefault(chave, []).append(texto(el).strip())
    for k, els in grupos.items():
        conteudo = (ctx.textos.secoes.get(k) or "").strip()
        if not conteudo:
            if not (k in so_amj and ctx.t.modalidade != "AMJ"):   # item só do AMJ: sai calado
                ctx.aviso(f"seção {k} sem texto da redação")
            for e in els:
                remover(e)
            continue
        escrever(ctx, els[0], conteudo, fixos.get(k, []))
        for e in els[1:]:
            remover(e)


def processo_amj(ctx) -> None:
    tb = ctx.tabela("Campo")
    if tb is None:
        return
    t = ctx.t
    partes = ""
    if t.partes and (t.partes.autor.strip() or t.partes.reu.strip()):
        partes = (f"Autor: {t.partes.autor.strip() or 'n/i'}; "
                  f"Réu: {t.partes.reu.strip() or 'n/i'}")
    vals = {"processo no": t.processo_numero.strip(), "juizo / vara": t.vara_juizo.strip(),
            "acao": t.acao.strip() or "—", "partes": partes}
    for tr in tb.findall(qn("w:tr"))[1:]:
        tcs = tr.findall(qn("w:tc"))
        v = vals.get(norm(texto(tcs[0])), "")
        definir(tcs[1].find(qn("w:p")), v or "n/i")


def modalidade(ctx) -> None:
    """Itens 'somente AMJ': saem fora do AMJ; no AMJ perdem a anotação."""
    amj = ctx.t.modalidade == "AMJ"
    tits = titulos(ctx)
    for h in tits:
        txt = texto(h)
        if "(AMJ; opcional em AM)" in txt:
            subst(h, " (AMJ; opcional em AM)", "")
        if "(somente AMJ)" not in txt:
            continue
        if amj:
            subst(h, " (somente AMJ)", "")
            continue
        el = h.getnext()
        while el is not None and el not in tits and el.tag != qn("w:sectPr"):
            prox = el.getnext()
            remover(el)
            el = prox
        remover(h)
    if amj:
        processo_amj(ctx)


def renumerar(ctx) -> None:
    """Renumera títulos após remoções (ex.: AM sem itens do AMJ)."""
    n, mapa = 0, {}
    for h in titulos(ctx):
        m = _RE_TITULO.match(texto(h).strip())
        if not m:
            continue
        num = m.group(1)
        partes = num.split(".")
        if len(partes) == 1:
            n += 1
            mapa[partes[0]] = str(n)
            novo = str(n)
        else:
            novo = ".".join([mapa.get(partes[0], partes[0]), *partes[1:]])
        if novo != num:
            subst(h, f"{num}. ", f"{novo}. ")
            subst(h, f"{num}.", f"{novo}.")


def montar_sumario(ctx) -> None:
    alvo = next((h for h in titulos(ctx) if "SUMÁRIO" in texto(h)), None)
    entradas = []
    for h in titulos(ctx):
        if h is alvo:
            continue
        txt = texto(h).strip()
        m = _RE_TITULO.match(txt)
        nivel = 1 if (txt.startswith("Anexo") or (m and "." in m.group(1))) else 0
        if re.match(r"^\d+\.\d+\s+–\s", txt):      # D-133: "3.1 – Escritura" (documento dentro do anexo):
            nivel = 1                                 # nível do anexo, com recuo maior no sumário
        set_outline(h, nivel)
        bm = next(b.get(qn("w:name")) for b in h.iter(qn("w:bookmarkStart")))
        entradas.append((txt, bm, nivel))
    if alvo is None:
        return
    modelo_ppr = None
    el = alvo.getnext()
    while el is not None and el.tag != qn("w:sectPr"):
        prox = el.getnext()
        if modelo_ppr is None and el.tag == qn("w:p") and el.find(qn("w:pPr")) is not None:
            modelo_ppr = copy.deepcopy(el.find(qn("w:pPr")))
        remover(el)
        el = prox
    estilos_sumario(ctx.doc, compacto=len(entradas) >= SUMARIO_LONGO)
    ref = alvo
    for p in sumario(modelo_ppr, entradas):
        ref = inserir_apos(ref, p)
    st = ctx.doc.settings.element
    if st.find(qn("w:updateFields")) is None:
        uf = OxmlElement("w:updateFields")
        uf.set(qn("w:val"), "true")
        st.insert_element_before(
            uf, "w:hdrShapeDefaults", "w:footnotePr", "w:endnotePr", "w:compat", "w:docVars",
            "w:rsids", "m:mathPr", "w:attachedSchema", "w:themeFontLang",
            "w:clrSchemeMapping", "w:doNotIncludeSubdocsInStats",
            "w:doNotAutoCompressPictures", "w:forceUpgrade", "w:captions",
            "w:readModeInkLockDown", "w:smartTagType", "w:schemaLibrary",
            "w:shapeDefaults", "w:doNotEmbedSmartTags", "w:decimalSymbol",
            "w:listSeparator")


# ------------------------------------------------------------------ paginação
def _prender(p, proximo: bool = True) -> None:
    from docx.text.paragraph import Paragraph
    f = Paragraph(p, None).paragraph_format
    f.keep_together = True
    if proximo:
        f.keep_with_next = True


# Texto (caracteres) que ainda cabe numa página junto com a assinatura; acima disso, só os
# 2 últimos parágrafos das Declarações acompanham a assinatura.
LIMITE_JUNTOS = 2200


def _inicio_assinatura(ps, txt, i: int) -> int:
    """Início do bloco preso à assinatura: título das Declarações (seção inteira, incluindo
    "composto por N páginas" e o que houver entre ela e a assinatura); se for longo demais
    para caber numa página, os 2 últimos parágrafos das Declarações."""
    d = next((k for k in range(i - 1, -1, -1)
              if re.fullmatch(r"(\d+\.\s*)?DECLARAÇÕES.*", txt[k])), None)
    if d is None:
        return max(i - 1, 0)
    if sum(len(t) for t in txt[d:i]) <= LIMITE_JUNTOS:
        return d
    tits = [k for k in range(d + 1, i) if _RE_TITULO.match(txt[k])]
    fim_decl = tits[0] if tits else i  # seção seguinte às Declarações (ex.: qualificação)
    corpo = [k for k in range(d + 1, fim_decl) if txt[k]]
    return corpo[-2] if len(corpo) >= 2 else d


def manter_juntos(ctx) -> None:
    """Assinatura nunca sozinha numa página; bloco do valor adotado indivisível."""
    ps = list(ctx.body.iter(qn("w:p")))
    txt = [texto(p).strip() for p in ps]
    i = next((k for k, t in enumerate(txt) if re.fullmatch(r"(\d+\.\s*)?ASSINATURA", t)), None)
    if i is not None:
        fim = next((k for k in range(i + 1, len(ps))
                    if "ANEXOS" in txt[k] or ps[k].find(".//" + qn("w:pageBreakBefore")) is not None),
                   len(ps))
        for p in ps[_inicio_assinatura(ps, txt, i):fim - 1]:
            _prender(p)
        if fim - 1 > i:
            _prender(ps[fim - 1], proximo=False)
    v = next((k for k, t in enumerate(txt) if t == "VALOR DE MERCADO ADOTADO"), None)
    if v is not None:
        for k, p in enumerate(ps[v:v + 3]):
            _prender(p, proximo=k < 2)
