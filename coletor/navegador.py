"""Dirige o Google Chrome instalado (Playwright, channel="chrome") num perfil próprio."""
from __future__ import annotations

import asyncio
import base64
import logging
import random
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

log = logging.getLogger("coletor")

MAX_TEXTO = 60_000
MAX_IMAGEM = 5 * 1024 * 1024
LARGURA = 1366            # viewport (print sai <= 1600 px)
JPEG, PNG = b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"

# Domínios que o coletor aceita abrir (qualquer subdomínio).
DOMINIOS = ("zapimoveis.com.br", "vivareal.com.br", "olx.com.br", "imovelweb.com.br")
MAPS = (("google.com", "/maps"), ("google.com.br", "/maps"), ("maps.app.goo.gl", ""))

# CDNs de imagem aceitas por portal (o próprio domínio + CDNs conhecidas dele).
CDNS_IMAGEM = {
    "zapimoveis.com.br": ("zapimoveis.com.br", "vivareal.com.br", "grupozap.com"),
    "vivareal.com.br": ("vivareal.com.br", "vivareal.com", "zapimoveis.com.br", "grupozap.com"),
    "olx.com.br": ("olx.com.br", "olxcdn.com"),   # img.olx.com.br
    "imovelweb.com.br": ("imovelweb.com.br", "imovelwebcdn.com", "naventcdn.com", "zonapropcdn.com"),
}

SINAIS_BLOQUEIO = ("captcha", "não sou um robô", "nao sou um robo", "acesso negado",
                   "access denied", "just a moment", "verify you are human",
                   "verifique se você é humano", "verificando se você é humano",
                   "press & hold", "pressione e segure")


def _sob(host: str, dom: str) -> bool:
    return host == dom or host.endswith("." + dom)


def url_permitida(url: str) -> bool:
    try:
        p = urlsplit(url or "")
        host = (p.hostname or "").lower()
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not host or p.username or p.password:
        return False
    if any(_sob(host, d) for d in DOMINIOS):
        return True
    for dom, prefixo in MAPS:
        if host in (dom, "www." + dom) and p.path.startswith(prefixo):
            return True
    return False


def foto_permitida(url_foto: str, url_pagina: str) -> bool:
    """https e do mesmo portal do anúncio (ou CDN conhecida dele)."""
    try:
        f, pg = urlsplit(url_foto or ""), urlsplit(url_pagina or "")
        hf, hp = (f.hostname or "").lower(), (pg.hostname or "").lower()
    except ValueError:
        return False
    if f.scheme != "https" or not hf:
        return False
    for portal, cdns in CDNS_IMAGEM.items():
        if _sob(hp, portal):
            return any(_sob(hf, c) for c in cdns)
    return False


def _jpeg_ou_png(dados: bytes) -> bytes | None:
    if dados.startswith((JPEG, PNG)):
        return dados
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(dados)) as im:
            out = io.BytesIO()
            im.convert("RGB").save(out, "JPEG", quality=80)
        b = out.getvalue()
        return b if len(b) <= MAX_IMAGEM else None
    except Exception:
        return None


async def bloqueado(pagina, status: int | None = None) -> bool:
    if status in (403, 429):
        return True
    try:
        titulo = (await pagina.title() or "").lower()
        texto = (await pagina.evaluate(
            "() => document.body ? document.body.innerText : ''") or "").lower()
        if any(s in titulo or s in texto[:20_000] for s in SINAIS_BLOQUEIO):
            return True
        return bool(await pagina.evaluate(
            # só iframe de desafio VISÍVEL: o reCAPTCHA invisível (aframe 0x0) está em toda página
            """() => !!document.querySelector('#px-captcha, #challenge-form') ||
               [...document.querySelectorAll('iframe')].some(f =>
                 /recaptcha|hcaptcha|captcha|challenges[.]cloudflare[.]com/i.test(
                     (f.src||'') + ' ' + (f.title||''))
                 && f.offsetWidth > 1 && f.offsetHeight > 1
                 && !/size=invisible/i.test(f.src||''))"""))
    except Exception:
        return False


JS_COLETA = """() => ({
  texto: document.body ? document.body.innerText : '',
  links: [...new Set([...document.querySelectorAll('a[href]')].map(a => a.href)
           .filter(h => /^https?:/i.test(h)))],
  og: (document.querySelector('meta[property="og:image"]') || {}).content || '',
  imgs: [...new Set([...document.images]
           .filter(i => (i.naturalWidth || i.width) >= 300 && (i.naturalHeight || i.height) >= 200)
           .map(i => i.currentSrc || i.src).filter(s => /^https?:/i.test(s)))]
})"""


def _recusada(url_final: str) -> dict:
    """Saiu da lista permitida (redirecionamento/navegação da página): nada de texto/print."""
    log.warning("navegação fora da lista recusada: %s", (url_final or "")[:200])
    return {"ok": False, "bloqueado": False, "url_final": "", "erro": "url não permitida"}


