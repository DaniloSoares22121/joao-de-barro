"""ORDEM 019: pesquisa pelo Chrome do avaliador — links de busca e "Enviar resultados desta
página" pela extensão (sem robô, sem contorno)."""
import asyncio
from datetime import date

import pytest
from fastapi import HTTPException

from lovable.avaliacao import db, routes
from lovable.avaliacao.modelos import Campo, Trabalho
from tests.avaliacao.conftest import numero_unico

ZAP = "https://www.zapimoveis.com.br/imovel/"


def _job() -> str:
    db.init()
    jid = db.criar_job(Trabalho(
        id="", numero=numero_unico(), modalidade="OV", finalidade="Venda", cliente="Teste",
        tipo="Galpão comercial", bairro="Polo Empresarial Goiás", cidade="Aparecida de Goiânia",
        pin_maps="", data_base=date(2026, 11, 12), data_vistoria=date(2026, 11, 12)))
    db.salvar_campos(jid, [Campo(nome="Área construída", valor=1982.96, origem="documento", fonte="iptu.pdf")])
    return jid


def _cartao(i: int, area: int, preco: str) -> dict:
    return {"link": f"{ZAP}venda-galpao-polo-empresarial-goias-aparecida-de-goiania-{i}/?source=x",
            "texto": f"Galpão/Depósito/Armazém para comprar com {area} m² em Polo Empresarial Goiás, "
                     f"Aparecida de Goiânia R$ {preco} Rua 6"}


def test_links_de_busca_do_galpao():
    jid = _job()
    r = asyncio.run(routes.links_busca(jid, _u={}))
    urls = [x["url"] for x in r["links"]]
    assert any("zapimoveis.com.br/venda/galpao-deposito-armazem/" in u for u in urls)
    assert any("vivareal.com.br" in u for u in urls) and any("olx.com.br" in u for u in urls)
    assert len(urls) == len(set(urls))


def test_pagina_enviada_vira_candidatos_sem_repetir():
    jid = _job()
    body = routes.PaginaEnviada(url="https://www.zapimoveis.com.br/venda/galpao/", cartoes=[
        _cartao(1, 2000, "5.000.000"), _cartao(2, 1800, "4.600.000"),
        {"link": "https://www.zapimoveis.com.br/venda/galpao/", "texto": "filtro da busca"},  # não é anúncio
        {"link": "https://exemplo.com/x", "texto": "R$ 1.000.000 outro site"}])
    r = asyncio.run(routes.candidatos_da_pagina(jid, body, _u={}))
    assert r["reconhecidos"] == 2 and r["ignorados"] == 2 and len(r["novos"]) == 2
    cands = db.candidatos(jid)
    assert {c.area_m2 for c in cands} == {2000, 1800}
    # mandar a mesma página de novo não duplica
    r2 = asyncio.run(routes.candidatos_da_pagina(jid, body, _u={}))
    assert r2["novos"] == [] and len(db.candidatos(jid)) == 2


def test_pagina_sem_anuncio_400():
    jid = _job()
    with pytest.raises(HTTPException) as e:
        asyncio.run(routes.candidatos_da_pagina(jid, routes.PaginaEnviada(cartoes=[
            {"link": "https://exemplo.com/x", "texto": "R$ 1"}]), _u={}))
    assert e.value.status_code == 400


def test_l200_mesmo_imovel_no_zap_e_no_viva_real_entra_uma_vez():
    """L200 (Caso W): o cartão do Viva Real não traz o bairro; o app só completa depois. O mesmo imóvel (área,
    preço e quartos iguais) que já veio do ZAP não entra de novo."""
    jid = _job()
    zap = routes.PaginaEnviada(url="https://www.zapimoveis.com.br/venda/galpao/", cartoes=[_cartao(1, 2000, "5.000.000")])
    asyncio.run(routes.candidatos_da_pagina(jid, zap, _u={}))
    viva = routes.PaginaEnviada(url="https://www.vivareal.com.br/venda/galpao/", cartoes=[
        {"link": "https://www.vivareal.com.br/imovel/galpao-deposito-armazem-2-vagas-id-999/",
         "texto": "+20 fotos Imobiliária Exemplo Galpão para comprar com 2000 m², 2 vagas em R$ 5.000.000 IPTU isento"}])
    r = asyncio.run(routes.candidatos_da_pagina(jid, viva, _u={}))
    assert r["reconhecidos"] == 1 and r["novos"] == [] and len(db.candidatos(jid)) == 1


def test_l200_zap_e_viva_real_tambem_com_a_busca_na_cidade():
    """L200 (Caso M): bairro que o portal não conhece dá 404; a busca na cidade inteira vai junto."""
    jid = _job()
    urls = [x["url"] for x in asyncio.run(routes.links_busca(jid, _u={}))["links"]]
    assert any(u.rstrip("/").endswith("go+aparecida-de-goiania") for u in urls if "zapimoveis" in u)
    assert len(urls) == len(set(urls))


def test_l200_link_do_imovelweb_sem_rastreio():
    """L200 (Caso M): o link do cartão do Imovelweb vinha com n_src/n_pos/n_search_id e o anúncio aberto virava
    candidato novo (o mesmo imóvel duas vezes)."""
    from lovable.avaliacao.agentes.pesquisa import link_limpo
    u = "https://www.imovelweb.com.br/propriedades/apto-3050975835.html"
    assert link_limpo(u + "?n_src=Listado&n_exp=x&n_pills=Varanda&n_pg=1&n_pos=27&n_search_id=e7") == u
