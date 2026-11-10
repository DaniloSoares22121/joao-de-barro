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
        _img(pasta / "maps_satelite.png", "black", (1000, 700))
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
    assert "999" not in txt
    assert "364,00" in txt  # campo de documento aparece
    assert "Rua das Acácias, Quadra 12" in txt
    assert "SEGREDO-VERBAL-XYZ" not in txt


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
              "R$ 3.282,83/m²", "R$ 2.735,85/m²", "360,00", "R$ 995.849,40",
              "Foi adotado o Método Comparativo Direto", "IPTU 2025",
              "Notificação de lançamento do IPTU 2025"):
        assert s in txt, s
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

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo=""):
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


def test_pdf_solicitante_tarjado_por_pagina():
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


def test_solicitante_sem_tarja_nao_anexa_e_e_grave():
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

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo=""):
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

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo=""):
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


def test_pdf_solicitante_pagina_sem_tarja_nao_anexa_nada():
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


def test_tarja_infinita_ignorada():
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
    v = next(k for k, p in enumerate(ps) if p.text.strip() == "VALOR DE MERCADO ADOTADO")
    assert all(_keep(p, "w:keepNext") for p in ps[v:v + 2])
    assert all(_keep(p, "w:keepLines") for p in ps[v:v + 3])


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
    curto = dict(_textos().secoes, **{"5": "Foi adotado o Método Comparativo Direto.",
                                       "7.4": "Tipo: sobrado.\nPadrão construtivo: simples.",
                                       "9": "Adota-se o unitário de R$ 2.735,85/m²."})
    f = redacao.deficiencias("OV", curto)
    assert any(x.startswith("5 (metodologia)") and "homogeneização" in x for x in f)
    assert any(x.startswith("7.4 (descricao)") for x in f)
    assert any(x.startswith("9 (determinacao)") and "dispersão" in x for x in f)


def test_redacao_curta_vira_aviso_grave_e_volta_com_faltas(monkeypatch):
    from lovable.avaliacao import orquestrador
    jid, sel, r = _job()
    db.evento(jid, "selecao", "resultado", "ok", dados=sel.model_dump(mode="json"))
    prompts = []

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo=""):
        prompts.append((sistema, prompt))
        return esquema.model_validate({"secoes": dict(_textos().secoes, **{"5": "Curta."})})
    monkeypatch.setattr(ia, "perguntar", fake)
    t = asyncio.run(redacao.rodar(jid))
    assert t.faltas and t.faltas[0].startswith("5 (metodologia)")
    av = [m for m in _avisos(jid) if m.startswith(redacao.SECOES_SEM_TEXTO)]
    assert av and "metodologia" in av[0] and orquestrador._grave(av[0])
    asyncio.run(redacao.rodar(jid))  # nova rodada recebe as faltas da anterior
    assert "ABAIXO DO MÍNIMO" in prompts[1][1] and "5 (metodologia)" in prompts[1][1]
    # prompt traz exemplo do P8 e o CV calculado em código
    assert "Não foram aplicados fatores de homogeneização" in prompts[0][0]
    assert "coeficiente de variação" in prompts[0][1] and "Candidatos analisados" in prompts[0][1]


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
    from lovable.avaliacao import coletor_fonte
    r = Referencial(n=1, link="x", portal="p", bairro="b", tipologia="t", padrao="",
                    idade_aparente="", descricao="")
    assert r.fonte_coleta == "coletor" and r.visto_em == ""
    a = {"id": 1, "url_limpa": "u", "portal": "p", "bairro_norm": "b", "bairro": "B",
         "tipologia": "casa", "tipologia_txt": "", "quartos": 1, "suites": 0, "lote_m2": None,
         "area_m2": 1, "preco": 1, "padrao": "", "idade_aparente": "", "descricao": "",
         "foto_path": "", "print_path": "", "publicado_em": None, "visto_em": "2026-10-01T00:00"}
    rb = coletor_fonte._referencial_do_banco("j", a)
    assert rb.fonte_coleta == "banco" and rb.visto_em == "2026-10-01T00:00"
