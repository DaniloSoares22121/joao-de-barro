"""ORDEM 082-2 (GRAVÍSSIMO): o envio da extensão trocou as áreas dos referenciais do 9120. Envio para referencial
que JÁ existe só acrescenta (foto, data de acesso, prova); dado diferente vira pergunta, o guardado vale."""
import asyncio

import pytest

from lovable.avaliacao import db, pendencias_simples as PS, routes
from lovable.avaliacao.agentes import leitor_anuncio
from lovable.avaliacao.modelos import Referencial
from tests.avaliacao.test_enviado_mesmo_link_077 import MANUAIS, PNG
from tests.avaliacao.test_pagina_enviada import _job

# nº, rua, lote certo, construída certa, preço — e o que a página "leu" errado (tabela da 082)
CASOS = [
    (2, "Rua VF", 300, 110, 159_000, {"lote_m2": 30, "area_m2": 290}),
    (3, "Rua JC-17A", 360, 230, 230_000, {"area_m2": 139}),
    (5, "Av. Anglo", None, 80, 200_000, {"area_m2": 300}),
    (6, "Rua VF-21", 300, 110, 200_000, {"area_m2": 170}),
]


def _refs(jid):
    db.salvar_candidatos(jid, [Referencial(n=n, link=MANUAIS[n - 1], portal="deztop", bairro="Jardim Curitiba", tipologia="Casa",
                                           padrao="", idade_aparente="", descricao=f"Localização: {rua}, Jardim Curitiba. Casa 110 m².",
                                           rua=rua, preco=preco, area_m2=area, lote_m2=lote, escolhido=True, decisao="entra",
                                           fonte_coleta="manual", coletado=True)
                               for n, rua, lote, area, preco, _ in CASOS])


@pytest.mark.parametrize("n,rua,lote,area,preco,errado", CASOS)
def test_envio_nao_troca_area_e_pergunta(monkeypatch, n, rua, lote, area, preco, errado):
    jid = _job()
    _refs(jid)

    class Lido:                                       # o leitor da página também "acha" outra descrição
        padrao = "médio"; idade_aparente = ""; descricao = "Anunciante: Fulana (CRECI 1)"; publicado_em = ""
        lote_m2 = errado.get("lote_m2"); quartos = None; suites = None; preco = None; area_m2 = errado.get("area_m2")

    async def ler(*a, **k):
        return Lido()
    monkeypatch.setattr(leitor_anuncio, "ler", ler)
    body = routes.AnuncioEnviado(link=MANUAIS[n - 1], titulo=f"Casa {errado['area_m2']} m²", texto="Casa", imagem=PNG, foto_principal=PNG,
                                 acessado_em="2026-11-14T23:50:00-03:00", bairro="Vila Finsocial", **errado)
    asyncio.run(routes.anuncio_enviado(jid, body, _u={}))
    c = next(x for x in db.candidatos(jid) if x.n == n)
    assert (c.area_m2, c.lote_m2, c.preco, c.rua) == (area, lote, preco, rua), "o envio mudou o referencial"
    assert c.descricao.startswith(f"Localização: {rua}") and "Anunciante" not in c.descricao
    assert c.escolhido and c.decisao == "entra" and c.foto and c.acessado_em
    assert c.bairro == "Jardim Curitiba" and c.divergencia_pagina.get("bairro") == "Vila Finsocial"
    for k, v in errado.items():
        if k == "lote_m2":                            # lote de 30 m² para casa de 290: leitura errada, ignorada
            assert c.lote_m2 == lote and "lote_m2" not in c.divergencia_pagina
            continue
        assert c.divergencia_pagina[k] == v
    cards = [k for k in PS.classificar(jid, [])["cards"] if k["chave"].startswith(f"divergencia:{n}:area_m2")]
    assert cards and cards[0]["titulo"] == (f"O anúncio {n} hoje mostra área construída {errado['area_m2']} m²; "
                                            f"o laudo usa {area} m².")
    assert cards[0]["opcoes"][0]["rotulo"] == f"Manter {area} m²"
    asyncio.run(routes.responder_divergencia(jid, n, routes.RespostaDivergencia(campo="area_m2", manter=True), _u={}))
    c = next(x for x in db.candidatos(jid) if x.n == n)
    assert c.area_m2 == area and "area_m2" not in c.divergencia_pagina
    asyncio.run(routes.responder_divergencia(jid, n, routes.RespostaDivergencia(campo="bairro", manter=False), _u={}))
    assert next(x for x in db.candidatos(jid) if x.n == n).bairro == "Vila Finsocial"


def test_area_de_anuncio_vizinho_nem_vira_pergunta(monkeypatch):
    """082-3: o 290 do nº 2 veio da lateral da página (outro anúncio): não está no título nem no link."""
    jid = _job()
    _refs(jid)

    async def sem_ia(*a, **k):
        return None
    monkeypatch.setattr(leitor_anuncio, "ler", sem_ia)
    body = routes.AnuncioEnviado(link=MANUAIS[1], titulo="Casa 3 quartos", texto="Casa", imagem=PNG, foto_principal=PNG,
                                 acessado_em="2026-11-14T23:50:00-03:00", area_m2=290, lote_m2=30)
    asyncio.run(routes.anuncio_enviado(jid, body, _u={}))
    c = next(x for x in db.candidatos(jid) if x.n == 2)
    assert (c.area_m2, c.lote_m2) == (110, 300) and c.divergencia_pagina == {} and c.foto
