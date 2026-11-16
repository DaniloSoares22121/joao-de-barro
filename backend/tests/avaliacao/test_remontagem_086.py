"""086-1/2: envio de anúncio sempre aceito (mesmo com o trabalho montando); a remontagem é UMA, depois que os
envios param; prova sozinha não remonta; resposta de passo com outros abertos espera o "Respondi tudo"."""
import asyncio

from lovable.avaliacao import db, orquestrador as O, routes
from lovable.avaliacao.agentes import leitor_anuncio
from tests.avaliacao.test_enviado_mesmo_link_077 import ENVIADOS, PNG, _manuais
from tests.avaliacao.test_pagina_enviada import _job


def _fila_falsa(monkeypatch):
    feitas = []
    monkeypatch.setattr(O, "reabrir", lambda j, e, motivo="": feitas.append((j, e, motivo)))
    monkeypatch.setattr(O, "enfileirar", lambda j: None)
    return feitas


def test_varios_envios_uma_remontagem_e_aceita_com_trabalho_ocupado(monkeypatch):
    jid = _job()
    _manuais(jid)
    db.evento(jid, "entrega", "resultado", "ok", dados={"status": "PARCIAL — PENDÊNCIAS"})
    feitas = _fila_falsa(monkeypatch)

    async def sem_ia(*a, **k):
        return None
    monkeypatch.setattr(leitor_anuncio, "ler", sem_ia)
    monkeypatch.setattr(O, "ESPERA_REMONTAR", 0.3)
    O._ativos.add(jid)                                       # o trabalho está montando

    async def cenario():
        for n, link in ENVIADOS[:3]:
            body = routes.AnuncioEnviado(link=link, titulo="Casa", texto="Casa", imagem=PNG, foto_principal=PNG,
                                         acessado_em="2026-11-15T01:02:00-03:00")
            r = await routes.anuncio_enviado(jid, body, _u={})     # nada de "trabalho em execução"
            assert r["n"] == n
        await asyncio.sleep(0.6)
        assert feitas == []                                  # montando: espera terminar
        O._ativos.discard(jid)
        await asyncio.sleep(10.5)
    try:
        asyncio.run(cenario())
    finally:
        O._ativos.discard(jid)
    assert len(feitas) == 1 and feitas[0][1] == "montagem"   # três envios = uma montagem
    assert "nº 1" in feitas[0][2] and "nº 3" in feitas[0][2]


def test_so_prova_nao_remonta(monkeypatch):
    jid = _job()
    _manuais(jid)
    db.evento(jid, "entrega", "resultado", "ok", dados={"status": "PARCIAL — PENDÊNCIAS"})
    for c in db.candidatos(jid):                             # já tinham foto e data
        db.salvar_candidatos(jid, [c.model_copy(update={"foto": "mercado/x.png", "acessado_em": "2026-11-14T23:00:00-03:00"})])

    async def sem_ia(*a, **k):
        return None
    monkeypatch.setattr(leitor_anuncio, "ler", sem_ia)
    n, link = ENVIADOS[0]
    body = routes.AnuncioEnviado(link=link, titulo="Casa", texto="Casa", imagem=PNG, foto_principal=PNG,
                                 acessado_em="2026-11-15T01:02:00-03:00")
    asyncio.run(routes.anuncio_enviado(jid, body, _u={}))
    assert O.remontagem_pendente(jid) is None


def test_passos_guardados_e_respondi_tudo(monkeypatch):
    jid = _job()
    feitas = _fila_falsa(monkeypatch)

    async def cenario():
        await routes.pedir_remontagem(jid, routes.Adiar(etapa="calculo", motivo="recalcular", adiar=True), _u={})
        await routes.pedir_remontagem(jid, routes.Adiar(etapa="extracao", motivo="documento novo", adiar=True), _u={})
        await asyncio.sleep(0.2)
        assert feitas == []                                  # cada resposta guardada, sem remontar
        await routes.atualizar_laudo(jid, _u={})
        await asyncio.sleep(0.2)
    asyncio.run(cenario())
    assert len(feitas) == 1 and feitas[0][1] == "extracao"   # a etapa mais cedo vale, uma vez só
    assert O.remontagem_pendente(jid) is None
