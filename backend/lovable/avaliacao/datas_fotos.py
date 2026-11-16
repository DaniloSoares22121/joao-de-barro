"""ORDEM 032-3: alerta cedo — data das fotos (EXIF) × data da vistoria.

Logo depois do envio dos arquivos (no detalhe do trabalho), sem esperar o revisor: se a data
mais comum das fotos da vistoria for diferente da data da vistoria informada, o avaliador vê
"As fotos são de DD/MM/AAAA e a vistoria está como DD/MM/AAAA. Confirme a data da vistoria"."""
from __future__ import annotations

import re
from collections import Counter
from datetime import date
from pathlib import Path

from PIL import Image

from . import db

_EXIF_IFD = 0x8769
_ORIGINAL, _DIGITALIZADA, _DATA = 0x9003, 0x9004, 0x0132
_NOME = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
_cache: dict[tuple, date | None] = {}


def _data_exif(p: Path) -> date | None:
    try:
        with Image.open(p) as im:
            ex = im.getexif()
            sub = ex.get_ifd(_EXIF_IFD) if ex else {}
            bruto = sub.get(_ORIGINAL) or sub.get(_DIGITALIZADA) or ex.get(_DATA)
    except Exception:
        return None
    m = re.match(r"(\d{4}):(\d{2}):(\d{2})", str(bruto or ""))
    return _valida(*m.groups()) if m else None


def _valida(a, m, d) -> date | None:
    try:
        x = date(int(a), int(m), int(d))
    except ValueError:
        return None
    return x if 2000 <= x.year <= 2100 else None


def data_das_fotos(job_id: str) -> date | None:
    """Data mais comum das fotos da vistoria: EXIF; sem EXIF, a data no nome (IMG_20260529_…)."""
    fotos = [a for a in db.arquivos(job_id) if a.get("tipo") == "foto"]
    chave = (job_id, tuple(sorted(a["caminho"] for a in fotos)))   # muda quando chega/sai foto
    if chave in _cache:
        return _cache[chave]
    pasta = db.pasta(job_id)
    datas = []
    for a in fotos:
        d = _data_exif(pasta / a["caminho"])
        if d is None:
            m = _NOME.search(Path(a["caminho"]).name)
            d = _valida(*m.groups()) if m else None
        if d is not None:
            datas.append(d)
    res = Counter(datas).most_common(1)[0][0] if datas else None
    _cache[chave] = res
    return res


def chave_confirmada(job_id: str) -> str:
    return f"datas_confirmadas:{job_id}"


def confirmada(job_id: str, data_vistoria) -> bool:
    """ORDEM 034-3: o avaliador confirmou ESTA data da vistoria (mudou a data -> pergunta de novo)."""
    return bool(data_vistoria) and db.setting(chave_confirmada(job_id)) == str(data_vistoria)[:10]


def alerta(job_id: str, data_vistoria: str | date | None) -> str:
    """Texto do alerta, ou "" (sem fotos com data, sem data de vistoria, ou datas iguais)."""
    fotos = data_das_fotos(job_id)
    if fotos is None or not data_vistoria:
        return ""
    try:
        vist = data_vistoria if isinstance(data_vistoria, date) else date.fromisoformat(str(data_vistoria)[:10])
    except ValueError:
        return ""
    if fotos == vist:
        return ""
    return (f"As fotos são de {fotos:%d/%m/%Y} e a vistoria está como {vist:%d/%m/%Y}. "
            "Confirme a data da vistoria.")
