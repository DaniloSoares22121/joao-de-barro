"""ORDEM 065 / 065-A: a proposta de verdade antes de aprovar, valor sem "R$ R$", e clique que não deixa
proposta vazia ocupando número."""
import asyncio
import json

import pytest
from fastapi import HTTPException

from lovable.avaliacao import conversa as C
from lovable.avaliacao import db, rascunho, rotas_conversa as R, rotas_propostas as P


def _cliente(valor="R$ 600,00"):
    cid = C.criar("Cliente Fictício")
    C.juntar_contexto(cid, {"solicitante_nome": "Cliente Fictício da Silva", "imovel_tipo": "Casa", "modalidade": "AM",
                            "finalidade": "Contestação do ITCMD", "cidade": "Goiânia", "bairro": "Setor Teste",
                            "valor_combinado": valor, "entendimento_status": "confirmado",
                            "proposta_status": "aguardando_revisao"})
    return cid


def _confirmar_portao(cid):
    """ORDEM 071: aprovar só com as perguntas da proposta confirmadas (aceita as sugestões)."""
    from lovable.avaliacao import portoes
    for q in portoes.montar(cid, "proposta")["perguntas"]:
        s = q["sugestao"]
        portoes.confirmar(cid, "proposta", q["id"], s["valor"], s["rotulo"])
    assert portoes.montar(cid, "proposta")["completo"]


def _n_propostas():
    P._init()
    with db._conn() as c:
        return c.execute("SELECT COUNT(*) FROM av_propostas").fetchone()[0]


@pytest.mark.parametrize("ent,dec,br", [("R$ 600,00", "600.00", "600,00"), ("600", "600", "600,00"), ("600.00", "600.00", "600,00"),
                                        ("1.200,50", "1200.50", "1.200,50"), ("R$600", "600", "600,00"), ("", None, "")])
def test_valor_limpo(ent, dec, br):
    v = P.valor_decimal(ent)
    assert (str(v) if v is not None else None) == dec and C.valor_br(ent) == br


def test_contexto_guarda_valor_sem_simbolo():
    cid = _cliente()
    assert C.obter(cid)["contexto"]["valor_combinado"] == "600,00"
    assert C.sugerir_proposta(C.obter(cid)["contexto"])["valor"] == "600,00"      # a tela põe "R$ " uma vez só


def test_rascunho_e_o_documento_real_sem_aprovar():
    cid = _cliente()
    antes = _n_propostas()
    meta = rascunho.gerar(cid, "proposta")
    pasta = C.pasta(cid) / "rascunho" / "proposta"
    assert meta["docx"] and (pasta / meta["docx"]).is_file()
    assert meta["numero"].endswith(f"-{P.proximo_numero(int(meta['numero'][:4])):03d}")   # o próximo número, sem reservar
    assert meta["valor"] == "600,00"
    assert _n_propostas() == antes                                                           # nada no banco de propostas
    ctx = C.obter(cid)["contexto"]
    assert ctx["proposta_status"] == "aguardando_revisao" and not C.obter(cid)["proposta_id"]
    assert rascunho.gerar(cid, "proposta")["marca"] == meta["marca"]                          # sem mudança: reaproveita
    C.juntar_contexto(cid, {"valor_combinado": "700"})
    assert rascunho.gerar(cid, "proposta")["valor"] == "700,00"                               # mudou o dado: refaz


def test_aprovar_com_valor_em_reais_funciona_e_nao_duplica(monkeypatch):
    cid = _cliente()
    antes = _n_propostas()
    with pytest.raises(HTTPException):                                                        # 071: pergunta aberta trava
        asyncio.run(R.aprovar_proposta(cid, _u={}))
    _confirmar_portao(cid)
    st = asyncio.run(R.aprovar_proposta(cid, _u={}))
    assert _n_propostas() == antes + 1
    pid = C.obter(cid)["proposta_id"]
    assert json.loads(json.dumps(P._ler(pid)["dados"]))["valor"] == "600.00"
    assert any(m["dados"].get("mensagem_pronta") for m in st["mensagens"])
    with pytest.raises(HTTPException):                                                        # não aprova duas vezes
        asyncio.run(R.aprovar_proposta(cid, _u={}))


def test_falha_ao_gerar_nao_deixa_proposta_vazia(monkeypatch):
    cid = _cliente()
    antes = _n_propostas()

    _confirmar_portao(cid)

    def quebra(*a, **k):
        raise RuntimeError("gerador fora do ar")
    monkeypatch.setattr(P, "_gerar", quebra)
    with pytest.raises(RuntimeError):
        asyncio.run(R.aprovar_proposta(cid, _u={}))
    assert _n_propostas() == antes and not C.obter(cid)["proposta_id"]


@pytest.mark.parametrize("frase,total", [
    ("Honorários de R$ 600, com sinal de R$ 300 já pago", "600"),          # ORDEM 071-A, a frase exata
    ("600 reais, 300 de entrada", "600"),
    ("R$ 1.500,00 em duas vezes de R$ 750", "1500.00"),
    ("600,00 (R$ 300,00 de sinal + R$ 300,00 na entrega)", "600.00"),       # como ficou gravado no cliente de teste
    ("R$ 1.200", "1200"),
    ("450.00", "450.00"),
])
def test_cada_valor_e_lido_sozinho(frase, total):
    assert str(P.valor_decimal(frase)) == total


def test_trava_de_valor_fora_do_normal():
    from lovable.avaliacao import portoes
    assert portoes.valor_fora_do_normal("600") is False
    assert portoes.valor_fora_do_normal("600.300") is True and portoes.valor_fora_do_normal("50") is True


def test_portao_da_proposta_sugere_com_fonte_e_trava():
    from lovable.avaliacao import dados_cliente as DC, portoes
    cid = _cliente(valor="")
    C.juntar_contexto(cid, {"solicitante_nome": "Fulano"})
    DC.aplicar_documento(cid, DC.DocLido(tipo_documento="Contrato de prestação de serviços", valor_honorarios="600,00",
                                         pagamento="R$ 300 na assinatura + R$ 300 na entrega, Pix",
                                         pessoas=[DC.Pessoa(nome="FULANO ALVES DE SOUZA", papel="contratante", doc="111.222.333-44"),
                                                  DC.Pessoa(nome="BELTRANA ALVES DE SOUZA", papel="proprietário")]),
                         "DOC-contrato.pdf")
    g = {q["id"]: q for q in portoes.montar(cid, "proposta")["perguntas"]}
    assert g["em_nome_de"]["sugestao"]["valor"] == "Fulano Alves de Souza"            # o nome completo, sem maiúsculas
    assert [o["valor"] for o in g["em_nome_de"]["opcoes"]][1] == "Beltrana Alves de Souza"
    assert g["valor"]["sugestao"]["valor"] == "600,00" and "contrato" in g["valor"]["fonte"]
    assert g["pagamento"]["opcoes"][0]["rotulo"] == "50% agora e 50% na entrega, Pix · R$ 300,00 + R$ 300,00"
    assert portoes.contrato_existente(C.obter(cid)["contexto"])["arquivo"] == "DOC-contrato.pdf"
    portoes.confirmar(cid, "proposta", "valor", "R$ 600.300,00")                          # o erro da 071-A
    assert portoes.montar(cid, "proposta")["perguntas"][2]["aviso"].startswith("R$ 600.300,00 está fora do normal")
