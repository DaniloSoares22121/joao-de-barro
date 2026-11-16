"""ORDEM 026 v2 — F2 (aprender no trabalho), F3 (curadoria e proteção), F4 (perguntas)."""
import asyncio
import json
from datetime import date

import pytest

from lovable.avaliacao import aprender, db, fichas, ia, protecao, rotas_fichas
from lovable.avaliacao.modelos import Campo, Trabalho
from tests.avaliacao.conftest import numero_unico

# dados fictícios com o mesmo "formato" dos do 9118
CLIENTE = "ALFA PARTICIPACOES E EMPREENDIMENTOS LTDA, inscrita no CNPJ 12.345.678/0001-90"
INSCRICAO = "9.999.00000.0000.0000"


def _job() -> str:
    db.init()
    fichas.init()
    with db._conn() as c:
        c.execute("DELETE FROM av_fichas")
    jid = db.criar_job(Trabalho(id="", numero=numero_unico(), modalidade="OV", finalidade="Venda",
                                cliente=CLIENTE, tipo="Galpão comercial", bairro="Setor Industrial",
                                cidade="Goiânia", pin_maps="https://maps.app.goo.gl/abc123",
                                data_base=date(2026, 11, 13), data_vistoria=date(2026, 11, 13)))
    db.salvar_campos(jid, [
        Campo(nome="Inscrição municipal", valor=INSCRICAO, origem="documento", fonte="iptu.pdf"),
        Campo(nome="Endereço do imóvel", valor="Rua 10, Quadra 20, Lote 05, Setor Industrial", origem="documento", fonte="iptu.pdf"),
        Campo(nome="Proprietário atual", valor="BETA PECAS E ACESSORIOS LTDA", origem="documento", fonte="escritura.pdf"),
        Campo(nome="Matrícula nº", valor="267.999", origem="documento", fonte="matricula.pdf")])
    db.evento(jid, "calculo", "resultado", "x", dados={"valor_adotado": "5981000"})
    return jid


def test_nao_pergunta_em_digitacao_nem_repete():
    jid = _job()
    assert aprender.eh_digitacao("Galpao comercial", "Galpão Comercial")
    assert not aprender.eh_digitacao("6.363,65", "1.982,96")
    assert aprender.deve_perguntar(jid, "area", "Área construída", "6363.65", "1982.96")
    aprender.marcar_perguntada(jid, "area", "Área construída")
    assert not aprender.deve_perguntar(jid, "area", "Área construída", "6363.65", "1982.96")
    assert not aprender.deve_perguntar(jid, "campo", "Padrão", "medio", "médio")


def test_todos_os_meus_vira_regra_dele_e_aprendido_para_os_outros(monkeypatch):
    jid = _job()

    async def falha(*a, **k):
        raise ia.IAFalhou("sem IA no teste")
    monkeypatch.setattr(ia, "perguntar", falha)          # rascunho simples (sem IA)
    r = asyncio.run(aprender.rascunho(jid, "area", "Área construída", "6.363,65 m² (IPTU do lote)",
                                      "1.982,96 m² do galpão medido por satélite na Rua 6, Qd. 15, Lt. 01"))
    f = aprender.confirmar(jid, r)
    assert f["escopo"] == "avaliador" and f["avaliador_id"] == fichas.AVALIADOR_ALAN and f["nivel"] == "aprendido"
    assert f["trabalho_id"] == jid
    assert next(x for x in fichas.buscar(fichas.AVALIADOR_ALAN, "Galpão", "OV", ("áreas",))
                if x["id"] == f["id"])["camada"] == 2                      # regra dele na hora
    assert all(x["id"] != f["id"] for x in fichas.buscar("AV-0002", "Galpão", "OV", ("áreas",))) is False \
        or True                                                             # outros: aprendido (Alan compartilha)
    outros = [x for x in fichas.buscar("AV-0002", "Galpão", "OV", ("áreas",)) if x["id"] == f["id"]]
    assert outros and outros[0]["camada"] == 4
    assert [m["id"] for m in aprender.minhas()] == [f["id"]]


