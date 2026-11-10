"""Agente de Seleção: a IA escolhe/justifica; regras objetivas aplicadas em código."""
from __future__ import annotations

import statistics
from datetime import date
import unicodedata
import re
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel

from .. import calculo, conhecimento, db, ia
from ..modelos import Referencial
from . import _comum

MIN_ESCOLHIDOS = 5

INSTRUCAO = """\
ETAPA ATUAL: SELEÇÃO DE REFERENCIAIS.
Para CADA candidato decida "escolhido" e escreva "justificativa" (sempre não vazia).
Exclua, explicando na justificativa: tipologia diferente (ex.: apartamento para casa),
imóvel novo/em acabamento para avaliando antigo (e vice-versa), padrão superior
(piscina, área gourmet de alto padrão etc.), imóvel de renda multi-unidade, lote com duas
casas, anúncio contraditório. Procure ao menos 5 semelhantes.
Opcionalmente proponha "unitario_adotado" (R$/m², dentro do intervalo dos escolhidos) com
"justificativa_unitario", e "faixa_pct" (padrão 10, entre 0 e 30).
Para TODO candidato não escolhido informe "motivo_exclusao": "regra" (excluído por uma das
regras acima ou tipologia diferente) ou "menos_similar" (semelhante, mas menos que os
escolhidos).
"""


class _Decisao(BaseModel):
    n: int
    escolhido: bool
    justificativa: str = ""
    motivo_exclusao: Literal["regra", "menos_similar", ""] = ""


class _RespostaIA(BaseModel):
    decisoes: list[_Decisao] = []
    unitario_adotado: Decimal | None = None
    justificativa_unitario: str = ""
    faixa_pct: Decimal | None = None


class Selecao(BaseModel):
    refs: list[Referencial]
    unitario_adotado: Decimal | None = None
    justificativa_unitario: str = ""
    faixa_pct: Decimal = Decimal("10")
    declaracao_amostra: str = ""


def _n(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.casefold().split())


def _areas_construidas(job_id: str) -> list[tuple[Decimal, str, str]]:
    """(valor, origem, nome) de cada campo de área construída válido, documento primeiro:
    a medida da matrícula/IPTU vale mais que a estimada na vistoria."""
    out = []
    for c in db.campos(job_id):
        nome = _n(c.nome)
        if "area" in nome and "constru" in nome and c.origem in ("documento", "vistoria"):
            try:
                v = _decimal_br(c.valor)
            except (InvalidOperation, ValueError):
                continue
            if v.is_finite() and v > 0:
                out.append((v, c.origem, c.nome))
    out.sort(key=lambda x: x[1] != "documento")   # estável: mantém a ordem dentro da origem
    return out


def _area_construida(job_id: str):
    """(valor, origem) da área construída do avaliando: campo cujo nome contém 'area' e
    'constru' (origem documento antes de vistoria); (None, 'pendente') se não houver."""
    areas = _areas_construidas(job_id)
    return (areas[0][0], areas[0][1]) if areas else (None, "pendente")


def areas_divergentes(job_id: str) -> str:
    """Aviso quando os campos de área construída trazem valores diferentes ('' se não)."""
    areas = _areas_construidas(job_id)
    if len({v for v, _, _ in areas}) < 2:
        return ""
    lista = "; ".join(f"{nome}: {_br(float(v))} m²" for v, _, nome in areas)
    return (f"áreas construídas divergentes ({lista}); o cálculo usou {_br(float(areas[0][0]))} m² "
            f"({areas[0][2]}) — confira e, se preciso, edite o campo")


def area_construida(job_id: str) -> Decimal | None:
    return _area_construida(job_id)[0]


def origem_area_construida(job_id: str) -> str:
    return _area_construida(job_id)[1]


_RE_NUMERO = re.compile(r"-?\d[\d.]*(?:,\d+)?")


def _br(x: float) -> str:
    """1234.5 -> '1.234,50'."""
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _decimal_br(v) -> Decimal:
    """Aceita número ou texto pt-BR: '1.234,56', '364,00 m²', '180'. Usa só o PRIMEIRO
    número do texto: juntar todos os dígitos transformava '180 m2' em 1802 e
    '180 m² (IPTU 2025)' em 1.802.025."""
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    m = _RE_NUMERO.search(str(v or ""))
    if not m:
        raise InvalidOperation("sem número")
    t = m.group().rstrip(".")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1 or re.fullmatch(r"-?\d{1,3}\.\d{3}", t):
        t = t.replace(".", "")
    return Decimal(t)


