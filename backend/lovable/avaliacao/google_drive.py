"""ORDEM 169: o laudo editável no Google Docs, numa pasta do JdB no Drive do PRÓPRIO avaliador.

- Login do Google (OAuth) com a permissão mínima `drive.file`: o JdB só enxerga os arquivos que ele mesmo cria.
- A chave do app (client ID e secret) e os tokens de cada avaliador ficam em DATA_DIR/google/ (fora do git),
  nunca voltam para a tela e nunca vão para log.
- Pasta "João de Barro" → uma subpasta por trabalho ("Nº - Cliente - Tipo - Bairro - Cidade") → o editável.
- Nada é compartilhado nem fica público.
- Todo acesso ao Google passa por `_http` (troca-se por um Google simulado nos testes)."""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

from .. import config
from . import db

ESCOPO = "https://www.googleapis.com/auth/drive.file"
REDIRECT = "http://localhost:8866/api/avaliacao/google/retorno"
AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
REVOGAR = "https://oauth2.googleapis.com/revoke"
DRIVE = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
PASTA_RAIZ = "João de Barro"
MIME_PASTA = "application/vnd.google-apps.folder"
MIME_DOCS = "application/vnd.google-apps.document"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class GoogleErro(Exception):
    """Falha falando com o Google (mensagem em português simples, sem token nem segredo)."""


# ------------------------------------------------------------------ transporte (trocado nos testes)
def _http(metodo: str, url: str, **kw):
    import httpx
    return httpx.request(metodo, url, timeout=60, **kw)


# ------------------------------------------------------------------ guarda (fora do git)
def _pasta() -> Path:
    p = config.DATA_DIR / "google"
    (p / "tokens").mkdir(parents=True, exist_ok=True)
    return p


def _ler(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        return {}


def _gravar(p: Path, d: dict) -> None:
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def cliente() -> dict:
    return _ler(_pasta() / "cliente.json")


def configurado() -> bool:
    c = cliente()
    return bool(c.get("client_id") and c.get("client_secret"))


def gravar_cliente(client_id: str, client_secret: str) -> None:
    """Só o dono, pela tela de Configurações; nunca volta para a tela."""
    if not client_id.strip() or not client_secret.strip():
        raise ValueError("informe o ID do cliente e a chave secreta")
    _gravar(_pasta() / "cliente.json", {"client_id": client_id.strip(), "client_secret": client_secret.strip()})


def _arq_token(av: str) -> Path:
    return _pasta() / "tokens" / f"{av}.json"


def conectado(av: str) -> bool:
    return bool(_ler(_arq_token(av)).get("refresh_token"))


def status(av: str) -> dict:
    t = _ler(_arq_token(av))
    return {"configurado": configurado(), "conectado": bool(t.get("refresh_token")), "email": t.get("email", "")}


# ------------------------------------------------------------------ OAuth
def url_conectar(av: str) -> str:
    c = cliente()
    if not c:
        raise GoogleErro("A chave do Google ainda não foi cadastrada (Configurações → Google).")
    estado = secrets.token_urlsafe(24)
    db.set_setting(f"google_estado:{estado}", json.dumps({"av": av, "ts": time.time()}))
    return AUTH + "?" + urlencode({"client_id": c["client_id"], "redirect_uri": REDIRECT, "response_type": "code",
                                   "scope": ESCOPO + " openid email", "access_type": "offline",
                                   "prompt": "consent", "state": estado, "include_granted_scopes": "true"})


def trocar_codigo(codigo: str, estado: str) -> str:
    """Volta do Google: troca o código pelo token e guarda. Devolve o avaliador."""
    bruto = db.setting(f"google_estado:{estado}")
    db.set_setting(f"google_estado:{estado}", "")
    try:
        e = json.loads(bruto or "{}")
    except ValueError:
        e = {}
    if not e.get("av") or time.time() - float(e.get("ts") or 0) > 900:
        raise GoogleErro("O pedido de conexão expirou. Toque em Conectar o Google de novo.")
    c = cliente()
    r = _http("POST", TOKEN, data={"code": codigo, "client_id": c.get("client_id", ""), "client_secret": c.get("client_secret", ""),
                                   "redirect_uri": REDIRECT, "grant_type": "authorization_code"})
    if r.status_code != 200:
        raise GoogleErro("O Google não aceitou a conexão. Tente de novo.")
    d = r.json()
    if not d.get("refresh_token"):
        raise GoogleErro("O Google não devolveu a permissão completa. Desligue o JdB na sua conta Google e conecte de novo.")
    email = ""
    if d.get("id_token"):
        try:
            import base64
            corpo = d["id_token"].split(".")[1]
            email = json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4))).get("email", "")
        except Exception:
            email = ""
    _gravar(_arq_token(e["av"]), {"refresh_token": d["refresh_token"], "access_token": d.get("access_token", ""),
                                  "expira": time.time() + float(d.get("expires_in") or 0) - 60, "email": email})
    return e["av"]


def desligar(av: str) -> None:
    t = _ler(_arq_token(av))
    if t.get("refresh_token"):
        try:
            _http("POST", REVOGAR, data={"token": t["refresh_token"]})
        except Exception:
            pass                                 # mesmo sem resposta do Google, o JdB esquece o acesso
    _arq_token(av).unlink(missing_ok=True)


def _token(av: str) -> str:
    t = _ler(_arq_token(av))
    if not t.get("refresh_token"):
        raise GoogleErro("Conecte o seu Google antes (Configurações → Google).")
    if t.get("access_token") and time.time() < float(t.get("expira") or 0):
        return t["access_token"]
    c = cliente()
    r = _http("POST", TOKEN, data={"client_id": c.get("client_id", ""), "client_secret": c.get("client_secret", ""),
                                   "refresh_token": t["refresh_token"], "grant_type": "refresh_token"})
    if r.status_code != 200:
        raise GoogleErro("A conexão com o Google venceu. Conecte de novo (Configurações → Google).")
    d = r.json()
    t.update(access_token=d.get("access_token", ""), expira=time.time() + float(d.get("expires_in") or 0) - 60)
    _gravar(_arq_token(av), t)
    return t["access_token"]


