"""Cópias dos arquivos do trabalho para a IA (ORDEM 013).

A API recusa (400) imagem acima de 5 MB ou 8000 px, pedido com mais de 20 imagens se alguma
passar de 2000 px e pedido acima de 32 MB. O original fica intocado para o laudo; a IA lê
só as cópias de `<job>/_ia/`:
  - imagem: lado maior ≤ LADO_IA, JPEG qualidade QUALIDADE, rotação do EXIF aplicada e EXIF
    removido (sem GPS);
  - PDF: cada página em JPEG a no máximo DPI_PDF e ≤ LADO_IA;
  - texto (.txt/.md/.csv/.json): vai como está;
  - outro formato (.cdr, .zip, .docx…): não vai à IA ("arquivo ignorado").
No máximo MAX_IMAGENS imagens por chamada (quem chama divide em lotes).
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps

LADO_IA = 1568          # px: a API reduz para isso internamente; maior só gasta banda
QUALIDADE = 80
DPI_PDF = 150
MAX_IMAGENS = 20
MAX_BYTES_IMAGEM = 4_500_000   # folga sob o limite de 5 MB da API
PASTA = "_ia"

EXT_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic",
              ".heif", ".avif"}
EXT_TEXTO = {".txt", ".md", ".csv", ".json"}

Image.MAX_IMAGE_PIXELS = 200_000_000   # foto de 100+ MP de celular não é "bomba"


@dataclass(frozen=True)
class ItemIA:
    """Um arquivo que a IA lê. `escala` converte coordenadas: original = ia / escala.
    Para página de PDF, `pagina` é o nº (1…) e a escala é px por ponto PDF."""
    original: str           # caminho relativo do arquivo do trabalho
    ia: str                 # caminho relativo do que a IA lê
    escala: float = 1.0
    pagina: int | None = None

    @property
    def imagem(self) -> bool:
        return PurePosixPath(self.ia).suffix.lower() in EXT_IMAGEM

    @property
    def chave(self) -> str:
        """Como a IA deve citar o arquivo nas respostas (PDF: "<arquivo>#pN")."""
        return f"{self.original}#p{self.pagina}" if self.pagina else self.original


def tipo(rel: str) -> str:
    """'imagem', 'pdf', 'texto' ou 'outro' (formato que a IA não lê)."""
    ext = PurePosixPath(rel).suffix.lower()
    if ext in EXT_IMAGEM:
        return "imagem"
    if ext == ".pdf":
        return "pdf"
    if ext in EXT_TEXTO:
        return "texto"
    return "outro"


def suportado(rel: str) -> bool:
    return tipo(rel) != "outro"


def _fresco(destino: Path, origem: Path) -> bool:
    try:
        return destino.is_file() and destino.stat().st_mtime >= origem.stat().st_mtime
    except OSError:
        return False


def _jpeg(im: Image.Image, lado: int) -> tuple[bytes, float]:
    """JPEG sem EXIF, lado maior ≤ lado e ≤ MAX_BYTES_IMAGEM (reduz mais se precisar)."""
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        fundo = Image.new("RGB", im.size, (255, 255, 255))
        fundo.paste(im, mask=im.split()[-1])
        im = fundo
    else:
        im = im.convert("RGB")
    w0 = im.width
    alvo = lado
    while True:
        esc = min(1.0, alvo / max(im.size))
        menor = im.resize((max(1, round(im.width * esc)), max(1, round(im.height * esc))),
                          Image.LANCZOS) if esc < 1.0 else im
        buf = io.BytesIO()
        menor.save(buf, "JPEG", quality=QUALIDADE, optimize=True)   # sem exif=: EXIF/GPS fora
        dados = buf.getvalue()
        if len(dados) <= MAX_BYTES_IMAGEM or alvo <= 400:
            return dados, menor.width / w0
        alvo = int(alvo * 0.75)


def copia_imagem(pasta: Path, rel: str, lado: int = LADO_IA) -> ItemIA:
    """Cópia da imagem para a IA em <pasta>/_ia/[<lado>/]<rel>.jpg (refeita se o original mudar)."""
    sub = PurePosixPath(PASTA) if lado == LADO_IA else PurePosixPath(PASTA) / str(lado)
    destino_rel = (sub / rel).with_suffix(PurePosixPath(rel).suffix + ".jpg").as_posix()
    origem, destino = pasta / rel, pasta / destino_rel
    marca = destino.with_name(destino.name + ".escala")
    if _fresco(destino, origem) and marca.is_file():
        return ItemIA(rel, destino_rel, float(marca.read_text()))
    with Image.open(origem) as im:
        dados, esc = _jpeg(im, lado)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(dados)
    marca.write_text(repr(esc))
    return ItemIA(rel, destino_rel, esc)


def paginas_pdf(pasta: Path, rel: str, lado: int = LADO_IA, dpi: int = DPI_PDF) -> list[ItemIA]:
    """Cada página do PDF em JPEG (≤ dpi e ≤ lado) em <pasta>/_ia/<rel>/p001.jpg…"""
    import pymupdf
    origem = pasta / rel
    sub = PurePosixPath(PASTA) if lado == LADO_IA else PurePosixPath(PASTA) / str(lado)
    base = (sub / rel).as_posix() + ".paginas"
    out: list[ItemIA] = []
    with pymupdf.open(origem) as d:
        for i, pg in enumerate(d, start=1):
            zoom = min(dpi / 72, lado / max(pg.rect.width, pg.rect.height, 1))
            destino_rel = f"{base}/p{i:03d}.jpg"
            destino = pasta / destino_rel
            if not _fresco(destino, origem):
                pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                with Image.open(io.BytesIO(pix.tobytes("png"))) as im:
                    dados, esc = _jpeg(im, lado)
                zoom *= esc
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(dados)
                (pasta / (destino_rel + ".escala")).write_text(repr(zoom))
            else:
                m = pasta / (destino_rel + ".escala")
                zoom = float(m.read_text()) if m.is_file() else zoom
            out.append(ItemIA(rel, destino_rel, zoom, i))
    return out


def preparar(pasta: Path, rels: list[str], lado: int = LADO_IA,
             lado_por_arquivo: dict[str, int] | None = None) -> tuple[list[ItemIA], list[str]]:
    """(itens que a IA lê, arquivos ignorados). Imagem/PDF que não abrem também são ignorados."""
    itens: list[ItemIA] = []
    ignorados: list[str] = []
    for rel in rels:
        rel = PurePosixPath(rel).as_posix()
        lado_arq = (lado_por_arquivo or {}).get(rel, lado)
        t = tipo(rel)
        try:
            if t == "imagem":
                itens.append(copia_imagem(pasta, rel, lado_arq))
            elif t == "pdf":
                itens.extend(paginas_pdf(pasta, rel, lado_arq))
            elif t == "texto":
                itens.append(ItemIA(rel, rel))
            else:
                ignorados.append(rel)
        except Exception:
            # PDF que não vira imagem (protegido, corrompido): vai como está, a IA tenta ler
            if t == "pdf":
                itens.append(ItemIA(rel, rel))
            else:
                ignorados.append(rel)
    return itens, ignorados


def lotes(itens: list[ItemIA], maximo: int = MAX_IMAGENS) -> list[list[ItemIA]]:
    """Divide em lotes de no máximo `maximo` imagens (texto não conta), na ordem."""
    out: list[list[ItemIA]] = [[]]
    n = 0
    for it in itens:
        if it.imagem and n >= maximo:
            out.append([])
            n = 0
        out[-1].append(it)
        n += it.imagem
    return [lote for lote in out if lote]


def agrupar(pasta: Path, rels: list[str], lado_por_arquivo: dict[str, int] | None = None,
            maximo: int = MAX_IMAGENS) -> list[list[str]]:
    """Arquivos do trabalho em grupos que rendem no máximo `maximo` imagens para a IA (PDF
    conta as páginas). Um PDF sozinho com mais páginas que isso fica num grupo próprio (a IA
    o lê em lotes de notas)."""
    grupos: list[list[str]] = []
    atual: list[str] = []
    n = 0
    for rel in rels:
        itens, _ = preparar(pasta, [rel], LADO_IA, lado_por_arquivo)
        k = sum(it.imagem for it in itens)
        if atual and n + k > maximo:
            grupos.append(atual)
            atual, n = [], 0
        atual.append(rel)
        n += k
    if atual:
        grupos.append(atual)
    return grupos


def converter_caixa(cx, escala: float):
    """Caixa nas coordenadas da cópia -> coordenadas do original (pixels ou pontos PDF)."""
    if not cx or not escala:
        return cx
    return [None if v is None else round(v / escala, 1) for v in cx]
