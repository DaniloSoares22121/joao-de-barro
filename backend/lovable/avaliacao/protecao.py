"""ORDEM 026 v2 — F3: proteção antes da base comum (D-061).

Duas travas: 1) regras (aqui, sem IA): tira nomes de pessoas e empresas do trabalho, CPF,
CNPJ, RG, CEP, endereço (rua, quadra, lote, número), matrícula, inscrição imobiliária, links
(Maps, anúncios), e-mail e telefone; valores e áreas viram faixa ("entre 1.500 e 2.500 m²",
"R$/m² entre 2.500 e 3.500"). 2) a IA (proteger_com_ia), que pega o que as regras não pegaram.
O curador vê a ficha já protegida."""
from __future__ import annotations

import re
import unicodedata

CAMPOS_TEXTO = ("titulo", "situacao", "decisao", "porque")
_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
_CEP = re.compile(r"\b\d{5}-?\d{3}\b|\bCEP\s*:?\s*\d[\d.\-]{6,}", re.I)
_RG = re.compile(r"(?i)\bRG\b[^,;\n]{0,15}?\d[\d.\-/xX]{4,}")
_URL = re.compile(r"(?i)\bhttps?://\S+|\bwww\.\S+|\bmaps\.app\.goo\.gl/\S+")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_TEL = re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b")
_MATRICULA = re.compile(r"(?i)\bmatr[ií]cula\s*(?:n[ºo°.]*\s*)?\d[\d.\-/]*")
_INSCRICAO = re.compile(r"(?i)\binscri[çc][ãa]o(?:\s+(?:imobili[áa]ria|municipal|cadastral))?\s*(?:n[ºo°.]*\s*)?\d[\d.\-/]{3,}"
                        r"|\b\d\.\d{3}\.\d{5}\.\d{4}(?:\.\d{1,4})?\b")
_QUADRA_LOTE = re.compile(r"(?i)\b(?:qd|quadra|q)\.?\s*\d+[a-z\-]*\s*,?\s*(?:lt|lote|l)\.?\s*[\d\-]+[a-z]?\b"
                          r"|\b(?:quadra|qd)\.?\s*\d+[a-z\-]*\b|\b(?:lote|lt)\.?\s*\d+[\d\-]*[a-z]?\b")
_RUA = re.compile(r"(?i)\b(?:rua|r\.|avenida|av\.|alameda|travessa|rodovia|estrada|pra[çc]a)\s+[^,;\n]{1,40}?"
                  r"(?=[,;\n]|$|\s+(?:n[ºo°]|qd|quadra|lote|lt)\b)")
_NUM_ENDERECO = re.compile(r"(?i)\bn[ºo°]\.?\s*\d+\b")
_AREA = re.compile(r"(?i)(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(m²|m2|metros quadrados)")
_REAL = re.compile(r"(?i)R\$\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)(\s*/\s*m²|\s*/\s*m2)?")
_EMPRESA = re.compile(r"(?i)\b[A-ZÀ-Ú][\wÀ-ú&.\-]*(?:\s+[A-ZÀ-Ú&][\wÀ-ú&.\-]*){0,5}\s+(?:LTDA|S/?A|EIRELI|ME|EPP)\b\.?")


def _num_br(s: str) -> float:
    s = s.strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        s = s.replace(".", "")
    return float(s)


