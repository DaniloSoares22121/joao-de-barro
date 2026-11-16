"""109-4: cada entrega guarda a revisão (o que mudou) e "Desfazer esta revisão" volta a anterior."""
from datetime import date

from lovable.avaliacao import db, revisoes
from lovable.avaliacao.modelos import Trabalho
from lovable.avaliacao.tela_trabalho import _revisao


def _job() -> tuple[str, dict]:
    db.init()
    jid = db.criar_job(Trabalho(id="", numero=1, modalidade="AM", finalidade="Garantia", cliente="F", tipo="Casa",
                                bairro="Centro", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
                                data_base=date(2026, 11, 15), data_vistoria=date(2026, 11, 14)))
    p = db.pasta(jid)
    return jid, {"docx": p / "laudo.docx", "pdf": p / "laudo.pdf", "xlsx": p / "laudo.xlsx"}


def _entregar(jid, arqs, versao, valor):
    for p in arqs.values():
        p.write_text(versao, encoding="utf-8")
    db.evento(jid, "calculo", "resultado", "ok", dados={"valor_adotado": valor})
    db.evento(jid, "redacao", "resultado", "ok", dados={"secoes": {"7.4": versao}})
    db.evento(jid, "entrega", "resultado", "PRONTO", dados={"status": "PRONTO", "arquivos": ["laudo.pdf"]})
    return revisoes.fotografar(jid, arqs)


def test_revisao_lista_o_que_mudou_e_desfaz():
    jid, arqs = _job()
    assert _entregar(jid, arqs, "rev1", 300000.0) == 1
    db.evento(jid, "redacao", "correcao", "trocar a frase", dados={"texto_original": "Na página 8: trocar a frase X"})
    db.arquivar_entrega(jid)
    db.set_setting(f"redacao_mudou:{jid}", '["7.4"]')
    assert _entregar(jid, arqs, "rev2", 310000.0) == 2
    lista = revisoes.listar(jid)
    assert [r["n"] for r in lista] == [2, 1]
    mudou = " | ".join(lista[0]["mudou"])
    assert "Na página 8: trocar a frase X" in mudou and "item 7.4" in mudou and "R$ 310.000,00" in mudou

    assert revisoes.desfazer(jid, arqs) == 1
    assert _revisao(jid) == 1
    assert arqs["pdf"].read_text(encoding="utf-8") == "rev1"
    assert (db.pasta(jid) / "entrega" / "laudo.pdf").read_text(encoding="utf-8") == "rev1"
    assert db.resultado(jid, "calculo")["valor_adotado"] == 300000.0
    assert db.resultado(jid, "redacao")["secoes"]["7.4"] == "rev1"
    assert db.correcoes(jid, "redacao") == []                 # o pedido desfeito não volta na próxima montagem
    assert [r["n"] for r in revisoes.listar(jid)] == [1]


def test_sem_revisao_anterior_nao_desfaz():
    jid, arqs = _job()
    _entregar(jid, arqs, "rev1", 1.0)
    try:
        revisoes.desfazer(jid, arqs)
        assert False
    except revisoes.NaoDa as e:
        assert "anterior" in str(e)
