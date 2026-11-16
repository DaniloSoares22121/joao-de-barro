"""ORDEM 194: galeria "Modelos de laudo" — um modelo por modalidade, exemplo em PDF (dados inventados),
[Subir o meu modelo] com "o que entendi" e [Voltar para o do sistema]. IA simulada."""
import asyncio
import io
from datetime import date

import pytest
from fastapi import HTTPException, UploadFile

from lovable.avaliacao import avaliadores as A
from lovable.avaliacao import db, fichas, ia
from lovable.avaliacao import rotas_avaliadores as RA
from lovable.avaliacao import routes

TEXTO = ("LAUDO DE EXEMPLO. Sumário: 1 Finalidade; 2 Vistoria; 3 Pesquisa; 4 Cálculo; 5 Conclusão. "
         "Solicitante: Sr. João Exemplo da Silva, CPF 123.456.789-00, Rua das Flores 100. ") * 6


def _av():
    import uuid
    return A.cadastrar(f"m194-{uuid.uuid4().hex[:10]}@teste.local", "senha-194-ok", {"nome": "Avaliador 194", "cnai": "1"})


def _upload(nome="meu.docx"):
    import docx
    d = docx.Document(); d.add_paragraph(TEXTO); b = io.BytesIO(); d.save(b); b.seek(0)
    return UploadFile(file=b, filename=nome)


@pytest.fixture
def ia_simulada(monkeypatch):
    async def falsa(sistema, prompt, esquema, **k):
        assert "123.456.789-00" not in prompt and "João Exemplo" not in prompt     # anonimizado antes da IA
        return esquema(topicos=["Sumário com 5 itens", "Conclusão em parágrafo único"])
    monkeypatch.setattr(ia, "perguntar", falsa)
    monkeypatch.setattr(ia, "definir_contexto", lambda *a, **k: None)


def test_galeria_comeca_no_sistema_e_exemplos_existem():
    av = _av()
    r = asyncio.run(RA.ver_modelos_laudo(_u={"avaliador_id": av}))
    assert [m["cod"] for m in r["modalidades"]] == ["OV", "AM", "AM_GARANTIA", "AMJ"]
    assert all(m["em_uso"] == "sistema" for m in r["modalidades"])
    for nome in A.NOMES_EXEMPLO:
        assert (A.EXEMPLOS / f"{nome}.pdf").is_file() and (A.EXEMPLOS / f"{nome}.png").is_file()
    with pytest.raises(HTTPException):
        asyncio.run(RA.exemplo_modelo("../app", _u={"avaliador_id": av}))


def test_subir_confirmar_e_voltar_por_modalidade(ia_simulada):
    av = _av()
    u = {"avaliador_id": av}
    r = asyncio.run(RA.subir_modelo(qual="laudo", arquivo=_upload(), modalidade="AM", _u=u))
    assert r["topicos"] and r["modalidade"] == "AM"
    guardado = (A.pasta(av) / "modelos" / r["guardado"]).read_text(encoding="utf-8")
    assert "123.456.789-00" not in guardado                             # sem dado de cliente
    assert A.modelo_em_uso(av, "AM") == "sistema"                       # antes de confirmar, nada muda
    ok = asyncio.run(RA.confirmar_topicos(RA.Confirmados(topicos=r["topicos"], modalidade="AM", guardado=r["guardado"]), _u=u))
    assert A.modelo_em_uso(av, "AM") == "proprio" and A.modelo_em_uso(av, "OV") == "sistema"
    regra = fichas.obter(ok["regras"][0])
    assert regra["modalidade"] == ["AM"] and regra["ativa"]
    # o trabalho mostra o modelo em uso, sem botão
    jid = db.criar_job(routes.Trabalho(id="", numero=9194, modalidade="AM", finalidade="Venda", cliente="X", tipo="Casa",
                                       bairro="B", cidade="Goiânia", pin_maps="", avaliador_id=av,
                                       data_base=date(2026, 11, 16), data_vistoria=date(2026, 11, 16)))
    assert routes._modelo_laudo(db.job(jid)) == {"modalidade": "PTAM não judicial", "de": "seu"}
    asyncio.run(RA.voltar_modelo("AM", _u=u))
    assert A.modelo_em_uso(av, "AM") == "sistema" and not fichas.obter(ok["regras"][0])["ativa"]
    assert routes._modelo_laudo(db.job(jid))["de"] == "sistema"
