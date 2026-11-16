"""D-082 (ORDEM 039-1): prova de cada anúncio, com data e hora de acesso.

Na coleta de cada referencial (Coletor, extensão e importação) guarda, na pasta de dados do
trabalho, em `provas/anuncios/` (fora do git):
  - a captura da página inteira com a faixa no rodapé
    "Acessado em dd/mm/aaaa às hh:mm (horário de Brasília) — <link limpo> — <portal>";
  - o PDF dessa captura (e o PDF da página, quando a extensão conseguir gerar);
  - a data e a hora de acesso no próprio referencial (`acessado_em`, ISO com -03:00).
No laudo, a foto principal de cada amostra leva o carimbo discreto "Acessado em dd/mm/aaaa às
hh:mm". A captura inteira NÃO entra nos anexos (D-015): fica para o caso de contestação.
Referencial antigo sem hora registrada: usa a do banco (visto_em) ou a do arquivo da página
capturada; sem nenhuma, "data de acesso não registrada" (pendência). Nunca inventa data."""
from __future__ import annotations

import io
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import db

# Brasília: UTC−3 o ano inteiro (sem horário de verão desde 2019). O Windows deste PC não tem a
# base de fusos (tzdata); com ela, usa America/Sao_Paulo.
try:
    from zoneinfo import ZoneInfo
    BRASILIA = ZoneInfo("America/Sao_Paulo")
except Exception:      # ZoneInfoNotFoundError sem tzdata
    BRASILIA = timezone(timedelta(hours=-3), "BRT")

SEM_DATA = "data de acesso não registrada"
PASTA = Path("provas") / "anuncios"


def agora() -> datetime:
    return datetime.now(BRASILIA)


def em_brasilia(iso: str) -> datetime | None:
    try:
        d = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(BRASILIA)


def fmt(d: datetime) -> str:
    """"dd/mm/aaaa às hh:mm" no horário de Brasília."""
    return d.astimezone(BRASILIA).strftime("%d/%m/%Y às %H:%M")


