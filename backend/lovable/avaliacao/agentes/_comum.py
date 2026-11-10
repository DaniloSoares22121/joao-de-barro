"""Utilidades compartilhadas pelos agentes."""
from __future__ import annotations

from pathlib import Path

from .. import db
from ..modelos import Trabalho


def trabalho(job_id: str) -> Trabalho:
    return Trabalho.model_validate(db.job(job_id)["dados"])


def arquivos(job_id: str) -> tuple[Path, list[Path]]:
    """(pasta do job, caminhos dos arquivos registrados) — caminhos relativos à pasta."""
    pasta = db.pasta(job_id)
    return pasta, [Path(a["caminho"]) for a in db.arquivos(job_id)]


def lista(rels: list[Path]) -> str:
    return "\n".join(f"- {r.as_posix()}" for r in rels) or "(nenhum arquivo enviado)"
