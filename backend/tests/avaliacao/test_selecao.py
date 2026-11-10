import asyncio
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from lovable.avaliacao import db, fonte_mercado, ia
from lovable.avaliacao.agentes import pesquisa, selecao
from lovable.avaliacao.modelos import Campo, Trabalho
from tests.avaliacao.conftest import numero_livre

FIX = Path(__file__).parent / "fixtures" / "ov120.json"


def _job(area=364.0) -> str:  # area pode ser texto pt-BR
    db.init()
    jid = db.criar_job(Trabalho(
        id="", numero=numero_livre(120), modalidade="OV", finalidade="Venda", cliente="Marina",
        tipo="Sobrado", bairro="Jardim Vila Boa", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
        data_base=date(2026, 10, 20), data_vistoria=date(2026, 10, 18)))
    db.salvar_campos(jid, [Campo(nome="area_construida", valor=area, unidade="m2",
                                 origem="documento", fonte="iptu.pdf")])
    return jid


def _ref(n, link, tip="Sobrado", area=200.0, preco=600000.0, bairro="Jardim Vila Boa", desc=""):
    return {"n": n, "link": link, "portal": "ZAP", "bairro": bairro, "tipologia": tip,
            "quartos": 3, "area_m2": area, "preco": preco, "padrao": "Simples",
            "idade_aparente": "Antiga", "descricao": desc}


def _fonte(tmp_path, refs) -> None:
    p = tmp_path / "mercado.json"
    p.write_text(json.dumps(refs, ensure_ascii=False), encoding="utf-8")
    fonte_mercado.registrar(fonte_mercado.FonteFixture(p))


def _mock(monkeypatch, escolher, unitario=None, motivo=lambda c: "menos_similar", faixa=None):
    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo=""):
        if esquema is pesquisa._Consultas:
            return esquema.model_validate({"consultas": [
                {"tipologia": "Sobrado", "bairro": "Jardim Vila Boa", "cidade": "Goiânia"}]})
        cands = db.candidatos(jid_box[0])
        return esquema.model_validate({
            "decisoes": [{"n": c.n, "escolhido": escolher(c),
                          "justificativa": "compatível" if escolher(c) else "excluído: incompatível",
                          "motivo_exclusao": "" if escolher(c) else motivo(c)}
                         for c in cands],
            "unitario_adotado": unitario, "justificativa_unitario": "média", "faixa_pct": faixa})
    jid_box = []
    monkeypatch.setattr(ia, "perguntar", fake)
    return jid_box


def test_selecao_ov120(monkeypatch, tmp_path):
    p8 = json.loads(FIX.read_text(encoding="utf-8"))
    for r in p8:
        r["escolhido"] = False
    extras = [
        _ref(0, "https://x.com/apto-1", tip="Apartamento", desc="apartamento"),
        _ref(0, "https://x.com/novo-2", desc="sobrado novo em fase de acabamento", preco=900000),
        _ref(0, "https://x.com/piscina-3", desc="sobrado com piscina e área gourmet", preco=1200000),
        dict(p8[0], link=p8[0]["link"] + "?utm_source=olx&utm_medium=x", portal="OLX"),
    ]
    _fonte(tmp_path, p8 + extras)
    links_p8 = {r["link"] for r in p8}
    box = _mock(monkeypatch, lambda c: c.link in links_p8)
    jid = _job()
    box.append(jid)
    cands = asyncio.run(pesquisa.rodar(jid))
    assert len(cands) == 8
    s = asyncio.run(selecao.rodar(jid))
    esc = [r for r in s.refs if r.escolhido]
    assert {r.link for r in esc} == links_p8
    assert all(r.justificativa for r in s.refs)
    assert s.declaracao_amostra == ""
    assert db.resultado(jid, "selecao") is not None


def test_dedup_link_utm(monkeypatch, tmp_path):
    _fonte(tmp_path, [_ref(0, "https://x.com/a"), _ref(0, "https://x.com/a?utm_source=x", preco=1)])
    box = _mock(monkeypatch, lambda c: True)
    jid = _job()
    box.append(jid)
    assert len(asyncio.run(pesquisa.rodar(jid))) == 1


def test_dedup_preco_area_bairro(monkeypatch, tmp_path):
    _fonte(tmp_path, [_ref(0, "https://x.com/a"), _ref(0, "https://y.com/b")])
    box = _mock(monkeypatch, lambda c: True)
    jid = _job()
    box.append(jid)
    assert len(asyncio.run(pesquisa.rodar(jid))) == 1


