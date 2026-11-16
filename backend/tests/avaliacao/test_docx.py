import asyncio
import json
import re
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from PIL import Image

from lovable.avaliacao import calculo, db, docx_builder, ia, pdf, planilha
from lovable.avaliacao.agentes import redacao
from lovable.avaliacao.agentes.redacao import Textos
from lovable.avaliacao.agentes.selecao import Selecao
from lovable.avaliacao.modelos import Campo, Referencial, Trabalho

from .textos_ok import SECOES_OV
from tests.avaliacao.conftest import numero_livre

FIX = Path(__file__).parent / "fixtures" / "ov120.json"
OUT = Path(__file__).parent / "_out"
MAPS = "https://maps.app.goo.gl/cipo1JeoaUS5EEq46"


def _img(p: Path, cor, tam=(1200, 800)):
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", tam, cor).save(p)


def _textos(**extra) -> Textos:
    s = dict(SECOES_OV)
    s.update(extra)
    return Textos(secoes=s, legendas={"fotos/f1.jpg": "Fachada frontal – vista da rua"},
                  descricao_amostras={})


def _job(campos_extra=(), com_maps=False, docinfo=True):
    db.init()
    jid = db.criar_job(Trabalho(
        id="", numero=numero_livre(120), modalidade="OV", finalidade="Venda", cliente="Marina",
        tipo="Sobrado", bairro="Jardim Vila Boa", cidade="Goiânia", pin_maps=MAPS,
        data_base=date(2026, 10, 16), data_vistoria=date(2026, 10, 16),
        contexto="SEGREDO-VERBAL-XYZ"))
    pasta = db.pasta(jid)
    for i, cor in enumerate(["green", "gray", "blue", "white", "red"], start=1):
        _img(pasta / "fotos" / f"f{i}.jpg", cor, (1200, 800) if i != 2 else (600, 900))
        db.adicionar_arquivo(jid, f"f{i}.jpg", "foto", f"fotos/f{i}.jpg")
    _img(pasta / "docs" / "iptu.png", "white", (800, 1100))
    db.adicionar_arquivo(jid, "iptu.png", "", "docs/iptu.png")
    _img(pasta / "docs" / "cnh_solicitante.png", "yellow", (800, 500))
    db.adicionar_arquivo(jid, "cnh_solicitante.png", "", "docs/cnh_solicitante.png")
    _img(pasta / "ref1.jpg", "orange", (400, 300))
    if com_maps:
        # 125-2: o print do mapa tem de ter conteúdo (imagem de uma cor só é "em branco" e não entra no laudo)
        import random
        from PIL import Image as _I
        rnd = random.Random(7)
        im = _I.new("RGB", (1000, 700))
        im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(1000 * 700)])
        im.save(pasta / "maps.png")
        db.evento(jid, "localizacao", "resultado", "ok",
                  dados={"poligono": [[100, 100], [400, 100], [400, 300], [100, 300]]})
    campos = [
        Campo(nome="endereco", valor="Rua das Acácias, Quadra 12, Lote 07, Jardim Vila Boa, "
              "município de Goiânia – GO, CEP 74360-300", origem="documento", fonte="docs/iptu.png"),
        Campo(nome="area_construida", valor=364.0, unidade="m2", origem="documento",
              fonte="docs/iptu.png"),
        Campo(nome="padrao_construtivo", valor="simples", origem="vistoria", fonte="fotos/f1.jpg"),
        Campo(nome="estado_conservacao", valor="regular", origem="vistoria", fonte="fotos/f1.jpg"),
        Campo(nome="solicitante", valor="Marina Oliveira Neves", origem="documento",
              fonte="docs/cnh_solicitante.png"),
        *campos_extra,
    ]
    db.salvar_campos(jid, campos)
    db.evento(jid, "extracao", "resultado", "ok", dados={
        "campos": [c.model_dump(mode="json") for c in campos],
        "fachada_caixa": [100, 50, 99999, 760],
        "fotos": [{"arquivo": f"fotos/f{i}.jpg", "legenda": f"Ambiente {i}", "ordem": i}
                  for i in range(1, 6)],
        "documentos": [{"arquivo": "docs/iptu.png", "rotulo_curto": "IPTU 2025",
                        "rotulo_completo": "Notificação de lançamento do IPTU 2025"}]
        if docinfo else [],
        "tarjas": {"docs/cnh_solicitante.png": [[10, 10, 300, 80], [5, 5, 5, 5],
                                                [-20, 0, 50, 9000]]},
    })
    refs = [Referencial(**d) for d in json.loads(FIX.read_text(encoding="utf-8"))]
    refs[0] = refs[0].model_copy(update={"foto": "ref1.jpg"})
    sel = Selecao(refs=refs, unitario_adotado=Decimal("2735.85"), faixa_pct=Decimal("10"))
    r = calculo.calcular(Decimal("364.00"), [x for x in refs if x.escolhido], Decimal("2735.85"))
    return jid, sel, r


def _texto(p: Path) -> str:
    with zipfile.ZipFile(p) as z:
        xml = "".join(z.read(n).decode("utf-8") for n in z.namelist()
                      if n.startswith("word/") and n.endswith(".xml"))
    return " ".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", xml))


def _xml(p: Path, nome="word/document.xml") -> str:
    with zipfile.ZipFile(p) as z:
        return z.read(nome).decode("utf-8")


def _avisos(jid):
    with db._conn() as c:
        return [r["msg"] for r in c.execute(
            "SELECT msg FROM av_events WHERE job=? AND nivel='aviso'", (jid,))]


def test_docx_so_documento_ou_vistoria():
    jid, sel, r = _job([
        Campo(nome="area_terreno", valor="999", unidade="m2", origem="inferido"),
    ])
    p = docx_builder.montar(jid, _textos(), r, sel)
    txt = _texto(p)
    # 174-5: a ÁREA inferida não entra (o rodapé pode ter um telefone de teste com "999", deixado por outro teste)
    assert not re.search(r"999(?:,00)?\s*m", txt)
    assert "364,00" in txt  # campo de documento aparece
    assert "Rua das Acácias, Quadra 12" in txt     # 172: o endereço do documento (o teste esperava "50" desde o 1º dia)
    assert "SEGREDO-VERBAL-XYZ" not in txt


def test_172_quadra_lote_do_documento_vale_e_avisa():
    """172-5: o endereço escrito com quadra/lote diferentes dos campos do documento → vale o documento, com aviso."""
    jid, sel, r = _job([
        Campo(nome="quadra", valor="50", origem="documento", fonte="docs/iptu.png"),
        Campo(nome="lote", valor="29", origem="documento", fonte="docs/iptu.png"),
    ])
    txt = _texto(docx_builder.montar(jid, _textos(), r, sel))
    assert "Rua das Acácias, Quadra 50, Lote 29" in txt and "Quadra 12" not in txt
    av = [m for m in _avisos(jid) if m.startswith("Endereço:")]
    assert any("quadra 12" in m and "quadra 50" in m for m in av), av
    assert any("lote 07" in m and "lote 29" in m for m in av), av


