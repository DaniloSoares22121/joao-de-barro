"""120: lista numerada de erros (página, item, no laudo, lugares, sugestão); conta do sistema nunca vai ao avaliador."""
from datetime import date

from lovable.avaliacao import db, pendencias_simples as PS
from lovable.avaliacao.modelos import Trabalho


def test_lista_numerada_e_d100(monkeypatch):
    db.init()
    jid = db.criar_job(Trabalho(id="", numero=1, modalidade="AM", finalidade="ITCD", cliente="F", tipo="Casa",
                                bairro="Jardim Curitiba", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
                                data_base=date(2026, 11, 13), data_vistoria=date(2026, 11, 13)))
    itens = [{"texto": "data-base: capa traz 28/10/2026", "dado": "data-base (duas datas de referência no laudo)",
              "lugares": [{"pagina": 1, "trecho": "28 de outubro de 2026"}, {"pagina": 2, "trecho": "13/11/2026"}],
              "do_avaliador": True, "sugestao": "Usar 13/11/2026 (data da vistoria) em todo o laudo",
              "valor_sugerido": "13/11/2026"},
             {"texto": "nº de amostras: traz 12 referenciais", "dado": "nº de amostras", "lugares": [],
              "do_avaliador": False, "sugestao": "", "valor_sugerido": ""}]
    db.evento(jid, "entrega", "resultado", "PARCIAL", dados={"status": "PARCIAL", "arquivos": [], "pendencias": [],
                                                             "coerencia": {"ok": False, "itens": itens}})
    pend = [{"texto": "conferência de coerência (D-084): 2 diferenças — …", "grave": True},
            {"texto": "revisor (redação/redação): Item 9.3 (_revisao/pagina-11.png): erro de concordância em 'construção novo'.",
             "grave": True},
            {"texto": "Não consegui fazer: Na página 5: trocar a foto — porque a foto não foi trocada", "grave": True}]
    r = PS.classificar(jid, pend)
    card = next(c for c in r["cards"] if c["chave"] == "texto_jdb")
    erros = card["erros"]
    assert [e["n"] for e in erros] == [1, 2, 3] and [e["pagina"] for e in erros] == [1, 5, 11]
    assert erros[0]["titulo"] == "As datas de referência do valor não batem." and erros[0]["campo"] == "data_base"
    assert erros[0]["valor_sugerido"] == "13/11/2026" and len(erros[0]["lugares"]) == 2
    assert erros[1]["tipo"] == "pedido" and "Motivo: a foto não foi trocada" in erros[1]["no_laudo"]
    assert erros[2]["item"] == "9.3" and erros[2]["no_laudo"] == "construção novo"
    assert not any("12 referenciais" in e["titulo"] for e in erros)            # D-100: conta do sistema não vai
    assert any("12 referenciais" in x for x in r["sozinho"]) and card["impede"]


def test_134_repetidos_viram_um():
    erros = PS._lista_de_erros({"a": "revisor (redação/redação): Item 7.3: área do lote 286,09 m² × 286,10 m² da escritura.",
                                "b": "revisor (visual/montagem): Pág. 21: no Mapa Fácil a área 286,09 m² e no texto 286,10 m².",
                                "c": "revisor (redação/redação): Item 9.3: 'construção novo'."}, [], [])
    assert len(erros) == 2 and [e["n"] for e in erros] == [1, 2]
