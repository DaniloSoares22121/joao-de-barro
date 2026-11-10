"""Montagem do laudo Word a partir do modelo P1 da modalidade (OV ou AM/AMJ).

Parte sempre do .docx do P1 (estilos, capa, cabeçalho/rodapé e anexos fixos B1/B2 já vêm
nele) e preenche: capa A1 com fachada demarcada, 7.1 com mapa e hiperlink, grade de fotos,
tabela de amostras (D-014), bloco do valor + quadro mín./adotado/máx. (D-018), resumo,
anexos de documentos (solicitante tarjado), total de páginas (campo NUMPAGES) e sumário no
final como campo TOC clicável (D-019). Campos do imóvel: só origem documento/vistoria."""
from __future__ import annotations

import copy
import json
import math
import re
import statistics
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path, PurePosixPath

import pymupdf
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from PIL import Image

from . import db, imagens, nomes
from . import docx_partes as X
from .agentes import _comum
from .agentes.extracao import _chave, _citados
from .agentes.redacao import Textos
from .agentes.selecao import Selecao, area_construida
from .calculo import Resultado
from .conhecimento import PASTA as _CONHECIMENTO
from .modelos import Campo, Referencial, Trabalho

MODELOS = {"OV": "P1_OV_Modelo.docx", "AM": "P1_AM_AMJ_Modelo.docx",
           "AM_GARANTIA": "P1_AM_AMJ_Modelo.docx", "AMJ": "P1_AM_AMJ_Modelo.docx"}
PLACEHOLDER = X.PLACEHOLDER
# Nome do curso no currículo fixo do P1 (presente também no P8); não é o nome do laudo.
_CURRICULO_PTAM = "Parecer Técnico de Avaliação Mercadológica (PTAM)"
_EXT_IMG = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
_SOLICITANTE = re.compile(r"cnh|\brg\b|identidade|oab|cpf|solicitante|pessoa", re.I)

# Avisos (textos únicos; orquestrador.AVISOS_GRAVES importa os graves daqui)
SEM_LOCALIZACAO = "imagem de localização ausente"
SEM_FOTOS = "nenhuma foto de vistoria para o relatório fotográfico"
SEM_TARJA = "documento do solicitante sem tarja"
AMJ_SEM_PROCESSO = "AMJ sem dados do processo"
PERITO_SEM_QUALIFICACAO = "perito sem qualificação na configuração do avaliador"
DPI_ANEXO = 110

# Caixas (EMU) das imagens
CAPA = (5580000, 3060000)  # cabe na 1ª página (Carta) com a legenda
FOTO = (2736000, 2052000)
AMOSTRA = (1368000, 912000)
MAPA = (5580000, 3720000)
ANEXO = (5760000, 7920000)


class ConteudoProibido(ValueError):
    """Conteúdo vedado no laudo (PTAM em OV, frase de engenharia, placeholder)."""


# ------------------------------------------------------------------ dados
_n = X.norm


def _campos(job_id: str) -> list[Campo]:
    """Só campos comprovados (documento/vistoria) — nunca inferido/pendente/contexto."""
    return [c for c in db.campos(job_id)
            if c.origem in ("documento", "vistoria") and c.valor not in (None, "")]


def _casa(nome: str, chave: str) -> bool:
    """A chave casa no COMEÇO de uma palavra do nome: "idade" não casa com "Cidade" nem
    "Unidade" (o resumo saía "idade aparente Goiânia"), mas "constru" casa "construída"."""
    return re.search(r"(?<![a-z0-9])" + re.escape(chave), nome) is not None


def _campo(cs: list[Campo], *chaves: str) -> Campo | None:
    for c in cs:
        nome = _n(c.nome)
        if all(_casa(nome, k) for k in chaves):
            return c
    return None


def _val(c: Campo | None) -> str:
    if c is None:
        return ""
    v = c.valor
    if isinstance(v, float) and v.is_integer():
        v = int(v)   # Campo.valor guarda número como float: "30.0" não é texto de laudo
    return str(v).strip()


def _area(c: Campo | None) -> str:
    if c is None:
        return "n/i"
    try:
        from .agentes.selecao import _decimal_br
        return X.num(_decimal_br(c.valor))
    except Exception:
        return str(c.valor)


