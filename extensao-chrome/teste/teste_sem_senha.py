"""ORDEM 077-D: extensão SEM login + aba do JdB aberta -> se liga sozinha, /extensao/estado instalada:true e envio aceito.
Servidor de teste 8868 (dados temporários) + tela de teste 5179. O anúncio do ZAP é página salva servida pelo Playwright.
Rodar: suba um servidor de TESTE (banco temporário) em 8868 e a tela de teste ligada a ele
(JDB_PORTA=5179 JDB_API=8868 npx vite --config vite.joaodebarro.config.ts) e rode com o Python do Coletor (Playwright).
"""
import asyncio
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")
SP = Path(tempfile.gettempdir())
EXT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("JDB_TESTE_PRINTS", tempfile.gettempdir()))
API = os.environ.get("JDB_TESTE_SERVIDOR", "http://127.0.0.1:8868").rstrip("/")
if API.endswith(":8866"):
    sys.exit("TRAVA (ORDEM 046): o 8866 é o banco real do Alan. Use um servidor de teste.")
APP = os.environ.get("JDB_TESTE_TELA", "http://127.0.0.1:5179/assets-jdb/joaodebarro.html")
ANUNCIO = "https://www.zapimoveis.com.br/imovel/venda-casa-3-quartos-jardim-exemplo-goiania-go-120m2-id-2999999999/"
HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Casa com 3 quartos à venda, 120 m² - Jardim Exemplo</title>
<meta property="og:image" content="https://resizedimgs.zapimoveis.com.br/img/vr-listing/teste/foto.jpg"></head>
<body style="font-family:Arial;margin:0"><div style="display:flex;gap:16px;padding:16px">
<img width="720" height="460" alt="foto" src="https://resizedimgs.zapimoveis.com.br/img/vr-listing/teste/foto.jpg">
<div><h1>Casa com 3 quartos à venda, 120 m²</h1><p style="font-size:26px">R$ 480.000</p>
<p>Área construída 120 m² · Terreno 360 m² · 3 quartos</p><p>Rua Exemplo, Jardim Exemplo, Goiânia - GO</p></div></div>
<p style="height:900px">Casa térrea.</p></body></html>"""


def foto() -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (720, 460), (120, 150, 110)).save(b, "JPEG")
    return b.getvalue()


EXT_T = SP / "jdb_ext_teste_077d"
shutil.rmtree(EXT_T, ignore_errors=True)
shutil.copytree(EXT, EXT_T, ignore=shutil.ignore_patterns("teste"))
m = json.loads((EXT_T / "manifest.json").read_text(encoding="utf-8"))
# só os portais já permitidos (no Chrome real: "Permitir o JdB nos portais", 1 toque). NADA de servidor/token.
m["host_permissions"] += m["web_accessible_resources"][0]["matches"] + ["https://*.imovelwebcdn.com/*"]
(EXT_T / "manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")


async def main():
    from playwright.async_api import async_playwright
    for _ in range(60):
        try:
            tk = httpx.post(API + "/api/auth/login", json={"email": "avaliador@local", "password": "joaodebarro"}, timeout=3).json()["token"]
            break
        except Exception:
            time.sleep(1)
    c = httpx.Client(base_url=API + "/api/avaliacao", headers={"Authorization": f"Bearer {tk}"}, timeout=60)
    c.post("/extensao/estado", json={"versao": "", "fixada": None, "portais": None})   # zera o "visto"
    jobs = c.get("/jobs").json()
    jid = next((j["id"] for j in jobs if j["numero"] == 99076), None) or c.post("/jobs", json={
        "numero": 99076, "modalidade": "OV", "finalidade": "Venda.", "cliente": "Cliente Exemplo", "tipo": "Casa",
        "bairro": "Jardim Exemplo", "cidade": "Goiânia", "pin_maps": "", "data_base": "2026-11-14",
        "data_vistoria": "2026-11-14"}).json()["id"]
    antes = len(c.get(f"/jobs/{jid}").json()["candidatos"])
    perfil = Path(tempfile.mkdtemp())
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            str(perfil), channel="chromium", headless=True, viewport={"width": 1280, "height": 800}, locale="pt-BR",
            args=[f"--disable-extensions-except={EXT_T}", f"--load-extension={EXT_T}"])
        sw = ctx.service_workers[0] if ctx.service_workers else await ctx.wait_for_event("serviceworker")
        print("1) extensão recém-instalada, sem login:", await sw.evaluate("() => chrome.storage.local.get(null)"))
        await sw.evaluate("() => registrarBotao()")
        # o JdB do Alan já está logado neste Chrome (a sessão do app fica no navegador, como no localhost:5177)
        await ctx.add_init_script(f"if (location.href.startsWith({json.dumps(APP.split('/assets-jdb')[0])})) localStorage.setItem('jdb_token', {json.dumps(tk)})")
        app = await ctx.new_page()
        await app.goto(APP)
        await app.wait_for_timeout(5000)
        st = await sw.evaluate("() => chrome.storage.local.get(['servidor', 'ligado_por']).then(async (c) => ({...c, tem_token: !!(await chrome.storage.local.get('jdb_token')).jdb_token}))")
        print("2) depois de abrir o JdB:", st)
        assert st.get("tem_token") and st.get("ligado_por") == "aba", st
        await app.wait_for_timeout(1500)
        print("3) /extensao/estado:", c.get("/extensao/estado").json())
        assert c.get("/extensao/estado").json()["instalada"] is True
        # popup: "Conectado ao JdB ✓"
        ext_id = sw.url.split("/")[2]
        pop = await ctx.new_page()
        await pop.set_viewport_size({"width": 360, "height": 520})
        await pop.goto(f"chrome-extension://{ext_id}/popup.html")
        await pop.wait_for_timeout(2500)
        print("4) popup:", (await pop.locator("#conectado").inner_text()), "| entrar visível:", await pop.locator("#entrar").is_visible())
        assert not await pop.locator("#senha").is_visible()
        await pop.screenshot(path=str(OUT / "extensao_conectado.png"))
        await pop.close()
        # envio de um anúncio pelo botão da página
        await ctx.route("https://resizedimgs.zapimoveis.com.br/**", lambda r: r.fulfill(status=200, body=foto(), content_type="image/jpeg"))
        await ctx.route("https://www.zapimoveis.com.br/**", lambda r: r.fulfill(status=200, body=HTML, content_type="text/html; charset=utf-8"))
        pg = await ctx.new_page()
        await pg.goto(ANUNCIO)
        await pg.locator("#jdb-enviar").wait_for(state="attached", timeout=15000)
        await pg.wait_for_timeout(1500)
        await pg.mouse.click(1280 - 16 - 90, 800 - 16 - 24)
        await pg.wait_for_timeout(2500)
        await pg.mouse.click(1280 - 16 - 160, 800 - 16 - 60 - 60)
        await pg.wait_for_timeout(12000)
        depois = c.get(f"/jobs/{jid}").json()["candidatos"]
        print("5) envio aceito:", len(depois) >= antes, "| candidatos", antes, "->", len(depois),
              "| último:", [(x["n"], x["preco"], bool(x["foto"]), x["fonte_coleta"]) for x in depois[-1:]])
        assert any(x["preco"] == 480000 and x["foto"] and x["fonte_coleta"] == "avaliador" for x in depois), depois
        # segurança: página que não é do JdB não entrega sessão
        falso = await sw.evaluate("(id) => guardarSessao({ id, url: 'https://www.zapimoveis.com.br/x', tab: { url: 'https://www.zapimoveis.com.br/x' } }, 'abc')", ext_id)
        print("6) portal tentando entregar sessão aceito?", falso)
        assert falso is False
        # sem sessão guardada + JdB já aberto (como ao instalar com o JdB aberto): procura a aba e se liga
        await sw.evaluate("() => chrome.storage.local.remove('jdb_token')")
        achou = await sw.evaluate("() => procurarAba()")
        await app.wait_for_timeout(1500)
        print("7) ao instalar com o JdB já aberto: abas achadas", achou, "| ligada:",
              bool((await sw.evaluate("() => chrome.storage.local.get('jdb_token')")).get("jdb_token")))
        # saiu do JdB -> desliga
        await app.evaluate("() => localStorage.removeItem('jdb_token')")
        await app.wait_for_timeout(4000)
        print("8) saiu do JdB: ligada?", bool((await sw.evaluate("() => chrome.storage.local.get('jdb_token')")).get("jdb_token")))
        pop = await ctx.new_page()
        await pop.set_viewport_size({"width": 360, "height": 420})
        await pop.goto(f"chrome-extension://{ext_id}/popup.html")
        await pop.wait_for_timeout(2500)
        print("9) popup sem JdB: entrar visível", await pop.locator("#entrar").is_visible(), "| senha visível:", await pop.locator("#senha").is_visible())
        await pop.screenshot(path=str(OUT / "extensao_abra_o_jdb.png"))
        await ctx.close()
    shutil.rmtree(perfil, ignore_errors=True)

if __name__ == "__main__":
    asyncio.run(main())