def test_ov_sem_ptam():
    jid, sel, r = _job()
    with pytest.raises(docx_builder.ConteudoProibido):
        docx_builder.montar(jid, _textos(**{"8": "Este PTAM foi elaborado..."}), r, sel)


def test_sem_inspecao_engenharia_proibido():
    jid, sel, r = _job()
    with pytest.raises(docx_builder.ConteudoProibido):
        docx_builder.montar(jid, _textos(**{"10": "Avaliação sem inspeção de engenharia."}), r, sel)


def test_docx_itens_fixos():
    jid, sel, r = _job([Campo(nome="area_terreno", valor=360.0, unidade="m2",
                              origem="documento", fonte="docs/iptu.png")], com_maps=True)
    p = docx_builder.montar(jid, _textos(), r, sel)
    assert p.name == "120 - Marina - Sobrado - Jardim Vila Boa - Goiânia.docx"
    txt = _texto(p)
    for s in ("VALOR DE MERCADO ADOTADO", "R$ 996.000,00", "Novecentos e noventa e seis mil reais",
              "R$ 896.400,00", "R$ 1.095.600,00", "(62) 9 9306-8692", "n/i",
              "OPINIÃO PROFISSIONAL DE VALOR", "N.º 120", "Marina Oliveira Neves",
              "16 de outubro de 2026", "Foto 01 – Fachada frontal – vista da rua",
              "360,00", "R$ 995.849,40",
              "Foi adotado o Método Comparativo Direto", "IPTU 2025",
              "Notificação de lançamento do IPTU 2025"):
        assert s in txt, s
    # ORDEM 002 (tabela de amostras D-031): o R$/m² sai em duas linhas da célula, "R$ x" e
    # "/m²", com espaço inseparável — antes "R$ x/m²" numa linha só
    for u in ("3.282,83", "2.735,85"):
        assert re.search(rf"R\$\s{re.escape(u)}\s*/m²", txt), u
    assert "[PREENCHER" not in txt
    assert "iptu.png" not in txt and "iptu " not in txt
    assert not any("rótulo de documento ausente" in m for m in _avisos(jid))
    assert "PTAM N.º" not in txt
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", txt)  # nenhum e-mail
    doc = _xml(p)
    rels = _xml(p, "word/_rels/document.xml.rels")
    assert MAPS in rels and "maps.app.goo.gl/EXEMPLO" not in rels
    assert re.search(r"<w:instrText[^>]*>\s*TOC [^<]*\\h", doc)
    assert "NUMPAGES" in doc
    d = Document(p)
    tabs = d.tables
    # amostra: cabeçalho + 5 referenciais; grade de 5 fotos -> 3 linhas x 2 colunas
    assert any(len(t.rows) == 6 and t.rows[0].cells[0].text == "Nr" and len(t.columns) == 7
               for t in tabs)
    assert any(len(t.rows) == 3 and t.rows[0].cells[0].text.startswith("Foto 01") for t in tabs)
    assert doc.count("<w:outlineLvl ") >= 20  # títulos entram no sumário
    assert not any("localização ausente" in m for m in _avisos(jid))
    OUT.mkdir(exist_ok=True)
    (OUT / p.name).write_bytes(p.read_bytes())


def test_maps_ausente_registra_pendencia():
    jid, sel, r = _job()
    p = docx_builder.montar(jid, _textos(), r, sel)
    assert any("imagem de localização ausente" in m for m in _avisos(jid))
    assert MAPS in _xml(p, "word/_rels/document.xml.rels")


def test_redacao_rodar(monkeypatch):
    jid, sel, r = _job()
    db.evento(jid, "selecao", "resultado", "ok", dados=sel.model_dump(mode="json"))
    vistos = {}

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo="", **_kw):
        vistos["prompt"] = prompt
        return esquema.model_validate(_textos().model_dump())
    monkeypatch.setattr(ia, "perguntar", fake)
    t = asyncio.run(redacao.rodar(jid))
    assert t.secoes["1"].startswith("A finalidade")
    assert "SEGREDO-VERBAL-XYZ" not in vistos["prompt"]
    assert db.resultado(jid, "redacao")["secoes"]["8"]


@pytest.mark.skipif(planilha.soffice_path() is None, reason="LibreOffice ausente")
def test_pdf_gera():
    import pymupdf
    jid, sel, r = _job()
    p = docx_builder.montar(jid, _textos(), r, sel)
    out = pdf.converter(p)
    assert out.exists()
    with pymupdf.open(out) as d:
        assert d.page_count >= 10


@pytest.mark.parametrize("mod", ["AM", "AMJ"])
def test_am_amj_monta(mod):
    jid, sel, r = _job()
    with db._conn() as c:  # troca a modalidade do job
        row = c.execute("SELECT dados_json FROM av_jobs WHERE id=?", (jid,)).fetchone()
        d = json.loads(row["dados_json"])
        d["modalidade"] = mod
        if mod == "AMJ":
            d.update(processo_numero="0001", vara_juizo="1ª Vara", acao="Divórcio",
                     partes={"autor": "A", "reu": "B"}, quesitos=["Qual o valor?"])
        c.execute("UPDATE av_jobs SET dados_json=? WHERE id=?", (json.dumps(d), jid))
    extra = {"4": "Limitação de uso conforme o destino.", "11": "Ressalva específica."}
    if mod == "AMJ":
        extra.update({"12": "Quesito 1: Qual o valor?\n\nResposta: R$ 996.000,00."})
    p = docx_builder.montar(jid, _textos(**extra), r, sel)
    txt = _texto(p)
    assert "[PREENCHER" not in txt and "PTAM N.º 120" in txt
    assert "somente AMJ" not in txt
    if mod == "AM":
        assert "QUESITOS" not in txt and "Dados do Processo" not in txt
        assert "12. RESUMO DA AVALIAÇÃO" in txt  # renumerado após remover os quesitos
    else:
        assert "AVALIAÇÃO MERCADOLÓGICA JUDICIAL" in txt and "1ª Vara" in txt


def test_rotulo_ausente_registra_aviso():
    jid, sel, r = _job(docinfo=False)
    docx_builder.montar(jid, _textos(), r, sel)
    assert any(m == "rótulo de documento ausente: iptu.png" for m in _avisos(jid))


