"""ORDEM 032-4: recorte do mapa do 7.1 com folga em volta do contorno; aviso quando o contorno
passa por baixo da interface do Google Maps (painel lateral)."""
from PIL import Image, ImageDraw

from lovable.avaliacao import imagens


def _print_maps(tmp_path, painel: int = 400):
    im = Image.new("RGB", (1366, 900), (90, 110, 80))      # "satélite"
    ImageDraw.Draw(im).rectangle((0, 0, painel, 900), fill=(255, 255, 255))   # painel branco
    p = tmp_path / "maps.png"
    im.save(p)
    return p


def test_folga_minima_em_volta_do_contorno(tmp_path):
    av = []
    pol = [[800, 380], [1000, 380], [1000, 620], [800, 620]]
    out, pp = imagens.recortar_mapa(_print_maps(tmp_path), pol, tmp_path / "r.png", proporcao=1.5, avisos=av)
    w, h = Image.open(out).size
    xs, ys = [p[0] for p in pp], [p[1] for p in pp]
    folga = min(min(xs), w - max(xs), min(ys), h - max(ys))
    assert folga >= imagens.MARGEM_MAPA_PX and av == []


def test_contorno_sob_o_painel_avisa(tmp_path):
    av = []
    pol = [[380, 400], [600, 400], [600, 600], [380, 600]]
    imagens.recortar_mapa(_print_maps(tmp_path), pol, tmp_path / "r.png", proporcao=1.5, avisos=av)
    assert av and "painel" in av[0]


def test_galpao_tem_lote_maior_que_residencial(monkeypatch):
    from types import SimpleNamespace

    from lovable.avaliacao import coletor_fonte
    from lovable.avaliacao.agentes import _comum
    monkeypatch.setattr(_comum, "trabalho", lambda jid: SimpleNamespace(tipo="Galpão comercial"))
    assert coletor_fonte.lado_lote("x") == coletor_fonte.LADO_GALPAO_PX
    monkeypatch.setattr(_comum, "trabalho", lambda jid: SimpleNamespace(tipo="Sobrado residencial"))
    assert coletor_fonte.lado_lote("x") == coletor_fonte.LADO_LOTE_PX
    q = coletor_fonte.quadrado_no_pino((500, 500), coletor_fonte.LADO_GALPAO_PX)
    assert q[1][0] - q[0][0] == coletor_fonte.LADO_GALPAO_PX


def test_telha_metalica_nao_e_ceramica():
    from lovable.avaliacao import coletor_fonte as cf
    assert not cf.telhado_ceramico("cobertura: estrutura metálica com telhas metálicas trapezoidais")
    assert cf.telhado_ceramico("cobertura: telha cerâmica") and cf.telhado_ceramico("telhado de telha colonial")
