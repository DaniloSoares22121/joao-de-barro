"""ORDEM 019: o extrator lê os cartões de uma página de RESULTADOS de busca (textContent: pega
também cartão ainda escondido/virtualizado, onde innerText volta vazio)."""
import asyncio
from pathlib import Path

HTML = """<!doctype html><html><body>
<div class="card"><a href="https://www.zapimoveis.com.br/imovel/galpao-1/">Galpão</a>
  <p>Galpão para comprar com 2.000 m² em Polo Empresarial Goiás, Aparecida de Goiânia</p><b>R$ 5.000.000</b></div>
<div class="card" style="display:none"><a href="https://www.zapimoveis.com.br/imovel/galpao-2/">Galpão</a>
  <p>Galpão para comprar com 1.800 m² em Polo Empresarial Goiás, Aparecida de Goiânia</p><b>R$ 4.600.000</b></div>
<div><a href="https://www.zapimoveis.com.br/venda/galpao/">Filtros da busca</a></div>
</body></html>"""


async def main():
    from playwright.async_api import async_playwright
    pasta = Path(__file__).parent
    pagina = pasta / "_resultados.html"
    pagina.write_text(HTML, encoding="utf-8")
    async with async_playwright() as pw:
        b = await pw.chromium.launch(channel="chrome", headless=True)
        pg = await b.new_page()
        await pg.goto(pagina.as_uri())
        await pg.add_script_tag(path=str(pasta.parent / "extrator.js"))
        r = await pg.evaluate("window.__jdbCartoes()")
        await b.close()
    pagina.unlink()
    links = [c["link"] for c in r["cartoes"]]
    assert links[:2] == ["https://www.zapimoveis.com.br/imovel/galpao-1/",
                         "https://www.zapimoveis.com.br/imovel/galpao-2/"], links
    assert "R$ 4.600.000" in r["cartoes"][1]["texto"]      # cartão escondido: textContent
    # link que não é anúncio (filtro da busca) pode vir: o servidor descarta (eh_anuncio)
    print(f"OK: {len(links)} cartões lidos, inclusive o escondido")

asyncio.run(main())