class _Ctx:
    def __init__(self, job_id: str, textos: Textos, r: Resultado, sel: Selecao):
        self.job = job_id
        self.t: Trabalho = _comum.trabalho(job_id)
        self.pasta = db.pasta(job_id)
        self.saida = self.pasta / "_laudo"
        self.textos, self.r, self.sel = textos, r, sel
        self.cs = _campos(job_id)
        self.ext = db.resultado(job_id, "extracao") or {}
        self.doc = Document(str(_CONHECIMENTO / MODELOS[self.t.modalidade]))
        self.body = self.doc.element.body
        self.part = self.doc.part
        self.sem_rotulo: set[str] = set()

    def aviso(self, msg: str) -> None:
        db.evento(self.job, "montagem", "aviso", msg)

    def arq(self, rel: str) -> Path | None:
        if not rel:
            return None
        p = (self.pasta / rel).resolve()
        try:
            p.relative_to(self.pasta.resolve())
        except ValueError:
            return None
        return p if p.is_file() else None

    # elementos do corpo
    def pars(self):
        return [e for e in self.body if e.tag == qn("w:p")]

    def par(self, prefixo: str):
        for p in self.body.iter(qn("w:p")):
            if X.texto(p).strip().startswith(prefixo):
                return p
        return None

    def tabela(self, cab: str):
        for tb in self.body.iter(qn("w:tbl")):
            tr = tb.find(qn("w:tr"))
            if tr is not None and X.texto(tr).startswith(cab):
                return tb
        return None


def _caixas(caixas, w: int, h: int) -> list[tuple[int, int, int, int]]:
    """Sanitiza caixas da IA: limita à imagem e descarta degeneradas."""
    out = []
    for c in caixas or []:
        try:
            x0, y0, x1, y1 = (int(round(float(v))) for v in c)
        except (TypeError, ValueError, OverflowError):
            continue
        x0, x1 = sorted((max(0, min(x0, w)), max(0, min(x1, w))))
        y0, y1 = sorted((max(0, min(y0, h)), max(0, min(y1, h))))
        if x1 - x0 >= 2 and y1 - y0 >= 2:
            out.append((x0, y0, x1, y1))
    return out


def _caixas_brutas(ctx: _Ctx, rel: str, pagina: int | None = None) -> list:
    """Caixas da extração para o arquivo (imagem: chave "<arquivo>"; página de PDF:
    "<arquivo>#p<N>", N a partir de 1). Aceita caminho relativo ou só o nome."""
    tj = ctx.ext.get("tarjas") or {}
    suf = "" if pagina is None else f"#p{pagina}"
    return tj.get(rel + suf) or tj.get(PurePosixPath(rel).name + suf) or []


def _tarjada(ctx: _Ctx, rel: str, origem: Path, caixas=None, escala: float = 1.0,
             destino: Path | None = None) -> Path:
    caixas = _caixas_brutas(ctx, rel) if caixas is None else caixas
    if not caixas:
        return origem
    with Image.open(origem) as im:
        w, h = im.size
    if escala != 1.0:
        esc = []
        for c in caixas:
            try:
                v4 = [float(v) * escala for v in c]
            except (TypeError, ValueError):
                continue
            if all(math.isfinite(v) for v in v4):
                esc.append(v4)
        caixas = esc
    boas = _caixas(caixas, w, h)
    if not boas:
        return origem
    return imagens.tarjar(origem, boas,
                          destino or ctx.saida / "tarjadas" / PurePosixPath(rel).name)


def _fotos(ctx: _Ctx) -> list[tuple[str, Path, str]]:
    out = []
    for f in sorted(ctx.ext.get("fotos") or [], key=lambda f: f.get("ordem", 0)):
        p = ctx.arq(f.get("arquivo", ""))
        if p is None or p.suffix.lower() not in _EXT_IMG:
            continue
        leg = ctx.textos.legendas.get(f["arquivo"]) or f.get("legenda") or ""
        out.append((f["arquivo"], _tarjada(ctx, f["arquivo"], p), leg))
    return out


# ------------------------------------------------------------------ capa e cabeçalho
def _cabecalhos(ctx: _Ctx) -> list:
    """Cabeçalhos/rodapés definidos (sem criar os que não existem)."""
    return [hf for s in ctx.doc.sections
            for hf in (s.header, s.footer, s.first_page_header, s.first_page_footer,
                       s.even_page_header, s.even_page_footer)
            if not hf.is_linked_to_previous]

def _imovel(ctx: _Ctx) -> str:
    end = _val(_campo(ctx.cs, "endereco"))
    end = end.rstrip(".") + "." if end else ""
    return f"{ctx.t.tipo} – {end}" if end else f"{ctx.t.tipo} – {ctx.t.bairro}, {ctx.t.cidade}"


