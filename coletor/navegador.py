"""Dirige o Google Chrome instalado (Playwright, channel="chrome") num perfil próprio."""
from __future__ import annotations

import asyncio
import base64
import logging
import random
import time
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger("coletor")

MAX_TEXTO = 60_000
MAX_IMAGEM = 5 * 1024 * 1024
LARGURA = 1366            # viewport (print sai <= 1600 px)
JPEG, PNG = b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"

# Domínios que o coletor aceita abrir (qualquer subdomínio).
DOMINIOS: tuple[str, ...] = ()   # 112: nenhum portal (a busca automática saiu); só o Google Maps
MAPS = (("google.com", "/maps"), ("google.com.br", "/maps"), ("maps.app.goo.gl", ""))


# ORDEM 018: na verificação ("Confirme que é humano", "Just a moment") a janela vem para a frente e
# o Coletor ESPERA a pessoa resolver (ou a verificação passar sozinha). Não clica nem contorna.
ESPERA_DESAFIO_S = 120.0
PASSO_DESAFIO_S = 2.0
# bloqueio que nenhuma pessoa resolve na hora: não adianta esperar
SINAIS_DEFINITIVO = ("you have been blocked", "você foi bloqueado", "voce foi bloqueado")

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


def permitida_para(acao: str, url: str) -> bool:
    """112: o Coletor só abre o Google Maps (a busca nos portais e na internet saiu)."""
    return acao == "maps" and url_permitida(url)


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


async def _definitivo(pagina) -> bool:
    try:
        texto = (await pagina.evaluate("() => document.body ? document.body.innerText : ''") or "")
    except Exception:
        return False
    t = texto.lower()[:20_000]
    return any(s in t for s in SINAIS_DEFINITIVO)


async def esperar_liberacao(pagina, status: dict, limite: float = ESPERA_DESAFIO_S,
                            passo: float = PASSO_DESAFIO_S, dormir=asyncio.sleep,
                            agora=time.monotonic) -> bool:
    """O portal mostrou uma verificação: traz a janela à frente e espera até `limite` s a PESSOA
    resolver (ou a verificação passar sozinha). True = a página do portal apareceu. O Coletor não
    clica, não resolve e não contorna nada. `status["s"]` é atualizado a cada documento novo."""
    if limite <= 0 or await _definitivo(pagina):
        return False
    try:
        await pagina.bring_to_front()
    except Exception:
        pass
    log.info("verificação do portal: esperando a pessoa resolver (até %d s)", int(limite))
    fim = agora() + limite
    while agora() < fim:
        await dormir(passo)
        try:
            if pagina.is_closed():
                return False
        except Exception:
            return False
        if not await bloqueado(pagina, status.get("s")):
            log.info("verificação resolvida: seguindo a coleta")
            return True
        if await _definitivo(pagina):
            return False
    return False


async def resposta_bloqueio(pagina, status: dict) -> dict:
    """Resultado de portal bloqueado com o título e o print do que apareceu (para o avaliador
    ver se era uma verificação que ele mesmo pode resolver)."""
    titulo = ""
    try:
        titulo = (await pagina.title() or "").strip()
    except Exception:
        pass
    res = {"ok": False, "bloqueado": True, "url_final": pagina.url,
           "erro": f"bloqueado: {titulo}"[:300] if titulo else "bloqueado", "status": status.get("s")}
    try:
        shot = await pagina.screenshot(type="jpeg", quality=70)
        if len(shot) <= MAX_IMAGEM:
            res["print_b64"] = base64.b64encode(shot).decode()
    except Exception:
        pass
    return res


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
                 headless: bool = False, canal: str | None = "chrome", permitir=url_permitida,
                 espera_desafio: float = ESPERA_DESAFIO_S):
        self.perfil, self.pausa, self.headless, self.canal = Path(perfil), pausa, headless, canal
        self.espera_desafio = 0 if headless else espera_desafio   # sem janela, ninguém resolve
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

    async def capturar(self, url: str, acao: str = "maps") -> dict:
        permitir = self.permitir
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
                        and not permitir(req.url)):
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
                        and req.frame == pagina.main_frame and not permitir(req.url)):
                    recusadas.append(req.url)
                    asyncio.ensure_future(pagina.close())
            pagina.on("request", _req)
            try:
                try:
                    await pagina.goto(url, wait_until="domcontentloaded", timeout=45_000)
                except Exception:
                    if recusadas:
                        return _recusada(pagina.url or url)
                    if status.get("s") not in (403, 429):
                        raise
                    if not permitir(pagina.url):   # nem chegou a mostrar a página
                        return {"ok": False, "bloqueado": True, "url_final": url,
                                "erro": "bloqueado", "status": status.get("s")}
                    # 403/429 com a página na tela: pode ser a verificação (abaixo)
                try:
                    await pagina.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:
                    pass
            finally:
                self._ultima = time.monotonic()
            if recusadas or not permitir(pagina.url):
                return _recusada(pagina.url)
            if await bloqueado(pagina, status.get("s")):
                if not await esperar_liberacao(pagina, status, self.espera_desafio):
                    return await resposta_bloqueio(pagina, status)
                try:   # a verificação passou: a página do portal recarrega
                    await pagina.wait_for_load_state("domcontentloaded", timeout=15_000)
                    await pagina.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:
                    pass
                if recusadas or not permitir(pagina.url):
                    return _recusada(pagina.url)
            pausa = (0.6, 1.6) if self.pausa[1] > 0 else (0, 0)
            if acao == "maps":
                # ORDEM 032-4: o painel lateral do lugar cobria o lote (o contorno saía cortado
                # no 7.1): recolhe o painel (botão do próprio Maps) antes do print
                try:
                    bt = pagina.locator('button[aria-label="Recolher painel lateral"], '
                                        'button[aria-label="Collapse side panel"]').first
                    if await bt.count():
                        await bt.click(timeout=3_000)
                        await asyncio.sleep(1.0)
                except Exception:
                    pass
                # no Maps a rodinha AFASTA o zoom (o lote saía minúsculo) e o mouse parado
                # sobre a interface deixava uma dica ("Recolher painel lateral") no print:
                # sem rolagem, mouse no canto e tempo para as imagens de satélite carregarem
                await pagina.mouse.move(LARGURA - 5, 895)
                if pausa[1] > 0:
                    await asyncio.sleep(2.5)
            dados = await pagina.evaluate(JS_COLETA)
            if recusadas or not permitir(pagina.url):   # navegou no meio da rolagem
                return _recusada(pagina.url)
            og = dados.get("og") or ""
            fotos = ([og] if og.startswith("http") else []) + [i for i in dados["imgs"] if i != og]
            shot = await pagina.screenshot(type="jpeg", quality=80)
            res = {"ok": True, "bloqueado": False, "url_final": pagina.url,
                   "texto": dados["texto"][:MAX_TEXTO], "links": dados["links"][:2000],
                   "fotos": fotos[:30], "erro": None, "status": status.get("s")}
            if len(shot) <= MAX_IMAGEM:
                res["print_b64"] = base64.b64encode(shot).decode()
            return res
        except Exception as e:
            log.exception("captura falhou: %s", url)
            return {"ok": False, "bloqueado": False, "url_final": url, "erro": str(e)[:500]}
        finally:
            try:
                await pagina.close()
            except Exception:   # janela fechada no meio: o resultado já está decidido
                pass
