"""ORDEM 169 (o documento no Google Docs): o que o JdB faz com o laudo que está no Drive do avaliador.

- puxar(jid): no [Concluir a revisão humana] (e no "✓ Todos os pontos conferidos"), o documento do Google Docs volta
  como .docx e passa a ser a cópia editável; daí o JdB gera o PDF pela NOSSA montagem (padrão do laudo) e confere por
  regra, como sempre. A cópia anterior fica guardada em revisoes/.
- ancora(jid, trecho): o link do cartão para o ponto certo do Docs. O Google não aceita link para uma frase; o JdB lê
  o documento exportado em HTML, acha a frase e devolve a âncora mais próxima ANTES dela (título "#heading=h.…" ou
  marcador "#bookmark=id.…"). Sem âncora antes, devolve "" (abre no começo).
Todo acesso ao Google passa por google_drive (nos testes, o Google simulado).
"""
from __future__ import annotations

import io
import re
import shutil
import time
import zipfile
from html.parser import HTMLParser

from . import db

_CACHE: dict[str, tuple[float, list]] = {}
VALIDADE = 30.0                     # s: os cartões tocados em sequência usam o mesmo HTML


def tem_google(jid: str) -> bool:
    from . import google_drive as G
    try:
        return bool(G.arquivo_do_trabalho(jid))
    except Exception:                          # noqa: BLE001
        return False


def puxar(jid: str) -> bool:
    """Traz o documento do Google Docs para a cópia editável. Devolve True se trouxe (False: o laudo não está no
    Docs). Erro do Google vira ValueError com a frase para o avaliador (o PDF não é gerado com o documento velho)."""
    from . import editavel
    from . import google_drive as G
    if not tem_google(jid):
        return False
    try:
        dados = G.exportar(jid, "docx")
    except Exception as e:                     # noqa: BLE001
        raise ValueError(f"Não consegui trazer o laudo do seu Google Docs agora ({type(e).__name__}). "
                         "Confira a internet e toque de novo.")
    try:
        with zipfile.ZipFile(io.BytesIO(dados)) as z:
            if "word/document.xml" not in z.namelist():
                raise zipfile.BadZipFile
    except zipfile.BadZipFile:
        raise ValueError("O Google não devolveu o laudo em Word. Toque de novo em alguns segundos.")
    c = editavel._garantir(jid)
    guarda = db.pasta(jid) / "revisoes" / f"edit-google-{editavel._agora().strftime('%Y%m%d-%H%M%S')}"
    guarda.mkdir(parents=True, exist_ok=True)
    with editavel._trava:
        if c.is_file():
            shutil.copy2(c, guarda / c.name)
        c.write_bytes(dados)
    _CACHE.pop(jid, None)
    db.evento(jid, "revisao", "info", "laudo trazido do Google Docs do avaliador para gerar o PDF")
    return True


class _Leitor(HTMLParser):
    """Blocos de texto do HTML exportado pelo Docs, cada um com a última âncora vista antes (ou nele)."""
    BLOCOS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ancora = ""
        self.blocos: list[tuple[str, str]] = []
        self._txt: list[str] = []
        self._dentro = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        idv = a.get("id") or ""
        if idv.startswith("h.") or idv.startswith("id."):
            self.ancora = ("#heading=" if idv.startswith("h.") else "#bookmark=") + idv
        if tag in self.BLOCOS:
            self._fechar()
            self._dentro += 1

    def handle_endtag(self, tag):
        if tag in self.BLOCOS:
            self._fechar()
            self._dentro = max(0, self._dentro - 1)

    def handle_data(self, data):
        if self._dentro:
            self._txt.append(data)

    def _fechar(self):
        t = " ".join("".join(self._txt).split())
        if t:
            self.blocos.append((self.ancora, t))
        self._txt = []


def _chave(s: str) -> str:
    return " ".join(str(s or "").replace(" ", " ").split()).casefold()


def _blocos(jid: str) -> list:
    from . import google_drive as G
    agora = time.monotonic()
    c = _CACHE.get(jid)
    if c and agora - c[0] < VALIDADE:
        return c[1]
    html = G.exportar(jid, "html").decode("utf-8", "replace")
    html = re.sub(r"<(style|script)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    p = _Leitor()
    p.feed(html)
    p._fechar()
    blocos = [(a, _chave(t)) for a, t in p.blocos]
    _CACHE[jid] = (agora, blocos)
    return blocos


def ancora(jid: str, trecho: str) -> dict:
    """{"ancora": "#heading=h.x" | "#bookmark=id.x" | "", "achou": bool} — a âncora mais próxima antes da frase."""
    if not tem_google(jid):
        return {"ancora": "", "achou": False}
    alvo = _chave(trecho)
    if len(alvo) < 4:
        return {"ancora": "", "achou": False}
    try:
        blocos = _blocos(jid)
    except Exception:                          # noqa: BLE001 — sem o HTML, abre no começo (o cartão traz a frase)
        return {"ancora": "", "achou": False}
    for corte in (alvo, alvo[:60], alvo[:30]):
        for a, t in blocos:
            if corte and corte in t:
                return {"ancora": a, "achou": True}
    return {"ancora": "", "achou": False}
