"""L200 (Caso W): o "Decide você" não escolhe o mesmo imóvel duas vezes (ZAP e Viva Real) nem anúncio de padrão
alto ou novo para um avaliando que não é (o padrão e a idade lidos no anúncio contam)."""
import asyncio
from datetime import date

from lovable.avaliacao import db, rotas_conversa
from lovable.avaliacao.modelos import Campo, Referencial, Trabalho
from tests.avaliacao.conftest import numero_unico


def _job() -> str:
    db.init()
    jid = db.criar_job(Trabalho(id="", numero=numero_unico(), modalidade="OV", finalidade="Venda", cliente="Teste",
                                tipo="Sobrado residencial", bairro="Setor Exemplo", cidade="Goiânia", pin_maps="",
                                data_base=date(2026, 10, 16), data_vistoria=date(2026, 10, 16)))
    db.salvar_campos(jid, [Campo(nome="area_construida", valor=300.0, origem="documento", fonte="iptu.png")])
    return jid


def _r(n, area, preco, portal="ZAP Imóveis", padrao="", idade="", rec=True, tip="sobrado", foto=""):
    return Referencial(n=n, link=f"https://www.exemplo.invalid/{portal[:3].lower()}/{n}", portal=portal, bairro="Setor Exemplo",
                       tipologia=tip, quartos=3, area_m2=area, preco=preco, padrao=padrao, idade_aparente=idade,
                       pontos=10, recomendado=rec, descricao="sobrado de exemplo", lote_m2=None, suites=None, foto=foto)


def test_decide_sem_repetido_e_sem_padrao_alto_ou_novo():
    jid = _job()
    db.salvar_candidatos(jid, [
        _r(1, 200, 600000), _r(2, 200, 600000, portal="Viva Real"),          # o mesmo imóvel em dois portais
        _r(3, 180, 1000000, padrao="alto", idade="novo"),                     # alto e novo: destoa do avaliando
        _r(8, 180, 1000000, portal="Viva Real"),                              # o mesmo do 3, não lido: fora também
        _r(4, 250, 700000), _r(5, 280, 800000), _r(6, 300, 900000), _r(7, 320, 950000, rec=False)])
    r = asyncio.run(rotas_conversa.responder_alinhamento(jid, rotas_conversa.Resposta(id="decide", resposta=""), _u={}))
    assert sorted(r["escolhidos"]) == [1, 4, 5, 6, 7]


def test_decide_so_mesma_tipologia_e_diz_quantos_faltam():
    jid = _job()
    db.salvar_candidatos(jid, [_r(1, 200, 600000), _r(2, 250, 700000), _r(3, 290, 1376000, tip="casa"),
                               _r(4, 235, 1250000, tip="casa térrea")])
    r = asyncio.run(rotas_conversa.responder_alinhamento(jid, rotas_conversa.Resposta(id="decide", resposta=""), _u={}))
    assert sorted(r["escolhidos"]) == [1, 2] and "faltam 3" in r["decidido"]


def test_decide_escolhe_a_amostra_mais_homogenea_e_diz_o_cv():
    jid = _job()
    db.salvar_candidatos(jid, [_r(1, 200, 1100000),                         # 5.500/m²: destoa dos outros
                               _r(2, 300, 960000), _r(3, 280, 900000), _r(4, 320, 1000000),
                               _r(5, 290, 950000), _r(6, 310, 1010000), _r(7, 250, 600000)])   # 2.400/m²
    r = asyncio.run(rotas_conversa.responder_alinhamento(jid, rotas_conversa.Resposta(id="decide", resposta=""), _u={}))
    assert sorted(r["escolhidos"]) == [2, 3, 4, 5, 6] and "CV da amostra" in r["decidido"] and "acima de 15%" not in r["decidido"]


def test_decide_prefere_anuncio_ja_aberto():
    jid = _job()
    db.salvar_candidatos(jid, [_r(i, 300, 900000 + i * 1000, foto=f"mercado/{i}.jpg") for i in range(1, 6)]
                         + [_r(i, 300, 960000 + i * 1000) for i in range(6, 12)])          # só cartão, sem foto
    r = asyncio.run(rotas_conversa.responder_alinhamento(jid, rotas_conversa.Resposta(id="decide", resposta=""), _u={}))
    assert sorted(r["escolhidos"]) == [1, 2, 3, 4, 5]


