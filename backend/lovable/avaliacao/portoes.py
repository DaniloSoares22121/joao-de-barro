"""ORDEM 071: os "portões" — perguntas obrigatórias antes de cada etapa (00_COMO_O_JOAO_TRABALHA, seção 2).

As perguntas ficam numa TABELA DE DADOS (abaixo), não só no texto para a IA. Cada uma já vem com a resposta
sugerida e a FONTE ("do contrato que você mandou", "da CNH", "você disse"). O avaliador confirma com um
toque, troca por outra opção ou escreve. O que foi confirmado fica ✓ e não é perguntado de novo. O
servidor não deixa aprovar a proposta nem o contrato com pergunta aberta."""
from __future__ import annotations

import re

from . import conversa as C
from . import dados_cliente as DC

LIMITES = (100, 10_000)          # 071-A: fora disso o valor só sai com confirmação do avaliador
MOD = DC.MOD

# A tabela: etapa → perguntas (id, texto, de onde vem a sugestão, obrigatória)
PERGUNTAS: dict[str, list[dict]] = {
    "proposta": [
        {"id": "em_nome_de", "pergunta": "A proposta vai em nome de quem?", "de_onde": "a pessoa da conversa; os proprietários dos documentos"},
        {"id": "servico", "pergunta": "Qual serviço?", "de_onde": "a modalidade confirmada na entrada"},
        {"id": "valor", "pergunta": "Quanto vai cobrar?", "de_onde": "o valor combinado (conversa, áudio, proposta ou contrato que você mandou); sem ele, sua tabela como dica"},
        {"id": "pagamento", "pergunta": "Como vai ser o pagamento?", "de_onde": "o combinado; seu padrão é 50% na contratação e 50% na entrega, por Pix"},
        {"id": "prazo", "pergunta": "Prazo de entrega", "de_onde": "sua tabela"},
    ],
    "contrato": [
        {"id": "em_nome_de", "pergunta": "O contrato vai em nome de {nome}, o mesmo da proposta?", "de_onde": "a proposta"},
        {"id": "cpf", "pergunta": "CPF ou CNPJ do contratante", "de_onde": "o documento DELE (CNH, RG, contrato)"},
        {"id": "endereco", "pergunta": "Endereço do contratante", "de_onde": "o documento ou comprovante dele"},
        {"id": "telefone", "pergunta": "Telefone do contratante", "de_onde": "a conversa do WhatsApp"},
        {"id": "pagamento", "pergunta": "O pagamento é o mesmo da proposta?", "de_onde": "a proposta"},
        {"id": "objeto", "pergunta": "Proprietários e imóvel que vão no contrato", "de_onde": "escritura, matrícula e IPTU"},
    ],
    "visita": [],          # 072-C10: as perguntas vêm da análise do relato da vistoria (visita_perguntas)
}


def _fotos(cid: str | None, tipo: str) -> list:
    pasta = C.pasta(cid) / tipo if cid else None
    return sorted(f for f in pasta.iterdir() if f.is_file()) if pasta and pasta.is_dir() else []


