"""ORDEM 075-B: todo botão de pendência faz alguma coisa. Nenhum cartão tem "Resolver" que só abre detalhes;
"Imagem de localização ausente" gera pelo pin (ou pede o link); sem ação possível, só [Seguir assim]/[Entendi]."""
from lovable.avaliacao import db
from lovable.avaliacao import pendencias_simples as PS
from tests.avaliacao.test_pagina_enviada import _job

COM_EFEITO = {"aceitar", "alinhamento", "refazer_mapa", "reabrir", "candidatos", "ver_mapa", "editar_campo",
              "extensao", "enviar_arquivo", "enviar_foto", "pin", "ver_capa", "mapa_digital"}
AMOSTRA = [
    "localizacao: imagem de localização ausente no item 7.1",
    "revisor (jurídica/redação): Divergência para o avaliador decidir (_revisao/pagina-21.png). Área diferente.",
    "Nenhum documento do imóvel (matrícula, escritura ou IPTU)",
    "campo essencial pendente: Área construída",
    "contestação simulada (D-083), gravidade alta — pág. 9: amostra dispersa. Como reforçar: explicar.",
    "Ressalva sobre a amostra: referencial 3 tem padrão superior",
    "o anúncio 2 está sem foto principal",
    "algo que o sistema não sabe classificar",
    "O endereço de cadastro da contribuinte no comunicado difere do endereço do imóvel",
]


def test_todo_botao_tem_efeito():
    jid = _job()
    r = PS.classificar(jid, [{"texto": t, "grave": False} for t in AMOSTRA])
    for c in r["cards"]:
        assert all(o["rotulo"] != "Resolver" for o in c["opcoes"]), c
        rec = [o for o in c["opcoes"] if o.get("recomendada")] or c["opcoes"]
        assert rec[0]["acao"] in COM_EFEITO or (rec[0]["acao"] == "detalhe" and c["detalhe"].strip()), c
    assert len(r["cards"]) <= PS.MAX_PASSOS                                                          # 087: trava de 5
    loc = [t for t in AMOSTRA if "localiza" in t.lower()]
    r1 = PS.classificar(jid, [{"texto": t, "grave": False} for t in loc])
    assert any(c["chave"] == "mapa_falta" and c["opcoes"][0]["acao"] == "pin" for c in r1["cards"])   # sem pin: pede o link
    assert any("contribuinte" in a for a in r["avisos"])                                          # não trava


def test_com_pin_gera_pelo_pin():
    jid = _job()
    from lovable.avaliacao.agentes import _comum
    t = _comum.trabalho(jid)
    db.atualizar_dados(jid, t.model_copy(update={"pin_maps": "https://maps.app.goo.gl/AbCdEf123"}))
    r = PS.classificar(jid, [{"texto": "localizacao: imagem de localização ausente", "grave": False}])
    assert r["cards"][0]["opcoes"][0]["acao"] == "refazer_mapa"
