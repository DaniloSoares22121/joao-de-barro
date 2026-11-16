"""ORDEM 101: a conferência pega número de documento trocado (o caso do 9125) e a frase do CV vetada pelo avaliador."""
from decimal import Decimal

import pymupdf

from lovable.avaliacao import coerencia as C

DOC = {"declarado": Decimal("155694.94"), "referência": Decimal("448335.57"), "FIPE": Decimal("295124.02"),
       "venal": Decimal("155694.94")}


def _pdf(tmp_path, linhas):
    arq = tmp_path / "laudo.pdf"
    with pymupdf.open() as d:
        pg = d.new_page()
        for i, ln in enumerate(linhas):
            pg.insert_text((25, 50 + 18 * i), ln, fontsize=7)
        d.save(arq)
    return arq


def _esp(cv_fora=False):
    return C.Esperado(valor_adotado=Decimal("173000.00"), area=Decimal("106.24"), unitario=Decimal("1627.03"),
                      doc_valores=DOC, doc_numeros={"matrícula": ["100.200", "40.800"]}, cv_fora=cv_fora)


def test_o_caso_do_9125(tmp_path):
    linhas = ["Valores do procedimento, distintos do valor de mercado:",
              "• R$ 173.000,00, valor declarado no ITCD, igual ao valor venal do IPTU 2025;",
              "• R$ 448.335,57, valor total de referência atribuído pela SEFAZ;",
              "O valor médio FIPE é composto por terreno de 106,24 m² × R$ 1.627,03/m² e construção.",
              "Referencial 01: R$ 250.000,00 ÷ 139,00 m² = R$ 1.798,56/m²",
              "Matrícula nº 100.200 do 2º Registro de Imóveis (matrícula de origem 40.800).",
              "Sem ele, o coeficiente de variação seria de 24,87%."]
    difs = C.conferir(_pdf(tmp_path, linhas), None, _esp(cv_fora=True)).diferencas
    dados = {d.dado for d in difs}
    assert any(d.dado == "valor declarado (documento)" and d.esperado == "R$ 155.694,94" for d in difs), difs
    assert "conta da FIPE (documento)" in dados and "frase vetada pelo avaliador (D-068)" in dados
    assert not [d for d in difs if d.dado in ("valor referência (documento)", "valor venal (documento)",
                                              "matrícula (documento)")], difs     # o que está certo não acusa
    assert C.substituicoes(C.Resultado(diferencas=difs)) == []                       # nada disso é trocado sozinho


def test_laudo_certo_nao_acusa(tmp_path):
    linhas = ["• R$ 155.694,94, valor declarado no ITCD, igual ao valor venal do IPTU 2025;",
              "• R$ 448.335,57, valor total de referência atribuído pela SEFAZ;",
              "O valor médio FIPE de R$ 295.124,02 é composto por terreno de 300,00 m² × R$ 397,60/m².",
              "Valor de mercado: R$ 173.000,00"]
    difs = C.conferir(_pdf(tmp_path, linhas), None, _esp()).diferencas
    assert not [d for d in difs if "documento" in d.dado or "D-068" in d.dado], difs


def test_104_matricula_de_origem_nao_e_erro(tmp_path):
    linhas = ["O imóvel está registrado sob o R-1 da Matrícula nº 100.200 do 2º Registro de Imóveis.",
              "O corpo da escritura menciona a Matrícula nº 40.800 como origem.",
              "Outra citação: matrícula nº 77.777 do imóvel."]
    esp = C.Esperado(doc_numeros={"matrícula": ["100.200"]})
    difs = [d for d in C.conferir(_pdf(tmp_path, linhas), None, esp).diferencas if d.dado == "matrícula (documento)"]
    assert [d.encontrado for d in difs] == ["77.777"]          # a de origem passa; a errada de verdade continua acusada
