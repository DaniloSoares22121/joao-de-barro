"""091-1: o JdB descartou sozinho 3 dos 6 anúncios que o avaliador enviou ("imóvel novo/em acabamento" e "várias unidades",
lidos de propaganda da página). Anúncio do avaliador nunca é descartado: só o aviso, quem tira é ele."""
from lovable.avaliacao import candidatos as C
from lovable.avaliacao.modelos import Referencial

AV = C.Avaliando(tipo="Casa", bairro="Jardim Curitiba", cidade="Goiânia", area=106.24, quartos=2, antigo=True)


def _r(desc, fonte):
    return Referencial(n=1, link="https://x/1", portal="ZAP", bairro="Jardim Curitiba", tipologia="Casa", padrao="",
                       idade_aparente="", descricao=desc, preco=180000, area_m2=110, fonte_coleta=fonte)


def test_enviado_pelo_avaliador_so_ganha_aviso():
    r = C.avaliar(_r("Casa em fase de acabamento, nunca habitada.", "avaliador"), AV)
    assert not r.nao_recomendado and "confira" in r.motivo and not r.motivo.startswith("Atenção")


def test_propaganda_da_pagina_nao_e_imovel_novo():
    r = C.avaliar(_r("Casa térrea com acabamento simples. Imóvel novo? Anuncie grátis no portal.", "coletor"), AV)
    assert "novo" not in (r.motivo or "")


def test_achado_pelo_jdb_continua_riscado():
    r = C.avaliar(_r("Lançamento: casa em construção, entrega em 2027.", "coletor"), AV)
    assert r.nao_recomendado


def test_096_1_envio_novo_grava_foto_e_print(monkeypatch):
    """096-1: na 092-1 um comentário engoliu 'foto=… print_=…' no anúncio NOVO enviado pela extensão."""
    import asyncio
    from lovable.avaliacao import db, routes
    from lovable.avaliacao.agentes import leitor_anuncio
    from tests.avaliacao.test_enviado_mesmo_link_077 import PNG
    from tests.avaliacao.test_pagina_enviada import _job

    async def sem_ia(*a, **k):
        return None
    monkeypatch.setattr(leitor_anuncio, "ler", sem_ia)
    jid = _job()
    body = routes.AnuncioEnviado(link="https://www.zapimoveis.com.br/imovel/venda-casa-3-quartos-jardim-curitiba-110m2-id-99/",
                                 titulo="Casa 3 quartos 110 m²", texto="Casa 3 quartos 110 m² R$ 200.000", preco=200000,
                                 area_m2=110, imagem=PNG, foto_principal=PNG, acessado_em="2026-11-15T04:30:00-03:00")
    r = asyncio.run(routes.anuncio_enviado(jid, body, _u={}))
    c = next(x for x in db.candidatos(jid) if x.n == r["n"])
    assert c.foto and c.print_ and c.fonte_coleta == "avaliador" and c.decisao == "entra"
