"""116-2: o ditado dos ajustes vira os pares "Onde fica: / O que mudar:" (página, item, geral)."""
import asyncio
import io

from starlette.datastructures import UploadFile

from lovable.avaliacao import ditado, rotas_amostra, transcricao
from tests.avaliacao.test_pagina_enviada import _job

FALA = ("Na página oito, trocar construção novo por construção nova. Próximo: no item nove ponto três, juntar as duas "
        "primeiras frases numa só e não repetir o valor de referência. Outro ajuste: tirar a frase sobre como a idade "
        "dos referenciais foi estimada.")


def test_tres_ajustes_viram_tres_pares():
    p = ditado.pares_da_fala(FALA)
    assert [x["onde"] for x in p] == ["página 8", "item 9.3", ""]
    assert [x["duvida"] for x in p] == [False, False, True]
    assert p[0]["oque"] == "Trocar construção novo por construção nova."
    assert p[1]["oque"].startswith("Juntar as duas primeiras frases")
    assert ditado.quadro(p).splitlines()[:2] == ["Onde fica: página 8", "O que mudar: Trocar construção novo por construção nova."]


def test_numeros_so_depois_do_lugar_e_lugar_no_meio_da_frase():
    p = ditado.pares_da_fala("No anexo três, trocar uma foto. No item sete ponto quatro, mudar o texto do item nove ponto três.")
    assert [(x["onde"], x["oque"]) for x in p] == [("anexo III", "Trocar uma foto."),
                                                   ("item 7.4", "Mudar o texto do item 9.3.")]
    assert ditado.pares_da_fala("Na capa, a data-base fica treze de novembro")[0] == {
        "onde": "capa", "oque": "A data-base fica treze de novembro.", "duvida": False}


def test_rota_transcreve_e_monta_o_quadro(monkeypatch):
    jid = _job()
    monkeypatch.setattr(transcricao, "disponivel", lambda: True)
    monkeypatch.setattr(transcricao, "transcrever", lambda arq: (FALA, 12.0, 0.5))
    up = UploadFile(io.BytesIO(b"audio"), filename="fala.webm")
    r = asyncio.run(rotas_amostra.corrigir_ditado(jid, up, so_texto=0, _u={}))
    assert len(r["pares"]) == 3 and r["quadro"].startswith("Onde fica: página 8")
    up = UploadFile(io.BytesIO(b"audio"), filename="fala.m4a")
    assert asyncio.run(rotas_amostra.corrigir_ditado(jid, up, so_texto=1, _u={})) == {"texto": FALA}


def test_falar_em_qualquer_campo_119(monkeypatch):
    monkeypatch.setattr(transcricao, "disponivel", lambda: True)
    monkeypatch.setattr(transcricao, "transcrever", lambda arq: ("  usar só a data   da vistoria ", 3.0, 0.2))
    up = UploadFile(io.BytesIO(b"audio"), filename="campo.webm")
    assert asyncio.run(rotas_amostra.falar(up, _u={})) == {"texto": "usar só a data da vistoria"}
    monkeypatch.setattr(transcricao, "disponivel", lambda: False)
    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        asyncio.run(rotas_amostra.falar(UploadFile(io.BytesIO(b"a"), filename="x.webm"), _u={}))
    assert e.value.status_code == 503
