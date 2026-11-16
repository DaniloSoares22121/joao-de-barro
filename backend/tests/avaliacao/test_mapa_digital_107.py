"""ORDEM 107: print do Mapa Digital Fácil no padrão do PTAM 122 (lote certo, enquadramento pelos nomes das ruas,
quadro de zoom com as medidas). Só a forma do lote, deslocada — sem localização nem inscrição de cliente."""
import importlib.util

import pytest

from lovable.avaliacao import mapa_digital as M
from tests.avaliacao.test_mapa_digital_077 import ANEL_9120


def _col():
    spec = importlib.util.spec_from_file_location("coletor_mapa", M.COLETOR_SCRIPT)
    col = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(col)
    return col


def _servico(monkeypatch, nm_lot):
    def consulta(camada, params):
        if camada == 3:
            return [{"attributes": {"nrquadra": "59", "nrlote": "02", "nmbairro": "JARDIM EXEMPLO", "nmlogradou": "R  EX4",
                                    "areaterr": 300}, "geometry": {"rings": [ANEL_9120]}}]
        assert "ci='1234567890'" in params.get("where", "")          # o desenho pelo código do lote
        return [{"attributes": {"nm_lot": nm_lot}, "geometry": {"rings": [ANEL_9120]}}]
    monkeypatch.setattr(M, "_consulta", consulta)


def test_lote_marcado_e_o_do_cadastro(monkeypatch):
    _servico(monkeypatch, "2")
    d = M.dados_lote("12345678900000")
    assert d["lote"] == "02" and "ci%3D1234567890" in d["fonte"] and "Mapa_Basico3/MapServer/311/query" in d["fonte"]


def test_desenho_de_outro_lote_bloqueia(monkeypatch):
    _servico(monkeypatch, "1")
    with pytest.raises(ValueError, match="lote 1, mas o cadastro diz lote 02"):
        M.dados_lote("12345678900000")


def test_mesmo_lote():
    assert M.mesmo_lote("2", "02 ") and M.mesmo_lote("2A", "02a") and not M.mesmo_lote("1", "02")


def _rot(txt, x, y, tipo="rua"):
    return {"txt": txt, "tipo": tipo, "bbox": [x - 8, y - 2, x + 8, y + 2]}


def test_enquadrar_poe_a_rua_do_avaliando_e_uma_vizinha_fora_do_quadro():
    rots = [_rot("R EX 4", 150, -60), _rot("R EX 22", -140, 20), _rot("VIA Pedestre 1", 30, 30),
            _rot("Jd Exemplo", 900, 900, "bairro")]
    p = M.enquadrar(ANEL_9120, rots, "R  EX4", 0.2646)
    assert p["rua"] and p["vizinhas"] == ["R EX 22"] and p["setor"] == []      # o setor longe não coube: dito
    res, (X, Y) = p["res"], p["centro"]
    cw, ch = M.CAIXA
    bx = 16 if p["canto"][1] == "e" else M.LARG - 16 - cw
    by = 16 if p["canto"][0] == "s" else M.ALT - 16 - ch
    lx, ly = (0 - X) / res + M.LARG / 2, (Y - 0) / res + M.ALT / 2               # um canto do lote
    assert not (bx - 60 <= lx <= bx + cw + 60 and by - 60 <= ly <= by + ch + 60)


def test_enquadrar_com_setor_perto():
    rots = [_rot("R EX 4", 60, -40), _rot("R EX 22", -60, 20), _rot("Jd Exemplo", 0, -120, "bairro")]
    assert M.enquadrar(ANEL_9120, rots, "R EX 4", 0.2646)["setor"] == ["Jd Exemplo"]


def test_quadro_de_zoom_etiquetas_fora_do_lote():
    col = _col()
    segs = [{"a": a, "b": b, "txt": f"{i} m"} for i, (a, b) in enumerate(zip(ANEL_9120, ANEL_9120[1:]))]
    det = col.detalhe(ANEL_9120, segs, 494, 398)
    assert len(det["lados"]) == 4
    xs = [p[0] for p in det["anel"]]
    assert min(xs) > 494 * 0.2 and max(xs) < 494 * 0.8                            # o lote no meio, ampliado
    for s in det["lados"]:
        assert 0 < s["x"] < 494 and 0 < s["y"] < 398
    assert col.area_txt({"area": "300,00", "area_origem": "cadastro"}).startswith("Área (cadastro imobiliário)")


def test_medidas_de_fonte_escolhida_108(monkeypatch):
    _servico(monkeypatch, "2")
    d = M.dados_lote("12345678900000")
    M.aplicar_medidas(d, None)
    assert d["medidas_fonte"].startswith("planta da Prefeitura")
    M.aplicar_medidas(d, {"lados": ["12,00", "25,00", "12,00", "25,00"], "area": "300,00", "fonte": "escritura"})
    assert [s["txt"] for s in d["lados_seg"]] == ["12,00 m", "25,00 m", "12,00 m", "25,00 m"]
    assert d["area"] == "300,00" and d["medidas_fonte"] == "escritura" and _col().area_txt(d) == "Área: 300,00 m²"
    with pytest.raises(ValueError, match="vieram 3 medidas"):
        M.aplicar_medidas(d, {"lados": ["1", "2", "3"]})


# ------------------------------------------------------------------ 109-1: o quadro mostra o que o laudo adota (escritura)
from types import SimpleNamespace as _C  # noqa: E402

_CONF = ("Frente para a Rua EX-4: 11,58 m. Lado direito, com o Lt. 03: 24,49 m. Lado esquerdo, com o Lt. 01: 24,62 m. "
         "Fundo, com o Lt. 24: 11,72 m.")


