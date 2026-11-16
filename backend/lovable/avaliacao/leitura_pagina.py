"""ORDEM 082-3: a área lida da página do anúncio nunca é chute.

A página aberta no Chrome tem, além do anúncio, os anúncios vizinhos (lateral, "imóveis semelhantes"), o
preço, o telefone… A extensão pega o primeiro "NNN m²" que acha e o leitor do texto (IA) também pode errar.
Regra: a área só vale se for CONFIRMADA:
  1. está no título do anúncio ou no endereço dele ("Possui 110 Metros Quadrados", "...-120m2-id-..."); ou
  2. a extensão e o leitor do texto leram o MESMO número.
Senão: "não achei" (None) e o motivo — o avaliador informa. Lote menor que 60 m² em casa é leitura errada.
"""
from __future__ import annotations

import re

_M2 = r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d{2,5}(?:[.,]\d{1,2})?)\s*(?:m²|m2|mts?²?|metros?\s+quadrados?)"


def _num(s: str) -> float | None:
    t = s.strip()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", t):        # "2.100" e "1.061,39" (milhar com ponto)
        t = t.replace(".", "")
    t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def areas_do_titulo(titulo: str) -> list[float]:
    """Áreas do título do anúncio que não são do lote/terreno ("Casa 110 m²"; "Lote 360 m²" fica fora)."""
    out: list[float] = []
    for m in re.finditer(_M2, titulo or "", flags=re.I):
        if re.search(r"(?i)(lote|terreno)\W{0,12}$", (titulo or "")[:m.start()]):
            continue
        v = _num(m.group(1))
        if v and v not in out:
            out.append(v)
    return out


def areas_do_link(link: str) -> list[float]:
    """Área no endereço do anúncio ("...-120m2-id-..."). Pode ser a do TERRENO (F-S003): só confirma, nunca decide."""
    return [float(m.group(1)) for m in re.finditer(r"[-/](\d{2,5})m2(?:[-/]|$)", (link or "").lower())]


def areas_do_anuncio(titulo: str, link: str) -> list[float]:
    """Áreas escritas no título e no endereço do próprio anúncio (sem a página em volta)."""
    out = areas_do_titulo(titulo)
    return out + [v for v in areas_do_link(link) if v not in out]


def _igual(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) < 0.5


_ROT_CONSTRUIDA = re.compile(
    r"(?i)(?:[áa]rea\s*(?:constru[íi]da|[úu]til|privativa|edificada|interna)|constru[íi]d[oa]s?)\s*(?:de|:|–|-)?\s*"
    r"(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d{2,5}(?:[.,]\d{1,2})?)\s*(?:m²|m2|metros)")
_ROT_CONSTRUIDA_DEPOIS = re.compile(        # 097-2: "1.061,39 m² construídos" (milhar com ponto) inteiro
    r"(?i)(?<![\d.,])(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d{2,5}(?:[.,]\d{1,2})?)\s*(?:m²|m2)\s*(?:de\s+)?(?:[áa]rea\s+)?"
    r"(?:constru[íi]d[oa]s?|[úu]teis|[úu]til|privativ[oa]s?)")


_CASA_N = re.compile(       # 100-2: "contendo uma casa (110m2)", "casa de 110 m²", "construção com 95 m²"
    r"(?i)\b(?:casa|constru[çc][ãa]o|edifica[çc][ãa]o|sobrado|resid[êe]ncia)\s*(?:\(|de\s+|com\s+)\s*"
    r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d{2,5}(?:[.,]\d{1,2})?)\s*(?:m²|m2)")
_RESUMO_AREA = re.compile(  # 100-2: o resumo do próprio anúncio na Deztop ("A casa possui 3 Dormitórios, …, 80m² de Área")
    r"(?i)\bpossui\b[^.\n]{0,120}?(\d{2,5}(?:[.,]\d{1,2})?)\s*m²\s*de\s*[áa]rea")