def test_pdf_timeout_mata_processo():
    import subprocess
    import sys
    with pytest.raises(subprocess.TimeoutExpired):
        pdf._rodar([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)


# ---------------------------------------------------------------- revisão final
def _pdf_doc(p: Path, paginas=1):
    import pymupdf
    p.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as d:
        for _ in range(paginas):
            d.new_page(width=400, height=300)  # fundo branco
        d.save(p)


def _midias(p: Path) -> list[Image.Image]:
    import io
    with zipfile.ZipFile(p) as z:
        return [Image.open(io.BytesIO(z.read(n))).convert("RGB") for n in z.namelist()
                if n.startswith("word/media/")]


def _job_pdf_sol(tarjas: dict):
    jid, sel, r = _job()
    pasta = db.pasta(jid)
    _pdf_doc(pasta / "docs" / "rg_solicitante.pdf", paginas=2)
    db.adicionar_arquivo(jid, "rg_solicitante.pdf", "", "docs/rg_solicitante.pdf")
    ext = db.resultado(jid, "extracao")
    ext["tarjas"] = tarjas
    db.evento(jid, "extracao", "resultado", "ok", dados=ext)
    return jid, sel, r


def test_pdf_solicitante_tarjado_por_pagina(monkeypatch):
    # regra antiga (tarja no laudo), mantida como chave: ORDEM 035 / D-062 desligou no laudo do cliente
    monkeypatch.setattr(docx_builder, "TARJA_NO_LAUDO_DO_CLIENTE", True)
    jid, sel, r = _job_pdf_sol({
        "docs/cnh_solicitante.png": [[10, 10, 300, 80]],
        "docs/rg_solicitante.pdf#p1": [[100, 100, 200, 150]],  # pontos PDF
        "docs/rg_solicitante.pdf#p2": [[10, 10, 50, 50]]})
    docx_builder.montar(jid, _textos(), r, sel)
    pg = db.pasta(jid) / "_laudo" / "anexos" / "rg_solicitante" / "pagina-01-tarjada.png"
    assert pg.exists()
    with Image.open(pg) as im:
        k = 110 / 72
        assert im.convert("RGB").getpixel((int(150 * k), int(125 * k))) == (0, 0, 0)
        assert im.convert("RGB").getpixel((5, 5)) == (255, 255, 255)


def test_solicitante_sem_tarja_nao_anexa_e_e_grave(monkeypatch):
    # regra antiga (tarja no laudo), mantida como chave: ORDEM 035 / D-062 desligou no laudo do cliente
    monkeypatch.setattr(docx_builder, "TARJA_NO_LAUDO_DO_CLIENTE", True)
    from lovable.avaliacao import orquestrador
    jid, sel, r = _job_pdf_sol({"docs/cnh_solicitante.png": [[10, 10, 300, 80]]})
    p = docx_builder.montar(jid, _textos(), r, sel)
    avs = [m for m in _avisos(jid) if m.startswith(docx_builder.SEM_TARJA)]
    assert avs == [f"{docx_builder.SEM_TARJA}: docs/rg_solicitante.pdf#p1",
                   f"{docx_builder.SEM_TARJA}: docs/rg_solicitante.pdf#p2"]
    assert orquestrador._grave(avs[0])
    assert not (db.pasta(jid) / "_laudo" / "anexos" / "rg_solicitante").exists()
    # a CNH tarjada continua anexada (tem caixa); imagem amarela sem tarja nenhuma não
    jid2, sel2, r2 = _job()
    ext = db.resultado(jid2, "extracao")
    ext["tarjas"] = {}
    db.evento(jid2, "extracao", "resultado", "ok", dados=ext)
    p2 = docx_builder.montar(jid2, _textos(), r2, sel2)
    amarelas = [im for im in _midias(p2) if im.size == (800, 500)]
    assert amarelas == []
    assert f"{docx_builder.SEM_TARJA}: docs/cnh_solicitante.png" in _avisos(jid2)


def test_avisos_graves_sao_constantes():
    from lovable.avaliacao import orquestrador
    for msg in (docx_builder.SEM_FOTOS, f"{redacao.SECOES_SEM_TEXTO}: 7.4, 9",
                docx_builder.SEM_LOCALIZACAO, f"{docx_builder.SEM_TARJA}: x.pdf"):
        assert orquestrador._grave(msg), msg
    assert not orquestrador._grave("rótulo de documento ausente: iptu.png")


def test_redacao_sem_texto_e_aviso_grave(monkeypatch):
    jid, sel, r = _job()

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo="", **_kw):
        return esquema.model_validate({"secoes": {"1": "x"}})
    monkeypatch.setattr(ia, "perguntar", fake)
    asyncio.run(redacao.rodar(jid))
    av = [m for m in _avisos(jid) if m.startswith(redacao.SECOES_SEM_TEXTO)]
    assert av and av[0].startswith(redacao.SECOES_SEM_TEXTO + ": ")


def test_nome_de_arquivo_no_texto_e_proibido():
    jid, sel, r = _job()
    with pytest.raises(docx_builder.ConteudoProibido, match="iptu.png"):
        docx_builder.montar(jid, _textos(**{"7.3": "Áreas conforme o arquivo iptu.png."}), r, sel)
    with pytest.raises(docx_builder.ConteudoProibido, match="f1.jpg"):
        docx_builder.montar(jid, Textos(secoes=_textos().secoes,
                                        legendas={"fotos/f1.jpg": "foto f1.jpg"}), r, sel)


def test_redacao_recebe_rotulos_dos_documentos(monkeypatch):
    jid, sel, r = _job()
    vistos = {}

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo="", **_kw):
        vistos["p"], vistos["s"] = prompt, sistema
        return esquema.model_validate(_textos().model_dump())
    monkeypatch.setattr(ia, "perguntar", fake)
    asyncio.run(redacao.rodar(jid))
    assert "Notificação de lançamento do IPTU 2025" in vistos["p"]
    assert "nome de arquivo" in vistos["s"]


def test_arquivos_doc_citacao_exata():
    jid, sel, r = _job()
    _img(db.pasta(jid) / "docs" / "planta_iptu.png", "white")
    db.adicionar_arquivo(jid, "planta_iptu.png", "", "docs/planta_iptu.png")
    with db._conn() as c:
        c.execute("DELETE FROM av_fields WHERE job=?", (jid,))
    db.salvar_campos(jid, [Campo(nome="area_terreno", valor="300", origem="documento",
                                 fonte="docs/planta_iptu.png")])
    ctx = docx_builder._Ctx(jid, _textos(), r, sel)
    imovel, _ = docx_builder._arquivos_doc(ctx)
    assert imovel == ["docs/planta_iptu.png"]  # 'iptu.png' é substring, mas não é citado


def test_pdf_solicitante_pagina_sem_tarja_nao_anexa_nada(monkeypatch):
    # regra antiga (tarja no laudo), mantida como chave: ORDEM 035 / D-062 desligou no laudo do cliente
    monkeypatch.setattr(docx_builder, "TARJA_NO_LAUDO_DO_CLIENTE", True)
    from lovable.avaliacao import orquestrador
    jid, sel, r = _job_pdf_sol({
        "docs/cnh_solicitante.png": [[10, 10, 300, 80]],
        "docs/rg_solicitante.pdf#p1": [[100, 100, 200, 150]],
        "docs/rg_solicitante.pdf#p2": [[5000, 5000, 6000, 6000]]})  # fora da página
    docx_builder.montar(jid, _textos(), r, sel)
    avs = [m for m in _avisos(jid) if m.startswith(docx_builder.SEM_TARJA)]
    assert avs == [f"{docx_builder.SEM_TARJA}: docs/rg_solicitante.pdf#p2"]
    assert orquestrador._grave(avs[0])
    assert not (db.pasta(jid) / "_laudo" / "anexos" / "rg_solicitante").exists()