def test_medidas_do_titulo_texto_e_campos_separados():
    a = M.medidas_do_titulo([_C(nome="confrontacoes_terreno", valor=_CONF, fonte="documento/Escrituração.pdf"),
                             _C(nome="area_terreno_escritura", valor=286.1, fonte="documento/Escrituração.pdf"),
                             _C(nome="area_terreno_iptu", valor=300.0, fonte="documento/INSCRIÇÃO.pdf")])
    assert a == {"frente": 11.58, "direito": 24.49, "esquerdo": 24.62, "fundo": 11.72, "area": 286.1}
    b = M.medidas_do_titulo([_C(nome="Frente do terreno – Rua EX (escritura)", valor="11.58", fonte="documento/x"),
                             _C(nome="Fundo do terreno – Lote 24 (escritura)", valor="11.72", fonte="documento/x"),
                             _C(nome="Lado direito do terreno (escritura)", valor="24.49", fonte="documento/x"),
                             _C(nome="Lado esquerdo do terreno (escritura)", valor="24.62", fonte="documento/x"),
                             _C(nome="area_terreno_titulo", valor="286.1", fonte="documento/Escrituração")])
    assert b and b["area"] == 286.1 and b["fundo"] == 11.72
    assert M.medidas_do_titulo([_C(nome="confrontacoes_terreno", valor="Frente: 10 m", fonte="documento/Escritura")]) is None


def test_casar_lados_pela_volta_do_lote():
    tit = {"frente": 11.58, "direito": 24.49, "fundo": 11.72, "esquerdo": 24.62}
    # o desenho (planta) na ordem em que foi traçado: 24,62 / 11,58 / 24,49 / 11,72
    assert M.casar_lados([24.62, 11.58, 24.49, 11.72], tit) == [24.62, 11.58, 24.49, 11.72]
    assert M.casar_lados([24.60, 11.60, 24.50, 11.70], tit) == [24.62, 11.58, 24.49, 11.72]
    assert M.casar_lados([30.0, 11.58, 24.49, 11.72], tit) is None              # o desenho não é o do título


def test_quadro_usa_a_escritura_e_o_setor_no_titulo(monkeypatch):
    _servico(monkeypatch, "2")
    d = M.dados_lote("12345678900000")
    monkeypatch.setattr(M.db, "campos", lambda j: [_C(nome="confrontacoes_terreno", valor=_CONF, fonte="documento/Escritura"),
                                                   _C(nome="area_terreno_escritura", valor=286.1, fonte="documento/Escritura")])
    med = M.medidas_adotadas("j", d)
    assert med["area"] == "286,10" and med["fonte"] == "escritura registrada" and sorted(med["lados"]) == sorted(
        ["11,58", "24,49", "24,62", "11,72"])
    M.aplicar_medidas(d, med)
    col = _col()
    assert col.area_txt(d) == "Área: 286,10 m²" and d["medidas_fonte"] == "escritura registrada"
    d["setor_no_titulo"] = True
    assert col.titulo(d) == "Quadra 59 – Lote 2 · Jardim Exemplo"


def test_um_campo_por_lado_como_no_trabalho_1_111():
    """111-1: no nº 1 a escritura veio um campo por lado ("confrontacao_frente" = "Rua EX-4 – 11,58 m")."""
    f = "documento/Escrituração.pdf#p2"
    a = M.medidas_do_titulo([_C(nome="area_terreno_escritura", valor=286.1, fonte=f),
                             _C(nome="area_terreno_iptu", valor=300.0, fonte="documento/INSCRIÇÃO.pdf#p2"),
                             _C(nome="confrontacao_frente", valor="Rua EX-4 – 11,58 m", fonte=f),
                             _C(nome="confrontacao_fundo", valor="Lote 24 – 11,72 m", fonte=f),
                             _C(nome="confrontacao_lado_direito", valor="Lote 03 – 24,49 m", fonte=f),
                             _C(nome="confrontacao_lado_esquerdo", valor="Lote 01 – 24,62 m", fonte=f)])
    assert a == {"frente": 11.58, "fundo": 11.72, "direito": 24.49, "esquerdo": 24.62, "area": 286.1}


def test_print_com_planta_e_refeito_quando_ha_escritura_111(monkeypatch):
    f = "documento/Escrituração.pdf#p2"
    campos = [_C(nome="confrontacao_frente", valor="Rua EX-4 – 11,58 m", fonte=f),
              _C(nome="confrontacao_fundo", valor="Lote 24 – 11,72 m", fonte=f),
              _C(nome="confrontacao_lado_direito", valor="Lote 03 – 24,49 m", fonte=f),
              _C(nome="confrontacao_lado_esquerdo", valor="Lote 01 – 24,62 m", fonte=f)]
    monkeypatch.setattr(M.db, "campos", lambda j: campos)
    monkeypatch.setattr(M, "_ultimo_gerado", lambda j: {"medidas_fonte": "planta da Prefeitura"})
    assert M.desatualizado("j")
    monkeypatch.setattr(M, "_ultimo_gerado", lambda j: {"medidas_fonte": "escritura registrada"})
    assert not M.desatualizado("j")
    monkeypatch.setattr(M.db, "campos", lambda j: [])
    monkeypatch.setattr(M, "_ultimo_gerado", lambda j: {"medidas_fonte": "planta da Prefeitura"})
    assert not M.desatualizado("j")                      # sem escritura com medidas: a planta vale
