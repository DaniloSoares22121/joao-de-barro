"""ORDEM 066: o solicitante é quem contrata; documento nunca vira solicitante sozinho; a leitura só preenche
o vazio; todo dado guardado pode ser corrigido. Caso fictício igual ao do Alan (sem IA)."""
import asyncio

from lovable.avaliacao import conversa as C
from lovable.avaliacao import dados_cliente as DC
from lovable.avaliacao import rotas_conversa as R

ESCRITURA = DC.DocLido(tipo_documento="Escritura de doação", matricula="100.200", matricula_origem="40.800",
                       imovel_endereco="Rua Fictícia 4, nº 00, Qd. 59, Lt. 02, Jardim Teste",
                       pessoas=[DC.Pessoa(nome="Beltrana Fictícia de Souza", papel="donatário", doc="111.222.333-44"),
                                DC.Pessoa(nome="Sicrano Fictício de Souza", papel="cônjuge"),
                                DC.Pessoa(nome="Estado de Goiás", papel="doador")])


def _cliente_da_conversa():
    cid = C.criar("Fulano")
    C.juntar_contexto(cid, {"solicitante_nome": "Fulano", "solicitante_telefone": "+55 62 90000-0000"})
    return cid


def test_documento_nao_vira_solicitante_e_pergunta_quem_contrata():
    cid = _cliente_da_conversa()
    texto, pergunta = DC.aplicar_documento(cid, ESCRITURA, "escritura.pdf")
    ctx = C.obter(cid)["contexto"]
    assert ctx["solicitante_nome"] == "Fulano" and "solicitante_doc" not in ctx           # nada da Beltrana no solicitante
    assert ctx["proprietario"] == "Beltrana Fictícia de Souza e Sicrano Fictício de Souza"
    assert ctx["matricula"] == "100.200" and ctx["matricula_origem"] == "40.800"           # a atual, não a de origem
    assert ctx["imovel_endereco"] == "Rua Fictícia 4, s/n, Qd. 59, Lt. 02, Jardim Teste"   # "nº 00" = s/n
    assert {p["papel"] for p in ctx["pessoas"]} == {"donatário", "cônjuge", "doador"}
    assert pergunta and pergunta["texto"] == "Quem está contratando o laudo?"
    ops = pergunta["dados"]["opcoes"]
    assert ops[0] == {"valor": "Fulano", "rotulo": "Fulano · quem conversa", "recomendada": True}   # 072-C1
    assert [o["valor"] for o in ops[1:3]] == ["Beltrana Fictícia de Souza", "Sicrano Fictício de Souza"]
    assert "Beltrana Fictícia de Souza (donatário)" in texto
    DC.aplicar_documento(cid, ESCRITURA, "escritura.pdf")                                     # mesma pergunta não repete
    assert len([m for m in C.mensagens(cid) if m["tipo"] == "escolha"]) == 1


def test_leitura_nao_sobrescreve_e_avisa_para_conferir():
    cid = _cliente_da_conversa()
    C.juntar_contexto(cid, {"imovel_endereco": "Rua Fictícia 4, Qd. 59, Lt. 02, Jardim Teste, Goiânia – GO"})
    outro = DC.DocLido(tipo_documento="Relatório FIPE", imovel_endereco="R FICTICIA 4 QD 59 LT 02 NÚMERO: 00")
    texto, _ = DC.aplicar_documento(cid, outro, "fipe.pdf")
    assert C.obter(cid)["contexto"]["imovel_endereco"] == "Rua Fictícia 4, Qd. 59, Lt. 02, Jardim Teste, Goiânia – GO"
    assert "Confira: endereço do imóvel" in texto


