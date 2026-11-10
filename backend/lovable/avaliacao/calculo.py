"""Cálculo determinístico da avaliação (método comparativo, valor unitário)."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .modelos import Referencial

_CENT = Decimal("0.01")
_MIL = Decimal("1000")
_UM = Decimal("1")


@dataclass
class Resultado:
    unitarios: list[Decimal]
    minimo: Decimal
    maximo: Decimal
    media: Decimal
    unitario_adotado: Decimal
    valor_calculado: Decimal
    valor_adotado: Decimal
    faixa_pct: Decimal
    valor_min: Decimal
    valor_max: Decimal
    extenso: str
    excluidos: list[tuple[int, str]] = field(default_factory=list)


def _q(v: Decimal, passo: Decimal) -> Decimal:
    return v.quantize(passo, rounding=ROUND_HALF_UP)


def _dec(v: float | int | str) -> Decimal:
    return Decimal(str(v))


def calcular(
    area_m2: Decimal,
    refs: list[Referencial],
    unitario_adotado: Decimal | None = None,
    faixa_pct: Decimal = Decimal("10"),
) -> Resultado:
    unitarios: list[Decimal] = []
    excluidos: list[tuple[int, str]] = []
    for r in refs:
        if not r.area_m2 or _dec(r.area_m2) <= 0:
            excluidos.append((r.n, "área construída ausente"))
            continue
        if not r.preco or _dec(r.preco) <= 0:
            excluidos.append((r.n, "preço ausente"))
            continue
        unitarios.append(_q(_dec(r.preco) / _dec(r.area_m2), _CENT))
    if not unitarios:
        raise ValueError("nenhum referencial válido para o cálculo")

    minimo, maximo = min(unitarios), max(unitarios)
    media = _q(sum(unitarios, Decimal(0)) / len(unitarios), _CENT)
    if unitario_adotado is None:
        unitario_adotado = media
    elif not (minimo <= unitario_adotado <= maximo):
        raise ValueError(
            f"unitário adotado {unitario_adotado} fora do intervalo [{minimo}, {maximo}]"
        )

    valor_calculado = _q(area_m2 * unitario_adotado, _CENT)
    valor_adotado = _q(valor_calculado / _MIL, _UM) * _MIL
    fator = faixa_pct / Decimal(100)
    return Resultado(
        unitarios=unitarios,
        minimo=minimo,
        maximo=maximo,
        media=media,
        unitario_adotado=unitario_adotado,
        valor_calculado=valor_calculado,
        valor_adotado=valor_adotado,
        faixa_pct=faixa_pct,
        valor_min=_q(valor_adotado * (1 - fator), _UM),
        valor_max=_q(valor_adotado * (1 + fator), _UM),
        extenso=por_extenso(valor_adotado),
        excluidos=excluidos,
    )


# ---------------------------------------------------------------- por extenso
_UNID = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove",
         "dez", "onze", "doze", "treze", "quatorze", "quinze", "dezesseis",
         "dezessete", "dezoito", "dezenove"]
_DEZ = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta",
        "oitenta", "noventa"]
_CENTS = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos",
          "seiscentos", "setecentos", "oitocentos", "novecentos"]


def _grupo(n: int) -> str:
    """Escreve 1..999."""
    if n == 100:
        return "cem"
    partes = []
    c, resto = divmod(n, 100)
    if c:
        partes.append(_CENTS[c])
    if resto:
        if resto < 20:
            partes.append(_UNID[resto])
        else:
            d, u = divmod(resto, 10)
            partes.append(_DEZ[d] + (f" e {_UNID[u]}" if u else ""))
    return " e ".join(partes)


_ESCALAS = [  # (valor, singular, plural)
    (10**9, "bilhão", "bilhões"),
    (10**6, "milhão", "milhões"),
    (10**3, "mil", "mil"),
]


def _inteiro(n: int) -> str:
    if n == 0:
        return "zero"
    blocos: list[tuple[int, str]] = []  # (valor do bloco, texto)
    resto = n
    for escala, sing, plur in _ESCALAS:
        q, resto = divmod(resto, escala)
        if q:
            if escala == 10**3 and q == 1:
                blocos.append((q, "mil"))
            else:
                blocos.append((q, f"{_grupo(q)} {sing if q == 1 else plur}"))
    if resto:
        blocos.append((resto, _grupo(resto)))
    texto = blocos[0][1]
    for i in range(1, len(blocos)):
        valor, t = blocos[i]
        # "e" antes de bloco < 100 ou centena redonda; senão vírgula
        texto += f" e {t}" if (valor < 100 or valor % 100 == 0) else f", {t}"
    return texto


def por_extenso(v: Decimal) -> str:
    """Valor em reais por extenso, pt-BR, primeira letra maiúscula."""
    v = _q(Decimal(v), _CENT)
    reais = int(v)
    centavos = int((v - reais) * 100)
    if reais == 0 and centavos == 0:
        txt = "zero reais"
    else:
        partes = []
        if reais:
            base = _inteiro(reais)
            if reais == 1:
                moeda = "real"
            elif reais % 10**6 == 0:
                moeda = "de reais"
            else:
                moeda = "reais"
            partes.append(f"{base} {moeda}")
        if centavos:
            partes.append(f"{_inteiro(centavos)} {'centavo' if centavos == 1 else 'centavos'}")
        txt = " e ".join(partes)
    return txt[0].upper() + txt[1:]
