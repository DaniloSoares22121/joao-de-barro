"""ORDEM 169: rotas da ligação com o Google do avaliador (Drive, permissão drive.file).
A chave do app só o dono cadastra; nada de chave ou token volta para a tela."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import google_drive as G
from .routes import _dono, _eh_dono, _job, router


@router.get("/google/status")
async def google_status(_u: dict = Depends(_dono)):
    return G.status(_u["avaliador_id"])


class ChaveGoogle(BaseModel):
    client_id: str = Field(max_length=300)
    client_secret: str = Field(max_length=300)


@router.put("/google/cliente")
async def google_cliente(body: ChaveGoogle, _u: dict = Depends(_dono)):
    """Só o dono cadastra a chave do app (Configurações → Google). Não devolve a chave."""
    if not _eh_dono(_u):
        raise HTTPException(status_code=403, detail="só o dono do sistema cadastra a chave do Google")
    try:
        G.gravar_cliente(body.client_id, body.client_secret)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"configurado": True}


@router.get("/google/conectar")
async def google_conectar(_u: dict = Depends(_dono)):
    try:
        return {"url": G.url_conectar(_u["avaliador_id"])}
    except G.GoogleErro as e:
        raise HTTPException(status_code=409, detail=str(e))


_PAGINA = ("<!doctype html><meta charset='utf-8'><title>JdB</title>"
           "<body style='font-family:system-ui;padding:40px;font-size:20px'><p>{}</p>"
           "<script>try{{window.opener&&window.opener.postMessage({{jdb:'google-conectado'}},'*')}}catch(e){{}}</script>")


@router.get("/google/retorno", response_class=HTMLResponse)
async def google_retorno(code: str = "", state: str = "", error: str = ""):
    """O Google volta aqui depois do login (sem o token do JdB: o estado assinado diz de quem é)."""
    if error or not code or not state:
        return HTMLResponse(_PAGINA.format("A conexão com o Google não foi feita. Pode fechar esta aba e tentar de novo."))
    try:
        G.trocar_codigo(code, state)
    except G.GoogleErro as e:
        return HTMLResponse(_PAGINA.format(str(e)))
    return HTMLResponse(_PAGINA.format("Google conectado ao João de Barro. Pode fechar esta aba."))


@router.post("/google/desligar")
async def google_desligar(_u: dict = Depends(_dono)):
    G.desligar(_u["avaliador_id"])
    return G.status(_u["avaliador_id"])


@router.get("/jobs/{jid}/google/ancora")
async def google_ancora(jid: str, trecho: str = "", _u: dict = Depends(_dono)):
    """169-4: o link do cartão — a âncora do Docs mais próxima antes da frase ("#heading=…"/"#bookmark=…")."""
    import asyncio
    from . import google_doc
    _job(jid)
    return await asyncio.to_thread(google_doc.ancora, jid, trecho)


@router.post("/jobs/{jid}/google/abrir")
async def google_abrir(jid: str, _u: dict = Depends(_dono)):
    """[Abrir o laudo editável] no Google Docs: sobe uma vez (na pasta "João de Barro") e abre sempre o mesmo."""
    _job(jid)
    if not G.conectado(_u["avaliador_id"]):
        raise HTTPException(status_code=409, detail="Conecte o seu Google antes de abrir o laudo editável.")
    try:
        return G.subir_editavel(jid)
    except G.GoogleErro as e:
        raise HTTPException(status_code=409, detail=str(e))
