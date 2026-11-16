"""089-3/4: a galeria não traz banner de loja nem logotipo; o passo do texto mostra o trecho e aceita
"Escreva como deve ficar", que vira correção da redação e uma remontagem (só a seção atingida, 081-7)."""
import asyncio

from lovable.avaliacao import db, orquestrador as O, pendencias_simples as PS, routes
from tests.avaliacao.test_pagina_enviada import _job


def test_galeria_sem_banner_de_loja():
    urls = ["https://img.deztop.com/casa-1.jpg", "https://deztop.com/static/app-store-badge.png",
            "https://x.com/img/logo-portal.png", "https://img.deztop.com/casa-2.jpg", "https://x.com/google-play.png"]
    assert routes._fotos_url(urls) == ["https://img.deztop.com/casa-1.jpg", "https://img.deztop.com/casa-2.jpg"]


def test_ponto_de_texto_com_trecho_e_correcao(monkeypatch):
    jid = _job()
    r = PS.classificar(jid, [{"texto": "revisor (documental/redação): O resumo diz 'Entre regular e reparos simples – idade "
                                       "aparente Cerca de 30 anos'. 'Cerca' está com maiúscula."}])
    card = next(c for c in r["cards"] if c["chave"] == "texto_jdb")
    assert card["pontos"][0]["trecho"].startswith("Entre regular e reparos simples")
    feitas = []
    monkeypatch.setattr(O, "reabrir", lambda j, e, motivo="": feitas.append(e))
    monkeypatch.setattr(O, "enfileirar", lambda j: None)

    async def cenario():
        await routes.corrigir_texto(jid, routes.CorrigirTexto(ponto=card["pontos"][0]["texto"],
                                                             como_fica="Entre regular e reparos simples – idade aparente de cerca de 30 anos"),
                                    _u={})
        await asyncio.sleep(0.2)
    asyncio.run(cenario())
    assert feitas == ["redacao"]
    assert any("cerca de 30 anos" in x for x in db.correcoes(jid, "redacao"))