class Navegador:
    def __init__(self, perfil: Path | str, pausa: tuple[float, float] = (4, 9),
                 headless: bool = False, canal: str | None = "chrome", permitir=url_permitida):
        self.perfil, self.pausa, self.headless, self.canal = Path(perfil), pausa, headless, canal
        self.permitir = permitir     # allowlist de navegação do quadro principal
        self._pw = self._ctx = None
        self._ultima = 0.0

    async def abrir(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        kw = {"channel": self.canal} if self.canal else {}
        self._ctx = await self._pw.chromium.launch_persistent_context(
            str(self.perfil), headless=self.headless, locale="pt-BR",
            viewport={"width": LARGURA, "height": 900}, **kw)
        return self

    async def fechar(self):
        try:
            if self._ctx:
                await self._ctx.close()
        finally:
            if self._pw:
                await self._pw.stop()
            self._ctx = self._pw = None

    async def _ritmo(self):
        """Pausa humana (4–9 s) desde a última página."""
        if not self._ultima or self.pausa[1] <= 0:
            return
        falta = random.uniform(*self.pausa) - (time.monotonic() - self._ultima)
        if falta > 0:
            await asyncio.sleep(falta)

    async def _baixar_foto(self, pagina, candidatas: list[str], url_pagina: str) -> str | None:
        """1ª foto válida do anúncio: https, domínio do portal/CDN, <= 5 MB, 20 s no total.
        Os portais servem WebP: converte para JPEG (q=80) quando não for JPEG/PNG."""
        urls = [u for u in candidatas if foto_permitida(u, url_pagina)
                and not urlsplit(u).path.lower().endswith((".svg", ".gif"))][:3]

        async def _get():
            for url in urls:
                r = None
                for _ in range(4):   # até 3 redirecionamentos, cada destino checado
                    r = await pagina.request.get(url, timeout=20_000, max_redirects=0)
                    if 300 <= r.status < 400 and r.headers.get("location"):
                        url = urljoin(url, r.headers["location"])
                        if not foto_permitida(url, url_pagina):
                            r = None
                            break
                        continue
                    break
                if (r is not None and r.ok
                        and int(r.headers.get("content-length") or 0) <= MAX_IMAGEM):
                    dados = await r.body()
                    if dados and len(dados) <= MAX_IMAGEM:
                        dados = _jpeg_ou_png(dados)
                        if dados:
                            return dados
            return None
        if not urls:
            return None
        try:
            dados = await asyncio.wait_for(_get(), 20)
        except Exception as e:
            log.info("foto não baixada (%s): %s", urls[0][:120], e)
            return None
        return base64.b64encode(dados).decode() if dados else None

    async def _nova_pagina(self):
        """Aba nova. A janela do Chrome é visível: se a pessoa fechou, reabre o navegador em
        vez de derrubar a conexão (o que fazia o servidor refazer a pesquisa inteira, em
        laço, até acabar a cota de IA do trabalho)."""
        try:
            return await self._ctx.new_page()
        except Exception as e:
            log.warning("navegador indisponível (%s): reabrindo", e)
            try:
                await self.fechar()
            except Exception:
                pass
            await self.abrir()
            return await self._ctx.new_page()

    async def capturar(self, url: str, acao: str = "busca") -> dict:
        await self._ritmo()
        try:
            pagina = await self._nova_pagina()
        except Exception as e:
            log.exception("não foi possível abrir o navegador")
            return {"ok": False, "bloqueado": False, "url_final": url,
                    "erro": f"navegador indisponível: {e}"[:500]}
        try:
            status, recusadas = {}, []

            async def _rota(route):
                req = route.request
                if (req.is_navigation_request() and req.frame.parent_frame is None
                        and not self.permitir(req.url)):
                    recusadas.append(req.url)
                    await route.abort("blockedbyclient")
                else:
                    await route.continue_()
            await pagina.route("**/*", _rota)

            def _resp(r):   # status do documento principal (mesmo se o goto falhar)
                if r.request.is_navigation_request() and r.frame == pagina.main_frame:
                    status["s"] = r.status
            pagina.on("response", _resp)

            def _req(req):   # redirecionamento HTTP (o route não vê) para fora da lista
                if (req.redirected_from is not None and req.is_navigation_request()
                        and req.frame == pagina.main_frame and not self.permitir(req.url)):
                    recusadas.append(req.url)
                    asyncio.ensure_future(pagina.close())
            pagina.on("request", _req)
            try:
                try:
                    await pagina.goto(url, wait_until="domcontentloaded", timeout=45_000)
                except Exception:
                    if recusadas:
                        return _recusada(pagina.url or url)
                    if status.get("s") in (403, 429):
                        return {"ok": False, "bloqueado": True, "url_final": pagina.url or url,
                                "erro": "bloqueado"}
                    raise
                try:
                    await pagina.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:
                    pass
            finally:
                self._ultima = time.monotonic()
            if recusadas or not self.permitir(pagina.url):
                return _recusada(pagina.url)
            if await bloqueado(pagina, status.get("s")):
                return {"ok": False, "bloqueado": True, "url_final": pagina.url,
                        "erro": "bloqueado", "status": status.get("s")}
            pausa = (0.6, 1.6) if self.pausa[1] > 0 else (0, 0)
            for _ in range(3):
                await pagina.mouse.wheel(0, 900)
                await asyncio.sleep(random.uniform(*pausa))
            dados = await pagina.evaluate(JS_COLETA)
            if recusadas or not self.permitir(pagina.url):   # navegou no meio da rolagem
                return _recusada(pagina.url)
            og = dados.get("og") or ""
            fotos = ([og] if og.startswith("http") else []) + [i for i in dados["imgs"] if i != og]
            shot = await pagina.screenshot(type="jpeg", quality=80)
            res = {"ok": True, "bloqueado": False, "url_final": pagina.url,
                   "texto": dados["texto"][:MAX_TEXTO], "links": dados["links"][:2000],
                   "fotos": fotos[:30], "erro": None, "status": status.get("s")}
            if len(shot) <= MAX_IMAGEM:
                res["print_b64"] = base64.b64encode(shot).decode()
            if acao == "anuncio" and fotos:
                b64 = await self._baixar_foto(pagina, fotos, pagina.url)
                if b64:
                    res["fotos_b64"] = [b64]
            return res
        except Exception as e:
            log.exception("captura falhou: %s", url)
            return {"ok": False, "bloqueado": False, "url_final": url, "erro": str(e)[:500]}
        finally:
            try:
                await pagina.close()
            except Exception:   # janela fechada no meio: o resultado já está decidido
                pass
