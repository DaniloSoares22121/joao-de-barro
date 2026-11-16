"""ORDEM 010 — proteções do "Confirmar valor" e limite de 2 rodadas de revisão (sem IA)."""
from datetime import date
from decimal import Decimal

from lovable.avaliacao import db, orquestrador
from lovable.avaliacao.modelos import Referencial, Trabalho
from lovable.avaliacao.routes import alertas_confirmacao
from tests.avaliacao.conftest import numero_unico


def _ref(n, **k):
    base = dict(n=n, link=f"https://x.com/{n}", portal="Imovelweb", bairro="B", tipologia="casa",
                area_m2=200.0, preco=600000.0, padrao="", idade_aparente="", descricao="",
                coletado=True, escolhido=True)
    base.update(k)
    return Referencial(**base)


def test_alertas_do_125():
    """A amostra do nº 125 (ORDEM 009) dispara os 5 alertas."""
    refs = [_ref(1), _ref(2, padrao="alto", descricao="piscina aquecida e sauna"),
            _ref(3), _ref(4, coletado=False, bloqueado=True), _ref(5)]
    al = alertas_confirmacao(refs, Decimal("2139.92"), Decimal("3241.08"), Decimal("2139.92"),
                             Decimal("4313.21"), 0.28)
    assert len(al) == 5
    assert "28,0%" in al[0] and "nº 2" in al[1] and "nº 4" in al[2]   # pt-BR (vírgula) desde a D-056
    assert "mínimo" in al[3] and "diferente da média" in al[4]


def test_sem_alertas_amostra_boa():
    refs = [_ref(i) for i in range(1, 6)]
    assert alertas_confirmacao(refs, Decimal("3000"), Decimal("3050"), Decimal("2800"),
                               Decimal("3300"), 0.06) == []


def test_enviado_pelo_avaliador_conta_como_conferido():
    refs = [_ref(1, fonte_coleta="avaliador", coletado=True), _ref(2, fonte_coleta="manual", coletado=False)]
    assert alertas_confirmacao(refs, None, Decimal("3000"), Decimal("2900"), Decimal("3100"), 0.03) == []


def test_rodadas_revisao_por_geracao():
    db.init()
    jid = db.criar_job(Trabalho(
        id="", numero=numero_unico(), modalidade="OV", finalidade="Venda", cliente="T", tipo="Casa",
        bairro="B", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
        data_base=date(2026, 11, 11), data_vistoria=date(2026, 11, 11)))
    db.evento(jid, "revisao", "resultado", "r1", dados={"aprovado": False})
    db.evento(jid, "orquestrador", "volta", "revisor reprovou", dados={"etapa": "redacao"})
    db.evento(jid, "revisao", "resultado", "r2", dados={"aprovado": False})
    assert orquestrador.rodadas_revisao(jid) == 2       # limite: não há 3ª volta automática
    orquestrador.reabrir(jid, "redacao", motivo="correção do avaliador")
    assert orquestrador.rodadas_revisao(jid) == 0       # nova geração pedida pelo avaliador
    assert orquestrador.MAX_REVISOES == 2
