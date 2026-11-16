"""115-c: o laudo com duas datas de referência (capa/cabeçalho/resumo 28/10/2026 × corpo "na data da vistoria,
13/11/2026") é barrado pela conferência (D-084) — a Revisão 5 do nº 1 passou como "tudo igual"."""
from datetime import date

import pymupdf

from lovable.avaliacao import coerencia as C


def _pdf(tmp_path, paginas):
    arq = tmp_path / "laudo.pdf"
    with pymupdf.open() as d:
        for txt in paginas:
            pg = d.new_page()
            for i, linha in enumerate(txt.split("\n")):
                pg.insert_text((40, 60 + 14 * i), linha, fontsize=8)
        d.save(arq)
    return arq


CAPA = "PTAM N.º 1 – Não judicial · Data-base 28/10/2026\nData-base da avaliação: 28 de outubro de 2026"
RESUMO = "PTAM N.º 1 – Não judicial · Data-base 28/10/2026\n12. RESUMO\nData-base da avaliação 28/10/2026"


def test_duas_datas_bloqueia(tmp_path):
    item1 = ("PTAM N.º 1 – Não judicial · Data-base 28/10/2026\n"
             "1. Determinar o valor de mercado do imóvel avaliando na data da vistoria, 13/11/2026, para fins de ITCD.")
    difs = C.conferir(_pdf(tmp_path, [CAPA, item1, RESUMO]), None, C.Esperado()).diferencas
    duas = [d for d in difs if d.dado == C.DUAS_DATAS]
    assert duas and duas[0].pagina == "pág. 2" and duas[0].encontrado.startswith("13/11/2026"), difs
    assert "28/10/2026" in duas[0].esperado
    assert C.DUAS_DATAS not in C._SUBSTITUIVEIS                     # não é troca automática: bloqueia


def test_mesma_data_nao_acusa(tmp_path):
    item1 = ("PTAM N.º 1 – Não judicial · Data-base 28/10/2026\n"
             "1. Determinar o valor de mercado do imóvel avaliando na data-base de 28/10/2026.\n"
             "Data de referência do valor: 28/10/2026. A vistoria foi feita em 13/11/2026.")
    difs = C.conferir(_pdf(tmp_path, [CAPA, item1, RESUMO]), None, C.Esperado(data_base=date(2026, 10, 28))).diferencas
    assert not [d for d in difs if d.dado.startswith("data-base")], difs


def test_bairro_como_no_documento_117(tmp_path):
    """117 (D-131): "Jardim Curitiba I" no documento; "Jardim Curitiba" sozinho na capa acusa."""
    capa = "Imóvel: Rua XV 9, Qd. 59, Lt. 2 – Jardim Curitiba, Goiânia"
    corpo = "O imóvel fica no Jardim Curitiba I, em Goiânia. Setor Jardim Curitiba I (conta de água)."
    difs = C.conferir(_pdf(tmp_path, [capa, corpo]), None, C.Esperado(bairro="Jardim Curitiba I")).diferencas
    b = [d for d in difs if d.dado == C.BAIRRO]
    assert len(b) == 1 and b[0].pagina == "pág. 1" and b[0].esperado == "Jardim Curitiba I", difs
    # sem número no fim do nome, não confere (a versão curta não é outro setor)
    assert not [d for d in C.conferir(_pdf(tmp_path, [capa]), None, C.Esperado(bairro="Vila Finsocial")).diferencas
                if d.dado == C.BAIRRO]


def test_numero_da_pagina_nao_e_contagem_118(tmp_path):
    """118-4: "Pág. 12" no rodapé seguido de "referenciais dividida…" não é "12 referenciais"."""
    pg = ("Os 6 referenciais da amostra apresentaram valor unitário médio de R$ 1.627,03\n"
          "Alan Soares da Silva · CRECI 36507/GO · Pág. 12 referenciais dividida pelo número de referenciais")
    difs = C.conferir(_pdf(tmp_path, [pg]), None, C.Esperado(n_amostras=6)).diferencas
    assert not [d for d in difs if d.dado == "nº de amostras"], difs
    difs = C.conferir(_pdf(tmp_path, ["Foram usados 7 referenciais na conta."]), None, C.Esperado(n_amostras=6)).diferencas
    assert [d for d in difs if d.dado == "nº de amostras"]                 # contagem errada de verdade acusa


def test_lista_da_tela_120(tmp_path):
    """120: cada diferença traz os lugares, se é do avaliador e a sugestão de um toque; [Mostrar no PDF] realça."""
    from lovable.avaliacao import rotas_amostra as R
    capa = "Data-base da avaliação: 28 de outubro de 2026\nImóvel Avaliado: Casa – Rua X, Qd. 1, Lt. 2, Jardim Curitiba, Goiânia"
    pdf = _pdf(tmp_path, [capa, "Foram usados 7 referenciais."])
    difs = C.conferir(pdf, None, C.Esperado(data_base=date(2026, 11, 13), bairro="Jardim Curitiba I",
                                            n_amostras=6)).diferencas
    data = next(d for d in difs if d.dado == "data-base")
    assert data.do_avaliador and data.lugares == [{"pagina": 1, "trecho": "28 de outubro de 2026"}]
    assert data.valor_sugerido == "13/11/2026" and "data da vistoria" in data.sugestao
    bairro = next(d for d in difs if d.dado == C.BAIRRO)
    assert bairro.do_avaliador and bairro.valor_sugerido == "Jardim Curitiba I"
    conta = next(d for d in difs if d.dado == "nº de amostras")
    assert conta.do_avaliador is False                                  # erro de conferência não vai ao avaliador
    png, achou = R.pagina_realcada(pdf, 1, "28 de outubro de 2026", 400)
    assert achou and png[:4] == b"\x89PNG"
    assert R.pagina_realcada(pdf, 2, "não existe aqui", 400)[1] is False


def test_resto_de_data_base_vira_troca_sozinha_126(tmp_path):
    """126-3b (D-127): "data-base" que sobrou nas frases fixas vira troca exata, aplicada sozinha (não vai ao avaliador)."""
    pgs = ["Data da vistoria da avaliação: 13/11/2026",
           "10. O valor foi determinado na data-base da avaliação. A data-base indicada foi considerada."]
    res = C.conferir(_pdf(tmp_path, pgs), None, C.Esperado(data_base=date(2026, 11, 13), data_vistoria=date(2026, 11, 13)))
    restos = [d for d in res.diferencas if d.dado == C.RESTO_DATA_BASE]
    assert {(d.encontrado, d.esperado) for d in restos} == {("Data da vistoria da avaliação", "Data da vistoria"),
                                                           ("na data-base da avaliação", "na data da vistoria"),
                                                           ("data-base indicada", "data da vistoria")}
    assert all(not d.do_avaliador for d in restos)
    pares = C.substituicoes(res)
    assert ("na data-base da avaliação", "na data da vistoria") in pares and ("data-base indicada", "data da vistoria") in pares
