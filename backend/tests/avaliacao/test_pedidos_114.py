"""114: o quadro único — 3 pares (página, item, geral) viram 3 pedidos; par vazio ignorado; texto livre aceito."""
from lovable.avaliacao.pedidos_revisao import dividir

MODELO = "Onde fica: \nO que mudar: "


def test_tres_pares_viram_tres_pedidos():
    t = ("Onde fica: 8\nO que mudar: trocar 'construção novo' por 'construção nova'\n\n"
         "Onde fica: item 7.4\nO que mudar: tirar a frase do telhado\n\n"
         "Onde fica: \nO que mudar: revisar a concordância do laudo inteiro\n\n"
         + MODELO)
    assert dividir(t) == ["Na página 8: trocar 'construção novo' por 'construção nova'",
                          "No item 7.4: tirar a frase do telhado",
                          "revisar a concordância do laudo inteiro"]


def test_modelo_vazio_nao_e_pedido():
    assert dividir(MODELO) == [] and dividir("") == []


def test_texto_livre_continua_aceito():
    assert dividir("A área construída correta é 148 m².") == ["A área construída correta é 148 m²."]
    assert dividir("Onde fica: 7.4\nO que mudar: tirar X\n\nE também mudar o título.")[-1] == "E também mudar o título."


def test_varias_linhas_no_o_que_mudar():
    assert dividir("Onde fica: 9.3\nO que mudar: primeira linha\nsegunda linha") == ["No item 9.3: primeira linha\nsegunda linha"]


def test_rota_grava_um_pedido_por_par_e_refaz_uma_vez(monkeypatch):
    import asyncio
    from datetime import date
    from lovable.avaliacao import db, ia, orquestrador, routes, revisoes
    from lovable.avaliacao.modelos import Trabalho
    db.init()
    jid = db.criar_job(Trabalho(id="", numero=1, modalidade="AM", finalidade="Garantia", cliente="F", tipo="Casa",
                                bairro="Centro", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
                                data_base=date(2026, 11, 15), data_vistoria=date(2026, 11, 14)))
    etapas = iter(["redacao", "montagem", "calculo"])

    async def fake(sistema, prompt, esquema, **kw):
        return esquema(etapa=next(etapas), instrucao="ajustar: " + prompt.rsplit("\n", 1)[-1][:40])
    monkeypatch.setattr(ia, "perguntar", fake)
    filas = []
    monkeypatch.setattr(orquestrador, "enfileirar", lambda j: filas.append(j))
    t = ("Onde fica: 8\nO que mudar: trocar A por B\n\nOnde fica: item 7.4\nO que mudar: tirar C\n\n"
         "Onde fica: \nO que mudar: revisar a concordância\n\nOnde fica: \nO que mudar: ")
    r = asyncio.run(routes.corrigir(jid, routes.Correcao(texto=t), _u={}))
    assert r["pedidos"] == 3 and r["etapa"] == "calculo" and filas == [jid]       # uma remontagem, da etapa mais cedo
    origs = revisoes._pedidos(jid, 0, 1 << 62)
    assert origs == ["Na página 8: trocar A por B", "No item 7.4: tirar C", "revisar a concordância"]
