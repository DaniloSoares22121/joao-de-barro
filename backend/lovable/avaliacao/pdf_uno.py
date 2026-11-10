"""Script executado pelo Python do LibreOffice (não importar no backend).

uso: python pdf_uno.py <soffice> <entrada.docx> <saida.pdf> <perfil-uri>
Abre o documento oculto, atualiza índices (sumário) e campos duas vezes e exporta PDF."""
import subprocess
import sys
import time
import uuid
from pathlib import Path

import uno  # noqa: E402  (disponível só no Python do LibreOffice)
from com.sun.star.beans import PropertyValue  # noqa: E402


def _prop(nome, valor):
    p = PropertyValue()
    p.Name, p.Value = nome, valor
    return p


def main(soffice, entrada, saida, perfil):
    pipe = "jdb" + uuid.uuid4().hex[:8]
    proc = subprocess.Popen([soffice, f"-env:UserInstallation={perfil}", "--headless",
                             "--invisible", "--nologo", "--norestore",
                             f"--accept=pipe,name={pipe};urp;StarOffice.ComponentContext"])
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local)
        ctx = None
        for _ in range(120):
            try:
                ctx = resolver.resolve(
                    f"uno:pipe,name={pipe};urp;StarOffice.ComponentContext")
                break
            except Exception:
                time.sleep(0.5)
        if ctx is None:
            raise RuntimeError("não conectou ao LibreOffice")
        desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        doc = desktop.loadComponentFromURL(Path(entrada).as_uri(), "_blank", 0,
                                           (_prop("Hidden", True),))
        for _ in range(2):  # o sumário altera a paginação; a 2ª passada estabiliza
            idx = doc.getDocumentIndexes()
            for i in range(idx.getCount()):
                idx.getByIndex(i).update()
            doc.getTextFields().refresh()
        doc.storeToURL(Path(saida).as_uri(), (_prop("FilterName", "writer_pdf_Export"),))
        doc.close(True)
        try:
            desktop.terminate()
        except Exception:
            pass
    finally:
        try:
            proc.wait(timeout=20)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    main(*sys.argv[1:5])