def _capa(ctx: _Ctx) -> None:
    t = ctx.t
    for parte in _cabecalhos(ctx):
        for p in parte._element.iter(qn("w:p")):
            X.subst(p, "[PREENCHER: nº]", str(t.numero))
    for p in ctx.body.iter(qn("w:p")):
        X.subst(p, "[PREENCHER: nº]", str(t.numero))
    if t.modalidade == "AMJ":
        X.subst(ctx.par("AVALIAÇÃO MERCADOLÓGICA"), "AVALIAÇÃO MERCADOLÓGICA",
                "AVALIAÇÃO MERCADOLÓGICA JUDICIAL")
    solicitante = _val(_campo(ctx.cs, "solicitante")) or t.cliente
    for rot, val in (("Imóvel Avaliado:", _imovel(ctx)),
                     ("Finalidade do Parecer:", t.finalidade.rstrip(".") + "."),
                     ("Solicitante:", solicitante.rstrip(".") + "."),
                     ("Data-base da avaliação:", X.data_extenso(t.data_base) + ".")):
        p = ctx.par(rot)
        if p is not None:
            X.definir_valor(p, val)
    p = ctx.par("Processo (somente AMJ):")
    if p is not None:
        proc = ", ".join(x for x in (t.processo_numero.strip(), t.vara_juizo.strip()) if x)
        if t.modalidade in ("AMJ", "AM") and proc:
            X.subst(p, "Processo (somente AMJ):", "Processo:")
            X.definir_valor(p, proc)
        else:
            X.remover(p)
    p = ctx.par("Vistoria realizada em:")
    if p is not None:
        X.definir_valor(p, X.data_extenso(t.data_vistoria) + ".")
    # foto da fachada (a marcada no envio; senão a primeira), demarcada em vermelho
    capa = next((e for e in ctx.body.iter(qn("w:p")) if X.tem_imagem(e)), None)
    fotos = _fotos(ctx)
    if capa is None:
        return
    if not fotos:
        ctx.aviso("foto da fachada ausente na capa")
        X.remover_imagens(capa)
        return
    rel, img, _ = fotos[0]
    caixa = ctx.ext.get("fachada_caixa")
    marcada = db.fachada(ctx.job)  # escolha do avaliador prevalece sobre a dedução
    if marcada and marcada != rel:
        p = ctx.arq(marcada)
        if p is not None and p.suffix.lower() in _EXT_IMG:
            rel, img, caixa = marcada, _tarjada(ctx, marcada, p), None  # caixa era de outra foto
    with Image.open(img) as im:
        w, h = im.size
    cx = _caixas([caixa] if caixa else [], w, h)
    if cx:
        x0, y0, x1, y1 = cx[0]
        img = imagens.demarcar(img, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                               ctx.saida / "capa_demarcada.png")
    else:
        ctx.aviso("fachada sem demarcação (caixa ausente ou inválida)")
    X.trocar_imagem(capa, ctx.part, img, *CAPA)


# ------------------------------------------------------------------ 6, 7.1, 7.3
def _arquivos_doc(ctx: _Ctx) -> tuple[list[str], list[str]]:
    """(documentos do imóvel, documentos do solicitante) — caminhos relativos registrados.
    Citação por nome exato (mesma regra da extração): 'iptu.png' não casa 'planta_iptu.png'."""
    regs = [a["caminho"] for a in db.arquivos(ctx.job)]
    fotos = {f.get("arquivo") for f in ctx.ext.get("fotos") or []}
    chaves = {_chave(rel) for rel in regs}

    def cita(fonte: str, rel: str) -> bool:
        return _chave(rel) in _citados(fonte or "", chaves)
    citados = []
    for c in ctx.cs:
        if c.origem != "documento":
            continue
        for rel in regs:
            if rel in fotos or rel in citados:
                continue
            if cita(c.fonte, rel):
                citados.append(rel)
    descartados = {PurePosixPath(d.get("arquivo", "")).name
                   for d in ctx.ext.get("documentos_descartados") or []}
    sol_fonte = _campo(ctx.cs, "solicitante")
    sol, imovel = [], []
    tipos = {a["caminho"]: a.get("tipo", "") for a in db.arquivos(ctx.job)}
    outras_fontes = " ".join(c.fonte or "" for c in ctx.cs if c is not sol_fonte)
    for rel in regs:
        if rel in fotos or PurePosixPath(rel).name in descartados:
            continue
        eh_sol = (_SOLICITANTE.search(PurePosixPath(rel).name) is not None
                  or tipos.get(rel) in ("solicitante", "identificacao")
                  or (sol_fonte is not None and cita(sol_fonte.fonte, rel)
                      and not cita(outras_fontes, rel)))
        if eh_sol:
            sol.append(rel)
        elif rel in citados:
            imovel.append(rel)
    return imovel, sol