def _faixa(v: float, passos=(100, 250, 500, 1000, 2500, 5000, 10000, 50000, 100000, 500000, 1000000, 5000000)) -> tuple[float, float]:
    """Faixa "redonda" que contém v (largura ~ metade da ordem de grandeza)."""
    passo = next((p for p in passos if v < p * 10), passos[-1])
    lo = (v // passo) * passo
    return lo, lo + passo


def _fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def _area_faixa(m: re.Match) -> str:
    try:
        lo, hi = _faixa(_num_br(m.group(1)))
    except ValueError:
        return "área (faixa)"
    return f"entre {_fmt(lo)} e {_fmt(hi)} {m.group(2)}"


def _real_faixa(m: re.Match) -> str:
    try:
        lo, hi = _faixa(_num_br(m.group(1)))
    except ValueError:
        return "R$ (faixa)"
    por = "/m²" if m.group(2) else ""
    return f"R${por} entre {_fmt(lo)} e {_fmt(hi)}"


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def termos_do_trabalho(job_id: str | None) -> list[str]:
    """Nomes e endereços do trabalho (solicitante, campos de documento) para tirar do texto."""
    if not job_id:
        return []
    from . import db
    from .nomes import nome_solicitante
    out: list[str] = []
    try:
        dados = db.job(job_id)["dados"]
    except Exception:
        return out
    cli = nome_solicitante(dados.get("cliente") or "")
    if cli:
        out.append(cli)
        out += [p for p in re.split(r"\s+", cli) if len(p) >= 4 and p.upper() not in ("LTDA", "EIRELI")]
    for c in db.campos(job_id):
        n = _sem_acento(c.nome).casefold()
        if any(k in n for k in ("proprietar", "titular", "solicitante", "ocupante", "endereco", "logradouro",
                                "nome", "empresa", "placa")):
            v = str(c.valor or "")
            if 3 <= len(v) <= 200:
                out.append(v.split(" (")[0].split(" – ")[0].strip())
    return sorted({t for t in out if len(t) >= 4}, key=len, reverse=True)


def proteger_texto(s: str, termos: list[str] = ()) -> str:
    """Trava 1 (regras)."""
    if not s:
        return s
    for t in termos:
        s = re.sub(re.escape(t), "[dado do trabalho]", s, flags=re.I)
    for rx, troca in ((_URL, "[link]"), (_EMAIL, "[e-mail]"), (_CNPJ, "[CNPJ]"), (_CPF, "[CPF]"),
                      (_RG, "[RG]"), (_CEP, "[CEP]"), (_MATRICULA, "matrícula [nº]"),
                      (_INSCRICAO, "inscrição [nº]"), (_QUADRA_LOTE, "[quadra/lote]"),
                      (_RUA, "[endereço]"), (_NUM_ENDERECO, "[nº]"), (_EMPRESA, "[empresa]"), (_TEL, "[telefone]")):
        s = rx.sub(troca, s)
    s = _REAL.sub(_real_faixa, s)
    s = _AREA.sub(_area_faixa, s)
    return re.sub(r"(\[dado do trabalho\]\s*){2,}", "[dado do trabalho] ", s).strip()


def proteger_ficha(d: dict, job_id: str | None = None) -> dict:
    termos = termos_do_trabalho(job_id)
    return {**d, **{k: proteger_texto(str(d.get(k) or ""), termos) for k in CAMPOS_TEXTO}}


def identificadores(job_id: str) -> list[str]:
    """O que identifica o trabalho (para o teste de que nada vaza): nome do solicitante, endereço,
    inscrição, matrícula, valor exato."""
    from . import db
    out = termos_do_trabalho(job_id)
    for c in db.campos(job_id):
        n = _sem_acento(c.nome).casefold()
        if any(k in n for k in ("inscricao", "matricula", "endereco", "logradouro")):
            out.append(str(c.valor))
    calc = db.resultado(job_id, "calculo") or {}
    for k in ("valor_adotado",):
        if calc.get(k):
            v = int(float(calc[k]))
            out += [str(v), _fmt(v)]
    return [x for x in out if x and len(x) >= 4]


INSTRUCAO_IA = """\
Revise a ficha de conhecimento abaixo e TIRE qualquer coisa que identifique um cliente ou um
imóvel: nomes de pessoas e empresas, CPF, CNPJ, RG, endereço (rua, quadra, lote, número, CEP),
matrícula, inscrição imobiliária, links, valores e áreas exatos (troque por faixas). Mantenha o
raciocínio (situação, decisão, porquê) igual. Devolva a ficha no mesmo formato."""


async def proteger_com_ia(d: dict, job_id: str | None = None) -> dict:
    """Trava 2 (IA), depois da trava das regras; se a IA falhar, fica a trava 1 (e a ficha
    continua indo para o curador revisar)."""
    from pydantic import BaseModel

    from . import ia

    class _F(BaseModel):
        titulo: str
        situacao: str
        decisao: str
        porque: str
    d1 = proteger_ficha(d, job_id)
    try:
        r: _F = await ia.perguntar(INSTRUCAO_IA, str({k: d1.get(k, "") for k in CAMPOS_TEXTO}), _F)
        return proteger_ficha({**d1, **r.model_dump()}, job_id)
    except Exception:
        return d1
