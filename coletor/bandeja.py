"""Ícone na bandeja (pystray) e atalho de inicialização automática."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _imagem(cor: str):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=cor)
    d.polygon([(32, 14), (12, 32), (52, 32)], fill="white")
    d.rectangle((20, 32, 44, 50), fill="white")
    return img


class Bandeja:
    def __init__(self, pasta_logs: Path, ao_sair):
        import pystray
        self.pasta_logs, self.ao_sair = pasta_logs, ao_sair
        self.conectado = False
        self.rotulo = "Desconectado"
        self.icone = pystray.Icon(
            "joaodebarro-coletor", _imagem("#9a9a9a"), "João de Barro — Desconectado",
            menu=pystray.Menu(
                pystray.MenuItem(lambda _i: self.rotulo,
                                 None, enabled=False),
                pystray.MenuItem("Abrir pasta de logs", self._logs),
                pystray.MenuItem("Sair", self._sair)))

    def iniciar(self):
        self.icone.run_detached()

    def status(self, conectado):
        """True/False, ou um texto (ex.: "pareie novamente") mostrado como alerta."""
        self.conectado = conectado
        texto = conectado if isinstance(conectado, str) else (
            "Conectado" if conectado else "Desconectado")
        cor = "#c0392b" if isinstance(conectado, str) else ("#2e8b57" if conectado else "#9a9a9a")
        self.rotulo = texto
        try:
            self.icone.icon = _imagem(cor)
            self.icone.title = "João de Barro — " + texto
            if isinstance(conectado, str):
                self.icone.notify("Token recusado: abra o coletor com --parear e cole um código novo.",
                                  "João de Barro — " + texto)
            self.icone.update_menu()
        except Exception:
            pass

    def _logs(self, *_):
        os.startfile(str(self.pasta_logs))  # noqa: S606 (Windows)

    def _sair(self, *_):
        self.ao_sair()
        self.icone.stop()


def instalar_autostart() -> Path:
    """Cria atalho em shell:startup apontando para este executável."""
    pasta = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    lnk = pasta / "João de Barro Coletor.lnk"
    if getattr(sys, "frozen", False):
        alvo, args = sys.executable, ""
    else:
        alvo = sys.executable.replace("python.exe", "pythonw.exe")
        args = f'"{Path(__file__).with_name("joaodebarro_coletor.py")}"'
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
          "$s.TargetPath=$env:ALVO;$s.Arguments=$env:ARGS;$s.Save()")
    env = dict(os.environ, LNK=str(lnk), ALVO=alvo, ARGS=args)
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, env=env,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return lnk