def _perguntas(etapa: str, ctx: dict, cid: str | None = None) -> list[dict]:
    if etapa == "visita":
        qs = []
        # 074-A2 (P5 §C): sem foto da vistoria, o laudo não começa
        if cid and not _fotos(cid, "foto"):
            n = len(_fotos(cid, "foto_cliente"))
            qs.append({"id": "fotos", "pergunta": (f"Não tenho fotos da vistoria. As {n} fotos que você mandou são da vistoria?"
                                                   if n else "Não tenho fotos da vistoria. Mande as fotos pela conversa."),
                       "de_onde": "P5: fotos, com uma de fachada boa para a capa"})
        # 074-B: o pin, para o mapa demarcado, o link e o Mapa Digital Fácil
        if not C.pin_do_contexto(ctx, cid):
            qs.append({"id": "pin", "pergunta": "Cole o link do pin do Google Maps em frente ao imóvel",
                       "de_onde": "P5: localização"})
        # 117 / D-127: a data de referência do laudo é a da vistoria — não há mais pergunta de data-base (antes 074-C/085-1)
        # 078-7 e 078-8: perguntas do fechamento da vistoria
        if ctx.get("medidas_confere") is None:   # 110-4 (102-1): o relato já respondeu → não é pergunta
            qs.append({"id": "medidas", "pergunta": "Mediu o terreno? As medidas batem com a escritura?",
                       "de_onde": "a vistoria (D-055)"})
        qs.append({"id": "idade", "pergunta": "Idade aparente do imóvel e dos referenciais (anos)?", "de_onde": "as fotos (D-071)"})
        def _ainda_vale(q: str) -> bool:     # 102-1: medida de trena não é perguntada quando o relato diz que bate
            ql = q.lower()
            return not (ctx.get("medidas_confere") and any(k in ql for k in ("trena", "medida", "frente", "fundo")))
        return qs + [{"id": f"v{i}", "pergunta": q, "de_onde": "a análise do relato da vistoria"}
                     for i, q in enumerate(ctx.get("visita_perguntas") or [], 1) if _ainda_vale(q)]
    return PERGUNTAS[etapa]


def valor_fora_do_normal(v) -> bool:
    from .rotas_propostas import valor_decimal
    d = valor_decimal(v)
    return d is None or not (LIMITES[0] <= float(d) <= LIMITES[1])


def _conf(ctx: dict, etapa: str) -> dict:
    return ((ctx.get("portoes") or {}).get(etapa) or {})


def _fonte(ctx: dict, campo: str, padrao: str = "") -> str:
    return ((ctx.get("_fonte") or {}).get(campo) or padrao)


def _brl(v) -> str:
    return C.valor_br(v)


def _opcoes_pagamento(valor: str) -> list[dict]:
    from .rotas_propostas import valor_decimal
    d = valor_decimal(valor)
    if d is None:
        return [{"valor": "50/50 Pix", "rotulo": "50% na contratação e 50% na entrega, Pix"},
                {"valor": "à vista Pix", "rotulo": "À vista, Pix"}]
    metade = _brl(round(float(d) / 2, 2))
    return [{"valor": "50/50 Pix", "rotulo": f"50% agora e 50% na entrega, Pix · R$ {metade} + R$ {metade}"},
            {"valor": "à vista Pix", "rotulo": f"À vista, Pix · R$ {_brl(d)}"}]


def contrato_existente(ctx: dict) -> dict | None:
    """Contrato de serviço que o avaliador já mandou, com o contratante = solicitante (071-B5)."""
    sol = ctx.get("solicitante_nome") or ""
    for d in reversed(ctx.get("docs") or []):
        if "contrato" not in (d.get("tipo") or "").lower():
            continue
        quem = [p["nome"] for p in d.get("pessoas") or [] if p.get("papel") == "contratante"]
        if not sol or any(DC.mesma_pessoa(q, sol) for q in quem) or not quem:
            return {"arquivo": d["arquivo"], "data": d.get("data", ""), "valor": d.get("valor", ""),
                    "pagamento": d.get("pagamento", ""), "sinal_pago": bool(ctx.get("sinal_pago"))}
    return None


