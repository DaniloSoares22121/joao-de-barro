"""Agente de Extração: lê os documentos/fotos do job e devolve os campos com origem.
Regras críticas (descarte de documento de outro imóvel, campo sem fonte, caixas inválidas)
são aplicadas em código, não confiadas à IA."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel

from .. import conhecimento, db, ia
from ..modelos import Campo
from . import _comum

Caixa = tuple[int, int, int, int]

INSTRUCAO = """\
ETAPA ATUAL: EXTRAÇÃO DE DADOS.
Você é o agente de extração do João de Barro. Leia com a ferramenta Read TODOS os arquivos
listados no pedido (caminhos relativos à pasta de trabalho) e extraia os dados do imóvel.
Regras obrigatórias:
1. Classifique a origem de cada campo: "documento" (lido em IPTU, matrícula, escritura,
   planta etc.; informe em "fonte" o caminho do arquivo e, se possível, a página),
   "vistoria" (observado nas fotos), "inferido" (dedução explicada em "observacao") ou
   "pendente" (não encontrado).
2. NUNCA invente. Dado não encontrado = origem "pendente" com valor null.
3. A informação verbal do formulário (campo "contexto") NUNCA é campo com origem
   "documento" (D-013). Não a transforme em dado do laudo.
4. Documento de OUTRO imóvel (quadra/lote/endereço diferente do IPTU/matrícula) vai em
   "documentos_descartados" com o motivo, e nenhum campo pode ter esse arquivo como fonte.
5. Em "quadras_lotes" informe, para cada documento, a quadra e o lote que ele indica e o
   "papel" do documento classificado pelo CONTEÚDO (não pelo nome do arquivo): "iptu",
   "matricula" ou "outro".
6. Aponte divergências entre documentos em "divergencias".
7. Fotos: para cada foto de vistoria dê legenda deduzida pela imagem e ordem sugerida
   (fachada primeiro). "fachada_caixa" = [x0, y0, x1, y1] em pixels da fachada na foto
   principal. "tarjas" = caixas [x0, y0, x1, y1] por arquivo a tarjar (placas, rostos,
   documentos pessoais). Chave = caminho do arquivo; para imagem, caixas em pixels da
   imagem. Para PDF, a chave é "<arquivo>#p<N>" (N = página, começando em 1) e as caixas
   ficam em pontos PDF (1/72 pol., origem no canto superior esquerdo da página).
   Documento do solicitante (RG, CNH, CPF, OAB) SEM caixas de tarja NÃO é anexado ao laudo:
   sempre informe as caixas dos dados pessoais sensíveis (nº de documentos, CPF, filiação,
   assinatura, foto) de cada página.