def test_tarja_infinita_ignorada(monkeypatch):
    # regra antiga (tarja no laudo), mantida como chave: ORDEM 035 / D-062 desligou no laudo do cliente
    monkeypatch.setattr(docx_builder, "TARJA_NO_LAUDO_DO_CLIENTE", True)
    jid, sel, r = _job_pdf_sol({
        "docs/cnh_solicitante.png": [[10, 10, 300, 80]],
        "docs/rg_solicitante.pdf#p1": [[100, 100, 200, 150], [0, 0, float("inf"), 9]],
        "docs/rg_solicitante.pdf#p2": [[10, 10, 50, 50]]})
    docx_builder.montar(jid, _textos(), r, sel)
    assert (db.pasta(jid) / "_laudo" / "anexos" / "rg_solicitante"
            / "pagina-01-tarjada.png").exists()


def _keep(p, tag):
    ppr = p._p.pPr
    return ppr is not None and ppr.find(qn(tag)) is not None


@pytest.mark.parametrize("mod", ["OV", "AM"])
def test_assinatura_e_valor_presos(mod):
    jid, sel, r = _job()
    extra = {}
    if mod != "OV":
        with db._conn() as c:
            row = c.execute("SELECT dados_json FROM av_jobs WHERE id=?", (jid,)).fetchone()
            dj = json.loads(row["dados_json"])
            dj["modalidade"] = mod
            c.execute("UPDATE av_jobs SET dados_json=? WHERE id=?", (json.dumps(dj), jid))
        extra = {"4": "Limitação de uso conforme o destino.", "11": "Ressalva específica."}
    d = Document(docx_builder.montar(jid, _textos(**extra), r, sel))
    ps = d.paragraphs
    i = next(k for k, p in enumerate(ps) if re.fullmatch(r"\d+\. ASSINATURA", p.text.strip()))
    fim = next(k for k in range(i + 1, len(ps)) if "ANEXOS" in ps[k].text)
    assin = ps[i:fim]
    d = next(k for k, p in enumerate(ps) if re.fullmatch(r"\d+\. DECLARAÇÕES.*", p.text.strip()))
    for p in [*ps[d:i], *assin[:-1]]:
        assert _keep(p, "w:keepNext") and _keep(p, "w:keepLines"), p.text
    # ORDEM 002 (D-040): o bloco do valor virou a CAIXA AZUL — tabela de 1 célula com a linha
    # indivisível (cantSplit) contendo rótulo, valor e extenso; o parágrafo anterior (conclusão)
    # fica preso a ela (keepNext). Antes: três parágrafos soltos com keepNext/keepLines.
    corpo = ps[0]._p.getparent()
    cx = next(t for t in corpo.iter(qn("w:tbl"))
              if "VALOR DE MERCADO ADOTADO" in "".join(x.text or "" for x in t.iter(qn("w:t"))))
    tr = cx.find(qn("w:tr"))
    assert tr.find(qn("w:trPr")) is not None and tr.find(qn("w:trPr")).find(qn("w:cantSplit")) is not None
    txt = [("".join(x.text or "" for x in p.iter(qn("w:t")))).strip() for p in tr.iter(qn("w:p"))]
    assert txt[0] == "VALOR DE MERCADO ADOTADO" and txt[1].startswith("R$") and txt[2].startswith("(")
    ant = cx.getprevious()
    assert ant is not None and ant.find(qn("w:pPr")) is not None \
        and ant.find(qn("w:pPr")).find(qn("w:keepNext")) is not None


@pytest.mark.skipif(planilha.soffice_path() is None, reason="LibreOffice ausente")
def test_pdf_paginacao_ov120():
    import pymupdf
    jid, sel, r = _job([Campo(nome="area_terreno", valor=360.0, unidade="m2",
                              origem="documento", fonte="docs/iptu.png")], com_maps=True)
    out = pdf.converter(docx_builder.montar(jid, _textos(), r, sel))
    with pymupdf.open(out) as d:
        textos = [pg.get_text() for pg in d]
        imgs = [len(pg.get_image_info()) for pg in d]
        n = d.page_count
    cab = len(textos[-1]) and min(len(t) for t in textos)  # cabeçalho + rodapé
    assert next(k for k, t in enumerate(textos, 1) if "1. FINALIDADE" in t) == 2
    for k, (t, im) in enumerate(zip(textos, imgs), 1):
        assert im or len(t) - cab >= 150, f"página {k} quase vazia: {t!r}"
    m = re.search(r"composto por\s+(\d+)\s+páginas", " ".join(textos))
    assert m and int(m.group(1)) == n
    assin = next(t for t in textos if re.search(r"\d+\. ASSINATURA", t) and "Goiânia," in t)
    assert "DECLARAÇÕES DO AVALIADOR" in assin and "honorários profissionais" in assin
    with pymupdf.open(out) as d:
        linhas = [(sp["text"], bool(sp["flags"] & 16)) for b in d[-1].get_text("dict")["blocks"]
                  for ln in b.get("lines", []) for sp in ln["spans"][:1]]
    negrito = dict(linhas)
    assert negrito[next(t for t in negrito if t.startswith("1. FINALIDADE"))]
    assert not negrito[next(t for t in negrito if t.startswith("7.1. "))]


def test_inicio_assinatura_secao_longa():
    from lovable.avaliacao import docx_partes as X
    txt = ["11. RESUMO", "12. DECLARAÇÕES DO AVALIADOR", "a" * 3000, "b" * 50, "c" * 50,
           "O presente parecer é composto por 9 páginas", "13. ASSINATURA"]
    assert X._inicio_assinatura([None] * len(txt), txt, 6) == 4  # 2 últimos parágrafos
    txt[2] = "curto"
    assert X._inicio_assinatura([None] * len(txt), txt, 6) == 1  # seção inteira


def test_capa_usa_foto_marcada_como_fachada(monkeypatch):
    jid, sel, r = _job()
    db.adicionar_arquivo(jid, "f3.jpg", "foto", "fotos/f3.jpg", papel="fachada")
    usadas = []
    orig = docx_builder.X.trocar_imagem

    def espiar(p, part, img, *a, **k):
        usadas.append(Path(img).name)
        return orig(p, part, img, *a, **k)

    monkeypatch.setattr(docx_builder.X, "trocar_imagem", espiar)
    docx_builder.montar(jid, _textos(), r, sel)
    assert usadas[0] == "f3.jpg"  # capa = marcada, sem a caixa deduzida para f1
    assert "fachada sem demarcação (caixa ausente ou inválida)" in _avisos(jid)


