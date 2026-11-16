"""113-1c: o quadro do item 6 diz o anexo em que o documento sai de verdade (a fatura SANEAGO, comprovante de endereço
do imóvel, sai no Anexo III — a redação escrevia Anexo IV)."""
from types import SimpleNamespace

from lovable.avaliacao import docx_builder as D


def test_saneago_no_anexo_do_imovel(monkeypatch):
    rot = {"docs/escritura.pdf": "Escritura particular de doação e outras avenças",
           "docs/fatura.pdf": "Fatura de água e esgoto SANEAGO referência jan/2026",
           "docs/cnh.pdf": "Carteira Nacional de Habilitação digital CNH-e do solicitante"}
    monkeypatch.setattr(D, "_arquivos_doc", lambda ctx: (["docs/escritura.pdf", "docs/fatura.pdf"], ["docs/cnh.pdf"]))
    monkeypatch.setattr(D, "mapa_digital", lambda job: ("mapa_digital/m.png", {}))
    monkeypatch.setattr(D, "_rotulo_extraido", lambda ctx, r, completo=False: rot[r])
    linhas = [["Escritura particular de doação e outras avenças – matrícula 1", "Contratante", "—", "Anexo III"],
              ["Consulta pública ao cadastro imobiliário – Mapa Digital Fácil", "Avaliador", "—", "Anexo IV"],
              ["Carteira Nacional de Habilitação digital (CNH-e) – solicitante", "Contratante", "—", "Identificação – Anexo III"],
              ["Fatura de água e esgoto SANEAGO – referência jan/2026 – Rua X", "Contratante", "—",
               "Comprovante de endereço do imóvel avaliando – Anexo IV"],
              ["Fotografias da vistoria", "Avaliador", "13/11/2026", "Item 7.5"]]
    D._anexo_real_no_quadro(SimpleNamespace(job="j"), linhas)
    assert [ln[3] for ln in linhas] == ["Anexo III", "Anexo III", "Identificação – Anexo IV",
                                        "Comprovante de endereço do imóvel avaliando – Anexo III", "Item 7.5"]


def test_data_do_proprio_documento_134(tmp_path):
    """134-3: a data do quadro do item 6 é a que o documento declara ("DATA EMISSÃO: 11/11/2026"), não a DITCD."""
    import pymupdf
    (tmp_path / "documento").mkdir()
    for nome, txt in (("relatorio-fipe-urbano", "VALOR MEDIO DE MERCADO - FIPE 10:42 DATA EMISSÃO: 11/11/2026 HORA"),
                      ("comunicado-malha", "Comunicado de divergência. Goiânia, 28/10/2026.")):
        with pymupdf.open() as d:
            d.new_page().insert_text((40, 60), txt, fontsize=9)
            d.save(tmp_path / "documento" / f"{nome}.pdf")
    linhas = [["Valor médio de mercado de imóvel urbano – FIPE (SEFAZ-GO)", "Contratante", "28/10/2026", "x"],
              ["Comunicado de divergência em malha fiscal", "Contratante", "28/10/2026", "x"],
              ["Fotografias da vistoria", "Avaliador", "13/11/2026", "Item 7.5"]]
    D._data_do_proprio_documento(SimpleNamespace(pasta=tmp_path), linhas)
    assert [ln[2] for ln in linhas] == ["11/11/2026", "28/10/2026", "13/11/2026"]