def _tab_documentos(ctx: _Ctx) -> None:
    tb = ctx.tabela("Nr")
    if tb is None or "Documento" not in X.texto(tb.find(qn("w:tr"))):
        return
    trs = tb.findall(qn("w:tr"))
    modelo = trs[1]
    linhas = []
    for ln in (ctx.textos.secoes.get("6") or "").splitlines():
        partes = [x.strip() for x in ln.split("|")]
        if len(partes) == 4 and partes[0]:
            linhas.append(partes)
    imovel, sol = _arquivos_doc(ctx)
    if not linhas:
        linhas = [[_rotulo(ctx, r, completo=True), "Contratante", "—", "Anexo III"]
                  for r in imovel]
        if sol:
            linhas.append(["Documentos de identificação do solicitante", "Contratante", "—",
                           "Anexo IV"])
    linhas.append(["Fotografias da vistoria", "Avaliador",
                   ctx.t.data_vistoria.strftime("%d/%m/%Y"), "Item 7.5"])
    for tr in trs[1:]:
        tb.remove(tr)
    for i, ln in enumerate(linhas, start=1):
        tr = copy.deepcopy(modelo)
        for tc, v in zip(tr.findall(qn("w:tc")), [f"{i:02d}", *ln]):
            p = tc.find(qn("w:p"))
            X.definir(p, v)
        tb.append(tr)


def _localizacao(ctx: _Ctx) -> None:
    leg = ctx.par("Imagem 02")
    img_p = leg.getprevious() if leg is not None else None
    mapas = sorted(ctx.pasta.glob("maps*.png"))
    if img_p is not None and X.tem_imagem(img_p):
        if mapas:
            img = mapas[0]
            loc = db.resultado(ctx.job, "localizacao") or {}
            pol = loc.get("poligono") or []
            if len(pol) >= 3:
                img = imagens.demarcar(img, [tuple(map(int, p)) for p in pol],
                                       ctx.saida / "mapa_demarcado.png")
            X.trocar_imagem(img_p, ctx.part, img, *MAPA)
        else:
            X.remover(img_p)
            X.remover(leg)
            ctx.aviso(SEM_LOCALIZACAO)
    link_p = ctx.par("Localização online:")
    if link_p is not None:
        h = link_p.find(qn("w:hyperlink"))
        if ctx.t.pin_maps and h is not None:
            X.apontar_hyperlink(h, ctx.part, ctx.t.pin_maps.strip())
        else:
            X.remover(link_p)
            ctx.aviso("link do Google Maps ausente")


def _tab_areas(ctx: _Ctx) -> None:
    tb = ctx.tabela("Área")
    if tb is None:
        return
    situ = {"documento": "Documental", "vistoria": "Vistoria"}
    for tr in tb.findall(qn("w:tr"))[1:]:
        tcs = tr.findall(qn("w:tc"))
        rot = _n(X.texto(tcs[0]))
        c = _campo(ctx.cs, "area", "terreno") if "terreno" in rot else \
            _campo(ctx.cs, "area", "constru")
        vals = ([_area(c), _fonte(ctx, c), situ.get(c.origem, "")] if c else ["n/i", "—", "—"])
        for tc, v in zip(tcs[1:], vals):
            X.definir(tc.find(qn("w:p")), v)


def _rotulo(ctx: _Ctx, fonte: str, completo: bool = False) -> str:
    """Rótulo do documento dado pela extração (pelo conteúdo); nome do arquivo só em último
    caso, com aviso."""
    f = fonte.replace("\\", "/").strip()
    for d in ctx.ext.get("documentos") or []:
        arq = PurePosixPath(str(d.get("arquivo", "")).replace("\\", "/")).name
        if arq and arq in f:
            r = d.get("rotulo_completo" if completo else "rotulo_curto") or ""
            if r.strip():
                return r.strip()
    nome = PurePosixPath(f.split()[0]).name if f else ""
    if nome and nome not in ctx.sem_rotulo:
        ctx.sem_rotulo.add(nome)
        ctx.aviso(f"rótulo de documento ausente: {nome}")
    return nome


def _fonte(ctx: _Ctx, c: Campo) -> str:
    if c.origem == "vistoria":
        return "Vistoria"
    return _rotulo(ctx, c.fonte) or "—"