def test_decide_nao_deixa_o_fora_da_curva_da_lista_tirar_os_antigos_simples():
    """A lista riscou os sobrados de R$ 3.200/m² contra uma mediana puxada pelos novos de R$ 5.500/m²."""
    jid = _job()
    caros = [_r(i, 200, 1100000, padrao="alto", foto="f") for i in range(1, 5)]                  # 5.500/m², alto
    simples = [_r(i, 300, 960000 + i * 3000, foto="f").model_copy(update={
        "nao_recomendado": True, "recomendado": False,
        "motivo": "preço fora da curva (R$ 3.200,00/m² × mediana R$ 5.500,00/m²)"}) for i in range(5, 10)]
    db.salvar_candidatos(jid, caros + simples)
    r = asyncio.run(rotas_conversa.responder_alinhamento(jid, rotas_conversa.Resposta(id="decide", resposta=""), _u={}))
    assert sorted(r["escolhidos"]) == [5, 6, 7, 8, 9]


def test_padrao_e_idade_do_avaliando_sao_perguntados_e_o_decide_nao_responde():
    jid = _job()
    db.salvar_candidatos(jid, [_r(i, 300, 900000 + i * 1000) for i in range(1, 6)])
    ali = asyncio.run(rotas_conversa.alinhamento(jid, _u={}))
    ids = [p["id"] for p in ali["pontos"]]
    assert "padrao" in ids and "idade" in ids
    r = asyncio.run(rotas_conversa.responder_alinhamento(jid, rotas_conversa.Resposta(id="decide", resposta=""), _u={}))
    assert {"padrao", "idade"} <= {p["id"] for p in r["pontos"]}          # continuam abertos: são do avaliador
    asyncio.run(rotas_conversa.responder_alinhamento(jid, rotas_conversa.Resposta(id="padrao", resposta="Simples"), _u={}))
    asyncio.run(rotas_conversa.responder_alinhamento(jid, rotas_conversa.Resposta(id="idade", resposta="Mais de 30 anos"), _u={}))
    cs = {c.nome: c.valor for c in db.campos(jid)}
    assert cs["padrao_construtivo"] == "Simples" and cs["idade_aparente"] == "Mais de 30 anos"
    assert not {"padrao", "idade"} & {p["id"] for p in asyncio.run(rotas_conversa.alinhamento(jid, _u={}))["pontos"]}


def test_avaliando_simples_nao_leva_anuncio_com_piscina_ou_gourmet():
    from lovable.avaliacao.modelos import Campo
    jid = _job()
    db.salvar_campos(jid, [Campo(nome="padrao_construtivo", valor="Simples", origem="vistoria", fonte="avaliador")])
    caros = [_r(i, 300, 990000 + i * 1000).model_copy(update={"descricao": "sobrado com piscina e espaço gourmet"})
             for i in (1, 2)]
    db.salvar_candidatos(jid, caros + [_r(i, 300, 900000 + i * 1000) for i in range(3, 8)])
    r = asyncio.run(rotas_conversa.responder_alinhamento(jid, rotas_conversa.Resposta(id="decide", resposta=""), _u={}))
    assert not {1, 2} & set(r["escolhidos"]) and len(r["escolhidos"]) == 5


def test_faixa_de_idade_vale_o_comeco():
    """L200 (Caso M): "5 a 15 anos" virava 15 (antigo) e tirava os anúncios novos do mesmo condomínio."""
    from lovable.avaliacao.agentes import pesquisa
    from lovable.avaliacao.modelos import Campo
    jid = _job()
    db.salvar_campos(jid, [Campo(nome="idade_aparente", valor="5 a 15 anos", origem="vistoria", fonte="avaliador")])
    assert pesquisa.avaliando(jid).antigo is False
    db.salvar_campos(jid, [Campo(nome="idade_aparente", valor="15 a 30 anos", origem="vistoria", fonte="avaliador")])
    assert pesquisa.avaliando(jid).antigo is True


def test_idade_nao_confunde_com_cidade_ou_unidade():
    from lovable.avaliacao.agentes import pesquisa
    from lovable.avaliacao.modelos import Campo
    jid = _job()
    db.salvar_campos(jid, [Campo(nome="unidade", valor="Apartamento nº 1.203", origem="documento", fonte="iptu"),
                           Campo(nome="cidade_uf", valor="Goiânia – GO", origem="documento", fonte="iptu"),
                           Campo(nome="idade_aparente", valor="5 a 15 anos", origem="vistoria", fonte="avaliador")])
    assert pesquisa.avaliando(jid).antigo is False