def test_redacao_minimos_por_secao():
    ok = redacao.deficiencias("OV", _textos().secoes)
    assert ok == []
    curto = dict(_textos().secoes, **{"5": "Foi adotado o Método Comparativo Direto.\n" + "x" * 250,
                                       "7.4": "Tipo: sobrado.\nPadrão construtivo: simples.",
                                       "9": "Adota-se o unitário de R$ 2.735,85/m²."})
    f = redacao.deficiencias("OV", curto)
    # ORDEM 002 (D-039): na OV a seção 5 é só o trecho dos referenciais (≤ 160 caracteres,
    # uma linha) e a determinação não fala de dispersão, mas exige "adota-se o valor
    # unitário de R$" (D-018). As exigências antigas (homogeneização, dispersão) ficam no AM.
    assert any(x.startswith("5 (metodologia)") and "trecho dos referenciais" in x for x in f)
    assert any(x.startswith("7.4 (descricao)") for x in f)
    assert any(x.startswith("9 (determinacao)") and "adota-se o valor" in x for x in f)
    am = redacao.deficiencias("AM", dict(curto, **{"5": "Foi adotado o Método Comparativo Direto.",
                                                   "10": "Adota-se o unitário de R$ 2.735,85/m²."}))
    assert any(x.startswith("5 (metodologia)") and "homogeneização" in x for x in am)
    assert not any("dispersão" in x for x in am)          # 106 (D-068): nem no AM a dispersão é exigida


def test_redacao_curta_vira_aviso_grave_e_volta_com_faltas(monkeypatch):
    from lovable.avaliacao import orquestrador
    jid, sel, r = _job()
    db.evento(jid, "selecao", "resultado", "ok", dados=sel.model_dump(mode="json"))
    prompts = []

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo="", **_kw):
        prompts.append((sistema, prompt))
        # 165: na OV a metodologia hoje é curta de propósito (só o trecho dos referenciais); falta é a seção vazia
        return esquema.model_validate({"secoes": dict(_textos().secoes, **{"5": ""})})
    monkeypatch.setattr(ia, "perguntar", fake)
    t = asyncio.run(redacao.rodar(jid))
    # 165: hoje a redação também aponta "fato do exemplo copiado"; a seção curta continua entre as faltas
    assert t.faltas and any(f.startswith("5 (metodologia)") for f in t.faltas), t.faltas
    av = [m for m in _avisos(jid) if m.startswith(redacao.SECOES_SEM_TEXTO)]
    assert av and "metodologia" in av[0] and orquestrador._grave(av[0])
    asyncio.run(redacao.rodar(jid))  # nova rodada recebe as faltas da anterior
    assert "ABAIXO DO MÍNIMO" in prompts[1][1] and "5 (metodologia)" in prompts[1][1]
    # prompt traz exemplo do P8 e o CV calculado em código
    assert "Não foram aplicados fatores de homogeneização" in prompts[0][0]
    # 165 (D-039): na OV o coeficiente de variação fica só na planilha — não vai mais no pedido da redação
    assert "coeficiente de variação" not in prompts[0][1] and "Candidatos analisados" in prompts[0][1]


def test_exemplos_secoes_sem_dados_pessoais():
    txt = json.dumps(redacao.exemplos(), ensure_ascii=False)
    for proibido in ("Marina", "Fulano de Tal", "Beltrana", "das Acácias", "das Palmeiras",
                     "000.000", ""):
        assert proibido not in txt
    assert redacao.exemplos()["OV"]["metodologia"] and redacao.exemplos()["PTAM"]["descricao"]


def _amj(jid, **dados):
    with db._conn() as c:
        row = c.execute("SELECT dados_json FROM av_jobs WHERE id=?", (jid,)).fetchone()
        d = json.loads(row["dados_json"])
        d.update(modalidade="AMJ", **dados)
        c.execute("UPDATE av_jobs SET dados_json=? WHERE id=?", (json.dumps(d), jid))


_EXTRA_AMJ = {"4": "Limitação de uso conforme o destino.", "11": "Ressalva específica.",
              "12": "Quesito 1: Qual o valor?\n\nResposta: R$ 996.000,00."}


def test_amj_processo_e_perito_vem_dos_campos_estruturados():
    jid, sel, r = _job()
    _amj(jid, processo_numero="5001234-56.2026.8.09.0051", vara_juizo="2ª Vara de Família",
         acao="Partilha", partes={"autor": "Fulano", "reu": "Beltrano"}, quesitos=["Qual o valor?"])
    db.set_setting("avaliador", json.dumps({
        "nome": "Alan", "formacao": "Técnico em Transações Imobiliárias",
        "qualificacao": "Atua há 10 anos em avaliações judiciais"}))
    try:
        txt = _texto(docx_builder.montar(jid, _textos(**_EXTRA_AMJ, **{"3.1": "Processo nº: X"}),
                                         r, sel))
    finally:
        db.set_setting("avaliador", "{}")
    assert "5001234-56.2026.8.09.0051" in txt and "2ª Vara de Família" in txt
    assert "Autor: Fulano; Réu: Beltrano" in txt and "Partilha" in txt
    assert "Processo nº: X" not in txt  # a tabela não vem da redação
    assert "Atua há 10 anos em avaliações judiciais." in txt
    assert "Técnico em Transações Imobiliárias." in txt
    assert not [m for m in _avisos(jid) if m.startswith((docx_builder.AMJ_SEM_PROCESSO,
                                                         docx_builder.PERITO_SEM_QUALIFICACAO))]


def test_amj_sem_processo_ou_qualificacao_e_grave():
    from lovable.avaliacao import orquestrador
    jid, sel, r = _job()
    _amj(jid, quesitos=["Qual o valor?"])
    db.set_setting("avaliador", "{}")
    docx_builder.montar(jid, _textos(**_EXTRA_AMJ), r, sel)
    av = _avisos(jid)
    proc = [m for m in av if m.startswith(docx_builder.AMJ_SEM_PROCESSO)]
    assert proc and "nº do processo" in proc[0] and "partes" in proc[0]
    assert orquestrador._grave(proc[0])
    assert docx_builder.PERITO_SEM_QUALIFICACAO in av
    assert orquestrador._grave(docx_builder.PERITO_SEM_QUALIFICACAO)


def test_quesitos_respondidos_um_a_um():
    base = _textos().secoes
    secoes = dict(base, **_EXTRA_AMJ)
    secoes.update({"8": base["7.1"], "9": base["8"], "10": base["9"]})  # numeração AM/AMJ
    f = redacao.deficiencias("AMJ", secoes, ["Qual o valor?", "Há benfeitorias?"])
    assert any(x.startswith("12 (quesitos)") and "2" in x for x in f)
    secoes["12"] += "\n\nQuesito 2: Há benfeitorias?\n\nResposta: Sim."
    assert not [x for x in redacao.deficiencias("AMJ", secoes, ["a", "b"]) if "quesitos" in x]


def test_amostra_do_banco_mostra_data_em_que_foi_vista():
    jid, sel, r = _job()
    refs = list(sel.refs)
    i = next(k for k, x in enumerate(refs) if x.escolhido)
    refs[i] = refs[i].model_copy(update={"fonte_coleta": "banco",
                                         "visto_em": "2026-10-01T12:00:00+00:00"})
    sel = sel.model_copy(update={"refs": refs})
    txt = _texto(docx_builder.montar(jid, _textos(), r, sel))
    assert "anúncio visto em 01/10/2026" in txt
    assert txt.count("anúncio visto em") == 1        # só o reaproveitado do banco


