"""ORDEM 024 item 6 / D-051 / D-053: proposta e contrato no sistema (nomes fictícios)."""
import asyncio
import zipfile

from lovable.avaliacao import db, propostas, rotas_propostas


def _texto(docx) -> str:
    with zipfile.ZipFile(docx) as z:
        return "".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.startswith("word/"))


def _nova(modalidade="OV", tipo="Casa", valor=None):
    return asyncio.run(rotas_propostas.nova_proposta(rotas_propostas.NovaProposta(
        modalidade=modalidade, solicitante_nome="Maria Souza Lima", finalidade="Venda",
        imovel=rotas_propostas.Imovel(descricao=f"{tipo} residencial", endereco="Rua Fictícia, 100",
                                      tipo=tipo, bairro="Setor Exemplo", cidade="Goiânia"),
        valor=valor), _u={}))


def test_precos_e_prazos_d051():
    assert str(propostas.preco_padrao("OV", "Casa")) == "450"
    assert str(propostas.preco_padrao("AM", "Galpão comercial")) == "1000"
    assert str(propostas.preco_padrao("AMJ", "Casa")) == "1500"
    assert propostas.prazo_entrega("OV") == "em até 3 dias úteis após a visita técnica"
    assert propostas.prazo_entrega("AMJ") == "de 7 a 15 dias úteis após a visita técnica"


def test_proposta_numeracao_propria_e_textos(monkeypatch, tmp_path):
    monkeypatch.setattr(rotas_propostas, "_pasta", lambda pid: tmp_path / pid)
    p1 = _nova(valor="450")                # 071: o valor vem do combinado; sem ele, a proposta não sai
    p2 = _nova("AMJ", "Galpão", valor="1500")
    assert (p2["ano"], p2["numero"]) == (p1["ano"], p1["numero"] + 1)
    assert p1["dados"]["valor"] == "450" and p2["dados"]["valor"] == "1500"
    docx = next(tmp_path.glob(f"{p1['id']}/*.docx"))
    t = _texto(docx)
    assert "serviço não judicial" in t and "PTAM extrajudicial" not in t
    assert "em até 3 dias úteis após a visita técnica" in t and "30 dias" in t and "90 dias" not in t
    assert "Válida por 10 dias" in t


def test_contrato_sem_dados_pessoais_no_codigo(monkeypatch, tmp_path):
    monkeypatch.setattr(rotas_propostas, "_pasta", lambda pid: tmp_path / pid)
    for k in ("CPF", "ENDERECO", "EMAIL", "PIX"):
        monkeypatch.delenv(f"JDB_CONTRATADO_{k}", raising=False)
    db.set_setting("contratado", "{}")
    p = _nova("AM", "Casa", valor="600")
    c = asyncio.run(rotas_propostas.gerar_contrato(p["id"], rotas_propostas.NovoContrato(
        contratante=rotas_propostas.Contratante(nome="Maria Souza Lima", doc_tipo="CPF", doc="000.000.000-00")), _u={}))
    t = _texto(next(tmp_path.glob(f"{p['id']}/Contrato*.docx")))
    assert "[CPF DO CONTRATADO]" not in t and "[CHAVE PIX]" not in t     # 071-A2: nunca sai colchete; sem dado, a frase sai sem ele
    assert "Upgrade para serviço judicial" in t and "Conversão em PTAM" not in t
    monkeypatch.setenv("JDB_CONTRATADO_PIX", "chave-de-teste")
    asyncio.run(rotas_propostas.gerar_contrato(p["id"], rotas_propostas.NovoContrato(
        contratante=rotas_propostas.Contratante(nome="Maria Souza Lima")), _u={}))
    assert "chave-de-teste" in _texto(next(tmp_path.glob(f"{p['id']}/Contrato*.docx")))
    pre = asyncio.run(rotas_propostas.abrir_trabalho(p["id"], _u={}))
    assert pre["cliente"] == "Maria Souza Lima" and pre["modalidade"] == "AM" and pre["bairro"] == "Setor Exemplo"
    assert c["status"] == "contrato"


def test_071_sem_valor_combinado_nao_sai_o_piso(monkeypatch, tmp_path):
    import pytest
    from fastapi import HTTPException
    monkeypatch.setattr(rotas_propostas, "_pasta", lambda pid: tmp_path / pid)
    with pytest.raises(HTTPException) as e:
        _nova()
    assert e.value.status_code == 409 and "quanto vai cobrar" in e.value.detail
