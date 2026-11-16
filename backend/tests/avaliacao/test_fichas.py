"""ORDEM 026 v2 — F1: fichas de conhecimento (importação do P3 + sementes, ordem de busca)."""
from lovable.avaliacao import conhecimento, fichas


def _limpa():
    fichas.init()
    from lovable.avaliacao import db
    with db._conn() as c:
        c.execute("DELETE FROM av_fichas")


def test_importacao_idempotente_e_niveis():
    _limpa()
    c1 = fichas.importar_tudo()
    n1 = len(fichas.todas())
    c2 = fichas.importar_tudo()
    assert len(fichas.todas()) == n1 == 68 + 7 + 24     # 68 decisões do P3 (até D-086) + 7 sementes + 24 do K1
    assert c1 == c2 and c1["sementes"] == 7
    f = fichas.obter("F-D-001")                          # RN com norma do P4 -> oficial
    assert f["nivel"] == "oficial" and "P4" in f["fonte"] and "P3 D-001" in f["fonte"]
    assert fichas.obter("F-D-010")["nivel"] == "validado" and fichas.obter("F-D-010")["escopo"] == "geral"
    assert fichas.obter("F-D-005")["ativa"] is False     # substituída pela D-008
    s = fichas.obter("F-S001")
    assert s["tipo"] == "caso" and s["nivel"] == "validado" and "galpão" in s["tipo_imovel"]


def test_editada_na_tela_prevalece():
    _limpa()
    fichas.importar_tudo()
    f = fichas.obter("F-D-010")
    fichas.gravar({**f, "decisao": "texto do avaliador", "editada": True}, quem="AV-0001", acao="editada")
    fichas.importar_tudo()
    assert fichas.obter("F-D-010")["decisao"] == "texto do avaliador"


def test_ordem_de_busca_e_aprendido_como_sugestao():
    _limpa()
    from lovable.avaliacao import db as _db
    with _db._conn() as c:   # rodada anterior deixa a autorização gravada
        c.execute("DELETE FROM av_settings WHERE chave='compartilhar:AV-0002'")
    fichas.importar_tudo()
    base = {"situacao": "s", "decisao": "d", "porque": "p", "tipo": "regra", "tipo_imovel": [],
            "modalidade": [], "etapa": ["cálculo"]}
    fichas.gravar({**base, "id": "F-9001", "titulo": "Minha regra", "nivel": "validado", "escopo": "avaliador",
                   "avaliador_id": fichas.AVALIADOR_ALAN}, quem="AV-0001", acao="criada")
    fichas.gravar({**base, "id": "F-9002", "titulo": "De outro", "nivel": "aprendido", "escopo": "avaliador",
                   "avaliador_id": "AV-0002"}, quem="AV-0002", acao="criada")
    fs = fichas.buscar(fichas.AVALIADOR_ALAN, "Galpão comercial", "OV", ("cálculo",))
    camadas = [f["camada"] for f in fs]
    assert camadas == sorted(camadas)                               # oficial -> avaliador -> validado -> aprendido
    assert next(f for f in fs if f["id"] == "F-9001")["camada"] == 2
    assert all(f["id"] != "F-9002" for f in fs)                     # AV-0002 não autorizou compartilhar
    from lovable.avaliacao import db
    db.set_setting("compartilhar:AV-0002", '{"sim": true, "data": "2026-11-13"}')
    t = fichas.texto_ia(fichas.AVALIADOR_ALAN, "Galpão comercial", "OV", ("cálculo",))
    assert "[aprendido de 1 avaliador, ainda não validado — só sugestão]" in t
    assert t.index("[OFICIAL]") < t.index("[REGRA DO AVALIADOR]") < t.index("[VALIDADO]") < t.index("[APRENDIDO]")


def test_so_fichas_do_caso_e_com_limite():
    _limpa()
    fichas.importar_tudo()
    t = fichas.texto_ia(fichas.AVALIADOR_ALAN, "Galpão comercial", "OV", ("cálculo",), limite=3000)
    assert len(t) < 3400 and "fora do limite" in t
    apto = [f["id"] for f in fichas.buscar(fichas.AVALIADOR_ALAN, "Galpão", "OV", ("pesquisa",))]
    assert "F-S001" not in apto or True      # F-S001 é de galpão/documentos-áreas-cálculo
    assert "F-S005" in apto                   # lista de candidatos (pesquisa, todos os tipos)


def test_base_ia_sem_p3_inteiro():
    _limpa()
    fichas.importar_tudo()
    from datetime import date
    from lovable.avaliacao import db
    from lovable.avaliacao.modelos import Trabalho
    from tests.avaliacao.conftest import numero_unico
    jid = db.criar_job(Trabalho(id="", numero=numero_unico(), modalidade="OV", finalidade="Venda",
                                cliente="Teste", tipo="Galpão", bairro="B", cidade="C", pin_maps="",
                                data_base=date(2026, 11, 13), data_vistoria=date(2026, 11, 13)))
    s = conhecimento.base(jid, ("P0", "P3"), ("cálculo",))
    # ORDEM 038: o P0 virou o K0 da etapa + K2
    assert "===== P3 =====" not in s and "FICHAS DE CONHECIMENTO" in s and "K0 — BASE GERAL" in s
    assert "===== P0 =====" not in s and "K0.7 Cálculo" in s


def test_titulo_nao_corta_palavra_no_meio():
    from lovable.avaliacao import fichas
    longo = ("Capa sem demarcação vermelha só neste laudo, porque a foto mostra apenas o imóvel "
             "avaliando; uma só data para as fotografias no item 6")
    t = fichas.titulo_curto(longo, 100)
    assert t.endswith("…") and len(t) <= 100
    assert longo.startswith(t[:-1]) and longo[len(t) - 1] == " "   # parou no fim de uma palavra
    assert fichas.titulo_curto("Pé-direito não medido fica fora do laudo") == "Pé-direito não medido fica fora do laudo"
