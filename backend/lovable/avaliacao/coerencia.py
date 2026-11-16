"""D-084 (ORDEM 039-3): conferência automática de coerência do laudo, por conta e SEM IA.

Antes de cada entrega, lê o PDF final e a planilha e confere que o mesmo dado é igual em todo
lugar (capa, corpo, resumo, quadro, extenso e planilha):
  valor adotado (número e extenso), mínimo e máximo da faixa, unitário, área, nº de amostras,
  CV (quando o laudo o mostra), data-base, número do laudo, CNAI (053569) e nome do arquivo.
E refaz as contas:
  R$/m² = preço ÷ área (2 casas); valor = área × unitário antes do arredondamento;
  arredondado ao milhar mais próximo (D-065); a faixa bate com o ± declarado.
Qualquer diferença, mesmo de R$ 1, bloqueia a entrega (PARCIAL — PENDÊNCIAS) e diz onde está
cada valor diferente. Sem dados do trabalho (ex.: PDF de fora do sistema), confere o PDF
consigo mesmo: o valor do quadro tem que bater com todas as outras ocorrências."""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pymupdf

from . import calculo

CNAI = "053569"
_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro"]
_RS = r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})"


@dataclass
class Diferenca:
    dado: str
    pagina: str          # "pág. 9" | "planilha" | "nome do arquivo"
    encontrado: str
    esperado: str
    # 120: para a lista numerada da tela — todos os lugares ({pagina, trecho} para o [Mostrar no PDF]), se o erro é
    # para o avaliador decidir (conta/número da conferência nunca é) e a sugestão de um toque, quando houver
    lugares: list = field(default_factory=list)
    do_avaliador: bool = False
    sugestao: str = ""
    valor_sugerido: str = ""

    def texto(self) -> str:
        return f"{self.dado}: {self.pagina} traz {self.encontrado}, o esperado é {self.esperado}"


@dataclass
class Resultado:
    diferencas: list[Diferenca] = field(default_factory=list)
    conferidos: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diferencas

    def resumo(self) -> str:
        if self.ok:
            return "conferência de coerência (D-084): tudo igual em todo o laudo e na planilha"
        return ("conferência de coerência (D-084): " + str(len(self.diferencas))
                + (" diferença" if len(self.diferencas) == 1 else " diferenças") + " — "
                + "; ".join(d.texto() for d in self.diferencas[:12]))


# ------------------------------------------------------------------ números
def brl(v) -> str:
    v = Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "§").replace(".", ",").replace("§", ".")


def num_br(s: str) -> Decimal:
    return Decimal(s.replace(".", "").replace(",", "."))