# ------------------------------------------------------------------ 7.5 fotos
def _grade_fotos(ctx: _Ctx) -> None:
    tb = ctx.tabela("Foto 01")
    if tb is None:
        return
    fotos = _fotos(ctx)
    trs = tb.findall(qn("w:tr"))
    modelo = trs[0]
    for tr in trs:
        tb.remove(tr)
    if not fotos:
        ctx.aviso(SEM_FOTOS)
        X.remover(tb)
        return
    for i in range(0, len(fotos), 2):
        tr = copy.deepcopy(modelo)
        for j, tc in enumerate(tr.findall(qn("w:tc"))):
            ps = tc.findall(qn("w:p"))
            if i + j < len(fotos):
                _, img, leg = fotos[i + j]
                X.definir(ps[0], f"Foto {i + j + 1:02d} – {leg}".rstrip(" –"))
                X.trocar_imagem(ps[1], ctx.part, img, *FOTO)
            else:
                X.definir(ps[0], "")
                X.remover_imagens(tc)
        tb.append(tr)


# ------------------------------------------------------------------ amostras e cálculo
def _unit(r: Referencial) -> Decimal:
    return (Decimal(str(r.preco)) / Decimal(str(r.area_m2))).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _escolhidos(sel: Selecao) -> list[Referencial]:
    return [r for r in sel.refs if r.escolhido and r.area_m2 and r.preco]


