"""109-5: idade estimada pela foto → cartão 'Confere?' em 1 toque; confirmar vira idade do avaliador."""
from datetime import date

from lovable.avaliacao import db, pendencias_simples as PS
from lovable.avaliacao.modelos import Referencial, Trabalho


def test_cartao_idade_pela_foto_e_confirmar():
    db.init()
    jid = db.criar_job(Trabalho(id="", numero=1, modalidade="AM", finalidade="Garantia", cliente="F", tipo="Casa",
                                bairro="Centro", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
                                data_base=date(2026, 11, 15), data_vistoria=date(2026, 11, 14)))
    db.salvar_candidatos(jid, [Referencial(n=1, portal="OLX", link="https://x/1", area_m2=100, preco=300000, bairro="Centro", tipologia="Casa", padrao="", descricao="", decisao="entra",
                                           escolhido=True, idade_aparente="cerca de 10 anos", idade_fonte="fotos")])
    cards = PS.classificar(jid, [])["cards"]
    chaves = [c["chave"] for c in cards]
    assert "idade_foto:1" in chaves, chaves
    c = next(c for c in cards if c["chave"] == "idade_foto:1")
    assert "cerca de 10 anos" in c["titulo"] and c["opcoes"][0]["acao"] == "aceitar"
    PS.aceitar(jid, "idade_foto:1")
    assert db.candidatos(jid)[0].idade_fonte == "avaliador"
    assert "idade_foto:1" not in [c["chave"] for c in PS.classificar(jid, [])["cards"]]
