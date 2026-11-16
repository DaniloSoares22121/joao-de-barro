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
from ..plural import pl

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


class PropostaIA(BaseModel):
    """O que a IA propôs (guardado para o avaliador comparar ao confirmar)."""
    unitario_adotado: Decimal | None = None
    justificativa_unitario: str = ""
    faixa_pct: Decimal | None = None


class Selecao(BaseModel):
    refs: list[Referencial]
    unitario_adotado: Decimal | None = None
    justificativa_unitario: str = ""
    faixa_pct: Decimal = Decimal("10")
    declaracao_amostra: str = ""
    # True quando o avaliador confirmou (ou trocou) unitário e faixa na tela; a redação só
    # começa depois disso (orquestrador pausa em AGUARDANDO_AVALIADOR)
    confirmado: bool = False
    proposta_ia: PropostaIA | None = None
    # 082-4: a amostra (nº, preço, áreas, usar) no momento em que o AVALIADOR fixou o unitário
    amostra: str = ""


ESCOLHA_MANUAL = "escolha manual do avaliador"
AMOSTRA_MUDOU = "A amostra mudou depois que você fixou o unitário"


def assinatura_amostra(refs) -> str:
    """Retrato da amostra usada no cálculo: mudou um preço, uma área ou quem entra → muda."""
    return "|".join(f"{r.n}:{r.preco}:{r.area_m2}:{r.lote_m2}" for r in sorted(
        (r for r in refs if r.escolhido), key=lambda r: r.n))


def unitario_valido(sel: "Selecao") -> tuple[Decimal | None, str]:
    """082-4 (trava de valor): (unitário a usar, problema). O padrão é a MÉDIA (None). Unitário fixo só com
    decisão escrita do avaliador (justificativa dele) e para a MESMA amostra; se a amostra mudou, volta a
    média e o problema é devolvido (o laudo para e pergunta)."""
    u = sel.unitario_adotado
    if u is None:
        return None, ""
    just = (sel.justificativa_unitario or "").strip()
    escrita = just.removeprefix(ESCOLHA_MANUAL).strip(" :")
    if not escrita or not sel.amostra:
        return None, ""                       # sem decisão escrita do avaliador: vale a média
    if sel.amostra != assinatura_amostra(sel.refs):
        return None, AMOSTRA_MUDOU
    return u, ""


FAIXA_PADRAO = Decimal("10")
MANUAL = "manual"   # Referencial.fonte_coleta dos referenciais cadastrados pelo avaliador


def eh_area_construida(nome: str) -> bool:
    """Nome de campo que é a área construída do avaliando. O IPTU de Goiânia escreve "Área
    edificada"; a matrícula/habite-se, "área construída". Exclui terreno/lote/privativa."""
    n = _n(nome)
    return ("area" in n and ("constru" in n or "edificad" in n)
            and not any(x in n for x in ("terreno", "lote", "sublote")))


def _n(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.casefold().split())


def _areas_construidas(job_id: str) -> list[tuple[Decimal, str, str]]:
    """(valor, origem, nome) de cada campo de área construída válido, documento primeiro:
    a medida da matrícula/IPTU vale mais que a estimada na vistoria."""
    out = []
    t = _comum.trabalho(job_id)
    if classe_tipologia(t.tipo) == "apartamento":
        # apartamento: a unidade de comparação é a ÁREA PRIVATIVA (escritura/IPTU), não a
        # "área total construída" (que soma área comum)
        for c in db.campos(job_id):
            if "privativ" in _n(c.nome) and "area" in _n(c.nome) and c.origem in ("documento", "vistoria"):
                try:
                    v = _decimal_br(c.valor)
                except (InvalidOperation, ValueError):
                    continue
                if v.is_finite() and v > 0:
                    out.append((v, c.origem, c.nome))
        if out:
            out.sort(key=lambda x: x[1] != "documento")
            return out
    for c in db.campos(job_id):
        if eh_area_construida(c.nome) and c.origem in ("documento", "vistoria"):
            try:
                v = _decimal_br(c.valor)
            except (InvalidOperation, ValueError):
                continue
            if v.is_finite() and v > 0:
                out.append((v, c.origem, c.nome))
    out.sort(key=lambda x: x[1] != "documento")   # estável: mantém a ordem dentro da origem
    return out


