"""ORDEM 039 — laudo incontestável: D-082 (prova com data e hora), D-084 (coerência sem IA),
D-085 (dossiê dos descartados) e D-086 (assinatura digital). Dados simulados."""
import asyncio
import base64
import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from lovable.avaliacao import assinatura, calculo, coerencia, db, dossie, provas, routes
from lovable.avaliacao.agentes import leitor_anuncio
from lovable.avaliacao.modelos import Referencial
from tests.avaliacao.test_pagina_enviada import _job


def _png(w=800, h=2400, cor="green") -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), cor).save(b, "PNG")
    return b.getvalue()


def _ref(n, **k):
    d = dict(n=n, link=f"https://site-teste.test/anuncio-{n}", portal="site-teste.test", bairro="B",
             tipologia="Galpão", padrao="", idade_aparente="", descricao="", area_m2=1000, preco=3_000_000)
    d.update(k)
    return Referencial(**d)


# ------------------------------------------------------------------ D-082
def test_hora_de_brasilia_e_formato():
    d = provas.em_brasilia("2026-11-14T03:05:00+00:00")
    assert provas.fmt(d) == "14/11/2026 às 00:05"


def test_prova_com_faixa_no_rodape_e_pdf():
    jid = _job()
    quando = provas.em_brasilia("2026-11-14T13:30:00+00:00")
    p = provas.gravar(jid, 3, _png(), "https://site-teste.test/anuncio-3", "site-teste.test", quando)
    assert p["acessado_em"].startswith("2026-11-14T10:30:00") and p["prova"].startswith("provas/anuncios/ref-03-")
    img = Image.open(db.pasta(jid) / p["prova"])
    assert img.height > 2400                                  # a faixa entrou no rodapé
    with pymupdf.open(db.pasta(jid) / p["prova_pdf"]) as d:
        assert d.page_count >= 1
    assert provas.texto_prova(quando, "https://x.test/a", "X") == \
        "Acessado em 14/11/2026 às 10:30 (horário de Brasília) — https://x.test/a — X"


def test_extensao_104_grava_prova_e_hora(monkeypatch):
    jid = _job()

    async def leitor(job_id, captura, portal, comuns=frozenset()):
        return None
    monkeypatch.setattr(leitor_anuncio, "ler", leitor)
    corpo = routes.AnuncioEnviado(
        link="https://corretor-teste.test/galpao-9", titulo="Galpão", preco=3_000_000, area_m2=1000,
        texto="Galpão com 1.000 m² construídos, R$ 3.000.000",
        pagina_inteira="data:image/png;base64," + base64.b64encode(_png()).decode(),
        acessado_em=provas.agora().isoformat())
    r = asyncio.run(routes.anuncio_enviado(jid, corpo, _u={}))
    c = next(x for x in db.candidatos(jid) if x.n == r["n"])
    assert c.acessado_em and c.prova.endswith(".jpg") and c.prova_pdf.endswith(".pdf")
    assert (db.pasta(jid) / c.prova).is_file()
    q, origem = provas.acesso(jid, c)
    assert q is not None and origem == "registrado na coleta"


def test_sem_hora_e_pendencia_nunca_data_inventada():
    jid = _job()
    r = _ref(1, fonte_coleta="manual")                 # ex.: amostra tirada do laudo oficial
    assert provas.acesso(jid, r) == (None, "")
    banco = _ref(2, fonte_coleta="banco", visto_em="2026-11-01T12:00:00+00:00")
    assert provas.fmt(provas.acesso(jid, banco)[0]) == "01/11/2026 às 09:00"


def test_carimbo_na_foto(tmp_path):
    f = tmp_path / "f.jpg"
    Image.new("RGB", (600, 400), "white").save(f)
    out = provas.carimbar(f, provas.em_brasilia("2026-11-14T13:30:00+00:00"), tmp_path / "c.jpg")
    a, b = Image.open(f), Image.open(out)
    assert a.size == b.size and list(a.getdata()) != list(b.getdata())


# ------------------------------------------------------------------ D-084
def _laudo(tmp: Path, valor_resumo="R$ 6.072.000,00", cnai="053569") -> Path:
    paginas = [
        ["Opinião Profissional de Valor N.º 9118 · Data-base 12/11/2026", f"CNAI {cnai}",
         "Valor de Mercado = 1.982,96 m² × R$ 3.061,95/m² = R$ 6.071.724,37",
         "VALOR DE MERCADO ADOTADO R$ 6.072.000,00", "(Seis milhões e setenta e dois mil reais).",
         "mínimo R$ 5.464.800,00 máximo R$ 6.679.200,00",
         "adota-se o valor unitário de R$ 3.061,95/m²", "R$ 2.173,55 R$ 3.461,54 R$ 3.025,88"],
        ["Opinião Profissional de Valor N.º 9118 · Data-base 12/11/2026", f"CNAI {cnai}",
         f"RESUMO Valor de mercado adotado {valor_resumo}"],
    ]
    out = tmp / "9118 - Cliente - Galpão - Bairro - Cidade.pdf"
    with pymupdf.open() as d:
        for linhas in paginas:
            pg = d.new_page()
            y = 50
            for ln in linhas:
                pg.insert_text((40, y), ln, fontsize=9)
                y += 16
        d.save(out)
    return out


