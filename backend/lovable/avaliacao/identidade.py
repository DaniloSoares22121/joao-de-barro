"""Identidade visual do Alan (D-040) e layout travado (P9 / REGRAS_GERADOR_D040).

Aplicada pelo docx_builder no fim da montagem, sobre o documento já preenchido:
página A4 e margens, Arial 11 justificado, capa (logo horizontal 8 cm no cabeçalho da 1ª
página, título azul 24 pt, nº amarelo 14 pt, linhas finas), cabeçalho interno (logo 4 cm +
"Modalidade N.º X · Data-base" em cinza 8 pt + linha amarela grossa), rodapé de 2 lados com
links, títulos com barra amarela, tabelas com cabeçalho azul/texto branco, caixa azul do
valor com o valor em amarelo. Sem marca d'água.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from PIL import Image

from . import docx_partes as X

AZUL, AMARELO, CINZA, LINHA, BRANCO = "18283B", "F5B800", "5B6470", "D5D9DF", "FFFFFF"
FONTE, TAMANHO = "Arial", 11.0      # L198: o modelo do avaliador pode trocar a fonte e o tamanho do corpo
PASTA = Path(__file__).parent / "assets" / "identidade"
LOGO = PASTA / "logo-horizontal.png"


def _logo_enviada() -> Path:
    from lovable import config
    return config.DATA_DIR / "identidade" / "logo-horizontal.png"


LOGO_ENVIADA = _logo_enviada()   # enviada pela tela de Configurações (prevalece)


# ORDEM 042 (D-095): laudo de outro avaliador usa a logo DELE (ou nenhuma: visual neutro)
_LOGO_FORCADA: Path | None | str = "padrao"
_AV_LAUDO = "AV-0001"


def caminho_logo() -> Path | None:
    if _LOGO_FORCADA != "padrao":
        return _LOGO_FORCADA
    return LOGO_ENVIADA if LOGO_ENVIADA.is_file() else (LOGO if LOGO.is_file() else None)


from contextlib import contextmanager  # noqa: E402


@contextmanager
def do_avaliador(av: str, modalidade: str = ""):
    """Paleta e logo do avaliador dono do laudo durante a montagem. O Alan (AV-0001) não muda
    nada (D-040). Outro avaliador: cores e logo dele; sem logo, neutro e sem marca."""
    global AZUL, AMARELO, CINZA, _LOGO_FORCADA, _AV_LAUDO, FONTE, TAMANHO
    antes = (AZUL, AMARELO, CINZA, _LOGO_FORCADA, _AV_LAUDO, FONTE, TAMANHO)
    _AV_LAUDO = av or "AV-0001"
    if _AV_LAUDO != "AV-0001":
        from . import avaliadores
        c = avaliadores.cores(_AV_LAUDO)
        AZUL, AMARELO, CINZA = c["principal"], c["destaque"], c["texto"]
        _LOGO_FORCADA = avaliadores.logo(_AV_LAUDO)
    if modalidade:                       # L198: a formatação do modelo que ele subiu para essa modalidade
        from . import avaliadores
        f = (avaliadores.modelo_do_laudo(_AV_LAUDO, modalidade) or {}).get("formato") or {}
        if re.fullmatch(r"[A-Za-z0-9 ]{2,40}", f.get("fonte") or ""):
            FONTE = f["fonte"]
        if isinstance(f.get("tamanho"), (int, float)) and 8 <= f["tamanho"] <= 14:
            TAMANHO = float(f["tamanho"])
        if re.fullmatch(r"[0-9A-Fa-f]{6}", f.get("cor_principal") or ""):
            AZUL = f["cor_principal"].upper()
        if re.fullmatch(r"[0-9A-Fa-f]{6}", f.get("cor_destaque") or ""):
            AMARELO = f["cor_destaque"].upper()
    try:
        yield
    finally:
        AZUL, AMARELO, CINZA, _LOGO_FORCADA, _AV_LAUDO, FONTE, TAMANHO = antes
SEM_LOGO = "logo horizontal do avaliador ausente (assets/identidade/logo-horizontal.png)"

# A4 e margens (REGRAS: sup. 2,0 / inf. 2,0 / esq. 2,5 / dir. 2,0 cm)
A4 = (Cm(21.0), Cm(29.7))
MARGENS = dict(top_margin=Cm(2.0), bottom_margin=Cm(2.0), left_margin=Cm(2.5),
               right_margin=Cm(2.0), header_distance=Cm(0.8), footer_distance=Cm(0.8))
LARGURA_TEXTO_CM = 21.0 - 2.5 - 2.0          # 16,5 cm
TWIP_CM = 567

PADRAO_AVALIADOR = {"nome": "Alan Soares da Silva", "creci": "36507/GO", "cnai": "053569",
                    "site": "avaliadordeimovel.com", "telefone": "(62) 9 9306-8692"}


# ------------------------------------------------------------------ utilitários OOXML
def _el(tag: str, **attrs):
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn(k), str(v))
    return e


def _trocar(pai, tag: str, novo):
    """Troca (ou acrescenta) o filho `tag` de `pai` por `novo`."""
    for velho in pai.findall(qn(tag)):
        pai.remove(velho)
    pai.append(novo)
    return novo


def _rpr(run):
    rpr = run.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        run.insert(0, rpr)
    return rpr


def estilo_run(run, cor: str | None = None, pt: float | None = None, negrito: bool | None = None,
               italico: bool | None = None, espaco: int | None = None) -> None:
    rpr = _rpr(run)
    if negrito is not None:
        for b in rpr.findall(qn("w:b")):
            rpr.remove(b)
        b = OxmlElement("w:b")
        if not negrito:
            b.set(qn("w:val"), "0")
        rpr.insert(0, b)
    if italico is not None:
        for i in rpr.findall(qn("w:i")):
            rpr.remove(i)
        i = OxmlElement("w:i")
        if not italico:
            i.set(qn("w:val"), "0")
        rpr.append(i)
    if cor:
        _trocar(rpr, "w:color", _el("w:color", **{"w:val": cor}))
    if espaco is not None:
        _trocar(rpr, "w:spacing", _el("w:spacing", **{"w:val": espaco}))
    if pt:
        hp = str(int(round(pt * 2)))
        _trocar(rpr, "w:sz", _el("w:sz", **{"w:val": hp}))
        _trocar(rpr, "w:szCs", _el("w:szCs", **{"w:val": hp}))


def estilo_par(p, **kw) -> None:
    for r in p.iter(qn("w:r")):
        if r.find(qn("w:t")) is not None or r.find(qn("w:tab")) is not None:
            estilo_run(r, **kw)


def _ppr(p):
    ppr = p.find(qn("w:pPr"))
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        p.insert(0, ppr)
    return ppr


# ordem dos filhos de w:pPr (schema) para inserir sem quebrar o Word
_ORDEM_PPR = ("w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr",
              "w:widowControl", "w:numPr", "w:suppressLineNumbers", "w:pBdr", "w:shd",
              "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct",
              "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi",
              "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing",
              "w:mirrorIndents", "w:suppressOverlap", "w:jc", "w:textDirection",
              "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId",
              "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")


def _ppr_set(p, novo) -> None:
    ppr = _ppr(p)
    tag = novo.tag
    for velho in ppr.findall(tag):
        ppr.remove(velho)
    nome = "w:" + tag.split("}")[1]
    depois = _ORDEM_PPR[_ORDEM_PPR.index(nome) + 1:] if nome in _ORDEM_PPR else ()
    for filho in ppr:
        fn = "w:" + filho.tag.split("}")[1]
        if fn in depois:
            filho.addprevious(novo)
            return
    ppr.append(novo)


def borda(p, lado: str, cor: str, sz: int, espaco: int = 4) -> None:
    """Borda de parágrafo (sz em oitavos de ponto)."""
    ppr = _ppr(p)
    bdr = ppr.find(qn("w:pBdr"))
    if bdr is None:
        bdr = OxmlElement("w:pBdr")
        _ppr_set(p, bdr)
    for v in bdr.findall(qn(f"w:{lado}")):
        bdr.remove(v)
    ordem = ("top", "left", "bottom", "right", "between", "bar")
    novo = _el(f"w:{lado}", **{"w:val": "single", "w:sz": sz, "w:space": espaco, "w:color": cor})
    for filho in bdr:
        if ordem.index(filho.tag.split("}")[1]) > ordem.index(lado):
            filho.addprevious(novo)
            break
    else:
        bdr.append(novo)


def alinhar(p, jc: str) -> None:
    _ppr_set(p, _el("w:jc", **{"w:val": jc}))


def espacar(p, antes: int | None = None, depois: int | None = None) -> None:
    sp = _el("w:spacing")
    if antes is not None:
        sp.set(qn("w:before"), str(antes))
    if depois is not None:
        sp.set(qn("w:after"), str(depois))
    _ppr_set(p, sp)


def sombrear_celula(tc, cor: str) -> None:
    tcpr = tc.find(qn("w:tcPr"))
    if tcpr is None:
        tcpr = OxmlElement("w:tcPr")
        tc.insert(0, tcpr)
    for s in tcpr.findall(qn("w:shd")):
        tcpr.remove(s)
    shd = _el("w:shd", **{"w:val": "clear", "w:color": "auto", "w:fill": cor})
    # w:shd vem depois de tcW/gridSpan/vMerge/tcBorders
    ref = None
    for tag in ("w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign", "w:hideMark"):
        ref = tcpr.find(qn(tag))
        if ref is not None:
            break
    if ref is not None:
        ref.addprevious(shd)
    else:
        tcpr.append(shd)


def bordas_tabela(tb, cor: str = LINHA, sz: int = 4) -> None:
    tblpr = tb.find(qn("w:tblPr"))
    if tblpr is None:
        return
    for b in tblpr.findall(qn("w:tblBorders")):
        tblpr.remove(b)
    bdr = OxmlElement("w:tblBorders")
    for lado in ("top", "left", "bottom", "right", "insideH", "insideV"):
        bdr.append(_el(f"w:{lado}", **{"w:val": "single", "w:sz": sz, "w:space": 0, "w:color": cor}))
    # posição: depois de tblW/jc/tblCellSpacing/tblInd
    ref = None
    for tag in ("w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook", "w:tblCaption"):
        ref = tblpr.find(qn(tag))
        if ref is not None:
            break
    if ref is not None:
        ref.addprevious(bdr)
    else:
        tblpr.append(bdr)
    # bordas próprias das células sobrepõem as da tabela: tira
    for tcpr in tb.iter(qn("w:tcPr")):
        for b in tcpr.findall(qn("w:tcBorders")):
            tcpr.remove(b)


def repetir_cabecalho(tr) -> None:
    trpr = tr.find(qn("w:trPr"))
    if trpr is None:
        trpr = OxmlElement("w:trPr")
        tr.insert(0, trpr)
    if trpr.find(qn("w:tblHeader")) is None:
        trpr.append(OxmlElement("w:tblHeader"))
    if trpr.find(qn("w:cantSplit")) is None:
        trpr.insert(0, OxmlElement("w:cantSplit"))


def nao_dividir_linhas(tb) -> None:
    for tr in tb.findall(qn("w:tr")):
        trpr = tr.find(qn("w:trPr"))
        if trpr is None:
            trpr = OxmlElement("w:trPr")
            tr.insert(0, trpr)
        if trpr.find(qn("w:cantSplit")) is None:
            trpr.insert(0, OxmlElement("w:cantSplit"))


# ------------------------------------------------------------------ logo
def logo_recortada(saida: Path) -> Path | None:
    """Logo sem as margens transparentes (o PNG oficial tem ~30% de respiro em cima/baixo)."""
    origem = caminho_logo()
    if origem is None:
        return None
    destino = saida / "logo-recortada.png"
    if destino.is_file() and destino.stat().st_mtime >= origem.stat().st_mtime:
        return destino
    with Image.open(origem) as im:
        im = im.convert("RGBA")
        caixa = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
        if caixa:
            im = im.crop(caixa)
        saida.mkdir(parents=True, exist_ok=True)
        im.save(destino)
    return destino


def _run_imagem(part, img: Path, largura_cm: float):
    """Run com imagem inline de largura fixa (altura proporcional)."""
    from docx.shared import Cm as _Cm
    with Image.open(img) as im:
        w, h = im.size
    cx = int(_Cm(largura_cm))
    cy = int(cx * h / w)
    inline = part.new_pic_inline(str(img), cx, cy)   # cabeçalho/rodapé são StoryPart
    r = OxmlElement("w:r")
    d = OxmlElement("w:drawing")
    d.append(inline)
    r.append(d)
    return r


# ------------------------------------------------------------------ página e fontes
def pagina_a4(doc) -> None:
    for s in doc.sections:
        s.page_width, s.page_height = A4
        for k, v in MARGENS.items():
            setattr(s, k, v)


def fonte_padrao(doc) -> None:
    """Arial 11, corpo justificado (estilo Normal e padrões do documento)."""
    st = doc.styles["Normal"]
    st.font.name = FONTE
    st.font.size = Pt(TAMANHO)
    rpr = st.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(a), FONTE)
    st.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    # runs com fonte explícita diferente de Arial (resto do modelo antigo) passam a Arial
    body = doc.element.body
    for f in body.iter(qn("w:rFonts")):
        for a in ("w:ascii", "w:hAnsi", "w:cs"):
            if f.get(qn(a)):
                f.set(qn(a), FONTE)


# ------------------------------------------------------------------ cabeçalho e rodapé
def _limpar(hf) -> None:
    el = hf._element
    for filho in list(el):
        el.remove(filho)


def _par(hf):
    p = OxmlElement("w:p")
    hf._element.append(p)
    return p


def _tab_direita(p, pos_twips: int) -> None:
    tabs = OxmlElement("w:tabs")
    tabs.append(_el("w:tab", **{"w:val": "right", "w:pos": pos_twips}))
    _ppr_set(p, tabs)


def _texto_run(s: str, cor=CINZA, pt=8.0, negrito=False):
    r = X.novo_run(s)
    estilo_run(r, cor=cor, pt=pt, negrito=negrito)
    _trocar(_rpr(r), "w:rFonts", _el("w:rFonts", **{"w:ascii": FONTE, "w:hAnsi": FONTE,
                                                     "w:cs": FONTE}))
    return r


def _link_run(part, url: str, s: str, cor=CINZA, pt=8.0):
    h = OxmlElement("w:hyperlink")
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    h.set(qn("r:id"), part.relate_to(url, RT.HYPERLINK, is_external=True))
    h.append(_texto_run(s, cor=cor, pt=pt))
    return h


def _campo_pagina(cor=CINZA, pt=8.0):
    rpr = _texto_run("", cor=cor, pt=pt).find(qn("w:rPr"))
    return X.campo_runs("PAGE", "1", rpr)


def rodape(hf, av: dict) -> None:
    _limpar(hf)
    p = _par(hf)
    borda(p, "top", LINHA, 6, 4)
    _tab_direita(p, int(LARGURA_TEXTO_CM * TWIP_CM))
    part = hf.part
    p.append(_texto_run(av["nome"], negrito=True))
    # ORDEM 042: campo vazio do avaliador (sem CNAI, sem site) não sai no rodapé
    reg = "".join(f"  ·  {r} {v}" for r, v in (("CRECI", av["creci"]), ("CNAI", av["cnai"])) if v)
    p.append(_texto_run(reg))
    p.append(_texto_run("\t"))
    if av["site"]:
        p.append(_link_run(part, "https://" + av["site"].removeprefix("https://"), av["site"]))
        p.append(_texto_run("  ·  "))
    fone = re.sub(r"\D", "", av["telefone"])
    if fone:
        p.append(_link_run(part, f"https://wa.me/55{fone}", av["telefone"]))
        p.append(_texto_run("  ·  "))
    p.append(_texto_run("Pág. "))
    for r in _campo_pagina():
        p.append(r)
    # o run do \t vira w:tab
    for r in p.iter(qn("w:r")):
        t = r.find(qn("w:t"))
        if t is not None and t.text == "\t":
            r.remove(t)
            r.append(OxmlElement("w:tab"))


def cabecalho_interno(hf, texto: str, logo: Path | None) -> None:
    _limpar(hf)
    p = _par(hf)
    _tab_direita(p, int(LARGURA_TEXTO_CM * TWIP_CM))
    borda(p, "bottom", AMARELO, 24, 4)        # linha amarela grossa (3 pt)
    if logo is not None:
        p.append(_run_imagem(hf.part, logo, 4.0))
    p.append(_texto_run("\t" + texto))
    for r in p.iter(qn("w:r")):
        t = r.find(qn("w:t"))
        if t is not None and t.text and t.text.startswith("\t"):
            t.text = t.text[1:]
            t.addprevious(OxmlElement("w:tab"))


def cabecalho_capa(hf, logo: Path | None) -> None:
    _limpar(hf)
    p = _par(hf)
    alinhar(p, "center")
    if logo is not None:
        p.append(_run_imagem(hf.part, logo, 8.0))
    else:
        p.append(_texto_run(" "))


# ------------------------------------------------------------------ títulos e tabelas
def titulos(ctx) -> None:
    for h in X.titulos(ctx):
        txt = X.texto(h).strip()
        m = X._RE_TITULO.match(txt)
        nivel2 = txt.startswith("Anexo") or bool(m and "." in m.group(1))
        borda(h, "left", AMARELO, 18 if nivel2 else 36, 8)
        _ppr_set(h, _el("w:ind", **{"w:left": 170}))
        espacar(h, antes=240 if not nivel2 else 160, depois=120)
        _ppr_set(h, _el("w:keepNext"))
        alinhar(h, "left")
        estilo_par(h, cor=AZUL, pt=11.5 if nivel2 else 13, negrito=True)


_SEM_CABECALHO = ("Foto ", "VALOR DE MERCADO ADOTADO")


def tabelas(ctx) -> None:
    for tb in ctx.body.iter(qn("w:tbl")):
        trs = tb.findall(qn("w:tr"))
        if not trs:
            continue
        cab = X.texto(trs[0]).strip()
        if any(cab.startswith(s) for s in _SEM_CABECALHO) or tb.get("jdb") in ("valor", "grade"):
            continue
        bordas_tabela(tb)
        repetir_cabecalho(trs[0])
        tcs = trs[0].findall(qn("w:tc"))
        if len(tcs) > 1 and not any(X.texto(tc).strip() for tc in tcs[1:]):
            # título numa célula só ("FAIXA DE VARIAÇÃO MERCADOLÓGICA"): mescla a linha
            tcpr = tcs[0].find(qn("w:tcPr"))
            if tcpr is None:
                tcpr = OxmlElement("w:tcPr")
                tcs[0].insert(0, tcpr)
            for g in tcpr.findall(qn("w:gridSpan")):
                tcpr.remove(g)
            span = _el("w:gridSpan", **{"w:val": len(tcs)})
            w = tcpr.find(qn("w:tcW"))
            (w.addnext(span) if w is not None else tcpr.insert(0, span))
            if w is not None:
                w.set(qn("w:type"), "dxa")
                w.set(qn("w:w"), str(sum(int(c.find(qn("w:tcPr")).find(qn("w:tcW")).get(qn("w:w")) or 0)
                                         for c in tcs if c.find(qn("w:tcPr")) is not None
                                         and c.find(qn("w:tcPr")).find(qn("w:tcW")) is not None)))
            for tc in tcs[1:]:
                trs[0].remove(tc)
            for p in tcs[0].iter(qn("w:p")):
                alinhar(p, "center")
        for tc in trs[0].findall(qn("w:tc")):
            sombrear_celula(tc, AZUL)
            for p in tc.iter(qn("w:p")):
                estilo_par(p, cor=BRANCO, negrito=True)
                if _ppr(p).find(qn("w:jc")) is None or \
                        _ppr(p).find(qn("w:jc")).get(qn("w:val")) in ("both", "distribute"):
                    alinhar(p, "left")   # cabeçalho justificado esticava o texto
        for tr in trs[1:]:   # célula de tabela: nada de justificado esticado (coluna estreita)
            for p in tr.iter(qn("w:p")):
                jc = _ppr(p).find(qn("w:jc"))
                if jc is None or jc.get(qn("w:val")) in ("both", "distribute"):
                    alinhar(p, "left")
        nao_dividir_linhas(tb)


# ------------------------------------------------------------------ capa
def capa(ctx) -> None:
    ps = ctx.pars()
    corpo = []
    for p in ps:   # capa = parágrafos até o 1º título com quebra de página
        if p.find(".//" + qn("w:pageBreakBefore")) is not None:
            break
        corpo.append(p)
    for p in corpo:
        t = X.texto(p).strip()
        if t in ("OPINIÃO PROFISSIONAL DE VALOR", "AVALIAÇÃO MERCADOLÓGICA",
                 "AVALIAÇÃO MERCADOLÓGICA JUDICIAL") or t.startswith("AVALIAÇÃO MERCADOLÓGICA"):
            alinhar(p, "center")
            espacar(p, antes=240, depois=60)
            estilo_par(p, cor=AZUL, pt=24, negrito=True)
        elif t.startswith("PARECER TÉCNICO DE AVALIAÇÃO MERCADOLÓGICA"):   # ORDEM 043 / D-078
            alinhar(p, "center")
            espacar(p, antes=200, depois=60)
            estilo_par(p, cor=AZUL, pt=20, negrito=True)
        elif t.startswith("Natureza do documento"):
            alinhar(p, "center")
            estilo_par(p, cor=CINZA, italico=True, pt=10)
        elif re.match(r"^(PTAM )?N\.º\s*\d+", t):
            alinhar(p, "center")
            estilo_par(p, cor=AMARELO, pt=14, negrito=True)
        elif t.startswith("Conforme"):
            alinhar(p, "center")
            estilo_par(p, cor=CINZA, italico=True, pt=10)
            borda(p, "bottom", LINHA, 6, 8)
            espacar(p, depois=200)
        elif t.startswith("Imagem 01"):
            alinhar(p, "center")
            estilo_par(p, cor=CINZA, pt=9, italico=True)
            borda(p, "top", LINHA, 6, 6)
        elif X.tem_imagem(p):
            alinhar(p, "center")
        elif ":" in t[:40]:
            alinhar(p, "left")
            rs = X.runs_texto(p)
            if rs:
                estilo_run(rs[0], cor=AZUL, negrito=True)
    # linha fina entre os dados e a foto: no último parágrafo de dados
    dados = [p for p in corpo if ":" in X.texto(p)[:40] and not X.texto(p).startswith("Conforme")]
    if dados:
        borda(dados[-1], "bottom", LINHA, 6, 8)
    # parágrafos vazios da capa não podem empurrar a legenda para a pág. 2
    for p in corpo:
        if not X.texto(p).strip() and not X.tem_imagem(p):
            espacar(p, antes=0, depois=0)
            estilo_par(p, pt=6)
            rpr = _ppr(p).find(qn("w:rPr"))
            if rpr is None:
                rpr = OxmlElement("w:rPr")
                _ppr_set(p, rpr)
            _trocar(rpr, "w:sz", _el("w:sz", **{"w:val": "12"}))


# ------------------------------------------------------------------ bloco do valor
def caixa_valor(ctx) -> None:
    """"VALOR DE MERCADO ADOTADO" + valor + extenso -> caixa azul (valor em amarelo 30 pt)."""
    ps = list(ctx.body.iter(qn("w:p")))
    i = next((k for k, p in enumerate(ps) if X.texto(p).strip() == "VALOR DE MERCADO ADOTADO"), None)
    if i is None or i + 2 >= len(ps):
        return
    rot, val, ext = ps[i], ps[i + 1], ps[i + 2]
    tb = OxmlElement("w:tbl")
    tb.set("jdb", "valor")
    tblpr = OxmlElement("w:tblPr")
    tblpr.append(_el("w:tblW", **{"w:w": int(LARGURA_TEXTO_CM * TWIP_CM), "w:type": "dxa"}))
    tblpr.append(_el("w:jc", **{"w:val": "center"}))
    bdr = OxmlElement("w:tblBorders")
    for lado in ("top", "left", "bottom", "right"):
        bdr.append(_el(f"w:{lado}", **{"w:val": "single", "w:sz": 4, "w:space": 0, "w:color": AZUL}))
    tblpr.append(bdr)
    mar = OxmlElement("w:tblCellMar")
    for lado, v in (("top", 160), ("bottom", 160), ("left", 200), ("right", 200)):
        mar.append(_el(f"w:{lado}", **{"w:w": v, "w:type": "dxa"}))
    tblpr.append(mar)
    tb.append(tblpr)
    grid = OxmlElement("w:tblGrid")
    grid.append(_el("w:gridCol", **{"w:w": int(LARGURA_TEXTO_CM * TWIP_CM)}))
    tb.append(grid)
    tr = OxmlElement("w:tr")
    trpr = OxmlElement("w:trPr")
    trpr.append(OxmlElement("w:cantSplit"))
    tr.append(trpr)
    tc = OxmlElement("w:tc")
    tcpr = OxmlElement("w:tcPr")
    tcpr.append(_el("w:tcW", **{"w:w": int(LARGURA_TEXTO_CM * TWIP_CM), "w:type": "dxa"}))
    tc.append(tcpr)
    sombrear_celula(tc, AZUL)
    tr.append(tc)
    tb.append(tr)
    rot.addprevious(tb)
    for p, kw in ((rot, dict(cor=BRANCO, pt=10, negrito=True, espaco=40)),
                  (val, dict(cor=AMARELO, pt=30, negrito=True)),
                  (ext, dict(cor=BRANCO, pt=10, italico=True))):
        tc.append(p)
        alinhar(p, "center")
        espacar(p, antes=40, depois=40)
        estilo_par(p, **kw)
        # sem keepNext dentro da célula (a linha já é indivisível)
        for k in _ppr(p).findall(qn("w:keepNext")):
            _ppr(p).remove(k)
    # memória de cálculo + conclusão presas à caixa (P6 E: o bloco do valor não quebra):
    # "Valor de Mercado = área × unitário", "= R$ exato", "Arredondando-se…" e linhas vazias
    ant = tb.getprevious()
    for _ in range(8):
        if ant is None or ant.tag != qn("w:p"):
            break
        t = X.texto(ant).strip()
        if t and not re.match(r"(Valor de Mercado =|Arredondando|Assim,|Dessa forma|Portanto)", t):
            break
        _ppr_set(ant, _el("w:keepNext"))
        ant = ant.getprevious()


def negritar(ctx, padrao: str) -> None:
    """Põe em negrito o trecho que casa `padrao` (regex) nos parágrafos do corpo."""
    rx = re.compile(padrao)
    for p in list(ctx.body.iter(qn("w:p"))):
        txt = X.texto(p)
        m = rx.search(txt)
        rs = X.runs_texto(p)
        if not m or not rs:
            continue
        # só texto corrido: parágrafo com link, imagem ou campo fica como está
        if any(p.find(".//" + qn(t)) is not None
               for t in ("w:hyperlink", "w:drawing", "w:fldChar")):
            continue
        rpr = copy.deepcopy(rs[0].find(qn("w:rPr")))
        if rpr is not None:
            for b in rpr.findall(qn("w:b")):
                rpr.remove(b)
        X.limpar_runs(p)
        antes, meio, depois = txt[:m.start()], txt[m.start():m.end()], txt[m.end():]
        if antes:
            p.append(X.novo_run(antes, rpr))
        p.append(X.novo_run(meio, rpr, negrito=True))
        if depois:
            p.append(X.novo_run(depois, rpr))


# ------------------------------------------------------------------ entrada
def avaliador(cfg: dict) -> dict:
    if _AV_LAUDO != "AV-0001":          # ORDEM 042: outro avaliador — nunca os dados do Alan
        av = {k: str(cfg.get(k) or "").strip() for k in PADRAO_AVALIADOR}
        dig = re.sub(r"\D", "", av["cnai"])
        av["cnai"] = dig                 # L201-2: o número como foi cadastrado (sem zero na frente)
        av["site"] = av["site"].removeprefix("https://").removeprefix("http://").rstrip("/")
        return av
    av = dict(PADRAO_AVALIADOR)
    for k in av:
        v = str(cfg.get(k) or "").strip()
        if v:
            av[k] = v
    av["creci"] = re.sub(r".*n[ºo°]\s*", "", av["creci"]).strip() or PADRAO_AVALIADOR["creci"]
    if "/" not in av["creci"]:
        av["creci"] += "/GO"
    # L201-2 (substitui a D-080): o CNAI sai como foi cadastrado, sem completar com zero
    av["cnai"] = re.sub(r"\D", "", av["cnai"]) or PADRAO_AVALIADOR["cnai"]
    av["site"] = av["site"].removeprefix("https://").removeprefix("http://").rstrip("/")
    return av


def aplicar(ctx, cfg_avaliador: dict) -> None:
    doc, t = ctx.doc, ctx.t
    av = avaliador(cfg_avaliador)
    logo = logo_recortada(ctx.saida)
    if logo is None and _AV_LAUDO == "AV-0001":     # outro avaliador sem logo: neutro (D-095)
        ctx.aviso(SEM_LOGO)
    pagina_a4(doc)
    fonte_padrao(doc)
    am = t.modalidade != "OV"
    # ORDEM 043 / D-078: PTAM não judicial com "Não judicial" no cabeçalho; AMJ como antes
    rotulo = (f"PTAM N.º {t.numero} · Não judicial" if t.modalidade in ("AM", "AM_GARANTIA")
              else f"Avaliação Mercadológica – PTAM N.º {t.numero}" if am
              else f"Opinião Profissional de Valor N.º {t.numero}")
    texto_cab = f"{rotulo}  ·  Vistoria {t.data_vistoria.strftime('%d/%m/%Y')}"   # 117 / D-127: só a data da vistoria
    for i, s in enumerate(doc.sections):
        s.different_first_page_header_footer = i == 0
        if i == 0:
            cabecalho_capa(s.first_page_header, logo)
            rodape(s.first_page_footer, av)
        if i == 0 or not s.header.is_linked_to_previous:
            cabecalho_interno(s.header, texto_cab, logo)
            rodape(s.footer, av)
    capa(ctx)
    titulos(ctx)
    caixa_valor(ctx)
    tabelas(ctx)
    negritar(ctx, r"adota-se o valor unit[aá]rio de R\$ ?[\d.]+,\d{2}/m²")
    negritar(ctx, r"±\d+(?:,\d+)?%")
    imagens_centralizadas(ctx)


def imagens_centralizadas(ctx) -> None:
    """Imagem solta no corpo (mapa, anexos, capa): sem recuo herdado do estilo e centralizada —
    o mapa de 16,5 cm com recuo estourava a margem direita (P6 E)."""
    for p in ctx.body.iter(qn("w:p")):
        if p.getparent().tag != qn("w:body") or not list(p.iter(qn("w:drawing"))):
            continue
        ppr = _ppr(p)
        for e in ppr.findall(qn("w:ind")):
            ppr.remove(e)
        _ppr_set(p, _el("w:ind", **{"w:left": 0, "w:right": 0, "w:firstLine": 0}))
        alinhar(p, "center")