def test_referencial_fonte_coleta_padrao():
    r = Referencial(n=1, link="x", portal="p", bairro="b", tipologia="t", padrao="",
                    idade_aparente="", descricao="")
    assert r.fonte_coleta == "coletor" and r.visto_em == ""
    # 112: o banco de comparáveis da busca automática saiu (o rótulo "banco" segue aceito nos dados antigos)


def test_visita_por_parceiro_d043():
    """D-043 (ORDEM 011): vistoria feita por parceiro — item 7 com a frase da visita técnica;
    vazio = a frase atual ("Vistoria realizada em: …")."""
    jid, sel, r = _job()
    p = docx_builder.montar(jid, _textos(), r, sel)
    assert "Vistoria realizada em:" in _texto(p) and "Visita técnica realizada por" not in _texto(p)
    with db._conn() as c:
        row = c.execute("SELECT dados_json FROM av_jobs WHERE id=?", (jid,)).fetchone()
        dj = json.loads(row["dados_json"])
        dj["visita_por"] = "João da Silva, CRECI 12345/GO"
        c.execute("UPDATE av_jobs SET dados_json=? WHERE id=?", (json.dumps(dj), jid))
    txt = _texto(docx_builder.montar(jid, _textos(), r, sel))
    assert ("Visita técnica realizada por João da Silva, CRECI 12345/GO, em 16 de outubro de 2026, "
            "sob responsabilidade técnica do avaliador signatário.") in txt
    assert "Vistoria realizada em:" not in txt


def test_d062_laudo_do_cliente_anexa_solicitante_sem_tarja():
    """ORDEM 035 / D-062: no laudo do cliente final todo documento entra sem tarja (inclusive a
    página sem caixa de tarja), sem aviso de "sem tarja" e sem a frase "dados ocultados"."""
    from lovable.avaliacao import orquestrador
    jid, sel, r = _job_pdf_sol({"docs/cnh_solicitante.png": [[10, 10, 300, 80]]})
    p = docx_builder.montar(jid, _textos(), r, sel)
    txt = " ".join(x.text for x in Document(p).paragraphs)
    assert "Documentação do Solicitante" in txt and "ocultados" not in txt
    assert not any(docx_builder.SEM_TARJA in m for m in _avisos(jid))
    assert orquestrador._grave(docx_builder.SEM_TARJA + ": x")   # a regra antiga continua grave se ligada


def test_080_4_comparacao_padrao_superior_fora_do_calculo():
    """D-069: imóvel marcado "só comparação" entra em item próprio, com a mesma tabela, fora da amostra e do cálculo."""
    jid, sel, r = _job()
    extra = Referencial(**{**sel.refs[0].model_dump(), "n": 99, "link": "https://exemplo.test/padrao-superior-123456",
                           "decisao": "comparacao", "escolhido": False, "area_m2": 220.0, "preco": 295000.0})
    db.salvar_candidatos(jid, list(db.candidatos(jid)) + [extra])
    p = docx_builder.montar(jid, _textos(), r, sel)
    t = _texto(p)
    assert "Imóveis de padrão superior ofertados pelo mercado por valores abaixo de R$" in t     # 117 / D-132
    assert "não integra a amostra nem o cálculo" in t
    assert "https://exemplo.test/padrao-superior-123456" in _xml(p, "word/_rels/document.xml.rels")


def test_081_7_remontar_sem_mudanca_de_dado_nao_mexe_no_texto(monkeypatch):
    """O Alan revisa o texto uma vez; remontar sem dado novo deixa o texto idêntico (a IA nem é chamada).
    Com uma correção pedida, só a seção atingida muda; o resto fica letra por letra."""
    jid, sel, r = _job()
    db.evento(jid, "selecao", "resultado", "ok", dados=sel.model_dump(mode="json"))
    chamadas = []

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo="", **_kw):
        chamadas.append(prompt)
        if len(chamadas) == 1:
            return esquema.model_validate(_textos().model_dump())
        # 2ª chamada: a IA devolve só a seção que a correção atinge
        return esquema.model_validate({"secoes": {"3": "Finalidade reescrita por pedido do avaliador."}})
    monkeypatch.setattr(ia, "perguntar", fake)
    monkeypatch.setattr(redacao, "deficiencias", lambda *a, **k: [])     # texto sem falta: nada a refazer
    t1 = asyncio.run(redacao.rodar(jid))
    t2 = asyncio.run(redacao.rodar(jid))
    assert len(chamadas) == 1 and t2.secoes == t1.secoes and t2.legendas == t1.legendas
    assert redacao.mudancas(jid) == []
    db.evento(jid, "redacao", "correcao", "Na finalidade, escreva que é para o inventário.")
    monkeypatch.setattr(db, "correcoes", lambda j, e: ["Na finalidade, escreva que é para o inventário."])
    t3 = asyncio.run(redacao.rodar(jid))
    assert len(chamadas) == 2
    assert "TEXTO ATUAL DO LAUDO" in chamadas[1] and "+- Na finalidade, escreva que é para o inventário." in chamadas[1]
    assert t3.secoes["3"] == "Finalidade reescrita por pedido do avaliador."
    assert {k: v for k, v in t3.secoes.items() if k != "3"} == {k: v for k, v in t1.secoes.items() if k != "3"}
    assert redacao.mudancas(jid) == ["3"]


def test_083_b1_localizacao_com_rua_e_082_6_sem_anunciante():
    """Padrão A1: "**Localização:** Rua JC-58, Jardim Curitiba, Goiânia – GO." e nada de nome/CRECI de anunciante."""
    jid, sel, r = _job()
    refs = list(sel.refs)
    i = next(k for k, x in enumerate(refs) if x.escolhido)
    refs[i] = refs[i].model_copy(update={"rua": "Rua JC-58", "bairro": "Jardim Curitiba",
                                         "descricao": "Casa térrea de 3 quartos. Anunciante: Lidiane Ventura (CRECI 11.991)."})
    sel = sel.model_copy(update={"refs": refs})
    t = _textos()
    t.descricao_amostras.pop(refs[i].n, None)
    p = docx_builder.montar(jid, t, r, sel)
    txt = _texto(p)
    assert re.search(r"Localização:\s+Rua JC-58, Jardim Curitiba,", txt)
    assert "Lidiane" not in txt and "CRECI 11.991" not in txt and "Casa térrea de 3 quartos." in txt
    assert re.search(r"<w:rPr><w:b/>(?:(?!</w:r>).)*?<w:t[^>]*>Localização: </w:t>", _xml(p))   # rótulo em negrito


def test_083_b3_frase_dos_analisados_uma_vez_so():
    """Pág. 9 do 9120: "Foram analisados seis anúncios, que constituem…" e, abaixo, "Foram analisados 6 anúncios; …
    conforme o dossiê". Fica só a primeira."""
    jid, sel, r = _job()
    t = _textos()
    from lovable.avaliacao.agentes.redacao import NOMES
    chave = next(k for k, v in NOMES["OV"].items() if v == "pesquisa")
    t.secoes[chave] = "Foram analisados seis anúncios, que constituem a amostra. A consulta foi feita em 14/11/2026."
    txt = _texto(docx_builder.montar(jid, t, r, sel))
    assert txt.count("Foram analisados") == 1 and "Foram analisados seis anúncios" in txt


