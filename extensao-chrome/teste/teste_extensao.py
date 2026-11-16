"""ORDEM 010 D: testa a extensão sem instalá-la — abre a página de anúncio SIMULADA, roda o
extrator.js da extensão nela, captura a tela e manda ao sistema pela mesma rota que o
popup usa. Confere se o referencial chega ao trabalho como escolhido "enviado pelo avaliador"."""
import asyncio, base64, json, sys
from pathlib import Path
import httpx
sys.stdout.reconfigure(encoding="utf-8")
EXT = Path(r"C:\Users\DELL\joao-de-barro\extensao-chrome")
# ORDEM 046: este teste CRIA trabalho no servidor. Nunca no servidor real (8866, banco do Alan):
# suba um servidor de teste com LOVABLE_DATA_DIR temporário e passe JDB_TESTE_SERVIDOR=http://127.0.0.1:<porta>
import os
SERVIDOR = os.environ.get("JDB_TESTE_SERVIDOR", "").rstrip("/")
if not SERVIDOR or SERVIDOR.endswith(":8866"):
    sys.exit("TRAVA (ORDEM 046): defina JDB_TESTE_SERVIDOR com um servidor de TESTE (banco temporário); "
             "o 8866 é o banco real do Alan. Nada foi enviado.")
API = SERVIDOR + "/api/avaliacao"


async def main():
    from playwright.async_api import async_playwright
    c = httpx.Client(timeout=60)
    tk = c.post(SERVIDOR + "/api/auth/login",
                json={"email": "avaliador@local", "password": "joaodebarro"}).json()["token"]
    c.headers["Authorization"] = f"Bearer {tk}"
    jid = c.post(f"{API}/jobs", json={
        "numero": 9905, "modalidade": "OV", "finalidade": "Venda.", "cliente": "Teste Extensao",
        "tipo": "Sobrado residencial", "bairro": "Jardim Vila Boa", "cidade": "Goiânia",
        "pin_maps": "https://maps.app.goo.gl/teste123", "data_base": "2026-11-11",
        "data_vistoria": "2026-11-11"}).json()["id"]
    async with async_playwright() as pw:
        b = await pw.chromium.launch(channel="chrome", headless=True)
        pg = await b.new_page(viewport={"width": 1200, "height": 800})
        await pg.goto((EXT / "teste" / "anuncio_exemplo.html").as_uri())
        await pg.add_script_tag(path=str(EXT / "extrator.js"))
        d = await pg.evaluate("window.__jdbExtrair()")
        img = await pg.screenshot(type="jpeg", quality=70)
        await b.close()
    print("lido da página:", json.dumps({k: v for k, v in d.items() if k != "texto"}, ensure_ascii=False))
    d["imagem"] = "data:image/jpeg;base64," + base64.b64encode(img).decode()
    d["link"] = "https://www.exemplo-portal.com.br/imovel/sobrado-3-quartos-jardim-vila-boa-123456"
    r = c.post(f"{API}/jobs/{jid}/candidatos/enviado", json=d)
    print("envio:", r.status_code, r.text[:300])
    r2 = c.post(f"{API}/jobs/{jid}/candidatos/enviado", json=d)
    print("reenvio do mesmo anúncio:", r2.status_code, r2.json().get("detail"))
    cand = c.get(f"{API}/jobs/{jid}").json()["candidatos"]
    x = cand[0]
    print("no trabalho:", {k: x.get(k) for k in ("n", "portal", "area_m2", "lote_m2", "preco", "quartos", "suites",
                                                   "decisao", "fonte_coleta", "coletado", "foto", "observacao")})
    print("excluir teste:", c.delete(f"{API}/jobs/{jid}").status_code)

asyncio.run(main())