# ------------------------------------------------------------ ORDEM 021: base e área do cálculo
# O avaliador escolhe SEMPRE a base ("construida" ou "terreno") e qual área (pode haver mais de
# um valor: IPTU do lote inteiro × galpão medido por satélite). A escolha fica por trabalho em
# av_settings e sobrevive a reextração e às voltas do revisor.
BASES = ("construida", "terreno")
ROTULO_BASE = {"construida": "área construída", "terreno": "área do terreno"}
_NAO_SUGERIR = ("cadastrad", "iptu", "total", "matricula")
FALTA_ESCOLHA = "escolha a base do cálculo e a área do imóvel"
SEM_VALOR = "escolha a base do cálculo e a área para ver o valor"


def eh_area_terreno(nome: str) -> bool:
    n = _n(nome)
    return "area" in n and ("terreno" in n or "lote" in n)


def _parte(job_id: str) -> str:
    """ORDEM 032-2: parte do imóvel que é o objeto da avaliação ("" = imóvel inteiro)."""
    try:
        return (_comum.trabalho(job_id).objeto_parte or "").strip()
    except Exception:
        return ""


def _opcoes(job_id: str, casa) -> list[dict]:
    """Campos de área (documento, vistoria ou inferido) com valor válido; valor repetido
    aparece uma vez (documento primeiro). A sugerida é a do imóvel avaliado: a 1ª que NÃO é
    cadastral/IPTU/total/matrícula; senão, a de documento."""
    cs = [c for c in db.campos(job_id) if casa(c.nome) and c.origem in ("documento", "vistoria", "inferido")]
    cs.sort(key=lambda c: {"documento": 0, "vistoria": 1, "inferido": 2}[c.origem])
    out, vistos = [], set()
    for c in cs:
        try:
            v = _decimal_br(c.valor)
        except (InvalidOperation, ValueError):
            continue
        if not v.is_finite() or v <= 0:
            continue
        chave = v.quantize(Decimal("0.01"))
        if chave in vistos:
            continue
        vistos.add(chave)
        out.append({"campo": c.nome, "valor": float(chave), "origem": c.origem,
                    "fonte": c.fonte or "", "sugerida": False})
    parte = _n(_parte(job_id))
    sug = ((next((o for o in out if parte in _n(o["campo"])), None) if parte else None)
           or next((o for o in out if not any(x in _n(o["campo"]) for x in _NAO_SUGERIR)), None)
           or next((o for o in out if o["origem"] == "documento"), None)
           or (out[0] if out else None))
    if sug:
        sug["sugerida"] = True
    return out


def opcoes_area(job_id: str) -> dict:
    """{construida: [...], terreno: [...], escolha} para a tela "Confirmar valor"."""
    t = _comum.trabalho(job_id)
    constr = []
    if classe_tipologia(t.tipo) == "apartamento":
        constr = _opcoes(job_id, lambda n: "privativ" in _n(n) and "area" in _n(n))
    constr = constr or _opcoes(job_id, eh_area_construida)
    return {"construida": constr, "terreno": _opcoes(job_id, eh_area_terreno),
            "escolha": escolha_area(job_id)}


def _chave_escolha(job_id: str) -> str:
    return f"area_escolha:{job_id}"


def escolha_area(job_id: str) -> dict | None:
    import json
    bruto = db.setting(_chave_escolha(job_id))
    try:
        d = json.loads(bruto) if bruto else None
    except ValueError:
        return None
    return d if isinstance(d, dict) and d.get("base") in BASES and d.get("campo") else None


