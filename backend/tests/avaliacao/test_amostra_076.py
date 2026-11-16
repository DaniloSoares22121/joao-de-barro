"""ORDEM 076-A: mexer nos anúncios pelos Detalhes — tirar/pôr, corrigir, mínimo de 5 e 'Gerar a REVISÃO N'."""
import asyncio

import pytest
from fastapi import HTTPException

from lovable.avaliacao import db, orquestrador, rotas_amostra as A, routes
from lovable.avaliacao.agentes import selecao
from lovable.avaliacao.modelos import Referencial
from tests.avaliacao.test_pagina_enviada import ZAP, _job

PRECOS = [(1, 3_000_000, 1500), (2, 3_200_000, 1600), (3, 2_900_000, 1450), (4, 3_100_000, 1550),
          (5, 3_050_000, 1500), (6, 4_800_000, 1600)]


def _laudo_pronto() -> str:
    jid = _job()
    db.salvar_candidatos(jid, [Referencial(n=n, link=f"{ZAP}galpao-{n}/", portal="ZAP Imóveis", bairro="Polo", tipologia="Galpão",
                                           padrao="", idade_aparente="", descricao="", preco=p, area_m2=a, escolhido=True,
                                           decisao="entra", fonte_coleta="avaliador", coletado=True) for n, p, a in PRECOS])
    asyncio.run(routes.escolher_referenciais(jid, routes.EscolhaReferenciais(
        escolhidos=[n for n, _, _ in PRECOS], base_area="construida", area_campo="Área construída"), _u={}))
    v = A._agora(jid)["valor"]
    db.evento(jid, "calculo", "resultado", "valor adotado", dados={"valor_adotado": v})   # o laudo gerado
    return jid


def test_tirar_da_amostra_muda_o_valor_sem_gerar(monkeypatch):
    jid = _laudo_pronto()
    gerou = []
    monkeypatch.setattr(orquestrador, "enfileirar", lambda j: gerou.append(j))
    e0 = A.estado(jid)
    assert not e0["mudou"] and e0["agora"]["n"] == 6
    e1 = asyncio.run(A.mudar_amostra(jid, A.Amostra(escolhidos=[1, 2, 3, 4, 5]), _u={}))   # tira o nº 6 (o caro)
    assert e1["mudou"] and e1["agora"]["n"] == 5 and e1["laudo"]["valor"] == e0["laudo"]["valor"]
    assert float(e1["agora"]["valor"]) < float(e0["agora"]["valor"])
    assert not gerou                                          # o laudo só é refeito com o toque do avaliador
    # desfazer = voltar à amostra do laudo
    e2 = asyncio.run(A.mudar_amostra(jid, A.Amostra(escolhidos=e0["laudo"]["escolhidos"]), _u={}))
    assert not e2["mudou"]


def test_minimo_de_5_e_gerar(monkeypatch):
    jid = _laudo_pronto()
    fila = []
    monkeypatch.setattr(orquestrador, "enfileirar", lambda j: fila.append(j))
    monkeypatch.setattr(orquestrador, "reabrir", lambda j, etapa, motivo="": None)
    e = asyncio.run(A.mudar_amostra(jid, A.Amostra(escolhidos=[1, 2, 3, 4]), _u={}))
    assert e["abaixo_do_minimo"]
    with pytest.raises(HTTPException) as err:
        asyncio.run(A.gerar_revisao(jid, A.Gerar(), _u={}))
    assert "mínimo é 5" in err.value.detail
    asyncio.run(A.mudar_amostra(jid, A.Amostra(escolhidos=[1, 2, 3, 4, 5]), _u={}))
    r = asyncio.run(A.gerar_revisao(jid, A.Gerar(confirmacao="amostra revista pelo avaliador"), _u={}))
    assert fila == [jid] and r["revisao"] >= 1
    assert (db.resultado(jid, "selecao") or {}).get("confirmado") is True


def test_corrigir_preco_refaz_a_conta():
    jid = _laudo_pronto()
    antes = A.estado(jid)["agora"]["valor"]
    e = asyncio.run(A.corrigir_anuncio(jid, 6, preco="3.100.000", area_m2="", lote_m2="", foto=None, _u={}))
    assert next(x for x in db.candidatos(jid) if x.n == 6).preco == 3_100_000
    assert e["mudou"] and float(e["agora"]["valor"]) < float(antes)
    assert selecao.escolha_area(jid)


def test_094_comparacao_nunca_entra_na_media():
    """094-1: 6 'entra' + 2 'comparacao' (um deles ainda marcado, como o #7 cadastrado à mão) -> a média é a dos 6."""
    jid = _laudo_pronto()
    base = A._agora(jid)
    db.salvar_candidatos(jid, [
        Referencial(n=7, link=f"{ZAP}galpao-7/", portal="ZAP Imóveis", bairro="Polo", tipologia="Galpão", padrao="",
                    idade_aparente="", descricao="", preco=9_000_000, area_m2=1500, escolhido=True, decisao="comparacao"),
        Referencial(n=8, link=f"{ZAP}galpao-8/", portal="ZAP Imóveis", bairro="Polo", tipologia="Galpão", padrao="",
                    idade_aparente="", descricao="", preco=8_000_000, area_m2=1500, escolhido=False, decisao="comparacao")])
    agora = A._agora(jid)
    assert agora["media"] == base["media"] and agora["n"] == 6 and 7 not in agora["escolhidos"]
