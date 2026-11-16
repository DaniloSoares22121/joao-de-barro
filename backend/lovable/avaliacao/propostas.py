"""ORDEM 024 item 6 / D-044 a D-053: PROPOSTA e CONTRATO dentro do sistema de laudos.

Base: P10_Gerador_Proposta_Contrato.py aprovado pelo Alan em 11/11/2026 (Word + PDF, logo, marca
d'água e cores da D-040). Fluxo no sistema: Nova proposta (numeração ANO-SEQ própria, separada do
nº do laudo, validade 10 dias) -> Gerar contrato -> Abrir trabalho com os dados preenchidos.

Atualizações (D-051 e D-053):
- serviço NÃO JUDICIAL (OV, AM, AM garantia): entrega em até 3 dias úteis após a visita;
  JUDICIAL (AMJ): de 7 a 15 dias úteis após a visita;
- preços padrão: não judicial a partir de R$ 450; galpão R$ 1.000; judicial R$ 1.500;
- upgrade: em até 30 dias da entrega, o não judicial vira judicial pagando só a diferença
  (substitui a conversão OV -> PTAM de 90 dias);
- textos comerciais dizem "serviço não judicial", nunca "PTAM extrajudicial".
Dados pessoais do Alan (CPF, endereço, e-mail) e a chave Pix vêm da configuração (.env ou
Configurações -> av_settings "contratado"), NUNCA do código: o que faltar sai [ENTRE COLCHETES].
"""
from __future__ import annotations

import copy
import io
import json
import os
from decimal import Decimal
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor, Twips

IDENT = Path(__file__).parent / "assets" / "identidade"
VALIDADE_DIAS = 10
JUDICIAL = ("AMJ",)
NAO_JUDICIAL = ("OV", "AM", "AM garantia", "AM_GARANTIA")
UPGRADE_DIAS = 30
PRECOS = {"nao_judicial": Decimal("450"), "galpao": Decimal("1000"), "judicial": Decimal("1500")}
NOME_MODALIDADE = {"OV": "Opinião de Valor", "AM": "Avaliação Mercadológica (PTAM)",
                   "AM garantia": "Avaliação Mercadológica para garantia (PTAM)",
                   "AM_GARANTIA": "Avaliação Mercadológica para garantia (PTAM)",
                   "AMJ": "Avaliação Mercadológica Judicial (PTAM judicial)"}


# ORDEM 042 (D-095/D-097): avaliador dono do documento em montagem. O Alan (AV-0001) sai igual
# a antes; outro avaliador sai com os dados, a logo e o registro DELE (sem logo: sem marca).
_AV = "AV-0001"


def _eh_alan() -> bool:
    return _AV == "AV-0001"


def _registro() -> str:
    if _eh_alan():
        return 'CRECI-GO 36507 · CNAI 053569'
    from . import avaliadores
    i = avaliadores.identidade_avaliador(_AV)
    return " · ".join(x for x in (i["creci"] and f"CRECI {i['creci']}", i["cnai"] and f"CNAI {i['cnai']}") if x)


def _nome_curto() -> str:
    if _eh_alan():
        return 'Alan Soares'
    from . import avaliadores
    return avaliadores.identidade_avaliador(_AV)["nome"] or "Avaliador"


def _logos() -> tuple[bytes, bytes] | None:
    if not _eh_alan():
        from . import avaliadores
        lg = avaliadores.logo(_AV)
        if lg is None:
            return None
        b = lg.read_bytes()
        return b, b
    h = (IDENT / "logo-horizontal.png").read_bytes()
    v = IDENT / "logo-vertical.png"
    return h, (v.read_bytes() if v.is_file() else h)


def _clarear(png, alfa=0.07):
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert('RGBA'); r, g, b, a = im.split()
    im.putalpha(a.point(lambda x: int(x * alfa))); out = io.BytesIO(); im.save(out, 'PNG'); return out.getvalue()


def LOGO(): return io.BytesIO(_logos()[0]) if _logos() else None
def WM(): return io.BytesIO(_clarear(_logos()[1])) if _logos() else None


