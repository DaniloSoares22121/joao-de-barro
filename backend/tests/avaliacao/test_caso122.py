"""ORDEM 071-D: o caso 122 é a régua (teste de calibragem). Usa IA de verdade (custa) e só roda quando chamado:

    JDB_CASO122=1 pytest tests/avaliacao/test_caso122.py -m caso122 -s

Importa a conversa do WhatsApp (zip em backend/data/teste122, FORA do git), roda a entrada e os portões da
proposta e do contrato, confere campo a campo com o esperado_122.json e falha se aparecer algo de `nao_e`.
Inclui a rodada de correção da 071-A (valor 600 em todo lugar e o CPF da CNH). Sem o arquivo, é pulado.
Nenhum dado do cliente fica neste arquivo: tudo vem do gabarito e dos documentos lidos."""
import asyncio
import json
import os
import re
import shutil
from pathlib import Path

import pytest

PASTA = Path(__file__).resolve().parents[2] / "data" / "teste122"
ESPERADO = PASTA / "esperado_122.json"
ZIP = next(PASTA.glob("*.zip"), None) if PASTA.is_dir() else None

pytestmark = [
    pytest.mark.caso122,
    pytest.mark.skipif(not os.environ.get("JDB_CASO122"), reason="caso122 usa IA de verdade: rode com JDB_CASO122=1"),
    pytest.mark.skipif(not (ESPERADO.is_file() and ZIP), reason="sem o gabarito do caso 122 (backend/data/teste122)"),
]


