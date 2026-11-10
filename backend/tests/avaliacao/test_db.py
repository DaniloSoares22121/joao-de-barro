from datetime import date

from lovable import config
from lovable.avaliacao import db
from lovable.avaliacao.modelos import Campo, Referencial, Trabalho


def _trabalho(numero: int = 120) -> Trabalho:
    return Trabalho(
        id="", numero=numero, modalidade="AM", finalidade="Garantia", cliente="Fulano",
        tipo="Casa", bairro="Centro", cidade="Cuiabá", pin_maps="https://maps.app.goo.gl/x",
        data_base=date(2026, 10, 20), data_vistoria=date(2026, 10, 18),
    )


def test_job_roundtrip():
    db.init()
    jid = db.criar_job(_trabalho())
    j = db.job(jid)
    assert j["etapa"] == "nova"
    assert j["numero"] == 120
    assert j["dados"]["cliente"] == "Fulano"
    pasta = db.pasta(jid)
    assert pasta.is_dir()
    assert pasta == config.DATA_DIR / "avaliacao" / jid

    campos = [
        Campo(nome="area_terreno", valor=250.0, unidade="m2", origem="documento", fonte="matricula"),
        Campo(nome="padrao", valor="medio", origem="vistoria"),
        Campo(nome="idade", valor=None, origem="pendente", observacao="conferir"),
    ]
    db.salvar_campos(jid, campos)
    assert db.campos(jid) == campos
    # salvar de novo faz upsert por nome (nao apaga os outros)
    db.salvar_campos(jid, [campos[0].model_copy(update={"valor": 300.0})])
    atuais = db.campos(jid)
    assert [c.nome for c in atuais] == ["area_terreno", "padrao", "idade"]
    assert atuais[0].valor == 300.0


def test_candidatos_roundtrip():
    db.init()
    jid = db.criar_job(_trabalho(121))
    refs = [
        Referencial(n=i, link=f"https://x/{i}", portal="vivareal", bairro="Centro", tipologia="Casa",
                    quartos=3, suites=1, lote_m2=250.0, area_m2=120.0, preco=500000.0, padrao="medio",
                    idade_aparente="10 anos", descricao="d", escolhido=(i == 2))
        for i in (1, 2, 3)
    ]
    db.salvar_candidatos(jid, refs)
    assert db.candidatos(jid) == refs


def test_etapa_e_eventos_resultado():
    db.init()
    jid = db.criar_job(_trabalho(122))
    db.set_etapa(jid, "extracao", "rodando")
    j = db.job(jid)
    assert (j["etapa"], j["status"]) == ("extracao", "rodando")

    assert db.resultado(jid, "extracao") is None
    db.evento(jid, "extracao", "info", "oi")
    assert db.resultado(jid, "extracao") is None
    db.evento(jid, "extracao", "resultado", "v1", dados={"a": 1})
    db.evento(jid, "extracao", "resultado", "v2", dados={"a": 2})
    db.evento(jid, "outra", "resultado", "x", dados={"a": 9})
    assert db.resultado(jid, "extracao") == {"a": 2}
    assert db.resultado(jid, "outra") == {"a": 9}
