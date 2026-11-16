"""ORDEM 041 / D-092: notificação do PRÓPRIO APP (Web Push), que toca no celular do avaliador.

Sem Google Agenda e sem convite .ics (decisão do Alan). O app é instalável (PWA, service worker);
o servidor guarda a "inscrição" do navegador e envia a notificação cifrada pelo padrão Web Push
(RFC 8291 aes128gcm + VAPID RFC 8292), sem biblioteca extra (cryptography + PyJWT).
As chaves VAPID ficam só na pasta de dados (fora do git). No celular, depende do site publicado
com HTTPS (etapa 5, com o Danilo); no PC funciona em localhost."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from lovable import config

from . import db

SUB = "mailto:avisos@joaodebarro.invalid"   # contato do remetente (genérico, sem dado do usuário)


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _chave() -> ec.EllipticCurvePrivateKey:
    p = config.DATA_DIR / "vapid_privada.pem"
    if not p.is_file():
        k = ec.generate_private_key(ec.SECP256R1())
        p.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    return serialization.load_pem_private_key(p.read_bytes(), None)


def chave_publica() -> str:
    pub = _chave().public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64u(pub)


# ------------------------------------------------------------------ inscrições
def _init():
    db.init()
    with db._conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS av_push (endpoint TEXT PRIMARY KEY, chaves TEXT NOT NULL, criado TEXT NOT NULL)")


def inscrever(sub: dict) -> None:
    _init()
    ep = str(sub.get("endpoint") or "")
    keys = sub.get("keys") or {}
    if not ep.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("inscrição inválida")
    with db._conn() as c:
        c.execute("INSERT OR REPLACE INTO av_push (endpoint, chaves, criado) VALUES (?,?,?)",
                  (ep, json.dumps(keys), time.strftime("%Y-%m-%dT%H:%M:%S")))


def inscricoes() -> list[dict]:
    _init()
    with db._conn() as c:
        return [{"endpoint": r[0], "keys": json.loads(r[1])} for r in c.execute("SELECT endpoint, chaves FROM av_push")]


def remover(endpoint: str) -> None:
    with db._conn() as c:
        c.execute("DELETE FROM av_push WHERE endpoint=?", (endpoint,))


# ------------------------------------------------------------------ cifra (RFC 8291) e VAPID (RFC 8292)
def _hkdf(salt: bytes, ikm: bytes, info: bytes, n: int) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:n]


def cifrar(payload: bytes, p256dh: str, auth: str) -> bytes:
    ua_pub = _unb64u(p256dh)
    auth_s = _unb64u(auth)
    as_priv = ec.generate_private_key(ec.SECP256R1())
    as_pub = as_priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = as_priv.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub))
    ikm = _hkdf(auth_s, shared, b"WebPush: info\x00" + ua_pub + as_pub, 32)
    salt = os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ct = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + (4096).to_bytes(4, "big") + bytes([len(as_pub)]) + as_pub + ct


def _vapid(endpoint: str) -> str:
    u = urlsplit(endpoint)
    tok = jwt.encode({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": SUB},
                     _chave(), algorithm="ES256")
    return f"vapid t={tok}, k={chave_publica()}"


def enviar(sub: dict, titulo: str, corpo: str, url: str = "") -> int:
    """Envia a uma inscrição. Devolve o status HTTP do serviço de push (201 = entregue)."""
    dados = json.dumps({"titulo": titulo, "corpo": corpo, "url": url}, ensure_ascii=False).encode()
    body = cifrar(dados, sub["keys"]["p256dh"], sub["keys"]["auth"])
    r = httpx.post(sub["endpoint"], content=body, timeout=20, headers={
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": "3600",
        "Urgency": "high", "Authorization": _vapid(sub["endpoint"])})
    if r.status_code in (404, 410):
        remover(sub["endpoint"])          # inscrição vencida
    return r.status_code


def enviar_todos(titulo: str, corpo: str, url: str = "") -> list[int]:
    out = []
    for s in inscricoes():
        try:
            out.append(enviar(s, titulo, corpo, url))
        except Exception:
            out.append(0)
    return out