def _campo(job_id: str, chave: str):
    for c in db.campos(job_id):
        if chave in _n(c.nome) and c.valor not in (None, ""):
            return c.valor
    return None


def _unit(r: Referencial) -> float:
    return r.preco / r.area_m2


_CLASSES_TIPO = (
    ("apartamento", ("apart", "apto", "flat", "kitnet", "kitchenette", "studio", "loft", "cobertura", "duplex")),
    ("casa", ("casa", "sobrado", "residencia", "chale", "bangalo")),
    ("terreno", ("lote", "terreno", "gleba")),
    ("rural", ("chacara", "sitio", "fazenda", "rural")),
    ("comercial", ("sala", "loja", "galpao", "comercial", "predio", "barracao", "salao")),
)


def classe_tipologia(tipo) -> str:
    """Classe da tipologia para comparar anúncios: 'Casa', 'Casa térrea' e 'Sobrado' são a
    mesma amostra. Texto que não casa com nenhuma classe fica como veio (normalizado)."""
    t = _n(tipo)
    for classe, chaves in _CLASSES_TIPO:
        if any(k in t for k in chaves):
            return classe
    return t


def _pontuacao(r: Referencial, tipo: str, bairro: str, area: Decimal | None,
               quartos: int | None, padrao: str, data_base: date | None = None) -> int:
    p = -PENALIDADE_VELHO if anuncio_velho(r, data_base) else 0
    if classe_tipologia(r.tipologia) == classe_tipologia(tipo):
        p += 3
    if _n(r.bairro) == _n(bairro):
        p += 2
    if area and abs(Decimal(str(r.area_m2)) - area) / area <= Decimal("0.3"):
        p += 2
    if quartos is not None and r.quartos == quartos:
        p += 1
    if padrao and _n(r.padrao) == _n(padrao):
        p += 1
    return p


FORA_DA_CURVA = "fora da curva estatística"
MIN_PARA_CURVA = 7          # válidos da mesma tipologia para aplicar a regra do IQR
IQR_MIN_PCT = 0.05          # piso do IQR: 5% da mediana (amostra quase igual não corta tudo)
DIAS_ANUNCIO_VELHO = 180
PENALIDADE_VELHO = 2


def fora_da_curva(cands: list[Referencial]) -> dict[int, str]:
    """n -> motivo dos candidatos com R$/m² fora de [Q1 − 1,5·IQR, Q3 + 1,5·IQR], por
    tipologia (só grupos com ≥ MIN_PARA_CURVA válidos; IQR com piso de IQR_MIN_PCT da
    mediana)."""
    grupos: dict[str, list[Referencial]] = {}
    for r in cands:
        if r.area_m2 and r.preco:
            grupos.setdefault(classe_tipologia(r.tipologia), []).append(r)
    out = {}
    for g in grupos.values():
        if len(g) < MIN_PARA_CURVA:
            continue
        q1, med, q3 = statistics.quantiles([_unit(r) for r in g], n=4, method="inclusive")
        iqr = max(q3 - q1, IQR_MIN_PCT * med)
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        for r in g:
            u = _unit(r)
            if u < lo or u > hi:
                out[r.n] = (f"{FORA_DA_CURVA}: R$ {_br(u)}/m² fora do intervalo "
                            f"R$ {_br(lo)} – {_br(hi)}/m² (quartis ± 1,5·IQR da tipologia)")
    return out


def anuncio_velho(r: Referencial, data_base: date | None) -> bool:
    """Anúncio publicado há mais de DIAS_ANUNCIO_VELHO dias da data-base."""
    if not r.publicado_em or data_base is None:
        return False
    try:
        pub = date.fromisoformat(r.publicado_em[:10])
    except ValueError:
        return False
    return (data_base - pub).days > DIAS_ANUNCIO_VELHO


