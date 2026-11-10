"""Conversão do laudo Word em PDF pelo LibreOffice headless, atualizando sumário e campos.

Caminho preferido: o Python do próprio LibreOffice (UNO) abre o .docx, atualiza todos os
índices (TOC) e campos — duas passadas, pois o sumário muda a paginação — e exporta o PDF
(`pdf_uno.py`). Se o UNO não estiver disponível, cai no `--convert-to pdf` simples: os
campos de página (PAGE/NUMPAGES/PAGEREF) são recalculados na paginação, mas o texto do
sumário fica o gerado na montagem (aviso no log)."""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from .planilha import soffice_path

log = logging.getLogger(__name__)
TIMEOUT = 120
_SCRIPT = Path(__file__).with_name("pdf_uno.py")


def _python_uno(soffice: str) -> str | None:
    """Python capaz de `import uno`: o embutido no LibreOffice (Windows/macOS) ou o do
    sistema (Linux, pacote python3-uno)."""
    prog = Path(soffice).resolve().parent
    for nome in ("python.exe", "python", "python3"):
        c = prog / nome
        if c.is_file():
            return str(c)
    py = shutil.which("python3")
    if py:
        try:
            subprocess.run([py, "-c", "import uno"], check=True, capture_output=True, timeout=20)
            return py
        except (subprocess.SubprocessError, OSError):
            pass
    return None


def _perfil() -> Path:
    return Path(tempfile.mkdtemp(prefix="jdb-lo-"))


def _matar_arvore(proc: subprocess.Popen) -> None:
    """Mata o processo e seus filhos (o soffice iniciado pelo pdf_uno)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def _rodar(cmd: list[str], timeout: int, env=None) -> None:
    kw = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
          else {"start_new_session": True})
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, **kw)
    try:
        _, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _matar_arvore(proc)
        proc.communicate()
        raise
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=err)


def converter(docx: Path, timeout: int = TIMEOUT) -> Path:
    docx = Path(docx).resolve()
    soffice = soffice_path()
    if soffice is None:
        raise RuntimeError("LibreOffice (soffice) não encontrado")
    destino = docx.with_suffix(".pdf")
    if destino.exists():
        destino.unlink()
    perfis: list[Path] = []
    try:
        py = _python_uno(soffice)
        if py:
            try:
                env = dict(os.environ)
                env.pop("PYTHONHOME", None)
                env.pop("PYTHONPATH", None)
                perfis.append(_perfil())
                _rodar([py, str(_SCRIPT), soffice, str(docx), str(destino),
                        perfis[-1].as_uri()], timeout, env)
                if destino.exists():
                    return destino
            except (subprocess.SubprocessError, OSError) as e:
                log.warning("conversão UNO falhou (%s); usando --convert-to simples", e)
        else:
            log.warning("Python UNO indisponível: sumário não será atualizado no PDF")
        perfis.append(_perfil())
        _rodar([soffice, f"-env:UserInstallation={perfis[-1].as_uri()}", "--headless",
                "--convert-to", "pdf", "--outdir", str(docx.parent), str(docx)], timeout)
        if not destino.exists():
            raise RuntimeError(f"LibreOffice não gerou o PDF de {docx.name}")
        return destino
    finally:
        for p in perfis:
            shutil.rmtree(p, ignore_errors=True)