def area_rotulada(texto: str, titulo: str = "") -> float | None:
    """097-2: a área CONSTRUÍDA escrita com rótulo no texto do PRÓPRIO anúncio ("Área construída 125 m²",
    "110 m² construídos", "casa (110m2)"). Só vale se o anúncio traz um número só (dois números diferentes = não decide).
    100-2: sem rótulo de construída, vale o resumo do próprio anúncio ("…possui …, 80m² de Área"), desde que não seja
    o lote ("lote 10 X 30 = 300 m2" + "300m² de Área" = é o terreno, não a casa)."""
    t = texto_do_anuncio(texto or "", titulo)
    achados = {_num(m.group(1)) for rx in (_ROT_CONSTRUIDA, _ROT_CONSTRUIDA_DEPOIS, _CASA_N) for m in rx.finditer(t)}
    achados.discard(None)
    if achados:
        return achados.pop() if len(achados) == 1 else None
    m = _RESUMO_AREA.search(t)
    if m:
        v = _num(m.group(1))
        lote = lote_confirmado(texto, titulo)
        if v and not (lote and _igual(v, lote)):
            return v
    return None


def area_confirmada(titulo: str, link: str, da_extensao: float | None, do_texto: float | None,
                    texto: str = "") -> tuple[float | None, str]:
    """(área, motivo). None = não achei: nunca um número que não se confirma.
    097-2: com o texto da página (texto=), a área rotulada no próprio anúncio também confirma ou decide."""
    rot = area_rotulada(texto, titulo) if texto else None
    if rot is not None:
        return rot, ("confere com o texto do anúncio" if any(_igual(rot, v) for v in (da_extensao, do_texto))
                     else "área construída escrita no texto do anúncio")
    no_anuncio = areas_do_anuncio(titulo, link)
    for v in (da_extensao, do_texto):
        if v and any(_igual(v, x) for x in no_anuncio):
            return float(v), "confere com o título/endereço do anúncio"
    no_titulo = areas_do_titulo(titulo)          # o link sozinho não decide (pode ser o terreno)
    if len(no_titulo) == 1:
        return no_titulo[0], "do título do anúncio" + (" (a página trazia outro número, de outro anúncio)"
                                                        if (da_extensao or do_texto) else "")
    if da_extensao and _igual(da_extensao, do_texto):
        return float(da_extensao), "a página e o texto do anúncio dizem o mesmo"
    if da_extensao or do_texto:
        lidos = " e ".join(f"{_fmt(v)} m²" for v in dict.fromkeys(x for x in (da_extensao, do_texto) if x))
        return None, f"não achei a área com certeza (a página mostra {lidos}, que podem ser de outro anúncio)"
    return None, "não achei a área na página"


def lote_plausivel(lote: float | None, area: float | None, tipo: str = "casa") -> float | None:
    """Lote de casa com menos de 60 m² (ou menor que metade da área construída térrea) é leitura errada."""
    if not lote:
        return None
    if "casa" in (tipo or "").lower() and (lote < 60 or (area and lote < float(area) / 2)):
        return None
    return float(lote)


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".").removesuffix(",00")


# ------------------------------------------------------------------ 091-4: rua e bairro pela página do anúncio
_SEP = r"\s*[›»>|/]\s*"
_RUA = r"(?:Rua|R\.|Avenida|Av\.?|Alameda|Al\.|Travessa|Tv\.|Rodovia|Estrada|Praça)"
_UFS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ",
        "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"}
_PORTAIS = re.compile(r"(?i)deztop|zap|viva ?real|olx|imovelweb|chaves ?na ?m[aã]o|mitula|62 ?im[oó]veis|quinto ?andar")


def bairro_ruim(b: str | None) -> bool:
    """Bairro que é lixo de leitura: vazio, sigla de estado, nome de portal ou rua/cidade grudadas."""
    t = (b or "").strip()
    return (not t or t.upper() in _UFS or bool(_PORTAIS.search(t)) or "," in t
            or bool(re.match(rf"(?i){_RUA}\s", t)) or len(t) > 60)


def _titulo(s: str) -> str:
    s = " ".join(s.split()).strip(" ,.-")
    return " ".join(w if w.isupper() and len(w) <= 4 and any(ch.isdigit() for ch in w) else w[:1].upper() + w[1:]
                    for w in s.split())


