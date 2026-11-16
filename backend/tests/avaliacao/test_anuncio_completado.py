"""ORDEM 029-5: "Enviar este anúncio" (extensão 1.0.3) num referencial que JÁ está na lista
(o Coletor não abriu a página) completa o mesmo nº com foto principal, print e dados."""
import asyncio
import base64

from lovable.avaliacao import db, routes
from lovable.avaliacao.agentes import leitor_anuncio
from lovable.avaliacao.modelos import Referencial
from tests.avaliacao.test_pagina_enviada import ZAP, _job

PNG = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                  "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()
LINK = f"{ZAP}venda-galpao-polo-empresarial-goias-aparecida-de-goiania-9/"


def _lista(jid: str) -> None:
    db.salvar_candidatos(jid, [Referencial(
        n=1, link=LINK, portal="ZAP Imóveis", bairro="Polo Empresarial Goiás", area_m2=2000,
        tipologia="Galpão", padrao="", idade_aparente="",
        preco=5_000_000, descricao="Padrão e idade a conferir no anúncio.", escolhido=True,
        decisao="entra", coletado=False, bloqueado=True)])
    db.evento(jid, "selecao", "resultado", "teste", dados={
        "refs": [db.candidatos(jid)[0].model_dump(mode="json")], "unitario_adotado": None,
        "faixa_pct": "10", "confirmado": True})


def test_envio_completa_o_mesmo_referencial(monkeypatch):
    jid = _job()
    _lista(jid)

    async def leitor(job_id, captura, portal, comuns=frozenset()):
        assert "Galpão em condomínio" in captura.texto
        return Referencial(n=0, link=captura.url_final, portal=portal, bairro="", tipologia="", padrao="médio",
                           idade_aparente="10 anos", descricao="Galpão com pé-direito de 12 m.")
    monkeypatch.setattr(leitor_anuncio, "ler", leitor)
    body = routes.AnuncioEnviado(link=LINK + "?utm=x", titulo="Galpão 2.100 m²", preco=5_200_000,
                                 area_m2=2100, texto="Galpão em condomínio, 2.100 m², R$ 5.200.000",
                                 imagem=PNG, foto_principal=PNG)
    r = asyncio.run(routes.anuncio_enviado(jid, body, _u={}))
    assert r["n"] == 1 and r["atualizado"] and r["foto"]
    cands = db.candidatos(jid)
    assert len(cands) == 1                      # não criou outro
    c = cands[0]
    assert c.escolhido and c.coletado and not c.bloqueado
    # 082-2: preço e área guardados não mudam; o que a página mostra diferente vira pergunta
    assert (c.preco, c.area_m2, c.padrao, c.idade_aparente) == (5_000_000, 2000, "médio", "10 anos")
    assert c.divergencia_pagina == {"preco": 5_200_000, "area_m2": 2100}
    assert "a conferir" not in c.descricao
    assert c.foto.endswith("-foto.png") and (db.pasta(jid) / c.foto).exists()
    assert c.print_.endswith("-pagina.png")
    # a seleção gravada (Confirmar valor) usa a cópia nova
    sel = db.resultado(jid, "selecao")
    assert sel["refs"][0]["foto"] == c.foto and sel["refs"][0]["escolhido"]


def test_envio_sem_ia_tira_a_conferir(monkeypatch):
    jid = _job()
    _lista(jid)

    async def falha(*a, **k):
        raise RuntimeError("IA fora")
    monkeypatch.setattr(leitor_anuncio, "ler", falha)
    body = routes.AnuncioEnviado(link=LINK, texto="Galpão", imagem=PNG)
    r = asyncio.run(routes.anuncio_enviado(jid, body, _u={}))
    c = db.candidatos(jid)[0]
    assert r["atualizado"] and c.foto.endswith("-pagina.png")    # sem recorte: a tela
    assert c.descricao == "" and (c.preco, c.area_m2) == (5_000_000, 2000)