def test_escolher_e_corrigir():
    cid = _cliente_da_conversa()
    DC.aplicar_documento(cid, ESCRITURA, "escritura.pdf")
    st = asyncio.run(R.escolher(cid, R.Escolha(pergunta="solicitante", valor="Beltrana Fictícia de Souza"), _u={}))
    ctx = C.obter(cid)["contexto"]
    assert ctx["solicitante_nome"] == "Beltrana Fictícia de Souza" and ctx["solicitante_doc"] == "111.222.333-44"
    assert [m for m in st["mensagens"] if m["tipo"] == "escolha"][0]["dados"]["respondida"] == "Beltrana Fictícia de Souza"
    asyncio.run(R.escolher(cid, R.Escolha(pergunta="solicitante", valor="Fulano"), _u={}))
    assert "solicitante_doc" not in C.obter(cid)["contexto"]                                 # o CPF era da Beltrana
    st = asyncio.run(R.corrigir_dado(cid, R.Correcao(campo="imovel_endereco", valor="Rua Fictícia 4, nº 0, Jardim Teste"), _u={}))
    ctx = C.obter(cid)["contexto"]
    assert ctx["imovel_endereco"] == "Rua Fictícia 4, s/n, Jardim Teste" and "imovel_endereco" in ctx["_corrigidos"]
    assert st["mensagens"][-1]["texto"] == "Você corrigiu endereço do imóvel: Rua Fictícia 4, s/n, Jardim Teste."
    C.juntar_contexto(cid, {"proprietario": ""})
    DC.corrigir(cid, "proprietario", "Beltrana e Sicrano")
    DC.aplicar_documento(cid, DC.DocLido(pessoas=[DC.Pessoa(nome="Outro Nome", papel="proprietário")]), "x.pdf")
    assert C.obter(cid)["contexto"]["proprietario"] == "Beltrana e Sicrano"                     # corrigido não é sobrescrito


def test_rotulos_em_portugues():
    cid = _cliente_da_conversa()
    C.juntar_contexto(cid, {"modalidade": "AM", "proposta_status": "aguardando_revisao", "valor_combinado": "R$ 600,00",
                            "solicitante_doc": "123.456.789-00"})
    ls = {l["rotulo"]: l["valor"] for l in DC.linhas(C.obter(cid)["contexto"])}
    assert ls["Modalidade"] == "PTAM não judicial" and ls["Proposta"] == "esperando sua revisão"
    assert ls["Valor combinado"] == "R$ 600,00" and ls["CPF ou CNPJ do solicitante"] == "•••.•••.•••-00"
    assert not any("_" in k for k in ls)


def test_mesma_pessoa():
    assert DC.mesma_pessoa("Fulano", "FULANO ALVES DE SOUZA")
    assert not DC.mesma_pessoa("Fulano", "Beltrana Alves de Souza")
    assert DC.mesma_pessoa("Sicrano Barbosa de Souza", "SICRANO BARBOSA DE SOUZA")


def test_endereco_e_cidade_limpos_071():
    from lovable.avaliacao import dados_cliente as D
    e = D.limpar_endereco("RUA JC. 4, s/n, JARDIM CURITIBA I, Q 59 L 2, GOIANIA, CEP: 74000-000")
    assert "Qd. 59, Lt. 02" in e and "CEP 74000-000" in e and e.startswith("Rua JC") and "Goiânia" in e
    assert D.limpar_endereco("Av. Goiás, nº 00, Centro") == "Av. Goiás, s/n, Centro"
    for c in ("Goiânia – GO", "Goiânia-GO", "GOIÂNIA/GO", "Goiânia"):
        assert D.limpar_cidade(c) == "Goiânia"
    assert D.limpar_cidade("Aparecida de Goiânia") == "Aparecida de Goiânia"
    assert D.peso_endereco("Escritura de doação") > D.peso_endereco("Fatura de água (Saneago)")


def test_endereco_misturado_e_cep_da_conta_071():
    from lovable.avaliacao import dados_cliente as D
    e = D.limpar_endereco("RUA XV-9, s/n, Qd. 59, Lt. 02, Loteamento JARDIM CURITIBA, GOIÂNIA - GO")
    assert e == "Rua XV-9, s/n, Qd. 59, Lt. 02, Loteamento Jardim Curitiba, Goiânia - GO"
    assert D.com_cep(e, "Rua JC. 4, Qd. 59, Lt. 02, Goiânia, CEP 74000-000").endswith("CEP 74000-000")
    assert D.com_cep("Rua A, CEP 74000-000", "Rua B, CEP 74000-000") == "Rua A, CEP 74000-000"


