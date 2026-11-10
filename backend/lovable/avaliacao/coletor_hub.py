"""Hub do Coletor (app Windows no PC do avaliador que dirige o Chrome dele).

Credenciais: código de pareamento (8 chars, 10 min, uso único, em memória) troca por um token
de 32 bytes; só o sha256 do token fica em `av_settings` (um coletor ativo por vez).

Protocolo WS (JSON):
- coletor -> servidor: {"tipo":"ola","versao":"x"}
- servidor -> coletor: {"tipo":"tarefa","id","job","acao":"busca"|"anuncio"|"maps","url"}
- coletor -> servidor: {"tipo":"resultado","id","ok","bloqueado","url_final","texto"(<=60000),
  "links":[...],"print_b64":<JPEG/PNG base64, <=5 MB>,"fotos":[URLs, só texto],
  "fotos_b64":[<1ª foto do anúncio baixada PELO COLETOR, base64 JPEG/PNG <=5 MB>],"erro",
  "status":<HTTP do documento principal ou null>}
  O servidor nunca baixa URLs: foto só chega via fotos_b64 (salva em mercado/<id>-foto.<ext>).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import logging
import secrets
import time
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel

from . import db

log = logging.getLogger("lovable")


class ColetorOffline(Exception):
    """Sem coletor conectado, ou ele caiu com a tarefa em voo."""


class Captura(BaseModel):
    ok: bool = False
    bloqueado: bool = False
    url_final: str = ""
    texto: str = ""
    links: list = []
    print_path: str | None = None
    fotos: list = []          # URLs (só texto: o servidor NUNCA baixa URL)
    foto_path: str | None = None
    erro: str | None = None
    status: int | None = None   # HTTP do documento principal (informado pelo coletor)

ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # sem 0/O, 1/I/L
VALIDADE_CODIGO_S = 600
CHAVE_TOKEN = "coletor_token_sha256"
MAX_TEXTO = 60_000
MAX_PRINT = 5 * 1024 * 1024
JPEG, PNG = b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"


def _decodificar_print(b64) -> bytes | None:
    """Base64 estrito, <= 5 MB decodificado, só JPEG/PNG; senão None."""
    if not isinstance(b64, str) or len(b64) > (MAX_PRINT * 4) // 3 + 8:
        return None
    try:
        dados = base64.b64decode(b64, validate=True)
    except (ValueError, binascii.Error):
        return None
    if len(dados) > MAX_PRINT or not dados.startswith((JPEG, PNG)):
        return None
    return dados


def _salvar_imagem(job_id: str, b64, nome: str) -> str | None:
    """Valida (b64 estrito, <= 5 MB, JPEG/PNG) e grava em mercado/<nome>.<ext>; rel ou None."""
    if not b64:
        return None
    dados = _decodificar_print(b64)
    if dados is None:
        log.warning("coletor: imagem recusada (inválida ou > 5 MB)")
        return None
    try:
        ext = "png" if dados.startswith(PNG) else "jpg"
        rel = f"mercado/{nome}.{ext}"
        destino = db.pasta(job_id) / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(dados)
        db.adicionar_arquivo(job_id, f"{nome}.{ext}", "mercado", rel)
        return rel
    except Exception:
        log.exception("coletor: salvar imagem")
        return None


def _status(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and 100 <= v <= 599 else None


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


class Hub:
    def __init__(self):
        self.relogio = time.time
        self.codigos: dict[str, float] = {}   # código -> expira (epoch)
        self.ws = None
        self.visto_em: str | None = None
        self.versao: str | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.pendentes: dict[str, asyncio.Future] = {}   # id da tarefa -> Future (no loop do ws)

    def status(self) -> dict:
        return {"online": self.ws is not None, "visto_em": self.visto_em, "versao": self.versao}

    # ---------------------------------------------------------- pareamento
    def novo_codigo(self) -> tuple[str, str]:
        agora = self.relogio()
        self.codigos = {c: e for c, e in self.codigos.items() if e > agora}
        cod = "".join(secrets.choice(ALFABETO) for _ in range(8))
        exp = agora + VALIDADE_CODIGO_S
        self.codigos[cod] = exp
        return cod, _iso(exp)

    def parear(self, codigo: str) -> str | None:
        exp = self.codigos.pop((codigo or "").strip().upper(), None)
        if exp is None or exp <= self.relogio():
            return None
        token = secrets.token_urlsafe(32)
        db.set_setting(CHAVE_TOKEN, _sha(token))
        return token

    def validar_token(self, token: str) -> bool:
        guardado = db.setting(CHAVE_TOKEN) or ""
        return bool(token and guardado) and hmac.compare_digest(_sha(token), guardado)

    # ---------------------------------------------------------- canal ws
    async def conectar(self, ws) -> None:
        """Registra a conexão (antes do accept, p/ não haver janela sem dono); a antiga cai com 4409."""
        antiga = self.ws
        self._falhar_pendentes()
        self.ws, self.loop, self.versao = ws, asyncio.get_running_loop(), None
        self.visto_em = _iso(self.relogio())
        if antiga is not None:
            try:
                await antiga.close(code=4409)
            except Exception:
                pass

    def desconectar(self, ws) -> None:
        if self.ws is ws:
            self.ws = None
            self._falhar_pendentes()

    def _falhar_pendentes(self) -> None:
        for f in self.pendentes.values():
            if not f.done():
                f.set_exception(ColetorOffline("coletor desconectou"))
        self.pendentes.clear()

    def receber(self, ws, msg: dict) -> None:
        if self.ws is not ws:
            return
        self.visto_em = _iso(self.relogio())
        tipo = msg.get("tipo")
        if tipo == "ola":
            self.versao = str(msg.get("versao") or "") or None
        elif tipo == "resultado":
            f = self.pendentes.pop(str(msg.get("id")), None)
            if f is not None and not f.done():
                f.set_result(msg)

    async def _tarefa(self, job_id: str, acao: str, url: str, timeout: float) -> Captura:
        ws = self.ws
        if ws is None:
            raise ColetorOffline("coletor offline")
        tid = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self.pendentes[tid] = fut
        try:
            try:
                await ws.send_json({"tipo": "tarefa", "id": tid, "job": job_id, "acao": acao, "url": url})
            except Exception as e:
                raise ColetorOffline(str(e)) from e
            try:
                msg = await asyncio.wait_for(fut, timeout)
            except asyncio.TimeoutError:
                return Captura(erro="timeout")
        finally:
            self.pendentes.pop(tid, None)   # sempre (inclusive cancelamento)
        erro = msg.get("erro")
        cap = Captura(ok=bool(msg.get("ok")), bloqueado=bool(msg.get("bloqueado")),
                      url_final=str(msg.get("url_final") or ""),
                      texto=str(msg.get("texto") or "")[:MAX_TEXTO],
                      links=list(msg.get("links") or []), fotos=list(msg.get("fotos") or []),
                      erro=None if erro is None else str(erro)[:2000],
                      status=_status(msg.get("status")))
        cap.print_path = _salvar_imagem(job_id, msg.get("print_b64"), tid)
        fb = msg.get("fotos_b64")
        if isinstance(fb, list) and fb:
            cap.foto_path = _salvar_imagem(job_id, fb[0], f"{tid}-foto")
        return cap

    async def executar(self, job_id: str, acao: str, url: str, timeout: float = 120) -> Captura:
        """Roda a tarefa no loop da conexão ws (pode ser chamado de qualquer loop/thread)."""
        loop = self.loop
        if self.ws is None or loop is None or loop.is_closed():
            raise ColetorOffline("coletor offline")
        try:
            mesmo = loop is asyncio.get_running_loop()
        except RuntimeError:
            mesmo = False
        if mesmo:
            return await self._tarefa(job_id, acao, url, timeout)
        cf = asyncio.run_coroutine_threadsafe(self._tarefa(job_id, acao, url, timeout), loop)
        return await asyncio.wrap_future(cf)

hub = Hub()


def validar_token(token: str) -> bool:
    return hub.validar_token(token)


def online() -> bool:
    return hub.ws is not None


async def executar(job_id: str, acao: str, url: str, timeout: float = 120) -> Captura:
    return await hub.executar(job_id, acao, url, timeout)