def local_da_pagina(texto: str, cidade: str = "Goiânia") -> tuple[str, str]:
    """(rua, bairro) pelo próprio anúncio. 1º o caminho de navegação ("Goiânia › Vila Finsocial › … › Avenida Anglo");
    senão o endereço escrito "Rua VF, Vila Finsocial, Goiânia". Vazio quando não acha (nunca chuta)."""
    t = texto or ""
    cid = re.escape(cidade.split("–")[0].split("-")[0].strip() or "Goiânia")
    for linha in t.splitlines():
        partes = [p.strip() for p in re.split(_SEP, linha) if p.strip()]
        if len(partes) < 3 or not any(re.fullmatch(rf"(?i){cid}(\s*-\s*\w\w)?", p) for p in partes):
            continue
        i = next(k for k, p in enumerate(partes) if re.fullmatch(rf"(?i){cid}(\s*-\s*\w\w)?", p))
        depois = [p for p in partes[i + 1:] if p not in ("…", "...")]
        rua = next((p for p in depois if re.match(rf"(?i){_RUA}\s", p)), "")
        bairro = next((p for p in depois if not re.match(rf"(?i){_RUA}\s", p) and not bairro_ruim(p)), "")
        if bairro or rua:
            return _titulo(rua), _titulo(bairro)
    m = re.search(rf"(?i)({_RUA}\s+[^,\n]{{1,40}}),\s*([^,\n]{{3,40}}),\s*{cid}", t)
    if m and not bairro_ruim(m.group(2)):
        return _titulo(m.group(1)), _titulo(m.group(2))
    return "", ""


_FIM_DO_ANUNCIO = re.compile(r"(?i)im[oó]veis semelhantes|an[uú]ncios? semelhantes|veja tamb[eé]m|voc[eê] tamb[eé]m pode|"
                             r"outros im[oó]veis|im[oó]veis similares|recomendados para voc[eê]|mais im[oó]veis|"
                             r"im[oó]veis pr[oó]ximos")      # 100-2: Deztop


def texto_do_anuncio(texto: str, titulo: str = "") -> str:
    """091-1: só o texto do PRÓPRIO anúncio — a página traz, depois, "imóveis semelhantes" e propaganda, de onde
    saíam "novo/em acabamento" e "várias unidades" que não eram deste anúncio. Corta no começo dessa parte."""
    t = texto or ""
    ini = t.find(titulo.strip()[:40]) if titulo.strip() else -1
    corpo = t[ini:] if ini > 0 else t
    m = _FIM_DO_ANUNCIO.search(corpo, 200)
    return corpo[: m.start()] if m else corpo


def separar_rua(rua: str, cidade: str = "Goiânia") -> tuple[str, str]:
    """091-4: "Rua Vf, Vila Finsocial, Goiânia - GO" (rua, bairro e cidade grudados) -> ("Rua Vf", "Vila Finsocial")."""
    partes = [p.strip() for p in (rua or "").split(",") if p.strip()]
    if len(partes) < 2:
        return (rua or "").strip(), ""
    cid = (cidade.split("–")[0].split("-")[0].strip() or "Goiânia").lower()
    bairro = next((p for p in partes[1:] if not p.lower().startswith(cid) and not bairro_ruim(p)
                   and not re.fullmatch(r"\d{5}-?\d{3}", p)), "")
    return partes[0], bairro


# ------------------------------------------------------------------ 092-1 e 092-3: descrição limpa e destaque
_LIXO_PORTAL = re.compile(
    r"(?i)pular para o conte[uú]do|criar conta|\bentrar\b|simul(?:ar|e)|favorit[ea]|anote aqui|alugar\s+comprar|lan[çc]amentos|"
    r"compartilh|denunciar|ver telefone|enviar mensagem|fale com|whats ?app|cookies?|pol[ií]tica de privacidade|"
    r"baixe o app|app store|google play|cons[oó]rcio|financiamento|anunciante|creci|c[oó]digo do an[uú]ncio|"
    r"publicado h[aá]|atualizado h[aá]|mais detalhes|ver mais|voltar|menu|buscar")


def _frases(t: str) -> list[str]:
    return [f.strip() for f in re.split(r"(?<=[.!?])\s+|\n+", t) if f.strip()]