def contratado() -> dict:
    """Dados do contratado: env JDB_CONTRATADO_* ou av_settings "contratado" (Configurações).
    CPF, endereço, e-mail e Pix nunca ficam no código."""
    if not _eh_alan():       # ORDEM 042: os dados do PRÓPRIO avaliador (CPF/Pix só na configuração dele)
        from . import avaliadores, db
        i = avaliadores.identidade_avaliador(_AV)
        d = {"nome": (i["nome"] or "").upper(), "whatsapp": i["telefone"], "site": i["site"]}
        try:
            d.update({k: v for k, v in json.loads(db.setting(f"contratado:{_AV}") or "{}").items() if v})
        except ValueError:
            pass
        return d
    d = {"nome": "ALAN SOARES DA SILVA", "whatsapp": "(62) 9 9306-8692", "site": "avaliadordeimovel.com"}
    try:
        from . import db
        d.update({k: v for k, v in json.loads(db.setting("contratado") or "{}").items() if v})
    except Exception:
        pass
    for k in ("nome", "cpf", "endereco", "email", "whatsapp", "site", "pix"):
        v = os.environ.get(f"JDB_CONTRATADO_{k.upper()}")
        if v:
            d[k] = v
    return d


def judicial(modalidade: str) -> bool:
    return (modalidade or "").strip() in JUDICIAL


def preco_padrao(modalidade: str, tipo_imovel: str = "") -> Decimal:
    """D-051: não judicial a partir de R$ 450; galpão R$ 1.000; judicial R$ 1.500."""
    if judicial(modalidade):
        return PRECOS["judicial"]
    if "galp" in (tipo_imovel or "").casefold() or "barrac" in (tipo_imovel or "").casefold():
        return PRECOS["galpao"]
    return PRECOS["nao_judicial"]


def prazo_entrega(modalidade: str) -> str:
    """D-051: não judicial em até 3 dias úteis após a visita; judicial de 7 a 15."""
    return ("de 7 a 15 dias úteis após a visita técnica" if judicial(modalidade)
            else "em até 3 dias úteis após a visita técnica")


def _servico(d) -> str:
    """D-053: "serviço não judicial" nos textos comerciais; nunca "PTAM extrajudicial"."""
    m = d.get("modalidade") or "OV"
    nome = NOME_MODALIDADE.get(m, m)
    return f"{nome} – serviço {'judicial' if judicial(m) else 'não judicial'}"


J = WD_ALIGN_PARAGRAPH
NAVY, YEL, GRAY, LINE = '18283B', 'F5B800', '5B6470', 'DDE2E8'      # D-040
TXT_W = 17.4                                                          # cm (A4 com margens de 1,8 cm)
# ------------------------------------------------------------------ utilidades
def falta(v, rot):
    """ORDEM 071-A: documento nunca sai com colchete de campo vazio. Sem o dado, a parte sai da frase
    (o portão pergunta antes). `rot` fica só para quem lê o código."""
    return v if (v not in (None, '')) else ''


def _pagamento_curto(d) -> str:
    """ORDEM 071: a forma de pagamento confirmada no portão ("À vista, Pix" ou 50% + 50%)."""
    if 'vista' in (d.get('pagamento_texto') or '').lower():
        return 'À vista, por Pix'
    return '50% na contratação · 50% na entrega do documento'


def partes(*itens) -> str:
    """Junta só as partes com dado: partes(('CPF', x), ('e-mail', y)) → 'CPF x, e-mail y'."""
    return ', '.join(f"{r} {v}".strip() for r, v in itens if v not in (None, ''))


def mat_cart(im) -> str:
    m, c = im.get('matricula'), im.get('cartorio')
    return (f"matrícula nº {m}" + (f" – {c}" if c else '')) if m else ''

def brl(v):
    s = f'{float(v):,.2f}'
    return s.replace(',', 'X').replace('.', ',').replace('X', '.')

def extenso(v):
    from .calculo import por_extenso
    return por_extenso(Decimal(str(v))).lower()

def bdr(pPr, side, sz, color, space=1):
    bd = pPr.find(qn('w:pBdr'))
    if bd is None:
        bd = OxmlElement('w:pBdr'); pPr.append(bd)
    e = OxmlElement('w:' + side)
    for a, v in [('val', 'single'), ('sz', str(sz)), ('space', str(space)), ('color', color)]:
        e.set(qn('w:' + a), v)
    bd.append(e)

def shade(cell, color):
    tcPr = cell._tc.get_or_add_tcPr(); sh = OxmlElement('w:shd')
    sh.set(qn('w:val'), 'clear'); sh.set(qn('w:color'), 'auto'); sh.set(qn('w:fill'), color); tcPr.append(sh)

def cell_margins(cell, top=0, bottom=0, left=0, right=0):
    tcPr = cell._tc.get_or_add_tcPr(); m = OxmlElement('w:tcMar')
    for side, v in (('top', top), ('left', left), ('bottom', bottom), ('right', right)):
        e = OxmlElement('w:' + side); e.set(qn('w:w'), str(int(v))); e.set(qn('w:type'), 'dxa'); m.append(e)
    tcPr.append(m)

