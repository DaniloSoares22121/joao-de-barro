"""ORDEM 045 / D-100: pendências simples — erro do sistema não vai para o avaliador; tarja no laudo do
cliente é descartada (D-062); assuntos repetidos viram um cartão só; título sem código interno."""
from lovable.avaliacao import db
from lovable.avaliacao import pendencias_simples as PS


def _job():
    from datetime import date
    from lovable.avaliacao.modelos import Trabalho
    n = 70001
    while db.numero_usado(n):
        n += 1
    return db.criar_job(Trabalho(id="", numero=n, modalidade="OV", finalidade="Venda", cliente="Cliente X",
                                 tipo="Galpão", bairro="B", cidade="C", pin_maps="",
                                 data_base=date(2026, 11, 14), data_vistoria=date(2026, 11, 14)))


def _p(texto, grave=False):
    return {"texto": texto, "grave": grave}


PEND = [
    _p("revisor (redação/redação): Há identificadores internos e grafia fora do padrão. Traz \"Medição (D-027)\".", True),
    _p("revisor (visual/montagem): Na página 18, o Anexo V começa no fim da página.", True),
    _p("revisor (visual/montagem): Anexo III (páginas 15 e 16): a escritura está anexada sem tarjas visíveis.", True),
    _p("revisor (jurídica/redação): A certidão \"tem validade de 30 dias\". Esse prazo não consta de nenhum dado.", True),
    _p("montagem: referencial 01 sem foto principal do anúncio"),
    _p("montagem: referencial 02 sem foto principal do anúncio"),
    _p("selecao: revisor (ressalva): A tabela de amostras não mostra foto principal dos anúncios."),
    _p("selecao: revisor (ressalva): Os seis referenciais trazem \"Padrão e idade a conferir no anúncio\"; sem foto principal."),
    _p("revisor (visual/montagem): Mapa do item 7.1: o recorte está muito aproximado e a demarcação fica cortada.", True),
    _p("localizacao: polígono da IA grande demais para um lote; demarcado quadrado em volta do pino"),
    _p("contestação simulada (D-083), gravidade alta — pág. 8: Amostras contraditórias no cálculo.. Como reforçar: Excluir.", True),
    _p("contestação simulada (D-083), gravidade alta — pág. 9: Dispersão alta.. Como reforçar: Mostrar sem a amostra 04.", True),
]


def test_classifica_sem_codigo_e_sem_repetir():
    jid = _job()
    r = PS.classificar(jid, PEND)
    titulos = [c["titulo"] for c in r["cards"]]
    assert len(r["sozinho"]) == 3                               # códigos, anexo no fim da página, prazo sem fonte
    assert len(r["descartadas"]) == 1                           # tarja no laudo do cliente (D-062)
    assert any(x.startswith("2 anúncios sem foto") and "Enviar ao JdB" in x for x in titulos)   # 077-A5: um card só
    assert "Padrão e idade dos anúncios ainda não foram conferidos." in titulos
    assert "O mapa da localização precisa ser refeito." in titulos
    assert "A parte contrária atacaria 2 pontos do laudo. Quer reforçar?" in titulos
    assert len(titulos) == 4
    for t in titulos:
        assert "D-0" not in t and "revisor" not in t.lower() and ".jpg" not in t
    # os cartões que impedem de seguir vêm primeiro
    assert r["cards"][0]["impede"]


def test_aceitar_some_o_cartao():
    jid = _job()
    PS.aceitar(jid, "extensao")                     # 077-A5: o card da extensão
    titulos = [c["titulo"] for c in PS.classificar(jid, PEND)["cards"]]
    assert not any("sem foto" in t for t in titulos)


def test_limpar_titulo():
    assert PS.limpar_titulo("montagem: rótulo ausente (D-027) em Frente.jpg") == "Rótulo ausente em um arquivo"
