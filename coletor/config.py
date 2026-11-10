r"""Configuração do Coletor: %LOCALAPPDATA%\JoaoDeBarro\config.json (servidor, token)."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

SERVIDOR_PADRAO = "https://app.brixly.com.br"


def pasta_base() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    p = Path(base) / "JoaoDeBarro"
    p.mkdir(parents=True, exist_ok=True)
    return p


def caminho() -> Path:
    return pasta_base() / "config.json"


def carregar() -> dict:
    try:
        return json.loads(caminho().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def salvar(cfg: dict) -> None:
    """Gravação atômica (temp + os.replace): queda no meio não corrompe o config."""
    destino = caminho()
    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, destino)


def url_ws(cfg: dict) -> str:
    s = cfg["servidor"].rstrip("/")
    s = "wss://" + s[8:] if s.startswith("https://") else "ws://" + s.removeprefix("http://")
    return f"{s}/ws/avaliacao/coletor"


def cabecalhos(cfg: dict) -> dict:
    return {"Authorization": f"Bearer {cfg['token']}"}


def parear(servidor: str, codigo: str, timeout: float = 20) -> str:
    """Troca o código de 8 caracteres por um token (POST /api/avaliacao/coletor/parear)."""
    req = urllib.request.Request(
        servidor.rstrip("/") + "/api/avaliacao/coletor/parear",
        data=json.dumps({"codigo": codigo.strip().upper()}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["token"]


def pedir_codigo() -> str | None:
    """Janelinha tkinter pedindo o código mostrado em Configurações > Coletor."""
    import tkinter as tk
    from tkinter import simpledialog
    raiz = tk.Tk()
    raiz.withdraw()
    try:
        return simpledialog.askstring(
            "João de Barro — Coletor",
            "Cole o código de pareamento (Configurações > Coletor no Brixly):", parent=raiz)
    finally:
        raiz.destroy()


def garantir(servidor: str | None = None, forcar_pareamento: bool = False) -> dict | None:
    cfg = carregar()
    if servidor:
        if cfg.get("servidor") != servidor:
            cfg.pop("token", None)
        cfg["servidor"] = servidor
    cfg.setdefault("servidor", SERVIDOR_PADRAO)
    if cfg.get("token") and not forcar_pareamento:
        return cfg
    from tkinter import messagebox
    while True:
        cod = pedir_codigo()
        if not cod:
            return None
        try:
            cfg["token"] = parear(cfg["servidor"], cod)
            salvar(cfg)
            return cfg
        except Exception as e:  # código inválido/expirado ou rede
            messagebox.showerror("João de Barro — Coletor", f"Não foi possível parear: {e}")