def montar(cid: str, etapa: str) -> dict:
    """As perguntas da etapa com a sugestão, a fonte, as opções e o que já foi confirmado."""
    from . import propostas
    cli = C.obter(cid) or {}
    ctx = cli.get("contexto") or {}
    conf = _conf(ctx, etapa)
    pessoas = ctx.get("pessoas") or []
    sol = ctx.get("solicitante_nome") or ""
    out = []
    existente = contrato_existente(ctx) if etapa == "contrato" else None
    for q in _perguntas(etapa, ctx, cid):
        item = {"id": q["id"], "pergunta": q["pergunta"], "opcoes": [], "livre": True, "sugestao": None, "fonte": "",
                "aviso": "", "dica": "", "confirmado": conf.get(q["id"])}
        if etapa == "proposta" and q["id"] == "em_nome_de":
            if sol:
                item["opcoes"].append({"valor": sol, "rotulo": f"{sol} · quem conversa"})
            for p in DC.candidatos_contratante(ctx):   # 072-C1: só quem pode contratar, sem nomes repetidos
                if not DC.mesma_pessoa(p["nome"], sol):
                    item["opcoes"].append({"valor": p["nome"], "rotulo": f"{p['nome']} · {p['papel']}"})
            item["sugestao"] = item["opcoes"][0] if item["opcoes"] else None
            item["fonte"] = _fonte(ctx, "solicitante_nome", "da conversa")
        elif q["id"] == "servico":
            item["opcoes"] = [{"valor": k, "rotulo": r} for k, r in MOD.items()]
            item["livre"] = False
            m = ctx.get("modalidade")
            item["sugestao"] = {"valor": m, "rotulo": MOD.get(m, m)} if m else None
            item["fonte"] = "você confirmou na entrada" if ctx.get("entendimento_status") == "confirmado" else ""
        elif q["id"] == "valor":
            v = _brl(ctx.get("valor_combinado"))
            item["sugestao"] = {"valor": v, "rotulo": f"R$ {v}"} if v else None
            item["fonte"] = _fonte(ctx, "valor_combinado", "você disse") if v else ""
            mod = ctx.get("modalidade") or "OV"
            tab = propostas.preco_padrao(mod, ctx.get("imovel_tipo") or "")
            item["dica"] = f"Sua tabela: {MOD.get(mod, mod).lower()} a partir de R$ {_brl(tab)}." if tab else ""
            if v and valor_fora_do_normal(v):
                item["aviso"] = f"R$ {v} está fora do normal (de R$ 100 a R$ 10.000). Confira antes."
        elif etapa == "proposta" and q["id"] == "pagamento":
            item["opcoes"] = _opcoes_pagamento(ctx.get("valor_combinado") or "")
            dito = ctx.get("pagamento") or ""
            item["sugestao"] = item["opcoes"][0]
            item["fonte"] = _fonte(ctx, "pagamento", "seu padrão") if dito else "seu padrão"
            if dito:
                item["dica"] = f"Combinado: {dito}."
        elif q["id"] == "prazo":
            p = propostas.prazo_entrega(ctx.get("modalidade") or "OV")
            item["opcoes"] = [{"valor": p, "rotulo": p[:1].upper() + p[1:]}]
            item["sugestao"] = item["opcoes"][0]
            item["fonte"] = "sua tabela"
        elif etapa == "contrato" and q["id"] == "em_nome_de":
            nome = (_conf(ctx, "proposta").get("em_nome_de") or {}).get("valor") or sol
            item["pergunta"] = q["pergunta"].format(nome=nome or "quem contrata")
            item["opcoes"] = [{"valor": nome, "rotulo": "Sim"}] if nome else []
            item["sugestao"] = item["opcoes"][0] if nome else None
            item["fonte"] = "a proposta"
        elif q["id"] == "cpf":
            eu = next((p for p in pessoas if sol and DC.mesma_pessoa(p["nome"], sol) and p.get("doc")), None)
            doc = eu["doc"] if eu else (ctx.get("solicitante_doc") if DC.mesma_pessoa(ctx.get("_doc_de") or "", sol) else "")
            if doc:
                item["sugestao"] = {"valor": doc, "rotulo": C.mascarar(doc)}
                item["fonte"] = (eu or {}).get("fonte_doc") or _fonte(ctx, "solicitante_doc", "documento dele")
        elif q["id"] == "endereco":
            # 071-B3: só o endereço que é DELE (da pessoa do solicitante num documento, ou que você corrigiu);
            # endereço guardado sem saber de quem é não vira sugestão: o portão pergunta
            eu = next((p for p in pessoas if sol and DC.mesma_pessoa(p["nome"], sol) and p.get("endereco")), None)
            fonte = str((ctx.get("_fonte") or {}).get("solicitante_endereco") or "")
            dele = DC.mesma_pessoa(ctx.get("_doc_de") or "", sol) or fonte.startswith("você")
            e = DC.limpar_endereco(eu["endereco"]) if eu else (ctx.get("solicitante_endereco") if dele else "")
            if e:
                item["sugestao"] = {"valor": e, "rotulo": e}
                item["fonte"] = (eu or {}).get("fonte_doc") or (eu or {}).get("fonte") or _fonte(ctx, "solicitante_endereco", "documento dele")
        elif q["id"] == "telefone":
            tel = ctx.get("solicitante_telefone")
            if tel:
                item["sugestao"] = {"valor": tel, "rotulo": tel}
                item["fonte"] = _fonte(ctx, "solicitante_telefone", "a conversa do WhatsApp")
        elif etapa == "contrato" and q["id"] == "pagamento":
            pg = (_conf(ctx, "proposta").get("pagamento") or {}).get("rotulo") or "50% na assinatura e 50% na entrega, Pix"
            item["pergunta"] = f"O pagamento é o mesmo da proposta ({pg})?"
            item["opcoes"] = [{"valor": pg, "rotulo": "Sim"}]
            item["sugestao"] = item["opcoes"][0]
            item["fonte"] = "a proposta"
        elif q["id"] == "objeto":
            donos = " e ".join(DC.nome_completo(DC.nome_proprio(n), pessoas) for n in re.split(r"\s+e\s+", ctx.get("proprietario") or "") if n)
            partes = [f"Proprietários: {donos or '—'}",
                      f"Imóvel: {ctx.get('imovel_endereco') or '—'}"]
            if ctx.get("matricula"):
                partes.append(f"Matrícula nº {ctx['matricula']}" + (f" – {ctx['cartorio']}" if ctx.get("cartorio") else ""))
            rot = " · ".join(partes)
            item["opcoes"] = [{"valor": "ok", "rotulo": "Está certo"}]
            item["sugestao"] = {"valor": "ok", "rotulo": rot}
            item["livre"] = False
            item["fonte"] = "escritura, matrícula e IPTU (Dados do cliente para corrigir)"
        if etapa == "visita" and q["id"] == "fotos":
            n = len(_fotos(cid, "foto_cliente"))
            item["opcoes"] = ([{"valor": "sim", "rotulo": "Sim, são da vistoria"}] if n else []) + [{"valor": "depois", "rotulo": "Vou mandar"}]
            item["livre"] = False
            item["sugestao"] = item["opcoes"][0] if n else None
            if conf.get("fotos", {}).get("valor") == "depois" or not _fotos(cid, "foto"):
                item["confirmado"] = None                     # só fecha com as fotos na pasta da vistoria
        elif etapa == "visita" and q["id"].startswith("v"):    # 102-1: pergunta da análise tem saída sem escrever
            item["opcoes"] = [{"valor": "Não se aplica", "rotulo": "Não se aplica / prefiro não informar"}]
            item["livre"] = True
        elif etapa == "visita" and q["id"] == "medidas":
            item["opcoes"] = [{"valor": "sim", "rotulo": "Sim, batem com a escritura"}, {"valor": "nao", "rotulo": "Não medi ou não batem"}]
            item["livre"] = False
        elif etapa == "visita" and q["id"] == "data_base" and not ctx.get("data_base"):
            item["livre"] = True                             # 085-1: sem DITCD conhecida, o avaliador digita
            item["sugestao"] = None
            item["fonte"] = "a regra do ITCD de Goiás"
        elif etapa == "visita" and q["id"] == "data_base":
            from datetime import date as _d
            f = lambda s: _d.fromisoformat(s[:10]).strftime("%d/%m/%Y")
            item["opcoes"] = [{"valor": ctx["data_base"][:10], "rotulo": f"DITCD {f(ctx['data_base'])} (recomendado para o ITCD)"},
                              {"valor": ctx["visita"][:10], "rotulo": f"Vistoria {f(ctx['visita'])}"}]
            item["livre"] = False
            item["sugestao"] = item["opcoes"][0]
            item["fonte"] = "a regra do ITCD de Goiás"
        out.append(item)
    abertas = [x["id"] for x in out if not x["confirmado"]]
    return {"etapa": etapa, "perguntas": out, "completo": not abertas, "abertas": abertas,
            "existente": existente, "usou_existente": bool(ctx.get("contrato_status") == "existente")}


