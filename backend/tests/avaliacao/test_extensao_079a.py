"""ORDEM 079-A: trabalho em 'PARCIAL — PENDÊNCIAS' com 6 referenciais sem foto RECEBE anúncio pela extensão; o link
que já é referencial vai direto para o trabalho certo (sem perguntar); o envio completa o mesmo nº, sem criar um 7º."""
import asyncio

from lovable.avaliacao import db, rotas_extensao as X, routes
from lovable.avaliacao.agentes import leitor_anuncio
from tests.avaliacao.test_enviado_mesmo_link_077 import ENVIADOS, PNG, _manuais
from tests.avaliacao.test_pagina_enviada import _job


def test_parcial_recebe_e_o_link_vai_direto_para_o_trabalho(monkeypatch):
    jid = _job()
    _manuais(jid)
    db.set_etapa(jid, "entrega", "PARCIAL — PENDÊNCIAS")
    cancelado = _job()
    db.set_etapa(cancelado, "entrega", "CANCELADO")
    ids = [j["id"] for j in asyncio.run(X.trabalhos(_u={}))]
    assert jid in ids and cancelado not in ids

    async def sem_ia(*a, **k):
        return None
    monkeypatch.setattr(leitor_anuncio, "ler", sem_ia)
    n, link = ENVIADOS[1]                     # o deztop 296628655, aberto no Chrome
    for j in db.listar_jobs():                # outros testes usam os mesmos links: aqui só este trabalho está aberto
        if j["id"] not in (jid, cancelado):
            db.set_etapa(j["id"], "entrega", "CANCELADO")
    dono = asyncio.run(X.de_quem(link=link, _u={}))
    assert dono["trabalho"] == jid and dono["n"] == n and dono["recebidos"] == 0 and dono["total"] == 6
    body = routes.AnuncioEnviado(link=link, titulo="Casa 3 quartos", texto="Casa 3 quartos", imagem=PNG,
                                 foto_principal=PNG, acessado_em="2026-11-15T02:20:00Z")
    r = asyncio.run(routes.anuncio_enviado(dono["trabalho"], body, _u={}))
    assert r["n"] == n
    cands = db.candidatos(jid)
    assert len(cands) == 6, "criou um 7º"
    c = next(x for x in cands if x.n == n)
    assert c.foto and c.acessado_em
    assert X.anuncios(jid)["recebidos"] == 1


def test_aprovado_nao_recebe():
    jid = _job()
    db.evento(jid, "entrega", "aprovado", "aprovado pelo avaliador")
    assert jid not in [j["id"] for j in asyncio.run(X.trabalhos(_u={}))]


def test_mesmo_anuncio_com_com_e_com_br():
    assert X.mesmo_anuncio("https://www.deztop.com.br/imovel/296628655/casa", "https://deztop.com/br/imovel/296628655/casa-3")
    assert not X.mesmo_anuncio("https://deztop.com/br/imovel/296628655/", "https://deztop.com/br/imovel/296628656/")


def test_mesmo_link_em_dois_trabalhos_pergunta():
    """084-2: o link é referencial do 9120 e do 9121 -> a extensão não escolhe sozinha (pergunta o trabalho)."""
    a, b = _job(), _job()
    _manuais(a)
    _manuais(b)
    r = asyncio.run(X.de_quem(link=ENVIADOS[1][1], _u={}))
    assert "trabalho" not in r and {a, b} <= {x["trabalho"] for x in r["varios"]}


def test_ordem_fixa_e_o_ultimo_em_cima():
    """086-3: a lista "Para qual trabalho?" não muda de ordem a cada envio; o último que recebeu fica em cima."""
    from lovable.avaliacao import db
    a, b = _job(), _job()
    db.evento(a, "pesquisa", "edicao_manual", "anúncio nº 1 completado pelo avaliador (Chrome): foto")
    lista = asyncio.run(X.trabalhos(_u={}))
    assert lista[0]["id"] == a and lista[0]["ultimo"]
    resto = [j["numero"] for j in lista[1:]]
    assert resto == sorted(resto, reverse=True)
    assert [j["id"] for j in asyncio.run(X.trabalhos(_u={}))] == [j["id"] for j in lista]   # mesma ordem de novo


