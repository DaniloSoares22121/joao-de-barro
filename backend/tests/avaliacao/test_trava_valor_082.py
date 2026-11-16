"""ORDEM 082-4/5: o valor sai da conta. Unitário diferente da média só por decisão escrita do avaliador, para a
mesma amostra; mudou a amostra → volta a pergunta. A IA nunca fixa unitário nem escreve justificativa para ele."""
from decimal import Decimal

from lovable.avaliacao import pendencias_simples as PS
from lovable.avaliacao.agentes import selecao as S
from lovable.avaliacao.modelos import Referencial
from tests.avaliacao.test_pagina_enviada import _job


def _refs():
    return [Referencial(n=i, link=f"https://x/{i}", portal="p", bairro="b", tipologia="Casa", padrao="", idade_aparente="",
                        descricao="", preco=p, area_m2=a, escolhido=True, decisao="entra")
            for i, (p, a) in enumerate([(159_000, 110), (230_000, 230), (200_000, 80)], 1)]


def _sel(refs, just="escolha manual do avaliador: casa de esquina, melhor que a média"):
    return S.Selecao(refs=refs, unitario_adotado=Decimal("1627.03"), justificativa_unitario=just,
                     amostra=S.assinatura_amostra(refs))


def test_unitario_do_avaliador_vale_para_a_mesma_amostra():
    refs = _refs()
    assert S.unitario_valido(_sel(refs)) == (Decimal("1627.03"), "")


def test_mudou_uma_area_volta_a_pergunta():
    refs = _refs()
    sel = _sel(refs)
    sel.refs[0] = sel.refs[0].model_copy(update={"area_m2": 290})          # o envio "leu" 290
    u, problema = S.unitario_valido(sel)
    assert u is None and problema == S.AMOSTRA_MUDOU


def test_sem_justificativa_escrita_vale_a_media():
    refs = _refs()
    assert S.unitario_valido(_sel(refs, just="escolha manual do avaliador")) == (None, "")
    sem_retrato = S.Selecao(refs=refs, unitario_adotado=Decimal("1627.03"), justificativa_unitario="IA: imóvel menor")
    assert S.unitario_valido(sem_retrato) == (None, "")                    # unitário da IA: nunca vale


def test_cards_da_trava():
    jid = _job()
    r = PS.classificar(jid, [{"texto": "A amostra mudou depois que você fixou o unitário: a média agora é R$ 1.174,11/m²"},
                             {"texto": "Com os dados novos o valor muda: passaria de R$ 173.000,00 para R$ 125.000,00. "
                                       "Conferir os anúncios e confirmar o valor de novo?"}])
    ch = {c["chave"]: c for c in r["cards"]}
    assert [o["acao"] for o in ch["amostra_mudou"]["opcoes"]] == ["usar_media", "confirmar_valor"]
    assert ch["valor_mudou"]["impede"] and "R$ 125.000,00" in ch["valor_mudou"]["titulo"]
    assert not any(o["acao"] == "aceitar" for c in ch.values() for o in c["opcoes"])   # sem "seguir assim"


def test_084_3_so_comparacao_sai_da_conta():
    import asyncio
    from lovable.avaliacao import db, routes
    jid = _job()
    db.salvar_candidatos(jid, _refs())
    asyncio.run(routes.decidir_candidato(jid, 2, routes.Decisao(decisao="comparacao"), _u={}))
    c = next(x for x in db.candidatos(jid) if x.n == 2)
    assert c.decisao == "comparacao" and not c.escolhido


def test_083_b5_itcd_pergunta_a_comparacao():
    from lovable.avaliacao import db
    from lovable.avaliacao.modelos import Campo
    jid = _job()
    db.salvar_campos(jid, [Campo(nome="itcd_valor_referencia", valor=448335.57, origem="documento", fonte="comunicado")])
    card = next(c for c in PS.classificar(jid, [])["cards"] if c["chave"] == "comparacao_d069")
    assert "abaixo de R$ 448.335,57" in card["titulo"]
    assert [o["acao"] for o in card["opcoes"]] == ["adicionar_comparacao", "aceitar"]
    db.salvar_candidatos(jid, [r.model_copy(update={"decisao": "comparacao", "escolhido": False}) for r in _refs()[:1]])
    assert not any(c["chave"] == "comparacao_d069" for c in PS.classificar(jid, [])["cards"])


def test_l200_frase_da_trava_com_pontuacao_certa():
    """L200 (Caso W): a troca ponto/vírgula dos números valia para a frase inteira e a pontuação saía trocada
    ("…o unitário. com a sua justificativa,")."""
    import inspect
    from lovable.avaliacao import orquestrador
    src = inspect.getsource(orquestrador)
    i = src.index("você tinha adotado")
    trecho = src[i - 200:i + 300]
    assert "br(media)" in trecho and '"com a sua justificativa.")' in trecho
