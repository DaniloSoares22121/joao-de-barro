"""ORDEM 021: o avaliador escolhe SEMPRE a base do cálculo (área construída × área do terreno)
e qual área usar. Caso real: nº 9118 (Galpão 01) — o IPTU traz 6.363,65 m² do lote inteiro e
o galpão medido por satélite tem 1.982,96 m² (laudo oficial do Alan: R$ 6.070.000)."""
import asyncio
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from lovable.avaliacao import calculo, db, orquestrador, routes
from lovable.avaliacao.agentes import selecao
from lovable.avaliacao.modelos import Campo, Referencial, Trabalho
from tests.avaliacao.conftest import numero_unico

# escolhidos do 9118 (unitário médio R$ 2.630,53)
AMOSTRA = [(1, 6000000, 2170), (2, 4600000, 1800), (3, 4800000, 1800), (9, 7149000, 2836),
           (11, 9000000, 3120), (13, 2990000, 1200), (14, 8600000, 3400)]


def _job(com_lote=True) -> str:
    db.init()
    jid = db.criar_job(Trabalho(
        id="", numero=numero_unico(), modalidade="OV", finalidade="Venda", cliente="Teste",
        tipo="Galpão comercial", bairro="Polo Empresarial Goiás", cidade="Aparecida de Goiânia",
        pin_maps="", data_base=date(2026, 11, 12), data_vistoria=date(2026, 5, 29)))
    db.salvar_campos(jid, [
        Campo(nome="Área do terreno", valor=19296.5, origem="documento", fonte="escritura.pdf#p12"),
        Campo(nome="Área edificada cadastrada (IPTU)", valor=6363.65, origem="documento", fonte="iptu.pdf"),
        Campo(nome="Área construída do Galpão 01 – medida por satélite", valor=1982.96,
              origem="inferido", fonte="foto/Frente.jpg (30,54 m); foto/Comprimento.jpg (64,93 m)"),
        Campo(nome="Área edificada (cadastro municipal)", valor=6363.65, origem="documento", fonte="iptu.pdf#p1"),
    ])
    refs = [Referencial(n=n, link=f"https://exemplo/{n}", portal="ZAP", bairro="Polo", tipologia="galpão",
                        preco=p, area_m2=a, lote_m2=(a * 3 if com_lote or n != 9 else None),
                        padrao="médio", idade_aparente="10 anos", descricao="galpão",
                        escolhido=True, decisao="entra", coletado=True)
            for n, p, a in AMOSTRA]
    db.salvar_candidatos(jid, refs, substituir=True)
    return jid


def _put(jid, **kw):
    corpo = {"escolhidos": [n for n, _, _ in AMOSTRA], "unitario_adotado": "2630,53",
             "justificativa": "média da amostra", "faixa_pct": "10",
             "confirmacao_alertas": "amostra conferida pelo avaliador", **kw}
    return asyncio.run(routes.escolher_referenciais(jid, routes.EscolhaReferenciais(**corpo), _u={}))


def test_areas_do_9118_tres_opcoes_e_sugerida_o_galpao():
    jid = _job()
    op = asyncio.run(routes.areas_do_calculo(jid, _u={}))
    constr = [(o["valor"], o["origem"], o["sugerida"]) for o in op["construida"]]
    assert constr == [(6363.65, "documento", False), (1982.96, "inferido", True)]   # IPTU uma vez só
    assert [(o["valor"], o["sugerida"]) for o in op["terreno"]] == [(19296.5, True)]
    assert op["escolha"] is None


def test_base_construida_galpao_01():
    jid = _job()
    r = _put(jid, continuar=False, base_area="construida",
             area_campo="Área construída do Galpão 01 – medida por satélite")
    assert Decimal(r["media"]) == Decimal("2630.53")
    # 1.982,96 m² × R$ 2.630,53 = 5.216.235,77 -> R$ 5.216.000 (±10%)
    assert r["area"] == "1982.96" and r["base_area"] == "construida"
    assert r["valor_adotado"] == "5216000" and r["valor_min"] == "4694400" and r["valor_max"] == "5737600"
    assert selecao.area_construida(jid) == Decimal("1982.96")      # cálculo, planilha, docx…
    assert selecao.origem_area_construida(jid) == "inferido"


