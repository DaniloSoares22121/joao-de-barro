"""ORDEM 087: o que vai para o avaliador cabe em no máximo 5 passos. Itens brutos de verdade do 9120 (58) e do 9121 (24)
na madrugada de 15/11 (sem dado de cliente: nomes, rua, bairro, quadra/lote, matrícula e CPF trocados)."""
import json
from pathlib import Path

import pytest

from lovable.avaliacao import db, pendencias_simples as P
from lovable.avaliacao.modelos import Referencial
from tests.avaliacao.test_pagina_enviada import ZAP, _job

FIX = Path(__file__).parent / "fixtures"


def _trabalho_com_6_anuncios_completos() -> str:
    jid = _job()
    db.salvar_candidatos(jid, [Referencial(n=n, link=f"{ZAP}casa-{n}/", portal="Deztop", bairro="Bairro Exemplo", tipologia="Casa",
                                           padrao="", idade_aparente="", descricao="", preco=170_000 + n, area_m2=100 + n,
                                           escolhido=True, decisao="entra", foto=f"mercado/enviado-{n}-foto.jpg",
                                           acessado_em="2026-11-15T00:40:00-03:00") for n in range(1, 7)])
    return jid


@pytest.mark.parametrize("caso", ["9120", "9121"])
def test_no_maximo_5_passos(caso):
    itens = json.loads((FIX / f"pendencias_087_{caso}.json").read_text(encoding="utf-8"))
    assert len(itens) >= 20                                  # o estado bruto de hoje (58 e 24)
    r = P.classificar(_trabalho_com_6_anuncios_completos(), itens)
    titulos = [c.get("titulo") or c.get("texto") or "" for c in r["cards"]]
    assert len(r["cards"]) <= 5, f"{len(r['cards'])} passos: {titulos}"
    for t in titulos:                                        # título é pergunta curta, sem resto de corte nem código
        assert "Seguir assim?" not in t or len(t) > 40, t
        assert not t.rstrip("? ").endswith(("pág", "pág.", "(pág")), t
        assert "Camada A" not in t, t
