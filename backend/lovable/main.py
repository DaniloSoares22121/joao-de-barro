"""Servidor do João de Barro: API do avaliador, WebSockets e a tela (frontend/dist-joaodebarro)."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import auth, config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("lovable")

app = FastAPI(title="João de Barro", docs_url=None, redoc_url=None)
auth.init()


# ------------------------------------------------------------------ login
class Login(BaseModel):
    email: str
    password: str


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@app.post("/api/auth/login")
async def login(body: Login, request: Request):
    if not auth.rate_limit(f"login:{_ip(request)}", 20, 300):
        raise HTTPException(status_code=429, detail="Muitas tentativas")
    token = auth.entrar(body.email, body.password)
    if not token:
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos")
    return {"token": token}


@app.get("/api/health")
async def health():
    return {"ok": True}


# ------------------------------------------------------------------ João de Barro
from .avaliacao import coletor_routes as _coletor_routes  # noqa: E402
from .avaliacao import routes as _avaliacao_routes  # noqa: E402

app.include_router(_avaliacao_routes.router, prefix="/api/avaliacao")
app.include_router(_coletor_routes.router, prefix="/api/avaliacao")
# coletor antes do ws do trabalho: /ws/avaliacao/{jid} engoliria /ws/avaliacao/coletor
app.include_router(_coletor_routes.ws_router)
app.include_router(_avaliacao_routes.ws_router)
app.add_middleware(_avaliacao_routes.LimiteCorpoAvaliacao)  # corta upload > 1 GB antes do parse
# O dono (única conta que entra) é definido pelo `criar_usuario.py`, não por rota.


@app.on_event("startup")
async def _avaliacao_init():
    from .avaliacao import conhecimento, db, orquestrador
    db.init()
    conhecimento.importar_decisoes()
    conhecimento.importar_normas()
    orquestrador.iniciar_fila()
    if not db.setting("dono_email"):
        log.warning("nenhum avaliador cadastrado: rode `python criar_usuario.py email senha`")


# ------------------------------------------------------------------ tela
_joaodebarro_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist-joaodebarro"
_JOAODEBARRO_HOST = ""   # qualquer host: este servidor só serve o João de Barro
_SEGURANCA = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
}


@app.middleware("http")
async def _tela(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") or path.startswith("/ws/"):
        return await call_next(request)
    if path.startswith("/assets-jdb/"):
        base = _joaodebarro_dist.resolve()
        alvo = (base / path[len("/assets-jdb/"):]).resolve()
        if base in alvo.parents and alvo.is_file():
            return FileResponse(str(alvo), headers={
                "Cache-Control": "public, max-age=31536000, immutable", **_SEGURANCA})
        return JSONResponse({"error": "not found"}, status_code=404, headers=_SEGURANCA)
    idx = _joaodebarro_dist / "index.html"
    if not idx.exists():
        return JSONResponse({"error": "A tela ainda não foi gerada: rode `npm run build` em frontend/"},
                            status_code=404, headers=_SEGURANCA)
    return FileResponse(str(idx), headers={"Cache-Control": "no-store, must-revalidate", **_SEGURANCA})