def tbl_borders(t, inner_h=True, bottom=True, color=LINE):
    pr = t._tbl.tblPr; b = OxmlElement('w:tblBorders')
    for side in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        e = OxmlElement('w:' + side)
        if (side == 'insideH' and inner_h) or (side == 'bottom' and bottom):
            for a, v in [('val', 'single'), ('sz', '4'), ('space', '0'), ('color', color)]: e.set(qn('w:' + a), v)
        else:
            e.set(qn('w:val'), 'nil')
        b.append(e)
    pr.append(b)

def fix_widths(t, widths_cm):
    t.autofit = False
    for k, gc in enumerate(t._tbl.tblGrid.findall(qn('w:gridCol'))):
        gc.set(qn('w:w'), str(int(Cm(widths_cm[k]).twips)))
    for row in t.rows:
        row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        for k, c in enumerate(row.cells): c.width = Cm(widths_cm[k])
    ordem = ['tblStyle', 'tblpPr', 'tblOverlap', 'bidiVisual', 'tblStyleRowBandSize', 'tblStyleColBandSize', 'tblW', 'jc',
             'tblCellSpacing', 'tblInd', 'tblBorders', 'shd', 'tblLayout', 'tblCellMar', 'tblLook']
    pr = t._tbl.tblPr; ch = list(pr)
    ch.sort(key=lambda e: ordem.index(e.tag.split('}')[1]) if e.tag.split('}')[1] in ordem else 99)
    for e in ch: pr.remove(e)
    for e in ch: pr.append(e)

def run(p, t, size=None, bold=False, color=None, italic=False):
    r = p.add_run(t); r.bold = bold; r.italic = italic
    if size: r.font.size = Pt(size)
    if color: r.font.color.rgb = RGBColor.from_string(color)
    return r

def para(container, t='', size=10.5, bold=False, color=NAVY, align=J.LEFT, before=0, after=4, italic=False, line=1.1):
    p = container.add_paragraph(); p.alignment = align
    pf = p.paragraph_format; pf.space_before = Pt(before); pf.space_after = Pt(after); pf.line_spacing = line
    if t: run(p, t, size, bold, color, italic)
    return p

def field(p, instr, size=8.5, color=GRAY, bold=False):
    for tag in ('begin', 'instr', 'separate', 'res', 'end'):
        r = run(p, '1' if tag == 'res' else '', size, bold, color)
        if tag == 'res': continue
        if tag == 'instr':
            e = OxmlElement('w:instrText'); e.set(qn('xml:space'), 'preserve'); e.text = f' {instr} '
        else:
            e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), tag)
        r._r.append(e)

def float_behind(r, uid):
    """Transforma a imagem em linha em imagem flutuante, atrás do texto e centralizada na página (marca d'água)."""
    inline = r._r.xpath('.//wp:inline')[0]
    ext = inline.find(qn('wp:extent')); graphic = inline.find(qn('a:graphic'))
    anchor = parse_xml(
        f'<wp:anchor {nsdecls("wp", "a", "pic", "r")} distT="0" distB="0" distL="0" distR="0" simplePos="0" '
        f'relativeHeight="0" behindDoc="1" locked="1" layoutInCell="1" allowOverlap="1">'
        f'<wp:simplePos x="0" y="0"/>'
        f'<wp:positionH relativeFrom="page"><wp:align>center</wp:align></wp:positionH>'
        f'<wp:positionV relativeFrom="page"><wp:align>center</wp:align></wp:positionV>'
        f'<wp:extent cx="{ext.get("cx")}" cy="{ext.get("cy")}"/>'
        f'<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
        f'<wp:docPr id="{uid}" name="MarcaDagua{uid}"/><wp:cNvGraphicFramePr/></wp:anchor>')
    anchor.append(copy.deepcopy(graphic))
    inline.getparent().replace(inline, anchor)

