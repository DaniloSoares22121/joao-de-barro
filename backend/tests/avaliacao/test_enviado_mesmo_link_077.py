"""ORDEM 077-5: "Enviar ao JdB" num anúncio que já foi cadastrado À MÃO (sem foto) COMPLETA o mesmo
referencial (foto, data e hora de acesso, o que faltar) — nunca cria um 7º repetido. Links no formato do 9120."""
import asyncio
import base64

import pytest

from lovable.avaliacao import db, routes
from lovable.avaliacao.agentes import leitor_anuncio
from lovable.avaliacao.modelos import Referencial
from tests.avaliacao.test_pagina_enviada import _job

PNG = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                  "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()
MANUAIS = [
    "https://www.zapimoveis.com.br/imovel/venda-casa-3-quartos-com-academia-jardim-curitiba-goiania-go-139m2-id-2845551234/",
    "https://deztop.com/br/imovel/296628655/casa-3-dormitorios-goiania",
    "https://deztop.com/br/imovel/299970092/casa-3-dormitorios-goiania",
    "https://www.zapimoveis.com.br/imovel/venda-casa-3-quartos-vila-finsocial-goiania-go-150m2-id-2901607630",
    "https://deztop.com/br/imovel/293212933/casa-3-dormitorios-goiania",
    "https://deztop.com/br/imovel/297399676/casa-3-dormitorios-goiania",
]
# como a extensão manda (origin + pathname da página aberta no Chrome) — e variações reais
ENVIADOS = [
    (1, "https://www.zapimoveis.com.br/imovel/venda-casa-3-quartos-com-academia-jardim-curitiba-goiania-go-139m2-id-2845551234/"),
    (2, "https://deztop.com/br/imovel/296628655/casa-3-dormitorios-goiania"),
    (3, "https://www.deztop.com/br/imovel/299970092/casa-3-dormitorios-goiania/"),          # com www e barra
    (4, "https://zapimoveis.com.br/imovel/venda-casa-3-quartos-vila-finsocial-goiania-go-150m2-id-2901607630/?source=ranking"),
    (5, "http://deztop.com/br/imovel/293212933/casa-3-dormitorios-goiania#fotos"),
    (6, "https://m.deztop.com/br/imovel/297399676/casa-3-dormitorios-goiania"),             # versão de celular
]


def _manuais(jid: str) -> None:
    db.salvar_candidatos(jid, [Referencial(n=i, link=lk, portal="", bairro="Jardim Curitiba", tipologia="Casa", padrao="",
                                           idade_aparente="", descricao="", preco=170_000 + i * 1000, area_m2=100 + i,
                                           escolhido=True, decisao="entra", fonte_coleta="manual", coletado=True)
                               for i, lk in enumerate(MANUAIS, 1)])


@pytest.mark.parametrize("n,link", ENVIADOS)
def test_envio_completa_o_cadastrado_a_mao(monkeypatch, n, link):
    jid = _job()
    _manuais(jid)

    async def sem_ia(*a, **k):
        return None
    monkeypatch.setattr(leitor_anuncio, "ler", sem_ia)
    body = routes.AnuncioEnviado(link=link, titulo="Casa 3 quartos", texto="Casa 3 quartos", imagem=PNG,
                                 foto_principal=PNG, acessado_em="2026-11-15T01:40:00Z")
    r = asyncio.run(routes.anuncio_enviado(jid, body, _u={}))
    cands = db.candidatos(jid)
    assert len(cands) == 6, "criou um anúncio repetido"
    assert r["n"] == n and r.get("atualizado")
    c = next(x for x in cands if x.n == n)
    assert c.foto and c.escolhido and c.fonte_coleta == "manual"
    assert (c.preco, c.area_m2) == (170_000 + n * 1000, 100 + n)       # o que já estava fica (a página não trouxe outro)


def test_outro_anuncio_entra_como_novo(monkeypatch):
    jid = _job()
    _manuais(jid)

    async def sem_ia(*a, **k):
        return None
    monkeypatch.setattr(leitor_anuncio, "ler", sem_ia)
    body = routes.AnuncioEnviado(link="https://deztop.com/br/imovel/111111111/casa-3-dormitorios-goiania", titulo="Casa",
                                 texto="Casa 3 quartos, 120 m², R$ 200.000", preco=200_000, area_m2=120, imagem=PNG,
                                 foto_principal=PNG)
    asyncio.run(routes.anuncio_enviado(jid, body, _u={}))
    assert len(db.candidatos(jid)) == 7
