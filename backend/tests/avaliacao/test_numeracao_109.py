"""109-2/109-3: numeração dos testes a partir do 1, separada da real; cliente na Lixeira some da lista sem apagar."""
from datetime import date

from lovable.avaliacao import db
from lovable.avaliacao.modelos import Trabalho


def _t(n: int) -> Trabalho:
    return Trabalho(id="", numero=n, modalidade="AM", finalidade="Garantia", cliente="Fulano", tipo="Casa",
                    bairro="Centro", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
                    data_base=date(2026, 11, 15), data_vistoria=date(2026, 11, 14))


def test_testes_comecam_do_1_e_a_real_fica_preservada():
    db.init()
    for n in (116, 123, 9118, 9127):
        db.criar_job(_t(n))
    assert db.proximo_numero() == 9119                    # real: maior real (9118) + 1; o 9127 é teste antigo
    db.set_setting("numeracao_modo", "teste")
    assert db.proximo_numero() == 1
    j1 = db.criar_job(_t(db.proximo_numero()))
    assert db.eh_teste(j1) and db.proximo_numero() == 2
    db.criar_job(_t(db.proximo_numero()))
    assert db.proximo_numero() == 3
    db.set_setting("numeracao_modo", "real")
    assert db.proximo_numero() == 9119                    # os testes 1 e 2 não mexem na numeração real
    db.set_setting("numeracao_real_proximo", "9200")      # o Alan pode informar o próximo número real
    assert db.proximo_numero() == 9200


def test_real_ignora_testes_antigos():
    db.init()
    with db._conn() as c:
        c.execute("DELETE FROM av_jobs"); c.execute("DELETE FROM av_settings WHERE chave LIKE 'numeracao%' OR chave LIKE 'job_teste:%'")
    for n in (116, 123, 9118):
        db.criar_job(_t(n))
    db.criar_job(_t(9125))
    assert db.proximo_numero() == 9119                    # 9119…9127 são testes antigos, ficam de fora do máximo


def test_cliente_na_lixeira_some_e_volta():
    from lovable.avaliacao import conversa as C, rotas_lixeira
    db.init()
    cid = C.criar("Fulano")
    rotas_lixeira.cliente_para_lixeira(cid)
    assert db.setting("lixeira_cliente:" + cid)
    assert C.obter(cid)                                   # nada apagado
    rotas_lixeira.cliente_restaurar(cid)
    assert not db.setting("lixeira_cliente:" + cid)