def descricao_limpa(texto: str, titulo: str = "", limite: int = 300) -> str:
    """092-1: só o texto do próprio anúncio, sem o menu do portal, curto e terminando em frase inteira."""
    t = texto_do_anuncio(texto or "", titulo)
    if titulo.strip() and t.startswith(titulo.strip()[:40]):
        t = t[len(titulo.strip()):]
    bons = []
    for f in _frases(t):
        if _LIXO_PORTAL.search(f) or len(f) < 25 or sum(ch.isalpha() for ch in f) < len(f) * 0.6:
            continue                       # menu, botão, preço solto, número de telefone
        bons.append(f if f.endswith((".", "!", "?")) else f + ".")
    out = ""
    for f in bons:
        if len(out) + len(f) + 1 > limite:
            break
        out = (out + " " + f).strip()
    return out


def destaque(texto: str, titulo: str = "") -> str:
    """092-3: uma linha com o que distingue o imóvel ("3 quartos, espaço gourmet, 220 m²"), só do próprio anúncio."""
    t = f"{titulo}\n{texto_do_anuncio(texto or '', titulo)}"
    itens = []
    m = re.search(r"(?i)(\d+)\s*(?:quartos?|dormit[óo]rios?)", t)
    if m:
        itens.append(f"{m.group(1)} quartos")
    m = re.search(r"(?i)(\d+)\s*su[íi]tes?", t)
    if m and int(m.group(1)) > 0:               # 102-8: nunca "0 suítes"
        itens.append(f"{m.group(1)} suíte" + ("s" if m.group(1) != "1" else ""))
    for rx, nome in ((r"gourmet", "espaço gourmet"), (r"piscina", "piscina"), (r"churrasqueira", "churrasqueira"),
                     (r"porcelanato", "porcelanato"), (r"planejad", "armários planejados"), (r"sobrado", "sobrado")):
        if re.search(rf"(?i){rx}", t) and nome not in itens:
            itens.append(nome)
    a = areas_do_titulo(titulo) or [_num(m.group(1)) for m in re.finditer(_M2, t, flags=re.I)][:1]
    if a and a[0]:
        itens.append(f"{_fmt(a[0])} m²")
    return ", ".join(itens[:5])


# ------------------------------------------------------------------ 096-7: a mesma foto em vários tamanhos
def _identidade_foto(u: str) -> str:
    """O que identifica a FOTO, sem o tamanho: na Deztop o endereço da imagem original vem codificado no fim
    ("proxy.deztop.com/image/1200x630/<base64>.jpg"); no ZAP/Viva Real é o caminho sem os parâmetros de tamanho."""
    import base64
    from urllib.parse import urlsplit
    x = urlsplit(u or "")
    if "deztop" in x.netloc:
        s = re.sub(r"\.(jpe?g|webp|png)$", "", x.path.rstrip("/").split("/")[-1])
        try:
            orig = base64.b64decode(s.replace("-", "+").replace("_", "/") + "=" * (-len(s) % 4)).decode("utf-8", "ignore")
            if orig.startswith("http"):
                return orig
        except (ValueError, UnicodeError):
            pass
    caminho = re.sub(r"/(?:fit-in|crop)/\d+x\d+/", "/", x.path)
    caminho = re.sub(r"/\d{2,4}x\d{2,4}/", "/", caminho)
    return f"{x.netloc}{caminho}".lower()


def fotos_unicas(urls: list[str], maximo: int = 12) -> list[str]:
    """096-7: a galeria só com fotos diferentes (o portal repete a mesma foto em 3 tamanhos). Fica a 1ª de cada."""
    vistos, out = set(), []
    for u in urls or []:
        k = _identidade_foto(u)
        if k and k not in vistos:
            vistos.add(k)
            out.append(u)
    return out[:maximo]


# ------------------------------------------------------------------ 098-2 e 098-3: lote e grafia da rua
_TIPOS_RUA = {"r": "Rua", "rua": "Rua", "av": "Avenida", "avenida": "Avenida", "al": "Alameda", "alameda": "Alameda",
              "tv": "Travessa", "travessa": "Travessa"}