async def rodar(job_id: str) -> Selecao:
    t = _comum.trabalho(job_id)
    cands = db.candidatos(job_id)
    area = area_construida(job_id)
    campos = [c.model_dump(mode="json") for c in db.campos(job_id)]
    curva = fora_da_curva(cands)   # regra objetiva, antes da IA
    sistema = conhecimento.texto("P0", "P3") + "\n\n" + INSTRUCAO
    prompt = ("Trabalho:\n" + t.model_dump_json(indent=2)
              + f"\n\nCampos do avaliando:\n{campos}\n\nCandidatos:\n"
              + "\n".join(r.model_dump_json(exclude={"foto", "print_"}) for r in cands)
              + db.texto_correcoes(job_id, "selecao"))
    if curva:
        prompt += ("\n\nExcluídos em código (não escolha; motivo_exclusao \"regra\"):\n"
                   + "\n".join(f"- n {n}: {m}" for n, m in sorted(curva.items())))
    resp: _RespostaIA = await ia.perguntar(sistema, prompt, _RespostaIA)
    dec = {d.n: d for d in resp.decisoes}
    for n, motivo in curva.items():
        dec[n] = _Decisao(n=n, escolhido=False, justificativa=f"excluído: {motivo}",
                          motivo_exclusao="regra")

    refs: list[Referencial] = []
    for r in cands:
        d = dec.get(r.n)
        if not r.area_m2 or not r.preco:
            upd = {"escolhido": False, "justificativa": "excluído: "
                   + ("área construída ausente" if not r.area_m2 else "preço ausente")}
        else:
            upd = {"escolhido": bool(d and d.escolhido),
                   "justificativa": (d.justificativa.strip() if d else "")
                   or "sem justificativa da IA — conferir"}
        refs.append(r.model_copy(update=upd))

    validos = [r for r in refs if r.area_m2 and r.preco]
    n_esc = sum(r.escolhido for r in refs)
    declaracao = ""
    if n_esc < MIN_ESCOLHIDOS:
        if len(validos) >= MIN_ESCOLHIDOS:
            q = _campo(job_id, "quarto")
            try:
                quartos = int(float(q)) if q is not None else None
            except (TypeError, ValueError):
                quartos = None
            padrao = str(_campo(job_id, "padrao") or "")
            mediana = statistics.median(_unit(r) for r in validos if r.n not in curva)
            resto = sorted((r for r in validos if not r.escolhido and r.n not in curva
                            and dec.get(r.n) and dec[r.n].motivo_exclusao == "menos_similar"
                            and classe_tipologia(r.tipologia) == classe_tipologia(t.tipo)), key=lambda r: (
                -_pontuacao(r, t.tipo, t.bairro, area, quartos, padrao, t.data_base),
                abs(_unit(r) - mediana)))
            falta = MIN_ESCOLHIDOS - n_esc
            add = {r.n for r in resto[:falta]}
            falta = len(add)
            refs = [r.model_copy(update={
                "escolhido": True,
                "justificativa": "incluído para completar a amostra mínima (maior "
                                 "similaridade entre os restantes); IA: " + r.justificativa})
                    if r.n in add else r for r in refs]
            if n_esc + falta < MIN_ESCOLHIDOS:
                declaracao = (f"Amostra reduzida: apenas {n_esc + falta} referencial(is) "
                              "semelhante(s) disponível(is) no mercado pesquisado.")
            else:
                declaracao = (f"Foram identificados apenas {n_esc} referencial(is) plenamente "
                            f"semelhante(s); a amostra foi completada com {falta} referencial(is) "
                            "de maior similaridade disponível no mercado.")
        else:
            declaracao = (f"Amostra reduzida: apenas {len(validos)} referencial(is) válido(s) "
                          "disponível(is) no mercado pesquisado.")

    faixa = Decimal("10")
    if resp.faixa_pct is not None:
        if Decimal("0") < resp.faixa_pct <= Decimal("30"):
            faixa = resp.faixa_pct
        else:
            db.evento(job_id, "selecao", "aviso",
                      f"faixa_pct {resp.faixa_pct} fora de (0, 30]; adotado 10")
    unitario, just_u = resp.unitario_adotado, resp.justificativa_unitario
    if unitario is not None:
        # centavos: com mais casas, "área × unitário" impresso no laudo não fecha com o valor
        unitario = unitario.quantize(Decimal("0.01"))
    divergencia = areas_divergentes(job_id)
    if divergencia:
        db.evento(job_id, "selecao", "aviso", divergencia)
    if area is None:
        db.evento(job_id, "selecao", "aviso", "área construída do avaliando ausente")
        unitario, just_u = None, ""
    elif unitario is not None:
        escolhidos = [r for r in refs if r.escolhido]
        try:
            calculo.calcular(area, escolhidos, unitario, faixa)
        except ValueError as e:
            db.evento(job_id, "selecao", "aviso", f"unitário adotado descartado: {e}")
            unitario, just_u = None, ""

    s = Selecao(refs=refs, unitario_adotado=unitario, justificativa_unitario=just_u,
                faixa_pct=faixa, declaracao_amostra=declaracao)
    db.salvar_candidatos(job_id, refs)
    db.evento(job_id, "selecao", "resultado",
              f"{sum(r.escolhido for r in refs)} de {len(refs)} referenciais escolhidos",
              dados=s.model_dump(mode="json"))
    return s