def _visto_em(r: Referencial) -> str:
    """dd/mm/aaaa em que o anúncio reaproveitado do banco foi visto ('' se coletado agora)."""
    if r.fonte_coleta != "banco" or not r.visto_em:
        return ""
    try:
        return datetime.fromisoformat(r.visto_em.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except ValueError:
        return ""


def _tab_amostras(ctx: _Ctx) -> None:
    tb = None
    for cand in ctx.body.iter(qn("w:tbl")):
        tr = cand.find(qn("w:tr"))
        if X.texto(tr).startswith("Nr") and "Foto Principal" in X.texto(tr):
            tb = cand
    if tb is None:
        return
    trs = tb.findall(qn("w:tr"))
    modelo = trs[1]
    for tr in trs[1:]:
        tb.remove(tr)
    uf = "GO"
    for i, r in enumerate(_escolhidos(ctx.sel), start=1):
        tr = copy.deepcopy(modelo)
        tcs = tr.findall(qn("w:tc"))
        X.definir(tcs[0].find(qn("w:p")), f"{i:02d}")
        ps = tcs[1].findall(qn("w:p"))
        X.definir(ps[0], f"Localização: {r.bairro}, {ctx.t.cidade} – {uf}.")
        X.definir(ps[1], f"Anúncio do site {r.portal.upper()} no link:")
        h = ps[2].find(qn("w:hyperlink"))
        X.apontar_hyperlink(h, ctx.part, r.link)
        desc = ctx.textos.descricao_amostras.get(r.n) or r.descricao or ""
        visto = _visto_em(r)
        if visto:
            desc = f"{desc.rstrip()} (anúncio visto em {visto})".strip()
        X.definir(ps[3], desc)
        X.definir(tcs[2].find(qn("w:p")), f"{X.num(r.lote_m2)} m²" if r.lote_m2 else "n/i")
        X.definir(tcs[3].find(qn("w:p")), f"{X.num(r.area_m2)} m²")
        X.definir(tcs[4].find(qn("w:p")), r.idade_aparente or "n/i")
        fps = tcs[5].findall(qn("w:p"))
        foto = ctx.arq(r.foto)
        if foto is not None and foto.suffix.lower() in _EXT_IMG:
            X.trocar_imagem(fps[0], ctx.part, foto, *AMOSTRA)
        else:
            X.remover_imagens(tcs[5])
        X.definir(fps[-1], X.brl(r.preco))
        X.definir(tcs[6].find(qn("w:p")), f"{X.brl(_unit(r))}/m²")
        tb.append(tr)


def _tab_label(tb, valores: dict[str, str]) -> None:
    for tr in tb.findall(qn("w:tr"))[1:]:
        tcs = tr.findall(qn("w:tc"))
        rot = _n(X.texto(tcs[0]))
        for k, v in valores.items():
            if rot.startswith(_n(k)):
                X.definir(tcs[1].find(qn("w:p")), v)
                break


def _calculo(ctx: _Ctx) -> None:
    r, t = ctx.r, ctx.t
    us = [float(u) for u in r.unitarios]
    media = float(r.media)
    dp = statistics.stdev(us) if len(us) > 1 else 0.0
    cv = dp / media * 100 if media else 0.0
    tb = ctx.tabela("Estatística")
    if tb is not None:
        _tab_label(tb, {
            "Número de referenciais": str(len(r.unitarios)),
            "Valor unitário mínimo": f"{X.brl(r.minimo)}/m²",
            "Valor unitário máximo": f"{X.brl(r.maximo)}/m²",
            "Média aritmética": f"{X.brl(r.media)}/m²",
            "Mediana": f"{X.brl(statistics.median(r.unitarios))}/m²",
            "Desvio padrão": f"{X.brl(dp)}/m²",
            "Coeficiente de variação": f"{X.num(cv)}%",
        })
    p = ctx.par("A amostra apresentou coeficiente de variação")
    if p is not None:
        if len(us) < 3:
            # com 1 referencial o desvio é 0 e o laudo afirmava "baixa dispersão"
            X.definir(p, f"A amostra conta com {len(us)} referencial(is), quantidade "
                         "insuficiente para medir a dispersão dos valores unitários.")
        else:
            grau = "baixa" if cv <= 15 else ("moderada" if cv <= 30 else "elevada")
            X.definir(p, f"A amostra apresentou coeficiente de variação de {X.num(cv)}%, "
                         f"indicando {grau} dispersão dos valores unitários.")
    area = area_construida(ctx.job) or (r.valor_calculado / r.unitario_adotado)
    p = ctx.par("Valor de Mercado = [PREENCHER: área]")
    if p is not None:
        X.definir(p, f"Valor de Mercado = {X.num(area)} m² × {X.brl(r.unitario_adotado)}/m²")
    p = ctx.par("Valor de Mercado = R$ [PREENCHER")
    if p is not None:
        X.definir(p, f"Valor de Mercado = {X.brl(r.valor_calculado)}")
    p = ctx.par("R$ [PREENCHER: valor adotado]")
    if p is not None:
        X.definir(p, X.brl(r.valor_adotado))
    p = ctx.par("([PREENCHER: valor por extenso])")
    if p is not None:
        X.definir(p, f"({r.extenso}).")
    f = X.pct(r.faixa_pct)
    for p in ctx.body.iter(qn("w:p")):
        X.subst(p, "±10%", f"±{f}%")
        X.subst(p, "(−10%)", f"(−{f}%)")
        X.subst(p, "(+10%)", f"(+{f}%)")
    tb = ctx.tabela("FAIXA DE VARIAÇÃO")
    if tb is not None:
        _tab_label(tb, {"Valor mínimo": X.brl(r.valor_min),
                        "Valor de mercado adotado": X.brl(r.valor_adotado),
                        "Valor máximo": X.brl(r.valor_max)})
    # resumo
    cs = ctx.cs
    terreno, constru = _campo(cs, "area", "terreno"), _campo(cs, "area", "constru")
    padrao = _val(_campo(cs, "padrao"))
    estado = _val(_campo(cs, "conservacao"))
    idade = _val(_campo(cs, "idade"))
    benf = _val(_campo(cs, "benfeitoria"))
    tb = ctx.tabela("Elemento")
    if tb is not None:
        _tab_label(tb, {
            "Imóvel": _imovel(ctx).split(" – ", 1)[-1],
            "Área do terreno": f"{_area(terreno)} m² ({_fonte(ctx, terreno)})" if terreno else "n/i",
            "Área construída adotada": f"{X.num(area)} m²"
                                       + (f" ({_fonte(ctx, constru)})" if constru else ""),
            "Tipologia / padrão": f"{t.tipo} / {padrao or 'n/i'}",
            "Estado de conservação": (estado or "n/i")
                                     + (f" – idade aparente {idade}" if idade else ""),
            "Principais benfeitorias": benf or "n/i",
            "Valor unitário médio": f"{X.brl(r.media)}/m²",
            "Valor unitário adotado": f"{X.brl(r.unitario_adotado)}/m²",
            "VALOR DE MERCADO DO IMÓVEL": X.brl(r.valor_adotado),
            "Faixa de variação": f"±{f}% – {X.brl(r.valor_min)} a {X.brl(r.valor_max)}",
            "Data-base": t.data_base.strftime("%d/%m/%Y"),
        })
    p = ctx.par("O presente parecer é composto por")
    if p is not None:
        rpr = X.rpr_base(p)
        X.limpar_runs(p)
        p.append(X.novo_run("O presente parecer é composto por ", rpr))
        for run in X.campo_runs("NUMPAGES", "1", rpr):
            p.append(run)
        p.append(X.novo_run(" páginas, incluindo anexos, todas numeradas.", rpr))
    p = ctx.par("Goiânia, [PREENCHER")
    if p is not None:
        X.definir(p, f"Goiânia, {X.data_extenso(date.today())}.")


# ------------------------------------------------------------------ AMJ / perito
def _avaliador() -> dict:
    try:
        d = json.loads(db.setting("avaliador", "{}") or "{}")
    except ValueError:
        d = {}
    return {k: str(v).strip() for k, v in d.items() if isinstance(v, (str, int, float))}


def _perito(ctx: _Ctx) -> None:
    """Qualificação do perito (AM/AMJ) a partir da config do avaliador (formação e
    qualificação), nunca da redação. Dados do processo ausentes no AMJ: aviso grave."""
    t = ctx.t
    if t.modalidade == "AMJ":
        faltam = [rot for rot, v in (("nº do processo", t.processo_numero),
                                     ("vara/juízo", t.vara_juizo),
                                     ("partes", t.partes and (t.partes.autor or t.partes.reu)))
                  if not (v or "").strip()]
        if faltam:
            ctx.aviso(f"{AMJ_SEM_PROCESSO}: {', '.join(faltam)}")
    p = ctx.par("Alan Soares da Silva, Corretor de Imóveis inscrito")
    if p is None:
        return
    av = _avaliador()
    base = X.texto(p).split(PLACEHOLDER)[0].strip()
    extra = " ".join(x.rstrip(".") + "." for x in (av.get("formacao", ""),
                                                   av.get("qualificacao", "")) if x)
    if not av.get("qualificacao") and t.modalidade == "AMJ":
        ctx.aviso(PERITO_SEM_QUALIFICACAO)
    X.definir(p, f"{base} {extra}".strip())


# ------------------------------------------------------------------ anexos
def _sem_tarja(ctx: _Ctx, rel: str) -> list[str]:
    """Imagem ou páginas de PDF ("<arquivo>#p<N>") sem nenhuma caixa válida dentro dos
    limites reais (imagem: pixels; PDF: pontos da página). Vazio = totalmente tarjado."""
    p = ctx.arq(rel)
    if p is None:
        return []
    if p.suffix.lower() == ".pdf":
        with pymupdf.open(p) as d:
            tams = [(pg.rect.width, pg.rect.height) for pg in d]
        return [f"{rel}#p{i}" for i, (w, h) in enumerate(tams, start=1)
                if not _caixas(_caixas_brutas(ctx, rel, i), int(w), int(h))]
    if p.suffix.lower() in _EXT_IMG:
        with Image.open(p) as im:
            w, h = im.size
        return [] if _caixas(_caixas_brutas(ctx, rel), w, h) else [rel]
    return []


def _imagens_doc(ctx: _Ctx, rel: str, tarjar: bool) -> list[Path]:
    p = ctx.arq(rel)
    if p is None:
        return []
    if p.suffix.lower() == ".pdf":
        pasta = ctx.saida / "anexos" / p.stem
        pags = imagens.pdf_paginas_png(p, pasta, dpi=DPI_ANEXO)
        if not tarjar:
            return pags
        # caixas da extração em pontos PDF (1/72 pol.) -> pixels do PNG renderizado
        return [_tarjada(ctx, rel, pg, _caixas_brutas(ctx, rel, i), DPI_ANEXO / 72,
                         pasta / f"{pg.stem}-tarjada.png")
                for i, pg in enumerate(pags, start=1)]
    if p.suffix.lower() in _EXT_IMG:
        return [_tarjada(ctx, rel, p) if tarjar else p]
    return []


def _anexo(ctx: _Ctx, titulo: str, rels: list[str], legenda_padrao: str | None,
           tarjar: bool) -> None:
    h = ctx.par(titulo)
    if h is None:
        return
    img_p = h.getnext()
    if img_p is None or not X.tem_imagem(img_p):
        return
    leg_p = img_p.getnext()
    paginas = [(rel, im) for rel in rels for im in _imagens_doc(ctx, rel, tarjar)]
    if not paginas:
        X.remover(img_p)
        if legenda_padrao is None:
            X.definir(leg_p, "Documentos não apresentados.")
        else:
            X.definir(leg_p, "Documentos de identificação não apresentados.")
        ctx.aviso(f"{titulo}: nenhum documento para anexar")
        return
    ultimo = leg_p if legenda_padrao is not None else img_p
    for i, (rel, im) in enumerate(paginas):
        novo = copy.deepcopy(img_p)
        X.trocar_imagem(novo, ctx.part, im, *ANEXO)
        ultimo = X.inserir_apos(ultimo, novo)
        if legenda_padrao is None:
            leg = copy.deepcopy(leg_p)
            X.definir(leg, _rotulo(ctx, rel, completo=True))
            ultimo = X.inserir_apos(ultimo, leg)
    X.remover(img_p)
    if legenda_padrao is None:
        X.remover(leg_p)


def _anexos(ctx: _Ctx) -> None:
    imovel, sol = _arquivos_doc(ctx)
    tarjados = []
    for rel in sol:  # nunca anexa documento do solicitante sem tarja (dado pessoal exposto)
        faltam = _sem_tarja(ctx, rel)  # uma página sem tarja barra o documento inteiro
        if not faltam:
            tarjados.append(rel)
        for f in faltam:
            ctx.aviso(f"{SEM_TARJA}: {f}")
    _anexo(ctx, "Anexo III – Documentação do Imóvel", imovel, None, tarjar=False)
    _anexo(ctx, "Anexo IV – Documentação do Solicitante", tarjados, "", tarjar=True)


# ------------------------------------------------------------------ sumário
# ------------------------------------------------------------------ varredura
def _todo_texto(ctx: _Ctx) -> str:
    partes = [X.texto(ctx.body)] + [X.texto(hf._element) for hf in _cabecalhos(ctx)]
    return "\n".join(partes)


def _nomes_arquivos(ctx: _Ctx) -> set[str]:
    """Nomes (normalizados) dos arquivos registrados do job."""
    return {_chave(a[k]) for a in db.arquivos(ctx.job) for k in ("nome", "caminho")
            if a.get(k)}


def _texto_redacao(ctx: _Ctx) -> str:
    t = ctx.textos
    return "\n".join([*t.secoes.values(), *t.legendas.values(),
                      *t.descricao_amostras.values()])


def varrer(texto: str, modalidade: str, arquivos: set[str] | frozenset = frozenset()) -> None:
    """Conteúdo vedado. `arquivos`: nomes de arquivo do job que não podem aparecer no texto
    redigido (o laudo cita documentos pelo rótulo, nunca pelo nome do arquivo)."""
    vazou = sorted(_citados(texto, set(arquivos))) if arquivos else []
    if vazou:
        raise ConteudoProibido(f"nome de arquivo no texto do laudo: {', '.join(vazou)}")
    if PLACEHOLDER in texto:
        i = texto.index(PLACEHOLDER)
        raise ConteudoProibido(f"campo do modelo não preenchido: {texto[i:i + 60]!r}")
    if re.search(r"sem\s+inspe[cç][aã]o\s+de\s+engenharia", texto, re.I):
        raise ConteudoProibido('frase vedada: "sem inspeção de engenharia" (D-012)')
    if modalidade == "OV" and re.search(r"\bPTAM\b", texto.replace(_CURRICULO_PTAM, "")):
        raise ConteudoProibido('a palavra "PTAM" não pode aparecer em OV (D-011)')


def _limpar_rels(ctx: _Ctx) -> None:
    xml = ctx.body.xml
    for rid, rel in list(ctx.part.rels.items()):
        if rel.reltype in (RT.HYPERLINK, RT.IMAGE) and f'"{rid}"' not in xml:
            del ctx.part.rels[rid]


def montar(job_id: str, textos: Textos, r: Resultado, selecao: Selecao) -> Path:
    ctx = _Ctx(job_id, textos, r, selecao)
    ctx.saida.mkdir(parents=True, exist_ok=True)
    _capa(ctx)
    _tab_documentos(ctx)
    _localizacao(ctx)
    _tab_areas(ctx)
    _grade_fotos(ctx)
    _tab_amostras(ctx)
    _calculo(ctx)
    _anexos(ctx)
    _perito(ctx)
    X.secoes(ctx)
    X.modalidade(ctx)
    X.renumerar(ctx)
    X.manter_juntos(ctx)
    X.montar_sumario(ctx)
    X.renumerar_docpr(ctx.body)
    varrer(_texto_redacao(ctx), ctx.t.modalidade, _nomes_arquivos(ctx))
    varrer(_todo_texto(ctx), ctx.t.modalidade)
    _limpar_rels(ctx)
    destino = ctx.pasta / f"{nomes.nome_arquivo(ctx.t)}.docx"
    ctx.doc.save(str(destino))
    db.evento(job_id, "montagem", "resultado", f"laudo Word gerado: {destino.name}",
              dados={"docx": destino.name})
    return destino