def gravar_escolha_area(job_id: str, base: str, campo: str) -> dict:
    """Valida (base conhecida, campo entre as opções dessa base) e grava. ValueError se não."""
    import json
    if base not in BASES:
        raise ValueError("base do cálculo inválida (use construida ou terreno)")
    op = next((o for o in opcoes_area(job_id)[base] if o["campo"] == campo), None)
    if op is None:
        raise ValueError(f"área \"{campo}\" não está entre as opções de {ROTULO_BASE[base]}")
    d = {"base": base, "campo": campo, "valor": op["valor"], "origem": op["origem"]}
    db.set_setting(_chave_escolha(job_id), json.dumps(d, ensure_ascii=False))
    return d


def apagar_escolha_area(job_id: str) -> None:
    db.set_setting(_chave_escolha(job_id), "")


def base_area(job_id: str) -> str:
    return (escolha_area(job_id) or {}).get("base", "construida")


def refs_na_base(job_id: str | None, refs: list, base: str | None = None) -> list:
    """Base terreno: o unitário de cada referencial é preço ÷ área do TERRENO (lote_m2). Devolve
    cópias com area_m2 = lote_m2 (cálculo, tabela de amostras e planilha usam a mesma área).
    Referencial escolhido sem lote_m2: ValueError com o nº."""
    # 094-1: "só comparação" (D-069) nunca entra na conta, mesmo marcado como escolhido
    refs = [r for r in refs if getattr(r, "decisao", "") != "comparacao"]
    base = base or (base_area(job_id) if job_id else "construida")
    if base != "terreno":
        return list(refs)
    sem = [r.n for r in refs if getattr(r, "escolhido", True) and not r.lote_m2]
    if sem:
        raise ValueError("referencial sem área de terreno (necessária na base terreno): nº "
                         + ", ".join(map(str, sem)))
    return [r.model_copy(update={"area_m2": r.lote_m2}) if r.lote_m2 else r for r in refs]