def test_completa_ate_cinco(monkeypatch, tmp_path):
    # unitários 3000,3050,3100,3150,3200,3500,3300 -> mediana 3150
    precos = [600000, 610000, 620000, 630000, 640000, 700000, 660000]
    refs = [_ref(0, f"https://x.com/{i}", area=200, preco=p,
                 bairro="Outro" if i == 3 else "Jardim Vila Boa") for i, p in enumerate(precos)]
    refs.append(_ref(0, "https://x.com/sem-area", area=None, preco=1))
    _fonte(tmp_path, refs)
    box = _mock(monkeypatch, lambda c: c.link.endswith(("/0", "/1", "/2")))
    jid = _job(area=210.0)
    box.append(jid)
    asyncio.run(pesquisa.rodar(jid))
    s = asyncio.run(selecao.rodar(jid))
    esc = {r.link.rsplit("/", 1)[1] for r in s.refs if r.escolhido}
    # 3 perde por bairro (pontuação); entre 4,5,6 desempata por |unitário − mediana|
    assert esc == {"0", "1", "2", "4", "6"}
    assert s.declaracao_amostra != ""
    sem = next(r for r in s.refs if r.link.endswith("sem-area"))
    assert not sem.escolhido and sem.justificativa


def test_completa_nunca_com_excluidos_por_regra(monkeypatch, tmp_path):
    refs = [_ref(0, f"https://x.com/{i}", area=200, preco=600000 + i * 1000) for i in range(3)]
    refs += [_ref(0, "https://x.com/apto", tip="Apartamento", preco=605000),
             _ref(0, "https://x.com/piscina", desc="com piscina", preco=601000),
             _ref(0, "https://x.com/m1", preco=650000),
             _ref(0, "https://x.com/m2", preco=660000)]
    _fonte(tmp_path, refs)
    regra = ("apto", "piscina")
    box = _mock(monkeypatch, lambda c: c.link.endswith(("/0", "/1", "/2")),
                motivo=lambda c: "regra" if c.link.endswith(regra) else "menos_similar")
    jid = _job(area=210.0)
    box.append(jid)
    asyncio.run(pesquisa.rodar(jid))
    s = asyncio.run(selecao.rodar(jid))
    esc = {r.link.rsplit("/", 1)[1] for r in s.refs if r.escolhido}
    assert esc == {"0", "1", "2", "m1", "m2"}


def test_completa_nao_usa_outra_tipologia_e_declara_reduzida(monkeypatch, tmp_path):
    refs = [_ref(0, f"https://x.com/{i}", area=200, preco=600000 + i * 1000) for i in range(3)]
    refs += [_ref(0, "https://x.com/apto", tip="Apartamento", preco=605000),
             _ref(0, "https://x.com/piscina", desc="com piscina", preco=601000),
             _ref(0, "https://x.com/m1", preco=650000)]
    _fonte(tmp_path, refs)
    box = _mock(monkeypatch, lambda c: c.link.endswith(("/0", "/1", "/2")),
                motivo=lambda c: "regra" if c.link.endswith("piscina") else "menos_similar")
    jid = _job(area=210.0)
    box.append(jid)
    asyncio.run(pesquisa.rodar(jid))
    s = asyncio.run(selecao.rodar(jid))
    esc = {r.link.rsplit("/", 1)[1] for r in s.refs if r.escolhido}
    assert esc == {"0", "1", "2", "m1"}
    assert s.declaracao_amostra.startswith("Amostra reduzida")


def test_area_br_e_ausente(monkeypatch, tmp_path):
    for txt, esperado in (("1.234,56", "1234.56"), ("364,00 m²", "364.00"), ("180", "180")):
        jid = _job(area=txt)
        assert selecao.area_construida(jid) == Decimal(esperado)
    _fonte(tmp_path, [_ref(0, f"https://x.com/{i}", area=200 + i, preco=600000 + i * 7000) for i in range(5)])
    box = _mock(monkeypatch, lambda c: True, unitario=3000)
    db.init()
    jid = db.criar_job(Trabalho(
        id="", numero=numero_livre(1), modalidade="OV", finalidade="Venda", cliente="X", tipo="Sobrado",
        bairro="Jardim Vila Boa", cidade="Goiânia", pin_maps="", data_base=date(2026, 10, 20),
        data_vistoria=date(2026, 10, 18)))
    box.append(jid)
    asyncio.run(pesquisa.rodar(jid))
    s = asyncio.run(selecao.rodar(jid))
    assert s.unitario_adotado is None
    assert _avisos(jid, "área construída do avaliando ausente")


def _avisos(jid, trecho):
    with db._conn() as c:
        rows = c.execute("SELECT msg FROM av_events WHERE job=? AND etapa='selecao' AND nivel='aviso'",
                         (jid,)).fetchall()
    return [r["msg"] for r in rows if trecho in r["msg"]]


def test_faixa_pct(monkeypatch, tmp_path):
    _fonte(tmp_path, [_ref(0, f"https://x.com/{i}", area=200 + i, preco=600000 + i * 7000) for i in range(5)])
    for faixa, esperado, aviso in ((15, "15", False), (0, "10", True), (45, "10", True)):
        box = _mock(monkeypatch, lambda c: True, faixa=faixa)
        jid = _job()
        box.append(jid)
        asyncio.run(pesquisa.rodar(jid))
        s = asyncio.run(selecao.rodar(jid))
        assert s.faixa_pct == Decimal(esperado)
        assert bool(_avisos(jid, "faixa_pct")) is aviso


