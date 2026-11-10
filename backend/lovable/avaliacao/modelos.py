"""Modelos pydantic do João de Barro."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel


class Campo(BaseModel):
    nome: str
    valor: str | float | None = None
    unidade: str = ""
    origem: Literal["documento", "vistoria", "pesquisa", "inferido", "pendente"]
    fonte: str = ""
    observacao: str = ""


class Referencial(BaseModel):
    n: int
    link: str
    portal: str
    bairro: str
    tipologia: str
    quartos: int | None = None
    suites: int | None = None
    lote_m2: float | None = None
    area_m2: float | None = None
    preco: float | None = None
    padrao: str
    idade_aparente: str
    descricao: str
    foto: str = ""
    print_: str = ""
    publicado_em: str = ""      # data de publicação do anúncio (ISO), se o portal informar
    fonte_coleta: Literal["coletor", "banco"] = "coletor"   # "banco": reaproveitado de av_anuncios
    visto_em: str = ""          # ISO; quando o anúncio foi visto (anúncios do banco)
    escolhido: bool = False
    justificativa: str = ""


class Partes(BaseModel):
    autor: str = ""
    reu: str = ""


class Trabalho(BaseModel):
    id: str
    numero: int
    modalidade: Literal["OV", "AM", "AM_GARANTIA", "AMJ"]
    finalidade: str
    cliente: str
    tipo: str
    bairro: str
    cidade: str
    pin_maps: str
    data_base: date
    data_vistoria: date
    contexto: str = ""
    # AMJ (opcionais em AM): dados do processo vão para a tabela 3.1 e a capa em código
    processo_numero: str = ""
    vara_juizo: str = ""
    acao: str = ""
    partes: Partes | None = None
    quesitos: list[str] = []
