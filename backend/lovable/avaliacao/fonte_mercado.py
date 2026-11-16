"""A consulta de mercado (usada nos links de busca) e o registro da fonte (o Coletor, hoje só para o mapa)."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


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
    """112: a busca automática nos portais saiu; a fonte só diz se o Coletor (mapa) está ligado."""

    def online(self) -> bool: ...


class FonteFixture:
    """Fonte de teste: Coletor desligado (o caminho do JSON fica por compatibilidade dos testes)."""

    def __init__(self, caminho_json: str | Path = ""):
        self.caminho = Path(caminho_json) if caminho_json else None

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