# ------------------------------------------------------------------ esqueleto comum
def base_doc(meta_linhas, rodape_pagina=False):
    D = Document()
    st = D.styles['Normal']; st.font.name = 'Arial'; st.font.size = Pt(10.5)
    st.font.color.rgb = RGBColor.from_string(NAVY); st.element.rPr.rFonts.set(qn('w:eastAsia'), 'Arial')
    st.paragraph_format.space_after = Pt(0); st.paragraph_format.space_before = Pt(0)
    lb = D.styles['List Bullet']; lb.font.name = 'Arial'; lb.font.size = Pt(10); lb.font.color.rgb = RGBColor.from_string(NAVY)
    s = D.sections[0]; s.page_width = Cm(21); s.page_height = Cm(29.7)
    s.left_margin = s.right_margin = Cm(1.8); s.top_margin = Cm(4.1); s.bottom_margin = Cm(2.2)
    s.header_distance = Cm(1.2); s.footer_distance = Cm(1.0)
    # cabeçalho: logo + dados à direita + linha amarela
    h = s.header; hp0 = h.paragraphs[0]
    t = h.add_table(rows=1, cols=2, width=Cm(TXT_W)); tbl_borders(t, inner_h=False, bottom=False)
    c0, c1 = t.cell(0, 0), t.cell(0, 1)
    p = c0.paragraphs[0]
    if LOGO() is not None:
        p.add_run().add_picture(LOGO(), height=Cm(1.75))
    c1.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    for k, l in enumerate(meta_linhas):
        pp = c1.paragraphs[0] if k == 0 else c1.add_paragraph()
        pp.alignment = J.RIGHT; pp.paragraph_format.space_after = Pt(0)
        run(pp, l, 9 if k else 9.5, k == 0, GRAY if k else NAVY)
    fix_widths(t, [9.4, 8.0])
    hp0._p.getparent().remove(hp0._p)                    # tira o parágrafo vazio de cima
    hl = h.add_paragraph(); hl.paragraph_format.space_before = Pt(2); hl.paragraph_format.space_after = Pt(0)
    bdr(hl._p.get_or_add_pPr(), 'bottom', 24, YEL, 1)
    wm = h.add_paragraph(); wm.paragraph_format.space_after = Pt(0)
    if WM() is not None:
        r = wm.add_run(); r.add_picture(WM(), width=Cm(12)); float_behind(r, 900)
    # rodapé
    fp = s.footer.paragraphs[0]; bdr(fp._p.get_or_add_pPr(), 'top', 4, LINE, 6)
    for pos in (4680, 9360):                              # limpa as tabulações do estilo Footer (modelo Letter)
        fp.paragraph_format.tab_stops.add_tab_stop(Twips(pos), WD_TAB_ALIGNMENT.CLEAR)
    fp.paragraph_format.tab_stops.add_tab_stop(Cm(TXT_W - 0.1), WD_TAB_ALIGNMENT.RIGHT)
    C = contratado()
    run(fp, f'{_nome_curto()} · {_registro()}', 8, False, GRAY)
    run(fp, '\t' + f"{C['site']} · {C['whatsapp']}", 8, False, GRAY)
    if rodape_pagina:
        run(fp, ' · Pág. ', 8, False, GRAY); field(fp, 'PAGE', 8); run(fp, ' de ', 8, False, GRAY); field(fp, 'NUMPAGES', 8)
    return D

def titulo(D, t, sub):
    p = para(D, '', after=1); r = run(p, t, 20, True, NAVY)
    sp = OxmlElement('w:spacing'); sp.set(qn('w:val'), '20'); r._r.get_or_add_rPr().append(sp)
    if sub: para(D, sub, 10.5, color=GRAY, after=8)

def H2(D, t, before=10):
    p = para(D, '', before=before, after=3); p.paragraph_format.keep_with_next = True
    p.paragraph_format.left_indent = Cm(0.1)
    run(p, t, 12, True, NAVY); bdr(p._p.get_or_add_pPr(), 'left', 32, YEL, 6)
    return p

def bullets(D, itens, size=10):
    for it in itens:
        p = D.add_paragraph(style='List Bullet'); p.paragraph_format.space_after = Pt(2)
        if isinstance(it, (list, tuple)):          # [(texto, negrito), ...]
            for tx, b in it: run(p, tx, size, b, NAVY)
        else:
            run(p, it, size, False, NAVY)

def tabela_rotulos(D, linhas, w0=4.2, size=10):
    t = D.add_table(rows=len(linhas), cols=2); tbl_borders(t)
    for i, (rot, val) in enumerate(linhas):
        c0, c1 = t.cell(i, 0), t.cell(i, 1)
        for c in (c0, c1): cell_margins(c, 70, 70, 60, 60)
        run(c0.paragraphs[0], rot, size, True, NAVY)
        vals = val if isinstance(val, list) else [val]
        for k, v in enumerate(vals):
            pp = c1.paragraphs[0] if k == 0 else c1.add_paragraph()
            pp.paragraph_format.space_after = Pt(0); pp.paragraph_format.line_spacing = 1.1
            if isinstance(v, (list, tuple)):
                for tx, b in v: run(pp, tx, size, b, NAVY)
            else:
                run(pp, v, size, False, NAVY)
    fix_widths(t, [w0, TXT_W - w0])
    return t

