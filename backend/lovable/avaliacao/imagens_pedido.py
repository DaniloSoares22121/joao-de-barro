"""ORDEM 117-4 (imagem): os pedidos de ajuste que mexem em IMAGEM, chamados pela correção do outro executor.

- trocar_foto(jid, n, descricao): "imóvel 2 com a foto da piscina" — olha as fotos guardadas do anúncio n (a galeria que
  a extensão trouxe) e escolhe a que mostra o que o avaliador descreveu (IA leve, uma chamada). Não acha: diz por quê.
- refazer_demarcacao(jid, pedido): "quadro exatamente em cima do lote, contorno mais fino" — nova captura do Google
  Maps no zoom 19 e o desenho do lote da Prefeitura sobre o lote (D-130); precisa do programa do mapa ligado.
"""
from __future__ import annotations

import io
import logging

from pydantic import BaseModel, Field

from . import coletor_hub, db, ia

log = logging.getLogger("lovable")
MAX_FOTOS = 12


class _Escolha(BaseModel):
    numero: int = Field(description="o número da foto (1, 2, 3…) que mostra o pedido; 0 se nenhuma mostra")
    motivo: str = Field(default="", description="uma frase: o que a foto escolhida mostra")


SISTEMA = """Você escolhe UMA foto de um anúncio de imóvel. As fotos estão numeradas na ordem em que foram
enviadas (foto 1, foto 2…). Devolva o número da foto que MOSTRA o que o avaliador pediu (ex.: "a da piscina", "a
fachada de blindex com pé-direito duplo"). Se nenhuma mostra, numero=0. Não invente."""


