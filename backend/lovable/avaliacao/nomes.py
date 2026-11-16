"""Nome do arquivo final (D-020): `Nº - Cliente - Tipo - Bairro/Condomínio - Cidade`."""
from __future__ import annotations

import re

from .modelos import Trabalho

_PROIBIDOS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MAX_PARTE = 60     # um solicitante de 300 letras estourava os 255 bytes do nome de arquivo
MAX_NOME = 180     # e a entrega falhava com o trabalho preso em "executando"


def _limpo(s) -> str:
    return " ".join(_PROIBIDOS.sub("", str(s)).split())[:MAX_PARTE].strip(" .")


_PJ = re.compile(r"(?i)\b(ltda|s/?a|eireli|me|epp|participa[cç][oõ]es|empreendimentos|"
                 r"comercial|ind[uú]stria|imobili[aá]ria|condom[ií]nio)\b")


# ORDEM 013 g: o avaliador às vezes cola a qualificação inteira no campo "Solicitante"
# (razão social, CNPJ, sede, representante e CPF do representante).
_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_FIM_NOME = re.compile(r"(?i)\s*(?:,|;|\(|\s-\s|\s–\s|\binscrit[ao]\b|\bCNPJ\b|\bCPF\b|"
                       r"\bpessoa jur[ií]dica\b|\bcom sede\b|\bsediad[ao]\b|\bneste ato\b|"
                       r"\brepresentad[ao]\b|\bportador[a]?\b|\bbrasileir[ao]\b)")
_REPRESENTANTE = re.compile(r"(?i)[,;]?\s*(?:neste ato\s+)?(?:representad[ao]|por seu|por sua|"
                            r"atrav[eé]s de seu|na pessoa de|s[oó]ci[ao]|administrador[a]?)\b.*$",
                            re.S)
_DOC_PESSOAL = re.compile(r"(?i)[,;]?\s*\b(?:CPF|RG|CNH)\b[^,;]*")


def nome_solicitante(cliente: str) -> str:
    """Só o nome (pessoa) ou a razão social (empresa): o que aparece na tela, nas listas e
    nos logs. "ALFA LTDA, inscrita no CNPJ…, neste ato representada por…" -> "ALFA LTDA"."""
    c = " ".join(str(cliente or "").split())
    nome = _FIM_NOME.split(c, maxsplit=1)[0].strip(" .,;-–")
    return _CPF.sub("", nome).strip(" .,;-–") or _CPF.sub("", c)[:120].strip()


def qualificacao_laudo(cliente: str) -> str:
    """O que vai no laudo como solicitante. Empresa (P1, PJ): razão social, CNPJ e sede,
    SEM o representante e o CPF dele. Pessoa: só o nome (sem CPF/RG)."""
    c = " ".join(str(cliente or "").split())
    if not _PJ.search(c) and "cnpj" not in c.lower():
        return nome_solicitante(c)
    c = _REPRESENTANTE.sub("", c)
    c = _DOC_PESSOAL.sub("", c)
    c = _CPF.sub("", c)
    return " ".join(c.split()).strip(" ,;-–")


def cliente_curto(cliente: str) -> str:
    """D-020: primeiro nome da pessoa ("Maria Souza Lima" -> "Maria"); empresa fica
    com o nome inteiro (só a razão social, sem a qualificação)."""
    c = nome_solicitante(cliente)
    return c if _PJ.search(c) else (c.split(" ")[0] if c else c)


def tipo_curto(tipo: str) -> str:
    """D-020: tipo do imóvel sem o qualificativo ("Sobrado residencial" -> "Sobrado")."""
    t = " ".join(re.sub(r"\s*\([^)]*\)", "", str(tipo or "")).split())     # 074-D: sem "(IPTU predial)"
    t = re.split(r"\s+(?:residencial|comercial|resid\.|com\.)\b", t, flags=re.I)[0] or t
    return t[:1].upper() + t[1:]


_CONDO = re.compile(r"(?i)^\s*(ed\.|edif[ií]cio|condom[ií]nio|cond\.|residencial|res\.|torre|"
                   r"conjunto|jardins?\b)")


def local_curto(bairro: str) -> str:
    """D-020: "Bairro ou condomínio" com os dois ("Ed. Residencial Exemplo – Setor Exemplo
    Continuação") -> só o condomínio; bairro sozinho fica como está."""
    b = " ".join(str(bairro or "").split())
    partes = [x.strip() for x in re.split(r"\s+[–—-]\s+", b) if x.strip()]
    if len(partes) >= 2:
        condo = next((x for x in partes if _CONDO.match(x)), None)
        if condo:
            return condo
    return b


def nome_arquivo(t: Trabalho) -> str:
    nome = " - ".join(_limpo(x) for x in (t.numero, cliente_curto(t.cliente), tipo_curto(t.tipo),
                                          local_curto(t.bairro), t.cidade))
    return nome[:MAX_NOME].strip(" .-") or str(t.numero)