def test_unitario_fora_do_intervalo_vira_none(monkeypatch, tmp_path):
    _fonte(tmp_path, [_ref(0, f"https://x.com/{i}", area=200 + i, preco=600000 + i * 7000) for i in range(5)])
    box = _mock(monkeypatch, lambda c: True, unitario=99999)
    jid = _job()
    box.append(jid)
    asyncio.run(pesquisa.rodar(jid))
    s = asyncio.run(selecao.rodar(jid))
    assert s.unitario_adotado is None


# ------------------------------------------------------------------ D5
def _r(n, preco, area=100.0, tip="Sobrado", publicado=""):
    from lovable.avaliacao.modelos import Referencial
    return Referencial.model_validate(dict(_ref(n, f"https://x.com/{n}", tip=tip, area=area,
                                                preco=preco), publicado_em=publicado))


def test_fora_da_curva_por_tipologia():
    sob = [_r(i, p) for i, p in enumerate([300000, 310000, 320000, 330000, 340000, 350000,
                                           900000], 1)]
    f = selecao.fora_da_curva(sob)
    assert set(f) == {7} and f[7].startswith(selecao.FORA_DA_CURVA) and "R$ 9.000,00/m²" in f[7]
    # menos de 7 válidos na tipologia: regra não se aplica
    assert selecao.MIN_PARA_CURVA == 7
    assert selecao.fora_da_curva([_r(i, p, tip="Casa") for i, p in
                                  enumerate([3e5, 3.1e5, 3.2e5, 3.3e5, 3.4e5, 9e5], 1)]) == {}
    # tipologias não se misturam: casas caras não são "fora da curva" dos sobrados
    casas = [_r(10 + i, 9e5 + i * 1e4, tip="Casa") for i in range(7)]
    assert set(selecao.fora_da_curva(sob[:6] + casas)) == set()


def test_fora_da_curva_iqr_minimo_de_5_por_cento_da_mediana():
    # 6 iguais (IQR = 0): sem o piso, qualquer diferença viraria "fora da curva"
    quase = [_r(i, 300000) for i in range(1, 7)] + [_r(7, 320000)]
    assert selecao.fora_da_curva(quase) == {}
    assert set(selecao.fora_da_curva([_r(i, 300000) for i in range(1, 7)] + [_r(7, 340000)])) == {7}


def test_fora_da_curva_excluido_antes_da_ia_e_nao_volta(monkeypatch, tmp_path):
    precos = [300000, 310000, 320000, 330000, 340000, 350000, 2000000]
    _fonte(tmp_path, [_ref(0, f"https://x.com/c{i}", preco=p) for i, p in enumerate(precos)])
    prompts = []
    box = _mock(monkeypatch, lambda c: True)          # a IA escolheria todos
    fake = ia.perguntar

    async def espia(sistema, prompt, esquema, **k):
        prompts.append(prompt)
        return await fake(sistema, prompt, esquema, **k)
    monkeypatch.setattr(ia, "perguntar", espia)
    jid = _job()
    box.append(jid)
    asyncio.run(pesquisa.rodar(jid))
    s = asyncio.run(selecao.rodar(jid))
    caro = next(r for r in s.refs if r.preco == 2000000)
    assert not caro.escolhido and selecao.FORA_DA_CURVA in caro.justificativa
    assert "Excluídos em código" in prompts[-1] and f"n {caro.n}:" in prompts[-1]
    assert sum(r.escolhido for r in s.refs) == 6


def test_anuncio_velho_perde_pontos():
    base = date(2026, 10, 20)
    novo, velho = _r(1, 3e5, publicado="2026-09-01"), _r(2, 3e5, publicado="2026-01-02")
    assert not selecao.anuncio_velho(novo, base) and selecao.anuncio_velho(velho, base)
    assert not selecao.anuncio_velho(_r(3, 3e5), base)           # sem data: sem penalidade
    p = lambda r: selecao._pontuacao(r, "Sobrado", "Jardim Vila Boa", None, 3, "", base)
    assert p(novo) - p(velho) == selecao.PENALIDADE_VELHO


def test_completar_prefere_anuncio_recente(monkeypatch, tmp_path):
    refs = [_ref(0, f"https://x.com/e{i}", preco=300000 + i * 1000) for i in range(6)]
    refs[0]["publicado_em"] = "2025-01-01"                      # velho
    _fonte(tmp_path, refs)
    box = _mock(monkeypatch, lambda c: c.link.endswith(("e2", "e3", "e4", "e5")))
    jid = _job()
    box.append(jid)
    asyncio.run(pesquisa.rodar(jid))
    refs_ = [r for r in asyncio.run(selecao.rodar(jid)).refs if r.escolhido]
    assert len(refs_) == 5 and {r.link for r in refs_} >= {"https://x.com/e1"}
    assert "https://x.com/e0" not in {r.link for r in refs_}
