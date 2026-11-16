"""ORDEM 061: áudio → texto em português, LOCAL (faster-whisper em CPU). Custo zero e o áudio do
cliente não sai do computador. O modelo ("small" por padrão; JDB_TRANSCRICAO_MODELO muda) é baixado
uma vez na primeira transcrição e fica no cache do usuário (fora do git e da pasta de dados)."""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)
MODELO = os.environ.get("JDB_TRANSCRICAO_MODELO", "small")
_modelo = None
_trava = threading.Lock()


def disponivel() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def _carregar():
    global _modelo
    with _trava:
        if _modelo is None:
            from faster_whisper import WhisperModel
            _modelo = WhisperModel(MODELO, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
    return _modelo


def impressao(caminho: Path) -> str:
    """093-5: a impressão digital do arquivo (SHA-256 do conteúdo) + o modelo usado."""
    import hashlib
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return f"{MODELO}:{h.hexdigest()}"


def _guardada(chave: str) -> tuple[str, float] | None:
    import json
    from . import db
    try:
        d = json.loads(db.setting("transcricao:" + chave) or "null")
    except (ValueError, TypeError):
        return None
    return (str(d.get("texto") or ""), float(d.get("duracao") or 0.0)) if isinstance(d, dict) else None


def _guardar(chave: str, texto: str, duracao: float) -> None:
    import json
    from . import db
    try:
        db.set_setting("transcricao:" + chave, json.dumps({"texto": texto, "duracao": duracao}, ensure_ascii=False))
    except Exception:          # noqa: BLE001 — sem cache a transcrição continua valendo
        log.warning("transcrição não guardada no cache")


def transcrever(caminho: Path) -> tuple[str, float, float]:
    """(texto, duração do áudio em s, tempo gasto em s). Vídeo também serve (lê a trilha de áudio).
    Sem fala: texto vazio. 093-5: o mesmo áudio (mesma impressão digital) não é transcrito de novo — a transcrição
    guardada volta na hora (o zip da mesma conversa importado 3 vezes não refaz os 15 áudios)."""
    t0 = time.monotonic()
    try:
        chave = impressao(Path(caminho))
    except OSError:
        chave = ""
    if chave:
        ja = _guardada(chave)
        if ja is not None:
            return ja[0], ja[1], time.monotonic() - t0
    segs, info = _carregar().transcribe(str(caminho), language="pt", vad_filter=True, beam_size=1)
    texto = " ".join(s.text.strip() for s in segs).strip()
    dur = float(getattr(info, "duration", 0.0) or 0.0)
    if chave:
        _guardar(chave, texto, dur)
    return texto, dur, time.monotonic() - t0