8. "documentos": para cada documento do imóvel/solicitante lido, dê "rotulo_curto"
   (ex.: "IPTU 2025") e "rotulo_completo" (ex.: "Notificação de lançamento do IPTU 2025 –
   inscrição 000.000.0459.0002"), deduzidos do CONTEÚDO, nunca do nome do arquivo.
"""


class DocDescartado(BaseModel):
    arquivo: str
    motivo: str


class FotoVistoria(BaseModel):
    arquivo: str
    legenda: str
    ordem: int


class DocInfo(BaseModel):
    arquivo: str
    rotulo_curto: str
    rotulo_completo: str


class QuadraLote(BaseModel):
    arquivo: str
    papel: Literal["iptu", "matricula", "outro"] = "outro"
    quadra: str = ""
    lote: str = ""


class _RespostaIA(BaseModel):
    """O que a IA devolve (caixas soltas; validadas no pós-processamento)."""
    campos: list[Campo] = []
    divergencias: list[str] = []
    documentos_descartados: list[DocDescartado] = []
    quadras_lotes: list[QuadraLote] = []
    fachada_caixa: list[float | None] | None = None
    fotos: list[FotoVistoria] = []
    tarjas: dict[str, list[list[float | None] | None]] = {}
    documentos: list[DocInfo] = []


class Extracao(BaseModel):
    campos: list[Campo]
    divergencias: list[str] = []
    documentos_descartados: list[DocDescartado] = []
    fachada_caixa: Caixa | None = None
    fotos: list[FotoVistoria] = []
    tarjas: dict[str, list[Caixa]] = {}
    documentos: list[DocInfo] = []


def _norm(v) -> str:
    """Normaliza quadra/lote: '  QD. 050' -> '50', 'LT 029' -> '29'."""
    s = str(v or "").strip().upper()
    # prefixo só sai se seguido de dígito/separador: quadra "L" ou "Q" sozinha fica
    s = re.sub(r"^(QUADRA|LOTE|QD|LT|Q|L)(?=[\s.:º°-]|\d)[\s.:º°-]*", "", s)
    s = s.replace(" ", "")
    return s.lstrip("0") or ("0" if s else "")


def _caixa(c) -> Caixa | None:
    if not c or len(c) != 4 or any(v is None for v in c):
        return None
    try:
        x0, y0, x1, y1 = (int(round(float(v))) for v in c)
    except (TypeError, ValueError, OverflowError):  # OverflowError: inf
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return (max(x0, 0), max(y0, 0), x1, y1)


_IMAGENS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".gif"}
SEM_REFERENCIA = ("documento de referência do imóvel não identificado; "
                  "verificação de outro imóvel não executada")


def _chave(nome: str) -> str:
    return PurePosixPath(str(nome).replace("\\", "/").strip()).name.casefold()


def _citados(fonte: str, nomes: set[str]) -> set[str]:
    """Nomes (chave normalizada) de arquivos citados em `fonte`, por token exato:
    'a.pdf' não casa com 'planta_a.pdf'."""
    f = fonte.replace("\\", "/").casefold()
    achados = set()
    for n in nomes:
        if n and re.search(r"(?<![\w.-])" + re.escape(n) + r"(?![\w-])", f):
            achados.add(n)
    return achados


def _referencia(qls: list[QuadraLote]) -> QuadraLote | None:
    """Quadra/lote do IPTU (ou, na falta, da matrícula), pelo papel dado pela IA."""
    for papel in ("iptu", "matricula"):
        for q in qls:
            if q.papel == papel and (q.quadra or q.lote):
                return q
    return None


def _difere(q: QuadraLote, ref: QuadraLote) -> str:
    for rotulo, a, b in (("quadra", q.quadra, ref.quadra), ("lote", q.lote, ref.lote)):
        if a and b and _norm(a) != _norm(b):
            return f"{rotulo} {a} ≠ {b} ({ref.arquivo})"
    return ""


def _pos(r: _RespostaIA, registrados: list[dict]) -> Extracao:
    nomes = {_chave(a[k]) for a in registrados for k in ("nome", "caminho") if a.get(k)}
    fotos = {n for n in nomes if PurePosixPath(n).suffix in _IMAGENS} | {
        _chave(a[k]) for a in registrados if a.get("tipo") == "foto"
        for k in ("nome", "caminho") if a.get(k)}
    divergencias = list(r.divergencias)
    descartes = {_chave(d.arquivo): d for d in r.documentos_descartados}
    ref = _referencia(r.quadras_lotes)
    if ref is None:
        divergencias.append(SEM_REFERENCIA)
    else:
        for q in r.quadras_lotes:
            k = _chave(q.arquivo)
            if k == _chave(ref.arquivo) or k in descartes:
                continue
            dif = _difere(q, ref)
            if not dif:
                continue
            if q.papel in ("iptu", "matricula"):
                divergencias.append(f"{q.papel} {q.arquivo} diverge do documento de referência: {dif}")
            else:
                descartes[k] = DocDescartado(arquivo=q.arquivo,
                                             motivo=f"documento de outro imóvel: {dif}")
    campos = []
    for c in r.campos:
        cit = _citados(c.fonte, nomes | set(descartes))
        if cit & set(descartes):
            continue
        validos = cit & (fotos if c.origem == "vistoria" else nomes)
        if c.origem in ("documento", "vistoria") and not validos:
            c = c.model_copy(update={
                "origem": "pendente",
                "observacao": (c.observacao + " " if c.observacao else "")
                + f"sem fonte em arquivo registrado ({c.origem}) — conferir"})
        campos.append(c)
    tarjas = {}
    for arq, cxs in r.tarjas.items():
        boas = [b for b in (_caixa(x) for x in cxs if x is not None) if b]
        if boas:
            tarjas[arq] = boas
    return Extracao(campos=campos, divergencias=divergencias,
                    documentos_descartados=list(descartes.values()),
                    fachada_caixa=_caixa(r.fachada_caixa), fotos=r.fotos, tarjas=tarjas,
                    documentos=r.documentos)


# Nomes de campo que o avaliador pode criar à mão (além dos já extraídos no job). Os rótulos
# do revisor (OBRIGATORIOS_IMOVEL) também valem: as pendências "n/i" apontam para eles.
CAMPOS_CONHECIDOS = (
    "endereco", "area_terreno", "area_construida", "padrao", "padrao_construtivo",
    "estado_conservacao", "idade_aparente", "quadra", "lote", "matricula", "inscricao_iptu",
    "solicitante", "proprietario", "benfeitorias", "testada", "tipologia", "quartos", "suites",
    "banheiros", "vagas")


def _norm_nome(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def nome_permitido(job_id: str, nome: str) -> bool:
    from .revisor import OBRIGATORIOS_IMOVEL
    alvo = _norm_nome(nome)
    ok = {_norm_nome(x) for x in (*CAMPOS_CONHECIDOS, *OBRIGATORIOS_IMOVEL)}
    ok |= {_norm_nome(c.nome) for c in db.campos(job_id)}
    return bool(alvo) and alvo in ok


def _mesmo_valor(a, b) -> bool:
    def n(v):
        if v is None:
            return ""
        t = v.strip() if isinstance(v, str) else v
        if isinstance(t, str) and "," in t:          # 1.234,5 (BR)
            t = t.replace(".", "").replace(",", ".")
        try:
            return float(t)
        except (TypeError, ValueError):
            return str(v).strip().casefold()
    return n(a) == n(b)


def divergencias_manuais(job_id: str, extraidos: list[Campo]) -> list[str]:
    """Campos em que a nova extração diverge do valor editado à mão (o editado prevalece)."""
    ed = edicoes_manuais(job_id)
    return [f"{c.nome}: extraído {c.valor} ≠ editado pelo avaliador {ed[c.nome].valor} "
            "(mantido o valor editado)"
            for c in extraidos if c.nome in ed and c.valor is not None
            and not _mesmo_valor(c.valor, ed[c.nome].valor)]


def edicoes_manuais(job_id: str) -> dict[str, Campo]:
    """Última edição manual do avaliador por campo (eventos 'edicao_manual' da extração)."""
    with db._conn() as c:
        rows = c.execute("SELECT dados_json FROM av_events WHERE job=? AND etapa='extracao' "
                         "AND nivel='edicao_manual' AND dados_json IS NOT NULL ORDER BY id",
                         (job_id,)).fetchall()
    out: dict[str, Campo] = {}
    for r in rows:
        try:
            c = Campo.model_validate(json.loads(r["dados_json"])["campo"])
        except Exception:
            continue
        out[c.nome] = c
    return out


def com_edicoes_manuais(job_id: str, campos: list[Campo]) -> list[Campo]:
    """A edição manual do avaliador prevalece sobre o que a IA extrair de novo."""
    ed = edicoes_manuais(job_id)
    out = [ed.pop(c.nome, c) for c in campos]
    return out + list(ed.values())


async def rodar(job_id: str) -> Extracao:
    t = _comum.trabalho(job_id)
    pasta, rels = _comum.arquivos(job_id)
    sistema = conhecimento.texto("P0", "P3", "P5", "P7") + "\n\n" + INSTRUCAO
    prompt = (
        'Formulário do trabalho (JSON; o campo "contexto" é informação verbal, NUNCA '
        "documento):\n" + t.model_dump_json(indent=2)
        + "\n\nLeia com Read estes arquivos (caminhos relativos à pasta de trabalho):\n"
        + _comum.lista(rels)
        + db.texto_correcoes(job_id, "extracao"))
    bruto: _RespostaIA = await ia.perguntar(sistema, prompt, _RespostaIA, arquivos=rels, cwd=pasta)
    r = _pos(bruto, db.arquivos(job_id))
    divs = divergencias_manuais(job_id, r.campos)
    for d in divs:
        db.evento(job_id, "extracao", "aviso", f"divergência com edição manual: {d}")
    r = r.model_copy(update={"campos": com_edicoes_manuais(job_id, r.campos),
                             "divergencias": [*r.divergencias, *divs]})
    if SEM_REFERENCIA in r.divergencias:
        db.evento(job_id, "extracao", "aviso", SEM_REFERENCIA)
    db.salvar_campos(job_id, r.campos)
    db.evento(job_id, "extracao", "resultado",
              f"{len(r.campos)} campos, {len(r.documentos_descartados)} documento(s) descartado(s)",
              dados=r.model_dump(mode="json"))
    return r
