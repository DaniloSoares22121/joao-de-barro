"""ORDEM 073-3 / 112: colou o link — sem busca automática (D-117) o JdB não abre o anúncio; manda trazer pela extensão
"Enviar ao JdB" no Chrome (ou preencher à mão). Diz o que não é link e o que já está na lista."""
import asyncio

from lovable.avaliacao import coletor_hub, routes
from tests.avaliacao.test_pagina_enviada import _job

ZAP = "https://www.zapimoveis.com.br/imovel/venda-casa-2-quartos-jardim-curitiba-goiania-go-103m2-id-2712345678/"


def test_link_colado_manda_para_a_extensao_e_nunca_abre_portal(monkeypatch):
    monkeypatch.setattr(coletor_hub, "online", lambda: True)

    async def nunca(*a, **k):
        raise AssertionError("o programa do PC não abre portal (112)")
    monkeypatch.setattr(coletor_hub, "executar", nunca)
    jid = _job()
    r = asyncio.run(routes.ler_links(jid, routes.Links(links=[ZAP, "isso não é link"]), _u={}))
    a, b = r["anuncios"]
    assert "Enviar ao JdB" in a["erro"] and a["link"]
    assert "não parece um link" in b["erro"]


def test_salvar_a_mao_sem_foto_do_coletor():
    jid = _job()
    s = asyncio.run(routes.adicionar_referencial(jid, link=ZAP, area_m2="103,00", preco="185.000,00", portal="ZAP Imóveis",
                                                 localizacao="", bairro="Jardim Curitiba", tipologia="Casa", quartos="2",
                                                 suites="", lote_m2="250,00", idade_estado="", padrao="", descricao="",
                                                 foto=None, _u={}))
    assert s["fonte_coleta"] == "manual"
    r2 = asyncio.run(routes.ler_links(jid, routes.Links(links=[ZAP]), _u={}))
    assert "já está na lista" in r2["anuncios"][0]["erro"]
