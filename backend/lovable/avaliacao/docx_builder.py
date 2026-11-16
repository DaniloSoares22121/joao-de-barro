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

from . import db, escolha_laudo, identidade, imagens, nomes
from . import docx_partes as X
from .agentes import _comum
from .agentes.extracao import _chave, _citados
from .agentes.redacao import Textos
from .agentes.selecao import Selecao, area_construida, base_area, eh_area_construida, refs_na_base
from .calculo import Resultado
from .conhecimento import PASTA as _CONHECIMENTO
from .modelos import Campo, Referencial, Trabalho
from .plural import pl

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
# ORDEM 035 / D-062 (Alan: "todo documento segue a mesma regra"): no laudo entregue ao CLIENTE
# FINAL nenhum documento leva tarja, inclusive RG/CNH/OAB do solicitante. Para qualquer outra
# pessoa (exemplo D-041, base comum, fichas, exportação) a proteção é obrigatória — o exemplo
# desfoca os anexos de documentação; as caixas de tarja da extração continuam guardadas.
TARJA_NO_LAUDO_DO_CLIENTE = False
AMJ_SEM_PROCESSO = "AMJ sem dados do processo"
PERITO_SEM_QUALIFICACAO = "perito sem qualificação na configuração do avaliador"
DPI_ANEXO = 110

# Caixas (EMU; 1 cm = 360000) das imagens — A4, REGRAS_GERADOR_D040 / D-031
CAPA = (5400000, 3780000)     # 15 cm de largura (fachada recortada no imóvel)
FOTO = (2592000, 1872000)     # caixa 7,2 × 5,2 cm do relatório fotográfico
AMOSTRA = (1440000, 1440000)  # foto principal do anúncio: 4,0 cm de largura, inteira
MAPA = (5940000, 3960000)     # 16,5 × 11 cm (largura do texto)
ANEXO = (5940000, 7200000)    # 16,5 × 20 cm: título + documento + legenda na mesma página
# ORDEM 029-1: documento de várias páginas em grade 2 × 2 por página, como no laudo do Alan
# (cada página do documento ~7,55 × 10,8 cm, sem legenda por imagem)
ANEXO_GRADE = (2718000, 3888000)
_PJ_DOC = re.compile(r"(?i)cnpj|cadastro nacional da pessoa jur|pessoa jur[ií]dica|contrato social|"
                     r"inscri[çc][ãa]o e de situa[çc][ãa]o cadastral")
_PESSOA_DOC = re.compile(r"(?i)\b(?:rg|cnh|cpf|identidade|carteira de (?:habilita|identid)|oab)\b")
MAX_FOTOS = 12                # (histórico, D-039) — D-057: sem limite; manda a escolha (escolha_laudo)
MIN_FOTOS = 8


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


def _constru(cs: list[Campo], job: str | None = None) -> Campo | None:
    """Campo da área construída ("Área construída", "Área edificada" do IPTU...). ORDEM 028-5: a
    escolhida pelo avaliador no "Confirmar valor" (ORDEM 021) vem primeiro — a tabela de áreas e o
    resumo têm de bater com a área do cálculo."""
    if job:
        from .agentes.selecao import escolha_area
        esc = escolha_area(job)
        if esc and esc.get("base") == "construida":
            # a escolhida pode ser "inferido" (medição por satélite), que _campos() deixa de fora
            c = next((c for c in list(cs) + db.campos(job) if c.nome == esc.get("campo")), None)
            if c is not None:
                return c
    return next((c for c in cs if eh_area_construida(c.nome)), None)


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
        if self.t.tipo:                       # 074-D: "casa (IPTU predial)" → "Casa" na capa, no resumo e no nome
            from .dados_cliente import tipo_limpo
            self.t = self.t.model_copy(update={"tipo": tipo_limpo(self.t.tipo) or self.t.tipo})
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
             destino: Path | None = None, chave: str | None = None) -> Path:
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
    # folga pequena: a caixa da IA costuma ficar justa e deixar dígito visível na borda;
    # a tarja cobre só os NÚMEROS (CPF, RG, registro CNH, inscrição OAB, nascimento) —
    # nome, filiação e foto ficam visíveis (vínculo do solicitante, P6 A)
    # A IA erra o comprimento do número no sentido do texto (documento girado na foto): folga
    # de metade do lado maior da caixa, em todas as direções.
    fotos = {f.get("arquivo") for f in ctx.ext.get("fotos") or []} | {_fachada(ctx)}
    if str(rel).startswith("foto/") or rel in fotos:
        # fotos (placa, rosto): folga pequena — a de 50% é para números de documentos
        boas = [(max(0, x0 - 4), max(0, y0 - 4), min(w, x1 + 4), min(h, y1 + 4))
                for x0, y0, x1, y1 in boas]
        return imagens.borrar(origem, boas,
                              destino or ctx.saida / "tarjadas" / PurePosixPath(rel).name)
    elif (chave or rel) in (ctx.ext.get("tarjas_conferidas") or []):
        # caixas conferidas pelo avaliador na tela: só 3 px de folga
        boas = [(max(0, x0 - 3), max(0, y0 - 3), min(w, x1 + 3), min(h, y1 + 3))
                for x0, y0, x1, y1 in boas]
    else:
        boas = [(max(0, x0 - (f := max(12, int(max(x1 - x0, y1 - y0) * 0.5)))), max(0, y0 - f),
                 min(w, x1 + f), min(h, y1 + f)) for x0, y0, x1, y1 in boas]
    return imagens.tarjar(origem, boas,
                          destino or ctx.saida / "tarjadas" / PurePosixPath(rel).name)


_NOME_FACHADA = re.compile(r"(?i)(?:^|[^a-z])(?:fachada|frente|frontal|portaria)(?:[^a-z]|$)")


def _fachada(ctx) -> str | None:
    """Foto da capa: a marcada pelo avaliador; senão (L201-4, Caso M: a IA pôs o hall interno como fachada) a foto que
    o próprio avaliador nomeou fachada/frente/portaria — a fachada antes da portaria. Senão, a escolha da extração."""
    marcada = db.fachada(ctx.job)
    if marcada:
        return marcada
    nomes = sorted((a["caminho"] for a in db.arquivos(ctx.job) if a.get("tipo") == "foto"
                    and _NOME_FACHADA.search(PurePosixPath(a["caminho"]).stem.replace("_", " "))),
                   key=lambda c: (not re.search(r"(?i)fachada|frente|frontal", c), c))
    return nomes[0] if nomes else None


def _fotos(ctx: _Ctx) -> list[tuple[str, Path, str]]:
    """Fotos do relatório (D-057): a fachada marcada pelo avaliador primeiro ("Fachada frontal –
    vista da rua"), depois as escolhidas pela extração sem as quase iguais (fica a mais nítida),
    na ordem externas → internas → detalhes, sem os prints de medição (vão para as áreas)."""
    out = []
    marcada = _fachada(ctx)
    lista = escolha_laudo.escolher_fotos(list(ctx.ext.get("fotos") or []), ctx.arq, marcada,
                                         escolha_laudo.prints_medicao(ctx.cs))
    for f in lista:
        p = ctx.arq(f.get("arquivo", ""))
        if p is None or p.suffix.lower() not in _EXT_IMG:
            continue
        leg = ctx.textos.legendas.get(f["arquivo"]) or f.get("legenda") or ""
        from . import ajustes
        if f.get("arquivo") != marcada and ajustes.foto_fora(ctx.job, f.get("arquivo", ""), leg):
            continue                               # L200 (Caso W): o avaliador tirou a foto pelo "Pedir ajuste"
        if f.get("arquivo") == marcada and not re.search(r"fachada", leg, re.I):
            leg = ("Fachada – portaria do condomínio, vista da rua" if re.search(r"(?i)portaria", marcada or "")
                   else "Fachada frontal – vista da rua")
        out.append((f["arquivo"], _tarjada(ctx, f["arquivo"], p), leg))
    return out


def _recorte_fachada(img: Path, caixa, destino: Path, folga: float = 1.6) -> tuple[Path, list | None]:
    """Recorta a foto no imóvel (caixa da fachada + respiro), na proporção da capa, e devolve
    a caixa em coordenadas do recorte para a demarcação."""
    with Image.open(img) as im:
        w, h = im.size
        if not caixa:
            return img, None
        x0, y0, x1, y1 = caixa
        bw, bh = x1 - x0, y1 - y0
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rw = max(bw * folga, bh * folga * CAPA[0] / CAPA[1])
        rh = rw * CAPA[1] / CAPA[0]
        rw, rh = min(rw, w), min(rh, h)
        if rw >= w * 0.95 and rh >= h * 0.95:
            return img, [x0, y0, x1, y1]
        left = int(min(max(cx - rw / 2, 0), w - rw))
        top = int(min(max(cy - rh / 2, 0), h - rh))
        corte = im.crop((left, top, int(left + rw), int(top + rh))).convert("RGB")
        destino.parent.mkdir(parents=True, exist_ok=True)
        corte.save(destino, "JPEG", quality=90)
    return destino, [x0 - left, y0 - top, x1 - left, y1 - top]


# ------------------------------------------------------------------ capa e cabeçalho
def _cabecalhos(ctx: _Ctx) -> list:
    """Cabeçalhos/rodapés definidos (sem criar os que não existem)."""
    return [hf for s in ctx.doc.sections
            for hf in (s.header, s.footer, s.first_page_header, s.first_page_footer,
                       s.even_page_header, s.even_page_footer)
            if not hf.is_linked_to_previous]

def _endereco_partes(ctx: _Ctx) -> str:
    """Endereço montado das partes (logradouro, quadra, lote, bairro, CEP) quando a extração
    não deu um campo "Endereço" inteiro: "Rua X, Quadra 10, Lote 05, Bairro, município de
    Cidade – GO, CEP 00000-000"."""
    log = re.sub(r",?\s*s/?n[º°.]?\s*$", "", _SIGLA_RUA.sub("", _val(_campo(ctx.cs, "logradouro"))), flags=re.I).strip()
    if not log:
        return ""
    qd, lt = _val(_campo(ctx.cs, "quadra")), _val(_campo(ctx.cs, "lote"))
    bairro = _val(_campo(ctx.cs, "bairro")) or ctx.t.bairro
    cep = _val(_campo(ctx.cs, "cep"))
    partes = [log] + ([f"Quadra {qd}"] if qd else []) + ([f"Lote {lt}"] if lt else []) + \
             [bairro, f"município de {ctx.t.cidade} – GO"] + ([f"CEP {cep}"] if cep else [])
    return ", ".join(partes)


def _trocas_grafia(ctx: _Ctx, texto: str) -> list[tuple[str, str]]:
    """Pares (como está, grafia do documento) para quadra/lote: "Qd. 58A" -> "Qd. 58-A" quando
    o campo "Quadra" diz 58-A (P6 A: endereço idêntico em todo o laudo)."""
    out = []
    for chave, rot in (("quadra", r"(?:Quadra|Qd\.?)"), ("lote", r"(?:Lote|Lt\.?)")):
        c = next((x for x in ctx.cs if x.nome.strip().casefold() == chave), None)
        v = _val(c).strip() if c else ""
        if not v:
            continue
        alvo = re.sub(r"[^0-9a-z]", "", v.casefold())
        for m in re.finditer(rf"\b({rot})\s*([0-9]+(?:\s*-\s*)?[A-Za-z]?(?:\s*-\s*[0-9A-Za-z]+)*)(?![0-9A-Za-z])", texto):
            if re.sub(r"[^0-9a-z]", "", m.group(2).casefold()) == alvo and m.group(2) != v:
                out.append((m.group(0), f"{m.group(1)} {v}"))
    return out


def _quadra_lote_do_documento(ctx: _Ctx, end: str) -> str:
    """172-5: o endereço escrito traz quadra/lote DIFERENTES dos campos "quadra"/"lote" lidos do documento (IPTU,
    matrícula) ou da vistoria → no laudo vale o do documento, e o avaliador recebe um aviso com os dois valores e a
    fonte de cada um (nunca corrigir em silêncio, nunca escrever número que contradiz o documento)."""
    end_c = next((x for x in ctx.cs if x.nome.strip().casefold() == "endereco"), None)
    trocas = _pares_quadra_lote(ctx, end, completo=True)
    for chave, velho, novo, antes, depois, fonte in trocas:
        end = end.replace(velho, novo, 1)
        try:
            from .planilha import _fonte as _f
            de = _f(end_c) if end_c is not None else "o campo do endereço"
            c = next((x for x in ctx.cs if x.nome.strip().casefold() == chave), None)
            doc = _f(c) if c is not None else fonte
        except Exception:
            de, doc = "o campo do endereço", fonte
        msg = (f"Endereço: {chave} {antes} (em {de or 'o campo do endereço'}) é diferente de {chave} {depois} "
               f"(em {doc or 'documento'}). No laudo ficou {chave} {depois}, a do documento. Confira.")
        if not db.setting(f"aviso_end:{ctx.job}:{chave}:{antes}:{depois}"):
            db.set_setting(f"aviso_end:{ctx.job}:{chave}:{antes}:{depois}", "1")
            db.evento(ctx.job, "montagem", "aviso", msg)
    return end


def _pares_quadra_lote(ctx: _Ctx, end: str, completo: bool = False) -> list:
    """172-5: (velho, novo) — ou, com completo, (chave, velho, novo, antes, depois, fonte) — para cada quadra/lote
    escrito diferente do campo do documento/vistoria."""
    trocas = []
    for chave, rot in (("quadra", r"(?:Quadra|Qd\.?)"), ("lote", r"(?:Lote|Lt\.?)")):
        c = next((x for x in ctx.cs if x.nome.strip().casefold() == chave and x.origem in ("documento", "vistoria")), None)
        v = _val(c).strip() if c else ""
        if not v:
            continue
        alvo = re.sub(r"[^0-9a-z]", "", v.casefold())
        # L200 (Caso M): o número inteiro ("01-26", não só "01") — antes "Lt. 01-26" virava "Lt. 01-26-26" a cada
        # montagem; e o endereço que JÁ traz o número do documento ("Lt. 001E, Compl. Lt. 01-26") não é mexido
        achados = list(re.finditer(rf"\b({rot})\s*([0-9]+[A-Za-z]?(?:\s*-\s*[0-9A-Za-z]+)*)(?![0-9A-Za-z])", end))
        if any(re.sub(r"[^0-9a-z]", "", m.group(2).casefold()) == alvo for m in achados):
            continue
        for m in achados:
            if re.sub(r"[^0-9a-z]", "", m.group(2).casefold()) != alvo:
                trocas.append((chave, m.group(0), f"{m.group(1)} {v}", m.group(2), v, getattr(c, "fonte", "") or ""))
    return trocas if completo else [(x[1], x[2]) for x in trocas]


def _grafia_documento(ctx: _Ctx, texto: str) -> str:
    for velho, novo in _trocas_grafia(ctx, texto):
        texto = texto.replace(velho, novo)
    return texto


_SIGLA_RUA = re.compile(r"\s*\((?:R|AV|AL|TV|PC|ROD)\.?\s*[A-Z0-9][A-Z0-9 \-]{0,20}\)")   # 093-A-9: "Rua XV 9 (R XV9)"


def _imovel(ctx: _Ctx) -> str:
    end = _SIGLA_RUA.sub("", _val(_campo(ctx.cs, "endereco")) or "")
    if end and not re.search(r"(?i)\b(quadra|qd\.?)\s*\w", end) and _val(_campo(ctx.cs, "quadra")):
        end = _endereco_partes(ctx)          # 093-A-9: o campo era só o logradouro — a capa leva quadra e lote
    end = _grafia_documento(ctx, end or _endereco_partes(ctx))
    end = _quadra_lote_do_documento(ctx, end)          # 172-5: número que contradiz o documento não entra no laudo
    end = end.rstrip(". ")
    # 085-6: endereço sem bairro/cidade ("Rua XV 9, Quadra 59, Lote 02") ganha "Jardim Curitiba, Goiânia – GO"
    bairro_base = re.sub(r"(?i)\s+(?:[ivx]+|\d+)$", "", (ctx.t.bairro or "").strip())
    if end and bairro_base and _n(bairro_base) not in _n(end):
        end += f", {ctx.t.bairro}"
    if end and ctx.t.cidade and _n(ctx.t.cidade) not in _n(end):
        end += f", {ctx.t.cidade} – GO"
    end = end + "." if end else ""
    return f"{ctx.t.tipo} – {end}" if end else f"{ctx.t.tipo} – {ctx.t.bairro}, {ctx.t.cidade}"


