"""094-1 (GRAVE): o nº 7 (só comparação, cadastrado à mão) entrou na média do 9120. Comparação nunca entra na conta:
nem na seleção automática, nem no cálculo, nem na confirmação, mesmo marcada como escolhida."""
import asyncio
from decimal import Decimal

from lovable.avaliacao import calculo, db, ia
from lovable.avaliacao.agentes import selecao
from lovable.avaliacao.modelos import Referencial
from tests.avaliacao.test_pagina_enviada import _job


def _r(n, preco, area, decisao, fonte="avaliador", escolhido=True):
    return Referencial(n=n, link=f"https://x/{n}", portal="p", bairro="Jardim Curitiba", tipologia="Casa", padrao="",
                       idade_aparente="", descricao="", preco=preco, area_m2=area, decisao=decisao, fonte_coleta=fonte,
                       escolhido=escolhido)


SEIS = [(1, 250000, 139), (2, 159000, 110), (3, 230000, 230), (4, 180000, 150), (5, 200000, 80), (6, 200000, 110)]


def test_refs_na_base_tira_comparacao_mesmo_marcada():
    refs = [_r(n, p, a, "entra") for n, p, a in SEIS] + [_r(7, 240000, 125, "comparacao", "manual", True)]
    na = selecao.refs_na_base(None, refs, "construida")
    assert [r.n for r in na] == [1, 2, 3, 4, 5, 6]
    media6 = calculo.calcular(Decimal("106.24"), na, None, Decimal("10")).media
    assert media6 == calculo.calcular(Decimal("106.24"), [r for r in refs if r.n <= 6], None, Decimal("10")).media


def test_selecao_automatica_nao_escolhe_comparacao_manual(monkeypatch):
    jid = _job()
    db.salvar_candidatos(jid, [_r(n, p, a, "entra") for n, p, a in SEIS]
                         + [_r(7, 240000, 125, "comparacao", "manual", True), _r(8, 295000, 220, "comparacao", "avaliador", False)])
    vistos = {}

    async def fake(sistema, prompt, esquema, **k):
        vistos["prompt"] = prompt
        return esquema.model_validate({"decisoes": []})
    monkeypatch.setattr(ia, "perguntar", fake)
    s = asyncio.run(selecao.rodar(jid))
    por_n = {r.n: r for r in s.refs}
    assert not por_n[7].escolhido and not por_n[8].escolhido
    assert '"n":7' not in vistos["prompt"].replace(" ", "") and '"n":8' not in vistos["prompt"].replace(" ", "")
