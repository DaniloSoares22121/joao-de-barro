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
    # "banco": reaproveitado de av_anuncios; "manual": cadastrado pelo avaliador na tela
    # "avaliador": enviado pelo Alan com a extensão "Enviar ao João de Barro" (ORDEM 010)
    fonte_coleta: Literal["coletor", "banco", "manual", "avaliador"] = "coletor"
    visto_em: str = ""          # ISO; quando o anúncio foi visto (anúncios do banco)
    # D-082 (ORDEM 039-1): data e hora de acesso (ISO, horário de Brasília) e a prova guardada
    # em provas/anuncios/ (captura da página inteira com a faixa de data/hora/link; PDF)
    acessado_em: str = ""
    prova: str = ""
    prova_pdf: str = ""
    escolhido: bool = False
    justificativa: str = ""
    # lista de candidatos da pesquisa (ORDEM 003): o avaliador decide quem entra no laudo
    decisao: Literal["", "entra", "descarta", "comparacao"] = ""   # 080-4: "comparacao" = só comparação (D-069)
    motivo_descarte: str = ""
    recomendado: bool = False          # ★ na lista
    nao_recomendado: bool = False      # riscado na lista (regra D-010/D-021)
    motivo: str = ""                   # por que ★ ou por que riscado (1 linha)
    observacao: str = ""               # o que conferir ao abrir o anúncio
    bloqueado: bool = False            # portal barrou a página do anúncio: abrir no navegador
    coletado: bool = False             # página do anúncio já lida (dados completos)
    rodada: int = 1
    titulo: str = ""
    rua: str = ""
    pontos: int = 0
    sem_estrela: str = ""              # por que não pode ter ★ (tipologia não confirmada etc.)
    # 153-4: referencial de PESQUISA DE CAMPO (sem anúncio na internet): sem link; a data da pesquisa e o informante
    pesquisa_campo: bool = False
    # 173: a foto da tabela — qual da galeria foi escolhida, ou se o avaliador enviou a dele (rastreabilidade)
    foto_url_escolhida: str = ""
    foto_avaliador: bool = False
    data_pesquisa: str = ""            # ISO (aaaa-mm-dd)
    informante: str = ""               # corretor, imobiliária, morador… (opcional)
    negocio: str = ""                  # "oferta" ou "venda" (venda realizada)
    # 081-5: fotos grandes da galeria do anúncio (a extensão manda até 12, a principal primeiro) e
    # o aviso de que a foto principal é arte de anúncio (banner "À VENDA…"), não a casa
    fotos_url: list[str] = []
    foto_arte: bool = False
    # 082-2: o que a página mostrou DIFERENTE do que está guardado (o guardado continua valendo até o
    # avaliador decidir): {"area_m2": 290.0, ...}
    divergencia_pagina: dict[str, float | int | str] = {}
    destaque: str = ""                 # 100-8: o que distingue o imóvel ("3 quartos, espaço gourmet, piscina, 220 m²")
    idade_fonte: str = ""              # 105-2: de onde veio a idade aparente: "anúncio" | "fotos" | "avaliador" | ""


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
    # Vistoria do avaliador (origem "vistoria"): texto livre + checklist colado do celular (P5
    # parte A). Linhas "Só contexto" do checklist vão para `contexto` (nunca entram no laudo).
    obs_vistoria: str = ""
    checklist_vistoria: str = ""
    data_emissao: date | None = None     # vazio = data do dia da montagem
    # D-043: visita técnica feita por parceiro ("Nome, CRECI/CNAI nº"); vazio = o avaliador
    visita_por: str = ""
    # ORDEM 032-2 / D-059: objeto da avaliação. Vazio = imóvel inteiro; senão, a PARTE avaliada
    # (ex.: "Galpão 01"): área do objeto, o lote é só contexto, o valor é da parte
    objeto_parte: str = ""
    # AMJ (opcionais em AM): dados do processo vão para a tabela 3.1 e a capa em código
    processo_numero: str = ""
    vara_juizo: str = ""
    acao: str = ""
    partes: Partes | None = None
    quesitos: list[str] = []
    # ORDEM 042: dono do trabalho (cada avaliador vê só os dele); AV-0001 = Alan
    avaliador_id: str = "AV-0001"