def _so_letras(s: str) -> str:
    import unicodedata
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def test_caso122():
    from lovable.avaliacao import conversa as C, dados_cliente as DC, portoes, rascunho, rotas_conversa as R, rotas_whatsapp as W
    esp = json.loads(ESPERADO.read_text(encoding="utf-8"))
    falhas, relatorio = [], []

    def conf(nome, ok, visto):
        relatorio.append(f"{'OK  ' if ok else 'FALHA'} {nome}: {visto}")
        if not ok:
            falhas.append(nome)

    from lovable import config
    # o Windows não aceita caminho com mais de 260 letras: o rascunho tem nome longo ("Proposta 2026-001 - …")
    assert len(str(config.DATA_DIR)) <= 60, ("use uma pasta de dados curta, por ex. "
                                             "LOVABLE_DATA_DIR=C:/Users/DELL/AppData/Local/Temp/t122")
    cid = C.criar("")
    imp = "20261114-000000"
    destino = W._pasta_imp(cid, imp)
    destino.mkdir(parents=True)
    shutil.copy2(ZIP, destino / "conversa.zip")
    asyncio.run(W.processar(cid, imp))                       # leitura + áudios (local) + documentos + resumo (062)
    ctx = C.obter(cid)["contexto"]
    e = esp["entrada"]
    # ---- entrada
    conf("solicitante", DC.mesma_pessoa(ctx.get("solicitante_nome", ""), e["solicitante"])
         and len(ctx.get("solicitante_nome", "")) >= len(e["solicitante"]) - 2, ctx.get("solicitante_nome"))
    donos = " ".join([ctx.get("proprietario", "")] + [p["nome"] for p in ctx.get("pessoas") or [] if "propriet" in p["papel"] or "donat" in p["papel"]])
    conf("proprietários", all(DC.mesma_pessoa(n, x) for n in e["proprietarios"]
                              for x in [next((p["nome"] for p in ctx.get("pessoas") or [] if DC.mesma_pessoa(p["nome"], n)), "")]),
         donos)
    end = ctx.get("imovel_endereco", "")
    conf("endereço (Qd/Lt/CEP, sem nº 00)", all(k in _so_letras(end) for k in ("59", "02", "74480470")) and not re.search(r"n[º°o]\s*0+\b", end, re.I), end)
    mat = ctx.get("matricula", "")
    conf("matrícula atual", _so_letras(mat).startswith("134312"), mat)
    conf("modalidade sugerida AM", ctx.get("modalidade_sugerida") == "AM", ctx.get("modalidade_sugerida"))
    fin = (ctx.get("finalidade_sugerida") or "") + " " + (ctx.get("entendimento_rascunho") or "")
    conf("finalidade ITCD/malha", bool(re.search(r"\bITCD\b", fin)) and bool(re.search(r"malha", fin, re.I)), (ctx.get("finalidade_sugerida") or "")[:160])
    conf("visita (13/11) já feita", bool(ctx.get("visita_feita")) or "2026-11-13" in (ctx.get("visita") or ""), f"{ctx.get('visita')} feita={ctx.get('visita_feita')}")
    texto = (ctx.get("entendimento_rascunho") or "").lower()
    conf("nada de 'contestar o valor venal'", not re.search(r"contest\w*\s+o\s+valor\s+venal", texto), "")
    conf("nada de 'imposto pago de R$ 155 mil'", not re.search(r"imposto[^.]{0,40}pag\w*[^.]{0,40}155", texto), "")
    # ---- proposta: o entendimento confirmado e os portões
    asyncio.run(R.confirmar_entendimento(cid, _u={}))
    g = {q["id"]: q for q in portoes.montar(cid, "proposta")["perguntas"]}
    p = esp["proposta"]
    conf("proposta em nome de", bool(g["em_nome_de"]["sugestao"]) and DC.mesma_pessoa(g["em_nome_de"]["sugestao"]["valor"], p["em_nome_de"]),
         g["em_nome_de"]["sugestao"])
    conf("valor 600 com fonte", (g["valor"]["sugestao"] or {}).get("valor") == "600,00", f"{g['valor']['sugestao']} · {g['valor']['fonte']}")
    conf("pagamento 300 + 300", "300,00 + R$ 300,00" in g["pagamento"]["opcoes"][0]["rotulo"], g["pagamento"]["opcoes"][0]["rotulo"])
    conf("prazo", "3 dias úteis" in (g["prazo"]["sugestao"] or {}).get("rotulo", ""), (g["prazo"]["sugestao"] or {}).get("rotulo"))
    ex = portoes.contrato_existente(C.obter(cid)["contexto"])
    conf("contrato já existe (e sinal pago)", bool(ex) and ex.get("sinal_pago"), ex)
    # ---- a rodada de correção da 071-A
    asyncio.run(R.nova_mensagem(cid, R.Entrada(texto="O valor da proposta está errado: são R$ 600,00 (seiscentos reais) no total, "
                                                     "com R$ 300 de sinal e R$ 300 na entrega. E o CPF do Fulano na proposta não é "
                                                     "o dele: o certo está na CNH e no contrato.", tipo="texto"), _u={}))
    ctx = C.obter(cid)["contexto"]
    conf("depois da correção: valor 600 no próximo passo", C.sugerir_proposta(ctx)["valor"] == "600,00", C.sugerir_proposta(ctx)["valor"])
    for q in portoes.montar(cid, "proposta")["perguntas"]:
        if q["sugestao"] and not q["confirmado"]:
            portoes.confirmar(cid, "proposta", q["id"], q["sugestao"]["valor"], q["sugestao"]["rotulo"])
    meta = rascunho.gerar(cid, "proposta")
    conf("depois da correção: valor 600 no rascunho", meta["valor"] == "600,00", meta["valor"])
    eu = next((x for x in ctx.get("pessoas") or [] if DC.mesma_pessoa(x["nome"], e["solicitante"]) and x.get("doc")), None)
    oferta = [m for m in C.mensagens(cid) if m["tipo"] == "escolha" and m["dados"].get("pergunta") == "cpf"]
    conf("CPF: o JdB vai ao documento e oferece o da pessoa certa",
         bool(eu and oferta and oferta[-1]["dados"]["opcoes"][0]["valor"] == eu["doc"]),
         (oferta[-1]["texto"] if oferta else "sem oferta"))
    docx = next((C.pasta(cid) / "rascunho" / "proposta").glob("*.docx"), None)
    if docx:
        from docx import Document
        corpo = "\n".join(par.text for par in Document(docx).paragraphs) + "\n".join(
            c.text for t in Document(docx).tables for r in t.rows for c in r.cells)
        conf("rascunho sem colchete de campo vazio", not re.search(r"\[[A-ZÇÃÉÍ ]{3,}\]", corpo), "")
        conf("rascunho com ITCD (não ITCMD)", "ITCMD" not in corpo, "")
    print("\n".join(["", "=== caso122 ==="] + relatorio + [f"=== {len(relatorio) - len(falhas)} de {len(relatorio)} certos ==="]))
    assert not falhas, f"caso122: {len(falhas)} falha(s): {', '.join(falhas)}"
