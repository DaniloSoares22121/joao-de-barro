"""ORDEM 042 (D-094 a D-097): avaliador novo — cadastro, separação dos dados, anonimização,
preço da tabela própria, Minhas regras com aviso de norma revogada, identidade sem dados do Alan."""
import asyncio
import uuid
from datetime import date

import pytest
from fastapi import HTTPException

from lovable.avaliacao import avaliadores as A
from lovable.avaliacao import conhecimento, db, rotas_avaliadores as RA, rotas_propostas as RP, routes
from lovable.avaliacao.modelos import Trabalho


def _av(nome="TESTE X", **k):
    email = f"{uuid.uuid4().hex[:8]}@teste.invalid"
    return A.cadastrar(email, "senha-123", {"nome": nome, **k})


def _job_de(av):
    n = 90001
    while db.numero_usado(n):
        n += 1
    return db.criar_job(Trabalho(id="", numero=n, modalidade="OV", finalidade="Venda", cliente="Cliente TESTE",
                                 tipo="Casa", bairro="B", cidade="C", pin_maps="", data_base=date(2026, 11, 14),
                                 data_vistoria=date(2026, 11, 14), avaliador_id=av))


def test_codigo_nunca_reaproveitado():
    a = _av()
    A.apagar(a)
    b = _av()
    assert a != b


def test_cada_um_ve_so_o_seu():
    a, b = _av("TESTE A"), _av("TESTE B")
    ja, jb = _job_de(a), _job_de(b)
    routes.AV_ATUAL.set(b)
    lista = asyncio.run(routes.listar(_u={}))
    ids = {x["id"] for x in lista}
    assert jb in ids and ja not in ids
    with pytest.raises(HTTPException) as e:
        routes._job(ja)
    assert e.value.status_code == 404
    routes.AV_ATUAL.set("AV-0001")
    assert ja not in {x["id"] for x in asyncio.run(routes.listar(_u={}))}


def test_preco_da_tabela_propria_e_em_branco_sem_tabela():
    a = _av("TESTE A", precos={"OV": "500"})
    b = _av("TESTE B")
    assert A.preco(a, "OV") == "500" and A.preco(b, "OV") == ""
    assert asyncio.run(RP.preco_padrao(modalidade="OV", _u={"avaliador_id": b}))["valor"] == ""


def test_anonimiza_antes_de_guardar():
    t = ("Solicitante: Maria Joana TESTE da Silva, CPF 123.456.789-00, Rua Teste das Flores, 100, Quadra 7, "
         "Lote 9, Condomínio Jardim Teste, matrícula 12.345, e-mail maria@teste.invalid, tel. (62) 99999-0000, "
         "https://maps.app.goo.gl/abc. Valor R$ 652.300,00.")
    s = A.anonimizar(t)
    for x in ("Maria Joana", "123.456.789-00", "Flores", "Quadra 7", "Lote 9", "Jardim Teste", "12.345",
              "maria@", "99999", "maps.app", "652.300"):
        assert x not in s, x


def test_minhas_regras_avisa_norma_revogada_uma_vez():
    conhecimento.importar_normas()
    av = _av()
    u = {"avaliador_id": av}
    r = asyncio.run(RA.nova_regra(RA.NovaRegra(titulo="Base legal", decisao="citar a Res. COFECI 957/2006"), _u=u))
    assert r.get("precisa_confirmar") and "957/2006" in r["aviso"]
    r2 = asyncio.run(RA.nova_regra(RA.NovaRegra(titulo="Base legal", decisao="citar a Res. COFECI 957/2006",
                                                confirmo=True), _u=u))
    assert r2["ficha"]["avaliador_id"] == av and r2["ficha"]["escopo"] == "avaliador"
    h = asyncio.run(RA.historico(_u=u))["historico"]
    assert h and h[0]["regra"] == "Base legal" and "957" in h[0]["detalhe"]


def test_identidade_sem_dados_do_alan():
    from lovable.avaliacao import identidade
    av = _av("TESTE N", creci="000-TESTE")
    with identidade.do_avaliador(av):
        x = identidade.avaliador(A.identidade_avaliador(av))
        assert x["nome"] == "TESTE N" and x["cnai"] == "" and x["site"] == "" and x["telefone"] == ""
        assert identidade.caminho_logo() is None and identidade.AZUL == A.NEUTRO["principal"]
    assert identidade.AZUL == "18283B"                      # o Alan volta a ser o padrão (D-040)
    assert identidade.avaliador({})["cnai"] == "053569"
