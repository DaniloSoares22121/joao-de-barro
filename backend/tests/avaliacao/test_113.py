"""113: remontagem liberada não volta a esperar; grave do revisor que sobrou vira passo; voltas desde o avaliador."""
from datetime import date

from lovable.avaliacao import db, orquestrador as O, pendencias_simples as PS
from lovable.avaliacao.modelos import Trabalho


def _job():
    db.init()
    return db.criar_job(Trabalho(id="", numero=1, modalidade="AM", finalidade="Garantia", cliente="F", tipo="Casa",
                                 bairro="Centro", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
                                 data_base=date(2026, 11, 15), data_vistoria=date(2026, 11, 14)))


def test_resposta_durante_a_montagem_entra_na_mesma_atualizacao():
    jid = _job()
    O.agendar_remontagem(jid, "resposta 1", etapa="redacao", atraso=0, esperar=True)
    assert O.remontagem_pendente(jid)["esperar"] is True
    O.atualizar_agora(jid)                                        # "Respondi tudo: atualizar o laudo"
    O.agendar_remontagem(jid, "resposta 2", etapa="montagem", atraso=0, esperar=True)   # chega enquanto monta
    p = O.remontagem_pendente(jid)
    assert p["esperar"] is False and p["motivos"] == ["resposta 1", "resposta 2"]


def test_grave_do_revisor_que_sobrou_vira_passo():
    jid = _job()
    pend = [{"texto": "revisor (redação/redação): Item 9.3: 'construção novo' tem erro de concordância.", "grave": True},
            {"texto": "revisor (visual/montagem): A legenda da foto 3 ficou na página seguinte.", "grave": True}]
    cards = PS.classificar(jid, pend)["cards"]
    assert [c["chave"] for c in cards] == ["texto_jdb"]
    leve = [{"texto": "revisor (redação/redação): vírgula sobrando.", "grave": False}]
    assert PS.classificar(jid, leve)["cards"] == []


def test_voltas_contam_desde_o_pedido_do_avaliador():
    jid = _job()
    for _ in range(3):
        db.evento(jid, "orquestrador", "volta", "revisor reprovou", dados={"etapa": "redacao"})
    assert O._Pipeline(jid).voltas == 3
    db.evento(jid, "orquestrador", "volta", "reaberto pelo avaliador", dados={"etapa": "redacao", "correcao": True})
    assert O._Pipeline(jid).voltas == 0


def test_reforco_na_mesma_passada_antes_de_entregar(monkeypatch):
    """113-3: o reforço da contestação refaz texto+montagem+revisão na mesma execução (sem remontar depois)."""
    import asyncio
    jid = _job()
    pipe = O._Pipeline(jid)
    chamadas = []

    async def ate(self):
        chamadas.append("revisao")

    async def conf(self, contestar=True):
        chamadas.append(f"conferencias:{contestar}")
    monkeypatch.setattr(O._Pipeline, "_ate_revisao", ate)
    monkeypatch.setattr(O._Pipeline, "_conferencias", conf)
    pipe.pend = [O._Pend("revisor (redação/redação): frase velha", True),
                 O._Pend("contestação simulada (D-083), gravidade alta — decisão do avaliador", True)]
    pipe.reforcar_agora = True
    asyncio.run(pipe._reforcar_e_conferir())
    assert chamadas == ["revisao", "conferencias:False"]
    assert [p.texto[:12] for p in pipe.pend] == ["contestação "]       # o do revisor sai (a revisão nova diz de novo)
    v = [e for e in db.eventos_desde(jid, 0) if e["nivel"] == "volta"][-1]
    assert v["dados"]["auto"] and v["dados"]["etapa"] == "redacao"
    assert O.remontagem_pendente(jid) is None                          # nada agendado para depois da entrega
