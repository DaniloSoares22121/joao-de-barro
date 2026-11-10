"""João de Barro — Coletor (Windows). Dirige o Chrome deste PC a pedido do servidor Brixly."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

import config
import conexao
from navegador import Navegador


def _logs():
    pasta = config.pasta_base() / "logs"
    pasta.mkdir(exist_ok=True)
    h = RotatingFileHandler(pasta / "coletor.log", maxBytes=2_000_000, backupCount=3,
                            encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log = logging.getLogger("coletor")
    log.setLevel(logging.INFO)
    log.addHandler(h)
    return pasta


async def _rodar(cfg, bandeja_cls, pasta_logs):
    parar = asyncio.Event()
    loop = asyncio.get_running_loop()
    tray = None
    if bandeja_cls:
        tray = bandeja_cls(pasta_logs, lambda: loop.call_soon_threadsafe(parar.set))
        tray.iniciar()
    try:
        nav = await Navegador(config.pasta_base() / "perfil-chrome").abrir()
    except Exception as e:
        logging.getLogger("coletor").exception("Chrome não abriu")
        _erro("Não foi possível abrir o Google Chrome. Instale o Chrome "
              f"(google.com/chrome) e abra o coletor de novo." + chr(10) * 2 + f"{e}")
        if tray:
            tray.icone.stop()
        return
    try:
        await conexao.loop(cfg, nav, parar=parar, ao_status=tray.status if tray else None)
    finally:
        await nav.fechar()


def _erro(msg: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        raiz = tk.Tk()
        raiz.withdraw()
        messagebox.showerror("João de Barro — Coletor", msg, parent=raiz)
        raiz.destroy()
    except Exception:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(prog="joaodebarro-coletor")
    ap.add_argument("--servidor", help="URL do servidor (dev); padrão " + config.SERVIDOR_PADRAO)
    ap.add_argument("--parear", action="store_true", help="pedir novo código de pareamento")
    ap.add_argument("--instalar-autostart", action="store_true")
    ap.add_argument("--sem-bandeja", action="store_true")
    a = ap.parse_args(argv)
    pasta_logs = _logs()
    if a.instalar_autostart:
        from bandeja import instalar_autostart
        print(instalar_autostart())
        return 0
    cfg = config.garantir(a.servidor, a.parear)
    if not cfg:
        return 1
    bandeja_cls = None
    if not a.sem_bandeja:
        from bandeja import Bandeja
        bandeja_cls = Bandeja
    asyncio.run(_rodar(cfg, bandeja_cls, pasta_logs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