def _api(av: str, metodo: str, url: str, **kw):
    h = kw.pop("headers", {}) | {"Authorization": f"Bearer {_token(av)}"}
    r = _http(metodo, url, headers=h, **kw)
    if r.status_code >= 400:
        raise GoogleErro(f"O Google recusou o pedido ({r.status_code}). Tente de novo.")
    return r


# ------------------------------------------------------------------ Drive: pasta, subir, abrir, exportar
def _multipart(meta: dict, dados: bytes) -> tuple[bytes, str]:
    """Corpo "multipart/related" do Drive: metadados (JSON) + o .docx."""
    limite = "jdb" + secrets.token_hex(8)
    q = "\r\n"
    cab = (f"--{limite}{q}Content-Type: application/json; charset=UTF-8{q}{q}{json.dumps(meta, ensure_ascii=False)}{q}"
           f"--{limite}{q}Content-Type: {MIME_DOCX}{q}{q}")
    return cab.encode() + dados + f"{q}--{limite}--{q}".encode(), limite


def _av_do_job(jid: str) -> str:
    return str((db.job(jid).get("dados") or {}).get("avaliador_id") or "AV-0001")


def _pasta_id(av: str, nome: str, pai: str | None) -> str:
    """Acha (entre os arquivos do próprio JdB) ou cria a pasta. Com drive.file, o Google só lista o que o JdB criou."""
    chave = f"google_pasta:{av}:{pai or 'raiz'}:{nome}"
    guardado = db.setting(chave)
    if guardado:
        return guardado
    corpo = {"name": nome, "mimeType": MIME_PASTA, **({"parents": [pai]} if pai else {})}
    fid = _api(av, "POST", f"{DRIVE}/files", json=corpo, params={"fields": "id"}).json()["id"]
    db.set_setting(chave, fid)
    return fid


def nome_do_trabalho(jid: str) -> str:
    from .orquestrador import _arquivos_finais
    return _arquivos_finais(jid)["docx"].stem          # "Nº - Cliente - Tipo - Bairro - Cidade"


def arquivo_do_trabalho(jid: str) -> str | None:
    return db.setting(f"google_doc:{jid}") or None


def url_do_documento(file_id: str) -> str:
    return f"https://docs.google.com/document/d/{file_id}/edit"


def subir_editavel(jid: str, converter: bool = True) -> dict:
    """Sobe o editável UMA vez (Google Docs, ou .docx no modo Office) e devolve {file_id, url, novo}.
    Já existindo, devolve o mesmo — nunca sobe outro por cima das mudanças do avaliador."""
    av = _av_do_job(jid)
    fid = arquivo_do_trabalho(jid)
    if fid:
        return {"file_id": fid, "url": url_do_documento(fid) if converter else f"https://docs.google.com/document/d/{fid}/edit",
                "novo": False}
    from . import editavel
    origem = editavel.caminho(jid)
    if not origem.is_file():
        from .orquestrador import _arquivos_finais
        origem = _arquivos_finais(jid)["docx"]
    if not origem.is_file():
        raise GoogleErro("Este trabalho ainda não tem o laudo em Word para editar.")
    raiz = _pasta_id(av, PASTA_RAIZ, None)
    sub = _pasta_id(av, nome_do_trabalho(jid), raiz)
    meta = {"name": nome_do_trabalho(jid), "parents": [sub], **({"mimeType": MIME_DOCS} if converter else {})}
    corpo, limite = _multipart(meta, origem.read_bytes())
    r = _api(av, "POST", UPLOAD, params={"uploadType": "multipart", "fields": "id"}, content=corpo,
             headers={"Content-Type": f"multipart/related; boundary={limite}"})
    fid = r.json()["id"]
    db.set_setting(f"google_doc:{jid}", fid)
    db.evento(jid, "revisao", "info", "laudo editável enviado para o Google Docs do avaliador (pasta João de Barro)")
    return {"file_id": fid, "url": url_do_documento(fid), "novo": True}


def exportar(jid: str, formato: str) -> bytes:
    """O documento do Drive em .docx ou .pdf (o Google limita a exportação a 10 MB por arquivo)."""
    fid = arquivo_do_trabalho(jid)
    if not fid:
        raise GoogleErro("O laudo ainda não está no seu Google Docs.")
    mime = {"docx": MIME_DOCX, "pdf": "application/pdf", "html": "text/html"}[formato]
    return _api(_av_do_job(jid), "GET", f"{DRIVE}/files/{fid}/export", params={"mimeType": mime}).content


def atualizar_conteudo(jid: str, docx: bytes) -> str:
    """Troca o conteúdo do MESMO arquivo (mesmo link, mesma pasta), convertendo o .docx para Google Docs.
    Uso só com a confirmação do avaliador (sobrescreve o que estiver no Docs)."""
    fid = arquivo_do_trabalho(jid)
    if not fid:
        raise GoogleErro("O laudo ainda não está no seu Google Docs.")
    corpo, limite = _multipart({"mimeType": MIME_DOCS}, docx)
    _api(_av_do_job(jid), "PATCH", f"{UPLOAD}/{fid}", params={"uploadType": "multipart", "fields": "id"}, content=corpo,
         headers={"Content-Type": f"multipart/related; boundary={limite}"})
    db.evento(jid, "revisao", "info", "laudo no Google Docs atualizado pelo JdB (mesmo arquivo)")
    return fid