def _esp():
    return coerencia.Esperado(
        valor_adotado=Decimal("6072000"), valor_calculado=Decimal("6071724.37"),
        valor_min=Decimal("5464800"), valor_max=Decimal("6679200"), faixa_pct=Decimal("10"),
        unitario=Decimal("3061.95"), area=Decimal("1982.96"),
        amostras=[(Decimal("6000000"), Decimal("2760.46")), (Decimal("4500000"), Decimal("1300")),
                  (Decimal("4500000"), Decimal("1487.17"))],
        data_base=datetime(2026, 11, 12).date(), numero="9118")


def test_coerencia_ok(tmp_path):
    r = coerencia.conferir(_laudo(tmp_path), None, _esp())
    assert r.ok, r.resumo()


def test_coerencia_pega_um_real_no_resumo(tmp_path):
    r = coerencia.conferir(_laudo(tmp_path, valor_resumo="R$ 6.072.001,00"), None, _esp())
    assert not r.ok
    assert any(d.dado == "valor adotado" and d.pagina == "pág. 2" and d.encontrado == "R$ 6.072.001,00"
               for d in r.diferencas)


def test_coerencia_pega_cnai_sem_zero(tmp_path):
    r = coerencia.conferir(_laudo(tmp_path, cnai="53569"), None, _esp())
    assert any(d.dado == "CNAI" and d.encontrado == "53569" for d in r.diferencas)


def test_coerencia_arredondamento_e_extenso():
    assert coerencia._milhar(Decimal("6071724.37")) == Decimal("6072000")
    assert calculo.por_extenso(Decimal("6072000")) == "Seis milhões e setenta e dois mil reais"


# ------------------------------------------------------------------ D-085
def test_motivos_lista_fechada():
    terreno = _ref(6, observacao="área do cartão (1.650 m²) … — a área do cartão era a do TERRENO (F-S003)")
    contra = _ref(11, observacao="ANÚNCIO CONTRADITÓRIO (preço)")
    dup = _ref(1, observacao="não usado: é o mesmo imóvel da amostra 05 do laudo oficial")
    assert dossie.motivos(terreno, False) == ["área de terreno no cartão"]
    assert dossie.motivos(contra, False) == ["anúncio contraditório"]
    assert dossie.motivos(dup, False) == ["duplicado (mesmo imóvel)"]
    assert dossie.motivos(_ref(9), False) == ["outro: não escolhido pelo avaliador (fora do critério adotado)"]
    assert dossie.motivos(_ref(9), True) == []
    assert all(m in dossie.MOTIVOS for m in ("área de terreno no cartão", "anúncio contraditório"))


def test_frase_do_laudo():
    jid = _job()
    db.salvar_candidatos(jid, [_ref(i) for i in range(1, 8)])
    f = dossie.frase_laudo(jid, 5)
    assert f == ("Foram analisados 7 anúncios; 5 atenderam aos critérios adotados; os demais foram "
                 "descartados pelos motivos registrados no dossiê de pesquisa, disponível mediante solicitação.")


# ------------------------------------------------------------------ D-086
def test_pdf_sem_assinatura(tmp_path):
    p = tmp_path / "a.pdf"
    with pymupdf.open() as d:
        d.new_page().insert_text((50, 50), "laudo")
        d.save(p)
    r = assinatura.conferir(p)
    assert not r.assinado and "nenhuma assinatura" in r.motivo
    assert assinatura.nome_assinado(Path("123 - X.pdf")) == "123 - X_assinado.pdf"


def test_imagem_de_assinatura_nao_conta(tmp_path):
    p = tmp_path / "b.pdf"
    img = tmp_path / "ass.png"
    Image.new("RGB", (200, 60), "blue").save(img)
    with pymupdf.open() as d:
        pg = d.new_page()
        pg.insert_image(pymupdf.Rect(50, 50, 250, 110), filename=str(img))
        pg.insert_text((50, 130), "Assinado: Avaliador")
        d.save(p)
    assert not assinatura.conferir(p).assinado


# PDF assinado de verdade (só leitura, fora do git): caminho na variável JDB_PDF_ASSINADO_TESTE
import os
G_PTAM122 = Path(os.environ.get("JDB_PDF_ASSINADO_TESTE", "inexistente.pdf"))


@pytest.mark.skipif(not G_PTAM122.is_file(), reason="defina JDB_PDF_ASSINADO_TESTE com um PDF assinado (só leitura)")
def test_ptam122_assinado_real_so_leitura():
    r = assinatura.conferir(G_PTAM122)
    assert r.assinado and r.assinaturas[0]["cobre_o_arquivo"]