def test_069_a12_nome_sem_qualificacao():
    from lovable.avaliacao import dados_cliente as D
    q = ("ISO PARTICIPAÇÕES E EMPREENDIMENTOS LTDA, pessoa jurídica de direito privado, inscrita no CNPJ sob o "
         "nº 00.000.000/0001-00, com sede na Rua Exemplo")
    assert D.nome_proprio(q) == "Iso Participações e Empreendimentos Ltda"
    assert D.nome_proprio("Maria Fictícia, brasileira, casada, portadora do RG 123") == "Maria Fictícia"
    assert D.nome_proprio("JOSÉ DA SILVA") == "José da Silva"


def test_072_c1_um_card_so_e_so_quem_pode_contratar(monkeypatch):
    from lovable.avaliacao import conversa as C, dados_cliente as D
    monkeypatch.setattr(D, "nome_avaliador", lambda: "Avaliador Fictício da Silva")
    assert D.mesma_pessoa("Sicrano Barboosa de Souza", "Sicrano Barbosa de Souza")
    assert not D.mesma_pessoa("Maria Silva", "Mario Silva")
    cid = C.criar("")
    C.juntar_contexto(cid, {"solicitante_nome": "Joana Fictícia"})
    escr = D.DocLido(tipo_documento="Escritura de doação", pessoas=[
        D.Pessoa(nome="PEDRO FICTÍCIO", papel="donatário"), D.Pessoa(nome="ROSA FICTÍCIA", papel="donatário"),
        D.Pessoa(nome="Estado de Goiás", papel="doador"), D.Pessoa(nome="Tabelião Fictício", papel="pessoa no documento"),
        D.Pessoa(nome="Agência Goiana de Habitação", papel="pessoa no documento"),
        D.Pessoa(nome="Avaliador Fictício da Silva", papel="pessoa no documento")])
    D.aplicar_documento(cid, escr, "escritura.pdf")
    D.aplicar_documento(cid, D.DocLido(tipo_documento="Conta de água", pessoas=[D.Pessoa(nome="PEDRO FICTICIIO", papel="titular do documento")]), "agua.pdf")
    cards = [m for m in C.mensagens(cid) if m["tipo"] == "escolha" and m["dados"].get("pergunta") == "solicitante"]
    assert len(cards) == 1                                         # um card só
    ops = [o["valor"] for o in cards[0]["dados"]["opcoes"]]
    assert ops == ["Joana Fictícia", "Pedro Fictício", "Rosa Fictícia"]    # sem avaliador, órgão, tabelião, doador
    # a CNH da Joana tira a dúvida: o card vira "✓ Joana…"
    D.aplicar_documento(cid, D.DocLido(tipo_documento="CNH", pessoas=[D.Pessoa(nome="JOANA FICTÍCIA DE SOUZA", papel="titular do documento", doc="000.000.000-00")]), "cnh.pdf")
    cards = [m for m in C.mensagens(cid) if m["tipo"] == "escolha" and m["dados"].get("pergunta") == "solicitante"]
    assert len(cards) == 1 and cards[0]["dados"]["respondida"].startswith("Joana Fictícia")


def test_077_c2_pergunta_respondida_nao_repete():
    from lovable.avaliacao import conversa as C, dados_cliente as D
    cid = C.criar("")
    C.juntar_contexto(cid, {"solicitante_nome": "Joana Fictícia"})
    esc = D.DocLido(tipo_documento="Escritura", pessoas=[D.Pessoa(nome="PEDRO FICTÍCIO", papel="donatário")])
    D.aplicar_documento(cid, esc, "e.pdf")
    card = next(m for m in C.mensagens(cid) if m["tipo"] == "escolha")
    C.marcar_dados(card["id"], {**card["dados"], "respondida": "Joana Fictícia"})
    for _ in range(3):
        D.pergunta_solicitante(cid)
        D.aplicar_documento(cid, esc, "e.pdf")
    assert len([m for m in C.mensagens(cid) if m["tipo"] == "escolha" and m["dados"].get("pergunta") == "solicitante"]) == 1
