"""D-064 (ORDEM 037-1): pesquisa na internet inteira quando faltam semelhantes nos portais.

(a) consulta pronta para o Google do avaliador; (b) página de QUALQUER site enviada pela
extensão -> IA leve + trava "área do cartão × texto"; (c) o Coletor abre sozinho só os sites
que não o bloquearem. Teste com 2 páginas salvas de sites diferentes (fictícios), sem abrir
portal real: `fixtures/sites/*.html` e o que o extrator.js da extensão leu delas
(`fixtures/sites/extraido.json`, gerado no Chrome sem janela)."""
import asyncio
import json
from pathlib import Path

from lovable.avaliacao import db, routes
from lovable.avaliacao.agentes import leitor_anuncio, pesquisa
from tests.avaliacao.test_pagina_enviada import _job

SITES = Path(__file__).parent / "fixtures" / "sites"
EXTRAIDO = json.loads((SITES / "extraido.json").read_text(encoding="utf-8"))
LINK_A = "https://www.imobiliaria-alfa.test/imovel/galpao-polo-exemplo-al-3321"
LINK_B = "https://corretor-beta.test/barracao-setor-exemplo-sul"

# o que a IA leve devolveria lendo o texto (mock: o teste não gasta)
IA = {
    LINK_A: {"negocio": "venda", "preco": 5_100_000, "area_m2": 1061.39, "lote_m2": 1650,
             "bairro": "Polo Empresarial Exemplo", "endereco": "Rua Exemplo das Indústrias, nº 100",
             "tipologia": "Galpão", "padrao": "normal"},
    LINK_B: {"negocio": "venda", "preco": 4_500_000, "area_m2": 1300, "lote_m2": 3887.59,
             "bairro": "Setor Exemplo Sul", "endereco": "Avenida Exemplo Sul, Qd. 1",
             "tipologia": "Barracão", "padrao": None},
}


def _ia_falsa(monkeypatch, vistos: list):
    from lovable.avaliacao import ia

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo="", **_kw):
        url = next(u for u in IA if u in prompt)
        vistos.append((url, modelo))
        return esquema.model_validate(IA[url])
    monkeypatch.setattr(ia, "perguntar", fake)


def _corpo(nome: str, link: str) -> routes.AnuncioEnviado:
    d = dict(EXTRAIDO[nome])
    d.pop("foto_rect", None)
    d["link"] = link
    return routes.AnuncioEnviado(**d)


def test_extrator_leu_as_duas_paginas():
    a, b = EXTRAIDO["imobiliaria_a.html"], EXTRAIDO["corretor_b.html"]
    assert a["preco"] == 5_100_000 and a["area_m2"] == 1650       # o "cartão" trazia o TERRENO
    assert b["preco"] == 4_500_000 and b["area_m2"] == 1300 and b["lote_m2"] == 3887.59
    assert "1.061,39" in a["texto"] and "Avenida Exemplo Sul" in b["texto"]


def test_b_qualquer_site_ia_leve_e_trava(monkeypatch):
    jid = _job()
    vistos: list = []
    _ia_falsa(monkeypatch, vistos)
    ra = asyncio.run(routes.anuncio_enviado(jid, _corpo("imobiliaria_a.html", LINK_A), _u={}))
    rb = asyncio.run(routes.anuncio_enviado(jid, _corpo("corretor_b.html", LINK_B), _u={}))
    assert {u for u, _ in vistos} == {LINK_A, LINK_B}
    assert all(m == leitor_anuncio.modelo_leve() for _, m in vistos)     # modelo leve
    c = {r.link: r for r in db.candidatos(jid)}
    a, b = c[LINK_A], c[LINK_B]
    # site A: área do cartão (1.650 = terreno) ≠ construída do texto -> R$/m² pela do texto
    assert a.area_m2 == 1061.39 and ra["unitario"] == round(5_100_000 / 1061.39, 2)
    assert "TERRENO" in a.observacao and "F-S003" in a.observacao
    assert a.rua.startswith("Rua Exemplo das Indústrias") and a.tipologia
    assert a.portal == "imobiliaria-alfa.test" and a.fonte_coleta == "avaliador"
    # site B: áreas batem, sem aviso
    assert b.area_m2 == 1300 and rb["unitario"] == round(4_500_000 / 1300, 2)
    assert "TERRENO" not in b.observacao and b.rua.startswith("Avenida Exemplo Sul")
    assert b.lote_m2 == 3887.59


def test_a_consulta_e_botao_google():
    jid = _job()
    q = pesquisa.consulta_internet(jid)
    assert q == "galpão Polo Empresarial Goiás Aparecida de Goiânia venda"
    assert pesquisa.url_google(q).startswith("https://www.google.com/search?q=galp%C3%A3o+Polo+")
    r = asyncio.run(routes.links_busca(jid, _u={}))
    assert r["internet"]["url"] == pesquisa.url_google(q)
    assert r["internet"]["semelhantes"] == 0 and r["internet"]["minimo"] == 5


def test_075_texto_da_l9_sem_pesquisa_automatica(monkeypatch):
    from lovable.avaliacao import rotas_conversa as R
    jid = _job()
    s = R.situacao_pesquisa(jid, {"tipo": "Casa"}, [])
    assert s["motivo"] == "Escolha os anúncios. Pesquise no seu Chrome e envie com a extensão, ou cadastre à mão."
    seis = [{"n": i, "fonte_coleta": "manual"} for i in range(6)]
    assert R.situacao_pesquisa(jid, {"tipo": "Casa"}, seis)["motivo"] == "Você adicionou 6 anúncios. Escolha os que entram no laudo."
