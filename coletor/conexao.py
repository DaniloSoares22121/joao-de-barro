"""Canal WebSocket com o servidor: uma tarefa por vez, reconexão 1→5→15→60 s, ping 30 s."""
from __future__ import annotations

import asyncio
import json
import logging

import websockets

from config import cabecalhos, url_ws
from navegador import url_permitida

log = logging.getLogger("coletor")
VERSAO = "1.0.0"
ESPERAS = (1, 5, 15, 60)
ACOES = ("busca", "anuncio", "maps")
PAREAR = "pareie novamente"   # status para a bandeja quando o token foi recusado


def _token_recusado(e: Exception) -> bool:
    """Handshake 401/403 (servidor fecha 4403 antes do accept) ou close 4401/4403 depois."""
    if isinstance(e, websockets.InvalidStatus):
        return e.response.status_code in (401, 403)
    if isinstance(e, websockets.ConnectionClosed):
        return bool(e.rcvd and e.rcvd.code in (4401, 4403))
    return False


async def _atender(ws, navegador) -> None:
    await ws.send(json.dumps({"tipo": "ola", "versao": VERSAO}))
    async for bruto in ws:
        try:
            msg = json.loads(bruto)
        except ValueError:
            continue
        if not isinstance(msg, dict) or msg.get("tipo") != "tarefa":
            continue
        tid, url, acao = msg.get("id"), str(msg.get("url") or ""), msg.get("acao")
        if acao not in ACOES or not url_permitida(url):
            log.warning("tarefa recusada: %s %s", acao, url[:200])
            res = {"ok": False, "bloqueado": False, "erro": "url não permitida"}
        else:
            log.info("tarefa %s: %s", acao, url[:200])
            res = await navegador.capturar(url, acao)
        await ws.send(json.dumps({"tipo": "resultado", "id": tid, **res}))


async def loop(cfg: dict, navegador, *, esperas=ESPERAS, ao_status=None,
               parar: asyncio.Event | None = None) -> None:
    """Conecta e atende até `parar` ser setado; se cair, espera e reconecta.
    Token recusado → avisa "pareie novamente" e para de tentar até reiniciar o app."""
    parar = parar or asyncio.Event()
    avisar = ao_status or (lambda _on: None)
    tentativa = 0
    while not parar.is_set():
        try:
            async with websockets.connect(url_ws(cfg), additional_headers=cabecalhos(cfg),
                                          ping_interval=30, ping_timeout=30,
                                          max_size=2 ** 20, open_timeout=20) as ws:
                tentativa = 0
                avisar(True)
                log.info("conectado a %s", cfg["servidor"])
                atend = asyncio.ensure_future(_atender(ws, navegador))
                fim = asyncio.ensure_future(parar.wait())
                await asyncio.wait({atend, fim}, return_when=asyncio.FIRST_COMPLETED)
                fim.cancel()
                if not atend.done():
                    atend.cancel()
                    try:
                        await atend
                    except (asyncio.CancelledError, Exception):
                        pass
                else:
                    atend.result()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if _token_recusado(e):
                log.error("token recusado pelo servidor: pareie novamente (%s)", e)
                avisar(PAREAR)
                return
            log.warning("conexão caiu: %s", e)
        avisar(False)
        if parar.is_set():
            break
        espera = esperas[min(tentativa, len(esperas) - 1)]
        tentativa += 1
        try:
            await asyncio.wait_for(parar.wait(), espera)
        except asyncio.TimeoutError:
            pass
