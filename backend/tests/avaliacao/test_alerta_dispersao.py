"""Alerta de amostra dispersa diz QUAL referencial espalha a amostra (pedido do Alan no 9118,
12/11/2026): sem isso o avaliador não sabe quem tirar."""
import statistics
from decimal import Decimal

from lovable.avaliacao.modelos import Referencial
from lovable.avaliacao.routes import alertas_confirmacao

# 9118 sem o nº 8: CV 17,4% (o que o Alan viu na tela)
UNIT = {1: (2170, 6_000_000), 2: (1800, 4_600_000), 3: (1800, 4_800_000), 4: (2336, 4_670_000),
        5: (1670, 3_700_000), 6: (1650, 5_100_000), 9: (2836, 7_149_000), 10: (1300, 4_500_000)}


def _refs():
    return [Referencial(n=n, link="https://x", portal="ZAP Imóveis", bairro="B", tipologia="comercial",
                        area_m2=a, preco=p, padrao="", idade_aparente="", descricao="",
                        fonte_coleta="avaliador", coletado=True) for n, (a, p) in UNIT.items()]


def test_alerta_aponta_quem_espalha_a_amostra():
    refs = _refs()
    us = [r.preco / r.area_m2 for r in refs]
    cv = statistics.stdev(us) / statistics.mean(us)
    media = Decimal(str(statistics.mean(us)))
    al = alertas_confirmacao(refs, None, media, Decimal(str(min(us))), Decimal(str(max(us))), cv)
    msg = next(a for a in al if a.startswith("amostra dispersa"))
    assert "17,4%" in msg
    assert "nº 10 (R$ 3.461,54/m², o mais alto): sem ele, 14,1%" in msg
    assert "nº 4 (R$ 1.999,14/m², o mais baixo): sem ele, 14,9%" in msg


def test_amostra_concentrada_sem_alerta():
    refs = _refs()[:3]
    us = [r.preco / r.area_m2 for r in refs]
    cv = statistics.stdev(us) / statistics.mean(us)
    assert not [a for a in alertas_confirmacao(refs, None, None, Decimal(0), Decimal(0), cv)
                if a.startswith("amostra dispersa")]
