"""Operações de imagem: demarcação, recorte, tarja e rasterização de PDF."""
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageOps

VERMELHO = "#E00000"
LARGURA_CONTORNO = 6


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


def tarjar(img: Path, caixas: list[tuple[int, int, int, int]], destino: Path) -> Path:
    """Cobre cada caixa com um retângulo preto sólido."""
    im = _abrir(img)
    d = ImageDraw.Draw(im)
    for x0, y0, x1, y1 in caixas:
        d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=(0, 0, 0))
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
LADO_MAX = 3000          # px: acima disso a foto é reduzida (o laudo não ganha nada com mais)
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