def competencia(tipo):
    if tipo.upper().startswith('PTAM'):
        return ('Parecer Técnico de Avaliação Mercadológica elaborado por corretor de imóveis avaliador (CRECI/CNAI), '
                'conforme a Lei nº 6.530/1978 e a Resolução COFECI nº 1.066/2007.')
    return 'Opinião de valor elaborada por corretor de imóveis avaliador (CRECI/CNAI), conforme a Lei nº 6.530/1978, art. 3º.'

def to_pdf(docx, outdir):
    subprocess.run(['soffice', '--headless', '--convert-to', 'pdf', '--outdir', outdir, docx],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return os.path.splitext(docx)[0] + '.pdf'

def imoveis(d):
    return d['imoveis'] if 'imoveis' in d else [d['imovel']]

# ------------------------------------------------------------------ PROPOSTA
def proposta(d):
    num = f"{d['ano']}-{int(d['numero']):03d}"
    D = base_doc([f'PROPOSTA Nº {num}', f"{d.get('cidade_emissao', 'Goiânia')}, {d['data']}",
                  f"Válida por {d.get('validade_dias', VALIDADE_DIAS)} dias"])
    m = d.get('modalidade') or 'OV'
    titulo(D, 'PROPOSTA DE AVALIAÇÃO', f"{_servico(d)} – imóvel {d.get('categoria', 'residencial')}")
    sol = d['solicitante']; linhas = [('Solicitante', sol['nome'] + (f" – {sol['doc']}" if sol.get('doc') else ''))]
    if d.get('proprietario'): linhas.append(('Proprietário', d['proprietario']))
    for k, im in enumerate(imoveis(d)):
        v = [im['descricao'], im['endereco']]
        if im.get('matricula'): v.append(mat_cart(im)[0].upper() + mat_cart(im)[1:])
        linhas.append(('Imóvel' if len(imoveis(d)) == 1 else f'Imóvel {k + 1}', v))
        if im.get('areas'): linhas.append(('Áreas (m²)', [f'{a}: {b} m²' for a, b in im['areas']]))
    linhas.append(('Finalidade', d['finalidade']))
    tabela_rotulos(D, linhas)
    bx = D.add_table(rows=1, cols=1); c = bx.cell(0, 0); shade(c, NAVY); cell_margins(c, 200, 200, 280, 280)
    p = c.paragraphs[0]; p.paragraph_format.space_after = Pt(2)
    run(p, 'Investimento: ', 11, False, 'FFFFFF'); run(p, 'R$ ' + brl(d['valor']), 16, True, YEL)
    run(para(c, after=0), _pagamento_curto(d), 10, False, 'FFFFFF')
    if d.get('valor_unit'):
        run(para(c, after=0), f"R$ {brl(d['valor_unit'])} por imóvel", 9.5, False, 'DDE2E8')
    if d.get('desconto'):
        ds = d['desconto']
        run(para(c, after=0), f"Valor já com {ds['percentual']}% de desconto pela indicação de {ds['indicador']}.", 9.5, False, 'DDE2E8')
    fix_widths(bx, [TXT_W]); para(D, '', after=0, size=4)
    H2(D, 'O que está incluído', 6)
    inc = ['Visita técnica ao imóvel com registro fotográfico', 'Análise da documentação (matrícula, IPTU)',
           'Pesquisa de mercado e comparação com imóveis semelhantes da região', 'Documento com o método explicado',
           'Uma ligação após a entrega para esclarecer dúvidas', 'Deslocamento incluído em até 30 km de Goiânia']
    bullets(D, d.get('incluido', inc) + d.get('incluido_extra', []))
    H2(D, 'Prazo', 6)
    bullets(D, ['Visita técnica: de 1 a 5 dias úteis após a contratação.',
                f"Entrega do documento: {d.get('prazo_texto') or prazo_entrega(m)}."])
    if not judicial(m):
        H2(D, 'Se o caso for para a Justiça', 6)
        vj = Decimal(str(d.get('valor_judicial', PRECOS['judicial']))); dif = vj - Decimal(str(d['valor']))
        bullets(D, [[('Em até ', False), (f'{UPGRADE_DIAS} dias', True),
                     (' da entrega, o serviço não judicial pode virar ', False), (f'judicial (R$ {brl(vj)})', True),
                     (f': paga-se só a diferença, R$ {brl(dif)}.' if dif > 0 else ': paga-se só a diferença.', False)]])
    para(D, competencia(m), 9, color=GRAY, italic=True, before=8, after=0)
    p = para(D, _nome_curto(), 10, True, before=26, after=0); p.paragraph_format.right_indent = Cm(TXT_W - 7)
    bdr(p._p.get_or_add_pPr(), 'top', 6, NAVY, 3)
    para(D, 'Corretor e Avaliador de Imóveis', 9.5, after=0)
    para(D, _registro(), 9.5, after=0)
    return D, f"Proposta {num} - {d['arquivo']}"


def competencia(modalidade):
    if (modalidade or 'OV') != 'OV':
        return ('Parecer Técnico de Avaliação Mercadológica elaborado por corretor de imóveis avaliador (CRECI/CNAI), '
                'conforme a Lei nº 6.530/1978 e a Resolução COFECI nº 1.066/2007.')
    return 'Opinião de valor elaborada por corretor de imóveis avaliador (CRECI/CNAI), conforme a Lei nº 6.530/1978, art. 3º.'


def imoveis(d):
    return d['imoveis'] if 'imoveis' in d else [d['imovel']]

# ------------------------------------------------------------------ CONTRATO
def contrato(d):
    num = f"{d['ano']}-{int(d['numero']):03d}"
    m = d.get('modalidade') or 'OV'
    ov = m == 'OV'
    D = base_doc(['CONTRATO DE PRESTAÇÃO DE SERVIÇOS', f'Referente à proposta nº {num}',
                  f"{d.get('cidade_emissao', 'Goiânia')}, {d.get('data_contrato', d['data'])}"], rodape_pagina=True)
    titulo(D, 'CONTRATO DE PRESTAÇÃO DE SERVIÇOS', 'Avaliação imobiliária – ' + _servico(d))
    C, K = contratado(), d['contratante']
    reg = ("corretor de imóveis (CRECI-GO 36507) e avaliador imobiliário (CNAI 053569)" if _eh_alan()
           else f"corretor de imóveis e avaliador imobiliário ({_registro()})")
    ct = partes(('', f"{C['nome']}, {reg}"), ('CPF', C.get('cpf')), ('com endereço na', C.get('endereco')),
                ('e-mail', C.get('email')), ('WhatsApp', C.get('whatsapp'))) + '.'
    kt = partes(('', K.get('nome')), (K.get('doc_tipo', 'CPF/CNPJ'), K.get('doc')), ('com endereço na', K.get('endereco')))
    if K.get('pj', True) or K.get('representante'):
        kt += (f", representado(a) por {K['representante']}" if K.get('representante') else '')
    resto = partes(('e-mail', K.get('email')), ('telefone', K.get('telefone')))
    kt += (f", {resto}" if resto else '') + '.'
    tabela_rotulos(D, [('CONTRATADO', ct), ('CONTRATANTE', kt)], w0=3.6, size=10)
    para(D, 'As partes acima firmam este contrato, que se rege pelas cláusulas seguintes.', after=2, before=6, align=J.JUSTIFY)
    n = [0]
    def CL(titulo_cl, itens):
        n[0] += 1; H2(D, f'Cláusula {n[0]} — {titulo_cl}', 9)
        for k, it in enumerate(itens, 1):
            p = para(D, '', align=J.JUSTIFY, after=3); run(p, f'{n[0]}.{k}. ', 10.5, True); run(p, it, 10.5)
    ims = imoveis(d)
    desc = '; '.join(partes(('', im['descricao']), ('', im['endereco']), ('', mat_cart(im))) for im in ims)
    obj = [f"Elaboração de {NOME_MODALIDADE.get(m, m)} ({'serviço judicial' if judicial(m) else 'serviço não judicial'}) do{'s' if len(ims) > 1 else ''} imóve{'is' if len(ims) > 1 else 'l'}: {desc}.",
           f"Finalidade declarada pelo CONTRATANTE: {d['finalidade']}. O documento só deve ser usado para essa finalidade."]
    if d.get('proprietario'):
        obj.append(f"O imóvel pertence a {d['proprietario']}. O CONTRATANTE declara estar autorizado a solicitar esta avaliação.")
    obj.append(competencia(m).replace('Opinião de valor elaborada', 'O serviço consiste em opinião de valor elaborada')
               .replace('Parecer Técnico de Avaliação Mercadológica elaborado', 'O serviço consiste em Parecer Técnico de Avaliação Mercadológica elaborado')
               + ' Não estão incluídos vistoria estrutural, perícia judicial por nomeação nem verificação da regularidade jurídica do imóvel.')
    CL('Objeto', obj)
    v = float(d['valor']); sinal = round(v / 2, 2); saldo = round(v - sinal, 2)
    forma = d.get('pagamento', 'pix')
    if forma == 'link':
        fp = 'por link de pagamento com cartão de crédito; juros e encargos da operadora ficam a cargo do CONTRATANTE'
    else:
        chave = d.get('pix') or C.get('pix')
        fp = f"por Pix (chave {chave}) ou transferência" if chave else 'por Pix ou transferência'
    CL('Preço e pagamento', [
        f"Valor total: R$ {brl(v)} ({extenso(v)}).",
        (f"Pagamento à vista, na assinatura deste contrato, {fp}." if 'vista' in (d.get('pagamento_texto') or '').lower() else
         f"50% (R$ {brl(sinal)}) na assinatura deste contrato, a título de sinal, e 50% (R$ {brl(saldo)}) na entrega do documento, {fp}."),
        'O documento final é entregue após a quitação do saldo.',
        'O atraso no pagamento implica mora automática do CONTRATANTE, com multa de 10% (dez por cento) sobre o valor total do serviço e juros de 1% (um por cento) ao mês, proporcionais ao período de atraso.'])
    CL('Prazos e visita técnica', [
        'Visita técnica: de 1 a 5 dias úteis após a assinatura e o pagamento do sinal, em data combinada entre as partes.',
        f'Entrega: {prazo_entrega(m)}, contados também do recebimento de todos os documentos da Cláusula 4.',
        'Atrasos causados pelo CONTRATANTE (documentos, acesso ao imóvel, remarcação) suspendem o prazo pelo mesmo período.',
        'O CONTRATADO aguarda até 15 (quinze) minutos após o horário marcado para a visita. Se o imóvel estiver indisponível por responsabilidade do CONTRATANTE, ou ninguém comparecer nesse prazo, a visita será considerada frustrada e o CONTRATANTE reembolsará R$ 100,00 (cem reais) de deslocamento.'])
    CL('Obrigações do CONTRATANTE', [
        'Enviar matrícula atualizada, IPTU, documento do solicitante (RG/CNH, ou cartão CNPJ e contrato social) e os demais documentos solicitados.',
        'Garantir acesso ao imóvel na data combinada e indicar pessoa para acompanhar a visita.',
        'Responder pela veracidade das informações prestadas.'])
    CL('Obrigações do CONTRATADO', [
        'Executar o serviço com técnica e ética profissional, conforme as normas do Sistema COFECI/CRECI.',
        'Entregar o documento em PDF assinado e fazer uma ligação de esclarecimento após a entrega.',
        'Manter sigilo sobre os dados do CONTRATANTE e do imóvel, conforme a cláusula de confidencialidade.'])
    CL('Validade e limites do documento', [
        'O valor reflete o mercado na data-base do documento e pode variar com o tempo e com as condições de mercado.',
        'O CONTRATADO não garante que o imóvel será vendido ou alugado pelo valor indicado, nem que terceiros (bancos, órgãos públicos, juízo ou outras partes) aceitarão o valor.'])
    if not judicial(m):
        CL('Upgrade para serviço judicial', [
            f'Em até {UPGRADE_DIAS} dias da entrega, o CONTRATANTE pode transformar este serviço não judicial em serviço judicial, pagando só a diferença entre os valores vigentes.',
            'Nesse prazo, não é preciso nova visita ao imóvel.'])
    CL('Confidencialidade e dados pessoais (LGPD)', [
        'Os dados pessoais serão usados só para executar este contrato e guardados pelo prazo legal, conforme a Lei nº 13.709/2018 (LGPD).',
        'Nenhum dado do CONTRATANTE ou do imóvel será divulgado sem autorização por escrito, salvo quando exigido por autoridade pública.'])
    CL('Desistência e sinal', [
        'As partes podem desistir deste contrato. O sinal pago na assinatura tem natureza de arras penitenciais, nos termos do art. 420 do Código Civil.',
        'Se o CONTRATANTE desistir, antes ou depois da visita técnica, o sinal não será devolvido.',
        'Se o CONTRATADO desistir, devolverá o sinal mais o equivalente, conforme o mesmo artigo.'])
    CL('Assinatura eletrônica', [
        'As partes assinam este contrato eletronicamente, pelo gov.br, e reconhecem a validade dessa assinatura, nos termos do art. 10, § 2º, da Medida Provisória nº 2.200-2/2001.'])
    CL('Foro', ['Fica eleito o foro da comarca de Goiânia – GO para resolver qualquer questão sobre este contrato.'])
    para(D, f"{d.get('cidade_emissao', 'Goiânia')}, {d.get('data_contrato', d['data'])}.", before=10, after=30)
    t = D.add_table(rows=1, cols=2); tbl_borders(t, inner_h=False, bottom=False)
    for c, linhas in ((t.cell(0, 0), [(C['nome'], True), ('CONTRATADO', False), (_registro(), False)]),
                      (t.cell(0, 1), [(falta(K.get('nome'), 'NOME OU RAZÃO SOCIAL'), True), ('CONTRATANTE', False),
                                      (f"{K.get('doc_tipo', 'CPF/CNPJ')} {K['doc']}" if K.get('doc') else '', False)])):
        for k, (tx, b) in enumerate(linhas):
            pp = c.paragraphs[0] if k == 0 else c.add_paragraph()
            pp.alignment = J.CENTER; pp.paragraph_format.space_after = Pt(0)
            if k == 0: bdr(pp._p.get_or_add_pPr(), 'top', 6, NAVY, 3); pp.paragraph_format.keep_with_next = True
            run(pp, tx, 9.5, b)
        cell_margins(c, 0, 0, 300, 300)
    fix_widths(t, [TXT_W / 2, TXT_W / 2])
    return D, f"Contrato {num} - {d['arquivo']}"

PPR = ['pStyle', 'keepNext', 'keepLines', 'pageBreakBefore', 'framePr', 'widowControl', 'numPr', 'suppressLineNumbers', 'pBdr',
       'shd', 'tabs', 'suppressAutoHyphens', 'kinsoku', 'wordWrap', 'overflowPunct', 'topLinePunct', 'autoSpaceDE', 'autoSpaceDN',
       'bidi', 'adjustRightInd', 'snapToGrid', 'spacing', 'ind', 'contextualSpacing', 'mirrorIndents', 'suppressOverlap', 'jc',
       'textDirection', 'textAlignment', 'textboxTightWrap', 'outlineLvl', 'divId', 'cnfStyle', 'rPr', 'sectPr', 'pPrChange']
RPR = ['rStyle', 'rFonts', 'b', 'bCs', 'i', 'iCs', 'caps', 'smallCaps', 'strike', 'dstrike', 'outline', 'shadow', 'emboss', 'imprint',
       'noProof', 'snapToGrid', 'vanish', 'webHidden', 'color', 'spacing', 'w', 'kern', 'position', 'sz', 'szCs', 'highlight', 'u',
       'effect', 'bdr', 'shd', 'fitText', 'vertAlign', 'rtl', 'cs', 'em', 'lang', 'eastAsianLayout', 'specVanish', 'oMath']
TCPR = ['cnfStyle', 'tcW', 'gridSpan', 'hMerge', 'vMerge', 'tcBorders', 'shd', 'noWrap', 'tcMar', 'textDirection', 'tcFitText',
        'vAlign', 'hideMark']

def ordenar(D):
    z = D.settings.element.find(qn('w:zoom'))
    if z is not None and z.get(qn('w:percent')) is None: z.set(qn('w:percent'), '100')
    s = D.sections[0]
    for root in [D.element.body, s.header._element, s.footer._element]:
        for tag, order in ((qn('w:pPr'), PPR), (qn('w:rPr'), RPR), (qn('w:tcPr'), TCPR)):
            for pr in root.iter(tag):
                if tag == qn('w:rPr') and pr.getparent().tag == qn('w:pPr'): continue
                ch = list(pr); ch.sort(key=lambda e: order.index(e.tag.split('}')[1]) if e.tag.split('}')[1] in order else 99)
                for e in ch: pr.remove(e)
                for e in ch: pr.append(e)



def gerar(d: dict, outdir: Path, qual: str = "ambos") -> list[Path]:
    """Gera .docx (e .pdf, se o LibreOffice estiver instalado) da proposta e/ou do contrato."""
    global _AV
    _AV = d.get("avaliador_id") or "AV-0001"
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True); saidas: list[Path] = []
    for nome, fn in (("proposta", proposta), ("contrato", contrato)):
        if qual not in (nome, "ambos"):
            continue
        D, arq = fn(d); ordenar(D); docx = outdir / (arq.replace("/", "-") + ".docx"); D.save(docx)
        saidas.append(docx)
        try:
            from .pdf import converter
            saidas.append(converter(docx))
        except Exception:
            pass      # sem LibreOffice: fica só o Word
    return saidas
