"""083-B6: o revisor pedia de volta o desvio-padrão e o CV (D-068) e questionava a idade aparente e a frase das
medidas, que o avaliador respondeu. Resposta e decisão do avaliador são a fonte: não voltam como pendência."""
from lovable.avaliacao import db, pendencias_simples as PS
from lovable.avaliacao.agentes import revisor
from tests.avaliacao.test_pagina_enviada import _job


def test_contra_decisao():
    T = {"cv", "idade", "medidas"}
    assert revisor.contra_decisao("Item 9: falta desvio-padrão e CV; em AM a estatística tem de ser completa", T) == "cv"
    assert revisor.contra_decisao("Idade aparente sem fonte nos referenciais", T) == "idade"
    assert revisor.contra_decisao("A frase 'as medidas conferidas na vistoria são compatíveis' não tem fonte", T) == "medidas"
    assert revisor.contra_decisao("Cidade errada no item 3", T) == ""
    assert revisor.contra_decisao("Idade aparente sem fonte", set()) == ""      # sem resposta: continua pendência


def test_pendencias_contra_decisao_viram_aviso(monkeypatch):
    jid = _job()
    monkeypatch.setattr(revisor, "decisoes_do_trabalho", lambda j: ([], {"cv", "idade", "medidas"}))
    r = PS.classificar(jid, [{"texto": "revisor: falta o desvio padrão e o coeficiente de variação na tabela 9.2"},
                             {"texto": "revisor: idade aparente sem fonte"},
                             {"texto": "revisor: medidas compatíveis com a escritura sem fonte"}])
    assert r["cards"] == []
    assert any("Idade aparente" in a for a in r["avisos"]) and any("Medidas" in a for a in r["avisos"])


def test_decisoes_do_trabalho_le_d068(monkeypatch):
    jid = _job()
    monkeypatch.setattr(db, "instrucoes_avaliador", lambda j: ["Deixe a conta do coeficiente de variação só na planilha"])
    linhas, temas = revisor.decisoes_do_trabalho(jid)
    assert "cv" in temas and any("planilha" in x and "D-068" in x for x in linhas)
