"""ORDEM 080 (itens 1, 2 e 3): a planilha não inventa a "Data da consulta", a aba Imovel sai dos mesmos dados do
laudo (com a fonte) e a conferência de coerência olha a aba Imovel inteira."""
from decimal import Decimal

import openpyxl
import pymupdf

from lovable.avaliacao import calculo, coerencia, db, planilha
from lovable.avaliacao.agentes import _comum
from lovable.avaliacao.modelos import Campo, Referencial
from tests.avaliacao.test_pagina_enviada import ZAP, _job


def _refs():
    base = dict(portal="ZAP Imóveis", bairro="Centro", tipologia="Casa", padrao="", descricao="", escolhido=True)
    return [Referencial(n=1, link=f"{ZAP}a/", preco=300_000, area_m2=150, idade_aparente="", acessado_em="2026-11-14T22:10:00-03:00",
                        observacao="foto e dados enviados pelo avaliador (Chrome) (D-082)", **base),
            Referencial(n=2, link=f"{ZAP}b/", preco=320_000, area_m2=160, idade_aparente="20 anos", **base),
            Referencial(n=3, link=f"{ZAP}c/", preco=310_000, area_m2=155, idade_aparente="", acessado_em="2026-11-15T01:30:00Z", **base)]


def _gerar(tmp_path, jid):
    refs = _refs()
    r = calculo.calcular(Decimal("106.24"), refs)
    return planilha.gerar(tmp_path / "p2.xlsx", _comum.trabalho(jid), Decimal("106.24"), refs, r, origem_area="documento")


def test_data_da_consulta_e_a_do_acesso_nunca_a_data_base(tmp_path, monkeypatch):
    jid = _job()
    monkeypatch.setattr(planilha, "_idade_estimada", lambda j: "30 anos (estimada)")
    wb = openpyxl.load_workbook(_gerar(tmp_path, jid))
    am = wb["Amostras"]
    datas = {am.cell(i, 1).value: am.cell(i, 11).value for i in range(2, 5)}
    assert datas[1].date().isoformat() == "2026-11-14"
    assert datas[2] is None                                   # sem acesso registrado: vazia
    assert datas[3].date().isoformat() == "2026-11-14"        # 01h30 UTC = 22h30 de 14/11 em Brasília
    pend = " ".join(str(c.value) for row in wb["Pendencias"].iter_rows() for c in row if c.value)
    assert "Data de acesso não registrada: referenciais nº 2" in pend
    # 080-3: idade (a estimada vale para quem não tem) e observações sem código
    assert am.cell(2, 8).value == "30 anos (estimada)" and am.cell(3, 8).value == "20 anos"
    assert am.cell(2, 12).value and "D-082" not in am.cell(2, 12).value


def test_aba_imovel_com_os_dados_do_laudo_e_a_fonte(tmp_path):
    jid = _job()
    db.salvar_campos(jid, [
        Campo(nome="Endereço do imóvel", valor="Rua Exemplo, Quadra 1, Lote 2, Centro", origem="documento", fonte="documento/escritura.pdf#p2"),
        Campo(nome="Matrícula atual do imóvel", valor="12.345", origem="documento", fonte="documento/matricula.pdf#p1"),
        Campo(nome="Cartório de registro", valor="1º Registro de Imóveis", origem="documento", fonte="documento/matricula.pdf#p1"),
        Campo(nome="Área do terreno – escritura (título)", valor=286.1, origem="documento", fonte="documento/escritura.pdf#p2"),
        Campo(nome="Estado de conservação", valor="Entre regular e necessitando de reparos simples", origem="vistoria"),
    ])
    im = openpyxl.load_workbook(_gerar(tmp_path, jid))["Imovel"]
    linha = {im.cell(i, 1).value: [im.cell(i, c).value for c in range(2, 6)] for i in range(2, 12)}
    assert linha["Endereço completo"] == ["Rua Exemplo, Quadra 1, Lote 2, Centro", None, "escritura.pdf, pág. 2", "Comprovado"]
    assert linha["Matrícula / cartório"][0] == "12.345 – 1º Registro de Imóveis"
    assert linha["Área do terreno"][:3] == [286.1, "m²", "escritura.pdf, pág. 2"]
    assert linha["Estado de conservação"][0] == "Entre regular e necessitando de reparos simples"
    assert all(v[2] for k, v in linha.items() if k != "Tipologia / padrão")   # toda linha com a fonte


