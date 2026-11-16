"""Lista de candidatos da pesquisa (ORDEM 003): leitura dos cartões da página de RESULTADOS
dos portais (sem abrir o anúncio, sem IA), semelhança com o avaliando (D-010/D-021),
recomendação (★) / não recomendação (riscado) com motivo, observação do que conferir, e
exportação .md/.xlsx. A numeração é estável: um candidato nunca muda de número."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .modelos import Referencial

MAX_LISTA = 20       # 1ª rodada: lista de 10 a 20
MAX_MAIS = 10        # "Pedir mais": até 10 novos por pedido
MAX_RECOMENDADOS = 8


def _n(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.casefold().split())


def _num(s: str) -> float | None:
    s = s.strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


# ------------------------------------------------------------------ leitura do cartão
_AGENCIA = re.compile(r"(?i)im[óo]veis|imobili[áa]ria|corretor|creci|destaque|\+\d+ fotos|"
                      r"enviar mensagem|ver telefone|contatar")
_RUA = re.compile(r"(?i)^(rua|r\.|avenida|av\.|alameda|al\.|travessa|tv\.|pra[çc]a|rodovia)\s")


@dataclass
class Cartao:
    link: str
    portal: str
    texto: str
    foto: str = ""


def _titulo(linhas: list[str]) -> str:
    cand = [ln for ln in linhas[:8] if len(ln) > 18 and "R$" not in ln and not _AGENCIA.search(ln)
            and not re.fullmatch(r"[\d.,]+\s*m²?", ln)]
    return max(cand, key=len)[:160] if cand else ""


def tipologia_classe(txt: str) -> str:
    t = _n(txt)
    if re.search(r"kitnet|kitinete|studio|loft|quitinete", t):
        return "kitnet"
    if re.search(r"apart|apto|\bflat\b|cobertura|duplex", t):
        return "apartamento"
    if "sobrado" in t:
        return "sobrado"
    if re.search(r"terrea|terreo", t):
        return "casa térrea"
    if re.search(r"galpao|barracao comercial|\bloja\b|sala comercial|predio comercial|ponto comercial", t):
        return "comercial"
    if re.search(r"\bcasa", t):   # "casa … amplo terreno" é casa
        return "casa"
    if re.search(r"\blote\b|terreno", t):
        return "terreno"
    return ""


def ler_cartao(c: Cartao, cidade: str) -> Referencial | None:
    """Dados do cartão de resultado. None se não achar preço e área."""
    txt = c.texto.replace("\xa0", " ")
    linhas = [ln.strip() for ln in txt.splitlines() if ln.strip()]
    plano = " | ".join(linhas)
    # preço: maior valor em R$ que não seja condomínio/IPTU
    precos = []
    for m in re.finditer(r"R\$\s*([\d.]+(?:,\d{2})?)", plano):
        antes = plano[max(0, m.start() - 14):m.start()].casefold()
        if "cond" in antes or "iptu" in antes:
            continue
        v = _num(m.group(1))
        if v and v >= 20000:
            precos.append(v)
    preco = max(precos) if precos else None
    # área construída
    area, area_total = None, False
    m = re.search(r"Tamanho do im[óo]vel \| ([\d.,]+)\s*m", plano)
    if m:
        area = _num(m.group(1))
    if area is None:
        m = re.search(r"([\d.,]+)\s*m²\s*(?:[úu]til|cob|constr)", plano, re.I)
        if m:
            area = _num(m.group(1))
    if area is None:
        m = re.search(r"([\d.,]+)\s*m²\s*tot", plano, re.I)
        if m:
            area, area_total = _num(m.group(1)), True
    if area is None:
        m = re.search(r"(?:^| \| )([\d.,]+)\s*m²(?: \||$)", plano)   # linha só com a área (OLX)
        if m:
            area = _num(m.group(1))
    if area is None:
        m = re.search(r"\b([\d.,]+)\s*m²", plano)
        if m:
            area = _num(m.group(1))
    lote = None
    m = re.search(r"(?i)(?:terreno|lote)[:\s]*(?:de\s*)?([\d.,]+)\s*m", plano) or \
        re.search(r"(?i)([\d.,]+)\s*m²\s*de\s*(?:terreno|lote)", plano)
    if m:
        lote = _num(m.group(1))
    # quartos / suítes
    quartos = None
    m = re.search(r"Quantidade de quartos \| (\d+)", plano) or re.search(r"(\d+)\s*quartos?", plano, re.I)
    if m:
        quartos = int(m.group(1))
    elif area is not None:   # OLX: área | quartos | banheiros | vagas
        m = re.search(r"\d+\s*m² \| (\d{1,2}) \|", plano)
        if m:
            quartos = int(m.group(1))
    suites = None
    m = re.search(r"(?i)(?:sendo\s*)?(\d+|uma|um|duas|dois|tr[êe]s|quatro)\s*su[íi]tes?", plano)
    if m:
        suites = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "três": 3, "quatro": 4}.get(
            m.group(1).casefold(), None) or (int(m.group(1)) if m.group(1).isdigit() else None)
    # bairro / rua
    cid = _n(cidade)
    bairro, rua = "", ""
    for ln in linhas:   # "Bairro, Cidade" (ZAP/VR/Imovelweb) ou "Cidade, Bairro" (OLX)
        partes = [p.strip() for p in ln.split(",")]
        if not bairro and len(partes) == 2 and len(ln) < 70 and "R$" not in ln:
            if _n(partes[1]) == cid:
                bairro = partes[0]
            elif _n(partes[0]) == cid:
                bairro = partes[1]
        if not rua and _RUA.match(ln):
            rua = ln[:80]
    if not bairro and cid:   # último recurso: linha curta com a cidade
        for ln in linhas:
            partes = [p.strip() for p in re.split(r",| - ", ln)]
            if cid in _n(ln) and len(ln) < 50 and len(partes) >= 2:
                outras = [p for p in partes if _n(p) != cid and p]
                if outras:
                    bairro = outras[-1]
                    break
    titulo = _titulo(linhas)
    if preco is None or area is None:
        return None
    r = Referencial(n=0, link=c.link, portal=c.portal, bairro=bairro, rua=rua, titulo=titulo,
                    tipologia=tipologia_classe(titulo + " " + c.link) or "—", quartos=quartos,
                    suites=suites, lote_m2=lote, area_m2=area, preco=preco, padrao="",
                    idade_aparente="", descricao=(titulo or plano[:200]), print_="",
                    foto="", fonte_coleta="coletor")
    if area_total:
        r = r.model_copy(update={"observacao": "área do anúncio é 'total' — conferir se é a do terreno"})
    return r


# ------------------------------------------------------------------ semelhança
_SUPERIOR = re.compile(r"piscina|sauna|alto padrao|luxo|mobiliad|decorad|hidromassagem|automacao")
# 091-1: "novo" solto (propaganda da página: "Imóvel novo? Anuncie") e "acabamento simples" não são imóvel novo
_NOVO = re.compile(r"\b(?:casa|imovel|sobrado|residencia|construcao) nov[oa]\b(?!\s*\?)|lancamento|na planta|em construcao|"
                   r"recem[- ]constru|em (?:fase de )?acabamento|entrega em|nunca habitad")
_RENDA = re.compile(r"\brenda\b|kitnets?|barracoes|duas casas|2 casas|tres casas|3 casas|"
                    r"casas independentes|varias unidades|predio de")
_REFORMA = re.compile(r"reformad|reforma recente|totalmente reformad")
_ANTIGO = re.compile(r"antig|precisa de reforma|necessita de reforma|para reformar|oportunidade")
_INDICIO_SUPERIOR = re.compile(r"churrasqueira|gourmet|porcelanato|planejad|armario embutido|"
                               r"armarios embutidos|lazer completo|area de lazer|acabamento de primeira")
_SIMPLES = re.compile(r"simples|precisa de reforma|necessita de reforma|para reformar|antig|"
                      r"original|padrao popular")
_CONDO_FECHADO = re.compile(r"casa de condominio|casas? em condominio|condominio fechado|"
                            r"residencial fechado|jardins florenca|sobrado em condominio|portaria 24")


@dataclass
class Avaliando:
    tipo: str
    bairro: str
    cidade: str
    area: float | None = None
    quartos: int | None = None
    padrao: str = ""          # "simples"…
    antigo: bool = True       # idade aparente alta (≥ 15 anos)
    condominio: str = ""      # edifício/condomínio (apto): os do mesmo vêm primeiro
    vizinhos: tuple[str, ...] = ()
    conhecidos: tuple[str, ...] = ()   # nomes de bairros (para conferir cartão × link × título)
    idade_anos: float | None = None    # L201-3: idade do avaliando (meio da faixa confirmada; "15 a 30" → 22,5)


_NAO_BAIRRO = re.compile(r"venda|vende|casa|sobrado|imovel|apartamento|aluguel|quarto|comprar")


def _bairro_em(texto_n: str, conhecidos) -> str:
    """Bairro conhecido mais específico (nome mais longo) citado no texto normalizado."""
    achados = [b for b in conhecidos if _n(b) and _n(b) in texto_n]
    return max(achados, key=len) if achados else ""


def conferir_bairro(r: Referencial, a: Avaliando) -> tuple[str, str]:
    """(bairro, aviso). Cartão com título no lugar do bairro, ou link de outro bairro: usa o
    mais específico (link > título > cartão) e avisa para conferir."""
    card = (r.bairro or "").strip()
    link_n = _n(re.sub(r"[-_/]", " ", r.link))
    titulo_n = _n(r.titulo)
    do_link = _bairro_em(link_n, a.conhecidos)
    do_titulo = _bairro_em(titulo_n, a.conhecidos)
    if not card or _NAO_BAIRRO.search(_n(card)):
        novo = do_link or do_titulo
        return (novo, f"bairro lido do {'link' if do_link else 'título'}: conferir") if novo else (
            "", "bairro não informado no cartão")
    if do_link and _n(do_link) != _n(card) and len(do_link) >= 6:
        return do_link, f"bairro divergente (cartão: {card} × link: {do_link}): conferir"
    return card, ""


def _anos_ref(idade: str) -> float | None:
    """Idade do referencial em anos ("10 anos", "15 a 20 anos" → meio da faixa); None se não diz."""
    m = re.search(r"(\d+)(?:\s*(?:a|e|-)\s*(\d+))?\s*anos", idade or "")
    if not m:
        return None
    a = float(m.group(1))
    return (a + float(m.group(2))) / 2 if m.group(2) else a


def destoa(r: Referencial, av: "Avaliando") -> list[str]:
    """L201-3 / regra 6 do projeto: o referencial destoa do avaliando? Etiquetas curtas ("padrão superior",
    "mais novo"). A mesma regra serve a lista (descem), a escolha automática (ficam de fora) e o aviso ao marcar."""
    out: list[str] = []
    pd, idd = _n(r.padrao or ""), _n(r.idade_aparente or "")
    txt = _texto_util(r) + " " + _n(getattr(r, "destaque", "") or "")   # o destaque vem do texto inteiro do anúncio
    alto = any(w in pd for w in ("alto", "luxo", "superior")) and av.padrao not in ("alto", "luxo")
    if av.padrao.startswith("simples") and (_SUPERIOR.search(txt) or _INDICIO_SUPERIOR.search(txt)):
        alto = True          # avaliando simples: piscina, gourmet, porcelanato, planejados já destoam
    elif av.padrao.startswith("normal") and _SUPERIOR.search(txt):
        alto = True          # avaliando normal: só o forte (piscina, sauna, luxo, alto padrão)
    if r.quartos and r.suites and r.quartos >= 2 and r.suites >= r.quartos and av.padrao.startswith("simples"):
        alto = True
    if alto:
        out.append("padrão superior")
    novo = av.antigo and (idd.startswith("novo") or idd.startswith("seminovo") or "planta" in idd
                          or "lancamento" in idd or bool(_NOVO.search(txt)))
    anos = _anos_ref(r.idade_aparente or "")
    if av.idade_anos is not None and anos is not None and anos < av.idade_anos - 10:
        novo = True          # 10 anos a menos que o avaliando ("15 a 30 anos" × "10 anos")
    if novo:
        out.append("mais novo")
    return out


def _texto_util(r: Referencial) -> str:
    """Título/descrição sem o nome da imobiliária ("… Imóveis Alto Padrão" não é padrão)."""
    linhas = [ln for ln in (r.titulo + "\n" + r.descricao).splitlines() if not _AGENCIA.search(ln)]
    return _n(" ".join(linhas) + " " + r.link.replace("-", " "))


def avaliar(r: Referencial, a: Avaliando) -> Referencial:
    """Pontua a semelhança (tipologia e padrão primeiro; depois idade, quartos, área ±40%,
    bairro) e decide ★ / riscado com o motivo e a observação do que conferir."""
    txt = _texto_util(r)
    cls_av, cls = tipologia_classe(a.tipo), (r.tipologia if r.tipologia != "—" else "")
    # só a nota que veio da leitura do cartão; o resto é recalculado (a reserva é reavaliada
    # a cada "Pedir mais" e as notas se repetiam)
    obs = [x for x in (r.observacao or "").split("; ") if x.startswith("área do anúncio é 'total'")][:1]
    motivos_bons, riscos = [], []
    if a.conhecidos:
        bairro, aviso = conferir_bairro(r, a)
        r = r.model_copy(update={"bairro": bairro})
        if aviso and aviso != "bairro não informado no cartão":
            obs.append(aviso)
    pts = 0
    sem_estrela = ""
    # tipologia: ★ só com a MESMA tipologia confirmada (ORDEM 005); "casa" sem indicação de
    # sobrado, com avaliando sobrado, fica sem ★ e com "confirmar se é sobrado"
    if cls_av and cls != cls_av:
        sem_estrela = "tipologia não confirmada"
    if cls and cls_av:
        if cls == cls_av:
            pts += 6
            motivos_bons.append("mesma tipologia")
        elif {cls, cls_av} <= {"sobrado", "casa", "casa térrea"}:
            pts += 3 if "casa" in (cls, cls_av) else 1
            if {cls, cls_av} == {"sobrado", "casa térrea"}:
                obs.append("casa térrea × sobrado: tipologia próxima, não igual")
            else:
                obs.append("confirmar se é sobrado")
        else:
            riscos.append(f"tipologia diferente ({cls})")
    # condomínio/edifício (apartamento)
    if a.condominio:
        toks = [t for t in _n(a.condominio).split() if len(t) > 3 and t not in
                ("edificio", "condominio", "residencial", "torre", "bloco")]
        if toks and all(t in txt for t in toks[-2:]):
            pts += 5
            motivos_bons.insert(0, "mesmo condomínio")
    # padrão / idade / renda
    if _SUPERIOR.search(txt):
        riscos.append("padrão superior (" + _SUPERIOR.search(txt).group(0) + ")")
    if a.antigo and _NOVO.search(txt):
        riscos.append("imóvel novo/em acabamento (avaliando antigo)")
    if _RENDA.search(txt):
        riscos.append("imóvel de renda / várias unidades")
    if cls_av in ("sobrado", "casa", "casa térrea") and not a.condominio and _CONDO_FECHADO.search(txt):
        riscos.append("condomínio fechado (avaliando em rua aberta: segmento diferente)")
    if _REFORMA.search(txt):
        obs.append("anúncio fala em reforma: conferir padrão e estado nas fotos")
    # indícios de padrão superior / imóvel mais novo: tiram pontos (o Alan confere)
    indicios = [m.group(0) for m in _INDICIO_SUPERIOR.finditer(txt)]
    if r.quartos and r.suites and r.quartos >= 2 and r.suites >= r.quartos:
        indicios.append("todos os quartos são suítes")
    if indicios:
        pts -= 3
        obs.append("indícios de padrão superior/mais novo: " + ", ".join(dict.fromkeys(indicios)))
    if a.antigo and _ANTIGO.search(txt):
        pts += 1
        motivos_bons.append("antigo")
    # padrão: só com indício no texto (o cartão quase nunca diz) — senão, conferir no anúncio
    if _SIMPLES.search(txt) and not indicios and not _SUPERIOR.search(txt):
        pts += 1
        motivos_bons.append("indício de padrão simples (" + _SIMPLES.search(txt).group(0) + ")")
    elif not indicios and not _SUPERIOR.search(txt):
        obs.insert(0, "padrão/idade: conferir no anúncio")
    # área (D-056: o porquê traz o número; quanto mais perto, mais ponto)
    if a.area and r.area_m2:
        dif = abs(r.area_m2 - a.area) / a.area
        quanto = f"{_milhar(r.area_m2)} m², {(r.area_m2 - a.area) / a.area * 100:+.0f}% do avaliando"
        if dif <= 0.2:
            pts += 3
            motivos_bons.append(f"área parecida ({quanto})")
        elif dif <= 0.4:
            pts += 2
            motivos_bons.append(f"área compatível ({quanto})")
        elif dif <= 0.6:
            pts += 1
            obs.append(f"área {r.area_m2:.0f} m² × {a.area:.0f} m² do avaliando")
        else:
            pts -= 1
            obs.append(f"área bem diferente ({r.area_m2:.0f} m² × {a.area:.0f} m²)")
    # quartos
    if a.quartos and r.quartos is not None and abs(r.quartos - a.quartos) <= 1:
        pts += 1
        motivos_bons.append(f"{r.quartos} quartos")
    # bairro
    b = _n(r.bairro)
    if b and b == _n(a.bairro):
        pts += 3
        motivos_bons.insert(1 if motivos_bons[:1] == ["mesmo condomínio"] else 0,
                            f"mesmo bairro ({a.bairro})")
    elif b and b in {_n(v) for v in a.vizinhos}:
        pts += 2
        motivos_bons.append("bairro limítrofe")
    elif b:
        obs.append(f"bairro {r.bairro}: conferir se é da mesma região")
    else:
        obs.append("bairro não informado no cartão")
    # galpão/comercial: polo, distrito ou parque industrial pesa como a vizinhança (D-056)
    if (cls_av == "comercial" and b and b != _n(a.bairro) and _INDUSTRIAL.search(_n(a.bairro))
            and _INDUSTRIAL.search(b)):
        pts += 2
        motivos_bons.append("região industrial/empresarial, como o avaliando")
    # anúncio contraditório
    if r.preco and r.area_m2:
        u = r.preco / r.area_m2
        if r.area_m2 < 25 or u < 600 or u > 18000:
            riscos.append(f"anúncio contraditório (R$ {u:,.0f}/m²)".replace(",", "."))
    if r.lote_m2 and r.area_m2 and r.area_m2 > r.lote_m2 * 2.5:
        obs.append("área construída muito maior que o lote: conferir")
    upd = {"pontos": pts, "observacao": "; ".join(dict.fromkeys(o for o in obs if o))[:300],
           "sem_estrela": sem_estrela, "recomendado": False}
    if riscos and r.fonte_coleta in ("avaliador", "manual"):
        # 091-1: anúncio que o AVALIADOR trouxe nunca é descartado pelo sistema: só o aviso, quem tira é ele
        upd.update(nao_recomendado=False, recomendado=False,
                   motivo=("; ".join(riscos) + " — confira")[:200])     # 093-6: a tela já escreve "Atenção:"
    elif riscos:
        upd.update(nao_recomendado=True, recomendado=False, motivo="; ".join(riscos)[:200])
    else:
        upd.update(nao_recomendado=False, motivo=", ".join(dict.fromkeys(motivos_bons))[:200])
    return r.model_copy(update=upd)


_INDUSTRIAL = re.compile(r"polo|industrial|distrito|daiag|empresarial|\bpark\b|logistic|armazen")


TOLERANCIA_AREA = 0.05   # 5%: diferença menor é arredondamento do anúncio


def conferir_area(area_cartao, area_texto, lote_texto=None) -> str:
    """ORDEM 034-1 / F-S003: a área do CARTÃO (lista do portal) × a área construída do TEXTO do
    anúncio. Diferentes -> aviso (o R$/m² usa a do texto). Se a do cartão bate com o terreno do
    texto, diz que o cartão trazia o terreno. Sem uma das duas: "" (nada a conferir)."""
    try:
        c, t = float(area_cartao or 0), float(area_texto or 0)
    except (TypeError, ValueError):
        return ""
    if c <= 0 or t <= 0 or abs(c - t) <= TOLERANCIA_AREA * max(c, t):
        return ""
    msg = (f"área do cartão ({_br(c)} m²) diferente da construída no texto do anúncio ({_br(t)} m²): "
           "o R$/m² usa a do texto")
    try:
        lote = float(lote_texto or 0)
    except (TypeError, ValueError):
        lote = 0
    if lote > 0 and abs(c - lote) <= TOLERANCIA_AREA * max(c, lote):
        msg += " — a área do cartão era a do TERRENO (F-S003)"
    return msg


def _milhar(v: float) -> str:
    return f"{int(round(v)):,}".replace(",", ".")


FORA_ALTO, FORA_BAIXO = 1.3, 0.7   # regra do Alan: preço fora da curva sai da amostra


def _brl(v: float) -> str:
    return f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


LOTES_TIPICOS = (200, 250, 300, 360, 375, 390, 400, 420, 450, 480, 500, 600, 750, 1000)
_CASAS = ("casa", "sobrado", "casa térrea")


def _area_de_terreno(refs: list[Referencial], tipologia_av: str) -> list[Referencial]:
    """Casa com área igual a lote típico e R$/m² baixo para a tipologia do avaliando (abaixo
    de 0,7× a mediana dos não riscados da mesma tipologia) → sem ★, com a observação."""
    import statistics
    if tipologia_av not in _CASAS:
        return refs
    base = [r.preco / r.area_m2 for r in refs if r.preco and r.area_m2 and not r.nao_recomendado
            and r.tipologia == tipologia_av]
    if len(base) < 2:
        base = [r.preco / r.area_m2 for r in refs if r.preco and r.area_m2
                and not r.nao_recomendado and r.tipologia in _CASAS]
    if len(base) < 2:
        return refs
    med = statistics.median(base)
    out = []
    for r in refs:
        if (r.tipologia in _CASAS and r.preco and r.area_m2 and not r.nao_recomendado
                and any(abs(r.area_m2 - l) <= 0.5 for l in LOTES_TIPICOS)
                and r.preco / r.area_m2 < 0.7 * med):
            nota = "área provável de terreno; conferir a área construída no anúncio"
            obs = "; ".join(x for x in (nota, r.observacao) if x and nota not in (r.observacao or ""))
            r = r.model_copy(update={"sem_estrela": r.sem_estrela or "área provável de terreno",
                                     "recomendado": False, "pontos": r.pontos - 2,
                                     "observacao": obs[:300]})
        out.append(r)
    return out


def ajustar_pelo_conjunto(refs: list[Referencial], tipologia_av: str = "") -> list[Referencial]:
    """Preço fora da curva sai da amostra (regra do Alan): mediana do R$/m² dos NÃO riscados
    da mesma tipologia; acima de 1,3× ou abaixo de 0,7× → riscado, visível, com o motivo.
    Depois, área provável de terreno (casa com área = lote típico e R$/m² baixo) perde a ★."""
    return _area_de_terreno(_fora_da_curva(refs), tipologia_av)


def _fora_da_curva(refs: list[Referencial]) -> list[Referencial]:
    import statistics
    grupos: dict[str, list[float]] = {}
    limpos: dict[str, list[float]] = {}   # sem indício de padrão superior/mais novo
    for r in refs:
        if r.preco and r.area_m2 and not r.nao_recomendado:
            grupos.setdefault(r.tipologia, []).append(r.preco / r.area_m2)
            if "indícios de padrão superior" not in (r.observacao or ""):
                limpos.setdefault(r.tipologia, []).append(r.preco / r.area_m2)
    out = []
    for r in refs:
        # a curva é a dos semelhantes sem indício de padrão superior (se houver ≥ 3): os mais
        # novos/caros não podem puxar a mediana e tirar da amostra os antigos simples
        us = limpos.get(r.tipologia) if len(limpos.get(r.tipologia) or []) >= 3 else \
            (grupos.get(r.tipologia) or [])
        if r.preco and r.area_m2 and not r.nao_recomendado and len(us) >= 3:
            med = statistics.median(us)
            u = r.preco / r.area_m2
            if u > FORA_ALTO * med or u < FORA_BAIXO * med:
                extra = ("; abaixo da curva: conferir se a área do anúncio é a do terreno"
                         if u < FORA_BAIXO * med else "")
                r = r.model_copy(update={
                    "nao_recomendado": True, "recomendado": False,
                    "motivo": (f"preço fora da curva (R$ {_brl(u)}/m² × mediana R$ {_brl(med)}/m²)"
                               + extra)[:200]})
        out.append(r)
    return out


def ordenar(refs: list[Referencial]) -> list[Referencial]:
    """Mais semelhantes primeiro; riscados por último."""
    return sorted(refs, key=lambda r: (r.nao_recomendado, -r.pontos,
                                       abs((r.preco or 0) / (r.area_m2 or 1))))


def marcar_recomendados(refs: list[Referencial], minimo_pontos: int = 6,
                        ja: int = 0) -> list[Referencial]:
    """★ nos melhores não riscados (lote parecido ou mesma rua não bastam: precisa de
    tipologia/padrão + outros atributos), até MAX_RECOMENDADOS na lista inteira (`ja` = ★
    que a lista já tem)."""
    out = []
    for r in refs:
        rec = (not r.nao_recomendado and not r.sem_estrela and r.pontos >= minimo_pontos
               and r.decisao != "descarta"
               and ja < MAX_RECOMENDADOS and not r.recomendado)
        if rec:
            ja += 1
        out.append(r.model_copy(update={"recomendado": r.recomendado or rec}))
    return out


def impressao(r: Referencial) -> tuple:
    """Mesmo imóvel em portais diferentes (ZAP e Viva Real repetem anúncios)."""
    return (round(r.area_m2 or 0), int(round((r.preco or 0), -3)), r.quartos,
            _n(r.bairro)[:20])


# ------------------------------------------------------------------ exportação
_CAB = ("Nº", "★", "Link", "Portal", "Bairro", "Tipologia", "Quartos/suítes", "Lote (m²)",
        "Área constr. (m²)", "Preço (R$)", "R$/m²", "Padrão/idade", "Observação", "Decisão")


def _br(v, casas=2) -> str:
    if v is None:
        return "n/i"
    s = f"{v:,.{casas}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def linha(r: Referencial) -> list:
    estrela = "★" if r.recomendado else ("✗" if r.nao_recomendado else "")
    qs = "/".join(str(x) for x in (r.quartos, r.suites) if x is not None) or "n/i"
    padrao = " · ".join(x for x in (r.padrao, r.idade_aparente) if x) or "n/i"
    pre = "NÃO RECOMENDADO: " if r.nao_recomendado else ("★ " if r.recomendado else "Semelhança: ")
    obs = "; ".join(x for x in ((pre + r.motivo)
                                if r.motivo else "", r.observacao,
                                "anúncio bloqueado pelo portal: abrir no navegador" if r.bloqueado else "")
                    if x)
    dec = {"entra": "Entra no laudo", "descarta": "Descartado" + (f" ({r.motivo_descarte})"
                                                                  if r.motivo_descarte else "")}.get(r.decisao, "")
    unit = (r.preco / r.area_m2) if r.preco and r.area_m2 else None
    return [r.n, estrela, r.link, r.portal, r.bairro or "n/i", r.tipologia, qs,
            _br(r.lote_m2) if r.lote_m2 else "n/i", _br(r.area_m2), _br(r.preco), _br(unit),
            padrao, obs, dec]


def markdown(refs: list[Referencial], titulo: str) -> str:
    out = [f"# {titulo}", "", "| " + " | ".join(_CAB) + " |", "|" + "---|" * len(_CAB)]
    for r in sorted(refs, key=lambda x: x.n):
        cel = [str(x).replace("|", "/") for x in linha(r)]
        if r.nao_recomendado:
            cel[2] = f"~~{cel[2]}~~"
        out.append("| " + " | ".join(cel) + " |")
    return "\n".join(out) + "\n"


def planilha(refs: list[Referencial], destino: Path, titulo: str) -> Path:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Candidatos"
    ws.append([titulo])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append(list(_CAB))
    for c in ws[2]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="18283B")
    for r in sorted(refs, key=lambda x: x.n):
        ws.append(linha(r))
        row = ws.max_row
        ws.cell(row, 3).hyperlink = r.link
        ws.cell(row, 3).font = Font(color="0563C1", underline="single", strike=r.nao_recomendado)
        if r.recomendado:
            for col in range(1, len(_CAB) + 1):
                ws.cell(row, col).fill = PatternFill("solid", fgColor="FFF4CC")
    for col, larg in zip("ABCDEFGHIJKLMN", (5, 4, 48, 12, 18, 12, 10, 10, 11, 13, 11, 16, 60, 18)):
        ws.column_dimensions[col].width = larg
    for row in ws.iter_rows(min_row=3):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return destino
