"""Operações de imagem: demarcação, recorte, tarja e rasterização de PDF."""
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageOps

VERMELHO = "#E00000"
LARGURA_CONTORNO = 3      # 117 (D-130): contorno fino sobre o lote (era 6)


def _abrir(img: Path) -> Image.Image:
    """Abre a imagem respeitando a orientação EXIF (fotos de celular)."""
    im = Image.open(img)
    im = ImageOps.exif_transpose(im)
    return im.convert("RGB")


def _salvar(im: Image.Image, destino: Path) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    im.save(destino)
    return destino


def demarcar(img: Path, poligono: list[tuple[int, int]], destino: Path) -> Path:
    """Desenha o contorno vermelho (#E00000, 6 px) do polígono."""
    im = _abrir(img)
    pts = [tuple(p) for p in poligono]
    if len(pts) >= 2:
        ImageDraw.Draw(im).line(pts + [pts[0]], fill=VERMELHO, width=LARGURA_CONTORNO, joint="curve")
    return _salvar(im, destino)


def recortar(img: Path, caixa: tuple[int, int, int, int], destino: Path) -> Path:
    """Recorta a caixa (x0, y0, x1, y1) em pixels da imagem original."""
    return _salvar(_abrir(img).crop(tuple(caixa)), destino)


def girar(img: Path, graus: int, destino: Path) -> Path:
    """Gira no sentido horário (0/90/180/270) — documento fotografado deitado vai ao anexo
    em posição de leitura."""
    g = int(graus or 0) % 360
    if g not in (90, 180, 270):
        return img
    return _salvar(_abrir(img).rotate(-g, expand=True), destino)


