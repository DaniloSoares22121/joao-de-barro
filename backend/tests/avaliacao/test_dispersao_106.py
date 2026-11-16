"""ORDEM 106 (D-068, regra do projeto): nada sobre dispersão dos referenciais no laudo — acusa e remove."""
from lovable.avaliacao.coerencia import frases_dispersao, sem_dispersao

ITEM10 = ("A amostra apresenta dispersão elevada entre os valores unitários, característica de mercado raso, em que as "
          "ofertas disponíveis no segmento são poucas e heterogêneas. O tratamento da dispersão consta da planilha de "
          "cálculo que acompanha o presente parecer. Considerando essa dispersão, admite-se faixa de variação "
          "mercadológica de 10% em torno do valor adotado.")
ITEM8 = "O mercado da região é raso, com valores unitários bastante dispersos entre si."


def test_acusa_o_paragrafo_do_9127():
    assert len(frases_dispersao(ITEM10)) == 3
    assert len(frases_dispersao(ITEM8)) == 1


def test_remove_e_mantem_a_faixa():
    t = sem_dispersao(ITEM10)
    assert not frases_dispersao(t)
    assert t == "Admite-se faixa de variação mercadológica de 10% em torno do valor adotado."
    assert sem_dispersao(ITEM8) == "O mercado da região é raso."


def test_palavras_vetadas():
    for s in ("O coeficiente de variação ficou em 18%.", "O CV da amostra é aceitável.",
              "O desvio-padrão dos unitários é baixo.", "Há variabilidade nos preços ofertados.",
              "A amplitude dos valores é grande.", "Há discrepância entre as amostras.",
              "Os valores se espalham entre R$ 2.000 e R$ 4.000/m²."):
        assert frases_dispersao(s), s
        assert sem_dispersao(s) == "", s


def test_o_que_pode():
    ok = ("Trata-se de mercado raso, com poucas ofertas no segmento. A ocupação do bairro é heterogênea, com casas "
          "e comércio. Admite-se faixa de variação mercadológica de 10%.")
    assert not frases_dispersao(ok)
    assert sem_dispersao(ok) == ok


def test_contestacao_so_conversa():
    from lovable.avaliacao.agentes.contestacao import SO_CONVERSA, so_conversa
    p = {"pagina": "pág. 9", "ponto": "CV de 22% na amostra", "por_que": "amostra heterogênea", "gravidade": "alta",
         "como_reforcar": "explicar a dispersão no item 10"}
    q = so_conversa(p)
    assert q["so_conversa"] and q["como_reforcar"] == SO_CONVERSA and q["gravidade"] == "alta"
    r = {"pagina": "pág. 4", "ponto": "área sem fonte", "por_que": "não cita a matrícula", "gravidade": "alta",
         "como_reforcar": "citar a matrícula"}
    assert so_conversa(r) == r


def test_faixa_do_9121_fica():
    t = ("A faixa de variação mercadológica admitida considera essa dispersão e as oscilações inerentes ao processo "
         "de negociação, preservando-se o valor adotado como a melhor estimativa.")
    assert sem_dispersao(t) == ("A faixa de variação mercadológica admitida considera as oscilações inerentes ao "
                                "processo de negociação, preservando-se o valor adotado como a melhor estimativa.")