def test_078_1_legenda_do_anexo_sempre_em_cima_e_colada():
    """Págs. 20–21 do 9120: legenda do "Anexo do Comunicado" em cima da imagem do Comunicado e a do Comunicado
    embaixo. Agora: cada documento com a legenda em cima, colada (keepNext), sempre na mesma posição."""
    from lovable.avaliacao import docx_partes as X
    jid, sel, r = _job()
    p = docx_builder.montar(jid, _textos(), r, sel)
    body = Document(p).element.body
    ps = list(body.iter(qn("w:p")))
    i0 = next(i for i, x in enumerate(ps) if X.texto(x).startswith("Anexo III")      # o do corpo (com documento)
              and any(X.tem_imagem(y) for y in ps[i + 1:i + 4]))
    i1 = next(i for i in range(i0 + 1, len(ps)) if X.texto(ps[i]).startswith("Anexo IV"))
    trecho = ps[i0 + 1:i1]
    imgs = [k for k, x in enumerate(trecho) if X.tem_imagem(x)]
    assert imgs
    for k in imgs:
        leg = trecho[k - 1]
        if leg.getparent().tag != qn("w:body"):
            continue                               # página de grade (tabela 2 × 2)
        assert X.texto(leg).strip() and not X.tem_imagem(leg), "imagem sem legenda logo acima"
        assert leg.find(".//" + qn("w:keepNext")) is not None, "legenda solta da imagem"


def test_085_capa_completa_e_frase_das_medidas(monkeypatch):
    from lovable.avaliacao import tela_trabalho
    jid, sel, r = _job()
    monkeypatch.setattr(tela_trabalho, "_cliente", lambda j: {"contexto": {"medidas_confere": True}})
    monkeypatch.setattr(docx_builder, "_grafia_documento", lambda ctx, e: "Rua XV 9, Quadra 59, Lote 02")
    p = docx_builder.montar(jid, _textos(), r, sel)
    txt = _texto(p)
    assert "As medidas conferidas na vistoria são compatíveis com a escritura e com o cadastro municipal." in txt
    assert re.search(r"Rua XV 9, Quadra 59, Lote 02, [^.]+, Goiânia – GO\.", txt)


def test_087_lista_com_hifens_vira_paragrafos():
    from lovable.avaliacao import docx_partes as X
    t = ("Fatores considerados:\n- casa térrea de padrão simples;\n- idade aparente de cerca de 30 anos;\n"
         "- garagem coberta.\n\nO valor adotado é a média.")
    assert X.texto_por_partes(t) == ["Fatores considerados:", "• casa térrea de padrão simples;",
                                     "• idade aparente de cerca de 30 anos;", "• garagem coberta.", "O valor adotado é a média."]