def test_091_links_colados_vao_direto_ao_trabalho_e_abrem_todos():
    """091-5: o link colado no "Adicionar anúncio" de um trabalho vai direto para ele (sem "Para qual trabalho?"),
    o trabalho que espera anúncios fica em cima e o "Abrir os anúncios" da extensão abre os colados."""
    from lovable.avaliacao import db
    jid = _job()
    for j in db.listar_jobs():                # isola de outros testes
        if j["id"] != jid:
            db.set_etapa(j["id"], "entrega", "CANCELADO")
    colados = ["https://deztop.com/br/imovel/700000001/casa", "https://www.zapimoveis.com.br/imovel/venda-casa-id-2700000002/"]
    r = asyncio.run(X.gravar_colados(jid, X.Colados(links=colados + ["isto não é link"]), _u={}))
    assert r["pendentes"] == colados
    dono = asyncio.run(X.de_quem(link="https://www.deztop.com.br/imovel/700000001/casa/", _u={}))
    assert dono["trabalho"] == jid and dono["n"] is None
    assert asyncio.run(X.trabalhos(_u={}))[0]["id"] == jid
    a = X.anuncios(jid)
    assert [f["link"] for f in a["faltam"] if f["n"] is None] == colados and a["colados"] == 2
    # chegou pela extensão (virou anúncio do trabalho): sai da fila
    from lovable.avaliacao.modelos import Referencial
    db.salvar_candidatos(jid, [Referencial(n=1, link=colados[0], portal="Deztop", bairro="B", tipologia="Casa", padrao="",
                                           idade_aparente="", descricao="", preco=1, area_m2=1, decisao="entra")])
    assert X.colados_pendentes(jid) == colados[1:]


def test_093a_link_ja_recebido_volta_a_perguntar():
    """093-A-15: o link já recebido (com foto e data) num trabalho não prende o anúncio: a extensão pergunta."""
    from lovable.avaliacao import db
    from lovable.avaliacao.modelos import Referencial
    a = _job()
    for j in db.listar_jobs():
        if j["id"] != a:
            db.set_etapa(j["id"], "entrega", "CANCELADO")
    lk = "https://www.zapimoveis.com.br/imovel/venda-casa-id-2901608902/"
    db.salvar_candidatos(a, [Referencial(n=8, link=lk, portal="ZAP", bairro="B", tipologia="Casa", padrao="", idade_aparente="",
                                         descricao="", preco=295000, area_m2=220, decisao="comparacao",
                                         foto="mercado/enviado-8-foto.jpg", acessado_em="2026-11-15T03:20:00-03:00")])
    assert asyncio.run(X.de_quem(link=lk, _u={})) == {}            # recebido: pergunta "Para qual trabalho?"
    db.salvar_candidatos(a, [db.candidatos(a)[0].model_copy(update={"foto": ""})])
    assert asyncio.run(X.de_quem(link=lk, _u={}))["trabalho"] == a  # ainda espera a foto: vai direto


def test_095_comparacao_sem_foto_entra_na_fila():
    """095-8: o link colado que já é anúncio "Só comparação" sem foto (o JC-18 no 9121) é aberto pela extensão."""
    from lovable.avaliacao import db
    from lovable.avaliacao.modelos import Referencial
    jid = _job()
    lk = "https://deztop.com/br/imovel/301959200/casa-2-dormitorios-goiania"
    db.salvar_candidatos(jid, [Referencial(n=7, link=lk, portal="Deztop", bairro="B", tipologia="Casa", padrao="", idade_aparente="",
                                           descricao="", preco=240000, area_m2=125, decisao="comparacao", escolhido=False)])
    asyncio.run(X.gravar_colados(jid, X.Colados(links=[lk]), _u={}))
    a = X.anuncios(jid)
    assert [f["link"] for f in a["faltam"]] == [lk]
    # 110-1: o contador da tela conta também a comparação ("N de 8"); a amostra, à parte, não
    assert a["total"] == 1 and a["recebidos"] == 0 and a["amostra"] == {"total": 0, "recebidos": 0}


def test_097_colado_como_comparacao_guarda_o_destino():
    jid = _job()
    lk = "https://deztop.com/br/imovel/301959200/casa-2-dormitorios-goiania"
    asyncio.run(X.gravar_colados(jid, X.Colados(links=[lk], decisao="comparacao"), _u={}))
    asyncio.run(X.gravar_colados(jid, X.Colados(links=["https://deztop.com/br/imovel/500000001/casa"]), _u={}))
    assert X.destino_colado(jid, "https://www.deztop.com.br/imovel/301959200/casa-2/") == "comparacao"
    assert X.destino_colado(jid, "https://deztop.com/br/imovel/500000001/casa") == "entra"
    assert X.destino_colado(jid, "https://deztop.com/br/imovel/999999999/x") is None
