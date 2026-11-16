"""ORDEM 092-10: a contestação simulada recebe o que o avaliador informou e decidiu (é a fonte) e não pode atacar
isso como "sem fonte". Teste sem IA: a pergunta é capturada, não enviada."""
import asyncio

import pymupdf

from lovable.avaliacao import tela_trabalho
from lovable.avaliacao.agentes import contestacao as K
from tests.avaliacao.test_pagina_enviada import _job


def test_relato_e_decisoes_vao_para_a_contestacao(tmp_path, monkeypatch):
    jid = _job()
    monkeypatch.setattr(tela_trabalho, "_cliente", lambda j: {"contexto": {
        "medidas_confere": True, "estado_conservacao": "entre regular e reparos simples", "idade_aparente": "30",
        "pontos_negativos": ["casa de festas na mesma quadra"]}})
    visto = {}

    async def falsa(sistema, prompt, modelo_cls, **kw):
        visto.update(sistema=sistema, prompt=prompt)
        return K.Contestacao(pontos=[])
    monkeypatch.setattr(K.ia, "perguntar", falsa)
    pdf = tmp_path / "laudo.pdf"
    with pymupdf.open() as d:
        d.new_page().insert_text((40, 60), "Laudo de teste", fontsize=9)
        d.save(pdf)
    asyncio.run(K.rodar(pdf, jid))
    p = visto["prompt"]
    assert "INFORMADO E DECIDIDO PELO AVALIADOR" in p
    assert "medidas do terreno conferidas na vistoria" in p and "entre regular e reparos simples" in p
    assert "casa de festas na mesma quadra" in p and "30 anos" in p
    assert "não aponte esses pontos como" in visto["sistema"]
