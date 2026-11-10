"""Fonte de dados de mercado (anúncios). O Coletor real (Plano 3) se registra aqui."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from .modelos import Referencial


class Consulta(BaseModel):
    portal: str | None = None
    tipologia: str
    bairro: str
    cidade: str
    quartos_min: int | None = None
    area_min: float | None = None
    area_max: float | None = None
    preco_max: float | None = None


@runtime_checkable
class FonteMercado(Protocol):
    async def buscar(self, job_id: str, consultas: list[Consulta]) -> list[Referencial]: ...

    def online(self) -> bool: ...


class FonteFixture:
    """Devolve os anúncios de um JSON (lista de Referencial), ignorando os filtros."""

    def __init__(self, caminho_json: str | Path):
        self.caminho = Path(caminho_json)

    async def buscar(self, job_id: str, consultas: list[Consulta]) -> list[Referencial]:
        dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        return [Referencial.model_validate(d) for d in dados]

    def online(self) -> bool:
        return False


_atual: FonteMercado | None = None


def registrar(f: FonteMercado) -> None:
    global _atual
    _atual = f


def atual() -> FonteMercado:
    if _atual is None:
        raise RuntimeError("nenhuma fonte de mercado registrada")
    return _atual