def _baixar(urls: list[str], pasta) -> list:
    import httpx
    from PIL import Image
    out = []
    pasta.mkdir(parents=True, exist_ok=True)
    for k, u in enumerate(urls[:MAX_FOTOS], 1):
        arq = pasta / f"{k:02d}.jpg"
        if not arq.is_file():
            try:
                r = httpx.get(u, timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                with Image.open(io.BytesIO(r.content)) as im:
                    im.convert("RGB").save(arq, "JPEG", quality=85)
            except Exception as e:           # noqa: BLE001 — foto que o portal não entrega fica de fora
                log.info("foto %s do anúncio não baixada: %s", k, e)
                continue
        out.append((k, arq))
    return out


async def trocar_foto(jid: str, n: int, descricao: str) -> dict:
    import asyncio
    import shutil

    from .leitura_pagina import fotos_unicas
    ref = next((r for r in db.candidatos(jid) if r.n == n), None)
    if ref is None:
        return {"ok": False, "motivo": f"o anúncio {n} não está neste trabalho", "foto": ""}
    urls = fotos_unicas(list(getattr(ref, "fotos_url", None) or []), maximo=MAX_FOTOS)
    if not urls:
        return {"ok": False, "motivo": f"o anúncio {n} não tem outras fotos guardadas (reenvie pela extensão)", "foto": ""}
    pasta = db.pasta(jid) / "mercado" / f"galeria-{n:02d}"
    fotos = await asyncio.to_thread(_baixar, urls, pasta)
    if not fotos:
        return {"ok": False, "motivo": "o portal não entregou as fotos do anúncio agora", "foto": ""}
    from .agentes.leitor_anuncio import modelo_leve
    try:
        ia.definir_contexto(jid, "revisao")
        r: _Escolha = await ia.perguntar(SISTEMA, f"Pedido do avaliador: {descricao!r}. Fotos: "
                                         + ", ".join(f"foto {k} = {a.name}" for k, a in fotos), _Escolha,
                                         arquivos=[a for _, a in fotos], cwd=pasta, modelo=modelo_leve())
    except Exception as e:                   # noqa: BLE001
        return {"ok": False, "motivo": f"não consegui olhar as fotos agora ({type(e).__name__})", "foto": ""}
    escolhida = next((a for k, a in fotos if k == r.numero), None)
    if escolhida is None:
        return {"ok": False, "motivo": f"nenhuma das {len(fotos)} fotos do anúncio mostra {descricao}", "foto": ""}
    rel = f"mercado/enviado-{n}-foto-escolhida.jpg"
    shutil.copyfile(escolhida, db.pasta(jid) / rel)
    agora = next((x for x in db.candidatos(jid) if x.n == n), ref)
    db.salvar_candidatos(jid, [agora.model_copy(update={"foto": rel})])
    db.evento(jid, "revisao", "info", f"anúncio {n:02d}: foto trocada a pedido do avaliador ({descricao}): "
              f"foto {r.numero} do anúncio — {r.motivo}"[:400])
    return {"ok": True, "motivo": r.motivo or f"foto {r.numero} do anúncio", "foto": rel}


def n_do_alvo(jid: str, alvo: str) -> int | None:
    """126-3c: "imóvel 2 do item 9.3" é o 2º item da COMPARAÇÃO (no nº 1, o anúncio nº 7), não o anúncio nº 2;
    "referencial 3"/"amostra 3"/"9.1" é o 3º da amostra; um número solto é o nº do anúncio na lista."""
    import re as _re
    t = " ".join(str(alvo or "").lower().split())
    t_sem = _re.sub(r"\b9\.[13]\b|\bitem\s+9\b", " ", t)
    nums = [int(x) for x in _re.findall(r"\b(\d{1,3})\b", t_sem)]
    if not nums:
        return None
    k = nums[0]
    cands = sorted(db.candidatos(jid), key=lambda r: r.n)
    if _re.search(r"9\.3|compara|padr[ãa]o superior", t):
        lista = [r for r in cands if r.decisao == "comparacao"]
    elif _re.search(r"9\.1|referencia|amostra", t):
        lista = [r for r in cands if r.escolhido or r.decisao == "entra"]
    else:
        return k if any(r.n == k for r in cands) else None
    return lista[k - 1].n if 1 <= k <= len(lista) else None


async def trocar_foto_alvo(jid: str, alvo: str, descricao: str) -> dict:
    """trocar_foto com o alvo como o avaliador falou ("imóvel 2 do 9.3")."""
    n = n_do_alvo(jid, alvo)
    if n is None:
        return {"ok": False, "motivo": f"não entendi qual anúncio é \"{alvo}\"", "foto": ""}
    return await trocar_foto(jid, n, descricao)


async def refazer_demarcacao(jid: str, pedido: str = "") -> dict:
    from . import coletor_fonte
    from .agentes import _comum
    t = _comum.trabalho(jid)
    if not t.pin_maps:
        return {"ok": False, "motivo": "o trabalho não tem o link do Google Maps (pino)"}
    if not coletor_hub.online():
        return {"ok": False, "motivo": "programa do mapa desligado"}
    def _ultimo() -> int:
        with db._conn() as c:
            return c.execute("SELECT COALESCE(MAX(id), 0) FROM av_events WHERE job=? AND etapa='localizacao' "
                             "AND nivel='resultado'", (jid,)).fetchone()[0]
    antes = _ultimo()
    await coletor_fonte.capturar_maps(jid, t, refazer=True)
    if _ultimo() == antes:                    # 121: captura em branco ou falha: o mapa de antes ficou
        return {"ok": False, "motivo": "o Google Maps não desenhou o mapa agora (ficou o mapa de antes); tente de novo"}
    with db._conn() as c:
        r = c.execute("SELECT msg, dados_json FROM av_events WHERE job=? AND etapa='localizacao' AND nivel='resultado' "
                      "ORDER BY id DESC LIMIT 1", (jid,)).fetchone()
    import json
    d = json.loads(r["dados_json"] or "{}") if r else {}
    if d.get("fonte_poligono") == "mapa_digital":
        return {"ok": True, "motivo": "mapa refeito no zoom do lote, com o desenho do lote da Prefeitura e contorno fino"}
    if d.get("poligono"):
        return {"ok": True, "motivo": "mapa refeito mais perto do lote, contorno fino (sem o desenho da Prefeitura: "
                                      "fora de Goiânia ou sem inscrição)"}
    return {"ok": False, "motivo": "a captura do mapa não deu certo (veja os avisos do trabalho)"}