def _area_construida(job_id: str):
    """(valor, origem) da área do cálculo: a ESCOLHIDA pelo avaliador (ORDEM 021) primeiro;
    senão, o campo de área construída (documento antes de vistoria); (None, 'pendente')."""
    esc = escolha_area(job_id)
    if esc:
        op = next((o for o in opcoes_area(job_id).get(esc["base"], []) if o["campo"] == esc["campo"]), None)
        if op:
            return Decimal(str(op["valor"])), op["origem"]
        return Decimal(str(esc["valor"])), esc.get("origem") or "documento"
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
    todos = db.candidatos(job_id)
    if any(r.decisao == "entra" for r in todos):
        # lista da pesquisa: só os escolhidos pelo avaliador seguem (e a IA só vê esses)
        cands = [r for r in todos if r.decisao == "entra"
                 or (r.fonte_coleta == MANUAL and r.decisao not in ("descarta", "comparacao"))]   # 094-1: o #7 entrava aqui
        fora = [r.model_copy(update={"escolhido": False, "justificativa": (
            f"descartado pelo avaliador{': ' + r.motivo_descarte if r.motivo_descarte else ''}"
            if r.decisao == "descarta" else "não escolhido pelo avaliador na lista")})
            for r in todos if r not in cands and r.decisao != "comparacao"]
    else:
        cands, fora = [r for r in todos if r.decisao != "comparacao"], []
    fora += [r.model_copy(update={"escolhido": False, "justificativa": "só comparação (fora do cálculo, D-069)"})
             for r in todos if r.decisao == "comparacao" and r not in fora]
    area = area_construida(job_id)
    campos = [c.model_dump(mode="json") for c in db.campos(job_id)]
    curva = fora_da_curva(cands)   # regra objetiva, antes da IA
    sistema = conhecimento.base(job_id, ("P0", "P3"), ("pesquisa", "cálculo")) + "\n\n" + INSTRUCAO
    prompt = ("Trabalho:\n" + t.model_dump_json(indent=2)
              + f"\n\nCampos do avaliando:\n{campos}\n\nCandidatos:\n"
              + "\n".join(r.model_dump_json(exclude={"foto", "print_"}) for r in cands)
              + db.texto_correcoes(job_id, "selecao"))
    manuais = {r.n for r in cands if (r.fonte_coleta == MANUAL or r.decisao == "entra")
               and r.area_m2 and r.preco}
    if manuais:
        prompt += ("\n\nReferenciais ESCOLHIDOS PELO AVALIADOR (n " + ", ".join(map(str, sorted(manuais)))
                   + "): ficam na amostra. Marque escolhido=true; se algum tiver ponto de "
                   "atenção (ex.: barracão independente), diga na justificativa, sem excluir.")
    curva = {n: m for n, m in curva.items() if n not in manuais}  # escolha do avaliador vale
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
        elif r.n in manuais:
            # referencial escolhido pelo avaliador nunca é excluído pela IA (só avisa)
            just = (d.justificativa.strip() if d else "")
            if d is not None and not d.escolhido:
                db.evento(job_id, "selecao", "aviso",
                          f"referencial {r.n} (escolhido pelo avaliador) mantido; "
                          f"atenção da IA: {just or 'sem motivo informado'}")
                just = f"Escolhido pelo avaliador (mantido). Atenção: {just}".strip()
            upd = {"escolhido": True, "justificativa": just or "escolhido pelo avaliador"}
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
                declaracao = (f"Amostra reduzida: apenas {pl(n_esc + falta, 'referencial semelhante disponível', 'referenciais semelhantes disponíveis')} "
                              "no mercado pesquisado.")
            else:
                declaracao = (f"Foram identificados apenas {pl(n_esc, 'referencial plenamente semelhante', 'referenciais plenamente semelhantes')}; "
                            f"a amostra foi completada com {pl(falta, 'referencial', 'referenciais')} "
                            "de maior similaridade disponível no mercado.")
        else:
            declaracao = (f"Amostra reduzida: apenas {pl(len(validos), 'referencial válido disponível', 'referenciais válidos disponíveis')} "
                          "no mercado pesquisado.")

    # Faixa padrão ±10%: outra faixa só com aval do avaliador (confirmação na tela); a da IA
    # fica registrada como proposta.
    faixa = FAIXA_PADRAO
    if resp.faixa_pct is not None and resp.faixa_pct != FAIXA_PADRAO:
        db.evento(job_id, "selecao", "info",
                  f"IA propôs faixa ±{resp.faixa_pct}%; adotado ±{FAIXA_PADRAO}% até o "
                  "avaliador confirmar")
    # 082-4: a IA só PROPÕE o unitário (fica em proposta_ia); o adotado é a média até o avaliador decidir
    unitario, just_u = None, ""
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
        try:
            escolhidos = refs_na_base(job_id, [r for r in refs if r.escolhido])
            calculo.calcular(area, escolhidos, unitario, faixa)
        except ValueError as e:
            db.evento(job_id, "selecao", "aviso", f"unitário adotado descartado: {e}")
            unitario, just_u = None, ""

    refs = sorted(refs + fora, key=lambda r: r.n)
    s = Selecao(refs=refs, unitario_adotado=unitario, justificativa_unitario=just_u,
                faixa_pct=faixa, declaracao_amostra=declaracao,
                proposta_ia=PropostaIA(
                    unitario_adotado=(resp.unitario_adotado.quantize(Decimal("0.01"))
                                      if resp.unitario_adotado is not None else None),
                    justificativa_unitario=resp.justificativa_unitario,
                    faixa_pct=resp.faixa_pct))
    db.salvar_candidatos(job_id, refs)
    db.evento(job_id, "selecao", "resultado",
              f"{sum(r.escolhido for r in refs)} de {len(refs)} referenciais escolhidos",
              dados=s.model_dump(mode="json"))
    return s