def test_087_capa_nao_repete_o_bairro(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(docx_builder, "_endereco_partes", lambda ctx: "")
    monkeypatch.setattr(docx_builder, "_grafia_documento",
                        lambda ctx, e: "Rua XV 9, Quadra 59, Lote 02, Loteamento Jardim Curitiba, Goiânia – GO")
    ctx = SimpleNamespace(t=SimpleNamespace(tipo="Casa", bairro="Jardim Curitiba I", cidade="Goiânia"), cs=[])
    assert docx_builder._imovel(ctx) == "Casa – Rua XV 9, Quadra 59, Lote 02, Loteamento Jardim Curitiba, Goiânia – GO."
    monkeypatch.setattr(docx_builder, "_grafia_documento", lambda ctx, e: "Rua XV 9, Quadra 59, Lote 02")
    assert docx_builder._imovel(ctx) == "Casa – Rua XV 9, Quadra 59, Lote 02, Jardim Curitiba I, Goiânia – GO."


def test_092_menu_do_portal_nunca_vai_para_o_laudo_e_comparacao_e_subitem():
    jid, sel, r = _job()
    refs = list(sel.refs)
    lixo = ("Casas para venda com 3 quartos | ZAP Imóveis\nPular para o conteúdo principal\nAlugar Comprar Lançamentos\n"
            "Criar conta Entrar Simular consórcio. Favorite o anúncio e anote aqui. Casa com 3 quartos, espaço gourmet e "
            "piscina, 220 m² construídos.")
    comp = refs[0].model_copy(update={"n": 99, "decisao": "comparacao", "escolhido": False, "descricao": lixo,
                                      "titulo": "Casa 3 quartos 220 m²", "link": "https://www.zapimoveis.com.br/imovel/x-id-1/"})
    db.salvar_candidatos(jid, [comp])
    txt = _texto(docx_builder.montar(jid, _textos(), r, sel))
    for proibido in ("Pular para o conteúdo", "Criar conta", "Simular consórcio", "Favorite o anúncio"):
        assert proibido not in txt, proibido
    assert re.search(r"\d+\.\d+\.\s*Imóveis de padrão superior ofertados pelo mercado", txt)     # 117 / D-132


def test_095_quebra_sobe_e_faixa_uma_vez(monkeypatch):
    """095-1/5: o trecho que ficava sozinho numa página antes do bloco do valor desce junto com ele (a quebra sobe);
    a justificativa da faixa aparece uma vez só, depois da caixa."""
    from lovable.avaliacao import docx_partes as X
    jid, sel, r = _job()
    t = _textos()
    from lovable.avaliacao.agentes.redacao import NOMES
    chave = next(k for k, v in NOMES["OV"].items() if v == "determinacao")
    t.secoes[chave] = (t.secoes[chave] + "\n\nA faixa de variação de ±10% é admitida em razão da elevada dispersão entre os "
                       "valores unitários dos referenciais.")
    db.set_setting(f"quebra_valor_antes:{jid}", "")
    p = docx_builder.montar(jid, t, r, sel)
    body = Document(p).element.body
    ps = list(body.iter(qn("w:p")))
    ini = next(i for i, x in enumerate(ps) if X.texto(x).startswith("Valor de Mercado = Área"))
    antes = [X.texto(x) for x in ps[max(0, ini - 6):ini]]
    assert not any("faixa de variação de ±10%" in x for x in antes)            # só a de depois da caixa
    alvo = next(X.texto(x) for x in reversed(ps[:ini]) if X.texto(x).strip())
    db.set_setting(f"quebra_valor_antes:{jid}", alvo[:60])
    p2 = docx_builder.montar(jid, t, r, sel)
    ps2 = list(Document(p2).element.body.iter(qn("w:p")))
    quebra = [X.texto(x)[:40] for x in ps2 if x.find(".//" + qn("w:pageBreakBefore")) is not None]
    # 134-3: sem quebra forçada antes do bloco do valor (como no A1): nem no texto de antes, nem na conta
    assert not any(alvo[:30] in q for q in quebra) and not any(q.startswith("Valor de Mercado = Área") for q in quebra)


def test_095_titulo_perde_pagina_nova_quando_a_anterior_fica_vazia():
    import json as _json
    from lovable.avaliacao import docx_partes as X
    jid, sel, r = _job()
    alvo = next(X.texto(p) for p in Document(docx_builder.montar(jid, _textos(), r, sel)).element.body.iter(qn("w:p"))
                if re.match(r"^\d+\.\d+\.\s+Relat", X.texto(p)))
    db.set_setting(f"sem_quebra:{jid}", _json.dumps([alvo]))
    p = docx_builder.montar(jid, _textos(), r, sel)
    tit = next(x for x in Document(p).element.body.iter(qn("w:p")) if X.texto(x) == alvo)
    pb = tit.find(".//" + qn("w:pageBreakBefore"))
    assert pb is not None and pb.get(qn("w:val")) == "0" and tit.find(".//" + qn("w:keepNext")) is not None
    db.set_setting(f"sem_quebra:{jid}", "[]")


def test_096_8_itcd_cita_os_valores_do_comunicado():
    jid, sel, r = _job()
    from lovable.avaliacao.agentes import _comum
    t = _comum.trabalho(jid)
    db.atualizar_dados(jid, t.model_copy(update={"finalidade": "ITCD – justificar o valor declarado na malha fiscal"}))
    db.salvar_campos(jid, [Campo(nome="itcd_valor_declarado", valor=155694.94, origem="documento", fonte="comunicado"),
                           Campo(nome="itcd_valor_referencia_sefaz", valor=448335.57, origem="documento", fonte="comunicado"),
                           Campo(nome="fipe_valor_medio_mercado", valor=295124.02, origem="documento", fonte="FIPE")])
    txt = _texto(docx_builder.montar(jid, _textos(), r, sel))
    assert "448.335,57" in txt and "155.694,94" in txt and "295.124,02" in txt


def test_101_1_conta_so_na_planilha_nenhuma_frase_de_cv(monkeypatch):
    """101-1 (e): com o motivo "conta da dispersão só na planilha" (D-068), nenhum coeficiente, desvio, limite interno
    nem "sem o referencial X a média seria…" no laudo — nem o que o reforço automático escreveu."""
    jid, sel, r = _job()
    monkeypatch.setattr(db, "cv_so_na_planilha", lambda j: True)
    t = _textos()
    from lovable.avaliacao.agentes.redacao import NOMES
    chave = next(k for k, v in NOMES["OV"].items() if v == "determinacao")
    t.secoes[chave] = (t.secoes[chave] + "\n\nEsse coeficiente está acima do limite de 15% adotado pelo avaliador e indica "
                       "elevada dispersão. Sem ele, a média seria de R$ 1.452,44/m² e o coeficiente de variação seria de 24,87%.")
    txt = _texto(docx_builder.montar(jid, t, r, sel))
    for proibido in ("coeficiente", "1.452,44", "24,87", "limite de 15%"):
        assert proibido not in txt, proibido


def test_101_1_reforco_nao_e_correcao_do_avaliador():
    jid, _, _ = _job()
    db.evento(jid, "redacao", "correcao", "Reforce no texto (contestação simulada): A dispersão alta (CV de 32,9%)…")
    db.evento(jid, "redacao", "correcao", "Na finalidade, escreva inventário.")
    assert db.correcoes(jid, "redacao") == ["Na finalidade, escreva inventário."]


def test_105_idade_novo_e_subitens_do_estado():
    assert docx_builder.idade_valida("excelente estado de conservação") == ""
    assert docx_builder.idade_valida("", "Casa nova, nunca habitada, 3 quartos") == "novo"
    assert docx_builder.idade_valida("30 anos") == "30 anos" and docx_builder.idade_valida("seminovo") == "seminovo"
    from lovable.avaliacao import docx_partes as X
    jid, sel, r = _job()
    t = _textos()
    from lovable.avaliacao.agentes.redacao import NOMES
    chave = next(k for k, v in NOMES["OV"].items() if v == "descricao")
    t.secoes[chave] = ("- Tipo: Casa térrea.\n- Estado de conservação: Entre regular e reparos simples.\n"
                       "- pintura desgastada na fachada;\n- umidade na parede do banheiro;\n- Cobertura: telha cerâmica.\n"
                       + "\n".join(f"- Item {i}: texto" for i in range(6)))
    p = docx_builder.montar(jid, t, r, sel)
    ps = {X.texto(x).strip(): x for x in Document(p).element.body.iter(qn("w:p"))}
    sub = next(v for k, v in ps.items() if k.startswith("pintura desgastada"))
    top = next(v for k, v in ps.items() if k.startswith("Cobertura"))
    ind = sub.find(".//" + qn("w:ind"))
    assert ind is not None and ind.get(qn("w:left")) == "1080"
    assert top.find(".//" + qn("w:ind")) is None or top.find(".//" + qn("w:ind")).get(qn("w:left")) != "1080"


def test_106_nada_sobre_dispersao_em_laudo_nenhum():
    """106 (D-068, regra do projeto): sem a decisão gravada, mesmo assim nenhuma frase sobre dispersão; a faixa fica."""
    jid, sel, r = _job()
    t = _textos()
    from lovable.avaliacao.agentes.redacao import NOMES
    det = next(k for k, v in NOMES["OV"].items() if v == "determinacao")
    loc = next(k for k, v in NOMES["OV"].items() if v == "localizacao")
    t.secoes[det] = (t.secoes[det] + "\n\nA amostra apresenta dispersão elevada entre os valores unitários, característica de "
                     "mercado raso, em que as ofertas disponíveis no segmento são poucas e heterogêneas. O tratamento da "
                     "dispersão consta da planilha de cálculo que acompanha o presente parecer. Considerando essa dispersão, "
                     "admite-se faixa de variação de ±10%.")
    t.secoes[loc] = t.secoes[loc] + " O mercado é raso, com valores unitários bastante dispersos entre si."
    txt = _texto(docx_builder.montar(jid, t, r, sel))
    for proibido in ("dispers", "heterogêne", "coeficiente de variação", "Desvio padrão"):
        assert proibido.lower() not in txt.lower(), proibido
    assert "faixa de variação" in txt.lower()          # a faixa continua declarada (uma vez, depois da caixa)


def test_117_d133_anexos_numerados_com_divisor_e_sumario():
    """117 / D-133: cada documento do Anexo III com "3.N – nome", linha divisória e entrada no sumário."""
    import zipfile
    jid, sel, r = _job()
    p = docx_builder.montar(jid, _textos(), r, sel)
    xml = zipfile.ZipFile(p).read("word/document.xml").decode("utf-8")
    txt = _texto(p)
    assert re.search(r"3\.1 – \S", txt), "o 1º documento do anexo tem o número 3.1"
    assert 'w:name="sec_anx3_1"' in xml                       # marcador do sumário
    assert txt.count("3.1 – ") >= 2 or "sec_anx3_1" in xml    # no corpo e no sumário (campo TOC)


def test_125_mapa_em_branco_nao_entra_no_laudo(tmp_path):
    from PIL import Image as _I
    branco = tmp_path / "maps.png"
    _I.new("RGB", (1366, 900), (229, 227, 223)).save(branco)          # a tela cinza do Google Maps que não desenhou
    assert not docx_builder.mapa_utilizavel(branco)