def _q2(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _milhar(v: Decimal) -> Decimal:
    return (v / 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 1000


def paginas(pdf: Path) -> list[str]:
    with pymupdf.open(pdf) as d:
        return [" ".join(p.get_text().replace("\xa0", " ").replace(" ", " ").split()) for p in d]


# 161: marcas de linha de referencial na tabela de amostras e na comparação
_REF_PERTO = re.compile(r"(?i)an[uú]ncio do site|pesquisa de campo realizada|\bno link:")

# ------------------------------------------------------------------ leituras do PDF
_ROTULO_VALOR = re.compile(r"(?i)(valor de mercado(?: adotado)?|valor adotado|valor de refer[eê]ncia|"
                           r"valor final|valor do im[oó]vel)\W{0,40}?" + _RS)
_EQUACAO = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*m²\s*[×x]\s*" + _RS + r"\s*/\s*m²(?:\s*=\s*" + _RS + r")?")
_EXTENSO = re.compile(r"\(([A-ZÁÉÍÓÚ][a-záàâãéêíóôõúç ,]+?(?:reais|real)(?: e [a-záàâãéêíóôõúç ]+centavos?)?)\)")
_MINMAX = re.compile(r"(?i)(m[ií]nimo|m[aá]ximo|limite inferior|limite superior)\W{0,30}?" + _RS)
_UNIT_ADOTADO = re.compile(r"(?i)(?:valor unit[aá]rio(?: adotado)?(?: de)?|unit[aá]rio adotado(?: de)?|adota-se o valor unit[aá]rio de)\W{0,25}?" + _RS + r"\s*/\s*m²")
_NUMERO = re.compile(r"N\.?\s?º\s*(\d{2,6})")
_CNAI = re.compile(r"CNAI[^0-9]{0,20}(\d{4,7})")
_DATA_TXT = r"(\d{1,2}/\d{1,2}/\d{4}|\d{1,2}º? de [a-zç]+ de \d{4})"
# 115-c: "valor de mercado do imóvel avaliando na data da vistoria, 13/11/2026" / "data de referência: 28/10/2026"
_DATAS_DO_VALOR = (
    re.compile(r"(?i)valor\s+de\s+mercado[^.;]{0,140}?\bna\s+data(?:\s+da\s+vistoria|\s+de\s+refer[êe]ncia|\s+de|-base|"
               r"\s+base)?\W{0,4}(?:de\s+)?" + _DATA_TXT),
    re.compile(r"(?i)data\s+de\s+refer[êe]ncia(?:\s+do\s+valor)?\W{0,6}" + _DATA_TXT),
)
DUAS_DATAS = "data-base (duas datas de referência no laudo)"
_DATA_BASE = re.compile(r"(?i)data-base(?: da avalia[cç][aã]o)?\W{0,6}(?:de\s+)?(\d{1,2}/\d{1,2}/\d{4}|\d{1,2} de [a-zç]+ de \d{4})")
_CV = re.compile(r"(?i)coeficiente de varia[cç][aã]o(?: \(CV\))?(?: de| =| foi de| é de)?\W{0,6}(\d{1,3},\d{1,2})\s*%")
_N_AMOSTRAS = re.compile(r"(?i)(?<!m[ií]nimo de )\b(\d{1,2})\s+(?:amostras|referenciais|anúncios semelhantes)\b(?! (?:analisad|descartad))")


def _data(s: str) -> date | None:
    s = s.strip().casefold()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        d, mm, a = map(int, m.groups())
        return date(a, mm, d)
    m = re.fullmatch(r"(\d{1,2}) de ([a-zç]+) de (\d{4})", s)
    if m and m.group(2) in _MESES:
        return date(int(m.group(3)), _MESES.index(m.group(2)) + 1, int(m.group(1)))
    return None


def _todas(rx, pags) -> list[tuple[int, re.Match]]:
    return [(i + 1, m) for i, t in enumerate(pags) for m in rx.finditer(t)]


# 100-1: número em frase sobre OUTRO documento (declarado no ITCD, referência da SEFAZ, FIPE, venal do IPTU, ITBI)
# não é número deste laudo: a conferência não o compara com o valor/área/unitário do laudo
_DE_DOCUMENTO = re.compile(r"(?i)declarad|refer[êe]ncia|sefaz|fipe|venal|iptu|itbi|itcd|comunicado|agehab|m[ée]dio de mercado")


def _de_documento(pags: list[str], pg: int, m: re.Match, antes: int = 160, depois: int = 80) -> bool:
    t = pags[pg - 1]
    return bool(_DE_DOCUMENTO.search(t[max(0, m.start() - antes):m.end() + depois]))


# ------------------------------------------------------------------ planilha (fórmulas refeitas)
def _sem(s: str) -> str:
    """Minúsculas, sem acento, sem hífen e com espaços simples (para comparar texto do PDF e da planilha)."""
    import unicodedata
    t = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(t.replace("-", " ").split())


def planilha(xlsx: Path) -> dict:
    """Lê as ENTRADAS da P2 e refaz as fórmulas (a planilha gerada não guarda os resultados)."""
    import openpyxl
    wb = openpyxl.load_workbook(xlsx, data_only=False)
    am, ca, im = wb["Amostras"], wb["Calculo"], wb["Imovel"]
    linhas = []
    for r in range(2, 22):
        usar, area, preco = am.cell(r, 2).value, am.cell(r, 7).value, am.cell(r, 9).value
        if usar == "S" and area and preco:
            linhas.append({"n": am.cell(r, 1).value, "area": Decimal(str(area)), "preco": Decimal(str(preco)),
                           "unit": _q2(Decimal(str(preco)) / Decimal(str(area)))})
    us = [x["unit"] for x in linhas]
    media = _q2(sum(us, Decimal(0)) / len(us)) if us else None
    b10 = ca["B10"].value
    unit = Decimal(str(b10)) if isinstance(b10, (int, float)) else media
    area = Decimal(str(im["B9"].value)) if im["B9"].value is not None else None
    exato = _q2(area * unit) if area is not None and unit is not None else None
    passo = Decimal(str(ca["B14"].value or 1000))
    adotado = (exato / passo).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * passo if exato is not None else None
    faixa = Decimal(str(ca["B17"].value or 0))
    data_base = im["B6"].value
    cv = (Decimal(str(statistics.stdev([float(u) for u in us]))) / (sum(us) / len(us))) if len(us) > 1 else None
    return {"amostras": linhas, "n": len(linhas), "media": media, "unitario": unit, "area": area,
            "exato": exato, "adotado": adotado, "faixa": faixa,
            "minimo": _q2(adotado * (1 - faixa)) if adotado is not None else None,
            "maximo": _q2(adotado * (1 + faixa)) if adotado is not None else None,
            "cv": cv, "data_base": data_base.date() if hasattr(data_base, "date") else data_base,
            # 080-2: a aba Imovel inteira (campo -> valor, status), para conferir com o laudo
            "imovel": {str(im.cell(r, 1).value): (im.cell(r, 2).value, str(im.cell(r, 5).value or ""))
                       for r in range(2, 12) if im.cell(r, 1).value}}


# ------------------------------------------------------------------ conferência
@dataclass
class Esperado:
    """O que o laudo tem que dizer (do trabalho). Campo None = tirar do próprio PDF."""
    valor_adotado: Decimal | None = None
    valor_calculado: Decimal | None = None
    valor_min: Decimal | None = None
    valor_max: Decimal | None = None
    faixa_pct: Decimal | None = None
    unitario: Decimal | None = None
    area: Decimal | None = None
    n_amostras: int | None = None
    unitarios: list[Decimal] = field(default_factory=list)
    amostras: list[tuple[Decimal, Decimal]] = field(default_factory=list)   # (preço, área)
    data_base: date | None = None
    numero: str | None = None
    nome_arquivo: str | None = None
    # 085-1: a data-base que o avaliador informou (em ITCD, a da DITCD) e a da vistoria, para não trocar uma pela outra
    data_base_informada: date | None = None
    # L200 (Caso M): o CNAI do avaliador DONO do trabalho ("" = sem CNAI: não confere). None = o do Alan
    cnai: str | None = None
    data_vistoria: date | None = None
    itcd: bool = False
    # 101: valores e números dos DOCUMENTOS (o que o laudo atribui a eles tem de bater com o campo extraído)
    doc_valores: dict = field(default_factory=dict)    # {"declarado": Decimal, "referência": …, "FIPE": …, "venal": …}
    doc_numeros: dict = field(default_factory=dict)    # {"matrícula": ["100.200", "40.800"], "inscrição": [...]}
    bairro: str = ""                                   # 117: o nome do setor como no documento ("Jardim Curitiba I")
    cv_fora: bool = False                              # D-068: o avaliador decidiu "conta da dispersão só na planilha"


def do_resultado(r: calculo.Resultado, area: Decimal, refs, data_base: date | None,
                 numero, nome_arquivo: str | None = None) -> Esperado:
    return Esperado(valor_adotado=r.valor_adotado, valor_calculado=r.valor_calculado,
                    valor_min=r.valor_min, valor_max=r.valor_max, faixa_pct=r.faixa_pct,
                    unitario=r.unitario_adotado, area=Decimal(str(area)), n_amostras=len(r.unitarios),
                    unitarios=list(r.unitarios),
                    amostras=[(Decimal(str(x.preco)), Decimal(str(x.area_m2))) for x in refs
                              if x.preco and x.area_m2],
                    data_base=data_base, numero=str(numero) if numero is not None else None,
                    nome_arquivo=nome_arquivo)


def conferir(pdf: Path, xlsx: Path | None = None, esp: Esperado | None = None) -> Resultado:
    esp = esp or Esperado()
    pags = paginas(pdf)
    res = Resultado()
    dif = res.diferencas.append

    # --- referência: do trabalho, senão da planilha, senão do próprio PDF (equação/quadro)
    pl = planilha(xlsx) if xlsx and Path(xlsx).is_file() else None
    eqs = _todas(_EQUACAO, pags)
    rot = _todas(_ROTULO_VALOR, pags)
    valor = esp.valor_adotado
    if valor is None and pl:
        valor = pl["adotado"]
    if valor is None and rot:     # 090: "valor de referência" é o do fisco (ITCD/SEFAZ), nunca o valor do laudo
        proprios = [m for _, m in rot if not m.group(1).lower().startswith("valor de refer")]
        valor = num_br(proprios[-1].group(2)) if proprios else None
    unit = esp.unitario if esp.unitario is not None else (pl["unitario"] if pl else (
        num_br(eqs[0][1].group(2)) if eqs else None))
    area = esp.area if esp.area is not None else (pl["area"] if pl else (
        num_br(eqs[0][1].group(1)) if eqs else None))
    res.conferidos.update(valor=valor, unitario=unit, area=area)
    # 090: só com o valor vindo do TRABALHO (seleção/cálculo) a montagem pode trocar números sozinha
    res.conferidos["valor_do_trabalho"] = esp.valor_adotado is not None

    # --- valor adotado: toda ocorrência rotulada
    if valor is not None:
        for pg, m in rot:
            if _de_documento(pags, pg, m):
                continue                           # 100-1: valor de outro documento
            v = num_br(m.group(2))
            exato = _q2(area * unit) if area is not None and unit is not None else None
            if v not in (valor, exato) and m.group(1).casefold().startswith(("valor de mercado", "valor adotado")):
                if "/m²" in pags[pg - 1][m.end():m.end() + 4]:
                    continue                       # é unitário ("valor de mercado de R$ X/m²")
                dif(Diferenca("valor adotado", f"pág. {pg}", brl(v), brl(valor)))
        if not any(brl(valor) in t for t in pags):
            dif(Diferenca("valor adotado", "laudo", "não encontrado", brl(valor)))
        # extenso
        ext = calculo.por_extenso(valor)
        permitidos = {ext.casefold()}
        for v in (esp.valor_min, esp.valor_max):
            if v is not None:
                permitidos.add(calculo.por_extenso(v).casefold())
        for pg, m in _todas(_EXTENSO, pags):
            e = " ".join(m.group(1).split())
            if e.casefold() not in permitidos and any(w in e.casefold() for w in ("mil", "milhão", "milhões")):
                dif(Diferenca("valor por extenso", f"pág. {pg}", f"({e})", f"({ext})"))
        if not any(ext.casefold() in t.casefold() for t in pags):
            dif(Diferenca("valor por extenso", "laudo", "não encontrado", f"({ext})"))
        # arredondamento ao milhar (D-065) e conta área × unitário
        if area is not None and unit is not None:
            exato = _q2(area * unit)
            res.conferidos["valor_calculado"] = exato
            if _milhar(exato) != valor:
                dif(Diferenca("arredondamento ao milhar (D-065)", "cálculo",
                              f"{brl(exato)} → {brl(valor)}", brl(_milhar(exato))))
        for pg, m in eqs:
            if _de_documento(pags, pg, m):
                continue                           # 100-1: a conta da FIPE (terreno/construção) não é a deste laudo
            a, u = num_br(m.group(1)), num_br(m.group(2))
            if area is not None and a != area:
                dif(Diferenca("área do cálculo", f"pág. {pg}", f"{m.group(1)} m²", f"{brl(area)[3:]} m²"))
            if unit is not None and u != unit:
                dif(Diferenca("unitário na conta", f"pág. {pg}", brl(u) + "/m²", brl(unit) + "/m²"))
            if m.group(3):
                t = num_br(m.group(3))
                if t not in (_q2(a * u), valor):
                    dif(Diferenca("resultado da conta", f"pág. {pg}", brl(t), brl(_q2(a * u))))
        # faixa
        pct = esp.faixa_pct if esp.faixa_pct is not None else (pl["faixa"] * 100 if pl else None)
        vmin = esp.valor_min if esp.valor_min is not None else (
            _q2(valor * (1 - pct / 100)) if pct is not None else None)
        vmax = esp.valor_max if esp.valor_max is not None else (
            _q2(valor * (1 + pct / 100)) if pct is not None else None)
        if pct is not None:
            if vmin != _q2(valor * (1 - pct / 100)).quantize(Decimal("1")) and vmin != _q2(valor * (1 - pct / 100)):
                dif(Diferenca("mínimo da faixa", "cálculo", brl(vmin), brl(valor * (1 - pct / 100))))
            if vmax != _q2(valor * (1 + pct / 100)).quantize(Decimal("1")) and vmax != _q2(valor * (1 + pct / 100)):
                dif(Diferenca("máximo da faixa", "cálculo", brl(vmax), brl(valor * (1 + pct / 100))))
        for pg, m in _todas(_MINMAX, pags):
            v = num_br(m.group(2))
            alvo = vmin if m.group(1).casefold().startswith(("mín", "min", "limite inf")) else vmax
            if alvo is not None and v != alvo and v > 1000:
                if "/m²" in pags[pg - 1][m.end():m.end() + 4]:
                    continue                       # mínimo/máximo da AMOSTRA (R$/m²)
                dif(Diferenca(f"{m.group(1).lower()} da faixa", f"pág. {pg}", brl(v), brl(alvo)))
        for nome, v in (("mínimo da faixa", vmin), ("máximo da faixa", vmax)):
            if v is not None and not any(brl(v) in t for t in pags):
                dif(Diferenca(nome, "laudo", "não encontrado", brl(v)))

    # --- 080-2: a aba Imovel da planilha tem que ter os dados do laudo (não basta o valor bater)
    if pl and pl.get("imovel"):
        texto_pdf = _sem(" ".join(pags))
        for campo, (v, status) in pl["imovel"].items():
            if v in (None, "") or status == "Pendente":
                dif(Diferenca(f"planilha: {campo}", "aba Imovel", "vazio" if v in (None, "") else "Pendente",
                              "o mesmo dado do laudo, com a fonte"))
                continue
            c = _sem(campo)
            if "endereco" in c and not re.search(r"(?i)\b(rua|r\.|av\.?|avenida|alameda|travessa|rodovia|quadra|qd\.?)\b", str(v)):
                dif(Diferenca("planilha: endereço completo", "aba Imovel", str(v)[:50], "rua, quadra, lote e CEP, como no laudo"))
            elif "matricula" in c:
                num = re.match(r"[\d.]+", str(v).strip())
                if num and _sem(num.group(0)) not in texto_pdf:
                    dif(Diferenca("planilha: matrícula", "aba Imovel", str(v)[:40], "a matrícula do laudo"))
            elif "area do terreno" in c and isinstance(v, (int, float)):
                if brl(Decimal(str(v)))[3:] not in " ".join(pags):
                    dif(Diferenca("planilha: área do terreno", "aba Imovel", f"{brl(Decimal(str(v)))[3:]} m²",
                                  "a área do terreno do laudo"))
            elif "conservacao" in c and _sem(str(v))[:25] not in texto_pdf:
                dif(Diferenca("planilha: estado de conservação", "aba Imovel", str(v)[:50], "o estado do laudo (item 7.4)"))

    # --- "quase igual": todo R$ a menos de 1% do adotado / mínimo / máximo / unitário, mas
    # diferente, é diferença (pega R$ 1 a mais no resumo, mesmo longe do rótulo)
    if valor is not None:
        us_ok = set(esp.unitarios) | ({_q2(sum(esp.unitarios) / len(esp.unitarios))} if esp.unitarios else set())
        exato_ok = {_q2(area * unit)} if area is not None and unit is not None else set()
        alvos = [("valor adotado", valor, {valor} | exato_ok)]
        if esp.valor_min is not None or (pl and pl["minimo"] is not None):
            vm = esp.valor_min if esp.valor_min is not None else pl["minimo"]
            alvos.append(("mínimo da faixa", vm, {vm}))
        if esp.valor_max is not None or (pl and pl["maximo"] is not None):
            vx = esp.valor_max if esp.valor_max is not None else pl["maximo"]
            alvos.append(("máximo da faixa", vx, {vx}))
        # 161: preço de referencial (tabela de amostras / comparação) nunca é "o valor do laudo quase igual"
        precos_refs = ({Decimal(str(p_)) for p_, _ in (esp.amostras or [])}
                       | ({Decimal(str(x["preco"])) for x in pl["amostras"]} if pl else set()))
        for pg, t in enumerate(pags, 1):
            for m in re.finditer(_RS + r"(\s*/\s*m²)?", t):
                v = num_br(m.group(1))
                if m.group(2):          # R$/m²
                    rotulo = t[max(0, m.start() - 30):m.start()].casefold()
                    if any(x in rotulo for x in ("mediana", "mínimo", "minimo", "máximo", "maximo", "desvio")):
                        continue        # estatística da amostra, não o unitário adotado
                    if unit is not None and v != unit and v not in us_ok and abs(v - unit) <= unit / 100:
                        dif(Diferenca("unitário", f"pág. {pg}", brl(v) + "/m²", brl(unit) + "/m²"))
                    continue
                antes = t[max(0, m.start() - 90):m.start()].casefold()
                if any(x in antes for x in ("declarad", "venal", "referência", "referencia", "itbi", "iptu")):
                    continue            # 074: valor do fisco (declarado/venal/FIPE), não número do cálculo
                da_faixa = any(x in antes for x in ("mínim", "minim", "máxim", "maxim", "faixa", "limite", "intervalo"))
                if not da_faixa and (v in precos_refs or _REF_PERTO.search(t[max(0, m.start() - 400):m.end() + 250])):
                    continue            # 161: linha de referencial (preço do anúncio / pesquisa de campo), não o valor do laudo
                for nome, alvo, ok in alvos:
                    if nome != "valor adotado" and not da_faixa:
                        continue        # 077-A: mínimo/máximo só no campo da faixa (não o declarado do ITCD numa tabela)
                    if v not in ok and abs(v - alvo) <= alvo / 100:
                        dif(Diferenca(nome, f"pág. {pg}", brl(v), brl(alvo)))

    # --- unitário adotado em toda frase que o declara
    if unit is not None:
        for pg, m in _todas(_UNIT_ADOTADO, pags):
            if "adot" in m.group(0).casefold() and num_br(m.group(1)) != unit:
                dif(Diferenca("unitário adotado", f"pág. {pg}", brl(num_br(m.group(1))) + "/m²", brl(unit) + "/m²"))

    # --- R$/m² de cada amostra = preço ÷ área (2 casas), no PDF e na planilha
    amostras = esp.amostras or ([(x["preco"], x["area"]) for x in pl["amostras"]] if pl else [])
    texto = " ".join(pags)
    for preco, a in amostras:
        u = _q2(preco / a)
        if brl(u) not in texto:
            dif(Diferenca("R$/m² da amostra", "tabela de amostras", "não encontrado",
                          f"{brl(u)} (= {brl(preco)} ÷ {brl(a)[3:]} m²)"))
    if pl and esp.amostras:
        a_pl = sorted((x["preco"], x["area"]) for x in pl["amostras"])
        if a_pl != sorted(esp.amostras):
            dif(Diferenca("amostras", "planilha", f"{len(a_pl)} amostras", f"{len(esp.amostras)} do laudo"))

    # --- planilha × laudo
    if pl:
        for nome, a, b in (("valor adotado", pl["adotado"], valor), ("unitário", pl["unitario"], unit),
                           ("área", pl["area"], area)):
            if a is not None and b is not None and a != b:
                dif(Diferenca(nome, "planilha", brl(a), brl(b)))
        if esp.data_base and pl["data_base"] and pl["data_base"] != esp.data_base:
            dif(Diferenca("data-base", "planilha", pl["data_base"].strftime("%d/%m/%Y"),
                          esp.data_base.strftime("%d/%m/%Y")))

    # --- nº de amostras
    n = esp.n_amostras if esp.n_amostras is not None else (pl["n"] if pl else None)
    if n is not None:
        res.conferidos["n_amostras"] = n
        for pg, m in _todas(_N_AMOSTRAS, pags):
            antes = pags[pg - 1][max(0, m.start() - 30):m.start()].casefold()
            if any(x in antes for x in ("mínimo", "minimo", "analisados", "foram analisad", "pelo menos")):
                continue
            if re.search(r"(?i)p[áa]g(?:ina)?\.?\s*$", antes):
                continue              # 118-4: "Pág. 12" do rodapé + "referenciais…" da página seguinte não é contagem
            if int(m.group(1)) != n:
                dif(Diferenca("nº de amostras", f"pág. {pg}", m.group(0), f"{n}"))

    # --- CV (quando o laudo mostra)
    us = esp.unitarios or ([x["unit"] for x in pl["amostras"]] if pl else [])
    if len(us) > 1:
        cv = Decimal(str(statistics.stdev([float(u) for u in us]))) / (sum(us) / len(us)) * 100
        for pg, m in _todas(_CV, pags):
            v = num_br(m.group(1) if "," in m.group(1) else m.group(1) + ",00")
            casas = len(m.group(1).split(",")[1])
            if v != cv.quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP):
                dif(Diferenca("coeficiente de variação", f"pág. {pg}", f"{m.group(1)}%",
                              f"{str(cv.quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)).replace('.', ',')}%"))

    # --- data-base, número do laudo, CNAI, nome do arquivo
    datas = [(pg, _data(m.group(1)), m.group(1)) for pg, m in _todas(_DATA_BASE, pags)]
    base = esp.data_base or next((d for _, d, _ in datas if d), None)
    for pg, d, bruto in datas:
        if d and base and d != base:
            dif(Diferenca("data-base", f"pág. {pg}", bruto, base.strftime("%d/%m/%Y")))
    # 115-c: a data em que o laudo diz que o valor vale ("valor de mercado … na data da vistoria, 13/11/2026") é a
    # data-base com outro nome — se for outra, o laudo tem duas datas de referência (capa/cabeçalho × corpo): bloqueia
    vistas_ref = set()
    for pg, m in [x for rx in _DATAS_DO_VALOR for x in _todas(rx, pags)]:
        d = _data(m.group(1).replace("º", ""))
        if d and base and d != base and (pg, m.start()) not in vistas_ref:      # cada frase (item 1 e item 4)
            vistas_ref.add((pg, m.start()))
            dif(Diferenca(DUAS_DATAS, f"pág. {pg}", f"{m.group(1)} (\"{' '.join(m.group(0).split())[:90]}\")",
                          f"{base.strftime('%d/%m/%Y')} (a data-base da capa, do cabeçalho e do resumo)"))
    nums = _todas(_NUMERO, pags)
    numero = esp.numero or (max({m.group(1) for _, m in nums}, key=lambda x: sum(
        1 for _, m in nums if m.group(1) == x)) if nums else None)
    for pg, m in nums:
        if numero and m.group(1) != numero:
            dif(Diferenca("número do laudo", f"pág. {pg}", m.group(1), numero))
    vistos = set()
    cnai_certo = CNAI if esp.cnai is None else esp.cnai     # L200: antes, todo laudo voltava para o CNAI do Alan
    for pg, m in (_todas(_CNAI, pags) if cnai_certo else []):
        if m.group(1) != cnai_certo and (pg, m.group(1)) not in vistos:
            vistos.add((pg, m.group(1)))
            dif(Diferenca("CNAI", f"pág. {pg}", m.group(1), cnai_certo))
    nome = Path(pdf).stem
    if numero and not nome.startswith(f"{numero} - ") and not nome.startswith(numero):
        dif(Diferenca("nome do arquivo", "nome do arquivo", nome, f"{numero} - Cliente - Tipo - Bairro - Cidade"))
    if esp.nome_arquivo and Path(esp.nome_arquivo).stem != nome.removesuffix("_assinado"):
        dif(Diferenca("nome do arquivo", "nome do arquivo", nome, Path(esp.nome_arquivo).stem))
    # 085-1: a data-base do laudo é a que o avaliador informou; em ITCD, nunca a da vistoria sem ele dizer
    if base and esp.data_base_informada and base != esp.data_base_informada:
        dif(Diferenca("data-base (a que o avaliador informou)", "laudo", base.strftime("%d/%m/%Y"),
                      esp.data_base_informada.strftime("%d/%m/%Y")))
    elif base and esp.itcd and not esp.data_base_informada and esp.data_vistoria and base == esp.data_vistoria:
        dif(Diferenca("data-base", "laudo", f"{base.strftime('%d/%m/%Y')} (a data da vistoria)",
                      "a data da declaração do ITCD (DITCD), informada pelo avaliador"))
    # 090-2: a assinatura (emissão) nunca é anterior à última consulta aos anúncios
    _assinatura_depois_da_pesquisa(pags, dif)
    # 101-2: cada número atribuído a um documento = o campo extraído desse documento
    _numeros_dos_documentos(pags, esp, dif)
    # 101-1: decisão do avaliador (D-068) — sem coeficiente de variação nem dispersão em % no laudo
    if esp.cv_fora:
        for pg, t in enumerate(pags, 1):
            m = _CV_NO_TEXTO.search(t)
            if m:
                dif(Diferenca("frase vetada pelo avaliador (D-068)", f"pág. {pg}", t[max(0, m.start() - 30):m.end() + 30].strip(),
                              "sem coeficiente de variação nem dispersão em % no laudo (a conta fica só na planilha)"))
    # 106-3: regra do projeto (vale sempre, com ou sem a decisão acima): nada sobre dispersão dos referenciais
    for pg, t in enumerate(pags, 1):
        for s in frases_dispersao(t):
            if esp.cv_fora and _CV_NO_TEXTO.search(s):
                continue                                    # já acusada acima
            dif(Diferenca(DISPERSAO, f"pág. {pg}", s[:220], "nenhuma frase sobre dispersão dos valores dos referenciais "
                          "(D-068: a conta fica só na planilha; a faixa é \"faixa de variação mercadológica admitida\")"))
    _bairro_igual(pags, esp.bairro, dif)                                    # 117 (D-131)
    if esp.data_vistoria:
        _resto_data_base(pags, dif)                                         # 126-3b (D-127)
    res.conferidos.update(numero=numero, data_base=base)
    res.diferencas = _agrupar(res.diferencas)
    return res


RESTO_DATA_BASE = "\"data-base\" que sobrou (D-127: só a data da vistoria)"
# do mais comprido para o mais curto: a troca exata de cada expressão (aplicada sozinha pelo 087, sem perguntar)
_TROCAS_DATA_BASE = (("Data da vistoria da avaliação", "Data da vistoria"),
                     ("na data-base da avaliação", "na data da vistoria"),
                     ("dados disponíveis na data-base", "dados disponíveis na data da vistoria"),
                     ("data-base indicada", "data da vistoria"),
                     ("data-base da avaliação", "data da vistoria"),
                     ("na data-base", "na data da vistoria"),
                     ("Data-base", "Data da vistoria"),
                     ("data-base", "data da vistoria"))


def _resto_data_base(pags: list[str], dif) -> None:
    """126-3b (D-127): depois da troca para a data da vistoria, procurar no PDF inteiro o termo antigo que sobrou
    (frases fixas do modelo: itens 10, 11 e 13; rótulo do resumo). Cada sobra vira troca exata, feita sozinha."""
    for pg, t in enumerate(pags, 1):
        resto = t
        for de, para in _TROCAS_DATA_BASE:
            if de in resto:
                dif(Diferenca(RESTO_DATA_BASE, f"pág. {pg}", de, para))
                resto = resto.replace(de, " ")


BAIRRO = "nome do bairro (como no documento)"
_DO_AVALIANDO = re.compile(r"(?i)\bQd\.|\bLt\.|\bquadra\s+\d|\blote\s+\d|avaliand|im[óo]vel\s+avaliado")
_SUFIXO_BAIRRO = re.compile(r"^(.*\S)\s+((?:I{1,3}|IV|V|VI{0,3}|IX|X)|\d{1,2})$")


def _bairro_igual(pags: list[str], bairro: str, dif) -> None:
    """117 (D-131): o setor se escreve como no documento em TODO o laudo. "Jardim Curitiba I" (conta de água e
    escritura) não pode aparecer como "Jardim Curitiba" na capa, no quadro, na legenda e no resumo. Só confere quando
    o nome tem o número no fim (I, II, 2…): é aí que a versão curta é outro setor."""
    m = _SUFIXO_BAIRRO.match(" ".join((bairro or "").split()))
    if not m:
        return
    base, suf = m.group(1), m.group(2)
    rx = re.compile(r"(?i)\b" + r"\s+".join(map(re.escape, base.split())) + r"\b(?!\s*[-–]?\s*" + re.escape(suf) + r"\b)"
                    r"(?!\s+(?:I{1,3}|IV|V|\d)\b)")
    vistos = set()
    for pg, t in enumerate(pags, 1):
        for mm in rx.finditer(t):
            if pg in vistos:
                break
            # 126: só o endereço do AVALIANDO; o anúncio (referencial/comparação) e o texto do mercado ficam como estão
            if not _DO_AVALIANDO.search(t[max(0, mm.start() - 120):mm.start()]):
                continue
            vistos.add(pg)
            dif(Diferenca(BAIRRO, f"pág. {pg}", t[max(0, mm.start() - 25):mm.end() + 15].strip(), bairro))


def _agrupar(difs: list[Diferenca]) -> list[Diferenca]:
    """A mesma diferença em várias páginas vira uma linha ("págs. 1, 2, 3")."""
    out: dict[tuple, Diferenca] = {}
    pgs: dict[tuple, list[str]] = {}
    for d in difs:
        k = (d.dado, d.encontrado, d.esperado)
        out.setdefault(k, d)
        pgs.setdefault(k, []).append(d.pagina)
    final = []
    for k, d in out.items():
        lista = list(dict.fromkeys(pgs[k]))
        if len(lista) > 1 and all(x.startswith("pág. ") for x in lista):
            d = Diferenca(d.dado, "págs. " + ", ".join(x[5:] for x in lista), d.encontrado, d.esperado)
        _para_a_tela(d, lista)
        final.append(d)
    return final


# 120: o que é para o avaliador decidir (o resto o sistema corrige ou explica — D-100) e a sugestão de um toque
_DO_AVALIADOR = {DUAS_DATAS, "data-base", "data-base (a que o avaliador informou)", BAIRRO}


def _trecho(encontrado: str) -> str:
    """O pedaço literal do PDF para realçar: o que está entre aspas, senão o valor antes do parêntese."""
    m = re.search(r"[\"“«](.+?)[\"”»]", encontrado or "")
    return (m.group(1) if m else re.split(r"\s+\(", encontrado or "", maxsplit=1)[0]).strip()[:120]


def _para_a_tela(d: Diferenca, paginas: list[str]) -> None:
    t = _trecho(d.encontrado)
    d.lugares = [{"pagina": int(p[5:]), "trecho": t} for p in paginas if re.fullmatch(r"pág\. \d+", p)]
    d.do_avaliador = d.dado in _DO_AVALIADOR
    if d.dado in (DUAS_DATAS, "data-base", "data-base (a que o avaliador informou)"):
        m = re.search(r"\d{2}/\d{2}/\d{4}", d.esperado or "")
        if m:
            d.sugestao, d.valor_sugerido = f"Usar {m.group(0)} (data da vistoria) em todo o laudo", m.group(0)
    elif d.dado == BAIRRO and d.esperado:
        d.sugestao, d.valor_sugerido = f"Escrever “{d.esperado}” em todo o laudo, como no documento", d.esperado


def do_trabalho(job_id: str, pdf: Path, xlsx: Path | None, r: calculo.Resultado) -> Resultado:
    """Conferência com os dados do trabalho (seleção confirmada, área, data-base e número)."""
    from . import db
    from .agentes import _comum
    from .agentes.selecao import Selecao, area_construida, refs_na_base
    t = _comum.trabalho(job_id)
    sel_d = db.resultado(job_id, "selecao") or {}
    refs = refs_na_base(job_id, [x for x in Selecao.model_validate(sel_d).refs if x.escolhido]) if sel_d else []
    area = area_construida(job_id)
    # 117 (D-127): a data de referência do laudo é SEMPRE a da vistoria — nenhuma "data-base" de outro documento
    # (a DITCD do ITCD inclusive); a 085-1 (data informada × vistoria) deixa de valer
    ref = t.data_vistoria or t.data_base
    esp = do_resultado(r, area if area is not None else Decimal(0), refs, ref, t.numero)
    esp.bairro = t.bairro or ""
    esp.doc_valores, esp.doc_numeros = _valores_do_trabalho(job_id)      # 101-2
    try:
        from . import db as _db
        esp.cv_fora = bool(_db.cv_so_na_planilha(job_id))                 # 101-1
    except Exception:
        esp.cv_fora = False
    esp.data_vistoria = t.data_vistoria
    try:                                   # L200 (Caso M): o CNAI certo é o do avaliador do trabalho
        from . import avaliadores
        esp.cnai = re.sub(r"\D", "", avaliadores.identidade_avaliador(t.avaliador_id or "AV-0001")["cnai"])
    except Exception:
        esp.cnai = None
    return conferir(pdf, xlsx, esp)


_ROT_DATA_BASE = re.compile(r"(?i)ditcd|data[\s_-]*base|data[\s_]*da[\s_]*declara")
_NAO_E_BASE = re.compile(r"(?i)comunicado|ci[eê]ncia|vistoria|emiss|escritura|nascimento")


def _como_data(v) -> date | None:
    if isinstance(v, date):
        return v
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})|(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m.group(1) else date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
    except ValueError:
        return None


def data_base_informada(job_id: str) -> date | None:
    """085-1: a data-base que o avaliador deu (campo ou resposta: "Data da DITCD 28/10/2026 (data-base)")."""
    from . import db
    for c in db.campos(job_id):
        if _ROT_DATA_BASE.search(c.nome) and not _NAO_E_BASE.search(c.nome) and _como_data(c.valor):
            return _como_data(c.valor)
    try:
        from . import tela_trabalho
        ctx = (tela_trabalho._cliente(job_id) or {}).get("contexto") or {}
    except Exception:
        ctx = {}
    if _como_data(ctx.get("data_ditcd")):          # gravada pela análise da visita (AAAA-MM-DD)
        return _como_data(ctx.get("data_ditcd"))
    for k, v in ctx.items():
        if isinstance(v, (str, date)) and _ROT_DATA_BASE.search(k) and not _NAO_E_BASE.search(k) and _como_data(v):
            return _como_data(v)
    return None


# ------------------------------------------------------------------ 087: o JdB corrige sozinho
PREFIXO = "conferência de coerência (D-084)"     # todo texto que sai daqui começa assim: vai para "corrijo sozinho"
# 100-1 (GRAVE): troca automática SÓ do que não tem como ser número de outro documento. Valor, área, unitário,
# faixa e data-base NUNCA são trocados sozinhos (no 9125 a troca levou o declarado do ITCD e a conta da FIPE para os
# números do laudo); essas diferenças voltam para o montador/avaliador.
_SUBSTITUIVEIS = ("data da assinatura", "número do laudo", "CNAI", RESTO_DATA_BASE)
DISPERSAO = "frase sobre dispersão dos referenciais (D-068)"


def substituicoes(res: Resultado) -> list[tuple[str, str]]:
    """087: as diferenças que são erro de TEXTO do JdB e têm troca segura (o número/data/extenso escrito no PDF por
    o certo). A montagem aplica essas trocas no texto do laudo e remonta — não é pergunta ao avaliador.
    Fica fora o que não tem troca exata (planilha vazia, "não encontrado", data da vistoria × DITCD sem a data)."""
    out: list[tuple[str, str]] = []
    do_trabalho = bool(res.conferidos.get("valor_do_trabalho"))
    for d in res.diferencas:
        if not d.pagina.startswith(("pág", "págs")) or d.dado not in _SUBSTITUIVEIS:
            continue
        if d.dado not in ("data da assinatura", RESTO_DATA_BASE) and not do_trabalho:
            continue              # o esperado foi adivinhado do próprio PDF: não troca nada sozinho
        de, para = d.encontrado.strip(), d.esperado.strip()
        if not de or not para or de == para or any(x in de for x in ("não encontrado", "vazio", "(a data")):
            continue
        if d.dado == "valor por extenso":
            de, para = de.strip("()"), para.strip("()")
        if (de, para) not in out:
            out.append((de, para))
    return out


_MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro")
_ASSINATURA = re.compile(r"([A-ZÀ-Ú][a-zà-ú]+(?: [A-ZÀ-Ú]?[a-zà-ú]+){0,3}), (\d{1,2}) de ((?i:" + "|".join(_MESES) + r")) de (\d{4})")
_CONSULTA = re.compile(r"(?i)(consulta|pesquisa|acess|captura)[^.;]{0,40}?((?:\d{1,2}(?:\s*,\s*|\s+e\s+))*\d{1,2})/(\d{1,2})/(\d{4})")


def _assinatura_depois_da_pesquisa(pags: list[str], dif) -> None:
    ultima = None
    for t in pags:
        for m in _CONSULTA.finditer(t):
            dias = [int(x) for x in re.findall(r"\d{1,2}", m.group(2))]
            try:
                d = date(int(m.group(4)), int(m.group(3)), max(dias))
            except ValueError:
                continue
            ultima = d if ultima is None or d > ultima else ultima
    if ultima is None:
        return
    for pg, t in enumerate(pags, 1):
        for m in _ASSINATURA.finditer(t):
            try:
                d = date(int(m.group(4)), _MESES.index(m.group(3).lower()) + 1, int(m.group(2)))
            except ValueError:
                continue
            if d < ultima:
                certo = f"{m.group(1)}, {ultima.day} de {_MESES[ultima.month - 1]} de {ultima.year}"
                dif(Diferenca("data da assinatura", f"pág. {pg}", m.group(0), certo))


# ------------------------------------------------------------------ 095-1: página de corpo quase vazia
def paginas_curtas(pdf: Path, minimo: int = 12) -> list[dict]:
    """Páginas do CORPO do laudo com menos de `minimo` linhas de texto (o resto em branco). Ficam fora: a capa, as
    páginas de fotos/imagens (relatório fotográfico, mapas), os anexos e a última página antes dos anexos (a da
    assinatura). Devolve [{"pagina": N, "linhas": n}] — vazio = nenhuma página quase vazia."""
    out: list[dict] = []
    with pymupdf.open(pdf) as d:
        info = []
        for i, pg in enumerate(d, 1):
            alt, larg = pg.rect.height, pg.rect.width
            blocos = pg.get_text("dict")["blocks"]
            ys = {round(l["bbox"][1] / 3) for b in blocos for l in b.get("lines", [])
                  if alt * 0.08 < l["bbox"][1] < alt * 0.92 and "".join(s["text"] for s in l["spans"]).strip()}
            img = sum((b["bbox"][2] - b["bbox"][0]) * (b["bbox"][3] - b["bbox"][1]) for b in blocos if b["type"] == 1)
            corpo = sorted((l["bbox"][1], "".join(s["text"] for s in l["spans"]).strip()) for b in blocos
                           for l in b.get("lines", []) if alt * 0.08 < l["bbox"][1] < alt * 0.92)
            primeira = next((t for _, t in corpo if t), "").upper()
            info.append((i, len(ys), img / (larg * alt), primeira.startswith("ANEXO")))   # o sumário também cita "ANEXO"
    anexo = next((i for i, _, _, a in info if a and i > 2), len(info) + 1)
    ultima_do_corpo = anexo - 1
    for i, linhas, img, _ in info:
        if i == 1 or i >= ultima_do_corpo or img >= 0.15:
            continue
        if linhas < minimo:
            out.append({"pagina": i, "linhas": linhas})
    return out


# ------------------------------------------------------------------ 101: números dos documentos e o CV vetado
_CV_NO_TEXTO = re.compile(r"(?i)coeficiente\s+de\s+varia[çc][ãa]o|\bCV\b|dispers[ãa]o[^.]{0,60}?\d+[.,]\d+\s*%")

# 106 (D-068, regra do projeto, toda modalidade): o laudo não fala de dispersão dos referenciais — nem com número,
# nem sem número, nem remetendo à planilha. "Mercado raso" (poucas ofertas) pode; "dispersos/heterogêneas" não.
_DISP_SEMPRE = re.compile(r"(?i:dispers\w*|coeficiente\s+de\s+varia\w*|desvio[- ]?padr\w*|variabilidade|"
                          r"amplitude\s+d[oe]s\s+valores|discrep\w*\s+entre\s+(?:as\s+|os\s+)?"
                          r"(?:amostras|referenciais|valores|ofertas|dados))|\bCV\b")
_DISP_CONTEXTO = re.compile(r"(?i)heterog[êe]ne\w*|espalh\w*")
_DE_VALORES = re.compile(r"(?i)amostra|referenc|valor|ofert|unit[áa]ri|pre[çc]o|dados")
_FRASE = re.compile(r"(?<=[.!?;])\s+(?=[A-ZÀ-Ú\"“(])")
_ABRE_CAUSA = re.compile(r"(?i)^(?:considerando|diante|em\s+raz[ãa]o|em\s+fun[çc][ãa]o|dad[ao]s?|devido|face|tendo\s+em\s+vista)\b")


def _vetada(s: str) -> bool:
    return bool(_DISP_SEMPRE.search(s) or (_DISP_CONTEXTO.search(s) and _DE_VALORES.search(s)))


def frases_dispersao(texto: str) -> list[str]:
    """As frases do texto que falam da dispersão/variação entre os valores dos referenciais (106)."""
    t = " ".join((texto or "").split())
    return [s for s in _FRASE.split(t) if _vetada(s)]


def _limpar_frase(s: str) -> str:
    """Uma frase vetada: tira só a parte sobre dispersão quando o resto se sustenta; senão, a frase toda ("")."""
    # "A faixa … admitida considera essa dispersão e as oscilações …" -> "… considera as oscilações …"
    sem_par = re.sub(r"(?i)\b(?:essa|esta|tal|a)\s+dispers[ãa]o(?:\s+d[oa]s\s+valores(?:\s+unit[áa]rios)?)?\s+e\s+", "", s)
    if sem_par != s and not _vetada(sem_par):
        return sem_par
    partes = [p.strip() for p in s.split(",")]
    if len(partes) > 1 and _vetada(partes[0]) and _ABRE_CAUSA.match(partes[0]):
        resto = ", ".join(partes[1:])                       # "Considerando essa dispersão, admite-se faixa…"
        if not _vetada(resto):
            return resto[:1].upper() + resto[1:]
    if len(partes) > 1 and not _vetada(partes[0]):           # "…mercado raso, com valores bastante dispersos."
        bons = []
        for p in partes:
            if _vetada(p):
                break
            bons.append(p)
        fim = s.rstrip()[-1:] if s.rstrip()[-1:] in ".;!?" else "."
        return ", ".join(bons).rstrip(" .;") + fim
    return ""


def sem_dispersao(texto: str) -> str:
    """O texto sem nenhuma frase sobre dispersão dos referenciais (106-3: a trava corrige sozinha, sem perguntar)."""
    if not texto or not _vetada(texto):
        return texto
    lead = texto[:len(texto) - len(texto.lstrip())]
    t = " ".join(texto.split())
    frases = [(_limpar_frase(s) if _vetada(s) else s) for s in _FRASE.split(t)]
    return lead + " ".join(f for f in frases if f.strip())
_ROTULOS_DOC = (("declarado", re.compile(r"(?i)declarad")),
                ("referência", re.compile(r"(?i)valor\s+(?:total\s+)?de\s+refer[êe]ncia\b|\brefer[êe]ncia\s+(?:da|do)\s+(?:sefaz|itcd|malha)")),
                ("FIPE", re.compile(r"(?i)\bFIPE\b")),
                ("venal", re.compile(r"(?i)\bvenal\b")))
_PARTE_DA_CONTA = re.compile(r"(?i)terreno|constru[çc][ãa]o|composto|m²|/m")


def _rotulo_doc(t: str, ini: int, fim: int) -> str | None:
    """O documento a que o número pertence: o rótulo mais perto ANTES (até 70 caracteres, sem outro R$ no meio);
    senão o logo DEPOIS ("R$ 173.000,00, valor declarado no ITCD")."""
    antes = t[max(0, ini - 70):ini]
    antes = antes[antes.rfind("R$") + 2:] if "R$" in antes else antes
    corte = max(antes.rfind(x) for x in (";", "•", ". ", "\n"))      # só a frase/tópico do próprio número
    antes = antes[corte + 1:] if corte >= 0 else antes
    melhor, pos = None, -1
    for nome, rx in _ROTULOS_DOC:
        for m in rx.finditer(antes):
            if m.start() > pos:
                melhor, pos = nome, m.start()
    if melhor:
        return melhor
    depois = t[fim:fim + 45]
    depois = depois[:depois.find("R$")] if "R$" in depois else depois
    achados = [(rx.search(depois).start(), nome) for nome, rx in _ROTULOS_DOC if rx.search(depois)]
    return min(achados)[1] if achados else None


def _numeros_dos_documentos(pags: list[str], esp: "Esperado", dif) -> None:
    vistos = set()
    for pg, t in enumerate(pags, 1):
        # 101-2: a conta da FIPE (terreno/construção) nunca é feita com a área e o unitário DESTE laudo
        if esp.area is not None and esp.unitario is not None:
            for m in _EQUACAO.finditer(t):
                if re.search(r"(?i)\bFIPE\b", t[max(0, m.start() - 200):m.start()]) and \
                        num_br(m.group(1)) == esp.area and num_br(m.group(2)) == esp.unitario:
                    dif(Diferenca("conta da FIPE (documento)", f"pág. {pg}", m.group(0)[:60],
                                  "a área e o unitário do relatório FIPE, não os deste laudo"))
        for m in re.finditer(_RS, t):
            if re.match(r"\s*/\s*m", t[m.end():m.end() + 5]):
                continue                     # R$/m² (unitário), nunca valor de documento
            nome = _rotulo_doc(t, m.start(), m.end())
            certo = esp.doc_valores.get(nome) if nome else None
            if certo is None:
                continue
            if _PARTE_DA_CONTA.search(t[m.end():m.end() + 12]) and nome == "FIPE":
                continue                     # parcela da conta da FIPE (terreno/construção), não o valor médio
            v = num_br(m.group(1))
            if v != certo and (pg, nome, v) not in vistos:
                vistos.add((pg, nome, v))
                dif(Diferenca(f"valor {nome} (documento)", f"pág. {pg}", brl(v), brl(certo)))
        for nome, rx in (("matrícula", r"(?i)matr[íi]cula(?!\s+(?:de\s+origem|m[ãa]e))\D{0,25}?(\d{1,3}(?:\.\d{3})+|\d{4,7})"),
                         ("inscrição", r"(?i)inscri[çc][ãa]o(?:\s+imobili[áa]ria|\s+municipal)?\D{0,20}?(\d[\d.\-]{8,})")):
            certos = esp.doc_numeros.get(nome) or []
            if not certos:
                continue
            for m in re.finditer(rx, t):
                achado = re.sub(r"\D", "", m.group(1))
                # 104-1: a matrícula de ORIGEM/anterior/mãe é citada de propósito ("… menciona a Matrícula nº 40.800
                # como origem"): só a que o laudo afirma ser a do imóvel é conferida
                ini_f = max(t.rfind(". ", 0, m.start()), t.rfind("; ", 0, m.start()), m.start() - 120) + 1
                fim_f = min([x for x in (t.find(". ", m.end()), t.find("; ", m.end())) if x >= 0] + [m.end() + 120])
                vizinho = t[max(0, ini_f):fim_f]                 # só a frase do próprio número
                if nome == "matrícula" and re.search(r"(?i)origem|anterior|m[ãa]e\b|matriz|antiga|desmembrad|unificad", vizinho):
                    continue
                if achado and not any(achado == re.sub(r"\D", "", c) for c in certos) and (pg, nome, achado) not in vistos:
                    vistos.add((pg, nome, achado))
                    dif(Diferenca(f"{nome} (documento)", f"pág. {pg}", m.group(1), " ou ".join(certos)))


def _valores_do_trabalho(job_id: str) -> tuple[dict, dict]:
    """Os valores e números dos documentos, pelos campos extraídos (qualquer nome que o leitor tenha dado)."""
    from . import db
    vals, nums = {}, {"matrícula": [], "inscrição": []}
    for c in db.campos(job_id):
        if c.origem != "documento" or c.valor in (None, ""):
            continue
        n = c.nome.replace("_", " ").lower()
        try:
            dv = Decimal(str(c.valor)) if isinstance(c.valor, (int, float)) else None
        except Exception:
            dv = None
        if dv is not None:
            for rot, chave in (("declarad", "declarado"), ("referência", "referência"), ("referencia", "referência"),
                               ("fipe", "FIPE"), ("venal", "venal")):
                if rot in n and chave not in vals and dv > 1000:
                    vals[chave] = _q2(dv)
        if "matr" in n and re.search(r"\d", str(c.valor)) and len(re.sub(r"\D", "", str(c.valor))) <= 7:
            nums["matrícula"].append(str(c.valor).strip())
        if "inscri" in n and len(re.sub(r"\D", "", str(c.valor))) >= 9:
            nums["inscrição"].append(str(c.valor).strip())
    return vals, {k: list(dict.fromkeys(v)) for k, v in nums.items() if v}