def test_escolha_sobrevive_a_reextracao():
    jid = _job()
    selecao.gravar_escolha_area(jid, "construida", "Área construída do Galpão 01 – medida por satélite")
    db.salvar_campos(jid, db.campos(jid))           # reextração regrava os campos
    assert selecao.area_construida(jid) == Decimal("1982.96")


def test_continuar_sem_escolha_400():
    jid = _job()
    with pytest.raises(HTTPException) as e:
        _put(jid, continuar=True)
    assert e.value.status_code == 400 and e.value.detail == selecao.FALTA_ESCOLHA


def test_campo_fora_das_opcoes_400():
    jid = _job()
    with pytest.raises(HTTPException) as e:
        _put(jid, continuar=False, base_area="terreno", area_campo="Área edificada cadastrada (IPTU)")
    assert e.value.status_code == 400


def test_base_terreno_unitario_pelo_lote():
    jid = _job()
    r = _put(jid, continuar=False, base_area="terreno", area_campo="Área do terreno",
             unitario_adotado="", justificativa="")
    # lote = 3 × área: unitário de terreno = 1/3 do de construção
    assert Decimal(r["media"]) == Decimal("876.84")
    assert r["area"] == "19296.5"


def test_base_terreno_referencial_sem_lote_400_com_o_numero():
    jid = _job(com_lote=False)
    with pytest.raises(HTTPException) as e:
        _put(jid, continuar=False, base_area="terreno", area_campo="Área do terreno",
             unitario_adotado="", justificativa="")
    assert e.value.status_code == 400 and "nº 9" in e.value.detail


def test_calculo_na_base_terreno_usa_lote():
    refs = [Referencial(n=1, link="x", preco=900000, area_m2=300, lote_m2=900, escolhido=True,
                        padrao="", idade_aparente="", descricao="", portal="", bairro="", tipologia="")]
    na = selecao.refs_na_base(None, refs, "terreno")
    assert calculo.calcular(Decimal("1000"), na).unitario_adotado == Decimal("1000.00")


def _pronto_para_selecao(jid, monkeypatch):
    """Triagem, extração e pesquisa já feitas; seleção manual confirmada (como o 9118)."""
    from lovable.avaliacao import ia
    from lovable.avaliacao.agentes import extracao

    async def sem_ia(*a, **k):
        raise AssertionError("a retomada na seleção não pode chamar a IA")
    monkeypatch.setattr(ia, "perguntar", sem_ia)
    db.evento(jid, "triagem", "resultado", "ok", dados={"quadro": {}, "bloqueado": False, "motivo": ""})
    db.evento(jid, "extracao", "resultado", "ok",
              dados=extracao.Extracao(campos=db.campos(jid)).model_dump(mode="json"))
    db.evento(jid, "pesquisa", "resultado", "ok", dados={"refs": []})
    s = selecao.Selecao(refs=db.candidatos(jid), unitario_adotado=Decimal("2630.53"),
                        faixa_pct=Decimal("10"), confirmado=True)
    db.evento(jid, "selecao", "resultado", "x", dados={**s.model_dump(mode="json"), "manual": True})
    orquestrador.reabrir(jid, "selecao", motivo="teste")
    # a barreira invalida a seleção salva: regrava a escolha manual depois dela
    db.evento(jid, "selecao", "resultado", "x", dados={**s.model_dump(mode="json"), "manual": True})


def test_pipeline_selecao_manual_sem_escolha_aguarda(monkeypatch):
    jid = _job()
    _pronto_para_selecao(jid, monkeypatch)
    st = asyncio.run(orquestrador.executar(jid))
    assert st == orquestrador.AGUARDANDO
    assert db.job(jid)["etapa"] == "selecao"


# ------------------------------------------------------------------ ORDEM 022
SEIS = [(1, 6000000, 2170), (6, 5100000, 1650), (10, 4500000, 1300), (11, 9000000, 3120),
        (14, 8600000, 3400), (15, 3500000, 1040)]   # média 3.016,14


