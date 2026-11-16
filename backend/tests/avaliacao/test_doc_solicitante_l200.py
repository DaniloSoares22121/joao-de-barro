"""L200 (Caso W): o documento que o avaliador manda como "do solicitante" põe o titular entre as opções de
"Quem está contratando o laudo?" (antes só entravam quem conversa e os proprietários)."""
from lovable.avaliacao import conversa as C
from lovable.avaliacao import dados_cliente as DC


def _cli():
    cid = C.criar("TESTE Fulano", "AV-0001")
    C.juntar_contexto(cid, {"solicitante_nome": "TESTE Fulano", "pessoas": [{"nome": "Beltrano Dono Exemplo", "papel": "proprietário"},
                                        {"nome": "Ciclana Exemplo Souza", "papel": "titular do documento"}]})
    return cid


def test_titular_do_documento_do_solicitante_vira_opcao():
    cid = _cli()
    DC.pergunta_solicitante(cid)
    card = [m for m in C.mensagens(cid) if m["tipo"] == "escolha"][-1]
    assert [o["valor"] for o in card["dados"]["opcoes"]] == ["TESTE Fulano", "Beltrano Dono Exemplo"]   # antes: ela de fora
    DC.marcar_documento_do_solicitante(cid, ["Ciclana Exemplo Souza"])
    card = [m for m in C.mensagens(cid) if m["tipo"] == "escolha"][-1]
    assert "Ciclana Exemplo Souza" in [o["valor"] for o in card["dados"]["opcoes"]]                   # o card se atualiza


def test_titular_de_conta_de_agua_continua_fora():
    cid = _cli()
    assert "Ciclana Exemplo Souza" not in [c["nome"] for c in DC.candidatos_contratante(C.obter(cid)["contexto"])]


def test_pais_da_cnh_nao_viram_opcao():
    """L200 (Caso M): a CNH traz os pais (filiação); só o titular vira opção (a rota marca só o titular)."""
    import inspect
    from lovable.avaliacao import rotas_conversa
    assert 'p.papel == "titular do documento"' in inspect.getsource(rotas_conversa.anexar)


def test_endereco_incompleto_e_trocado_pelo_completo_do_iptu():
    """L200 (Caso M): a escritura guardou o endereço com "(unidade, logradouro e número não constam nesta página)";
    o IPTU traz rua e apartamento e passa a valer (antes só virava "confira")."""
    cid = C.criar("TESTE M", "AV-0001")
    C.juntar_contexto(cid, {"imovel_endereco": "Torre D - Edifício Exemplo, 12º Pavimento, Aparecida de Goiânia "
                                               "(unidade, logradouro e número não constam nesta página)",
                            "_fonte": {"imovel_endereco": "Escritura Pública (escritura.jpeg)"}})
    lido = DC.DocLido(tipo_documento="IPTU 2026", imovel_endereco="Rua 12, s/n, Qd. 58A, Ed. Exemplo, Bloco D, Apto 1203, "
                                                                  "Bairro Exemplo, Aparecida de Goiânia - GO")
    DC.aplicar_documento(cid, lido, "iptu.pdf")
    assert C.obter(cid)["contexto"]["imovel_endereco"].startswith("Rua 12")
