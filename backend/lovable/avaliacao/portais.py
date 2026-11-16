"""Portais de anúncios (V1): modelos de URL de busca e padrão de URL de anúncio.

Os modelos ficam aqui no servidor (nunca no .exe do Coletor). Busca e padrão de anúncio dos
4 portais verificados ao vivo em 2026-10-20 (Chrome real, Jardim Vila Boa/Goiânia) — revisar se
um portal mudar o formato.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from .fonte_mercado import Consulta


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


UF_PADRAO = "go"

# tipologia (slug) -> termo de cada portal
_TIPOS = {
    "zap": {"casa": "casas", "apartamento": "apartamentos", "terreno": "terrenos-lotes-condominios",
            "sobrado": "sobrados", "galpao": "galpao-deposito-armazem", "_": "imoveis"},
    "vivareal": {"casa": "casa_residencial", "apartamento": "apartamento_residencial",
                 "terreno": "lote-terreno_residencial", "sobrado": "sobrado_residencial",
                 "galpao": "galpao_comercial", "_": ""},
    # OLX: galpão não tem categoria própria na URL; vai como texto na busca (ver _olx)
    "olx": {"casa": "casas", "apartamento": "apartamentos", "terreno": "terrenos",
            "sobrado": "casas", "galpao": "", "_": ""},
    "imovelweb": {"casa": "casas", "apartamento": "apartamentos", "terreno": "terrenos",
                  "sobrado": "casas", "galpao": "comerciais-galpao-deposito-barracao", "_": "imoveis"},
}

# Galpão: URLs conferidas ao vivo no Chrome do Alan em 2026-11-12 (Polo Empresarial Goiás,
# Aparecida de Goiânia): ZAP /venda/galpao-deposito-armazem/, Viva Real .../galpao_comercial/,
# Imovelweb comerciais-galpao-deposito-barracao-venda-..., OLX só por texto ("galpao ...").


def _tipo(portal: str, tipologia: str) -> str:
    t = slug(tipologia).split("-")[0] if tipologia else ""
    if t == "barracao":
        t = "galpao"
    m = _TIPOS[portal]
    return m.get(t, m["_"])


def _eh_galpao(tipologia: str) -> bool:
    return (slug(tipologia).split("-")[0] if tipologia else "") in ("galpao", "barracao")


@dataclass(frozen=True)
class Portal:
    nome: str
    dominio: str
    modelo: Callable[[Consulta], str]
    padrao_anuncio: re.Pattern

    def url_busca(self, c: Consulta) -> str:
        return self.modelo(c)

    def eh_anuncio(self, url: str) -> bool:
        try:
            p = urlsplit(url or "")
        except ValueError:
            return False
        host = (p.hostname or "").lower()
        if p.scheme not in ("http", "https") or not (host == self.dominio or host.endswith("." + self.dominio)):
            return False
        return bool(self.padrao_anuncio.search(p.path))


# O ZAP abrevia termos do bairro na URL (verificado ao vivo em 2026-10-20: "Jardim Vila Boa"
# -> "jd-vl-boa"; vistos também "jd-america", "jds-madri", "resid-granville"; "setor-jao" igual).
_ZAP_ABREV = {"jardim": "jd", "jardins": "jds", "residencial": "resid", "vila": "vl"}


def _zap_bairro(bairro: str) -> str:
    return "-".join(_ZAP_ABREV.get(t, t) for t in slug(bairro).split("-"))


def _zap(c: Consulta) -> str:
    # sem bairro = a cidade inteira ("go+aparecida-de-goiania/", conferido em 2026-11-12)
    local = f"{UF_PADRAO}+{slug(c.cidade)}" + (f"++{_zap_bairro(c.bairro)}" if slug(c.bairro) else "")
    return f"https://www.zapimoveis.com.br/venda/{_tipo('zap', c.tipologia)}/{local}/"


def _vivareal(c: Consulta) -> str:
    tipo = _tipo("vivareal", c.tipologia)
    u = f"https://www.vivareal.com.br/venda/{slug('goias')}/{slug(c.cidade)}/"
    if slug(c.bairro):
        u += f"bairros/{slug(c.bairro)}/"
    return u + (f"{tipo}/" if tipo else "")


def _olx(c: Consulta) -> str:
    tipo = _tipo("olx", c.tipologia)
    u = f"https://www.olx.com.br/imoveis/venda/{tipo + '/' if tipo else ''}estado-{UF_PADRAO}"
    termos = (["galpao"] if _eh_galpao(c.tipologia) else []) + [slug(c.bairro), slug(c.cidade)]
    return u + "?q=" + "+".join(t.replace("-", "+") for t in termos if t)


# Imovelweb: cidade que não é capital precisa da UF no caminho (sem ela o portal devolve a busca
# nacional — visto em "aparecida-de-goiania", ORDEM 010)
_IMOVELWEB_CIDADE = {"aparecida-de-goiania": "aparecida-de-goiania-go",
                     "senador-canedo": "senador-canedo-go", "trindade": "trindade-go"}


def _imovelweb(c: Consulta) -> str:
    # ORDEM 010: sem bairro (busca pela cidade inteira) o caminho é "<tipo>-venda-<cidade>"
    cid = _IMOVELWEB_CIDADE.get(slug(c.cidade), slug(c.cidade))
    local = "-".join(x for x in (slug(c.bairro), cid) if x)
    return f"https://www.imovelweb.com.br/{_tipo('imovelweb', c.tipologia)}-venda-{local}.html"


PORTAIS: dict[str, Portal] = {
    "zap": Portal("ZAP Imóveis", "zapimoveis.com.br", _zap, re.compile(r"^/imovel/[^/]+")),
    "vivareal": Portal("Viva Real", "vivareal.com.br", _vivareal, re.compile(r"^/imovel/[^/]+")),
    "olx": Portal("OLX", "olx.com.br", _olx,
                  re.compile(r"(^/d/.+|^/imoveis/.*-\d{6,}/?$|/imoveis/.*-\d{6,}$)")),
    "imovelweb": Portal("Imovelweb", "imovelweb.com.br", _imovelweb,
                        re.compile(r"^/propriedades/.+-\d+\.html$")),
}