def logradouro(rua: str) -> str:
    """098-3: "Rua Jc18" -> "Rua JC-18"; "Rua VF 9" -> "Rua VF-9"; "Rua Vf" -> "Rua VF". Nome comum fica como está
    ("Avenida Anglo"). Só mexe na sigla de 1 a 3 letras logo depois do tipo do logradouro."""
    t = " ".join((rua or "").split())
    m = re.match(r"(?i)^(r|rua|av|avenida|al|alameda|tv|travessa)\.?\s+([a-z]{1,3})(?:[\s-]?(\d+[a-z]?))?(?=$|[\s,.;])(.*)$", t)
    if not m or (not m.group(3) and m.group(2).lower() in ("da", "de", "do", "das", "dos", "dom", "sao", "rei", "seu")):
        return t                          # "Rua das Flores", "Rua Dom Pedro": nome comum, não sigla
    tipo = _TIPOS_RUA[m.group(1).lower()]
    sigla = m.group(2).upper() + (f"-{m.group(3).upper()}" if m.group(3) else "")
    return f"{tipo} {sigla}{m.group(4)}"


_LOTE = re.compile(r"(?i)(?:terreno|lote|[áa]rea\s+total|[áa]rea\s+do\s+(?:terreno|lote))\s*(?:de|com|medindo|mede|:|–|-)?\s*"
                   r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d{2,5}(?:[.,]\d{1,2})?)\s*(?:m²|m2|metros)")
_LOTE_DEPOIS = re.compile(   # 100-3: ZAP/Viva Real escrevem o número antes ("300 m² de terreno", "300 m² área total")
    r"(?i)(?<![\d.,])(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d{2,5}(?:[.,]\d{1,2})?)\s*(?:m²|m2)\s*(?:de\s+)?"
    r"(?:terreno|lote|[áa]rea\s+total)")
_LOTE_XY = re.compile(r"(?i)(?:terreno|lote)\s*(?:de|com|medindo|mede|:)?\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:[xX×]|por)\s*(\d{1,3}(?:[.,]\d{1,2})?)")


def lote_confirmado(texto: str, titulo: str = "", lido: float | None = None) -> float | None:
    """098-2: a área do LOTE só do texto do próprio anúncio ("Terreno 300 m²", "lote de 10x30"). Número que não
    está no anúncio (de outro anúncio da página, de propaganda) não vale: None, e o laudo põe "n/i"."""
    t = texto_do_anuncio(texto or "", titulo) + "\n" + (titulo or "")
    achados = {_num(m.group(1)) for rx in (_LOTE, _LOTE_DEPOIS) for m in rx.finditer(t)}
    for m in _LOTE_XY.finditer(t):
        a, b = _num(m.group(1)), _num(m.group(2))
        if a and b:
            achados.add(round(a * b, 2))
    achados.discard(None)
    if lido and any(_igual(lido, x) for x in achados):
        return float(lido)
    return achados.pop() if len(achados) == 1 else None



# ------------------------------------------------------------------ L200: quartos/suítes escritos no anúncio
_EXTENSO = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "três": 3, "quatro": 4, "cinco": 5, "seis": 6}
_NUM_Q = r"(\d{1,2}|uma?|dois|duas|tr[êe]s|quatro|cinco|seis)"


def _n_ext(s: str) -> int:
    return int(s) if s.isdigit() else _EXTENSO[s.casefold()]


def quartos_suites(texto: str) -> tuple[int | None, int | None]:
    """Quartos e suítes que o texto do anúncio diz. Número que se contradiz no mesmo texto não vale."""
    t = texto or ""
    q = {_n_ext(m.group(1)) for m in re.finditer(rf"(?i)\b{_NUM_Q}\s*(?:quartos?|dormit[óo]rios?)\b", t)}
    s = {_n_ext(m.group(1)) for m in re.finditer(rf"(?i)\b{_NUM_Q}\s*su[íi]tes?\b", t)}
    q.discard(0)
    s.discard(0)
    return (q.pop() if len(q) == 1 else None), (s.pop() if len(s) == 1 else None)


def combinacao_impossivel(quartos: int | None, suites: int | None) -> bool:
    """Mais suítes que quartos: o número guardado foi mal lido (ex.: banheiros no lugar de suítes)."""
    return bool(quartos and suites and suites > quartos)
