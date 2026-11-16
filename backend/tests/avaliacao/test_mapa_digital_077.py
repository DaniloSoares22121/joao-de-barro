"""ORDEM 077-1(b): os quatro lados do lote e os casos em que o JdB pede o print ao avaliador (sem internet)."""
from datetime import date

import pytest

from lovable.avaliacao import db, mapa_digital as M
from lovable.avaliacao.modelos import Trabalho
from tests.avaliacao.conftest import numero_unico


def test_lados_une_pontos_no_meio_do_lado():
    # retângulo 12 x 25 com um ponto a mais no meio do lado de 25 (como vem do cadastro)
    anel = [[0, 0], [12, 0], [12, 12.5], [12, 25], [0, 25], [0, 0]]
    ls = M.lados(anel)
    assert sorted(round(x["m"], 2) for x in ls) == [12.0, 12.0, 25.0, 25.0]


def test_lados_de_um_lote_inclinado():
    import math
    a = math.radians(30)
    rot = lambda x, y: [x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)]
    anel = [rot(0, 0), rot(11.58, 0), rot(11.58, 24.6), rot(0, 24.6), rot(0, 0)]
    assert [M.br(x["m"]) for x in M.lados(anel)].count("11,58") == 2


def _job(cidade: str) -> str:
    db.init()
    return db.criar_job(Trabalho(id="", numero=numero_unico(), modalidade="OV", finalidade="Venda", cliente="Teste",
                                 tipo="Casa", bairro="Centro", cidade=cidade, pin_maps="", data_base=date(2026, 11, 13),
                                 data_vistoria=date(2026, 11, 13)))


def test_fora_de_goiania_e_sem_inscricao_pedem_o_print():
    with pytest.raises(ValueError, match="só de Goiânia"):
        M.gerar(_job("Aparecida de Goiânia"))
    with pytest.raises(ValueError, match="inscrição"):
        M.gerar(_job("Goiânia"))


# ORDEM 077-B: o desenho do lote do 9120 (só a forma, deslocada para a origem; sem localização nem inscrição)
ANEL_9120 = [[0.0, 0.0], [-10.1089, -22.4538], [-20.6974, -17.7616], [-10.7696, 4.6246], [0.0, 0.0]]


def _servico_falso(monkeypatch, com_divisas=True):
    def consulta(camada, params):
        if camada == 3:
            return [{"attributes": {"nrquadra": "59", "nrlote": "02", "nmbairro": "JARDIM EXEMPLO", "nmlogradou": "R  EXEMPLO",
                                    "areaterr": 300}, "geometry": {"rings": [ANEL_9120]}}]
        return [{"geometry": {"rings": [ANEL_9120]}}] if com_divisas else []
    monkeypatch.setattr(M, "_consulta", consulta)


def test_area_do_quadro_e_a_da_planta_e_o_cadastro_fica_a_parte(monkeypatch):
    _servico_falso(monkeypatch)
    d = M.dados_lote("123")
    assert abs(float(d["area"].replace(".", "").replace(",", ".")) - 286.09) <= 0.05
    assert d["area_origem"] == "planta" and d["area_cadastro"] == "300,00"
    import importlib.util
    spec = importlib.util.spec_from_file_location("coletor_mapa", M.COLETOR_SCRIPT)
    col = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(col)
    # 107-b: no quadro só a área da planta; o cadastro (300,00) fica na legenda do laudo
    assert col.area_txt(d) == "Área: 286,09 m²" and col.titulo(d) == "Quadra 59 – Lote 2"


def test_sem_desenho_do_lote_a_area_e_dita_do_cadastro(monkeypatch):
    _servico_falso(monkeypatch, com_divisas=False)
    d = M.dados_lote("123")
    assert d["area"] == "300,00" and d["area_origem"] == "cadastro"


def test_hora_da_consulta_em_brasilia_e_a_mesma_no_carimbo_e_no_evento(monkeypatch):
    # 078-2: o carimbo da imagem e a legenda usam a MESMA hora, no horário de Brasília
    _servico_falso(monkeypatch)
    jid = _job("Goiânia")
    from lovable.avaliacao.modelos import Campo
    db.salvar_campos(jid, [Campo(nome="Inscrição imobiliária", valor="123", origem="documento", fonte="iptu.pdf")])
    visto = {}

    class R:
        returncode = 0

    def rodar(cmd, **kw):
        import json as _j
        from pathlib import Path as _P
        visto.update(_j.loads(_P(cmd[2]).read_text(encoding="utf-8")))
        _P(cmd[3]).write_bytes(b"png")
        return R()
    monkeypatch.setattr(M.subprocess, "run", rodar)
    d = M.gerar(jid)
    assert visto["consultado_em"] == d["consultado_em"]
    assert d["consultado_em_iso"].endswith("-03:00")
    assert d["area"] == "286,09" and d["area_planta"] == "286,09" and d["area_cadastro"] == "300,00"


def test_garantir_gera_uma_vez_so_em_goiania(monkeypatch):
    """085-4: trabalho novo de Goiânia com inscrição -> o mapa sai sozinho; já existindo, não gera de novo;
    fora de Goiânia ou com falha, não para nada."""
    from lovable.avaliacao.modelos import Campo
    chamadas = []

    def falso(jid):
        chamadas.append(jid)
        (db.pasta(jid) / M.ARQ).parent.mkdir(parents=True, exist_ok=True)
        (db.pasta(jid) / M.ARQ).write_bytes(b"png")
        db.adicionar_arquivo(jid, "mapa_digital_facil.png", "mapa_digital", M.ARQ, "", "")
        return {"imagem": M.ARQ}
    monkeypatch.setattr(M, "gerar", falso)
    monkeypatch.setattr(M, "ATIVO", True)
    jid = _job("Goiânia")
    db.salvar_campos(jid, [Campo(nome="Inscrição imobiliária", valor="123", origem="documento", fonte="iptu.pdf")])
    assert M.garantir(jid) == {"imagem": M.ARQ}
    assert M.garantir(jid) is None and len(chamadas) == 1          # já tem: não gera de novo
    assert M.garantir(_job("Aparecida de Goiânia")) is None and len(chamadas) == 1

    def quebra(jid):
        raise ValueError("O Mapa Digital Fácil pediu uma verificação de pessoa.")
    monkeypatch.setattr(M, "gerar", quebra)
    outro = _job("Goiânia")
    db.salvar_campos(outro, [Campo(nome="Inscrição imobiliária", valor="456", origem="documento", fonte="iptu.pdf")])
    assert M.garantir(outro) is None                                 # falhou: aviso, e a montagem segue