def _pino(im: Image.Image, x_min: int) -> tuple[int, int] | None:
    """Ponta do marcador vermelho do Google Maps (#EA4335): base do maior grupo de pixels
    vermelhos à direita de `x_min`. None se não houver marcador."""
    px = im.load()
    w, h = im.size
    pts = [(x, y) for y in range(0, h, 2) for x in range(x_min, w, 2)
           if (lambda r, g, b: r > 190 and g < 95 and b < 90 and r - g > 120)(*px[x, y][:3])]
    if len(pts) < 8:
        return None
    xs = sorted(p[0] for p in pts)
    xm = xs[len(xs) // 2]
    perto = [p for p in pts if abs(p[0] - xm) <= 18]
    ym = sorted(p[1] for p in perto)[len(perto) // 2]
    perto = [p for p in perto if abs(p[1] - ym) <= 30]
    if not perto:
        return None
    return xm, max(p[1] for p in perto) + 4


def _fim_painel(im: Image.Image) -> int:
    """x onde termina o painel lateral branco do Google Maps (0 se não houver)."""
    g = im.convert("L")
    w, h = g.size
    px = g.load()
    fim = 0
    for x in range(0, w // 2, 4):
        brancos = sum(1 for y in range(80, h - 80, 8) if px[x, y] > 238)
        if brancos / max(1, len(range(80, h - 80, 8))) > 0.55:
            fim = x
    return fim + 45 if fim else 0   # + botão "<" de recolher o painel, colado na borda


MARGEM_MAPA_PX, MARGEM_MAPA_FRACAO = 40, 0.20   # ORDEM 032-4: folga mínima em volta do contorno


def recortar_mapa(img: Path, poligono: list, destino: Path,
                  proporcao: float = 1.5, avisos: list | None = None) -> tuple[Path, list]:
    """Print do Google Maps -> só a imagem de satélite em volta do pino, sem a interface
    (painel lateral, barra de busca, botões, rodapé). Devolve o recorte e o polígono do lote
    em coordenadas do recorte."""
    im = _abrir(img)
    w, h = im.size
    x_min = _fim_painel(im)
    topo, base = int(h * 0.09), int(h * 0.94)          # barra de busca/chips e rodapé
    dir_ = int(w * 0.965)                               # coluna dos botões de zoom
    pino = _pino(im, x_min)
    if poligono:
        xs, ys = [p[0] for p in poligono], [p[1] for p in poligono]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    elif pino:
        cx, cy = pino[0], pino[1] - 20
    else:
        cx, cy = (x_min + dir_) / 2, (topo + base) / 2
    alt_max = min(base - topo, int((dir_ - x_min) / proporcao))
    alt = min(alt_max, 460)
    if poligono:
        # ORDEM 032-4: o recorte cresce até caber o contorno com folga (nunca colado na borda)
        pw, ph = max(xs) - min(xs), max(ys) - min(ys)
        m = max(MARGEM_MAPA_PX, MARGEM_MAPA_FRACAO * max(pw, ph))
        alt = int(min(alt_max, max(alt, ph + 2 * m, (pw + 2 * m) / proporcao)))
        if avisos is not None and (min(xs) - m < x_min or max(xs) + m > dir_
                                   or min(ys) - m < topo or max(ys) + m > base):
            avisos.append("o contorno do lote passa por baixo da interface do Google Maps (painel "
                          "lateral, busca ou botões) e sai cortado no 7.1: refaça a captura do "
                          "mapa com o Coletor (o painel é recolhido) e confira o contorno")
    larg = int(alt * proporcao)
    x0 = int(min(max(cx - larg / 2, x_min), dir_ - larg))
    y0 = int(min(max(cy - alt / 2, topo), base - alt))
    x0, y0 = max(x0, 0), max(y0, 0)
    corte = im.crop((x0, y0, x0 + larg, y0 + alt))
    pol = [[int(p[0] - x0), int(p[1] - y0)] for p in poligono or []]
    return _salvar(corte, destino), pol


def tarjar(img: Path, caixas: list[tuple[int, int, int, int]], destino: Path) -> Path:
    """Cobre cada caixa com um retângulo preto sólido."""
    im = _abrir(img)
    d = ImageDraw.Draw(im)
    for x0, y0, x1, y1 in caixas:
        d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=(0, 0, 0))
    return _salvar(im, destino)


def borrar(img: Path, caixas: list[tuple[int, int, int, int]], destino: Path) -> Path:
    """Fotos (pessoa, placa de carro): pixeliza a área em vez do quadrado preto — preserva a
    privacidade sem um borrão preto no meio da capa/foto."""
    im = _abrir(img)
    for x0, y0, x1, y1 in caixas:
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        reg = im.crop((x0, y0, x1, y1))
        bloco = max(6, min(x1 - x0, y1 - y0) // 6)
        peq = reg.resize((max(1, (x1 - x0) // bloco), max(1, (y1 - y0) // bloco)), Image.BILINEAR)
        im.paste(peq.resize(reg.size, Image.NEAREST), (x0, y0))
    return _salvar(im, destino)


def pdf_paginas_png(pdf: Path, pasta: Path, dpi: int = 110) -> list[Path]:
    """Renderiza cada página do PDF em PNG dentro de `pasta`."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    saidas: list[Path] = []
    with pymupdf.open(pdf) as doc:
        for i, pagina in enumerate(doc, start=1):
            destino = pasta / f"pagina-{i:02d}.png"
            pagina.get_pixmap(dpi=dpi).save(destino)
            saidas.append(destino)
    return saidas


# ------------------------------------------------------------------ normalização no envio
EXT_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic",
              ".heif", ".avif"}
LADO_MAX = 1600          # px: foto reduzida no envio (a IA lê menos e o laudo usa ≤ 1.200 px)
QUALIDADE_JPEG = 90


class ImagemInvalida(ValueError):
    """O arquivo tem extensão de imagem mas não abre (corrompido ou formato sem suporte)."""


def normalizar(origem: Path) -> bool:
    """Deixa a imagem enviada num formato que TODO o pipeline entende, regravando no
    próprio arquivo como JPEG quando preciso. Devolve True se regravou (o chamador troca a
    extensão para .jpg).

    Uma vez só, na entrada: orientação EXIF aplicada nos pixels (tarja e demarcação são
    desenhadas em coordenadas da imagem já girada; com o EXIF pendurado elas caíam no lugar
    errado), formato que o Word aceita (webp/heic/avif derrubavam a montagem) e lado máximo.
    JPEG/PNG já corretos ficam intocados. Levanta ImagemInvalida se não abrir."""
    origem = Path(origem)
    try:
        with Image.open(origem) as im:
            im.load()
            formato = (im.format or "").upper()
            orientacao = im.getexif().get(0x0112, 1)
            if (formato in ("JPEG", "PNG") and orientacao in (1, None)
                    and max(im.size) <= LADO_MAX and im.mode in ("RGB", "L")):
                return False
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                fundo = Image.new("RGB", im.size, (255, 255, 255))
                fundo.paste(im, mask=im.split()[-1])
                im = fundo
            else:
                im = im.convert("RGB")
            if max(im.size) > LADO_MAX:
                im.thumbnail((LADO_MAX, LADO_MAX), Image.LANCZOS)
            tmp = origem.with_name(origem.name + ".norm")
            im.save(tmp, "JPEG", quality=QUALIDADE_JPEG, optimize=True)
    except ImagemInvalida:
        raise
    except Exception as e:  # PIL levanta de tudo: UnidentifiedImageError, OSError, DecompressionBomb…
        raise ImagemInvalida(str(e) or type(e).__name__) from e
    tmp.replace(origem)
    return True
