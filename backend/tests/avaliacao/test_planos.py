"""ORDEM 040 / D-087: planos e cobrança (só local). Casos da ordem."""
from datetime import date

import pytest

from lovable.avaliacao import db, planos
from lovable.avaliacao.modelos import Trabalho
from tests.avaliacao.conftest import numero_unico


@pytest.fixture(autouse=True)
def _config_padrao():
    db.init()
    db.set_setting("planos", "{}")
    yield


def test_entrada_7_laudos_conta_e_aviso():
    c = planos.conta("entrada", 7)
    assert float(c.total) == 227.0 and c.extras == 2 and c.incluidos == 5   # 149 + 2 × 39
    a = planos.aviso_economia(c)
    assert a and a["para"] == "profissional"
    assert a["texto"] == ("Este mês você pagou R$ 227,00 no Entrada. Por R$ 22,00 a mais, no Profissional "
                          "você teria 10 laudos incluídos (5 a mais).")


def test_avulso_3_laudos_99_por_cento():
    c = planos.conta("avulso", 3)
    assert float(c.total) == 147.0
    a = planos.aviso_economia(c)
    assert a and a["tipo"] == "mais_incluidos"
    assert "Por R$ 2,00 a mais, no Entrada você teria 5 laudos incluídos" in a["texto"]


def test_avulso_2_laudos_sem_aviso():
    c = planos.conta("avulso", 2)
    assert float(c.total) == 98.0 and planos.aviso_economia(c) is None     # 66% de 149


def test_avulso_4_laudos_economia():
    c = planos.conta("avulso", 4)
    a = planos.aviso_economia(c)
    assert float(c.total) == 196.0 and a["tipo"] == "economia"
    assert a["texto"] == ("Este mês você pagou R$ 196,00 no Avulso. No Entrada, teria pago R$ 149,00 com 5 "
                          "laudos incluídos: economia de R$ 47,00.")


def test_entrada_6_laudos_sem_aviso():
    c = planos.conta("entrada", 6)
    assert float(c.total) == 188.0 and planos.aviso_economia(c) is None    # 75% de 249


def test_profissional_nao_tem_plano_acima():
    assert planos.aviso_economia(planos.conta("profissional", 30)) is None


def test_precos_vem_da_configuracao():
    db.set_setting("planos", '{"planos": {"entrada": {"preco": 159}}}')
    assert float(planos.conta("entrada", 5).total) == 159.0


def _job(cliente="Cliente X", av="AV-9999"):
    n = 70001
    while db.numero_usado(n):
        n += 1
    jid = db.criar_job(Trabalho(id="", numero=n, modalidade="OV", finalidade="Venda",
                                cliente=cliente, tipo="Casa", bairro="B", cidade="C", pin_maps="",
                                data_base=date(2026, 11, 14), data_vistoria=date(2026, 11, 14)))
    j = db.job(jid)
    d = j["dados"]
    d["avaliador_id"] = av
    with db._conn() as c:
        import json
        c.execute("UPDATE av_jobs SET dados_json=? WHERE id=?", (json.dumps(d, default=str), jid))
    return jid


def _rascunho(jid):
    """155: o 1º PDF entregue (evento "resultado" da entrega) é o que conta."""
    db.evento(jid, "entrega", "resultado", "PRONTO PARA REVISÃO", dados={"status": "PRONTO PARA REVISÃO", "arquivos": []})


def test_primeiro_laudo_gratis_uma_vez_so():
    av = "AV-GRATIS"
    a, b, t = _job(av=av), _job(av=av), _job(cliente="CÓPIA DE TESTE", av=av)
    for j in (a, b, t):
        _rascunho(j)
    _rascunho(a)                                        # nova versão do mesmo trabalho não conta 2×
    planos.aprovar(a)                                   # 155: aprovar não conta
    ms = planos.meses(av)
    assert len(ms) == 1 and ms[0]["laudos"] == 2 and ms[0]["gratis"] == 1   # o de teste não conta
    assert ms[0]["total"] == 49.0                         # avulso: 1 grátis + 1 × 49
    # num mês seguinte o grátis não se repete
    assert planos.conta("avulso", 2, 0).total == 98


def test_155_conta_no_primeiro_rascunho_nao_no_aprovar():
    av = "AV-RASC"
    a = _job(av=av)
    planos.aprovar(a)
    assert planos.meses(av) == []                       # aprovar sozinho não conta
    _rascunho(a)
    assert [m["laudos"] for m in planos.meses(av)] == [1]
    db.set_setting(f"lixeira:{a}", "1")                 # apagar depois do 1º rascunho continua contado
    assert [m["laudos"] for m in planos.meses(av)] == [1]
    c = _job(av=av)
    planos.marcar_teste(c)
    _rascunho(c)
    assert [m["laudos"] for m in planos.meses(av)] == [1]   # cópia de teste não conta


def test_156_dono_sem_limite_e_novo_com_limite():
    import json
    dono, novo = "AV-DONO", "AV-NOVO"
    db.set_setting("sem_limite", json.dumps([dono]))
    try:
        for _ in range(3):                              # o dono gera vários sem aviso
            j = _job(av=dono)
            assert planos.extra_antes_de_comecar(j) is None
            _rascunho(j)
        assert planos.plano_de(novo) == "avulso"        # usuário novo nasce no plano padrão (com limite)
        j1 = _job(av=novo)
        assert planos.extra_antes_de_comecar(j1) is None    # o 1º da vida é grátis
        _rascunho(j1)
        j2 = _job(av=novo)
        ex = planos.extra_antes_de_comecar(j2)          # acabou o incluído: aviso ANTES de começar, com o preço
        assert ex and ex["preco"] == 49.0 and "laudo extra" in ex["texto"]
        assert planos.sem_limite(novo) is False
    finally:
        db.set_setting("sem_limite", "[]")