def _job6() -> str:
    jid = _job()
    refs = [Referencial(n=n, link=f"https://exemplo/s{n}", portal="ZAP", bairro="Polo", tipologia="galpão",
                        preco=p, area_m2=a, lote_m2=None, padrao="médio", idade_aparente="", descricao="",
                        escolhido=True, decisao="entra", coletado=True) for n, p, a in SEIS]
    db.salvar_candidatos(jid, refs, substituir=True)
    return jid


def _put6(jid, **kw):
    corpo = {"escolhidos": [n for n, _, _ in SEIS], "unitario_adotado": "3016,14",
             "justificativa": "média", "faixa_pct": "10", "continuar": False,
             "confirmacao_alertas": "conferido pelo avaliador", **kw}
    return asyncio.run(routes.escolher_referenciais(jid, routes.EscolhaReferenciais(**corpo), _u={}))


def test_salvar_grava_base_e_mostra_previa_9118():
    jid = _job6()
    r = _put6(jid, base_area="construida", area_campo="Área construída do Galpão 01 – medida por satélite")
    assert r["valor_adotado"] == "5981000" and r["valor_min"] == "5382900" and r["valor_max"] == "6579100"
    assert selecao.escolha_area(jid)["campo"].startswith("Área construída do Galpão 01")
    d = asyncio.run(routes.detalhe(jid, _u={}))
    assert d["resultado"] is None                      # nada de cálculo velho como atual
    assert d["previa_calculo"]["valor_adotado"] == "5981000" and d["previa_calculo"]["previa"] is True


def test_salvar_sem_escolha_valor_nulo_com_mensagem():
    jid = _job6()
    r = _put6(jid)
    assert r["valor_adotado"] is None and r["mensagem"] == selecao.SEM_VALOR
    d = asyncio.run(routes.detalhe(jid, _u={}))
    assert d["previa_calculo"]["pendente"] is True


def test_calculo_antigo_some_depois_da_reabertura():
    jid = _job6()
    db.evento(jid, "calculo", "resultado", "velho", dados={"area": "6363.65", "valor_adotado": "16740000",
                                                          "valor_min": "1", "valor_max": "2",
                                                          "unitario_adotado": "2630.53"})
    assert asyncio.run(routes.detalhe(jid, _u={}))["resultado"]["valor_adotado"] == "16740000"
    orquestrador.reabrir(jid, "selecao", motivo="teste")
    assert asyncio.run(routes.detalhe(jid, _u={}))["resultado"] is None


def test_tabela_de_areas_usa_a_area_escolhida_e_rotulo_com_pagina():
    """ORDEM 028-5 (revisor da cópia do 9118): a tabela 7.3/resumo mostrava a área do IPTU do
    lote inteiro e o nome cru do arquivo ("Escritura_Polo.pdf#p12;")."""
    from types import SimpleNamespace

    from lovable.avaliacao import docx_builder as DB
    jid = _job()
    cs = db.campos(jid)
    assert DB._constru(cs, jid).nome == "Área edificada cadastrada (IPTU)"       # sem escolha: o 1º
    selecao.gravar_escolha_area(jid, "construida", "Área construída do Galpão 01 – medida por satélite")
    assert DB._constru(cs, jid).nome.startswith("Área construída do Galpão 01")
    ctx = SimpleNamespace(ext={"documentos": [
        {"arquivo": "documento/Escritura_Polo.pdf", "rotulo_curto": "Escritura e matrícula"},
        {"arquivo": "documento/Escritura_Polo.pdf#p6", "rotulo_curto": "Registro R-2"}]},
        sem_rotulo=set(), aviso=lambda m: None)
    assert DB._rotulo(ctx, "documento/Escritura_Polo.pdf#p12; documento/IPTU.pdf#p1") == "Escritura e matrícula"
    assert DB._rotulo(ctx, "documento/Escritura_Polo.pdf#p6") == "Registro R-2"
    assert DB._rotulo(ctx, "documento/Outro.pdf#p3;") == "Outro.pdf"
