"""ORDEM 076-3: a tela diz se a extensão "Enviar ao JdB" está no Chrome do avaliador e se está fixada.

A extensão (1.1.0+) manda o próprio estado a cada uso: versão, se está fixada na barra e se o avaliador já
permitiu o JdB nos portais de imóveis (o botão flutuante na página do anúncio). Versões antigas só mandam o
cabeçalho X-JdB-Extensao (gravado pelo middleware de routes.py em "extensao_versao").
"""
from __future__ import annotations

import json
import re

from fastapi import Depends, Query
from pydantic import BaseModel, Field

from . import db
from .routes import _dono, _job, router

CHAVE = "extensao_estado"


def versao_atual() -> str:
    """A versão da extensão que está na pasta extensao-chrome (a que o avaliador deve ter)."""
    from pathlib import Path
    try:
        m = Path(__file__).resolve().parents[3] / "extensao-chrome" / "manifest.json"
        return str(json.loads(m.read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return ""


def estado() -> dict:
    try:
        e = json.loads(db.setting(CHAVE) or "{}")
    except ValueError:
        e = {}
    vista = e.get("versao") or db.setting("extensao_versao") or ""
    atual = versao_atual()
    return {"instalada": bool(vista), "vista": vista, "atual": atual,
            "atualizar": bool(vista) and bool(atual) and vista != atual,
            # None = versão antiga, que não informa (a tela não afirma nada)
            "fixada": e.get("fixada") if e.get("versao") else None,
            "portais": e.get("portais") if e.get("versao") else None,
            # 081-6: permissão de captura da página (a prova do acesso com data, hora e link); None = versão que não informa
            "captura": e.get("captura") if e.get("versao") else None,
            "visto_em": e.get("visto_em") or ""}


class Estado(BaseModel):
    versao: str = Field(max_length=20)
    fixada: bool | None = None
    portais: bool | None = None
    captura: bool | None = None


@router.get("/extensao/estado")
async def ver_estado(_u: dict = Depends(_dono)):
    return estado()


@router.post("/extensao/estado")
async def gravar_estado(body: Estado, _u: dict = Depends(_dono)):
    from datetime import datetime, timezone
    db.set_setting(CHAVE, json.dumps({**body.model_dump(), "visto_em": datetime.now(timezone.utc).isoformat()}))
    db.set_setting("extensao_versao", body.versao)
    return estado()


# ------------------------------------------------------------ 079-1: "Abrir os anúncios" pela extensão
def anuncios(jid: str) -> dict:
    """Os anúncios do laudo e quais já chegaram com foto e data de acesso (o "3 de 6 recebidos" da tela).
    `faltam` é a lista que a extensão abre, um a um."""
    entra = [c for c in db.candidatos(jid) if c.escolhido or c.decisao == "entra"]
    ok = [c for c in entra if c.foto and (c.acessado_em or "")]
    faltam = [{"n": c.n, "link": c.link, "portal": c.portal} for c in entra
              if not (c.foto and (c.acessado_em or "")) and (c.link or "").startswith(("http://", "https://"))]
    # 095-8: "Só comparação" sem foto/data também é aberto (não conta no "N de 6" da amostra)
    faltam += [{"n": c.n, "link": c.link, "portal": c.portal} for c in db.candidatos(jid)
               if c.decisao == "comparacao" and not c.escolhido and not (c.foto and (c.acessado_em or ""))
               and (c.link or "").startswith(("http://", "https://"))]
    # 091-5: os links colados no "Adicionar anúncio" que ainda não chegaram também entram (a extensão abre e envia)
    colados = colados_pendentes(jid)
    faltam += [{"n": None, "link": lk, "portal": ""} for lk in colados]
    # 110-1: o contador conta TODOS os que o avaliador mandou abrir (amostra + "só comparação"): 8 colados = "N de 8"
    comp = [c for c in db.candidatos(jid) if c.decisao == "comparacao" and not c.escolhido
            and (c.link or "").startswith(("http://", "https://"))]
    comp_ok = [c for c in comp if c.foto and (c.acessado_em or "")]
    return {"total": len(entra) + len(comp) + len(colados), "recebidos": len(ok) + len(comp_ok),
            "amostra": {"total": len(entra), "recebidos": len(ok)}, "faltam": faltam, "colados": len(colados),
            "sem_link": [c.n for c in entra if not (c.foto and (c.acessado_em or ""))
                         and not (c.link or "").startswith(("http://", "https://"))]}


@router.get("/jobs/{jid}/extensao/anuncios")
async def ver_anuncios(jid: str, _u: dict = Depends(_dono)):
    _job(jid)
    return anuncios(jid)


# ------------------------------------------------------------ 079-A: quais trabalhos recebem anúncio e de quem é o link
CANCELADOS = ("CANCELADO", "CANCELANDO")


def _host(u: str) -> str:
    from urllib.parse import urlsplit
    h = re.sub(r"^(?:www\.|m\.|mobile\.)", "", urlsplit(u.strip()).netloc.lower())
    return re.sub(r"\.br$", "", h)                       # deztop.com e deztop.com.br são o mesmo portal


def _chave(u: str) -> tuple[str, str]:
    from urllib.parse import urlsplit
    from .agentes.pesquisa import link_limpo
    x = urlsplit(link_limpo(u.strip()))
    return _host(u), (x.path.rstrip("/") + ("?" + x.query if x.query else "")).lower()


def _id_anuncio(u: str) -> str:
    m = re.search(r"-id-(\d{6,})|/imovel/(\d{6,})(?:/|$)|/(\d{8,})(?:[/-]|$)", u or "")
    return next((g for g in (m.groups() if m else ()) if g), "")


def mesmo_anuncio(a: str, b: str) -> bool:
    """Mesmo anúncio com outro jeito de escrever o link (http/https, www, m., barra, .com/.com.br) ou pelo nº dele."""
    if not a or not b:
        return False
    if _chave(a) == _chave(b):
        return True
    i = _id_anuncio(a)
    return bool(i) and i == _id_anuncio(b) and _host(a) == _host(b)


async def recebem(_u: dict) -> list[dict]:
    """Trabalhos que recebem anúncio: todos, menos aprovado, assinado, cancelado (e os da Lixeira, que a lista já tira).
    'PARCIAL — PENDÊNCIAS', 'PRONTO PARA REVISÃO' e 'BLOQUEADO' recebem: é quando faltam as fotos."""
    from . import routes, tela_trabalho
    out = []
    for j in await routes.listar(_u=_u):
        if (j.get("status") or "").upper() in CANCELADOS:
            continue
        try:
            t = tela_trabalho.resumo(db.job(j["id"]))
            if t.get("aprovado") or t.get("assinado"):
                continue
        except Exception:
            pass
        out.append({k: j.get(k) for k in ("id", "numero", "cliente", "bairro", "status")})
    # 086-3: ordem FIXA (por número) e o último trabalho que recebeu anúncio em cima. A extensão ordena pelo campo
    # "atualizado" (do maior para o menor): ele vira essa chave de ordem, que não muda a cada envio.
    ultimo = _ultimo_envio()
    for j in out:             # 091-5: quem espera anúncios colados vem primeiro; depois o último que recebeu
        espera = bool(colados_pendentes(j["id"]))
        j["atualizado"] = ("3" if espera else "2" if j["id"] == ultimo else "1") + f"{int(j.get('numero') or 0) + 10**9:012d}"
        j["espera_anuncios"] = espera
        j["ultimo"] = j["id"] == ultimo
    out.sort(key=lambda j: j["atualizado"], reverse=True)
    return out


def _ultimo_envio() -> str:
    """O trabalho que recebeu o último anúncio enviado pela extensão (Chrome)."""
    with db._conn() as c:
        r = c.execute("SELECT job FROM av_events WHERE etapa='pesquisa' AND msg LIKE '%(Chrome)%' "
                      "ORDER BY id DESC LIMIT 1").fetchone()
    return r[0] if r else ""


@router.get("/extensao/trabalhos")
async def trabalhos(_u: dict = Depends(_dono)):
    return await recebem(_u)


@router.get("/extensao/de-quem")
async def de_quem(link: str = Query(..., max_length=2000), _u: dict = Depends(_dono)):
    """O link aberto já é referencial de UM trabalho? Então a extensão envia direto para ele (sem perguntar).
    084-2: se é referencial de MAIS DE UM trabalho aberto, não escolhe: a extensão pergunta "Para qual trabalho?"
    (quem veio do "Abrir os anúncios" de um trabalho já vai para esse, sem passar por aqui)."""
    # 093-A-15: envio DIRETO só quando o link ESPERA num trabalho só — colado e ainda não recebido, ou referencial
    # ainda sem foto/data de acesso. Link já recebido (foto e data) não prende o anúncio: volta a perguntar.
    espera = []
    for j in await recebem(_u):
        c = next((c for c in db.candidatos(j["id"]) if mesmo_anuncio(link, c.link)), None)
        if c is not None and not (c.foto and (c.acessado_em or "")):
            espera.append((j, c.n))
        elif c is None and any(mesmo_anuncio(link, lk) for lk in colados_pendentes(j["id"])):
            espera.append((j, None))
    if len(espera) == 1:
        j, n = espera[0]
        a = anuncios(j["id"])
        return {"trabalho": j["id"], "numero": j["numero"], "n": n, "recebidos": a["recebidos"], "total": a["total"]}
    if len(espera) > 1:
        return {"varios": [{"trabalho": j["id"], "numero": j["numero"], "n": n} for j, n in espera]}
    return {}



# ------------------------------------------------------------ 091-5: links colados no "Adicionar anúncio"
def _chave_colados(jid: str) -> str:
    return f"extensao_colados:{jid}"


def colados_pendentes(jid: str) -> list[str]:
    """Links colados neste trabalho que ainda não viraram anúncio (o que chega pela extensão sai da fila)."""
    try:
        links = json.loads(db.setting(_chave_colados(jid)) or "[]")
    except ValueError:
        links = []
    cands = db.candidatos(jid)
    return [lk for lk in links if not any(mesmo_anuncio(lk, c.link) for c in cands)]


class Colados(BaseModel):
    links: list[str] = Field(max_length=30)
    decisao: str = "entra"            # 097-1: "comparacao" quando colados pelo passo/botão de comparação (D-069)


def _chave_destino(jid: str) -> str:
    return f"extensao_colados_destino:{jid}"


def destino_colado(jid: str, link: str) -> str | None:
    """097-1: com que destino o link foi colado neste trabalho: "comparacao", "entra" ou None (não foi colado).
    O envio do anúncio novo usa isto: colado como comparação nasce "comparacao" (fora da amostra)."""
    try:
        d = json.loads(db.setting(_chave_destino(jid)) or "{}")
    except ValueError:
        d = {}
    return next((v for lk, v in d.items() if mesmo_anuncio(link, lk)), None)


@router.post("/jobs/{jid}/extensao/colados")
async def gravar_colados(jid: str, body: Colados, _u: dict = Depends(_dono)):
    """"Abrir no meu Chrome": o JdB guarda os links colados. Ao abrir cada um, a extensão já sabe o trabalho
    (envia sem perguntar) e o "Abrir os N" da tela abre todos, um a um."""
    _job(jid)
    novos = [lk.strip() for lk in body.links if re.match(r"^https?://\S+$", lk.strip())]
    try:
        antes = json.loads(db.setting(_chave_colados(jid)) or "[]")
    except ValueError:
        antes = []
    junto = list(dict.fromkeys(antes + novos))[-30:]
    db.set_setting(_chave_colados(jid), json.dumps(junto))
    try:
        destinos = json.loads(db.setting(_chave_destino(jid)) or "{}")
    except ValueError:
        destinos = {}
    destinos.update({lk: ("comparacao" if body.decisao == "comparacao" else "entra") for lk in novos})
    db.set_setting(_chave_destino(jid), json.dumps({k: v for k, v in destinos.items() if k in junto}))
    return {"pendentes": colados_pendentes(jid)}
