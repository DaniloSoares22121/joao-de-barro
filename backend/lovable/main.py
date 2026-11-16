"""Servidor LOCAL do João de Barro (substitui o main.py do Brixly).

    cd backend
    python -m uvicorn lovable.main:app --port 8866

Na primeira subida cria a conta do avaliador (JDB_EMAIL / JDB_SENHA, padrão
avaliador@local / joaodebarro) e a define como dona do João de Barro.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import auth
from .avaliacao import coletor_routes, db, orquestrador, routes
from .avaliacao import mapa_digital, rotas_amostra, rotas_extensao  # noqa: F401  (ORDEM 076: rotas no routes.router antes do include)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("lovable")

EMAIL = os.environ.get("JDB_EMAIL", "avaliador@local")
SENHA = os.environ.get("JDB_SENHA", "joaodebarro")


def _preparar() -> None:
    auth.init()
    db.init()
    if auth.user_by_email(EMAIL) is None:
        auth.criar_usuario(EMAIL, SENHA)
        log.info("conta local criada: %s", EMAIL)
    if not db.setting("dono_email"):
        db.set_setting("dono_email", EMAIL.casefold())
    # P3 (decisões) e P4 (normas) -> banco, para a tela de Configurações; só insere códigos
    # ausentes (o que foi editado na tela prevalece)
    from .avaliacao import conhecimento
    log.info("base de conhecimento: %d decisões, %d normas lidas",
             conhecimento.importar_decisoes(), conhecimento.importar_normas())


@asynccontextmanager
async def _vida(app: FastAPI):
    _preparar()
    from .avaliacao import coletor_fonte, fonte_mercado
    if fonte_mercado._atual is None:
        fonte_mercado.registrar(coletor_fonte.ColetorFonte())
    orquestrador.iniciar_fila()
    try:                                     # 081-1: leitura da conversa que o reinício interrompeu continua sozinha
        from .avaliacao import rotas_whatsapp
        n = rotas_whatsapp.retomar_todas()
        orquestrador.retomar_remontagens()       # 086-1: pedido de remontagem que esperava continua
        if n:
            log.info("leituras de conversa retomadas: %d", n)
    except Exception:
        log.exception("retomar leituras")
    yield
    orquestrador.encerrar()


app = FastAPI(title="João de Barro (local)", lifespan=_vida)


class Login(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
async def login(body: Login):
    if not auth.rate_limit(f"login:{body.email.casefold()}", 10, 300):
        raise HTTPException(status_code=429, detail="Muitas tentativas")
    tk = auth.login(body.email, body.password)
    if not tk:
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos")
    return {"token": tk}


async def _admin(x_admin_token: str = Header(default="")) -> None:
    if not auth.admin_ok(x_admin_token):
        raise HTTPException(status_code=401, detail="Admin não autenticado")


app.include_router(routes.router, prefix="/api/avaliacao")
app.include_router(coletor_routes.router, prefix="/api/avaliacao")
app.include_router(routes.admin_router, prefix="/api/admin", dependencies=[Depends(_admin)])
app.include_router(coletor_routes.ws_router)
app.include_router(routes.ws_router)
app.add_middleware(routes.LimiteCorpoAvaliacao)


@app.get("/api/saude")
async def saude():
    return {"ok": True}
