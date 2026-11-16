"""ORDEM 025 / D-057: o sistema escolhe fotos e páginas do anexo (sem limite de páginas)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from lovable.avaliacao import escolha_laudo as E
from lovable.avaliacao.modelos import Campo


def _foto(p: Path, cor: str, borrar: bool = False, forma: int = 0) -> Path:
    im = Image.new("RGB", (400, 300), cor)
    d = ImageDraw.Draw(im)
    for k in range(6):
        d.rectangle([20 + k * 60 + forma * 7, 40 + forma * 30, 50 + k * 60, 260 - forma * 25], fill="black")
    if borrar:
        im = im.filter(ImageFilter.GaussianBlur(4))
    im.save(p)
    return p


def test_tira_quase_iguais_fica_a_mais_nitida_e_ordena(tmp_path):
    arqs = {
        "foto/fachada.jpg": _foto(tmp_path / "fachada.jpg", "white", forma=0),
        "foto/sala_borrada.jpg": _foto(tmp_path / "sala_b.jpg", "gray", borrar=True, forma=2),
        "foto/sala.jpg": _foto(tmp_path / "sala.jpg", "gray", forma=2),
        "foto/lateral.jpg": _foto(tmp_path / "lateral.jpg", "green", forma=4),
        "foto/medicao.jpg": _foto(tmp_path / "medicao.jpg", "blue", forma=1),
    }
    itens = [{"arquivo": "foto/sala_borrada.jpg", "legenda": "Sala de estar", "ordem": 1},
             {"arquivo": "foto/sala.jpg", "legenda": "Sala de estar", "ordem": 2},
             {"arquivo": "foto/lateral.jpg", "legenda": "Lateral externa", "ordem": 3},
             {"arquivo": "foto/medicao.jpg", "legenda": "Medição", "ordem": 4}]
    out = E.escolher_fotos(itens, lambda r: arqs.get(r), marcada="foto/fachada.jpg",
                           excluir={"foto/medicao.jpg"})
    assert [f["arquivo"] for f in out] == ["foto/fachada.jpg", "foto/lateral.jpg", "foto/sala.jpg"]


def _cena(p: Path, semente: int) -> Path:
    """Cena distinta (blocos aleatórios): nenhuma é quase igual a outra."""
    import random
    r = random.Random(semente)
    im = Image.new("L", (400, 300), r.randint(0, 255))
    d = ImageDraw.Draw(im)
    for _ in range(25):
        x, y = r.randint(0, 380), r.randint(0, 280)
        d.rectangle([x, y, x + r.randint(10, 120), y + r.randint(10, 120)], fill=r.randint(0, 255))
    im.convert("RGB").save(p)
    return p


def test_sem_limite_fixo_de_fotos(tmp_path):
    arqs = {f"foto/{i}.jpg": _cena(tmp_path / f"{i}.jpg", i) for i in range(15)}
    itens = [{"arquivo": r, "legenda": f"Ambiente {i}", "ordem": i} for i, r in enumerate(arqs)]
    assert len(E.escolher_fotos(itens, lambda r: arqs[r])) > 12


def test_paginas_do_anexo_como_o_alan_9118():
    """ORDEM 028-3: no laudo oficial do Galpão 01 o Alan anexou as págs. 1–6 do PDF (escritura +
    verso com o registro) e a 1ª do IPTU; ITCD (p7, só CEP), DARE, certidões e as cópias da
    matrícula (p12, p14) ficaram só citadas. Campos e fontes no formato do 9118."""
    P = "documento/Escritura_Polo.pdf"
    fontes = [("Endereço", f"{P}#p2"), ("Bairro / Loteamento", f"{P}#p12"), ("CEP", f"{P}#p7"),
              ("Inscrição imobiliária municipal", f"{P}#p2"), ("Matrícula", f"{P}#p12"),
              ("Proprietário atual (escritura / IPTU)", f"{P}#p1"), ("Área do terreno", f"{P}#p12; documento/IPTU.pdf#p1"),
              ("Valor atribuído na doação (ITCD)", f"{P}#p3"), ("Proprietária conforme matrícula", f"{P}#p12; {P}#p14"),
              ("Título de aquisição", f"{P}#p1; {P}#p5"), ("Ônus e ações", f"{P}#p2; {P}#p4; {P}#p12"),
              ("CEP do imóvel", f"{P}#p7")]
    docs = [{"arquivo": P}, {"arquivo": f"{P}#p6"}]
    assert E.paginas_anexo(P, 15, fontes, docs) == [1, 2, 3, 4, 5, 6]          # igual ao Alan
    assert E.paginas_anexo("documento/IPTU.pdf", 1, fontes, docs) == [1]
    assert E.paginas_anexo("documento/x.pdf", 2, [], []) == [1, 2]
    # matrícula de 4 págs. com o ato citado na p4: o bloco vai até ela (lacuna de 1 página)
    assert E.paginas_anexo("m.pdf", 4, [("Matrícula", "m.pdf#p1"), ("Registro", "m.pdf#p3"), ("Ônus", "m.pdf#p4")], []) == [1, 2, 3, 4]
    # a extração indicou as páginas: manda
    assert E.paginas_anexo(P, 15, fontes, [{"arquivo": P, "paginas_anexo": [2, 99]}]) == [1, 2]


def test_prints_de_medicao_saem_das_fotos():
    cs = [Campo(nome="Área construída do Galpão 01 – medida por satélite", valor=1982.96, origem="inferido",
                fonte="foto/Frente.jpg (30,54 m); foto/Comprimento.jpg (64,93 m); foto/Mapa_e_localiza_o.jpg"),
          Campo(nome="Piso", valor="concreto", origem="vistoria", fonte="foto/IMG_1.jpg"),
          # ORDEM 030 (regressão OV 120): "Área de serviço" com foto da vistoria não é print de medição
          Campo(nome="Área de serviço", valor="coberta", origem="vistoria", fonte="foto/IMG_20261016_124016.jpg"),
          Campo(nome="Área de fundos", valor="sim", origem="vistoria", fonte="foto/IMG_2.jpg",
                observacao="Não foi medida e não consta em documento."),
          # regressão PTAM 116: a observação cita o Google, mas as fotos são da vistoria
          Campo(nome="Áreas comuns / lazer observadas", valor="academia", origem="vistoria",
                fonte="foto/Academia_.jpg; foto/Hall_2.jpg",
                observacao="A piscina aparece na imagem do Google (mercado/x.jpg).")]
    # ORDEM 031: os 3 prints do 9118 (frente, comprimento, mapa); foto de câmera nunca
    assert E.prints_medicao(cs) == {"foto/Frente.jpg", "foto/Comprimento.jpg", "foto/Mapa_e_localiza_o.jpg"}
    assert E.legenda_print("foto/Frente.jpg", cs) == \
        "Medição da frente do Galpão 01 por imagem de satélite (Google Maps) – 30,54 m"
    assert E.legenda_print("foto/Comprimento.jpg", cs) == \
        "Medição do comprimento do Galpão 01 por imagem de satélite (Google Maps) – 64,93 m"
    assert "Mapa" not in E.legenda_print("foto/Mapa_e_localiza_o.jpg", cs)
    sat = [Campo(nome="Área medida por satélite", valor=1, origem="inferido", fonte="foto/IMG_20261016_122417.jpg")]
    assert E.prints_medicao(sat) == set()


def test_ordem_dos_grupos():
    assert [E.grupo_legenda(x) for x in ("Fachada frontal", "Portão de acesso", "Sala", "Detalhe do quadro")] \
        == [0, 1, 2, 3]
