"""108-1: abaixo da imagem do Mapa Digital Fácil só vai o link do site; a fonte dos dados (servidor) nunca aparece."""
from types import SimpleNamespace

import docx

from lovable.avaliacao import docx_builder as B


def _texto(doc) -> str:
    return "\n".join("".join(t.text or "" for t in p.iter(B.qn("w:t"))) for p in doc.element.body.iter(B.qn("w:p")))


def _rodar(monkeypatch, dados):
    monkeypatch.setattr(B.db, "setting", lambda *a, **k: None)
    doc = docx.Document()
    doc.add_paragraph("Consulta ao Mapa Digital Fácil da Prefeitura de Goiânia em 15/11/2026: Rua XV 9.")
    ctx = SimpleNamespace(body=doc.element.body, part=doc.part)
    B._links_mapa_digital(ctx, "x.png", dados)
    return _texto(doc)


def test_so_o_link_do_site(monkeypatch):
    t = _rodar(monkeypatch, {"url": "https://portalmapa.goiania.go.gov.br/mapafacil/",
                             "url_fonte": "https://portalmapa.goiania.go.gov.br/servicogyn/rest/services/MapaServer/Feature_Base/MapServer/3"})
    assert "Mapa Digital Fácil – Prefeitura de Goiânia: https://portalmapa.goiania.go.gov.br/mapafacil/" in t
    assert "Fonte dos dados" not in t and "servicogyn" not in t and "rest/services" not in t


def test_link_sempre_presente_mesmo_sem_dados(monkeypatch):
    t = _rodar(monkeypatch, {})
    assert "https://portalmapa.goiania.go.gov.br/mapafacil/" in t


def test_url_do_servidor_vira_o_site(monkeypatch):
    t = _rodar(monkeypatch, {"url": "https://portalmapa.goiania.go.gov.br/servicogyn/rest/services/X/MapServer/3"})
    assert "servicogyn" not in t and "mapafacil/" in t


def test_legenda_diz_a_fonte_das_medidas(monkeypatch):
    ctx = SimpleNamespace(job="j", cs=[], t=SimpleNamespace(bairro="Jardim Curitiba", cidade="Goiânia"))
    monkeypatch.setattr(B, "mapa_digital", lambda j: ("x.png", {"consultado_em": "15/11/2026 07:44", "quadra": "59", "lote": "02",
                                                               "area_planta": "286,09", "medidas_fonte": "planta da Prefeitura (Divisas de Lote)"}))
    monkeypatch.setattr(B, "_endereco_partes", lambda c: "Rua XV 9")
    leg = B._legenda_mapa_digital(ctx)
    assert "medidas conforme a planta da Prefeitura" in leg
    assert "servicogyn" not in leg


def test_legenda_escritura_109(monkeypatch):
    ctx = SimpleNamespace(job="j", cs=[], t=SimpleNamespace(bairro="Jardim Curitiba", cidade="Goiânia"))
    monkeypatch.setattr(B, "mapa_digital", lambda j: ("x.png", {"area_planta": "286,09", "medidas_fonte": "escritura registrada"}))
    monkeypatch.setattr(B, "_endereco_partes", lambda c: "Rua XV 9")
    assert "medidas conforme a escritura registrada" in B._legenda_mapa_digital(ctx)


def test_legenda_area_da_escritura_111(monkeypatch):
    ctx = SimpleNamespace(job="j", cs=[], t=SimpleNamespace(bairro="Jardim Curitiba", cidade="Goiânia"))
    monkeypatch.setattr(B, "mapa_digital", lambda j: ("x.png", {"area": "286,10", "area_planta": "286,09", "area_cadastro": "300,00",
                                                               "medidas_fonte": "escritura registrada"}))
    monkeypatch.setattr(B, "_endereco_partes", lambda c: "Rua XV 9")
    leg = B._legenda_mapa_digital(ctx)
    assert "área do lote (escritura registrada) 286,10 m²" in leg and "conforme a escritura registrada" in leg
    assert "(planta) 286,09" not in leg and "cadastro imobiliário" not in leg      # 117 / D-134


def test_legenda_imagem_e_link_juntos_113(monkeypatch):
    monkeypatch.setattr(B.db, "setting", lambda *a, **k: None)
    doc = docx.Document()
    leg = doc.add_paragraph("Consulta ao Mapa Digital Fácil da Prefeitura de Goiânia em 15/11/2026: Rua XV 9.")
    ctx = SimpleNamespace(body=doc.element.body, part=doc.part)
    B._links_mapa_digital(ctx, "x.png", {})
    ppr = leg._p.find(B.qn("w:pPr"))
    assert ppr is not None and ppr.find(B.qn("w:keepNext")) is not None


def test_comparacao_frase_unica_e_genero_113():
    import inspect
    src = inspect.getsource(B._comparacao_d069)
    assert "Mesmo" not in src and "Seguem" in src
    src2 = inspect.getsource(B)
    assert "construção {id_c[:-1] + 'a'}" in src2
