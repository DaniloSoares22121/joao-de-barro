"""ORDEM 047 / D-101: linha de etapas (Proposta → Contrato → Visita → Laudo → Assinatura) e
próximo passo em poucas palavras, para a tela do trabalho e a lista."""
from datetime import date, timedelta

from lovable.avaliacao import db, tela_trabalho as T
from lovable.avaliacao.modelos import Trabalho


def _job(vistoria: date) -> str:
    n = 70001
    while db.numero_usado(n):
        n += 1
    return db.criar_job(Trabalho(id="", numero=n, modalidade="OV", finalidade="Venda", cliente="Cliente X",
                                 tipo="Casa", bairro="B", cidade="C", pin_maps="",
                                 data_base=vistoria, data_vistoria=vistoria))


def _st(r):
    return {e["etapa"]: e["status"] for e in r["etapas"]}


def test_nao_iniciado_sem_visita_feita_fica_na_visita():
    r = T.resumo(db.job(_job(date.today() + timedelta(days=3))))
    assert [e["rotulo"] for e in r["etapas"]] == ["Proposta", "Contrato", "Visita", "Laudo"]   # 178: sem Assinatura
    assert _st(r)["proposta"] == "sem_registro"          # sem cliente e sem visita: não inventa
    assert _st(r)["visita"] == "atual" and r["atual"] == "visita"
    assert r["proximo"] == "Enviar arquivos e iniciar"


def test_laudo_pronto_e_aprovado():
    jid = _job(date.today() - timedelta(days=1))
    with db._conn() as c:
        c.execute("UPDATE av_jobs SET etapa='entrega', status='PRONTO PARA REVISÃO' WHERE id=?", (jid,))
    r = T.resumo(db.job(jid))
    # ORDEM 056: sem cliente nem fotos no JdB, nada ganha ✓ — "fora" (feita fora do JdB)
    assert _st(r)["proposta"] == "fora" and _st(r)["visita"] == "fora"
    assert _st(r)["laudo"] == "atual" and r["proximo"] == "Baixar para a revisão humana"
    db.evento(jid, "entrega", "aprovado", "PDF final aprovado pelo avaliador")
    r = T.resumo(db.job(jid))
    assert r["aprovado"] and _st(r)["laudo"] == "feito" and "assinatura" not in _st(r)
    assert r["proximo"] == "Laudo concluído ✓" and r["atual"] == "laudo"


def test_dados_alterados_pede_atualizar():
    jid = _job(date.today() - timedelta(days=1))
    with db._conn() as c:
        c.execute("UPDATE av_jobs SET etapa='entrega', status='PRONTO PARA REVISÃO' WHERE id=?", (jid,))
    db.evento(jid, "entrega", "resultado", "PRONTO PARA REVISÃO")
    db.evento(jid, "extracao", "edicao_manual", "área corrigida")
    assert T.resumo(db.job(jid))["proximo"] == "Atualizar o laudo"