def confirmar(cid: str, etapa: str, qid: str, valor: str, rotulo: str = "") -> dict:
    """Grava a resposta e leva o valor para os dados do cliente (o rascunho 065 se refaz sozinho)."""
    ctx = (C.obter(cid) or {}).get("contexto") or {}
    if etapa not in PERGUNTAS or qid not in {q["id"] for q in _perguntas(etapa, ctx, cid)}:
        raise ValueError("pergunta")
    v = (valor or "").strip()
    if not v:
        raise ValueError("vazio")
    portoes = dict(ctx.get("portoes") or {})
    resp = {"valor": v, "rotulo": rotulo or v}
    if qid == "valor":
        v = C.valor_br(v)
        if not v:
            raise ValueError("valor")
        resp = {"valor": v, "rotulo": f"R$ {v}"}
    portoes[etapa] = {**(portoes.get(etapa) or {}), qid: resp}
    DC._gravar(cid, {"portoes": portoes})
    # o que vale para o documento
    if etapa == "proposta" and qid == "em_nome_de":
        DC.escolher_solicitante(cid, v)
    elif qid == "servico":
        DC.corrigir(cid, "modalidade", v)
    elif qid == "valor":
        DC.corrigir(cid, "valor_combinado", v)
    elif etapa == "proposta" and qid == "pagamento":
        DC._gravar(cid, {"pagamento_texto": resp["rotulo"], "pagamento_forma": v})
    elif qid == "prazo":
        DC._gravar(cid, {"prazo_texto": v})
    elif qid == "cpf":
        DC._gravar(cid, {"solicitante_doc": v, "_doc_de": ctx.get("solicitante_nome") or ""})
    elif qid == "endereco":
        DC.corrigir(cid, "solicitante_endereco", v)
    elif qid == "telefone":
        DC.corrigir(cid, "solicitante_telefone", v)
    elif etapa == "visita" and qid == "fotos" and v == "sim":   # 074-A2: as fotos que ele mandou são da vistoria
        from .rotas_whatsapp import _mover
        for f in _fotos(cid, "foto_cliente"):
            _mover(cid, f"foto_cliente/{f.name}", "foto")
        C.mensagem(cid, "sistema", "texto", f"Combinado: {len(_fotos(cid, 'foto'))} fotos agora são da vistoria.")
    elif etapa == "visita" and qid == "pin":
        if not C._PIN.search(v):
            raise ValueError("pin")
        DC._gravar(cid, {"pin_maps": C._PIN.search(v).group(0)})
    elif etapa == "visita" and qid == "medidas":
        DC._gravar(cid, {"medidas_confere": v.lower().startswith("sim")})
    elif etapa == "visita" and qid == "idade":
        DC._gravar(cid, {"idade_aparente": re.sub(r"\D", "", v)[:3] or v[:20]})
    elif etapa == "visita" and qid == "data_base":
        m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", v)
        iso = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else v.strip()[:10]
        if not re.match(r"\d{4}-\d{2}-\d{2}$", iso):
            raise ValueError("data_base")
        DC._gravar(cid, {"data_base_escolhida": iso})
    return montar(cid, etapa)


def usar_contrato_existente(cid: str) -> None:
    ctx = (C.obter(cid) or {}).get("contexto") or {}
    ex = contrato_existente(ctx)
    if not ex:
        raise ValueError("sem contrato")
    DC._gravar(cid, {"contrato_status": "existente", "contrato_arquivo": ex["arquivo"]})
