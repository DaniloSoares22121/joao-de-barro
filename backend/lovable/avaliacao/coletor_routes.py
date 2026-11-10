"""Rotas do Coletor: /api/avaliacao/coletor/* e /ws/avaliacao/coletor."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from lovable import auth, config

from . import coletor_hub
from .coletor_hub import hub
from .routes import _dono

router = APIRouter()
ws_router = APIRouter()


def _ip(request: Request) -> str:
    cf = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf:
        return cf
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return xff or (request.client.host if request.client else "?")


@router.post("/coletor/codigo")
async def codigo(_u: dict = Depends(_dono)):
    cod, exp = hub.novo_codigo()
    return {"codigo": cod, "expira_em": exp}


class Pareamento(BaseModel):
    codigo: str


@router.post("/coletor/parear")
async def parear(body: Pareamento, request: Request):
    # O IP vem de cabeçalho (forjável por quem chega direto na origem): o teto global segura
    # a força bruta mesmo com um "IP" novo a cada tentativa.
    if (not auth.rate_limit("coletor_parear:global", 60, 300)
            or not auth.rate_limit(f"coletor_parear:{_ip(request)[:64]}", 10, 300)):
        raise HTTPException(status_code=429, detail="Muitas tentativas")
    token = hub.parear(body.codigo)
    if not token:
        raise HTTPException(status_code=401, detail="Código inválido ou expirado")
    return {"token": token}


@router.get("/coletor/status")
async def status(_u: dict = Depends(_dono)):
    return hub.status()


@router.get("/coletor/download")
async def download(_u: dict = Depends(_dono)):
    exe = config.DATA_DIR / "avaliacao" / "coletor" / "joaodebarro-coletor.exe"
    if not exe.is_file():
        raise HTTPException(status_code=404, detail="Instalador indisponível")
    return FileResponse(exe, filename=exe.name, media_type="application/octet-stream")


@ws_router.websocket("/ws/avaliacao/coletor")
async def ws_coletor(ws: WebSocket):
    # Token só no cabeçalho Authorization (nunca na URL, que vai para logs de proxy).
    tipo, _, token = (ws.headers.get("authorization") or "").partition(" ")
    if tipo.lower() != "bearer" or not coletor_hub.validar_token(token.strip()):
        await ws.close(code=4403)
        return
    try:
        # dentro do try: se o accept falhar (cliente desistiu no handshake), o desconectar
        # roda e o status não fica "online" com um socket morto
        await hub.conectar(ws)
        await ws.accept()
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except (ValueError, TypeError):
                continue
            if isinstance(msg, dict):
                hub.receber(ws, msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.desconectar(ws)
