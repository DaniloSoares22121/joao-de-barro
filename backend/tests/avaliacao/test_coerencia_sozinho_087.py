"""ORDEM 087: diferença da conferência de coerência é erro do JdB — vira troca de texto que a montagem aplica sozinha."""
from lovable.avaliacao import coerencia as C


def test_trocas_seguras():
    r = C.Resultado(diferencas=[
        C.Diferenca("valor adotado", "pág. 10", "R$ 173.001,00", "R$ 173.000,00"),
        C.Diferenca("valor por extenso", "pág. 9", "(Cento e setenta e três mil e um reais)", "(Cento e setenta e três mil reais)"),
        C.Diferenca("data-base", "pág. 1", "13/11/2026", "28/10/2026"),
        C.Diferenca("valor adotado", "laudo", "não encontrado", "R$ 173.000,00"),          # sem troca exata
        C.Diferenca("planilha: Área do terreno", "aba Imovel", "vazio", "o mesmo dado do laudo"),
        C.Diferenca("valor adotado", "pág. 12", "R$ 173.001,00", "R$ 173.000,00"),         # repetida: uma troca só
    ])
    r.conferidos["valor_do_trabalho"] = True                  # o esperado veio do trabalho (como na montagem)
    # 100-1: valor, extenso e data-base NUNCA são trocados sozinhos (podem ser de outro documento)
    assert C.substituicoes(r) == []
    r.diferencas.append(C.Diferenca("número do laudo", "pág. 2", "9999", "9120"))
    assert C.substituicoes(r) == [("9999", "9120")]
    assert r.resumo().startswith(C.PREFIXO)


def test_troca_no_word_corpo_cabecalho_e_texto_partido(tmp_path):
    from docx import Document
    from lovable.avaliacao import docx_builder
    arq = tmp_path / "laudo.docx"
    d = Document()
    d.sections[0].header.paragraphs[0].text = "PTAM nº 9999 · Data-base 13/11/2026"
    d.add_paragraph("Valor de mercado: R$ 173.001,00")
    p = d.add_paragraph()
    p.add_run("Data-base: 13/")
    p.add_run("11/2026.")                       # partido em dois trechos
    d.save(arq)
    n = docx_builder.aplicar_substituicoes(arq, [("R$ 173.001,00", "R$ 173.000,00"), ("13/11/2026", "28/10/2026")])
    assert n == 3
    d2 = Document(arq)
    corpo = "\n".join(x.text for x in d2.paragraphs)
    assert "R$ 173.000,00" in corpo and "Data-base: 28/10/2026." in corpo and "13/11" not in corpo
    assert "28/10/2026" in d2.sections[0].header.paragraphs[0].text
    assert docx_builder.aplicar_substituicoes(arq, [("R$ 173.001,00", "R$ 173.000,00")]) == 0   # nada mais a trocar


def test_090_assinatura_antes_da_pesquisa(tmp_path):
    import pymupdf
    arq = tmp_path / "laudo.pdf"
    with pymupdf.open() as d:
        pg = d.new_page()
        pg.insert_text((40, 60), "Consulta realizada em 14 e 15/11/2026, com acesso e captura.", fontsize=9)
        pg.insert_text((40, 90), "Vistoria realizada em 14 de novembro de 2026.", fontsize=9)
        d.new_page().insert_text((40, 60), "Goiania, 14 de novembro de 2026", fontsize=9)
        d.save(arq)
    r = C.conferir(arq, None, C.Esperado())
    assert C.substituicoes(r) == [("Goiania, 14 de novembro de 2026", "Goiania, 15 de novembro de 2026")]
    with pymupdf.open() as d:
        pg = d.new_page()
        pg.insert_text((40, 60), "Consulta realizada em 14/11/2026.", fontsize=9)
        pg.insert_text((40, 90), "Goiania, 15 de novembro de 2026", fontsize=9)
        d.save(tmp_path / "ok.pdf")
    assert not [x for x in C.conferir(tmp_path / "ok.pdf", None, C.Esperado()).diferencas if x.dado == "data da assinatura"]


def test_090_sem_valor_do_trabalho_nao_troca_numero(tmp_path):
    """Sem o valor vindo do trabalho, a conferência não adivinha nem troca valor sozinha — nunca pelo 'valor de
    referência' do fisco."""
    import pymupdf
    arq = tmp_path / "laudo.pdf"
    with pymupdf.open() as d:
        pg = d.new_page()
        pg.insert_text((40, 60), "Valor de mercado: R$ 173.000,00", fontsize=9)
        pg.insert_text((40, 90), "Valor declarado R$ 155.694,94; valor de referência R$ 448.335,57", fontsize=9)
        d.save(arq)
    r = C.conferir(arq, None, C.Esperado())
    assert r.conferidos["valor"] != C.Decimal("448335.57")
    assert not any("448.335,57" in para for _, para in C.substituicoes(r))
    r.diferencas.append(C.Diferenca("valor adotado", "pág. 1", "R$ 173.000,00", "R$ 1,00"))
    assert C.substituicoes(r) == []


def test_100_numeros_de_outros_documentos_nunca_sao_trocados(tmp_path):
    """100-1 (o caso do 9125): o declarado do ITCD e a conta da FIPE não são números deste laudo."""
    import pymupdf
    from decimal import Decimal
    from docx import Document
    from lovable.avaliacao import docx_builder
    frases = ["Valor de mercado: R$ 173.000,00",
              "Valor declarado no ITCD: R$ 155.694,94, igual ao valor venal do IPTU 2025.",
              "O valor médio FIPE é composto por terreno de 300,00 m² × R$ 397,60/m² e construção de "
              "106,24 m² × R$ 1.655,15/m².",
              "Cálculo: 106,24 m² × R$ 1.627,03/m² = R$ 172.855,67"]
    pdf = tmp_path / "laudo.pdf"
    with pymupdf.open() as d:
        pg = d.new_page()
        for i, f in enumerate(frases):
            pg.insert_text((30, 60 + 20 * i), f, fontsize=8)
        d.save(pdf)
    esp = C.Esperado(valor_adotado=Decimal("173000.00"), unitario=Decimal("1627.03"), area=Decimal("106.24"))
    r = C.conferir(pdf, None, esp)
    assert not [x for x in r.diferencas if x.dado in ("valor adotado", "área do cálculo", "unitário na conta")], r.diferencas
    assert C.substituicoes(r) == []
    # mesmo que viesse uma troca, a frase sobre outro documento não é reescrita no Word
    arq = tmp_path / "laudo.docx"
    doc = Document()
    for f in frases:
        doc.add_paragraph(f)
    doc.save(arq)
    docx_builder.aplicar_substituicoes(arq, [("R$ 155.694,94", "R$ 173.000,00"), ("300,00 m²", "106,24 m²")])
    texto = "\n".join(p.text for p in Document(arq).paragraphs)
    assert "Valor declarado no ITCD: R$ 155.694,94" in texto and "terreno de 300,00 m² × R$ 397,60/m²" in texto
