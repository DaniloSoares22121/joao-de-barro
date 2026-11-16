"""ORDEM 162-2: dois toques (duas abas do JdB no mesmo trabalho) não registram nada em dobro."""
from datetime import date

from lovable.avaliacao import db, planos
from lovable.avaliacao.modelos import Trabalho


def _job():
    n = 71001
    while db.numero_usado(n):
        n += 1
    return db.criar_job(Trabalho(id="", numero=n, modalidade="OV", finalidade="Venda", cliente="Cliente 162", tipo="Casa",
                                 bairro="B", cidade="C", pin_maps="", data_base=date(2026, 11, 15), data_vistoria=date(2026, 11, 15)))


def test_aprovar_duas_vezes_registra_uma():
    j = _job()
    a, b = planos.aprovar(j), planos.aprovar(j)
    assert a["novo"] is True and b["novo"] is False
    with db._conn() as c:
        assert c.execute("SELECT COUNT(*) FROM av_events WHERE job=? AND nivel='aprovado'", (j,)).fetchone()[0] == 1


def test_aceitar_duas_vezes_registra_uma():
    import asyncio
    from lovable.avaliacao.rotas_conversa import Aceite, aceitar_pendencia
    j = _job()
    for _ in range(2):
        try:
            asyncio.run(aceitar_pendencia(j, Aceite(chave="texto_jdb"), _u={}))
        except Exception:
            pass                                   # a lista de pendências (resposta) não importa aqui
    with db._conn() as c:
        n = c.execute("SELECT COUNT(*) FROM av_events WHERE job=? AND msg LIKE 'pendência aceita%'", (j,)).fetchone()[0]
    assert n == 1