def _hora_vistoria(ctx) -> str:
    """093-3: a hora da vistoria que o avaliador informou ("13/11/2026 às 12h30"), como no laudo 122."""
    from . import tela_trabalho
    try:
        v = str(((tela_trabalho._cliente(ctx.job) or {}).get("contexto") or {}).get("visita") or "")
    except Exception:
        return ""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})", v)
    if not m or m.group(1) != ctx.t.data_vistoria.isoformat() or (m.group(2), m.group(3)) == ("00", "00"):
        return ""
    return f", às {int(m.group(2))}h{m.group(3)}"


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
    elif t.modalidade in ("AM", "AM_GARANTIA"):
        # ORDEM 043 / D-078 (mudança 2): título do PTAM não judicial
        X.subst(ctx.par("AVALIAÇÃO MERCADOLÓGICA"), "AVALIAÇÃO MERCADOLÓGICA",
                "PARECER TÉCNICO DE AVALIAÇÃO MERCADOLÓGICA – PTAM")
        pn = ctx.par(f"PTAM N.º {t.numero}")
        if pn is not None:
            X.subst(pn, f"PTAM N.º {t.numero}", f"N.º {t.numero} · NÃO JUDICIAL")
            nat = copy.deepcopy(pn)
            X.definir(nat, "Natureza do documento: parecer extrajudicial (não judicial)")
            pn.addnext(nat)
    # ORDEM 013 g: PJ com razão social, CNPJ e sede; nunca o CPF do representante
    solicitante = nomes.qualificacao_laudo(_val(_campo(ctx.cs, "solicitante")) or t.cliente)
    for rot, val in (("Imóvel Avaliado:", _imovel(ctx)),
                     ("Finalidade do Parecer:", t.finalidade.rstrip(".") + "."),
                     ("Solicitante:", solicitante.rstrip(".") + "."),
                     ("Data-base da avaliação:", X.data_extenso(t.data_vistoria) + ".")):
        p = ctx.par(rot)
        if p is not None and rot.startswith("Data-base"):
            X.subst(p, "Data-base da avaliação", "Data da vistoria")   # 117 / D-127: só a data da vistoria
        if p is not None:
            X.definir_valor(p, val)
    p = ctx.par("Processo (somente AMJ):")
    if p is not None:
        partes = ""
        if t.partes and (t.partes.autor or t.partes.reu):
            partes = "; ".join(x for x in ((f"Autor: {t.partes.autor}" if t.partes.autor else ""),
                                           (f"Réu: {t.partes.reu}" if t.partes.reu else "")) if x)
        # P7: capa do AMJ com nº, vara/juízo, ação e partes
        proc = ", ".join(x for x in (t.processo_numero.strip(), t.vara_juizo.strip(),
                                     (t.acao or "").strip() if t.modalidade == "AMJ" else "",
                                     partes if t.modalidade == "AMJ" else "") if x)
        if t.modalidade in ("AMJ", "AM") and proc:
            X.subst(p, "Processo (somente AMJ):", "Processo:")
            X.definir_valor(p, proc)
        else:
            X.remover(p)
    p = ctx.par("Vistoria realizada em:")
    if p is not None:
        if (t.visita_por or "").strip():
            # D-043: visita técnica feita por parceiro — o laudo diz a verdade
            X.definir(p, f"Visita técnica realizada por {t.visita_por.strip().rstrip('.')}, em "
                         f"{X.data_extenso(t.data_vistoria)}, sob responsabilidade técnica do "
                         "avaliador signatário.")
        else:
            X.definir_valor(p, X.data_extenso(t.data_vistoria) + _hora_vistoria(ctx) + ".")
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
    marcada = _fachada(ctx)  # escolha do avaliador prevalece sobre a dedução (L201-4: ou a foto com nome de fachada)
    exts = sorted(ctx.ext.get("fotos") or [], key=lambda f: f.get("ordem", 0))
    if marcada and exts and exts[0].get("arquivo") != marcada:
        caixa = None   # a caixa da extração é de outra foto
    if marcada and marcada != rel:
        p = ctx.arq(marcada)
        if p is not None and p.suffix.lower() in _EXT_IMG:
            rel, img, caixa = marcada, _tarjada(ctx, marcada, p), None  # caixa era de outra foto
    with Image.open(img) as im:
        w, h = im.size
    # AMJ: a capa tem as linhas do processo; com a foto de 10,5 cm a legenda caía sozinha
    # na página 2 (P6 E) — foto 82% do tamanho
    # AMJ e PTAM não judicial (título da D-078 em 2 linhas + natureza): foto menor, capa numa página
    tam = CAPA if t.modalidade == "OV" else (int(CAPA[0] * 0.82), int(CAPA[1] * 0.82))
    from .agentes import fachada
    contorno = fachada.resultado(ctx.job, rel)
    if fachada.eh_edificio(t.tipo) and not contorno:
        # ORDEM 005: torre não identificada com segurança -> foto do condomínio sem
        # demarcação (nada de caixa/contorno adivinhado) e aviso ao avaliador
        X.trocar_imagem(capa, ctx.part, img, *tam)
        for p in ctx.body.iter(qn("w:p")):
            if X.texto(p).strip().startswith("Imagem 01"):
                X.definir(p, "Imagem 01 – Fachada do condomínio onde se localiza a unidade avalianda.")
                break
        # ORDEM 006: decisão do Alan — informativo, não pendência (como no laudo antigo)
        db.evento(ctx.job, "montagem", "info",
                  "capa sem demarcação: a foto do condomínio não permite identificar a torre do "
                  "avaliando com segurança (regra do Alan para apartamento)")
        return
    if contorno:
        # D-004/P6: capa recortada no imóvel e demarcada só nele (contorno da fachada)
        xs, ys = [p[0] for p in contorno], [p[1] for p in contorno]
        img, cx_r = _recorte_fachada(img, (min(xs), min(ys), max(xs), max(ys)),
                                     ctx.saida / "capa_recorte.jpg", folga=1.25)
        dx, dy = min(xs) - cx_r[0], min(ys) - cx_r[1]
        from . import imagens_laudo             # 172-3: o contorno que o avaliador desenhou/aprovou vale
        meu = imagens_laudo.contorno_do_avaliador(ctx.job, "capa", imagens_laudo.chave_capa(rel, contorno))
        img = imagens.demarcar(img, meu or [(x - dx, y - dy) for x, y in contorno],
                               ctx.saida / "capa_demarcada.png")
        X.trocar_imagem(capa, ctx.part, img, *tam)
        ctx.aviso("Confira a capa: o contorno vermelho acompanha o imóvel")      # 077-2: o avaliador confere
        return
    cx = _caixas([caixa] if caixa else [], w, h)
    if cx:
        img, caixa_r = _recorte_fachada(img, cx[0], ctx.saida / "capa_recorte.jpg")
        x0, y0, x1, y1 = caixa_r
        from . import imagens_laudo             # 174-1: o contorno do avaliador vale também no recorte pela caixa
        meu = imagens_laudo.contorno_do_avaliador(ctx.job, "capa", imagens_laudo.chave_da_caixa(rel, cx[0]))
        img = imagens.demarcar(img, meu or [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                               ctx.saida / "capa_demarcada.png")
    else:
        from . import imagens_laudo             # 172-3: sem contorno automático, vale o que o avaliador desenhou
        meu = imagens_laudo.contorno_do_avaliador(ctx.job, "capa", imagens_laudo.chave_capa(rel, None))
        if meu:
            img = imagens.demarcar(img, meu, ctx.saida / "capa_demarcada.png")
        else:
            ctx.aviso("fachada sem demarcação (caixa ausente ou inválida)")
    X.trocar_imagem(capa, ctx.part, img, *tam)


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


_TIPO_DOC = re.compile(r"\b(escritura|matr[ií]cula|iptu|certid[aã]o|contrato|habite-?se|"
                       r"alvar[aá]|planta|memorial)\b", re.I)
_DATA_CURTA = re.compile(r"^(\d{2}/\d{2}/\d{4}|\d{2}/\d{4}|\d{4}|—|-)$")


def _um_por_documento(linhas: list[list[str]]) -> list[list[str]]:
    """Item 6: uma linha por DOCUMENTO (P6 A). Linhas do mesmo tipo (ex.: as 2 fotos da
    escritura) viram uma só, "Escritura pública – 2 imagens"; a coluna de data fica curta
    (data ou "—"): texto longo nela quebrava a palavra na coluna estreita e vai para a
    observação."""
    out: list[list[str]] = []
    grupos: dict[str, int] = {}
    contagem: dict[str, int] = {}
    for doc, por, data, obs in linhas:
        if (data or "—").strip() in ("—", "-", ""):
            # 077-4: sem data, mas a observação diz o exercício/referência ("Exercício 2025", "Referência JAN/2026")
            m = re.search(r"exerc[ií]cio\s+(\d{4})|refer[eê]ncia\s+((?:jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\w*/\d{4})",
                          obs or "", re.I)
            if m:
                data = (m.group(1) or m.group(2)).upper()
        if data and not _DATA_CURTA.match(data.strip()):
            # 077-4: "referência JAN/2026", "exercício 2025", "emitida em 26/01/2026" → a data curta fica na coluna
            m = (re.search(r"\b(\d{2}/\d{2}/\d{4})\b", data) or re.search(r"\b((?:jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\w*/\d{4})\b", data, re.I)
                 or re.search(r"\b(\d{2}/\d{4})\b", data) or re.search(r"exerc[ií]cio\s+(\d{4})", data, re.I))
            if m:
                data = m.group(1).upper() if re.match(r"[a-z]", m.group(1), re.I) else m.group(1)
                if not _DATA_CURTA.match(data) and not re.match(r"^[A-Z]{3}\w*/\d{4}$", data):
                    data = "—"
        if data and not _DATA_CURTA.match(data.strip()) and not re.match(r"^[A-Z]{3}\w*/\d{4}$", data.strip()):
            obs = "; ".join(x for x in (obs if obs not in ("—", "-") else "", data) if x)
            data = "—"
        m = _TIPO_DOC.search(doc)
        k = m.group(1).casefold().replace("í", "i").replace("ã", "a") if m else None
        if k and k in grupos:
            i = grupos[k]
            contagem[k] += 1
            ant = out[i]
            if obs and obs not in ("—", "-") and obs not in ant[3]:
                ant[3] = "; ".join(x for x in (ant[3] if ant[3] not in ("—", "-") else "", obs) if x)
            if ant[2] in ("—", "-", "") and data not in ("—", "-", ""):
                ant[2] = data
            continue
        if k:
            grupos[k] = len(out)
            contagem[k] = 1
        out.append([doc, por, data or "—", obs or "—"])
    for k, i in grupos.items():
        if contagem[k] > 1:
            base = re.split(r"\s+[–(-]\s*|\s+\(", out[i][0], maxsplit=1)[0].strip()
            out[i][0] = f"{base} – {contagem[k]} imagens"
    return out


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
    linhas = _um_por_documento(linhas)
    imovel, sol = _arquivos_doc(ctx)
    if not linhas:
        linhas = [[_rotulo(ctx, r, completo=True), "Contratante", "—", "Anexo III"]
                  for r in imovel]
        if sol:
            linhas.append(["Documentos de identificação do solicitante", "Contratante", "—",
                           "Anexo IV"])
    _data_mapa_no_quadro(ctx, linhas)          # 092-6
    _data_do_proprio_documento(ctx, linhas)    # 134-3
    _anexo_real_no_quadro(ctx, linhas)         # 113-1c
    linhas = _sem_docs_pedidos(ctx, linhas)    # 117: documento que o avaliador pediu para tirar do quadro
    # 117 / D-128 (regra do Capitão): documento de identificação do solicitante (CNH, RG) não entra no quadro do
    # item 6 — ele vai só no anexo, com o nome certo
    linhas = [ln for ln in linhas if not re.search(r"(?i)\bcnh\b|carteira nacional de habilita|\brg\b|carteira de "
                                                  r"identidade|identifica[çc][ãa]o do solicitante", ln[0])]
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
    _sem_coluna_de_data(tb)


def _sem_coluna_de_data(tb) -> None:
    """136 (decisão do Capitão, regra do modelo): o quadro "Documentação analisada" sai SEM a coluna "Data / emissão";
    a largura dela vai para a coluna "Documento"."""
    trs = tb.findall(qn("w:tr"))
    if not trs:
        return
    cab = trs[0].findall(qn("w:tc"))
    k = next((i for i, tc in enumerate(cab) if re.search(r"(?i)^\s*data", X.texto(tc))), None)
    if k is None:
        return
    grade = tb.find(qn("w:tblGrid"))
    cols = grade.findall(qn("w:gridCol")) if grade is not None else []
    larg = int(cols[k].get(qn("w:w")) or 0) if len(cols) > k else 0
    if len(cols) > k:
        grade.remove(cols[k])
        if len(cols) > 1 and larg:
            cols[1].set(qn("w:w"), str(int(cols[1].get(qn("w:w")) or 0) + larg))
    for tr in trs:
        tcs = tr.findall(qn("w:tc"))
        if len(tcs) <= k:
            continue
        tr.remove(tcs[k])
        if larg and len(tcs) > 1:
            w = tcs[1].find(qn("w:tcPr") + "/" + qn("w:tcW"))
            if w is not None and (w.get(qn("w:w")) or "").isdigit():
                w.set(qn("w:w"), str(int(w.get(qn("w:w"))) + larg))


# ------------------------------------------------------------------ 117: ações de modelo pedidas pelo avaliador
def _sem_docs_pedidos(ctx: _Ctx, linhas: list[list[str]]) -> list[list[str]]:
    from . import ajustes
    fora = [_n(x) for x in ajustes.docs_fora(ctx.job) if x.strip()]
    if not fora:
        return linhas
    def _sai(rot: str) -> bool:
        r = _n(rot)
        return any(f in r or all(w in r for w in f.split()) for f in fora)
    return [ln for ln in linhas if not _sai(ln[0])]


def _titulos_pedidos(ctx: _Ctx) -> None:
    from . import ajustes
    for item, novo in ajustes.titulos(ctx.job).items():
        rx = re.compile(rf"^(\s*{re.escape(item)}\.?\s*[–-]?\s*)\S")
        for h in X.titulos(ctx):
            m = rx.match(X.texto(h))
            if m:
                X.definir(h, m.group(1) + novo.rstrip("."))
                break


def _trechos_pedidos(ctx: _Ctx) -> None:
    from . import ajustes
    trechos = [t.strip().rstrip(".;,") for t in ajustes.trechos_fora(ctx.job) if t.strip()]
    if not trechos:
        return
    raizes = [ctx.body] + [hf._element for hf in _cabecalhos(ctx)]
    for raiz in raizes:
        for p in list(raiz.iter(qn("w:p"))):
            txt = X.texto(p)
            novo = txt
            for tr in trechos:
                rx = re.compile(r"\s*[;,]?\s*" + r"\s+".join(re.escape(w) for w in tr.split()), re.I)
                novo = rx.sub("", novo)
            if novo != txt:
                novo = re.sub(r"\s*;\s*;", ";", novo).strip()
                X.definir(p, novo)


def mapa_utilizavel(caminho: Path) -> bool:
    """125-2: o print do mapa serve? Arquivo minúsculo (ex.: 5,7 KB) ou imagem quase toda de uma cor (tela cinza do
    Google Maps que não desenhou) não serve."""
    try:
        if caminho.stat().st_size < 40_000:
            return False
        from PIL import Image, ImageStat
        with Image.open(caminho) as im:
            g = im.convert("L").resize((128, 128), Image.NEAREST)    # amostra sem média (a média apaga a variação)
            return ImageStat.Stat(g).stddev[0] >= 6.0
    except Exception:
        return False


def _localizacao(ctx: _Ctx) -> None:
    leg = ctx.par("Imagem 02")
    img_p = leg.getprevious() if leg is not None else None
    # 125-2: só o maps.png (o maps_pino.png é o recorte para a IA demarcar; o contorno não vale nele) e só se servir:
    # imagem de mapa vazia/minúscula nunca entra no laudo
    mapas = [m for m in [ctx.pasta / "maps.png"] if m.exists() and mapa_utilizavel(m)]
    if (ctx.pasta / "maps.png").exists() and not mapas:
        try:                        # 130: antes de sair sem mapa, volta a última captura BOA do próprio trabalho
            from .coletor_fonte import restaurar_ultimo_bom
            if restaurar_ultimo_bom(ctx.job) and mapa_utilizavel(ctx.pasta / "maps.png"):
                mapas = [ctx.pasta / "maps.png"]
        except Exception:           # noqa: BLE001 — sem restauração, segue o aviso
            pass
    if (ctx.pasta / "maps.png").exists() and not mapas:
        ctx.aviso(f"{SEM_LOCALIZACAO}: a imagem do mapa está em branco ou incompleta")
    if img_p is not None and X.tem_imagem(img_p):
        if mapas:
            loc = db.resultado(ctx.job, "localizacao") or {}
            pol = loc.get("poligono") or []
            # só o satélite em volta do pino, sem a interface do Google Maps (P9 / 7.1)
            avisos_mapa: list[str] = []
            img, pol = imagens.recortar_mapa(mapas[0], pol if len(pol) >= 3 else [],
                                             ctx.saida / "mapa_recorte.png",
                                             proporcao=MAPA[0] / MAPA[1], avisos=avisos_mapa)
            for a in avisos_mapa:
                ctx.aviso(a)
            from . import imagens_laudo         # 172-3: o contorno que o avaliador desenhou/aprovou vale
            meu = imagens_laudo.contorno_do_avaliador(ctx.job, "mapa", imagens_laudo.chave_mapa(ctx.job))
            if meu:
                pol = meu
            if len(pol) >= 3:
                img = imagens.demarcar(img, [tuple(map(int, p)) for p in pol],
                                       ctx.saida / "mapa_demarcado.png")
            else:
                ctx.aviso("mapa sem demarcação do lote (polígono ausente)")
            X.trocar_imagem(img_p, ctx.part, img, *MAPA)
            _manter_junto(img_p)               # 098-4: a imagem de satélite anda com a legenda "Imagem 02"
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
    # D-033: cabeçalho "Descrição | Área (m²) | Fonte | Situação"
    for tc, v in zip(tb.find(qn("w:tr")).findall(qn("w:tc")),
                     ("Descrição", "Área (m²)", "Fonte", "Situação")):
        X.definir(tc.find(qn("w:p")), v)
    def situ(c: Campo) -> str:
        if c.origem == "vistoria":
            return "Vistoria"
        f = _n(_fonte(ctx, c) + " " + (c.fonte or ""))
        if "iptu" in f or "cadastr" in f:
            return "Cadastral"
        if "matricula" in f or "registro" in f:
            return "Registral"
        if "escritura" in f:
            return "Documental (escritura)"
        return "Documental"
    medida = _area_medida(ctx)
    for tr in tb.findall(qn("w:tr"))[1:]:
        tcs = tr.findall(qn("w:tc"))
        rot = _n(X.texto(tcs[0]))
        c = _campo(ctx.cs, "area", "terreno") if "terreno" in rot else _constru(ctx.cs, ctx.job)
        eh_medida = bool(medida and "terreno" not in rot and c is not None and c.nome == medida[0].nome)
        # (a fonte da medida é o texto da medição: sem procurar rótulo de "Frente.jpg")
        vals = ([_area(c), _fonte(ctx, c), situ(c)] if c and not eh_medida else
                [] if eh_medida else ["n/i", "—", "—"])
        if eh_medida:
            # ORDEM 029-4 / D-027 / D-059: área do objeto medida por satélite, a adotada no cálculo
            parte = (ctx.t.objeto_parte or "").strip()
            X.definir(tcs[0].find(qn("w:p")), f"Construída do {parte} (objeto; adotada no cálculo)"
                      if parte else "Construída do objeto (adotada no cálculo)")
            vals = [_area(c), "Medição por imagem de satélite (Google Maps) – print neste item", "Medição por satélite"]
        for tc, v in zip(tcs[1:], vals):
            X.definir(tc.find(qn("w:p")), v)
        if medida and "terreno" not in rot and c is not None and c.nome == medida[0].nome and medida[1] is not None:
            cad = copy.deepcopy(tr)   # a cadastral do lote inteiro, mostrada e NÃO usada no cálculo
            ctcs = cad.findall(qn("w:tc"))
            X.definir(ctcs[0].find(qn("w:p")), "Edificada cadastrada (lote inteiro – não usada no cálculo)")
            for tc, v in zip(ctcs[1:], [_area(medida[1]), _fonte(ctx, medida[1]), situ(medida[1])]):
                X.definir(tc.find(qn("w:p")), v)
            tr.addnext(cad)
    _linha_mapa_digital(ctx, tb)
    _prints_medicao(ctx, tb)


def _num_br(s) -> float | None:
    try:
        return float(str(s).replace(".", "").replace(",", ".")) if isinstance(s, str) else float(s)
    except (TypeError, ValueError):
        return None


def _linha_mapa_digital(ctx: _Ctx, tb) -> None:
    """077-B2 (D-055): com o Mapa Digital Fácil, a tabela de áreas ganha a linha da Prefeitura (área do desenho
    do lote), logo depois do terreno do título: "Confere com o título" ou "Divergente"."""
    _, d = mapa_digital(ctx.job)
    if re.search(r"(?i)escritura|t[ií]tulo|matr[ií]cula", str(d.get("medidas_fonte") or "")):
        return                     # 134 (decisão do Capitão 08h46): vale a escritura; "286,09 / planta" não aparece
    area = _num_br(d.get("area_planta") or d.get("area"))
    if not area:
        return
    trs = tb.findall(qn("w:tr"))[1:]
    alvo = next((tr for tr in trs if "terreno" in _n(X.texto(tr.findall(qn("w:tc"))[0]))), None)
    if alvo is None or any("mapa digital" in _n(X.texto(tr)) for tr in trs):
        return
    titulo = _num_br(re.sub(r"[^\d,.]", "", X.texto(alvo.findall(qn("w:tc"))[1]))) if len(alvo.findall(qn("w:tc"))) > 1 else None
    confere = bool(titulo and abs(titulo - area) <= max(0.5, titulo * 0.005))
    nova = copy.deepcopy(alvo)
    for tc, v in zip(nova.findall(qn("w:tc")), ("Terreno – Prefeitura (Mapa Digital Fácil)", X.num(area),
                                                 "Mapa Digital Fácil", "Confere com o título" if confere else "Divergente")):
        X.definir(tc.find(qn("w:p")), v)
    alvo.addnext(nova)


def _area_medida(ctx: _Ctx):
    """(área escolhida medida por satélite/inferida, área edificada de documento) ou None."""
    c = _constru(ctx.cs, ctx.job)
    if c is None or c.origem == "documento":
        return None
    if not re.search(r"(?i)sat[ée]lite|google|medi[dç]", f"{c.nome} {c.fonte or ''} {c.observacao or ''}"):
        return None
    doc = next((x for x in ctx.cs if eh_area_construida(x.nome) and x.origem == "documento"), None)
    return c, doc


def _prints_medicao(ctx: _Ctx, tb) -> None:
    """D-057/D-027: prints de medição por satélite entram no item de áreas, logo depois da
    tabela (não no relatório fotográfico). Usa o parágrafo-modelo de imagem do Anexo III."""
    # todos os campos: a área medida por satélite costuma ser "inferido" (fora de ctx.cs)
    campos = db.campos(ctx.job)
    prints = [r for r in sorted(escolha_laudo.prints_medicao(campos)) if ctx.arq(r) is not None]
    h = ctx.par("Anexo III – Documentação do Imóvel")
    modelo = h.getnext() if h is not None else None
    if not prints or modelo is None or not X.tem_imagem(modelo):
        return
    leg_modelo = modelo.getnext()
    ultimo = tb
    for rel in prints:
        img = copy.deepcopy(modelo)
        X.trocar_imagem(img, ctx.part, ctx.arq(rel), *FOTO)
        ultimo = X.inserir_apos(ultimo, img)
        if leg_modelo is not None and leg_modelo.tag == qn("w:p"):
            leg = copy.deepcopy(leg_modelo)
            X.definir(leg, escolha_laudo.legenda_print(rel, campos))
            ultimo = X.inserir_apos(ultimo, leg)


def mapa_digital(job_id: str) -> tuple[str | None, dict]:
    """077-1 (D-077): o print do Mapa Digital Fácil (enviado pelo avaliador ou capturado pelo Coletor) e os
    dados da consulta, se houver (evento localizacao/mapa_digital)."""
    rel = next((a["caminho"] for a in reversed(db.arquivos(job_id)) if a.get("tipo") == "mapa_digital"), None)
    dados: dict = {}
    with db._conn() as c:
        r = c.execute("SELECT dados_json, ts FROM av_events WHERE job=? AND etapa='localizacao' AND nivel='mapa_digital' "
                      "ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
    if r:
        try:
            dados = {**(json.loads(r["dados_json"] or "{}") or {}), "_ts": r["ts"]}
        except ValueError:
            dados = {}
    return rel, dados


def _legenda_mapa_digital(ctx: _Ctx) -> str:
    _, d = mapa_digital(ctx.job)
    # 078-2: a data da consulta no horário de Brasília, a mesma do carimbo da imagem
    quando = str(d.get("consultado_em") or "")
    if not quando:
        try:
            from datetime import timedelta, timezone
            quando = (datetime.fromisoformat(str(d.get("_ts") or "").replace("Z", "+00:00"))
                      .astimezone(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M"))
        except ValueError:
            pass
    end = _val(_campo(ctx.cs, "endereco")) or _endereco_partes(ctx) or f"{ctx.t.bairro}, {ctx.t.cidade}"
    partes = [f"Consulta ao Mapa Digital Fácil da Prefeitura de Goiânia{(' em ' + quando) if quando else ''}: {str(end).rstrip('.')}"]
    if d.get("quadra") or d.get("lote"):
        partes.append(", ".join(x for x in (f"quadra {d['quadra']}" if d.get("quadra") else "",
                                            f"lote {d['lote']}" if d.get("lote") else "") if x))
    escritura = bool(re.search(r"(?i)escritura|t[ií]tulo|matr[ií]cula", str(d.get("medidas_fonte") or "")))
    if escritura and d.get("area"):             # 111-1: o quadro mostra a área da escritura (o que o laudo adota)
        partes.append(f"área do lote (escritura registrada) {d['area']} m²")   # 134: sem a área da planta
    elif d.get("area_planta") or d.get("area"):
        partes.append(f"área do lote (planta) {d.get('area_planta') or d['area']} m²")
    # 117 / D-134 (regra do Capitão): a legenda do Mapa Digital Fácil não cita a área do cadastro imobiliário
    if d.get("lados"):
        partes.append("lados " + "; ".join(str(x) for x in d["lados"]))
    if d.get("medidas_fonte"):                 # 108-2: de onde vêm as medidas e a área do quadro de zoom
        mf = str(d["medidas_fonte"]).strip().rstrip(".")             # 109-1: o quadro mostra o que o laudo adota
        partes.append("medidas conforme a escritura registrada" if re.search(r"(?i)escritura|t[ií]tulo|matr[ií]cula", mf)
                      else "medidas conforme a planta da Prefeitura" if re.search(r"(?i)planta|prefeitura|divisas", mf)
                      else f"medidas conforme {mf}")
    return "; ".join(partes) + "."           # 134: sem "(anotações do avaliador)" (anotação interna)


def _rotulo(ctx: _Ctx, fonte: str, completo: bool = False) -> str:
    """Rótulo do documento dado pela extração (pelo conteúdo); nome do arquivo só em último
    caso, com aviso."""
    rel_md, _ = mapa_digital(ctx.job) if getattr(ctx, "job", None) else (None, {})
    if rel_md and fonte.replace("\\", "/").strip() == rel_md:
        return _legenda_mapa_digital(ctx)
    r = _rotulo_extraido(ctx, fonte, completo)
    if r:
        return r
    f = fonte.replace("\\", "/").strip()
    nome = re.split(r"[#;,]", PurePosixPath(f.split()[0]).name)[0] if f else ""
    if nome and nome not in ctx.sem_rotulo:
        ctx.sem_rotulo.add(nome)
        ctx.aviso(f"rótulo de documento ausente: {nome}")
    return nome


def _rotulo_extraido(ctx: _Ctx, fonte: str, completo: bool = False) -> str:
    """Rótulo dado pela extração, ou "" (sem aviso)."""
    f = fonte.replace("\\", "/").strip()
    docs = ctx.ext.get("documentos") or []
    # ORDEM 028-5: rótulo da página exata ("x.pdf#p6") primeiro; depois o do documento, também
    # quando a fonte cita uma página ("x.pdf#p12;") — antes saía o nome cru do arquivo
    for exato in (True, False):
        for d in docs:
            arq = PurePosixPath(str(d.get("arquivo", "")).replace("\\", "/")).name
            if not arq or ("#p" in arq) != exato:
                continue
            # nome inteiro: "Escritura.jpeg" não pode casar com "1-_Escritura.jpeg"
            if re.search(rf"(?:^|[/\s;,(]){re.escape(arq)}(?:$|[\s;,)#])", f):
                r = d.get("rotulo_completo" if completo else "rotulo_curto") or ""
                if r.strip():
                    return r.strip()
    return ""


def _fonte(ctx: _Ctx, c: Campo) -> str:
    if c.origem == "vistoria":
        return "Vistoria"
    if (c.fonte or "").strip().startswith("foto/") and re.search(
            r"(?i)sat[ée]lite|google|earth", f"{c.nome} {c.fonte} {c.observacao or ''}"):
        # ORDEM 030: área medida em print do Google (foto/Frente.jpg…): não é documento com rótulo
        return "medição por imagem de satélite – Google Maps"
    return _rotulo(ctx, c.fonte) or "—"


# ------------------------------------------------------------------ 7.5 fotos
def _grade_fotos(ctx: _Ctx) -> None:
    tb = ctx.tabela("Foto 01")
    if tb is None:
        return
    tit = ctx.par("7.5.")   # P9: o relatório fotográfico começa em página nova
    if tit is not None:
        identidade._ppr_set(tit, identidade._el("w:pageBreakBefore"))
    pesq = ctx.par("8. PESQUISA")   # ...e a pesquisa continua na mesma página (OV ≤ 19 págs.)
    if pesq is not None and ctx.t.modalidade == "OV":
        for e in pesq.iter(qn("w:pageBreakBefore")):
            e.getparent().remove(e)
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
                # P9: legenda 8 pt negrito no topo, respiro ~10 pt, foto centralizada
                identidade.estilo_par(ps[0], pt=8, negrito=True)
                identidade.alinhar(ps[0], "left")
                identidade.espacar(ps[0], antes=60, depois=200)
                identidade.alinhar(ps[1], "center")
                identidade.espacar(ps[1], antes=0, depois=120)
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


FRASE_MEDIDAS = ("As medidas conferidas na vistoria são compatíveis com a escritura e com o cadastro municipal.")


def _frase_medidas(ctx: _Ctx) -> None:
    """085-5 (D-055): o avaliador respondeu que mediu e que as medidas batem → a frase entra no 7.3, sempre
    (no 9121 a IA não escreveu). Sem número de trena."""
    from . import tela_trabalho
    from .agentes.redacao import NOMES
    cctx = ((tela_trabalho._cliente(ctx.job) or {}).get("contexto") or {})
    if not cctx.get("medidas_confere"):
        return
    chave = next((k for k, v in NOMES.get(ctx.t.modalidade, {}).items() if v == "areas"), None)
    if not chave:
        return
    atual = (ctx.textos.secoes.get(chave) or "").rstrip()
    if re.search(r"(?i)medidas conferidas na vistoria", atual):
        return
    ctx.textos.secoes[chave] = (atual + "\n\n" + FRASE_MEDIDAS).strip()


def _frase_itcd(ctx: _Ctx) -> None:
    """096-8 / 093-1: em laudo de ITCD, o diagnóstico cita o valor declarado, o valor de referência da SEFAZ e o valor
    médio FIPE lidos do comunicado (a redação às vezes esquece). Só com os números dos campos; nunca inventa."""
    from . import joao
    from .agentes.redacao import NOMES
    from .pendencias_simples import valor_referencia_fisco
    if not joao.eh_itcd(ctx.t.finalidade or ""):
        return
    ref = valor_referencia_fisco(ctx.job)
    if not ref:
        return

    def _v(*chaves):
        for c in ctx.cs:
            n = _n(c.nome)
            if c.valor and c.origem == "documento" and all(k in n for k in chaves):
                try:
                    return float(c.valor)
                except (TypeError, ValueError):
                    continue
        return None
    decl, fipe = _v("declarado"), _v("fipe", "valor")
    chave = next((k for k, v in NOMES.get(ctx.t.modalidade, {}).items() if v == "diagnostico"), None)         or next((k for k, v in NOMES.get(ctx.t.modalidade, {}).items() if v == "pesquisa"), None)
    if not chave:
        return
    atual = (ctx.textos.secoes.get(chave) or "").rstrip()
    ref_txt = X.brl(ref).replace("R$ ", "").replace("R$", "").strip()
    if ref_txt in atual or f"{ref:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".") in atual:
        return
    partes = []
    if decl:
        partes.append(f"o valor declarado na DITCD foi de {X.brl(decl)}")
    partes.append(f"o valor de referência da Secretaria da Economia é de {X.brl(ref)}")
    if fipe:
        partes.append(f"o valor médio de mercado da tabela FIPE consultada pela Secretaria é de {X.brl(fipe)}")
    frase = "No comunicado de malha fiscal do ITCD, " + "; ".join(partes) + "."
    ctx.textos.secoes[chave] = (atual + "\n\n" + frase).strip()


def _frase_dossie(ctx: _Ctx) -> None:
    """D-085 (ORDEM 039-4): no item da pesquisa de mercado, em toda modalidade, a frase de
    quantos anúncios foram analisados e de que os motivos dos descartes estão no dossiê."""
    from . import dossie
    from .agentes.redacao import NOMES
    chave = next((k for k, v in NOMES.get(ctx.t.modalidade, {}).items() if v == "pesquisa"), None)
    if not chave:
        return
    frase = dossie.frase_laudo(ctx.job, len(_escolhidos(ctx.sel)))
    atual = (ctx.textos.secoes.get(chave) or "").rstrip()
    if "dossiê de pesquisa" in atual:
        return
    # a contagem que a redação já escreveu ("Foram analisados N candidatos, …") dá lugar à
    # frase do dossiê (contagem feita em código, igual ao dossiê)
    # 083-B3: a redação já disse quantos foram analisados por extenso ("Foram analisados seis anúncios, que
    # constituem…"): fica só ela, nada de segunda frase
    # 083-B3 / 087: a redação já disse quantos foram analisados (por extenso ou em número): fica só a dela
    if re.search(r"(?i)foram analisad[oa]s", atual):
        return
    antiga = re.compile(r"Foram analisad[oa]s\s+\d+\s+(?:candidatos|anúncios|referenciais|imóveis)[^.]*\.")
    if antiga.search(atual):
        ctx.textos.secoes[chave] = antiga.sub(frase, atual, count=1).strip()
        return
    ctx.textos.secoes[chave] = (atual + "\n\n" + frase).strip()


def _tab_amostras(ctx: _Ctx, tb=None, refs: list | None = None, aviso: bool = True) -> None:
    if tb is None:
        for cand in ctx.body.iter(qn("w:tbl")):
            tr = cand.find(qn("w:tr"))
            if X.texto(tr).startswith("Nr") and "Foto Principal" in X.texto(tr):
                tb = cand
    if tb is None:
        return
    if refs is None:                          # 080-4: o modelo vazio fica guardado para a tabela de comparação
        ctx._modelo_amostras = copy.deepcopy(tb)
    trs = tb.findall(qn("w:tr"))
    modelo = trs[1]
    for tr in trs[1:]:
        tb.remove(tr)
    uf = "GO"
    from .agentes import fachada
    edificio = fachada.eh_edificio(ctx.t.tipo)
    condo = ""
    if edificio:
        cab = trs[0].findall(qn("w:tc"))[2]
        X.definir(cab.find(qn("w:p")), "Padrão")
        # nome do condomínio: o do trabalho ("Ed. Residencial Exemplo – Setor Exemplo …");
        # campo só se tiver nome curto ("Condomínio"/"Empreendimento"), nunca o de lazer
        nome = re.split(r"\s+[–-]\s+", ctx.t.bairro)[0]
        if not re.match(r"(?i)(ed\.|edif|condom|residencial)", nome):
            c = next((x for x in ctx.cs if _n(x.nome) in ("condominio", "empreendimento",
                                                          "nome do condominio")), None)
            nome = _val(c) if c else ""
        nome = re.sub(r"(?i)^(condom[ií]nio|edif[ií]cio|ed\.|residencial)\s+", "", nome.strip(' "'))
        condo = _n(nome.strip(' "'))
    for i, r in enumerate(_escolhidos(ctx.sel) if refs is None else refs, start=1):
        tr = copy.deepcopy(modelo)
        tcs = tr.findall(qn("w:tc"))
        X.definir(tcs[0].find(qn("w:p")), f"{i:02d}")
        ps = tcs[1].findall(qn("w:p"))
        local, desc_av = _local_manual(r)
        # 083-B1 (padrão A1): "**Localização:** Rua JC-58, Jardim Curitiba, Goiânia – GO." — a rua do campo `rua`
        rua = (r.rua or "").strip().rstrip(",.")
        try:                                  # 098-3: "Rua Jc18" → "Rua JC-18", igual ao avaliando
            from .leitura_pagina import logradouro as _logr
            rua = _logr(rua) if rua else rua
            local = _logr(local) if local else local
        except Exception:
            pass
        if not local and rua:
            local = rua
        from . import leitura_pagina as _LPb
        if local and r.bairro and not _LPb.bairro_ruim(r.bairro) and _n(r.bairro) not in _n(local):   # 087 / 092-3
            local = f"{local.rstrip(' ,.')}, {r.bairro.strip()}"
        rpr = X.rpr_base(ps[0])
        X.limpar_runs(ps[0])
        ps[0].append(X.novo_run("Localização: ", rpr, negrito=True))
        ps[0].append(X.novo_run(f"{local or ('' if _LPb.bairro_ruim(r.bairro) else r.bairro) or r.rua or ''}, {ctx.t.cidade} – {uf}."
                                .lstrip(", "), rpr, negrito=False))
        if getattr(r, "pesquisa_campo", False):     # 153-4: pesquisa de campo — sem anúncio, sem link
            dp = getattr(r, "data_pesquisa", "") or ""
            dbr = f"{dp[8:10]}/{dp[5:7]}/{dp[:4]}" if len(dp) >= 10 else dp
            inf = (getattr(r, "informante", "") or "").strip()
            X.definir(ps[1], f"Pesquisa de campo realizada pelo avaliador em {dbr}" + (f"; informante: {inf}." if inf else "."))
            X.limpar_runs(ps[2])
        else:
            X.definir(ps[1], f"Anúncio do site {r.portal.upper()} no link:")
            h = ps[2].find(qn("w:hyperlink"))
            X.apontar_hyperlink(h, ctx.part, r.link)
        desc = ((desc_av if r.fonte_coleta == "manual" and desc_av else "")
                or ctx.textos.descricao_amostras.get(r.n) or desc_av or r.descricao or "")
        from . import leitura_pagina as _LP
        if _LIXO_PORTAL.search(desc or ""):  # 092-1: trava — menu do portal nunca vai para o laudo
            desc = _LP.descricao_limpa(desc, r.titulo or "")
        if r.decisao == "comparacao":        # 092-3: no comparativo, a linha que mostra por que é padrão superior
            dest = (getattr(r, "destaque", "") or _LP.destaque(r.descricao or "", r.titulo or ""))   # 100-8
            # 104-3 / 105-3: em quê é superior ao avaliando, só com o que o anúncio traz (idade, área, itens)
            porque = []
            id_c = _idade_ref(r, " ".join(x for x in (r.descricao, dest, r.titulo) if x))
            try:
                from . import tela_trabalho as _tt
                _ia = str((((_tt._cliente(ctx.job) or {}).get("contexto") or {}).get("idade_aparente")) or "").strip()
            except Exception:
                _ia = ""
            id_av = (f"cerca de {_ia} anos" if _ia.isdigit() else _ia)
            if id_c in ("novo", "seminovo"):
                porque.append(f"construção {id_c[:-1] + 'a'}"          # 113-1a: "construção nova/seminova"
                              + (f" (o avaliando tem idade aparente de {id_av})" if id_av else ""))
            elif re.match(r"\d+", id_c or "") and _ia.isdigit() and int(re.match(r"\d+", id_c).group(0)) < int(_ia):
                porque.append(f"idade aparente de {id_c}, menor que a do avaliando ({id_av})")   # 111-2 (b)
            try:
                from .agentes.selecao import area_construida as _ac
                a_av = float(_ac(ctx.job) or 0)
            except Exception:
                a_av = 0.0
            if r.area_m2 and a_av and float(r.area_m2) > a_av * 1.1:
                porque.append(f"área construída de {X.num(r.area_m2)} m², maior que os {X.num(a_av)} m² do avaliando")
            elif r.area_m2:
                porque.append(f"área construída de {X.num(r.area_m2)} m²")
            if dest:
                itens = re.sub(r"(?i),?\s*\d+(?:[.,]\d+)?\s*m²", "", dest).strip(" ,;")
                if itens:
                    porque.append(itens)
            if porque:
                desc = f"{(r.tipologia or 'Imóvel').strip()} de padrão superior ao avaliando: " + "; ".join(porque) + "."
        desc = sem_anunciante(desc)          # 082-6: nome e CRECI de anunciante não entram no laudo
        desc = _sem_localizacao(desc)        # 090-3: a "Localização:" já está na 1ª linha da célula
        visto = _visto_em(r)
        if visto:
            desc = f"{desc.rstrip()} (anúncio visto em {visto})".strip()
        desc = desc.strip()
        desc = desc[:1].upper() + desc[1:]  # 111-2 (c): a descrição começa com maiúscula
        X.definir(ps[3], desc)
        nb = " "   # espaço inseparável: "350,00 m²" e "R$ 3.282,83" não quebram
        if edificio:   # apartamento: coluna "Padrão" no lugar da área de terreno
            mesmo = condo and condo in _n(" ".join((local or "", r.bairro or "", desc_av or "",
                                                    r.descricao or "", r.link.replace("-", " "))))
            # hífen opcional (U+00AD): a coluna é estreita e "condomínio)" sobrava ")" sozinho
            X.definir(tcs[2].find(qn("w:p")), "padrão do edifício (mesmo condo­mínio)" if mesmo
                      else (r.padrao or "n/i"))
        else:
            X.definir(tcs[2].find(qn("w:p")), f"{X.num(r.lote_m2)}{nb}m²" if r.lote_m2 else "n/i")
        X.definir(tcs[3].find(qn("w:p")), f"{X.num(r.area_m2)}{nb}m²")
        # 090-3: a idade respondida vale para a AMOSTRA; o comparativo (D-069) fica n/i até o avaliador dizer
        # 104-2: só número é idade ("excelente estado" é estado, não idade): o resto vira n/i
        idade_r = _idade_ref(r, " ".join(x for x in (r.descricao, getattr(r, "destaque", ""), r.titulo) if x))
        X.definir(tcs[4].find(qn("w:p")), idade_r or ("" if r.decisao == "comparacao" else _idade_estimada(ctx)) or "n/i")
        fps = tcs[5].findall(qn("w:p"))
        foto = ctx.arq(r.foto) or ctx.arq(r.print_)
        # D-082 (ORDEM 039-1): carimbo discreto "Acessado em dd/mm/aaaa às hh:mm" na foto;
        # sem hora registrada: pendência (nunca data inventada)
        from . import provas
        quando, _origem = provas.acesso(ctx.job, r)
        if quando is None:
            ctx.aviso(f"referencial {i:02d}: {provas.SEM_DATA} (D-082)")
        elif foto is not None and foto.suffix.lower() in _EXT_IMG:
            try:
                foto = provas.carimbar(foto, quando, ctx.saida / f"amostra-{i:02d}-acesso.jpg")
            except Exception as e:
                ctx.aviso(f"referencial {i:02d}: carimbo da data de acesso não aplicado ({e})")
        if foto is not None and foto.suffix.lower() in _EXT_IMG:
            X.trocar_imagem(fps[0], ctx.part, foto, *AMOSTRA)
        else:
            X.remover_imagens(tcs[5])
            if aviso:
                ctx.aviso(f"referencial {i:02d} sem foto principal do anúncio")
        X.definir(fps[-1], X.brl(r.preco))
        # R$/m² em 2 linhas ("R$ 3.282,83" / "/m²"): na coluna de 1,9 cm não quebra palavra
        pu = tcs[6].find(qn("w:p"))
        X.definir(pu, X.brl(_unit(r)).replace(" ", nb))
        pu2 = copy.deepcopy(pu)
        X.definir(pu2, "/m²")
        pu.addnext(pu2)
        tb.append(tr)
    _layout_amostras(tb)


def _idade_ref(r, texto: str = "") -> str:
    """111-2 (a): idade estimada pela foto e não confirmada pelo avaliador não vai para o laudo como fato (fica n/i);
    o que o anúncio diz ("casa nova") continua valendo."""
    if getattr(r, "idade_fonte", "") == "fotos":
        return idade_valida("", texto)
    return idade_valida(r.idade_aparente, texto)


def _comparacao_d069(ctx: _Ctx) -> None:
    """080-4 (D-069): imóveis de padrão superior ofertados abaixo do valor de referência do fisco, marcados pelo
    avaliador como "só comparação". Item próprio depois do tratamento dos dados, mesma tabela (foto, link, áreas,
    R$/m²), com a frase de que não integram a amostra nem o cálculo."""
    refs = [r for r in db.candidatos(ctx.job) if r.decisao == "comparacao" and r.area_m2 and r.preco]
    modelo = getattr(ctx, "_modelo_amostras", None)
    if not refs or modelo is None:
        return
    titulos = [p for p in ctx.body.iter(qn("w:p"))
               if re.match(r"^\s*\d+(?:\.\d+)*\.?\s*tratamento", X.texto(p), re.I)
               and not re.search(r"\d\s*$", X.texto(p).strip())]     # fora o sumário ("…Dados5")
    ancora = titulos[0] if titulos else None
    alvo = None
    if ancora is not None:                     # fim da seção do tratamento: antes do próximo título numerado
        e = ancora.getnext()
        while e is not None and not (e.tag == qn("w:p") and re.match(r"^\s*\d+(?:\.\d+)*\.?\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]", X.texto(e))):
            alvo, e = e, e.getnext()
    if alvo is None:
        alvo = ctx.body[-2]
    # 092-4: subitem numerado (ex.: 9.3), com o estilo do subitem anterior, e entra no sumário
    sub, e = None, alvo
    while e is not None:
        if e.tag == qn("w:p") and re.match(r"^\s*\d+\.\d+\.?\s+\S", X.texto(e)):
            sub = e
            break
        e = e.getprevious()
    # 117 / D-132 (regra do Capitão): o título não confronta o fisco — "ofertados pelo mercado por valores abaixo de
    # R$ X", com X um valor redondo (múltiplo de 50 mil) acima do mais caro da comparação
    import math
    teto = max((float(r.preco or 0) for r in refs), default=0.0)
    teto = math.floor(teto / 50_000 + 1) * 50_000 if teto else 0
    nome = ("Imóveis de padrão superior ofertados pelo mercado por valores abaixo de " + X.brl(teto) if teto
            else "Imóveis de padrão superior ofertados pelo mercado")
    if sub is not None:
        m = re.match(r"^\s*(\d+)\.(\d+)", X.texto(sub))
        tit = copy.deepcopy(sub)
        X.definir(tit, f"{m.group(1)}.{int(m.group(2)) + 1}. {nome}")
    else:
        tit = copy.deepcopy(ancora if ancora is not None else alvo)
        X.definir(tit, nome)
    frase = copy.deepcopy(alvo if alvo.tag == qn("w:p") else tit)
    um = len(refs) == 1                       # 090-3: concordância com o número
    # 113-1b: uma frase só (sem repetir "abaixo do valor de referência") e sem começar com algarismo
    qtd = {1: "um", 2: "dois", 3: "três", 4: "quatro", 5: "cinco"}.get(len(refs), str(len(refs)))
    X.definir(frase, f"{'Segue' if um else 'Seguem'} {qtd} {'imóvel' if um else 'imóveis'} de padrão superior ao avaliando, "
                     f"{'ofertado' if um else 'ofertados'} por valor abaixo do valor de referência do fisco e "
                     f"{'apresentado' if um else 'apresentados'} apenas para comparação; "
                     f"{'não integra' if um else 'não integram'} a amostra nem o cálculo.")     # 095-6 / 105-3
    tb = copy.deepcopy(modelo)
    alvo.addnext(tit); tit.addnext(frase); frase.addnext(tb)
    _tab_amostras(ctx, tb=tb, refs=refs, aviso=False)
    # 095-2: título e frase andam presos ao quadro
    _manter_junto(tit)
    _manter_junto(frase)
    # 098-1: a linha que não podia se partir sumia do PDF na virada de página (o capítulo seguinte abre página nova):
    # no quadro da comparação as linhas podem continuar na página seguinte
    for tr in tb.findall(qn("w:tr"))[1:]:
        trpr = tr.find(qn("w:trPr"))
        if trpr is not None:
            for cs in trpr.findall(qn("w:cantSplit")):
                trpr.remove(cs)


# D-031: colunas Nr 1,0 | Descrição 6,7 | Terreno 1,6 | Construída 1,7 | Idade 1,5 |
# Foto 4,4 | R$/m² 1,9 cm = 18,8 cm, centralizada na FOLHA (margens 2,5/2,0 → recuo −1,4 cm)
_COLS_AMOSTRAS_CM = (1.0, 6.7, 1.6, 1.7, 1.5, 4.4, 1.9)
_CM = 567  # twips


def _layout_amostras(tb) -> None:
    from docx.oxml import OxmlElement
    larg = [int(round(c * _CM)) for c in _COLS_AMOSTRAS_CM]
    tblpr = tb.find(qn("w:tblPr"))
    for tag in ("w:tblW", "w:jc", "w:tblInd"):
        for e in tblpr.findall(qn(tag)):
            tblpr.remove(e)
    tw = OxmlElement("w:tblW")
    tw.set(qn("w:w"), str(sum(larg)))
    tw.set(qn("w:type"), "dxa")
    # folha 21 cm, tabela 18,8 → começa a 1,1 cm da borda; margem esquerda 2,5 → recuo −1,4 cm
    ind = OxmlElement("w:tblInd")
    ind.set(qn("w:w"), str(int(round((1.1 - 2.5) * _CM))))
    ind.set(qn("w:type"), "dxa")
    estilo = tblpr.find(qn("w:tblStyle"))
    (estilo if estilo is not None else tblpr[0]).addnext(tw)
    tw.addnext(ind)
    # margem interna de 0,08 cm: "R$ 3.282,83" e "350,00 m²" cabem numa linha nas colunas
    # estreitas sem quebrar o número
    for e in tblpr.findall(qn("w:tblCellMar")):
        tblpr.remove(e)
    mar = OxmlElement("w:tblCellMar")
    for lado, v in (("top", 40), ("left", 45), ("bottom", 40), ("right", 45)):
        m = OxmlElement(f"w:{lado}")
        m.set(qn("w:w"), str(v))
        m.set(qn("w:type"), "dxa")
        mar.append(m)
    look = tblpr.find(qn("w:tblLook"))
    (look.addprevious(mar) if look is not None else tblpr.append(mar))
    grid = tb.find(qn("w:tblGrid"))
    for g, w in zip(grid.findall(qn("w:gridCol")), larg):
        g.set(qn("w:w"), str(w))
    for k, tr in enumerate(tb.findall(qn("w:tr"))):
        for tc, w in zip(tr.findall(qn("w:tc")), larg):
            tcpr = tc.find(qn("w:tcPr"))
            tcw = tcpr.find(qn("w:tcW"))
            tcw.set(qn("w:w"), str(w))
            tcw.set(qn("w:type"), "dxa")
            va = tcpr.find(qn("w:vAlign"))
            if va is not None:
                va.set(qn("w:val"), "center" if k == 0 else "top")
            for j, p in enumerate(tc.findall(qn("w:p"))):
                tcs_ = tr.findall(qn("w:tc"))
                foto_valor = j > 0 and tc is tcs_[5]
                tam = 10 if (k > 0 and foto_valor) else (8 if (k > 0 and tc is tcs_[0]) else 7)
                identidade.estilo_par(p, pt=tam)
                for h in p.iter(qn("w:hyperlink")):
                    for r in h.iter(qn("w:r")):
                        identidade.estilo_run(r, pt=7)
        if k > 0:
            ps = tr.findall(qn("w:tc"))[1].findall(qn("w:p"))
            for p in ps[:1] + ps[2:3]:          # "linha em branco" após localização e link
                identidade.espacar(p, depois=160)
            if len(ps) > 3:
                identidade.alinhar(ps[3], "both")


_ANUNCIANTE = re.compile(r"(?i)\b(?:anunciante|corretora?|imobili[áa]ria|creci)\b")
_FIM_FRASE = re.compile(r"(?<=[.;!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])")


_LIXO_PORTAL = re.compile(r"(?i)pular para o conte[uú]do|criar conta|\bentrar\b|simular|favorite|alugar comprar|"
                          r"lan[cç]amentos|anuncie|baixe o app")


_NOVO_IDADE = re.compile(r"(?i)\b(?:casa|im[oó]vel|sobrado|constru[cç][aã]o) nov[oa]\b(?!\s*\?)|rec[eé]m[- ]constru|nunca habitad|"
                         r"primeira loca[cç][aã]o|na planta|entrega recente|\bnov[oa] em folha\b")
_SEMINOVO = re.compile(r"(?i)\bsemi[- ]?nov[oa]\b")


def idade_valida(v: str | None, texto: str = "") -> str:
    """105-2: idade aparente é número de anos, ou "novo"/"seminovo" (o anúncio diz). Estado ("excelente", "bom",
    "reformado") nunca é idade. Sem idade escrita, o texto do anúncio ("casa nova", "nunca habitada") vale."""
    v = (v or "").strip()
    if re.search(r"\d", v):
        return v
    if _SEMINOVO.search(v) or (not v and _SEMINOVO.search(texto or "")):
        return "seminovo"
    if re.search(r"(?i)\bnov[oa]\b", v) or _NOVO_IDADE.search(v) or _NOVO_IDADE.search(texto or ""):
        return "novo"
    return ""


def _sem_localizacao(desc: str) -> str:
    frases = [f for f in _FIM_FRASE.split((desc or "").strip()) if f and not re.match(r"(?i)\s*localiza[cç][aã]o\s*:", f)]
    return " ".join(frases).strip()


def sem_anunciante(desc: str) -> str:
    """082-6: tira a frase com nome/CRECI de quem anunciou ("Anunciante: Lidiane Ventura (CRECI 11.991).")."""
    frases = [f for f in _FIM_FRASE.split((desc or "").strip()) if f and not _ANUNCIANTE.search(f)]
    return " ".join(frases).strip()


def _local_manual(r: Referencial) -> tuple[str, str]:
    """(localização, descrição) do referencial cadastrado à mão: a tela grava
    "Localização: <rua, nº – bairro>. <descrição>" em `descricao`."""
    d = r.descricao or ""
    if not d.startswith("Localização:"):
        return "", d.strip()
    corpo = d[len("Localização:"):].lstrip()
    # ORDEM 035: o fim da localização é o 1º ". " que NÃO é de abreviação ("Av. Antônio…" saía "Av,")
    for m in re.finditer(r"\.\s+", corpo):
        antes = re.search(r"(\S+)$", corpo[:m.start()])
        if antes and (len(antes.group(1)) == 1 or re.fullmatch(r"(?i)(av|r|al|rod|pç|pc|qd|qda|lt|st|dr|prof|ed|n[º°o]|km|br|go)", antes.group(1))):
            continue
        return corpo[:m.start()].strip(), corpo[m.end():].strip()
    return "", d.strip()


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
    if p is not None:                 # 106 (D-068, regra do projeto): sem CV nem desvio no laudo, em todo trabalho
        # 074-F3: o avaliador pediu a conta do coeficiente só na planilha — a frase e a linha saem do laudo
        p.getparent().remove(p)
        p = None
        if tb is not None:
            for tr in tb.findall(qn("w:tr"))[1:]:
                if re.match(r"(?i)coeficiente|desvio", X.texto(tr).strip()):   # 078-9: o desvio segue a decisão do CV
                    tb.remove(tr)
    if p is not None:
        if len(us) < 3:
            # com 1 referencial o desvio é 0 e o laudo afirmava "baixa dispersão"
            X.definir(p, f"A amostra conta com {pl(len(us), 'referencial', 'referenciais')}, quantidade "
                         "insuficiente para medir a dispersão dos valores unitários.")
        else:
            grau = "baixa" if cv <= 15 else ("moderada" if cv <= 30 else "elevada")
            X.definir(p, f"A amostra apresentou coeficiente de variação de {X.num(cv)}%, "
                         f"indicando {grau} dispersão dos valores unitários.")
    if t.modalidade == "OV" and tb is not None:
        # D-039: OV só nº, mínimo, máximo e média — tira as linhas de dispersão se houver
        for tr in tb.findall(qn("w:tr"))[1:]:
            if re.match(r"(?i)mediana|desvio|coeficiente", X.texto(tr).strip()):
                tb.remove(tr)
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
    p = ctx.par("Arredondando-se o resultado")
    if p is not None and r.valor_calculado == r.valor_adotado:
        # sem arredondamento de fato, a frase afirmaria algo que não ocorreu
        X.definir(p, "Conclui-se, assim, que o valor de mercado do imóvel avaliado, na data "
                     "de referência desta Opinião de Valor, é de:"
                  if t.modalidade == "OV" else
                  "Conclui-se, assim, que o valor de mercado do imóvel avaliado, na data de "
                  "referência desta avaliação, é de:")
    # resumo: mesmo conteúdo do 7.4 (redação) — nada de "n/i" se o 7.4 tem o dado
    cs = ctx.cs
    d74 = {X.norm(k): v.strip().rstrip(".") for k, v in
           X.linhas_rotulo(ctx.textos.secoes.get("7.4") or "").items()}

    def _do74(*chaves: str) -> str:
        for k, v in d74.items():
            if all(c in k for c in chaves):
                return v
        return ""
    terreno, constru = _campo(cs, "area", "terreno"), _constru(cs, ctx.job)
    padrao = _do74("padrao") or _val(_campo(cs, "padrao"))
    padrao = re.split(r"[;.]", padrao)[0].strip()
    estado = _do74("conservacao") or _val(_campo(cs, "conservacao"))
    idade = _do74("idade") or _val(_campo(cs, "idade"))
    if estado and idade and X.norm(idade) in X.norm(estado):
        idade = ""          # "Idade aparente e estado de conservação" já traz os dois
    idade = re.sub(r"(?i)^idade aparente( de)?\s*", "", idade).strip()
    benf = _do74("benfeitoria") or _val(_campo(cs, "benfeitoria"))
    estado, benf = (s[:1].upper() + s[1:] if s else s for s in (estado, benf))
    tb = ctx.tabela("Elemento")
    if tb is not None:
        _tab_label(tb, {
            "Imóvel": _imovel(ctx).split(" – ", 1)[-1]
                      + (f" Objeto da avaliação: {ctx.t.objeto_parte.strip()} (parte do imóvel)."
                         if (ctx.t.objeto_parte or "").strip() else ""),
            "Área do terreno": f"{_area(terreno)} m² ({_fonte(ctx, terreno)})" if terreno else "n/i",
            "Área construída adotada": f"{X.num(area)} m²"
                                       + (f" ({_fonte(ctx, constru)})" if constru else ""),
            "Tipologia / padrão": f"{t.tipo} / {(padrao or 'n/i').lower()}",
            "Estado de conservação": (estado or "n/i")
                                     + (f" – idade aparente {idade}" if idade else ""),
            "Principais benfeitorias": benf or "n/i",
            "Valor unitário médio": f"{X.brl(r.media)}/m²",
            "Valor unitário adotado": f"{X.brl(r.unitario_adotado)}/m²",
            "VALOR DE MERCADO DO IMÓVEL": X.brl(r.valor_adotado),
            "Faixa de variação": f"±{f}% – {X.brl(r.valor_min)} a {X.brl(r.valor_max)}",
            "Data-base": t.data_vistoria.strftime("%d/%m/%Y"),
        })
        X.subst(tb, "Data-base da avaliação", "Data da vistoria")   # 125-3: o rótulo inteiro
        X.subst(tb, "Data-base", "Data da vistoria")         # 117 / D-127
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
        cidade = "Goiânia"
        if identidade._AV_LAUDO != "AV-0001":       # ORDEM 043: "[Cidade], [data]" do avaliador
            from . import avaliadores
            cidade = ((avaliadores.obter(identidade._AV_LAUDO) or {}).get("dados", {}).get("cidade") or t.cidade)
            cidade = re.sub(r"\bGoiania\b", "Goiânia", cidade)      # L200 (Caso M): cadastro sem acento
        X.definir(p, f"{cidade}, {X.data_extenso(t.data_emissao or date.today())}.")


# ------------------------------------------------------------------ AMJ / perito
def _avaliador() -> dict:
    if identidade._AV_LAUDO != "AV-0001":          # ORDEM 042: dados do avaliador dono do laudo
        from . import avaliadores
        return {k: v for k, v in avaliadores.identidade_avaliador(identidade._AV_LAUDO).items() if v}
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
    def _novo(trecho: str) -> bool:
        """Trecho que só repete o registro já dito no início (CRECI/CNAI) sai (P6 D)."""
        nums = re.findall(r"\d{4,}", trecho)
        return not nums or not all(n in base for n in nums)

    partes = [x.strip() for x in re.split(r";|\n", av.get("qualificacao", "") or "") if x.strip()]
    qualif = "; ".join(x for x in partes if _novo(x))
    extra = " ".join(x.rstrip(".") + "." for x in (av.get("formacao", ""), qualif) if x)
    if not av.get("qualificacao") and t.modalidade == "AMJ":
        ctx.aviso(PERITO_SEM_QUALIFICACAO)
    X.definir(p, f"{base} {extra}".strip())


# ------------------------------------------------------------------ anexos
def _quebras_dos_anexos(ctx: _Ctx) -> None:
    """ORDEM 029-3 / 031-2: título de anexo nunca fica sozinho no fim da página. Anexo só de
    texto (currículo, "não apresentados") que cabe numa página fica INTEIRO: segue na mesma
    página se couber; senão vai todo para a seguinte (título + linhas presos uns aos outros).
    Anexo com documento/tabela continua em página própria."""
    corpo = list(ctx.body)
    fim_re = re.compile(r"^(?:Anexo |(?:\d+\.\s*)?SUMÁRIO)")
    for i, el in enumerate(corpo):
        if el.tag != qn("w:p") or not X.texto(el).strip().startswith("Anexo "):
            continue
        ppr = el.find(qn("w:pPr"))
        if ppr is None:
            continue
        if ppr.find(qn("w:keepNext")) is None:
            ppr.append(identidade._el("w:keepNext"))
        bloco = []
        for nxt in corpo[i + 1:]:
            if nxt.tag == qn("w:sectPr"):
                break
            if nxt.tag == qn("w:p") and (fim_re.match(X.texto(nxt).strip())
                                          or nxt.find(f".//{qn('w:pageBreakBefore')}") is not None
                                          or nxt.find(f".//{qn('w:br')}[@{qn('w:type')}='page']") is not None):
                break
            bloco.append(nxt)
        tem_imagem = any(X.tem_imagem(b) for b in bloco) or any(b.tag == qn("w:tbl") for b in bloco)
        cabe = sum(len(X.texto(b)) for b in bloco) < ANEXO_TEXTO_CABE
        if tem_imagem or not cabe:
            continue
        for e in list(el.iter(qn("w:pageBreakBefore"))):
            e.getparent().remove(e)
        ps = [b for b in bloco if b.tag == qn("w:p")]
        for b in ps[:-1]:     # tudo preso ao seguinte: o bloco não se parte
            bp = b.find(qn("w:pPr"))
            if bp is None:
                bp = identidade._el("w:pPr")
                b.insert(0, bp)
            if bp.find(qn("w:keepNext")) is None:
                bp.append(identidade._el("w:keepNext"))
            if bp.find(qn("w:keepLines")) is None:
                bp.append(identidade._el("w:keepLines"))


ANEXO_TEXTO_CABE = 1800   # caracteres de texto que cabem com folga numa página


def _doc_pj_sem_pessoa(ctx: _Ctx, rel: str) -> bool:
    """Cartão CNPJ / contrato social: documento de PJ; com CPF/RG/CNH de pessoa, continua
    exigindo tarja (a extração marca caixas nesses números)."""
    # rótulo sem aviso: aqui só se consulta (o aviso sai quando o documento é anexado)
    rot = f"{rel} {_rotulo_extraido(ctx, rel)} {_rotulo_extraido(ctx, rel, completo=True)}"
    if not _PJ_DOC.search(rot) or _PESSOA_DOC.search(rot):
        return False
    tj = ctx.ext.get("tarjas") or {}
    return not any(k == rel or k.startswith(rel + "#p") for k in tj if tj.get(k))


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
            # D-057: só as páginas que importam; o resto fica citado em "Documentação analisada"
            fontes = [(c.nome, c.fonte or "") for c in ctx.cs if c.origem == "documento"]
            sel = escolha_laudo.paginas_anexo(rel, len(pags), fontes, ctx.ext.get("documentos") or [])
            if len(sel) < len(pags):
                db.evento(ctx.job, "montagem", "info",
                          f"anexo de {PurePosixPath(rel).name}: {len(sel)} de {len(pags)} páginas "
                          f"({', '.join(map(str, sel))}); as demais ficam citadas na documentação analisada")
            return [pags[i - 1] for i in sel]
        # caixas da extração em pontos PDF (1/72 pol.) -> pixels do PNG renderizado
        return [_tarjada(ctx, rel, pg, _caixas_brutas(ctx, rel, i), DPI_ANEXO / 72,
                         pasta / f"{pg.stem}-tarjada.png", chave=f"{rel}#p{i}")
                for i, pg in enumerate(pags, start=1)]
    if p.suffix.lower() in _EXT_IMG:
        img = _tarjada(ctx, rel, p) if tarjar else p
        graus = _rotacao(ctx, rel)
        if graus:   # documento fotografado deitado: anexo em posição de leitura
            img = imagens.girar(img, graus, ctx.saida / "anexos" / f"{p.stem}-girado.png")
        return [img]
    return []


def _rotacao(ctx: _Ctx, rel: str) -> int:
    nome = PurePosixPath(rel).name
    for d in ctx.ext.get("documentos") or []:
        if PurePosixPath(str(d.get("arquivo", "")).replace("\\", "/")).name == nome:
            try:
                return int(d.get("rotacao") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _grade_anexo(ctx: _Ctx, imgs: list[Path]):
    """Tabela 2 colunas (cópia da grade de fotos, sem as legendas) com as páginas do documento."""
    modelo = ctx.tabela("Foto 01")
    if modelo is None or len(imgs) < 2:
        return None
    tb = copy.deepcopy(modelo)
    tb.set("jdb", "grade")   # identidade.tabelas não pinta a 1ª linha como cabeçalho
    tpr = tb.find(qn("w:tblPr"))
    if tpr is not None:   # sem o "cabeçalho" do estilo da tabela (pintava a 1ª linha)
        for look in tpr.findall(qn("w:tblLook")):
            look.set(qn("w:firstRow"), "0")
            look.set(qn("w:val"), "0000")
        for shd in list(tpr.iter(qn("w:shd"))):
            shd.getparent().remove(shd)
        for st in tpr.findall(qn("w:tblStyle")):      # sem estilo: só as imagens lado a lado
            tpr.remove(st)
    for cnf in list(tb.iter(qn("w:cnfStyle"))):
        cnf.getparent().remove(cnf)
    trs = tb.findall(qn("w:tr"))
    # linha-modelo: uma linha comum de 2 fotos (a 1ª pode ser o título "Relatório fotográfico",
    # célula única azul-marinho repetida como cabeçalho)
    comuns = [tr for tr in trs if len(tr.findall(qn("w:tc"))) == 2 and tr.find(f".//{qn('w:gridSpan')}") is None]
    if not comuns:
        return None
    tr0 = comuns[0]
    for trpr in tr0.findall(qn("w:trPr")):
        for th in trpr.findall(qn("w:tblHeader")):
            trpr.remove(th)
    for tr in trs:
        tb.remove(tr)
    for i in range(0, len(imgs), 2):
        tr = copy.deepcopy(tr0)
        for j, tc in enumerate(tr.findall(qn("w:tc"))):
            for shd in list(tc.iter(qn("w:shd"))):     # sem fundo de célula (o da grade de fotos)
                shd.getparent().remove(shd)
            ps = tc.findall(qn("w:p"))
            if len(ps) >= 2:
                X.remover(ps[0])              # sem legenda por imagem (como o Alan)
                alvo = ps[1]
            else:
                alvo = ps[0]
            if i + j < len(imgs):
                X.trocar_imagem(alvo, ctx.part, imgs[i + j], *ANEXO_GRADE)
                identidade.alinhar(alvo, "center")
                identidade.espacar(alvo, antes=0, depois=60)
            else:
                X.remover_imagens(tc)
        tb.append(tr)
    return tb


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
    num = _numero_do_anexo(titulo)
    for k, rel in enumerate(dict.fromkeys(r for r, _ in paginas), start=1):
        ims = [im for r, im in paginas if r == rel]
        if legenda_padrao is None and num:
            # 117 / D-133 (regra do Capitão): cada documento do anexo com divisão, título e número que entram no
            # sumário — "3.1 – Escritura", linha divisória, "3.2 – …"
            if k > 1:
                ultimo = X.inserir_apos(ultimo, _divisor(leg_p))
            nome_doc = ("Mapa Digital Fácil – Prefeitura de Goiânia" if rel == mapa_digital(ctx.job)[0]
                        else _rotulo(ctx, rel, completo=False))       # 134: o título do 3.3 não repete a legenda
            ultimo = X.inserir_apos(ultimo, _subtitulo_anexo(leg_p, f"{num}.{k} – {nome_doc}",
                                                             f"sec_anx{num}_{k}", 8000 + num * 100 + k))
        grade = _grade_anexo(ctx, ims) if legenda_padrao is None else None
        if grade is not None:
            # ORDEM 029-1: o nome do documento uma vez e as páginas em grade 2 × 2
            leg = copy.deepcopy(leg_p)
            X.definir(leg, _rotulo(ctx, rel, completo=True))
            ppr = leg.find(qn("w:pPr"))
            if ppr is not None:
                ppr.append(identidade._el("w:keepNext"))
            ultimo = X.inserir_apos(ultimo, leg)
            ultimo = X.inserir_apos(ultimo, grade)
            continue
        for im in ims:
            if legenda_padrao is None:
                # 078-1 / 083-B4: a legenda SEMPRE em cima do documento (como na grade), colada nele (keepNext):
                # nunca embaixo de um e em cima do outro, nunca sozinha no pé da página
                leg = copy.deepcopy(leg_p)
                X.definir(leg, _rotulo(ctx, rel, completo=True))
                ppr = leg.find(qn("w:pPr"))
                if ppr is None:
                    ppr = identidade._el("w:pPr")
                    leg.insert(0, ppr)
                if ppr.find(qn("w:keepNext")) is None:
                    ppr.append(identidade._el("w:keepNext"))
                ultimo = X.inserir_apos(ultimo, leg)
            novo = copy.deepcopy(img_p)
            X.trocar_imagem(novo, ctx.part, im, *ANEXO)
            ultimo = X.inserir_apos(ultimo, novo)
    X.remover(img_p)
    if legenda_padrao is None:
        X.remover(leg_p)


_ROMANO = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}


def _numero_do_anexo(titulo: str) -> int:
    m = re.match(r"\s*Anexo\s+([IVX]+|\d+)\b", titulo or "")
    if not m:
        return 0
    return int(m.group(1)) if m.group(1).isdigit() else _ROMANO.get(m.group(1), 0)


def _subtitulo_anexo(modelo, texto: str, marcador: str, ident: int):
    """D-133: subtítulo numerado do documento no anexo (negrito, preso ao documento, com marcador para o sumário)."""
    p = copy.deepcopy(modelo)
    X.definir(p, texto)
    for r in p.iter(qn("w:r")):
        rpr = r.find(qn("w:rPr"))
        if rpr is None:
            rpr = identidade._el("w:rPr"); r.insert(0, rpr)
        if rpr.find(qn("w:b")) is None:
            rpr.insert(0, identidade._el("w:b"))
    _manter_junto(p)
    ini, fim = identidade._el("w:bookmarkStart"), identidade._el("w:bookmarkEnd")
    ini.set(qn("w:id"), str(ident)); ini.set(qn("w:name"), marcador); fim.set(qn("w:id"), str(ident))
    ppr = p.find(qn("w:pPr"))
    pos = (list(p).index(ppr) + 1) if ppr is not None else 0
    p.insert(pos, ini)
    p.append(fim)
    return p


def _divisor(modelo):
    """D-133: a linha que separa um documento do outro no anexo."""
    p = copy.deepcopy(modelo)
    X.definir(p, "")
    ppr = p.find(qn("w:pPr"))
    if ppr is None:
        ppr = identidade._el("w:pPr"); p.insert(0, ppr)
    for e in ppr.findall(qn("w:keepNext")):
        ppr.remove(e)
    bdr = identidade._el("w:pBdr")
    baixo = identidade._el("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", "8"), ("w:space", "6"), ("w:color", "C9A227")):
        baixo.set(qn(k), v)
    bdr.append(baixo)
    ppr.append(bdr)
    return p


MAPA_FACIL_URL = "https://portalmapa.goiania.go.gov.br/mapafacil/"


def _links_mapa_digital(ctx: _Ctx, rel: str, d: dict) -> None:
    """Link clicável abaixo da imagem do Mapa Digital Fácil: só o do site (108-1, sem a fonte dos dados)."""
    leg = next((p for p in ctx.body.iter(qn("w:p")) if X.texto(p).startswith("Consulta ao Mapa Digital Fácil")), None)
    if leg is None:
        return
    rpr_leg = leg
    prox = leg.getnext()                      # 098-4: legenda em cima (078-1) → os links vão depois da IMAGEM,
    if prox is not None and prox.tag == qn("w:p") and X.tem_imagem(prox):   # nunca entre a legenda e a figura
        leg = prox
    _manter_junto(rpr_leg)                    # 113-1d: legenda, imagem e link do Mapa Digital na mesma página
    if leg is not rpr_leg:
        _manter_junto(leg)
    # 108-1: só o link do site, sempre; a "Fonte dos dados do lote" (servidor de mapas) nunca vai para o laudo
    url = str(d.get("url") or db.setting("mapa_digital_url") or "")
    if not url or "servicogyn" in url or "/rest/services" in url:
        url = MAPA_FACIL_URL
    for rot, url in (("Mapa Digital Fácil – Prefeitura de Goiânia", url),):
        p = copy.deepcopy(rpr_leg)
        for r in list(p):
            if r.tag != qn("w:pPr"):
                p.remove(r)
        from docx.oxml import OxmlElement
        rpr0 = rpr_leg.find(".//" + qn("w:rPr"))        # 078-2: mesma letra da legenda, com espaço depois dos dois-pontos
        run = OxmlElement("w:r")
        if rpr0 is not None:
            run.append(copy.deepcopy(rpr0))
        tx = OxmlElement("w:t"); tx.text = f"{rot}: "; tx.set(qn("xml:space"), "preserve"); run.append(tx); p.append(run)
        p.append(X.novo_hyperlink(ctx.part, url, url, rpr0))
        leg = X.inserir_apos(leg, p)


_FIXAS = [
    (re.compile(r"\bPTAM\s+PTAM\b"), lambda m: "PTAM"),     # 095-3: sigla dobrada no item 2
    (_SIGLA_RUA, lambda m: ""),               # 093-A-9: a sigla do cadastro da Prefeitura não vai para o laudo
    (re.compile(r"\b([Aa]) presente parecer\b"), lambda m: ("O" if m.group(1) == "A" else "o") + " presente parecer"),
    (re.compile(r"\bCEP[-‐–]SIND(?:I)?M[OÓ]VEIS(?:/GO)?\b", re.I), lambda m: "CEP-SINDIMÓVEIS/GO"),
    # 134: a área do lote é a da escritura (decisão do Capitão) — sem "confirmada pela planta … (286,09 m²)"
    (re.compile(r"(?i),?\s*confirmad[oa] pela planta do lote no Mapa Digital F[áa]cil[^.;()]*\(\s*\d+(?:[.,]\d+)?\s*m²\s*\)"),
     lambda m: ""),
    (re.compile(r"(?i)[ ]?Área do lote \(planta do Mapa Digital F[áa]cil[^)]*\):\s*\d+(?:[.,]\d+)?\s*m²[^.]*\."),
     lambda m: ""),
    # 125-3 / D-127: nenhuma "data-base" no laudo — a data de referência é a da vistoria
    (re.compile(r"(?i)\bData da vistoria da avalia[çc][ãa]o\b"), lambda m: "Data da vistoria"),
    (re.compile(r"(?i)\bdata[- ]base da avalia[çc][ãa]o\b"), lambda m: "data da vistoria"),
    (re.compile(r"\bdata[- ]base indicada\b"), lambda m: "data da vistoria"),
    (re.compile(r"\bData[- ]base indicada\b"), lambda m: "Data da vistoria"),
    (re.compile(r"\bdata[- ]base\b"), lambda m: "data da vistoria"),
    (re.compile(r"\bData[- ]base\b"), lambda m: "Data da vistoria"),
    # 113-4: a idade dos referenciais sai sem dizer como foi estimada
    (re.compile(r"(?i),\s*(?:estimad[ao]s?|inferid[ao]s?)\s+(?:a partir\s+)?(?:pel[ao]s|d[ao]s)\s+fotografias?"
                r"(?:\s+d[oe]s?\s+an[uú]ncios?)?(?:\s*\(D-071\))?"), lambda m: ""),
]
_CV_PALAVRAS = re.compile(r"(?i)medida estatística da dispersão|coeficiente de variação|\bcoeficiente\b|desvio[- ]padrão|"
                          r"limite de \d+ ?% adotado|sem (?:ele|o referencial \d+)[^.;]*a média seria|\bdispers\w*|"
                          r"\bespalha\w*|variabilidade|amplitude dos valores|discrep\w* entre|"
                          r"heterog[eê]ne\w*[^.;]*(?:valor|unit[aá]ri|amostr|referenc|oferta)|"
                          r"(?:valor|unit[aá]ri|amostr|referenc|oferta)[^.;]*heterog[eê]ne\w*")   # 106-1/3: o assunto inteiro


class _FraseCV:
    """101-1 (e): com a conta da dispersão só na planilha (D-068), a FRASE inteira que fala de coeficiente, desvio,
    'sem o referencial X a média seria…' ou limite interno sai — o corte é por frase (o ponto do milhar não corta)."""
    @staticmethod
    def search(txt: str):
        return any(_CV_PALAVRAS.search(f) for f in _FIM_FRASE.split(txt or ""))

    @staticmethod
    def sub(_rep: str, txt: str) -> str:
        out = []
        for f in _FIM_FRASE.split((txt or "").strip()):
            # 106-1: "Considerando essa dispersão, admite-se faixa…" → "Admite-se faixa…" (a faixa fica, o motivo sai)
            g = re.sub(r"(?i)^\s*(?:considerando|diante d|em raz[aã]o d)[^,]*dispers\w*[^,]*,\s*", "", f)
            if g != f and g:
                g = g[:1].upper() + g[1:]
            if not _CV_PALAVRAS.search(g):
                out.append(g)
        return " ".join(out).strip()


_FRASE_CV = _FraseCV()


def _idade_estimada(ctx: _Ctx) -> str:
    """078-7 (D-071): a idade aparente que o avaliador respondeu no portão vale para os referenciais sem idade."""
    from . import tela_trabalho
    v = ((tela_trabalho._cliente(ctx.job) or {}).get("contexto") or {}).get("idade_aparente") or ""
    return f"{v} anos (estimada)" if str(v).isdigit() else str(v)


def _bairro_completo(ctx: _Ctx) -> tuple[re.Pattern, str] | None:
    """125-3 / D-131: o bairro com o nome completo do documento ("Jardim Curitiba I") em todo o laudo — capa,
    legendas e textos que vieram do endereço do documento ainda com "Jardim Curitiba"."""
    b = (ctx.t.bairro or "").strip()
    m = re.match(r"^(.+?)\s+([IVX]+|\d+)$", b)
    if not m:
        return None
    base = m.group(1)
    return re.compile(r"(?<![\w-])" + re.escape(base) + r"(?!\s*(?:[IVX]+|\d+)\b)(?![\w-])"), b


def _grafia_rua(ctx: _Ctx) -> tuple[re.Pattern, str] | None:
    """078-12: a grafia do logradouro no documento do imóvel ("Rua XV 9") vale no laudo inteiro ("Rua XV-9" → "Rua XV 9")."""
    from . import tela_trabalho
    end = ((tela_trabalho._cliente(ctx.job) or {}).get("contexto") or {}).get("imovel_endereco") or ""
    m = re.match(r"\s*((?:Rua|Avenida|Av\.|Alameda|Travessa)\s+[A-Z]{1,4})[\s.-]*(\d+)\b", end)
    if not m:
        return None
    tipo, letras = m.group(1).split()[0], m.group(1).split()[-1]
    return re.compile(rf"\b{re.escape(tipo)}\s+{re.escape(letras)}[\s.-]*{m.group(2)}\b"), f"{tipo} {letras} {m.group(2)}"


def _correcoes_fixas(ctx: _Ctx) -> None:
    """077-A4: concordância e grafias que são erro do sistema (corrigidas sem perguntar); com a decisão do CV
    (D-068), a frase da dispersão sai do texto também."""
    cv_fora = True                 # 106 (D-068, regra do projeto): o assunto dispersão nunca vai ao laudo, em todo trabalho
    rua = _grafia_rua(ctx)
    bairro = _bairro_completo(ctx)
    # 132-3: "na data de referência deste parecer/laudo" → "na data da vistoria (dd/mm/aaaa)" (a definição da norma fica)
    vist = ctx.t.data_vistoria.strftime("%d/%m/%Y")
    ref_parecer = re.compile(r"(?i)\bna data de refer[êe]ncia (?:deste|do presente) (?:parecer|laudo|PTAM)\b")
    from . import ajustes as _aj
    trocas_av = [tuple(x) for x in _aj.trocas(ctx.job) if isinstance(x, list) and len(x) == 2]
    # 126-3b: o nome completo vale para o AVALIANDO; os referenciais (células com "Anúncio do site"/"Localização:")
    # continuam como o anúncio diz
    de_referencial = {p for tc in ctx.body.iter(qn("w:tc"))
                      if re.search(r"Anúncio do site|Localização:", X.texto(tc)) for p in tc.iter(qn("w:p"))}
    for p in list(ctx.body.iter(qn("w:p"))):
        bairro_aqui = bairro if p not in de_referencial else None
        for r in p.iter(qn("w:t")):
            v = r.text or ""
            for rx, f in _FIXAS:
                v = rx.sub(f, v)
            if rua:
                v = rua[0].sub(rua[1], v)
            if bairro_aqui:
                v = bairro_aqui[0].sub(bairro_aqui[1], v)
            v = ref_parecer.sub(f"na data da vistoria ({vist})", v)
            if p not in de_referencial:
                for antes, depois in trocas_av:          # 129: dado trocado pelo avaliador, por regra (sem IA)
                    if antes and antes in v and depois not in v:
                        v = v.replace(antes, depois)
            if v != (r.text or ""):
                r.text = v
        try:                                   # 106-3: 2ª camada — a mesma regra da conferência (coerencia.sem_dispersao)
            from .coerencia import sem_dispersao as _sd
            t0 = X.texto(p)
            t1 = _sd(t0)
            if t1 != t0 and not t0.strip().startswith("Coeficiente"):
                if t1.strip():
                    X.definir(p, t1)
                elif p.getparent() is not None and not X.tem_imagem(p):
                    p.getparent().remove(p)
                    continue
        except ImportError:
            pass
        if cv_fora and _FRASE_CV.search(X.texto(p)) and not X.texto(p).strip().startswith("Coeficiente"):
            novo = _FRASE_CV.sub("", X.texto(p)).strip()
            if novo:
                X.definir(p, novo)
            elif p.getparent() is not None and not X.tem_imagem(p):
                p.getparent().remove(p)
    # 092-5: frase que abre uma lista e não lista nada ("…Pontos observados na vistoria:") perde o final; e
    # "Principais benfeitorias…" termina com ponto
    for p in list(ctx.body.iter(qn("w:p"))):
        txt = X.texto(p)
        prox = p.getnext()
        lista_depois = prox is not None and prox.tag == qn("w:p") and re.match(r"^\s*[-•–*]|^\s*\w[^:]{0,40}:", X.texto(prox) or "")
        if (re.match(r"(?i)^\s*estado de conserva", txt) and re.search(r"(?i)pontos observados na vistoria", txt)
                and len(txt) < 400):     # 095-4: no resumo, só a classificação
            X.definir(p, re.sub(r"(?i)[,;.–-]?\s*pontos observados na vistoria.*$", "", txt).rstrip(" ,;:–-") + ".")
            continue
        if re.search(r"(?i)[,;.]?\s*pontos observados na vistoria:\s*$", txt) and not lista_depois:
            X.definir(p, re.sub(r"(?i)[,;.]?\s*pontos observados na vistoria:\s*$", "", txt).rstrip(" ,;:") + ".")
        elif re.match(r"(?i)^\s*principais benfeitorias", txt) and re.search(r":\s*\S", txt) and txt.strip()[-1] not in ".!?:":   # 102-8: só com conteúdo
            X.definir(p, txt.rstrip() + ".")
    # 104-4: "conforme… conforme" na mesma frase — a 2ª vira "segundo"
    for p in list(ctx.body.iter(qn("w:p"))):
        txt = X.texto(p)
        if txt.lower().count("conforme") < 2:
            continue
        frases = []
        for f in _FIM_FRASE.split(txt):
            ms = list(re.finditer(r"(?i)\bconforme\b", f))
            if len(ms) >= 2:
                m = ms[1]
                f = f[:m.start()] + ("Segundo" if f[m.start()].isupper() else "segundo") + f[m.end():]
                f = re.sub(r"(?i)segundo filia", "segundo a filia", f)
            frases.append(f)
        novo = " ".join(frases)
        if novo != txt:
            X.definir(p, novo)
    # 103-4: no Resumo (item 12), o estado de conservação é 1 frase (a classificação), nunca o parágrafo do 7.4
    no_resumo = False
    for p in list(ctx.body.iter(qn("w:p"))):
        txt = X.texto(p).strip()
        if re.match(r"^12\.?\s+\S", txt) and not re.search(r"\d\s*$", txt):
            no_resumo = True
            continue
        if no_resumo and re.match(r"^1[3-9]\.?\s+\S", txt) and not re.search(r"\d\s*$", txt):
            break
        if no_resumo and re.match(r"(?i)^estado de conserva", txt) and len(txt) > 140:
            frases = _FIM_FRASE.split(txt)
            X.definir(p, frases[0].rstrip(" :;") + ("" if frases[0].rstrip().endswith(".") else "."))
    # 090-9: sem certidão atualizada da matrícula, o laudo não diz que o valor considera o imóvel livre de ônus
    if any(_SEM_CERTIDAO.search(X.texto(p)) for p in ctx.body.iter(qn("w:p"))):
        for p in list(ctx.body.iter(qn("w:p"))):
            txt = X.texto(p)
            if _LIVRE_ONUS.search(txt):
                novo = " ".join(f for f in _FIM_FRASE.split(txt.strip()) if not _LIVRE_ONUS.search(f)).strip()
                if novo:
                    X.definir(p, novo)
                elif p.getparent() is not None and not X.tem_imagem(p):
                    p.getparent().remove(p)


_SEM_CERTIDAO = re.compile(r"(?i)n[aã]o foi apresentada certid[aã]o")
_LIVRE_ONUS = re.compile(r"(?i)livre (?:e desembaraçado )?de [oô]nus")


def _manter_junto(p, proximo: bool = True) -> None:
    ppr = p.find(qn("w:pPr"))
    if ppr is None:
        ppr = identidade._el("w:pPr")
        p.insert(0, ppr)
    pos = 1 if ppr.find(qn("w:pStyle")) is not None else 0      # ordem do esquema: pStyle, keepNext, keepLines…
    for tag in (["w:keepNext"] if proximo else []) + ["w:keepLines"]:
        if ppr.find(qn(tag)) is None:
            ppr.insert(pos, identidade._el(tag))
        pos += 1


def _bloco_valor_junto(ctx: _Ctx) -> None:
    """077-3: o bloco do valor (memória de cálculo, caixa azul, extenso e o quadro mínimo/adotado/máximo)
    não quebra entre páginas: cada parágrafo "mantém com o próximo" e as linhas das tabelas não se partem."""
    ini = next((p for p in ctx.body.iter(qn("w:p")) if X.texto(p).strip().startswith("Valor de Mercado = Área")), None)
    if ini is None:
        return
    # 095-5: a faixa de ±N% é justificada UMA vez, depois da caixa do valor; a de antes da conta sai
    depois, e = [], ini.getnext()
    while e is not None and len(depois) < 25:
        depois.append(e)
        e = e.getnext()
    if any(x.tag == qn("w:p") and re.search(r"(?i)faixa de varia", X.texto(x)) for x in depois):
        e, k = ini.getprevious(), 0
        while e is not None and k < 6:
            ant = e.getprevious()
            if e.tag == qn("w:p") and re.search(r"(?i)faixa de varia[cç][aã]o de [±+-]?\s*\d", X.texto(e)) and not X.tem_imagem(e):
                e.getparent().remove(e)
            e, k = ant, k + 1
    bloco, e = [], ini
    while e is not None:
        bloco.append(e)
        if e.tag == qn("w:tbl") and "FAIXA DE VARIA" in X.texto(e).upper():
            break
        e = e.getnext()
    if not bloco or bloco[-1].tag != qn("w:tbl"):
        return                                  # sem o quadro da faixa no fim: não mexe
    # 134-3 (pedido do Capitão, "quebrar como no A1"): o bloco NÃO começa numa página nova (antes a quebra forçada
    # deixava meia folha em branco). A memória de cálculo corre normalmente; só a caixa do valor, o extenso e o quadro
    # da faixa ficam juntos.
    k_tab = next((k for k, el in enumerate(bloco) if el.tag == qn("w:tbl")), 0)
    bloco = bloco[max(0, k_tab - 1):]          # o parágrafo logo antes da caixa anda com ela
    for i, el in enumerate(bloco):
        ultimo = i == len(bloco) - 1
        if el.tag == qn("w:p"):
            _manter_junto(el)
            continue
        linhas = el.findall(qn("w:tr"))
        for j, tr in enumerate(linhas):
            trpr = tr.find(qn("w:trPr"))
            if trpr is None:
                trpr = identidade._el("w:trPr")
                tr.insert(0, trpr)
            if trpr.find(qn("w:cantSplit")) is None:
                trpr.append(identidade._el("w:cantSplit"))
            for p in tr.iter(qn("w:p")):
                _manter_junto(p, proximo=not (ultimo and j == len(linhas) - 1))


def _tirar_quebras(ctx: _Ctx) -> None:
    """095-1: títulos cuja página nova deixou a anterior quase vazia (medido no PDF da montagem anterior) passam a
    seguir o texto (sem página nova), presos ao que vem depois."""
    import json as _json
    try:
        alvos = [_n(x)[:50] for x in _json.loads(db.setting(f"sem_quebra:{ctx.job}") or "[]") if x]
    except ValueError:
        alvos = []
    if not alvos:
        return
    for p in ctx.body.iter(qn("w:p")):
        t = _n(X.texto(p))
        if t and any(t.startswith(a) for a in alvos):
            ppr = p.find(qn("w:pPr"))
            if ppr is None:
                ppr = identidade._el("w:pPr")
                p.insert(0, ppr)
            for q in ppr.findall(qn("w:pageBreakBefore")):
                ppr.remove(q)
            pb = identidade._el("w:pageBreakBefore")
            pb.set(qn("w:val"), "0")                  # vence a quebra que vem do estilo do título
            ppr.insert(1 if ppr.find(qn("w:pStyle")) is not None else 0, pb)
            _manter_junto(p)


def ajustes_de_quebra(pdf_path) -> tuple[str, list[str]]:
    """095-1: (começo do trecho que deve descer com o bloco do valor, títulos que devem perder a página nova), a partir
    das páginas quase vazias que a conferência mede (coerencia.paginas_curtas)."""
    import pymupdf
    from . import coerencia
    try:
        curtas = coerencia.paginas_curtas(pdf_path)
    except Exception:
        return "", []
    if not curtas:
        return "", []
    valor, titulos = "", []
    with pymupdf.open(str(pdf_path)) as d:
        for c in curtas:
            n = int(c["pagina"])                     # 1-based
            if n >= len(d):
                continue
            prox = d[n]
            h = prox.rect.height
            corpo = [b for b in prox.get_text("blocks") if b[4].strip() and h * 0.07 < b[1] < h * 0.92 and "CRECI" not in b[4]]
            if not corpo:
                continue
            primeiro = " ".join(corpo[0][4].split())
            if primeiro.startswith("Valor de Mercado = Área"):
                valor = pagina_curta_antes_do_valor(pdf_path) or valor
            else:
                titulos.append(primeiro[:80])
    return valor, titulos


def pagina_curta_antes_do_valor(pdf_path) -> str:
    """095-1: mede o PDF. Se a página logo antes do bloco do valor ("Valor de Mercado = Área…") tem menos de 12 linhas
    de corpo, devolve o começo do 1º parágrafo dela (para a quebra subir até ali); senão "". """
    import pymupdf
    try:
        d = pymupdf.open(str(pdf_path))
    except Exception:
        return ""
    for i in range(1, len(d)):
        if "Valor de Mercado = Área" not in d[i].get_text():
            continue
        p = d[i - 1]
        h = p.rect.height
        corpo = [b for b in p.get_text("blocks") if b[4].strip() and h * 0.07 < b[1] < h * 0.92 and "CRECI" not in b[4]]
        linhas = sum(b[4].strip().count("\n") + 1 for b in corpo)
        if not corpo or linhas >= 12:
            return ""
        return " ".join(corpo[0][4].split())[:80]
    return ""


def _anexos(ctx: _Ctx) -> None:
    imovel, sol = _arquivos_doc(ctx)
    tarjados = []
    com_tarja = 0       # documentos que tiveram tarja de verdade
    for rel in (sol if TARJA_NO_LAUDO_DO_CLIENTE else []):  # regra antiga (só com a tarja ligada)
        if _doc_pj_sem_pessoa(ctx, rel):
            # ORDEM 029-2: documento de pessoa jurídica sem CPF/RG de pessoa (ex.: cartão CNPJ)
            # entra sem tarja, como no laudo do Alan
            tarjados.append(rel)
            continue
        faltam = _sem_tarja(ctx, rel)  # uma página sem tarja barra o documento inteiro
        if not faltam:
            tarjados.append(rel)
            com_tarja += 1
        for f in faltam:
            ctx.aviso(f"{SEM_TARJA}: {f}")
    rel_md, dados_md = mapa_digital(ctx.job)
    if rel_md and rel_md not in imovel:       # 077-1 (D-077): o Mapa Digital Fácil no anexo dos documentos do imóvel
        imovel = list(imovel) + [rel_md]
    elif not rel_md and re.match(r"^goiania\s*[-/–]?\s*(?:go)?$",           # L200 (Caso M): "Aparecida de Goiânia"
                                 (nomes._limpo(ctx.t.cidade) or "").lower().replace("â", "a").strip()):   # não é Goiânia
        ctx.aviso("Falta a imagem do Mapa Digital Fácil")
    imovel = _na_ordem_do_quadro(ctx, list(imovel))     # 092-7: anexos na mesma ordem do quadro do item 6
    _anexo(ctx, "Anexo III – Documentação do Imóvel", imovel, None, tarjar=False)
    if rel_md:
        _links_mapa_digital(ctx, rel_md, dados_md)
    if not TARJA_NO_LAUDO_DO_CLIENTE:
        tarjados = list(sol)       # D-062: laudo do cliente, documentos como vieram
    _anexo(ctx, "Anexo IV – Documentação do Solicitante", tarjados, "", tarjar=TARJA_NO_LAUDO_DO_CLIENTE)
    # vínculo do solicitante com o titular (P0 itens 7/10, P6 A): frase da redação antes dos
    # documentos; legenda no gênero do solicitante
    h = ctx.par("Anexo IV – Documentação do Solicitante")
    vinc = (ctx.textos.secoes.get("anexo4") or "").strip()
    if h is not None and vinc:
        nxt = h.getnext()
        while nxt is not None and nxt.tag == qn("w:p") and X.tem_imagem(nxt):
            nxt = nxt.getnext()
        p = copy.deepcopy(nxt) if (nxt is not None and nxt.tag == qn("w:p")) else None
        if p is not None:
            X.definir(p, vinc)
            h.addnext(p)
    # a legenda DO ANEXO IV (depois do título): a tabela "Documentação analisada" pode ter uma
    # linha com o mesmo começo e era ela que a busca achava
    leg = None
    if h is not None:
        depois = False
        for q in ctx.body.iter(qn("w:p")):
            if q is h:
                depois = True
                continue
            if depois and X.texto(q).strip().startswith("Documentos de identificação do solicitante"):
                leg = q
                break
    if leg is not None and re.search(r"\b(a solicitante|da solicitante)\b", vinc, re.I):
        X.subst(leg, "do solicitante", "da solicitante")
    if leg is not None and tarjados and not com_tarja:
        # ORDEM 030-A (Instruções §2.8): sem tarja aplicada, o laudo não declara que ocultou dados
        t = X.texto(leg)
        novo = re.sub(r"\s*\(dados não necessários ocultados\)", "", t, flags=re.I)
        if novo != t:
            X.definir(leg, novo)


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
    if re.search(r"\b957\s*/\s*(?:20)?06\b|n[ºo°]\s*957\b|\b957,\s*de\s*22", texto, re.I):
        raise ConteudoProibido("citação vedada: Resolução COFECI 957/2006, revogada (D-001)")
    if re.search(r"item\s*3\.34", texto, re.I):
        raise ConteudoProibido('citação vedada: "item 3.34" da NBR 14653-1 (D-008)')
    if modalidade != "AMJ" and re.search(r"13\.105\s*/\s*2015|C[óo]digo de Processo Civil|\bCPC\b",
                                         texto):
        raise ConteudoProibido("citação vedada: CPC só no AMJ (P4 N7)")
    if modalidade == "OV" and re.search(r"\bPTAM\b", texto.replace(_CURRICULO_PTAM, "")):
        raise ConteudoProibido('a palavra "PTAM" não pode aparecer em OV (D-011)')


def _limpar_rels(ctx: _Ctx) -> None:
    xml = ctx.body.xml
    for rid, rel in list(ctx.part.rels.items()):
        if rel.reltype in (RT.HYPERLINK, RT.IMAGE) and f'"{rid}"' not in xml:
            del ctx.part.rels[rid]


def _sem_contexto_verbal(ctx: _Ctx) -> None:
    """D-013: valores da informação verbal do contratante (contexto) não podem aparecer no
    texto do laudo (preço pretendido, venda de vizinho, nº de apartamento citado...)."""
    ctxt = ctx.t.contexto or ""
    if not ctxt.strip():
        return
    valores = set(re.findall(r"R\$\s*[\d.]+(?:,\d{2})?", ctxt))
    valores |= {n for n in re.findall(r"\b\d{3,5}\b", ctxt) if not re.fullmatch(r"(19|20)\d\d", n)}
    texto = _texto_redacao(ctx)
    plano = texto.replace("\xa0", " ")
    achados = sorted(v for v in valores if re.search(r"(?<![\d.,])" + re.escape(v.replace("R$", "R$").strip())
                                                     + r"(?![\d])", plano))
    if achados:
        raise ConteudoProibido("informação verbal do contratante no laudo (D-013): "
                               + ", ".join(achados[:5]))


def _contatos_com_link(ctx: _Ctx) -> None:
    """Anexo V (P9/D-034): telefone/WhatsApp, site e Instagram viram hiperlinks reais."""
    av = identidade.avaliador(_avaliador())
    fone = re.sub(r"\D", "", av["telefone"])
    insta = (_avaliador().get("instagram") or ("@alansoares_corretor" if identidade._AV_LAUDO == "AV-0001" else "")).strip().lstrip("@")
    alvos = (("Telefone / WhatsApp:", f"https://wa.me/55{fone}"),
             ("Site:", f"https://{av['site']}"),
             ("Instagram:", f"https://www.instagram.com/{insta}/"))
    for prefixo, url in alvos:
        p = ctx.par(prefixo)
        if p is None or p.find(".//" + qn("w:hyperlink")) is not None:
            continue
        txt = X.texto(p)
        rot, _, valor = txt.partition(":")
        rpr = X.rpr_base(p)
        X.limpar_runs(p)
        p.append(X.novo_run(rot + ": ", rpr))
        p.append(X.novo_hyperlink(ctx.part, url, valor.strip(), rpr))


_METODO_OV = "[PREENCHER: tipologia, padrão e idade dos referenciais]"


def _metodologia_ov(ctx: _Ctx) -> None:
    """OV: metodologia = parágrafo fixo do P1-OV; a redação só dá o trecho dos referenciais."""
    if ctx.t.modalidade != "OV":
        return
    p = next((e for e in ctx.body.iter(qn("w:p")) if _METODO_OV in X.texto(e)), None)
    if p is None:
        return
    trecho = (ctx.textos.secoes.get("5") or "").strip().rstrip(".")
    if not trecho or len(trecho) > 200:
        trecho = "imóveis de mesma tipologia, padrão construtivo e idade semelhantes"
        ctx.aviso("metodologia: trecho dos referenciais ausente ou longo; usado texto genérico")
    trecho = trecho[0].lower() + trecho[1:]
    X.definir(p, X.texto(p).replace(_METODO_OV, trecho))


def _apartamento(ctx: _Ctx) -> None:
    """Apartamento: a unidade é a ÁREA PRIVATIVA (escritura/IPTU) — rótulos do laudo e linha da
    tabela de áreas com a privativa adotada."""
    from .agentes.selecao import classe_tipologia
    if classe_tipologia(ctx.t.tipo) != "apartamento":
        return
    priv = next((c for c in ctx.cs if "privativ" in _n(c.nome) and "area" in _n(c.nome)), None)
    tb = ctx.tabela("Descrição") or ctx.tabela("Área")
    if tb is not None and priv is not None:
        for tr in tb.findall(qn("w:tr"))[1:]:
            tcs = tr.findall(qn("w:tc"))
            if "terreno" in _n(X.texto(tcs[0])):
                X.definir(tcs[0].find(qn("w:p")), "Terreno do condomínio (total)")
            if "constru" in _n(X.texto(tcs[0])):
                X.definir(tcs[0].find(qn("w:p")), "Área privativa (adotada no cálculo)")
                X.definir(tcs[1].find(qn("w:p")), _area(priv))
                X.definir(tcs[2].find(qn("w:p")), _fonte(ctx, priv))
    for tbl in ctx.body.iter(qn("w:tbl")):   # resumo: o terreno é o do condomínio inteiro
        for tr in tbl.findall(qn("w:tr")):
            tcs = tr.findall(qn("w:tc"))
            if tcs and X.texto(tcs[0]).strip() == "Área do terreno":
                X.definir(tcs[0].find(qn("w:p")), "Terreno do condomínio (total)")
            if (tcs and len(tcs) > 1 and priv is not None
                    and X.texto(tcs[0]).strip() in ("Área construída adotada", "Área privativa adotada")):
                # mesma fonte do 7.3 (a da área privativa), não a da área construída do IPTU
                num = X.texto(tcs[1]).split(" (")[0].strip()
                X.definir(tcs[1].find(qn("w:p")), f"{num} ({_fonte(ctx, priv)})")
    for p in ctx.body.iter(qn("w:p")):
        X.subst(p, "Área Construída × Valor Unitário", "Área Privativa × Valor Unitário")
        X.subst(p, "Área construída adotada", "Área privativa adotada")
        X.subst(p, "(área construída)", "(área privativa)")
    for tbl in ctx.body.iter(qn("w:tbl")):
        tr = tbl.find(qn("w:tr"))
        if tr is not None and "Foto Principal" in X.texto(tr):
            for p in tr.iter(qn("w:p")):
                X.subst(p, "Construída", "Privativa")


def _cpc_473(ctx: _Ctx, titulo: str, frase: str, depois_do_primeiro: bool | None) -> None:
    """Acrescenta `frase` à seção cujo título contém `titulo` (só se a seção ainda não cita o
    art. 473). depois_do_primeiro: None = logo após o título; False = no fim da seção."""
    h = next((x for x in X.titulos(ctx) if titulo in X.texto(x).upper()), None)
    if h is None:
        return
    corpo = []
    e = h.getnext()
    while e is not None and e not in X.titulos(ctx):
        if e.tag == qn("w:p") and X.texto(e).strip():
            corpo.append(e)
        e = e.getnext()
    if not corpo or any("473" in X.texto(p) for p in corpo):
        return
    modelo = corpo[0]
    novo = copy.deepcopy(modelo)
    X.definir(novo, frase)
    (h if depois_do_primeiro is None else corpo[-1]).addnext(novo)


def _limitar_altura(p, cm: float) -> None:
    """Reduz proporcionalmente a imagem do parágrafo para no máximo `cm` de altura."""
    lim = int(cm * 360000)
    for ext in p.iter(qn("wp:extent")):
        cx, cy = int(ext.get("cx")), int(ext.get("cy"))
        if cy <= lim:
            return
        f = lim / cy
        ext.set("cx", str(int(cx * f)))
        ext.set("cy", str(lim))
    for e in p.iter(qn("a:ext")):
        if e.get("cx") and e.get("cy"):
            e.set("cx", str(int(int(e.get("cx")) * f)))
            e.set("cy", str(int(int(e.get("cy")) * f)))


def _textos_fixos(ctx: _Ctx) -> None:
    """Depois da renumeração: (1) AM/AMJ sem a terminologia de OV que o modelo P1-AM traz;
    (2) remissão "limitações descritas no item N" apontando para o item real dos pressupostos;
    (3) pesquisa sem quebra de página forçada (página quase vazia antes dela)."""
    if ctx.t.modalidade != "OV":
        for p in ctx.body.iter(qn("w:p")):
            # ORDEM 043 (mudança 3): no PTAM a palavra é "parecer"
            X.subst(p, "Opinião de valor elaborada", "Parecer elaborado")
            X.subst(p, "desta Opinião de Valor", "deste parecer")
            X.subst(p, "presente Opinião de Valor", "presente parecer")
    num = next((m.group(1) for h in X.titulos(ctx)
                if (m := re.match(r"(\d+)\.\s+PRESSUPOSTOS", X.texto(h).strip()))), None)
    if num:
        for p in ctx.body.iter(qn("w:p")):
            t = X.texto(p)
            m = re.search(r"limitações descritas no item (\d+)", t)
            if m and m.group(1) != num:
                X.subst(p, f"no item {m.group(1)}.", f"no item {num}.")
    for h in X.titulos(ctx):
        if "PESQUISA DE IMÓVEIS REFERENCIAIS" in X.texto(h):
            for e in list(h.iter(qn("w:pageBreakBefore"))):
                e.getparent().remove(e)
    if ctx.t.modalidade == "AMJ":   # P4 N7 / P7: CPC art. 473 só no AMJ
        _cpc_473(ctx, "METODOLOGIA",
                 "O Método Comparativo Direto de Dados de Mercado é o predominantemente aceito pelos "
                 "especialistas em avaliação de imóveis urbanos, atendendo ao art. 473, III, da Lei "
                 "nº 13.105/2015 (Código de Processo Civil).", depois_do_primeiro=False)
        _cpc_473(ctx, "RESPOSTAS AOS QUESITOS",
                 "Os quesitos são respondidos a seguir, um a um, de forma conclusiva, nos termos do "
                 "art. 473, IV, da Lei nº 13.105/2015 (Código de Processo Civil).", depois_do_primeiro=None)
    if ctx.t.modalidade == "AMJ":   # P7: declarações do AMJ + ausência de impedimento
        for p in ctx.body.iter(qn("w:p")):
            if X.texto(p).strip().startswith("O avaliador não possui interesse"):
                novo = copy.deepcopy(p)
                X.definir(novo, "O avaliador declara não haver impedimento nem suspeição para atuar "
                                "como perito neste processo e não possui vínculo com as partes.")
                p.addnext(novo)
                break
    # Anexo I logo após a lista de anexos: a 1ª imagem (19 cm) não cabia e deixava a página
    # da lista quase em branco (P6 E) — reduzida para 15,5 cm de altura, proporcional
    ps = list(ctx.body.iter(qn("w:p")))
    for i, p in enumerate(ps):
        if X.texto(p).strip().startswith("Anexo I – Tabela de Fatores") and not X.texto(p).endswith("\t"):
            img = next((q for q in ps[i + 1:i + 4] if X.tem_imagem(q)), None)
            if img is not None:
                _limitar_altura(img, 15.5)
            break
    # quadra/lote com a grafia do documento em todo o laudo (capa, 7.1, resumo, anexos)
    logr = (_val(_campo(ctx.cs, "endereco")) or "").split(",")[0].strip()
    for p in ctx.body.iter(qn("w:p")):
        t = X.texto(p)
        for velho, novo in _trocas_grafia(ctx, t):
            X.subst(p, velho, novo)
        if len(logr) >= 6 and logr in t:       # 172-5: no endereço do AVALIANDO (nunca no de um referencial)
            t = X.texto(p)
            if _quadra_lote_do_documento(ctx, t) != t:
                for velho, novo in _pares_quadra_lote(ctx, t):
                    X.subst(p, velho, novo)


def _base_terreno(ctx: "_Ctx") -> None:
    """ORDEM 021: base terreno — o laudo fala em área do terreno, nunca em área construída."""
    for p in ctx.body.iter(qn("w:p")):
        X.subst(p, "Área Construída × Valor Unitário", "Área do Terreno × Valor Unitário")
        X.subst(p, "Área construída adotada", "Área do terreno adotada")
        X.subst(p, "(área construída)", "(área do terreno)")
        X.subst(p, "área construída do avaliando", "área do terreno do avaliando")


import threading  # noqa: E402
_TROCA_AV = threading.Lock()

# ORDEM 045 / D-100: código interno no texto (D-027, F-S003…) e prazo sem fonte ("tem validade de
# 30 dias") são erro do sistema: saem do texto final, sem perguntar ao avaliador.
_COD_INTERNO = re.compile(r"\s*\((?:D-\d{3}|F-[SKD]-?\d{3,4})(?:[,;/ ]+(?:D-\d{3}|F-[SKD]-?\d{3,4}))*\)")
_VALIDADE_SEM_FONTE = re.compile(r",?\s*(?:que\s+)?(?:tem|com|possui)\s+validade\s+de\s+\d+\s*(?:\([^)]*\)\s*)?dias")


def _limpar_codigos(ctx) -> None:
    for el in [ctx.body] + [hf._element for hf in _cabecalhos(ctx)]:
        for t in el.iter(qn("w:t")):
            if t.text and ("D-" in t.text or "F-" in t.text or "validade" in t.text):
                novo = _VALIDADE_SEM_FONTE.sub("", _COD_INTERNO.sub("", t.text))
                if novo != t.text:
                    t.text = novo


def montar(job_id: str, textos: Textos, r: Resultado, selecao: Selecao) -> Path:
    """ORDEM 042: a montagem usa a identidade do avaliador DONO do trabalho (o Alan não muda)."""
    t = _comum.trabalho(job_id)
    av = t.avaliador_id or "AV-0001"
    with _TROCA_AV, identidade.do_avaliador(av, t.modalidade):            # L198: com a formatação do modelo dele
        return _montar(job_id, textos, r, selecao)


# ORDEM 042: o modelo P1 traz os dados do Alan; no laudo de outro avaliador eles viram os DELE
# (provisório até a ORDEM 043 trocar pelos modelos gerais aprovados).
def _pares_identidade() -> list[tuple[str, str]]:
    from . import avaliadores
    i = avaliadores.identidade_avaliador(identidade._AV_LAUDO)
    nome, creci, cnai = i["nome"] or "Avaliador", i["creci"] or "", i["cnai"] or ""
    num_creci = (re.findall(r"\d{3,}", creci) or [re.sub(r"\D", "", creci) or creci])[-1]
    # ORDEM 043: "[Nª] Região – CRECI/[UF]" tirados do CRECI do avaliador (ex.: "CRECI 2ª Região – SP, nº 1234")
    reg = re.search(r"(\d+)\s*[ªa]\s*Regi", creci)
    uf = re.search(r"\b(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b", creci)
    conselho = ("Conselho Regional de Corretores de Imóveis"
                + (f" da {reg.group(1)}ª Região" if reg else "") + (f" – CRECI/{uf.group(1)}" if uf else ""))
    sem_cnai = [] if cnai else [            # sem CNAI: a linha de perito sai inteira (K3: só OV)
        ("Avaliador de Imóveis / Perito Judicial – CNAI nº 053569.", ""),
        ("CNAI nº 053569 – Avaliador de Imóveis / Perito Judicial", ""),
        ("Avaliação: Avaliador de Imóveis / Perito Judicial – CNAI nº 053569", ""),
        (" – CNAI 053569", ""),
    ]
    sem_perito = [                          # ORDEM 043 (mudança 5): "Perito Judicial" fora do modelo geral
        ("Avaliador de Imóveis / Perito Judicial inscrito", "Avaliador de Imóveis inscrito"),
        ("Avaliador de Imóveis / Perito Judicial", "Avaliador de Imóveis"),
    ]
    return sem_cnai + sem_perito + [
        ("O avaliador signatário encontra-se regularmente inscrito no Conselho Regional de Corretores de Imóveis da 5ª Região – CRECI/GO, sob o nº 36507",
         f"O avaliador signatário encontra-se regularmente inscrito no {conselho}, sob o nº {num_creci}"),
        ("inscrito no CRECI/GO sob o nº 36507",
         f"inscrito no CRECI{('/' + uf.group(1)) if uf else ''} sob o nº {num_creci}"),
        ("Alan Soares da Silva", nome), ("ALAN SOARES DA SILVA", nome.upper()),
        ("CRECI 36507/GO", f"CRECI {creci}".strip()), ("CNAI nº 053569", f"CNAI nº {cnai}".strip()),
        ("CNAI 053569", f"CNAI {cnai}".strip()), ("sob o nº 053569", f"sob o nº {cnai}"),
        ("(62) 9 9306-8692", i["telefone"]), ("avaliadordeimovel.com", i["site"]),
        ("@alansoares_corretor", i["instagram"]),
        ("Certificação em Parecer Técnico de Avaliação Mercadológica (PTAM) – Instituto Monitor.", ""),
        ("Curso Técnico em Transações Imobiliárias – CEP-SINDIMÓVEIS/GO.", i["formacao"]),
    ]


def _itens_do_modelo(ctx) -> None:
    """L198: cada item a mais do modelo do avaliador vira uma seção do laudo, com o texto fixo dele (sem dados de
    clientes), logo antes da Assinatura. O título copia o formato dos nossos e entra na renumeração e no sumário."""
    from . import avaliadores
    itens = (avaliadores.modelo_do_laudo(identidade._AV_LAUDO, ctx.t.modalidade) or {}).get("itens") or []
    if not itens:
        return
    tits = X.titulos(ctx)
    alvo = next((h for h in tits if re.search(r"ASSINATURA", X.texto(h))), None)
    modelo_tit = next((h for h in tits if re.search(r"DECLARA", X.texto(h))), alvo)
    if alvo is None or modelo_tit is None:
        return
    corpo_modelo = modelo_tit.getnext()
    while corpo_modelo is not None and (corpo_modelo.tag != qn("w:p") or not X.texto(corpo_modelo).strip()):
        corpo_modelo = corpo_modelo.getnext()
    for k, it in enumerate(itens, start=1):
        tit = copy.deepcopy(modelo_tit)
        for b in tit.iter(qn("w:bookmarkStart")):
            b.set(qn("w:name"), f"sec_extra_{k}")
            b.set(qn("w:id"), str(90000 + k))
        for b in tit.iter(qn("w:bookmarkEnd")):
            b.set(qn("w:id"), str(90000 + k))
        X.definir(tit, f"99. {str(it.get('titulo') or 'Item').upper()}")
        alvo.addprevious(tit)
        for par in [x.strip() for x in str(it.get("texto") or "").split("\n") if x.strip()]:
            p = copy.deepcopy(corpo_modelo if corpo_modelo is not None else modelo_tit)
            for b in (list(p.iter(qn("w:bookmarkStart"))) + list(p.iter(qn("w:bookmarkEnd"))) + list(p.iter(qn("w:numPr")))
                      + list(p.iter(qn("w:pStyle"))) + list(p.iter(qn("w:ind")))):
                b.getparent().remove(b)                    # sem marcador de lista: parágrafo comum
            X.definir(p, par)
            alvo.addprevious(p)


_ROTULOS_ANEXO_V = ("Formação:", "Contato:", "Telefone / WhatsApp:", "Site:", "Instagram:")
_CURSO_ALAN = "Curso Técnico em Transações Imobiliárias – CEP-SINDIMÓVEIS/GO."
# a grafia do modelo varia ("SINDIMOVEIS", hífen) e só é acertada depois (_FIXAS)
_CERT_ALAN_RX = re.compile(r"(?i)Certifica[çc][ãa]o em Parecer T[ée]cnico de Avalia[çc][ãa]o Mercadol[óo]gica\s*(?:\(PTAM\)\s*)?[-‐–]\s*Instituto Monitor\.?")   # OV: sem "(PTAM)"
_CURSO_ALAN_RX = re.compile(r"(?i)Curso T[ée]cnico em Transa[çc][õo]es Imobili[áa]rias\s*[-‐–]\s*CEP[-‐–]SINDI?M[OÓ]VEIS(?:/GO)?\.?")


def _anexo_v_sem_vazios(ctx) -> None:
    """L200/L201-2: no laudo de outro avaliador, a formação do Alan (curso e certificação, em qualquer parágrafo e
    grafia do modelo) sai — vira a formação cadastrada dele, ou nada — e rótulo do Anexo V sem nada depois some."""
    from . import avaliadores
    i = avaliadores.identidade_avaliador(identidade._AV_LAUDO)
    formacao = (i.get("formacao") or "").strip()
    usada = False
    for p in list(ctx.body.iter(qn("w:p"))):
        t = X.texto(p)
        if not (_CURSO_ALAN_RX.search(t) or _CERT_ALAN_RX.search(t)):
            continue
        novo = _CERT_ALAN_RX.sub("", t)
        novo = _CURSO_ALAN_RX.sub(lambda m: "" if usada else formacao, novo, count=1)
        novo = _CURSO_ALAN_RX.sub("", novo)
        usada = usada or bool(formacao and formacao in novo)
        novo = re.sub(r"\s{2,}", " ", novo).strip()
        if not novo or novo.rstrip(":") + ":" in _ROTULOS_ANEXO_V:
            X.remover(p)
        elif novo != t.strip():
            X.definir(p, novo)
    tem_contato = any(i.get(k) for k in ("telefone", "site", "instagram"))
    for p in list(ctx.body.iter(qn("w:p"))):
        t = X.texto(p).strip()
        if t in _ROTULOS_ANEXO_V and (t != "Contato:" or not tem_contato):
            X.remover(p)


def _trocar_identidade(ctx) -> None:
    pares = _pares_identidade()
    elementos = [ctx.body] + [hf._element for hf in _cabecalhos(ctx)]
    for el in elementos:
        for p in el.iter(qn("w:p")):
            ts = [t for t in p.iter(qn("w:t")) if t.text]
            if not ts:
                continue
            for velho, novo in pares:
                if any(velho in t.text for t in ts):
                    for t in ts:
                        if velho in t.text:
                            t.text = t.text.replace(velho, novo)
                elif velho in "".join(t.text for t in ts):     # texto partido em vários trechos
                    junto = "".join(t.text for t in ts).replace(velho, novo)
                    ts[0].text = junto
                    for t in ts[1:]:
                        t.text = ""


def _montar(job_id: str, textos: Textos, r: Resultado, selecao: Selecao) -> Path:
    base = base_area(job_id)
    # tabela de amostras e cálculo na base escolhida (terreno: área = lote_m2 do referencial)
    selecao = selecao.model_copy(update={"refs": refs_na_base(job_id, selecao.refs, base)})
    # L200 (Caso W): a idade que o avaliador confirmou depois da escolha ("Confere") vale na tabela do laudo;
    # a escolha gravada guardava a idade "pelas fotos" (n/i no laudo) e a planilha já mostrava a confirmada
    atuais = {c.n: c for c in db.candidatos(job_id)}
    selecao = selecao.model_copy(update={"refs": [
        x.model_copy(update={"idade_aparente": atuais[x.n].idade_aparente, "idade_fonte": atuais[x.n].idade_fonte})
        if x.n in atuais and atuais[x.n].idade_fonte == "avaliador" else x for x in selecao.refs]})
    ctx = _Ctx(job_id, textos, r, selecao)
    ctx.saida.mkdir(parents=True, exist_ok=True)
    _metodologia_ov(ctx)
    _capa(ctx)
    _tab_documentos(ctx)
    _localizacao(ctx)
    _tab_areas(ctx)
    _grade_fotos(ctx)
    _tab_amostras(ctx)
    _comparacao_d069(ctx)                          # 080-4: padrão superior abaixo da referência, só comparação
    _calculo(ctx)
    if base == "terreno":
        _base_terreno(ctx)
    _anexos(ctx)
    _perito(ctx)
    _quebras_dos_anexos(ctx)
    _contatos_com_link(ctx)
    _apartamento(ctx)
    if ctx.t.modalidade == "OV":   # D-011/P9: nenhuma ocorrência de "PTAM" numa OV
        for p in ctx.body.iter(qn("w:p")):
            X.subst(p, f"{_CURRICULO_PTAM}", "Parecer Técnico de Avaliação Mercadológica")
    _frase_dossie(ctx)
    _frase_medidas(ctx)
    _frase_itcd(ctx)                     # 096-8
    X.secoes(ctx)
    X.modalidade(ctx)
    _itens_do_modelo(ctx)                          # L198: os itens a mais do modelo do avaliador, antes da Assinatura
    X.renumerar(ctx)
    _textos_fixos(ctx)
    X.manter_juntos(ctx)
    _titulos_pedidos(ctx)                          # 117: título de item trocado pelo avaliador (entra no sumário)
    X.montar_sumario(ctx)
    if identidade._AV_LAUDO != "AV-0001":
        _trocar_identidade(ctx)                    # ORDEM 042: modelo sem os dados do Alan
    identidade.aplicar(ctx, _avaliador())          # D-040 + layout travado (P9)
    if identidade._AV_LAUDO != "AV-0001":
        _anexo_v_sem_vazios(ctx)                   # L200 (Caso M): contato/formação não cadastrados saem
    X.renumerar_docpr(ctx.body)
    for k, e in enumerate((e for hf in _cabecalhos(ctx) for e in hf._element.iter(qn("wp:docPr"))),
                          start=9000):
        e.set("id", str(k))                        # ids únicos também nos cabeçalhos
    varrer(_texto_redacao(ctx), ctx.t.modalidade, _nomes_arquivos(ctx))
    _sem_contexto_verbal(ctx)
    varrer(_todo_texto(ctx), ctx.t.modalidade)
    _limpar_rels(ctx)
    _limpar_codigos(ctx)                           # ORDEM 045 / D-100: erro do sistema corrigido sozinho
    _correcoes_fixas(ctx)                          # 077-A4: o que o JdB corrige sozinho no texto
    _trechos_pedidos(ctx)                          # 117: trecho fixo que o avaliador pediu para tirar
    _bloco_valor_junto(ctx)                        # 077-3: memória, caixa azul, extenso e faixa na mesma página
    _tirar_quebras(ctx)                            # 095-1: quebra de página que deixou a anterior quase vazia
    destino = ctx.pasta / f"{nomes.nome_arquivo(ctx.t)}.docx"
    ctx.doc.save(str(destino))
    db.evento(job_id, "montagem", "resultado", f"laudo Word gerado: {destino.name}",
              dados={"docx": destino.name})
    return destino



# ------------------------------------------------------------------ 087: o JdB corrige sozinho o que a conferência acha
def aplicar_substituicoes(docx_path: Path, pares: list[tuple[str, str]]) -> int:
    """Troca no Word (corpo, cabeçalhos e rodapés) o texto errado pelo certo que a conferência de coerência
    apontou (coerencia.substituicoes). Primeiro dentro de cada trecho (mantém a formatação); se o texto estiver
    partido em trechos, no parágrafo inteiro. Devolve quantas trocas fez (0 = nada a salvar)."""
    if not pares:
        return 0
    doc = Document(str(docx_path))
    partes = [doc.element.body]
    for s in doc.sections:
        for hf in (s.header, s.footer, s.first_page_header, s.first_page_footer):
            try:
                partes.append(hf._element)
            except Exception:       # noqa: BLE001 — seção sem cabeçalho próprio
                pass
    feitas = 0
    for raiz in partes:
        for p in list(raiz.iter(qn("w:p"))):
            if re.search(r"(?i)declarad|refer[êe]ncia|sefaz|fipe|venal|iptu|itbi|comunicado|agehab", X.texto(p)):
                continue                   # 100-1: frase sobre outro documento nunca é reescrita
            for de, para in pares:
                if de not in X.texto(p):
                    continue
                trocou = False
                for t in p.iter(qn("w:t")):
                    if t.text and de in t.text:
                        feitas += t.text.count(de)
                        t.text = t.text.replace(de, para)
                        trocou = True
                if not trocou and de in X.texto(p):          # partido em vários trechos
                    feitas += X.texto(p).count(de)
                    X.definir(p, X.texto(p).replace(de, para))
    if feitas:
        doc.save(str(docx_path))
    return feitas


# ------------------------------------------------------------------ 092-6 e 092-7: quadro do item 6 × anexos
def _quando_mapa(ctx: _Ctx) -> str:
    """dd/mm/aaaa da consulta ao Mapa Digital Fácil (a mesma da legenda do anexo, em Brasília)."""
    leg = _legenda_mapa_digital(ctx) if mapa_digital(ctx.job)[0] else ""
    m = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", leg)
    return m.group(1) if m else ""


def _data_mapa_no_quadro(ctx: _Ctx, linhas: list[list[str]]) -> None:
    """092-6: a linha do Mapa Digital Fácil no quadro do item 6 leva a data da consulta (nunca "—").
    093-A-11: as outras linhas sem data levam a data do campo do PRÓPRIO documento (ex.: "Anexo do comunicado ITCD" →
    "Data de emissão do comunicado ITCD" = 28/10/2026). Sem campo que case, fica como está (nunca inventa)."""
    datas = []
    for c in getattr(ctx, "cs", None) or []:
        nome, valor = (c.nome or "").replace("_", " "), str(c.valor or "")   # 095-10: "data_titulo", "itcd_comunicado"
        m = (re.search(r"(?i)(?:emitid[oa]|emiss[aã]o|datad[oa])[^0-9]{0,40}?(\d{2}/\d{2}/\d{4})", valor)   # "emitido … em 28/10/2026"
             or (re.search(r"\b(\d{2}/\d{2}/\d{4})\b", valor) if re.search(r"(?i)\bdata\b|emiss|emitid", nome) else None))
        if m:
            datas.append((_palavras_doc(re.sub(r"(?i)\b(data|emiss[aã]o|emitid[oa])\b", " ", nome)), m.group(1)))
    for ln in linhas:
        if (ln[2] or "—").strip() not in ("—", "-", ""):
            continue
        if re.search(r"(?i)mapa digital", ln[0]):
            ln[2] = _quando_mapa(ctx) or ln[2]
            continue
        w = _palavras_doc(ln[0])
        notas = [(len(w & pal), d) for pal, d in datas]
        melhor = max(notas, default=(0, ""))
        if melhor[0] >= 2 or (melhor[0] == 1 and sum(1 for n, _ in notas if n == 1) == 1):
            ln[2] = melhor[1]


def _palavras_doc(s: str) -> set[str]:
    import unicodedata
    t = unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z0-9]{3,}", t)} - {"documento", "copia", "imagem", "imagens", "pdf", "jpg", "png"}


_EMISSAO_DOC = re.compile(r"(?i)(?:data\s+(?:de\s+)?emiss[ãa]o|emitid[oa]\s+em|gerad[oa]\s+em)\s*:?\s*(\d{2}/\d{2}/\d{4})")


def _data_do_proprio_documento(ctx: _Ctx, linhas: list[list[str]]) -> None:
    """134-3: a coluna "Data / emissão" do quadro do item 6 traz a data que o PRÓPRIO documento declara ("DATA EMISSÃO:
    11/11/2026" no relatório FIPE), não a data-base/DITCD que a redação repetiu. Só troca quando o documento diz a data
    de emissão com todas as letras; sem isso, a linha fica como está."""
    import pymupdf
    pasta = ctx.pasta / "documento"
    if not pasta.is_dir():
        return
    docs = []
    for f in pasta.glob("*.pdf"):
        try:
            with pymupdf.open(f) as d:
                m = _EMISSAO_DOC.search(" ".join(d[0].get_text().split())) if len(d) else None
        except Exception:                   # noqa: BLE001 — PDF que não abre fica de fora
            continue
        if m:
            docs.append((_palavras_doc(f.stem.replace("-", " ").replace("_", " ")), m.group(1)))
    for ln in linhas:
        if len(ln) < 3 or not re.fullmatch(r"\d{2}/\d{2}/\d{4}", (ln[2] or "").strip()):
            continue
        w = _palavras_doc(ln[0])
        notas = sorted(((len(w & pal), d) for pal, d in docs), reverse=True)
        if notas and notas[0][0] >= 2 and (len(notas) == 1 or notas[1][0] < notas[0][0]) and notas[0][1] != ln[2].strip():
            ln[2] = notas[0][1]


def _anexo_real_no_quadro(ctx: _Ctx, linhas: list[list[str]]) -> None:
    """113-1c: a coluna "Observação" do quadro do item 6 diz o anexo em que o documento SAI de verdade. A redação
    escrevia "Anexo IV" para a fatura da SANEAGO (comprovante de endereço do imóvel), mas a montagem a põe no Anexo
    III (documentação do imóvel). Cada linha casa com o arquivo de mais palavras em comum (como a 092-7)."""
    imovel, sol = _arquivos_doc(ctx)
    rel_md, _ = mapa_digital(ctx.job)
    arquivos = [(r, "Anexo III") for r in imovel] + [(r, "Anexo IV") for r in sol]
    if not arquivos and not rel_md:
        return
    palavras = [(_palavras_doc(_rotulo_extraido(ctx, r, completo=True) or PurePosixPath(r).stem), a) for r, a in arquivos]
    for ln in linhas:
        if len(ln) < 4 or not re.search(r"\bAnexo\s+I(?:II|V)\b", ln[3]):
            continue
        if re.search(r"(?i)mapa digital", ln[0]):
            certo = "Anexo III" if rel_md else ""
        else:
            w = _palavras_doc(ln[0])
            notas = [(len(w & pw), a) for pw, a in palavras]
            melhor = max(notas, default=(0, ""))
            iguais = {a for n, a in notas if n == melhor[0]}
            certo = melhor[1] if melhor[0] >= 2 and len(iguais) == 1 else ""   # empate ou casamento fraco: não mexe
        if certo:
            ln[3] = re.sub(r"\bAnexo\s+I(?:II|V)\b", certo, ln[3])


def _na_ordem_do_quadro(ctx: _Ctx, rels: list[str]) -> list[str]:
    """092-7: o Anexo III segue a ordem das linhas do quadro "Documentação analisada" (item 6). Cada arquivo vai
    para a linha com mais palavras em comum com o rótulo dele; o que não casa fica no fim, na ordem de antes."""
    linhas = [ln.split("|")[0] for ln in (ctx.textos.secoes.get("6") or "").splitlines() if ln.count("|") >= 3]
    if not linhas:
        return rels
    rel_md, _ = mapa_digital(ctx.job)
    alvos = [_palavras_doc(x) for x in linhas]

    def pos(rel: str) -> int:
        if rel == rel_md:
            return next((i for i, x in enumerate(linhas) if re.search(r"(?i)mapa digital", x)), len(linhas))
        w = _palavras_doc(_rotulo_extraido(ctx, rel, completo=True) or PurePosixPath(rel).stem)
        notas = [len(w & a) for a in alvos]
        melhor = max(notas) if notas else 0
        return notas.index(melhor) if melhor > 0 else len(linhas)
    return [r for _, _, r in sorted((pos(r), i, r) for i, r in enumerate(rels))]
