"""ORDEM 077-1(b) / D-077 / ORDEM 107: print do Mapa Digital Fácil (Prefeitura de Goiânia) no padrão do PTAM 122 (pág. 23).

Roda com o Python do Coletor (Playwright), chamado pelo servidor do JdB:
    python mapa_digital.py <entrada.json> <saida.png>
entrada.json: {"anel": [[x, y], ...] (SIRGAS 2000 / UTM 22S, EPSG 31982), "area": "286,09", "lados_seg": [...],
               "quadra": "59", "lote": "02", "area_origem": "planta", "consultado_em": "dd/mm/aaaa hh:mm",
               "plano": {"centro": [x, y], "res": 0.26, "canto": "ie"} (o enquadramento escolhido pelo servidor)}

O que sai (107):
1. no alto, a faixa com o endereço do site (sem as abas do navegador) e a hora da consulta;
2. o mapa do site no zoom em que se leem o nome da rua do avaliando e o de uma vizinha (e do setor, se couber),
   sem os botões do site; o lote PREENCHIDO (laranja, contorno vermelho);
3. o QUADRO DE ZOOM num canto livre: "Quadra 59 – Lote 2", "Área: 286,09 m²" em vermelho, o recorte ampliado da
   planta (lotes vizinhos e números) com o lote preenchido e a medida de cada lado em etiqueta junto do lado,
   e uma linha vermelha ligando o quadro ao lote.
Se o site pedir verificação (captcha), PARA e avisa (saída 3). Nada de contorno.
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

SITE = "https://portalmapa.goiania.go.gov.br/mapafacil/"
BASICO = "https://portalmapa.goiania.go.gov.br/servicogyn/rest/services/MapaServer/Mapa_Basico3/MapServer"
LARG, ALT = 1366, 860
CAIXA = (500, 470)
TOPO = 66                   # altura do título do quadro (quadra/lote e área)
FUNDO = (238, 238, 238)     # o cinza do Mapa Digital Fácil

JS_LIMPAR = """() => {
  const m = window._viewerMap
  const lay = document.getElementById(m.id + '_layers') || m.root
  const fica = (el) => el === lay || el.contains(lay) || lay.contains(el)
  document.querySelectorAll('body *').forEach((el) => { if (!fica(el)) el.style.visibility = 'hidden' })
  document.body.style.background = '#eeeeee'
}"""

JS_EXTENSAO = """(e) => new Promise((ok) => {
  const m = window._viewerMap
  const Ext = m.extent.constructor
  const h = m.on('extent-change', () => { h.remove(); setTimeout(ok, 300) })
  m.setExtent(new Ext({ xmin: e[0], ymin: e[1], xmax: e[2], ymax: e[3], spatialReference: m.spatialReference }))
  setTimeout(ok, 8000)
})"""

JS_DESENHAR = """(d) => {
  const m = window._viewerMap
  const r0 = (document.getElementById(m.id) || m.root).getBoundingClientRect()
  const e = m.extent, w = m.width, h = m.height
  const tela = ([x, y]) => [r0.left + (x - e.xmin) / (e.xmax - e.xmin) * w, r0.top + (e.ymax - y) / (e.ymax - e.ymin) * h]
  const pts = d.anel.map(tela)
  const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length, cy = pts.reduce((s, p) => s + p[1], 0) / pts.length
  const [cw, ch] = d.caixa, M = 16
  const bx = d.canto[1] === 'e' ? M : innerWidth - M - cw, by = d.canto[0] === 's' ? M : innerHeight - M - ch
  const ns = 'http://www.w3.org/2000/svg'
  const svg = document.createElementNS(ns, 'svg')
  svg.setAttribute('style', `position:fixed;left:0;top:0;width:${innerWidth}px;height:${innerHeight}px;z-index:9999;pointer-events:none`)
  const el = (t, a, pai) => { const x = document.createElementNS(ns, t); for (const k in a) x.setAttribute(k, a[k]); (pai || svg).appendChild(x); return x }
  el('polygon', { points: pts.map((p) => p.join(',')).join(' '), fill: 'rgba(244,164,96,0.92)', stroke: '#d10000', 'stroke-width': 2.5 })
  // a linha vermelha do quadro ao lote: do canto do quadro mais perto do lote
  const cantos = [[bx, by], [bx + cw, by], [bx, by + ch], [bx + cw, by + ch]]
  const k = cantos.reduce((a, c) => (Math.hypot(c[0] - cx, c[1] - cy) < Math.hypot(a[0] - cx, a[1] - cy) ? c : a))
  el('line', { x1: k[0], y1: k[1], x2: cx, y2: cy, stroke: '#c00000', 'stroke-width': 1.6 })
  document.body.appendChild(svg)
  // o quadro de zoom
  const q = document.createElement('div')
  q.setAttribute('style', `position:fixed;left:${bx}px;top:${by}px;width:${cw}px;height:${ch}px;z-index:10000;box-sizing:border-box;` +
    'background:#fff;border:3px solid #c00000;overflow:hidden;font-family:Arial,Helvetica,sans-serif')
  q.innerHTML = `<div style="height:${d.topo}px;box-sizing:border-box;padding:8px 0 0;text-align:center;border-bottom:1px solid #ddd">` +
    `<div style="font-size:21px;font-weight:700;color:#111">${d.titulo}</div>` +
    `<div style="font-size:20px;font-weight:700;color:#c00000;margin-top:3px">${d.area_txt}</div></div>` +
    `<div style="position:relative;width:${d.det.w}px;height:${d.det.h}px;background:#eeeeee">` +
    `<img src="data:image/png;base64,${d.det.png}" style="position:absolute;left:0;top:0;width:${d.det.w}px;height:${d.det.h}px">` +
    `<svg style="position:absolute;left:0;top:0;width:${d.det.w}px;height:${d.det.h}px" xmlns="${ns}">` +
    `<polygon points="${d.det.anel.map((p) => p.join(',')).join(' ')}" fill="rgba(244,164,96,0.82)" stroke="#d10000" stroke-width="4"/></svg>` +
    d.det.lados.map((s) => `<div style="position:absolute;left:${s.x}px;top:${s.y}px;transform:translate(-50%,-50%);background:#fff;` +
      'border:2px solid #b00000;padding:1px 5px;font-size:18px;font-weight:700;color:#7a0000;white-space:nowrap">' + s.txt + '</div>').join('') +
    '</div>'
  document.body.appendChild(q)
  return { cx, cy, bx, by }
}"""


def numero_lote(v) -> str:
    return str(v or "").strip().lstrip("0") or str(v or "").strip()


def area_txt(d: dict) -> str:
    """107-b: no quadro, a área da planta (Divisas de Lote); a do cadastro fica só na legenda do laudo."""
    if d.get("area_origem", "planta") == "planta":
        return f"Área: {d.get('area')} m²"
    return f"Área (cadastro imobiliário): {d.get('area')} m²"


def titulo(d: dict) -> str:
    t = f"Quadra {str(d.get('quadra') or '').strip()} – Lote {numero_lote(d.get('lote'))}"
    if d.get("setor_no_titulo") and d.get("bairro"):          # 109-1: o nome do setor não coube no mapa
        t += f" · {d['bairro']}"
    return t


def detalhe(anel, lados_seg, w: int, h: int, ocupa: float = 0.5) -> dict:
    """O recorte ampliado: a extensão (UTM) com o lote no meio ocupando ~metade do quadro; o lote e as etiquetas dos
    lados em pixels do recorte (cada etiqueta fora do lote, junto do meio do seu lado)."""
    xs, ys = [p[0] for p in anel], [p[1] for p in anel]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    res = max((max(xs) - min(xs)) / (ocupa * w), (max(ys) - min(ys)) / (ocupa * h))
    ext = (cx - w / 2 * res, cy - h / 2 * res, cx + w / 2 * res, cy + h / 2 * res)
    px = lambda p: [round((p[0] - ext[0]) / res, 1), round((ext[3] - p[1]) / res, 1)]
    pts = [px(p) for p in anel]
    mx, my = w / 2, h / 2
    lados = []
    for s in lados_seg or []:
        a, b = px(s["a"]), px(s["b"])
        m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        nx, ny = -(b[1] - a[1]), b[0] - a[0]
        n = math.hypot(nx, ny) or 1
        nx, ny = nx / n, ny / n
        if (m[0] - mx) * nx + (m[1] - my) * ny < 0:
            nx, ny = -nx, -ny
        x = min(max(m[0] + nx * 34, 50), w - 50)
        y = min(max(m[1] + ny * 22, 16), h - 16)
        lados.append({"x": round(x, 1), "y": round(y, 1), "txt": s["txt"]})
    return {"ext": ext, "res": res, "anel": pts, "lados": lados, "w": w, "h": h}


async def _exportar(pg, ext, w: int, h: int) -> bytes:
    """A planta do mapa básico (lotes e números) no recorte, sobre o cinza do site (pedida pelo mesmo navegador)."""
    q = urllib.parse.urlencode({"bbox": ",".join(f"{v:.3f}" for v in ext), "bboxSR": 31982, "imageSR": 31982,
                                "size": f"{w},{h}", "format": "png32", "transparent": "true",
                                "layers": "show:311,196,195", "dpi": 96, "f": "image"})
    r = await pg.request.get(f"{BASICO}/export?{q}", timeout=60_000)
    if not r.ok:
        raise RuntimeError(f"recorte da planta: HTTP {r.status}")
    dados = await r.body()
    from io import BytesIO
    from PIL import Image
    im = Image.open(BytesIO(dados)).convert("RGBA")
    fundo = Image.new("RGBA", im.size, FUNDO + (255,))
    fundo.alpha_composite(im)
    out = BytesIO()
    fundo.convert("RGB").save(out, "PNG")
    return out.getvalue()


def _faixa_endereco(png: Path, url: str, quando: str = "") -> None:
    """A faixa do endereço do site e da consulta, no alto do print (sem as abas do navegador)."""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.open(png).convert("RGB")
    alto = 44
    out = Image.new("RGB", (im.width, im.height + alto), (241, 243, 244))
    out.paste(im, (0, alto))
    d = ImageDraw.Draw(out)
    d.rounded_rectangle((12, 7, im.width - 12, alto - 7), radius=15, fill=(255, 255, 255), outline=(218, 220, 224))
    try:
        f = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        f = ImageFont.load_default()
    agora = quando or datetime.now(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M")   # Brasília
    d.rounded_rectangle((28, 20, 40, 31), radius=2, fill=(95, 99, 104))          # cadeado desenhado
    d.arc((30, 13, 38, 25), 180, 360, fill=(95, 99, 104), width=2)
    d.text((50, 12), url.replace("https://", ""), fill=(32, 33, 36), font=f)
    t = f"consultado em {agora} (Brasília)"
    d.text((im.width - 28 - d.textlength(t, font=f), 12), t, fill=(95, 99, 104), font=f)
    out.save(png)


async def capturar(d: dict, saida: Path) -> int:
    from playwright.async_api import async_playwright
    xs, ys = [p[0] for p in d["anel"]], [p[1] for p in d["anel"]]
    plano = d.get("plano") or {}
    res = float(plano.get("res") or 0.2645838625010584)
    X, Y = plano.get("centro") or [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]
    ext = (X - LARG / 2 * res, Y - ALT / 2 * res, X + LARG / 2 * res, Y + ALT / 2 * res)
    cw, ch = CAIXA
    det = detalhe(d["anel"], d.get("lados_seg") or [], cw - 6, ch - 6 - TOPO)
    url = f"{SITE}?extent={ext[0]:.1f},{ext[1]:.1f},{ext[2]:.1f},{ext[3]:.1f},31982"
    async with async_playwright() as pw:
        b = await pw.chromium.launch(channel="chromium", headless=True)
        pg = await b.new_page(viewport={"width": LARG, "height": ALT}, locale="pt-BR")
        await pg.goto(url, timeout=90_000)
        await pg.wait_for_function("() => window._viewerMap && window._viewerMap.loaded", timeout=60_000)
        await pg.wait_for_timeout(5000)
        corpo = (await pg.evaluate("document.body.innerText.slice(0, 3000)")).lower()
        if any(k in corpo for k in ("captcha", "não sou um robô", "verify you are human", "verifique que você")):
            await b.close()
            return 3
        for t in ("OK", "Ok", "Fechar", "Entendi"):             # a janela inicial do site, se aparecer
            bt = pg.get_by_role("button", name=t)
            if await bt.count():
                try:
                    await bt.first.click(timeout=2000)
                except Exception:
                    pass
        det["png"] = base64.b64encode(await _exportar(pg, det["ext"], det["w"], det["h"])).decode()
        await pg.evaluate(JS_EXTENSAO, list(ext))              # o enquadramento exato (centro e escala do plano)
        await pg.evaluate("() => new Promise((ok) => { const m = window._viewerMap; if (!m.updating) return ok(); "
                          "const h = m.on('update-end', () => { h.remove(); ok() }); setTimeout(ok, 15000) })")
        await pg.wait_for_timeout(2500)
        await pg.evaluate(JS_LIMPAR)                           # sem os botões e a busca do site
        await pg.evaluate(JS_DESENHAR, {"anel": d["anel"], "canto": plano.get("canto") or "sd", "caixa": list(CAIXA),
                                        "topo": TOPO, "titulo": titulo(d), "area_txt": area_txt(d),
                                        "det": {k: det[k] for k in ("png", "anel", "lados", "w", "h")}})
        await pg.wait_for_timeout(600)
        await pg.screenshot(path=str(saida))
        await b.close()
    _faixa_endereco(saida, SITE, d.get("consultado_em", ""))
    return 0


def main() -> int:
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    return asyncio.run(capturar(d, Path(sys.argv[2])))


if __name__ == "__main__":
    sys.exit(main())