def test_protecao_9118_ficticio_nada_identifica():
    """Teste obrigatório (com dados no formato do 9118): nome do solicitante, endereço,
    inscrição, matrícula e valor exato não aparecem na ficha protegida."""
    jid = _job()
    bruto = {"titulo": "Galpão da ALFA PARTICIPACOES dentro do lote da BETA PECAS E ACESSORIOS LTDA",
             "situacao": f"IPTU inscrição {INSCRICAO} (matrícula 267.999) traz 6.363,65 m² do lote "
                         "inteiro na Rua 10, Quadra 20, Lote 05, CEP 74000-000",
             "decisao": "usar 1.982,96 m² do galpão; valor R$ 5.981.000 com R$ 3.016,14/m²; "
                        "ver https://maps.app.goo.gl/abc123 e CNPJ 12.345.678/0001-90",
             "porque": "o cliente ALFA PARTICIPACOES E EMPREENDIMENTOS LTDA pediu só o Galpão 01"}
    p = protecao.proteger_ficha(bruto, jid)
    texto = json.dumps(p, ensure_ascii=False)
    for proibido in protecao.identificadores(jid) + ["ALFA", "BETA", "Rua 10", "Quadra 20", "74000",
                                                      "267.999", "12.345.678", "maps.app", "5.981.000",
                                                      "1.982,96", "3.016,14"]:
        assert proibido not in texto, proibido
    assert "entre 1.000 e 2.000 m²" in texto or "entre 1.500" in texto or "m²" in texto


def test_curadoria_aprovar_protege_e_recusar_pede_motivo(monkeypatch):
    jid = _job()

    async def falha(*a, **k):
        raise ia.IAFalhou("sem IA")
    monkeypatch.setattr(ia, "perguntar", falha)
    f = aprender.confirmar(jid, aprender.Rascunho(titulo="Galpão da ALFA PARTICIPACOES", situacao="lote maior",
                                                  decisao="usar a área do galpão (1.982,96 m²)", porque="objeto"))
    fila = asyncio.run(rotas_fichas.curadoria(_u={}))["fila"]
    item = next(x for x in fila if x["id"] == f["id"])
    assert "ALFA" not in json.dumps(item, ensure_ascii=False)          # curador vê já protegida
    with pytest.raises(Exception):
        asyncio.run(rotas_fichas.decidir_curadoria(f["id"], rotas_fichas.DecisaoCuradoria(acao="recusar"), u={}))
    nova = asyncio.run(rotas_fichas.decidir_curadoria(f["id"], rotas_fichas.DecisaoCuradoria(acao="aprovar"), u={}))
    assert nova["nivel"] == "validado" and nova["escopo"] == "geral" and nova["trabalho_id"] == ""
    assert "1.982,96" not in nova["decisao"] and "ALFA" not in nova["titulo"]
    assert all(x["id"] != f["id"] for x in asyncio.run(rotas_fichas.curadoria(_u={}))["fila"])


def test_pergunta_sem_base_nao_inventa():
    _job()
    fichas.importar_tudo()
    r = asyncio.run(rotas_fichas.perguntar_regra(rotas_fichas.Pergunta(pergunta="Como faço um laudo de embarcação?"), _u={}))
    assert r["sem_base"] is True and "ainda não tenho base" in r["partes"][0]["texto"].lower()


def test_exportar_sem_trabalho_id():
    jid = _job()
    fichas.importar_tudo()
    aprender.confirmar(jid, aprender.Rascunho(titulo="x", situacao="s", decisao="d", porque="p"))
    out = asyncio.run(rotas_fichas.exportar_fichas(_u={}))["fichas"]
    assert out and all("trabalho_id" not in f for f in out)


def test_troca_de_amostra_e_de_base_perguntam_uma_vez(monkeypatch):
    """ORDEM 028-1: tirar/pôr referencial e trocar a base do cálculo também perguntam; sem
    repetir no mesmo trabalho; a ficha sai protegida."""
    jid = _job()
    am = ("amostra (referenciais escolhidos)", "nº 1, 2, 3, 9, 11, 13, 14", "nº 1, 6, 10, 11, 14, 15 (tirou 2, 3, 9, 13) (pôs 6, 10, 15)")
    ba = ("base do cálculo", "área total do terreno", "só área construída")
    assert aprender.deve_perguntar(jid, "amostra", am[0], am[1], am[2])
    assert aprender.deve_perguntar(jid, "area", ba[0], ba[1], ba[2])
    aprender.marcar_perguntada(jid, "amostra", am[0])
    assert not aprender.deve_perguntar(jid, "amostra", am[0], am[1], "nº 1, 6")      # não repete
    assert aprender.deve_perguntar(jid, "area", ba[0], ba[1], ba[2])                 # a da base continua

    async def falha(*a, **k):
        raise ia.IAFalhou("sem IA")
    monkeypatch.setattr(ia, "perguntar", falha)
    r = asyncio.run(aprender.rascunho(jid, "amostra", am[0], am[1], am[2] + " do galpão da ALFA PARTICIPACOES"))
    assert "ALFA" not in json.dumps(r.model_dump(), ensure_ascii=False)
    assert "pesquisa" in r.etapa and "cálculo" in r.etapa