def test_coerencia_acusa_aba_imovel_vazia(tmp_path):
    jid = _job()                                              # sem campos: a aba Imovel fica com linhas vazias
    xlsx = _gerar(tmp_path, jid)
    pdf = tmp_path / "laudo.pdf"
    with pymupdf.open() as d:
        d.new_page().insert_text((40, 60), "Matrícula 12.345. Área do terreno 286,10 m².", fontsize=9)
        d.save(pdf)
    difs = coerencia.conferir(pdf, xlsx, coerencia.Esperado()).diferencas
    nomes = {d.dado for d in difs}
    assert {"planilha: Matrícula / cartório", "planilha: Área do terreno", "planilha: Estado de conservação",
            "planilha: Endereço completo"} <= nomes, nomes


def test_088_endereco_igual_ao_laudo_pendencias_abertas_e_rua_nas_amostras(tmp_path):
    jid = _job()
    db.salvar_campos(jid, [
        Campo(nome="Endereço do imóvel", valor="Rua Exemplo 4, Quadra 1, Lote 2", origem="documento", fonte="documento/escritura.pdf#p2"),
        Campo(nome="Bairro / loteamento", valor="Setor Exemplo", origem="documento", fonte="documento/iptu.pdf#p1"),
        Campo(nome="Município / UF", valor="Goiânia – GO", origem="documento", fonte="documento/iptu.pdf#p1"),
        Campo(nome="CEP", valor="74000-000", origem="documento", fonte="documento/iptu.pdf#p1"),
    ])
    refs = [r.model_copy(update={"rua": "Rua Vizinha 58"}) for r in _refs()]
    r = calculo.calcular(Decimal("106.24"), refs)
    t = _comum.trabalho(jid).model_copy(update={"pin_maps": "https://maps.app.goo.gl/exemplo"})
    wb = openpyxl.load_workbook(planilha.gerar(tmp_path / "p2.xlsx", t, Decimal("106.24"), refs, r, origem_area="documento"))
    assert wb["Imovel"]["B3"].value == "Rua Exemplo 4, Quadra 1, Lote 2, Setor Exemplo, Goiânia – GO, CEP 74000-000"
    assert wb["Amostras"]["E2"].value == "Rua Vizinha 58, Centro"
    pend = [wb["Pendencias"].cell(i, 2).value for i in range(2, 16) if wb["Pendencias"].cell(i, 2).value]
    assert "Assinatura do avaliador" in pend
    assert not any("Pin do Google" in x for x in pend)          # o pin foi dado: não fica "aberto" na planilha


def test_102_8_sem_sigla_e_comparacao_na_planilha(tmp_path):
    jid = _job()
    db.salvar_campos(jid, [Campo(nome="endereco", valor="Rua XV-9 (R XV9), Qd. 59, Lt. 02, Setor Exemplo, Goiânia – GO, CEP 74000-000",
                                 origem="documento", fonte="documento/iptu.pdf#p1")])
    refs = _refs()
    db.salvar_candidatos(jid, refs + [Referencial(n=7, link=f"{ZAP}comp/", portal="Deztop", bairro="Setor Exemplo", rua="Rua JC-18",
                                                  tipologia="Casa", padrao="", idade_aparente="", descricao="", preco=240000,
                                                  area_m2=125, decisao="comparacao", escolhido=False)])
    r = calculo.calcular(Decimal("106.24"), refs)
    wb = openpyxl.load_workbook(planilha.gerar(tmp_path / "p2.xlsx", _comum.trabalho(jid), Decimal("106.24"), refs, r,
                                               origem_area="documento"))
    assert "(R XV9)" not in wb["Imovel"]["B3"].value
    am = wb["Amostras"]
    linha = next(i for i in range(2, 22) if am.cell(i, 1).value == 7)
    assert am.cell(linha, 2).value == "N" and "comparação" in am.cell(linha, 12).value