def _fonte(tam: int):
    for nome in ("arial.ttf", "DejaVuSans.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(nome, tam)
        except OSError:
            continue
    return ImageFont.load_default()


def faixa_rodape(img: Image.Image, texto: str) -> Image.Image:
    """Imagem + faixa branca no rodapé com o texto da prova (quebra em linhas se precisar)."""
    img = img.convert("RGB")
    w = img.width
    tam = max(14, min(26, w // 70))
    f = _fonte(tam)
    d0 = ImageDraw.Draw(img)
    palavras, linhas, atual = texto.split(" "), [], ""
    for p in palavras:
        teste = (atual + " " + p).strip()
        if d0.textlength(teste, font=f) > w - 2 * tam and atual:
            linhas.append(atual)
            atual = p
        else:
            atual = teste
    linhas.append(atual)
    alt = (tam + 8) * len(linhas) + 16
    out = Image.new("RGB", (w, img.height + alt), "white")
    out.paste(img, (0, 0))
    d = ImageDraw.Draw(out)
    d.line([(0, img.height), (w, img.height)], fill=(24, 40, 59), width=3)
    for i, ln in enumerate(linhas):
        d.text((tam, img.height + 10 + i * (tam + 8)), ln, fill=(24, 40, 59), font=f)
    return out


def texto_prova(quando: datetime, link: str, portal: str) -> str:
    return f"Acessado em {fmt(quando)} (horário de Brasília) — {link} — {portal or 'site'}"


def _seguro(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", s)[:40].strip("-") or "x"


def gravar(job_id: str, n: int, imagem: bytes | Path | None, link: str, portal: str,
           quando: datetime | None = None, pdf_pagina: bytes | None = None) -> dict:
    """Grava a prova do referencial nº n. Devolve {acessado_em, prova, prova_pdf, prova_pagina_pdf}
    com caminhos relativos à pasta do trabalho ('' quando não houve)."""
    quando = quando or agora()
    pasta = db.pasta(job_id) / PASTA
    pasta.mkdir(parents=True, exist_ok=True)
    import hashlib
    quem = f"ref-{n:02d}" if n else "anuncio-" + hashlib.sha1(link.encode()).hexdigest()[:8]
    base = f"{quem}-{quando.strftime('%Y%m%d-%H%M%S')}"
    out = {"acessado_em": quando.isoformat(timespec="seconds"), "prova": "", "prova_pdf": "",
           "prova_pagina_pdf": ""}
    if imagem:
        try:
            img = Image.open(imagem if isinstance(imagem, Path) else io.BytesIO(imagem))
            img.load()
        except Exception:
            img = None
        if img is not None:
            # página muito comprida: limita a altura (o rodapé com a prova sempre aparece)
            if img.height > 12000:
                img = img.crop((0, 0, img.width, 12000))
            final = faixa_rodape(img, texto_prova(quando, link, portal))
            jpg = pasta / f"{base}.jpg"
            final.save(jpg, "JPEG", quality=82)
            out["prova"] = str(jpg.relative_to(db.pasta(job_id))).replace("\\", "/")
            pdf = pasta / f"{base}.pdf"
            _imagem_em_pdf(final, pdf)
            out["prova_pdf"] = str(pdf.relative_to(db.pasta(job_id))).replace("\\", "/")
    if pdf_pagina and pdf_pagina[:5] == b"%PDF-":
        p = pasta / f"{base}-pagina.pdf"
        p.write_bytes(pdf_pagina)
        out["prova_pagina_pdf"] = str(p.relative_to(db.pasta(job_id))).replace("\\", "/")
    return out


def _imagem_em_pdf(img: Image.Image, destino: Path) -> None:
    """A captura (com a faixa) em PDF A4 de largura, em várias páginas se for comprida."""
    import pymupdf
    larg_pt = 595
    escala = larg_pt / img.width
    alt_pg = int(842 / escala)
    with pymupdf.open() as doc:
        for y in range(0, img.height, alt_pg):
            pedaco = img.crop((0, y, img.width, min(img.height, y + alt_pg)))
            b = io.BytesIO()
            pedaco.save(b, "JPEG", quality=80)
            pg = doc.new_page(width=larg_pt, height=pedaco.height * escala)
            pg.insert_image(pg.rect, stream=b.getvalue())
        doc.save(destino)


# ------------------------------------------------------------------ data de acesso de um referencial
def acesso(job_id: str, r) -> tuple[datetime | None, str]:
    """(quando, de onde) — `acessado_em` registrado; senão `visto_em` do banco de comparáveis;
    senão a hora do arquivo da PÁGINA capturada (print feito no acesso). Sem nada: (None, '').
    A foto recortada de outro documento (ex.: laudo oficial) não é acesso ao anúncio."""
    if getattr(r, "acessado_em", ""):
        d = em_brasilia(r.acessado_em)
        if d:
            return d, "registrado na coleta"
    if r.fonte_coleta == "banco" and r.visto_em:
        d = em_brasilia(r.visto_em)
        if d:
            return d, "banco de comparáveis"
    if r.print_ and r.fonte_coleta in ("coletor", "avaliador"):
        f = db.pasta(job_id) / r.print_
        if f.is_file():
            return (datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).astimezone(BRASILIA),
                    "arquivo da página capturada")
    return None, ""


def carimbar(foto: Path, quando: datetime, destino: Path) -> Path:
    """Cópia da foto com o carimbo discreto "Acessado em dd/mm/aaaa às hh:mm" (canto inferior)."""
    img = Image.open(foto).convert("RGB")
    w, h = img.size
    tam = max(10, w // 60)          # discreto: ~1/3 da largura da foto
    f = _fonte(tam)
    txt = f"Acessado em {fmt(quando)}"
    d = ImageDraw.Draw(img, "RGBA")
    tw = d.textlength(txt, font=f)
    pad = max(4, tam // 3)
    x0, y0 = w - tw - 3 * pad, h - tam - 3 * pad
    d.rectangle([x0, y0, w, h], fill=(255, 255, 255, 200))
    d.text((x0 + pad, y0 + pad), txt, fill=(24, 40, 59, 255), font=f)
    destino.parent.mkdir(parents=True, exist_ok=True)
    img.save(destino, "JPEG", quality=88)
    return destino
