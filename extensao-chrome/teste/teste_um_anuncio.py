"""ORDEM 029-5: "Enviar este anúncio" (extensão 1.0.3) com página SALVA (sem portal real, sem IA).
Abre a página de exemplo no Chrome sem janela, roda o extrator.js, faz o MESMO recorte da foto
principal que o popup.js faz (função `recortar` copiada do popup) e manda ao sistema, num
trabalho de teste em pasta temporária, um referencial que já estava na lista sem foto.

Rodar: backend/.venv/Scripts/python.exe extensao-chrome/teste/teste_um_anuncio.py"""
import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

EXT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXT.parent / "backend"))
os.environ["LOVABLE_DATA_DIR"] = tempfile.mkdtemp()
os.environ["LOVABLE_CLAUDE_CLI"] = r"C:\nao-existe\claude.exe"   # sem IA (custa dinheiro)
sys.stdout.reconfigure(encoding="utf-8")

LINK = "https://www.zapimoveis.com.br/imovel/venda-galpao-polo-empresarial-goias-teste-1/"
HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Galpão 2.100 m²</title></head>
<body style="font-family:Arial;margin:0">
<header style="height:60px;background:#eee"><img src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='40'/>" width="120" height="40" alt="logo"></header>
<div style="display:flex;gap:16px;padding:16px">
  <img id="principal" width="640" height="420" alt="foto" src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='640' height='420'><rect width='640' height='420' fill='%23c0392b'/></svg>">
  <img width="150" height="100" alt="mini" src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='150' height='100'><rect width='150' height='100' fill='%232c3e50'/></svg>">
</div>
<h1>Galpão em condomínio – Polo Empresarial Goiás</h1>
<p>R$ 5.200.000</p><p>Área construída 2.100 m² · Terreno 4.000 m²</p>
<p>Condomínio R$ 1.500</p>
</body></html>"""


async def ler_pagina():
    from playwright.async_api import async_playwright
    popup = (EXT / "popup.js").read_text(encoding="utf-8")
    recortar = re.search(r"async function recortar\(imagem, ret\) \{.*?\n\}\n", popup, re.S).group(0)
    pasta = Path(tempfile.mkdtemp())
    pagina = pasta / "anuncio.html"
    pagina.write_text(HTML, encoding="utf-8")
    async with async_playwright() as pw:
        b = await pw.chromium.launch(channel="chrome", headless=True)
        pg = await b.new_page(viewport={"width": 1100, "height": 760})
        await pg.goto(pagina.as_uri())
        await pg.add_script_tag(path=str(EXT / "extrator.js"))
        d = await pg.evaluate("window.__jdbExtrair()")
        tela = await pg.screenshot(type="jpeg", quality=80)
        import base64
        imagem = "data:image/jpeg;base64," + base64.b64encode(tela).decode()
        foto = await pg.evaluate(f"(async () => {{ {recortar}; return await recortar(arguments[0], arguments[1]) }})"
                                 .replace("arguments[0], arguments[1]", "a.imagem, a.ret")
                                 .replace("async () =>", "async (a) =>"), {"imagem": imagem, "ret": d["foto_rect"]})
        await b.close()
    return d, imagem, foto


def main():
    from datetime import date

    from PIL import Image

    from lovable.avaliacao import db, routes
    from lovable.avaliacao.modelos import Referencial, Trabalho
    import json
    import subprocess
    saida = Path(tempfile.mkdtemp()) / "pagina.json"
    coletor_py = EXT.parent / "coletor" / ".venv" / "Scripts" / "python.exe"   # tem o Playwright
    subprocess.run([str(coletor_py), __file__, "--pagina", str(saida)], check=True)
    d, imagem, foto = json.loads(saida.read_text(encoding="utf-8"))
    print("extrator:", {k: d[k] for k in ("preco", "area_m2", "lote_m2")}, "foto_rect:", d["foto_rect"])
    assert d["foto_rect"] and round(d["foto_rect"]["w"]) == 640, d["foto_rect"]
    assert foto.startswith("data:image/jpeg;base64,"), foto[:40]

    db.init()
    jid = db.criar_job(Trabalho(id="", numero=99029, modalidade="OV", finalidade="Venda", cliente="Teste",
                                tipo="Galpão comercial", bairro="Polo Empresarial Goiás",
                                cidade="Aparecida de Goiânia", pin_maps="", data_base=date(2026, 11, 13),
                                data_vistoria=date(2026, 11, 13)))
    db.salvar_candidatos(jid, [Referencial(
        n=1, link=LINK, portal="ZAP Imóveis", bairro="Polo Empresarial Goiás", tipologia="Galpão",
        padrao="", idade_aparente="", area_m2=2000, preco=5_000_000, escolhido=True, decisao="entra",
        descricao="Padrão e idade a conferir no anúncio.", bloqueado=True)])
    d.pop("foto_rect")
    d["link"] = LINK
    body = routes.AnuncioEnviado(**d, imagem=imagem, foto_principal=foto)
    r = asyncio.run(routes.anuncio_enviado(jid, body, _u={}))
    print("resposta:", r)
    c = db.candidatos(jid)
    assert len(c) == 1 and r["atualizado"] and c[0].escolhido
    c = c[0]
    im = Image.open(db.pasta(jid) / c.foto).convert("RGB")
    cor = im.getpixel((im.width // 2, im.height // 2))
    print("foto gravada:", c.foto, im.size, "cor no centro:", cor, "| print:", c.print_)
    assert abs(im.width - 640) <= 2 and abs(im.height - 420) <= 2, im.size
    assert cor[0] > 150 and cor[1] < 90 and cor[2] < 90, cor   # é o recorte da foto vermelha
    assert (c.preco, c.area_m2, c.lote_m2) == (5_200_000, 2100, 4000), (c.preco, c.area_m2, c.lote_m2)
    assert c.coletado and not c.bloqueado and "a conferir" not in c.descricao
    print("OK: referencial nº 1 completado com a foto principal e os dados da página")


if len(sys.argv) == 3 and sys.argv[1] == "--pagina":
    import json
    Path(sys.argv[2]).write_text(json.dumps(asyncio.run(ler_pagina())), encoding="utf-8")
else:
    main()
