"""ORDEM 072-C10: o relato da vistoria passa pela análise do João (portão da visita) antes do "Montar o laudo".
Os números são os da volta 3 (fictícios no nome; as medidas são as do relato). A IA é simulada: o teste não gasta."""
import asyncio

from lovable.avaliacao import analise_visita as AV
from lovable.avaliacao import conversa as C
from lovable.avaliacao import portoes

DOCS = [{"arquivo": "escritura.pdf", "tipo": "Escritura de doação", "terreno_m2": 286.10},
        {"arquivo": "iptu.pdf", "tipo": "Carnê de IPTU 2025", "terreno_m2": 300.0, "construida_m2": 106.24, "valor_venal": 155694.94}]
RELATO = AV.Relato(frente_m=11.76, fundo_m=11.70, lado_direito_m=24.70, lado_esquerdo_m=24.64,
                   casa_comprimento_m=12.96, casa_largura_m=7.95, quartos=2, suites=1, banheiros=2,
                   data_ditcd="2026-10-28", data_ciencia="2026-11-09", valor_referencia_malha=448335.57,
                   perguntas=["A edícula dos fundos tem documento?"])


def test_conferencias_como_o_joao():
    linhas = AV.conferir(RELATO, {"docs": DOCS})
    texto = "\n".join(linhas)
    assert "compatível com a escritura (286,10 m²), não com o IPTU (300,00 m²). Fica a da escritura." in texto
    assert "Casa pela trena (~103,03 m²): compatível com os 106,24 m² do IPTU." in texto
    assert "A medida de trena não entra em número no laudo" in texto
    assert "Data da DITCD: 28/10/2026 (fato do processo; o laudo vale na data da vistoria)." in texto   # 117 / D-127
    assert "Prazo da malha: ciência em 09/11 + 30 dias = 09/12/2026." in texto
    assert "Referência da malha: R$ 448.335,57. Declarado: R$ 155.694,94." in texto and "não serve para justificar" in texto
    assert "2 quartos (1 suíte) e 2 banheiros: confiro nas fotos." in texto


def test_sem_areas_lidas_nao_inventa():
    linhas = AV.conferir(RELATO, {"docs": []})
    assert any("Não tenho a área da escritura nem do IPTU lida" in x for x in linhas)


def test_analisar_deixa_na_conversa_e_vira_portao(monkeypatch):
    from lovable.avaliacao import ia

    async def falsa(sistema, prompt, esquema, **kw):
        assert "RELATO" in prompt and "2.4" in sistema or "Visita" in sistema
        return RELATO
    monkeypatch.setattr(ia, "perguntar", falsa)
    cid = C.criar("")
    C.juntar_contexto(cid, {"docs": DOCS, "visita_feita": True, "finalidade": "ITCD malha fiscal"})
    asyncio.run(AV.analisar(cid, "VISTORIA Nº 1 · Casa\nfrente 11,76…"))
    ctx = C.obter(cid)["contexto"]
    assert ctx["data_base"] == "2026-10-28" and ctx["prazo_malha"].startswith("09/12/2026")
    msg = C.mensagens(cid)[-1]["texto"]
    assert msg.startswith("O que conferi na vistoria:") and "Montar o laudo" in msg and "Seguir para o laudo" not in msg
    g = portoes.montar(cid, "visita")
    da_analise = [q for q in g["perguntas"] if q["id"].startswith("v")]
    assert [q["pergunta"] for q in da_analise] == ["A edícula dos fundos tem documento?"] and not g["completo"]
    assert {"fotos", "pin"} <= {q["id"] for q in g["perguntas"]}       # 074: fotos e pin (sem visita marcada, sem data-base)
    g = portoes.confirmar(cid, "visita", "v1", "Não tem, é só contexto")
    assert "v1" not in g["abertas"]


def test_085_relato_na_conversa_responde_o_portao(monkeypatch):
    """083-C2 / 085: o checklist escrito na conversa (9121) já respondia medidas, idade e DITCD; o portão não pergunta
    de novo (marca "entendi assim") e o estado/pontos negativos do avaliador vão para o contexto."""
    import asyncio
    from lovable.avaliacao import analise_visita as A, conversa as C, ia, portoes
    from lovable.avaliacao.rotas_conversa import _eh_checklist
    txt = ("Visita feita em 13/11/2026 às 12h30. Mandei as 31 fotos. Checklist: o endereço confere; lote regular, plano. "
           "Casa térrea, 2 quartos sendo 1 suíte, 2 banheiros, 2 salas, cozinha, garagem coberta para 2 vagas. Padrão simples. "
           "Estado: entre regular e reparos simples. Idade aparente 30 anos. Medi o terreno e as medidas batem com a escritura. "
           "Ponto negativo: casa de festas na mesma quadra 59. Data da DITCD 28/10/2026 (data-base).")
    assert _eh_checklist(txt)
    cid = C.criar("")
    C.juntar_contexto(cid, {"finalidade": "ITCD – malha fiscal", "visita": "2026-11-13T12:30"})

    async def fake(sistema, prompt, esquema, **k):
        return A.Relato(data_ditcd="2026-10-28", idade_aparente_anos=30, medidas_batem=True,
                        estado_conservacao="entre regular e reparos simples",
                        pontos_negativos=["casa de festas na mesma quadra 59"])
    monkeypatch.setattr(ia, "perguntar", fake)
    asyncio.run(A.analisar(cid, txt))
    ctx = C.obter(cid)["contexto"]
    assert ctx["estado_conservacao"] == "entre regular e reparos simples" and ctx["pontos_negativos"]
    assert C.trabalho_do_contexto(ctx, 1)["data_base"] == ctx["visita"][:10]       # 117 / D-127: a da vistoria
    g = portoes.montar(cid, "visita")
    for qid in ("medidas", "idade", "data_base"):
        assert qid not in g["abertas"], qid
    assert ctx.get("medidas_confere") is True and ctx.get("idade_aparente") == "30"
    assert any("Entendi assim" in m["texto"] for m in C.mensagens(cid))


def test_102_1_medidas_batem_nao_pergunta_a_trena():
    from lovable.avaliacao import conversa as C, portoes
    cid = C.criar("")
    C.juntar_contexto(cid, {"visita": "2026-11-13T12:30", "medidas_confere": True,
                            "visita_perguntas": ["Quais foram as medidas do terreno tiradas na trena (frente, fundo, lado direito e lado esquerdo)?",
                                                 "A garagem é coberta?"]})
    g = portoes.montar(cid, "visita")
    textos = [q["pergunta"] for q in g["perguntas"]]
    assert not any("trena" in t for t in textos) and any("garagem" in t for t in textos)
    v = next(q for q in g["perguntas"] if "garagem" in q["pergunta"])
    assert v["opcoes"] and v["opcoes"][0]["valor"] == "Não se aplica"
