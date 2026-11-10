import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import navegador as nv  # noqa: E402

ANUNCIO = """<html><head><title>Casa 3 quartos Jardim Vila Boa</title></head><body>
<h1>Casa à venda</h1><p>3 quartos, 180 m², R$ 650.000</p>
<a href="https://www.zapimoveis.com.br/imovel/venda-casa-3-quartos-id-123/">anúncio</a>
<a href="/relativo">rel</a>
<div style="height:3000px"></div></body></html>"""


def _rodar(coro):
    return asyncio.run(coro)


async def _com_pagina(html, fn):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", headless=True)
        pg = await b.new_page()
        await pg.set_content(html)
        try:
            return await fn(pg)
        finally:
            await b.close()


@pytest.mark.parametrize("html,esperado", [
    ("<html><title>Verificação</title><body>Por favor resolva o captcha</body></html>", True),
    ("<html><body><iframe src='https://www.google.com/recaptcha/api2/anchor' width='304' height='78'></iframe></body></html>", True),
    ("<html><body>Não sou um robô</body></html>", True),
    ("<html><title>Access Denied</title><body>x</body></html>", True),
    (ANUNCIO, False),
    # reCAPTCHA invisível (iframe 0x0) presente em páginas normais dos portais
    (ANUNCIO.replace("<h1>", "<iframe src='https://www.google.com/recaptcha/api2/aframe' "
                    "width='0' height='0' style='border:0'></iframe><h1>"), False),
    ("<html><body>Robô aspirador em oferta</body></html>", False),
])
def test_bloqueado(html, esperado):
    assert _rodar(_com_pagina(html, nv.bloqueado)) is esperado


def test_bloqueado_por_status():
    assert _rodar(_com_pagina(ANUNCIO, lambda pg: nv.bloqueado(pg, 429))) is True


def test_capturar_file(tmp_path):
    arq = tmp_path / "anuncio.html"
    arq.write_text(ANUNCIO, encoding="utf-8")

    async def go():
        n = await nv.Navegador(tmp_path / "perfil", pausa=(0, 0), headless=True,
                               permitir=_so_file).abrir()
        try:
            return await n.capturar(arq.as_uri(), "anuncio")
        finally:
            await n.fechar()
    r = _rodar(go())
    assert r["ok"] and not r["bloqueado"]
    assert "3 quartos" in r["texto"]
    assert "https://www.zapimoveis.com.br/imovel/venda-casa-3-quartos-id-123/" in r["links"]
    assert r["print_b64"].startswith("/9j/")     # JPEG
    assert "fotos_b64" not in r


def test_url_permitida():
    ok = ["https://www.zapimoveis.com.br/venda/", "https://www.olx.com.br/d/x",
          "https://www.google.com/maps/search/x", "https://maps.app.goo.gl/abc",
          "https://www.google.com.br/maps/place/x"]
    nao = ["https://evil.com/", "https://zapimoveis.com.br.evil.com/", "https://www.google.com/search",
           "file:///c:/x", "javascript:alert(1)", "https://user@olx.com.br.evil.com/"]
    assert all(nv.url_permitida(u) for u in ok)
    assert not any(nv.url_permitida(u) for u in nao)


def test_foto_permitida():
    pg = "https://www.zapimoveis.com.br/imovel/x/"
    assert nv.foto_permitida("https://resizedimgs.zapimoveis.com.br/a.jpg", pg)
    assert not nv.foto_permitida("http://resizedimgs.zapimoveis.com.br/a.jpg", pg)
    assert not nv.foto_permitida("https://evil.com/a.jpg", pg)
    assert not nv.foto_permitida("https://img.olx.com.br/a.jpg", pg)


def test_foto_cdns_vistas_ao_vivo():
    assert nv.foto_permitida("https://resizedimgs.vivareal.com/img/x.webp",
                             "https://www.vivareal.com.br/imovel/x/")
    assert nv.foto_permitida("https://imgbr.imovelwebcdn.com/avisos/1.jpg",
                             "https://www.imovelweb.com.br/propriedades/x-1.html")


def test_webp_vira_jpeg():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "WEBP")
    assert nv._jpeg_ou_png(buf.getvalue()).startswith(nv.JPEG)
    assert nv._jpeg_ou_png(b"<svg/>") is None


@pytest.mark.parametrize("marcador", [
    "Just a moment...", "Verify you are human", "Verifique se você é humano",
    "Verificando se você é humano", "Press & Hold", "Pressione e segure"])
def test_bloqueado_desafios_antibot(marcador):
    assert _rodar(_com_pagina(f"<html><body><p>{marcador}</p></body></html>", nv.bloqueado))


@pytest.mark.parametrize("html", [
    "<html><body><iframe src='https://challenges.cloudflare.com/cdn-cgi/x' width='300' height='65'></iframe></body></html>",
    "<html><body><div id='px-captcha'></div></body></html>",
    "<html><body><form id='challenge-form'></form></body></html>"])
def test_bloqueado_elementos_desafio(html):
    assert _rodar(_com_pagina(html, nv.bloqueado))


def _so_file(u):
    return u.startswith("file:") or nv.url_permitida(u)


@pytest.mark.parametrize("corpo", [
    "<meta http-equiv='refresh' content='0;url=http://127.0.0.1:9/'>",
    "<a href='https://evil.example/'>x</a><script>setTimeout(()=>document.querySelector('a').click(),50)</script>",
])
def test_navegacao_fora_da_lista_recusada(tmp_path, corpo):
    arq = tmp_path / "p.html"
    arq.write_text(f"<html><head></head><body>segredo {corpo}</body></html>", encoding="utf-8")

    async def go():
        n = await nv.Navegador(tmp_path / "perfil", pausa=(0, 0), headless=True,
                               permitir=_so_file).abrir()
        try:
            return await n.capturar(arq.as_uri(), "busca")
        finally:
            await n.fechar()
    r = _rodar(go())
    assert r["ok"] is False and r["erro"] == "url não permitida"
    assert "texto" not in r and "print_b64" not in r


def test_redirecionamento_http_fora_da_lista_recusado(tmp_path):
    import http.server
    import threading
    import time

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/ok":
                self.send_response(302)
                self.send_header("Location", "/fora")
                self.end_headers()
            else:
                fora.append(self.path)
                time.sleep(6)   # a página fora da lista não pode ser esperada nem lida
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>segredo fora</body></html>")

        def log_message(self, *a):
            pass

    fora = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    async def go():
        n = await nv.Navegador(tmp_path / "perfil", pausa=(0, 0), headless=True,
                               permitir=lambda u: u.startswith(base + "/ok")).abrir()
        try:
            return await n.capturar(base + "/ok", "busca")
        finally:
            await n.fechar()
    t0 = time.monotonic()
    try:
        r = _rodar(go())
    finally:
        srv.shutdown()
    assert time.monotonic() - t0 < 5, "esperou carregar a página fora da lista"
    assert r["ok"] is False and r["erro"] == "url não permitida"
    assert "texto" not in r and "print_b64" not in r
