"""ORDEM 041 (D-089 a D-093): rotas da conversa por cliente, do push (D-092) e do agendador de
avisos. Só local: nada é enviado ao cliente; o sistema deixa a mensagem pronta para o avaliador."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from datetime import date, datetime, timezone

from fastapi import Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import conversa as C
from . import dados_cliente as DC
from . import entendimento as E
from . import db, webpush
from .routes import _dono, router

log = logging.getLogger("lovable")


def _cli(cid: str) -> dict:
    """Cliente do avaliador logado (ORDEM 042: o de outro avaliador é 404)."""
    from .routes import av_atual
    cli = C.obter(cid)
    if cli is None or cli["avaliador_id"] != av_atual():
        raise HTTPException(status_code=404, detail="cliente não encontrado")
    return cli


def _estado(cid: str) -> dict:
    from .routes import av_atual
    cli = C.obter(cid)
    if cli is None or cli["avaliador_id"] != av_atual():
        raise HTTPException(status_code=404, detail="cliente não encontrado")
    ctx = cli["contexto"]
    seguro = {k: (C.mascarar(v) if k == "solicitante_doc" else v) for k, v in ctx.items()}
    if seguro.get("prazo") and C.eh_prazo_malha(str(seguro["prazo"])):     # 072-C3: clientes antigos
        seguro.setdefault("prazo_malha", seguro["prazo"])
        seguro["prazo"] = ""
    if seguro.get("imovel_tipo"):
        seguro["imovel_tipo"] = DC.tipo_limpo(seguro["imovel_tipo"])     # 072-C2: "casa (IPTU predial)" → "Casa"
    with db._conn() as c:
        comp = c.execute("SELECT quando, aviso_min, avisado FROM av_compromissos WHERE cliente=? ORDER BY id DESC LIMIT 1",
                         (cid,)).fetchone()
    prop = None
    if cli["proposta_id"]:
        from .rotas_propostas import _ler
        try:
            p = _ler(cli["proposta_id"])
            prop = {"id": p["id"], "numero": f"{p['ano']}-{p['numero']:03d}", "status": p["status"],
                    "arquivos": p["arquivos"]}
        except HTTPException:
            prop = None
    imp = _importacao(cid)
    lendo = bool(imp and imp.get("estado") == "trabalhando")       # 081-1: leitura parada/rodando não vira pergunta
    return {"id": cid, "nome": cli["nome"] or ctx.get("solicitante_nome") or "Cliente novo",
            "contexto": seguro, "etapas": C.etapas(cli), "etapa_atual": C.etapa_atual(cli),
            "pendencias": [] if lendo else C.pendencias(cli), "mensagens": C.mensagens(cid), "job_id": cli["job_id"],
            "proposta": prop, "visita": ({"quando": comp[0], "legivel": C.quando_legivel(comp[0]),
                                          "aviso_min": comp[1], "avisado": bool(comp[2])} if comp else None),
            "sugestao": C.sugerir_proposta(ctx) if ctx.get("proposta_status") == "aguardando_revisao" else None,
            # ORDEM 061: andamento da importação do WhatsApp ("Transcrevendo 12 áudios…")
            "importacao": imp,
            "contrato_existente": _contrato_antes(ctx)}


def _contrato_antes(ctx: dict) -> dict | None:
    """072-C5: contrato do avaliador já assinado na conversa, com a proposta ainda não aprovada nem pulada."""
    if ctx.get("proposta_status") in ("aprovada", "fora") or ctx.get("proposta_mesmo_assim"):
        return None
    from . import portoes
    ex = portoes.contrato_existente(ctx)
    if not ex:
        return None
    return {**ex, "data_legivel": (ex["data"][8:10] + "/" + ex["data"][5:7]) if len(ex.get("data") or "") >= 10 else ""}


def _importacao(cid: str) -> dict | None:
    from . import rotas_whatsapp
    try:
        return rotas_whatsapp.status(cid)
    except Exception:                                # o andamento é ajuda: nunca derruba a tela (nada de 500)
        return None


@router.get("/clientes")
async def listar_clientes(_u: dict = Depends(_dono)):
    out = []
    from .routes import av_atual
    for cli in C.listar(av_atual()):
        if db.setting("lixeira_cliente:" + cli["id"]):   # 109-2: cliente na Lixeira some da lista (nada apagado)
            continue
        pend = C.pendencias(cli)
        ctx = cli["contexto"]
        imp = _importacao(cli["id"])
        if imp and imp.get("estado") == "trabalhando":
            prox = "O JdB está lendo a conversa"          # 081-1: enquanto lê, nada de pergunta ao avaliador
        elif pend:
            prox = pend[0]["texto"]
        elif ctx.get("visita_feita") and not (cli.get("job_id") and C.job_existe(cli["job_id"])):
            prox = "Montar o laudo"                  # 072-B: visita feita, sem trabalho → o próximo passo é o laudo
        else:
            prox = "Nada pendente"
        tipo = DC.tipo_limpo(ctx.get("imovel_tipo") or "")
        out.append({"id": cli["id"], "nome": cli["nome"] or ctx.get("solicitante_nome") or "Cliente novo",
                    "imovel": " · ".join(x for x in (tipo, ctx.get("bairro")) if x),
                    "etapa": C.etapa_atual(cli), "proximo": prox,
                    "atualizado": cli["atualizado"],
                    "job_id": cli["job_id"] if cli.get("job_id") and C.job_existe(cli["job_id"]) else "",   # trabalho na lixeira: volta a ser card
                    "modalidade": cli["contexto"].get("modalidade") or ""})
    return {"clientes": out}


class NovoCliente(BaseModel):
    nome: str = Field(default="", max_length=200)


@router.post("/clientes")
async def novo_cliente(body: NovoCliente, _u: dict = Depends(_dono)):
    from .routes import av_atual
    cid = C.criar(body.nome, av_atual())
    if body.nome.strip():
        C.juntar_contexto(cid, {"solicitante_nome": body.nome.strip()})
    return _estado(cid)


@router.get("/clientes/{cid}")
async def ver_cliente(cid: str, _u: dict = Depends(_dono)):
    return _estado(cid)


@router.delete("/clientes/{cid}")
async def apagar_cliente(cid: str, _u: dict = Depends(_dono)):
    _cli(cid)
    C.apagar(cid)
    return {"ok": True}


class Entrada(BaseModel):
    texto: str = Field(min_length=1, max_length=20000)
    tipo: str = Field(default="texto", pattern="^(texto|whatsapp)$")


_SINAIS_VISTORIA = re.compile(r"(?i)\b(?:quartos?|su[ií]tes?|banheiros?|cozinha|sala|telhado|cobertura|forro|piso|"
                              r"reboco|pintura|umidade|infiltra[cç][aã]o|trinca|fissura|estado de conserva[cç][aã]o|"
                              r"reparos?|esquadrias?|muro|port[aã]o|garagem|vizinhan[cç]a|medi(?:u|das?|[cç][aã]o)|"
                              r"trena|idade aparente|padr[aã]o construtivo|fachada)\b")


def _eh_checklist(texto: str) -> bool:
    """O relato da vistoria: o que vem da página de vistoria ("VISTORIA…") ou o checklist escrito na conversa
    (085: no 9121 o Alan escreveu o checklist na conversa e ele nunca chegou ao laudo)."""
    t = texto.lstrip()
    if t.upper().startswith(("VISTORIA", "CHECKLIST", "RELATO DA VISTORIA")):
        return True
    return len(t) >= 300 and len(set(m.group(0).lower() for m in _SINAIS_VISTORIA.finditer(t))) >= 5


def _guardar_checklist(cid: str, texto: str) -> None:
    """Soma ao relato que já existe (a vistoria pode vir em mais de uma mensagem)."""
    antes = (C.obter(cid)["contexto"].get("checklist") or "").strip()
    novo = texto.strip() if not antes or texto.strip() in antes else antes + "\n\n" + texto.strip()
    C.juntar_contexto(cid, {"checklist": novo, "visita_feita": True})
    from . import rotas_whatsapp as W
    n = W.fotos_pendentes_para_vistoria(cid)
    if n:
        total = len([f for f in (C.pasta(cid) / "foto").glob("*") if f.is_file()])
        C.mensagem(cid, "sistema", "texto", f"As fotos que você mandou são da vistoria: {total} fotos da vistoria guardadas.")


_PEDE_MUDANCA = re.compile(r"(?i)\b(ajust\w*|mud\w*|troc\w*|corrig\w*|corrij\w*|refa\w*|tir\w*|aument\w*|diminu\w*|"
                           r"centraliz\w*|mov\w*|arrum\w*|alter\w*|coloc\w*|substitu\w*)\b")
_LAUDO = re.compile(r"(?i)\b(laudo|texto|frase|par[aá]grafo|p[aá]gina|item|tabela|t[ií]tulo|quebra)\b")
_IMAGEM = re.compile(r"(?i)\b(quadrad\w*|ret[aâ]ngul\w*|contorno|demarca\w*|mapa|imagem|foto|fachada|capa|figura)\b")


def _onde_se_muda(cid: str, texto: str) -> tuple[str, str] | None:
    """167-3: o chat não fica calado nem refaz o laudo. Com o laudo já montado, um pedido de mudança no texto ou numa
    imagem recebe UMA linha dizendo onde se faz, com o botão [Abrir o laudo editável]."""
    jid = (_cli(cid) or {}).get("job_id") or ""
    if not jid or not C.job_existe(jid) or not db.resultado(jid, "entrega"):
        return None
    if not _PEDE_MUDANCA.search(texto or "") or not (_IMAGEM.search(texto) or _LAUDO.search(texto)):
        return None                         # conversa comum (ex.: "o cliente mudou de endereço") segue o caminho normal
    # 172: a revisão final é no Word do avaliador (baixado na revisão humana)
    if _IMAGEM.search(texto):
        return ("Imagem: antes de montar, ajuste em Imagens do laudo, na escolha dos referenciais; depois de pronto, baixe a "
                "imagem em Detalhes → Imagens do laudo, edite no seu programa e troque no Word.", jid)
    return ("Isso você muda no Word: toque em [Baixar para a revisão humana], abra o Word no seu computador ou no "
            "Google Drive e ache o trecho com Ctrl+F.", jid)


@router.post("/clientes/{cid}/mensagem")
async def nova_mensagem(cid: str, body: Entrada, _u: dict = Depends(_dono)):
    """O avaliador escreve (ou cola o WhatsApp); o sistema entende, diz o que vai fazer e faz o que
    é interno. O que sai para fora espera o OK (botão)."""
    from . import ia
    _cli(cid)
    C.mensagem(cid, "avaliador", body.tipo, body.texto)
    resp = _onde_se_muda(cid, body.texto)   # 167-3: pedido de mudança no laudo pronto → diz onde se faz (sem refazer)
    if resp:
        C.mensagem(cid, "sistema", "texto", resp[0], dados={"job_id": resp[1]})
        return _estado(cid)
    if _eh_checklist(body.texto):           # checklist da página de vistoria ou escrito na conversa
        _guardar_checklist(cid, body.texto)
        await _analisar_visita(cid, body.texto)
        try:                                # 085: o mesmo texto pode trazer dados (DITCD, base…): lê também
            lido = await C.ler_mensagem(cid, body.texto, body.tipo)
            campos = {k: v for k, v in lido.campos.model_dump().items() if v not in (None, "")
                      and k in ("data_ditcd", "visita", "pin_maps", "matricula")}
            if campos:
                C.juntar_contexto(cid, campos)
            if campos.get("data_ditcd"):             # 099-3: a DITCD do relato responde o portão (sem "Confirmar")
                try:
                    from . import portoes
                    d = str(campos["data_ditcd"])[:10]
                    portoes.confirmar(cid, "visita", "data_base", d, f"DITCD {d[8:10]}/{d[5:7]}/{d[:4]} (do seu relato)")
                except Exception:
                    pass
            nome = (lido.campos.solicitante_nome or "").strip()
            if nome and not C.obter(cid)["contexto"].get("solicitante_confirmado"):
                DC.escolher_solicitante(cid, nome)       # 096-3: "Quem contrata é o Fulano." responde a pergunta
                C.mensagem(cid, "sistema", "texto", f"✓ Quem contrata: {nome} (do seu relato).")
        except Exception:
            pass
        ctx = C.obter(cid)["contexto"]
        contrato_assinado = re.search(r"(?i)n[aã]o precisa (?:de |fazer )?proposta|contrato j[aá] (?:foi |está )?assinado", body.texto)
        if contrato_assinado and ctx.get("proposta_status") not in ("aprovada", "fora"):
            C.juntar_contexto(cid, {"proposta_status": "fora"})           # 096-4: o relato dispensa a proposta
            C.mensagem(cid, "sistema", "texto", "✓ Proposta dispensada: o contrato já foi assinado (do seu relato).")
        if contrato_assinado:                    # 100-4: vale a palavra do avaliador, mesmo antes de achar o documento
            C.juntar_contexto(cid, {"contrato_assinado_relato": True})
        if contrato_assinado:                    # 099-2: o contrato que já está na conversa vale, sem as 6 confirmações
            try:
                from . import portoes
                if portoes.contrato_existente(C.obter(cid)["contexto"]) and C.obter(cid)["contexto"].get("contrato_status") != "aprovado":
                    portoes.usar_contrato_existente(cid)
                    C.mensagem(cid, "sistema", "texto", "✓ Contrato assinado (do seu relato): vale o que já está na conversa.")
            except Exception:
                pass
        if precisa_entender(cid) and C.obter(cid)["contexto"].get("entendimento_status") != "aguardando":
            try:                                 # 099-1: o relato que chega primeiro também passa pelo entendimento
                await E.resumir(cid)
            except Exception:
                pass
        return _estado(cid)
    if precisa_entender(cid):               # ORDEM 062: antes de começar, resume e pergunta "É isso?"
        try:
            await E.resumir(cid)
        except ia.IAFalhou as e:
            C.mensagem(cid, "sistema", "texto", f"Não consegui ler agora ({e}). O texto ficou guardado.")
        return _estado(cid)
    try:
        lido = await C.ler_mensagem(cid, body.texto, body.tipo)
    except ia.IAFalhou as e:
        C.mensagem(cid, "sistema", "texto", f"Não consegui ler agora ({e}). O texto ficou guardado.")
        return _estado(cid)
    campos = {k: v for k, v in lido.campos.model_dump().items() if v not in (None, "")}
    if campos.get("solicitante_nome"):          # 071-C4: quem o AVALIADOR diz que contrata manda (e fica protegido)
        DC.escolher_solicitante(cid, campos.pop("solicitante_nome"))
        C.atualizar(cid, nome=C.obter(cid)["contexto"]["solicitante_nome"][:200])
    if campos.get("proprietario"):
        campos["proprietario"] = DC.nome_proprio(campos["proprietario"])
    if campos:
        fontes = dict((C.obter(cid)["contexto"].get("_fonte") or {}))
        fontes.update({k: "você disse" for k in campos})
        campos["_fonte"] = fontes
    ctx, mudou = C.juntar_contexto(cid, campos)
    _oferecer_doc(cid, body.texto)              # 071-A: "está na CNH" → o JdB vai ao documento e mostra
    feitos = []
    quando_v = C._dt(ctx.get("visita") or "") if "visita" in mudou else None
    passou = bool(ctx.get("visita_feita")) or bool(quando_v and quando_v < datetime.now(timezone.utc))
    if "visita" in mudou and passou:       # 069-A6: visita que já aconteceu não tem aviso
        if not ctx.get("visita_feita"):
            C.juntar_contexto(cid, {"visita_feita": True})
        feitos.append(f"Anotei a visita de {C.quando_legivel(ctx['visita'])} como feita.")
    elif "visita" in mudou:                # interno: compromisso + aviso no app (D-092)
        C.agendar(cid, ctx["visita"], f"Visita: {ctx.get('imovel_tipo') or 'imóvel'} "
                                      f"{('– ' + ctx['bairro']) if ctx.get('bairro') else ''}".strip())
        feitos.append(f"Visita marcada no sistema para {C.quando_legivel(ctx['visita'])}; "
                      f"aviso no app {int(db.setting('aviso_visita_min') or 120) // 60} h antes.")
    falta_prop = C.faltam(ctx, C.CAMPOS_PROPOSTA)
    if ("proposta" in lido.intencao or not ctx.get("proposta_status")) and not falta_prop \
            and not C._contrato_ja_mandado(ctx) \
            and ctx.get("proposta_status") not in ("aguardando_revisao", "aprovada"):
        C.juntar_contexto(cid, {"proposta_status": "aguardando_revisao"})
        s = C.sugerir_proposta(ctx)
        feitos.append(f"Proposta montada para revisar: {E.NOME_MOD.get(s['modalidade'], s['modalidade'])}"
                      + (f", R$ {s['valor']}" if s.get("valor") else "") + ". " + _confira(cid))
    if "visita_feita" in lido.intencao:
        C.juntar_contexto(cid, {"visita_feita": True})
    jid_c = (C.obter(cid) or {}).get("job_id") or ""
    if jid_c and C.job_existe(jid_c):            # 111-3b: idade dos anúncios dita na conversa vale nos anúncios
        try:
            from . import idade_conversa
            ns = idade_conversa.aplicar(jid_c, body.texto)
            if ns:
                feitos.append("Gravei a idade nos anúncios " + ", ".join(str(n) for n in ns)
                              + ". Toque em Atualizar o laudo para ela entrar no PDF.")
        except Exception:                        # noqa: BLE001 — a conversa nunca cai por isso
            log.exception("idade na conversa %s", cid)
    resp = " ".join(x for x in (lido.resposta.strip(), *feitos) if x) or "Anotado."
    C.mensagem(cid, "sistema", "texto", resp, {"campos": list(mudou)})
    if lido.pergunta.strip():
        C.mensagem(cid, "sistema", "pergunta", lido.pergunta.strip())
    return _estado(cid)


def _oferecer_doc(cid: str, texto: str) -> None:
    """Quando o avaliador diz onde está o dado ("o CPF está na CNH e no contrato"), o JdB não pergunta de novo:
    vai ao documento já lido e mostra "No documento: CPF •••-16. Uso esse?"."""
    import re
    if not re.search(r"\bcpf\b", texto, re.I) or not re.search(r"\bcnh\b|contrato|\brg\b|documento|identidade", texto, re.I):
        return
    ctx = C.obter(cid)["contexto"]
    sol = ctx.get("solicitante_nome") or ""
    eu = next((p for p in ctx.get("pessoas") or [] if sol and DC.mesma_pessoa(p["nome"], sol) and p.get("doc")), None)
    if not eu:
        return
    C.mensagem(cid, "sistema", "escolha", f"No documento ({eu.get('fonte_doc') or eu.get('fonte') or 'documento'}): "
               f"CPF {C.mascarar(eu['doc'])}, de {eu['nome']}. Uso esse?",
               {"pergunta": "cpf", "opcoes": [{"valor": eu["doc"], "rotulo": "Usar esse", "recomendada": True}], "outro": True})


def precisa_entender(cid: str) -> bool:
    """Ainda não confirmou o entendimento do caso. Cliente que já passou da proposta (de antes da
    ORDEM 062) segue como estava."""
    ctx = (C.obter(cid) or {}).get("contexto") or {}
    # 099-1: a proposta dispensada pelo relato ("fora") não dispensa o entendimento — só quem já passou da proposta
    # de verdade (aprovada ou em revisão, clientes de antes da 062) segue sem ele
    return (ctx.get("entendimento_status") != "confirmado"
            and ctx.get("proposta_status") not in ("aprovada", "aguardando_revisao"))


@router.post("/clientes/{cid}/entendimento")
async def refazer_entendimento(cid: str, _u: dict = Depends(_dono)):
    """Resume o caso de novo (ex.: depois de mandar só arquivos)."""
    from . import ia
    _cli(cid)
    try:
        await E.resumir(cid)
    except ia.IAFalhou as e:
        C.mensagem(cid, "sistema", "texto", f"Não consegui resumir agora ({e}).")
    return _estado(cid)


@router.post("/clientes/{cid}/entendimento/confirmar")
async def confirmar_entendimento(cid: str, _u: dict = Depends(_dono)):
    """"É isso, pode começar": guarda o "Entendimento do caso", a finalidade e a modalidade confirmadas
    preenchem o trabalho, e só então começa o fluxo (proposta para revisão — D-089/D-091). Nada vai ao cliente."""
    cli = _cli(cid)
    ctx = cli["contexto"]
    if ctx.get("entendimento_status") != "aguardando" or not ctx.get("entendimento_rascunho"):
        raise HTTPException(status_code=409, detail="não há resumo esperando confirmação")
    novos = {"entendimento_status": "confirmado", "entendimento": E.para_guardar(ctx["entendimento_rascunho"]),
             "entendimento_em": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if ctx.get("modalidade_sugerida"):
        novos["modalidade"] = ctx["modalidade_sugerida"]
    if ctx.get("finalidade_sugerida"):
        novos["finalidade"] = ctx["finalidade_sugerida"]
    ctx, _ = C.juntar_contexto(cid, novos)
    _levar_ao_trabalho(cli, ctx)
    feitos = ["Combinado, guardei o entendimento do caso."]
    falta_prop = C.faltam(ctx, C.CAMPOS_PROPOSTA)
    if (not falta_prop and ctx.get("proposta_status") not in ("aguardando_revisao", "aprovada", "fora")
            and not C._contrato_ja_mandado(ctx)):        # 096-4: proposta dispensada não volta
        C.juntar_contexto(cid, {"proposta_status": "aguardando_revisao"})
        s = C.sugerir_proposta(ctx)
        feitos.append(f"Montei a proposta para você revisar: {E.NOME_MOD.get(s['modalidade'], s['modalidade'])}, "
                      + (f"R$ {s['valor']}" if s.get("valor") else "falta dizer quanto vai cobrar")
                      + ". " + _confira(cid) + " Nada foi enviado ao cliente.")
    elif falta_prop:
        feitos.append("Para montar a proposta ainda falta: " + "; ".join(r for _, r in falta_prop) + ".")
    C.mensagem(cid, "sistema", "texto", " ".join(feitos))
    from . import joao
    caso = " ".join(str(ctx.get(k) or "") for k in ("finalidade", "entendimento"))
    if joao.eh_itcd(caso) and not ctx.get("itcd_avisado"):   # 069-B2: as regras do ITCD de Goiás, logo no começo
        msg = ITCD_GOIAS
        d = str(ctx.get("data_ditcd") or ctx.get("data_base_escolhida") or "")[:10]
        if re.match(r"\d{4}-\d{2}-\d{2}$", d):          # 096-4: a DITCD já foi informada: não pede de novo
            msg = msg.replace("não a da vistoria: me mande essa data;",
                              f"não a da vistoria: vale a que você informou ({d[8:10]}/{d[5:7]}/{d[:4]});")
        C.mensagem(cid, "sistema", "texto", msg)
        C.juntar_contexto(cid, {"itcd_avisado": True})
    return _estado(cid)


ITCD_GOIAS = (
    "Como é ITCD em Goiás, combine com o cliente antes de seguir: "
    "1) o laudo vale na data da vistoria; mande a data da declaração (DITCD) só como fato do processo; "
    "2) o valor não fica abaixo da base que a Prefeitura usa no ITBI ou no IPTU (a maior das duas); "
    "3) a justificativa da malha tem prazo de 30 dias da ciência do comunicado e só pode ser feita uma vez; "
    "4) a referência da malha é a tabela FIPE (mande o relatório FIPE, o comunicado e o print do ITCD Web); "
    "5) atenção ao gol contra: se a casa valer mais que o declarado, o laudo não serve para justificar.")


def _confira(cid: str) -> str:
    """072-C4: diz quantos pontos o portão ainda pede antes do botão."""
    try:
        from . import portoes
        n = sum(1 for q in portoes.montar(cid, "proposta")["perguntas"] if not q.get("confirmado"))
    except Exception:
        n = 0
    if n:
        return (f"Confirme {'o ponto' if n == 1 else f'os {n} pontos'} do próximo passo e aperte “Aprovar e gerar mensagem”.")
    return "Confira e aperte “Aprovar e gerar mensagem”."


def _levar_ao_trabalho(cli: dict, ctx: dict) -> None:
    """Trabalho já aberto (com documentos e fotos): a finalidade e a modalidade confirmadas vão para ele."""
    from .modelos import Trabalho
    from .orquestrador import ocupado
    jid = cli.get("job_id")
    if not jid or not C.job_existe(jid) or ocupado(jid):
        return
    j = db.job(jid)
    d = dict(j["dados"])
    mudou = False
    if ctx.get("modalidade") in E.MODALIDADES and d.get("modalidade") != ctx["modalidade"]:
        d["modalidade"], mudou = ctx["modalidade"], True
    if ctx.get("finalidade") and d.get("finalidade") != ctx["finalidade"]:
        d["finalidade"], mudou = ctx["finalidade"], True
    if mudou:
        db.atualizar_dados(jid, Trabalho.model_validate(d))
        db.evento(jid, "orquestrador", "edicao_manual", "finalidade e modalidade confirmadas no entendimento do caso")


@router.post("/clientes/{cid}/proposta/aprovar")
async def aprovar_proposta(cid: str, _u: dict = Depends(_dono)):
    """OK do avaliador: gera a proposta pelo P10 (PDF) e a mensagem pronta. Nada é enviado."""
    from . import portoes
    from .rascunho import proposta_do_cliente
    from .rotas_propostas import nova_proposta
    cli = _cli(cid)
    ctx = cli["contexto"]
    if cli.get("proposta_id"):
        raise HTTPException(status_code=409, detail="a proposta já foi aprovada")
    g = portoes.montar(cid, "proposta")
    if not g["completo"]:                    # ORDEM 071: nada de aprovar com pergunta aberta
        raise HTTPException(status_code=409, detail="antes de seguir, confirme: " + "; ".join(
            q["pergunta"].lower().rstrip("?") for q in g["perguntas"] if not q["confirmado"]))
    p = await nova_proposta(proposta_do_cliente(ctx), _u=_u)      # a mesma do rascunho (ORDEM 065)
    numero = f"{p['ano']}-{p['numero']:03d}"
    C.atualizar(cid, proposta_id=p["id"])
    C.juntar_contexto(cid, {"proposta_status": "aprovada", "proposta_numero": numero})
    C.mensagem(cid, "sistema", "proposta", f"Proposta nº {numero} pronta (PDF). Mensagem para você mandar no seu WhatsApp:",
               {"mensagem_pronta": C.msg_proposta(ctx, numero), "arquivos": p["arquivos"], "proposta_id": p["id"]})
    return _estado(cid)


class OkContrato(BaseModel):
    pagamento: str = "pix"


@router.post("/clientes/{cid}/contrato/aprovar")
async def aprovar_contrato(cid: str, body: OkContrato, _u: dict = Depends(_dono)):
    """Revisão obrigatória: o contrato só sai com o OK. Faltando dado: mensagem pronta para pedir."""
    from .rotas_propostas import Contratante, NovoContrato, gerar_contrato
    from . import portoes
    cli = _cli(cid)
    ctx = cli["contexto"]
    if not cli["proposta_id"]:
        raise HTTPException(status_code=409, detail="aprove a proposta antes")
    g = portoes.montar(cid, "contrato")
    if not g["completo"] and not C.faltam(ctx, C.CAMPOS_CONTRATO):
        raise HTTPException(status_code=409, detail="antes de seguir, confirme: " + "; ".join(
            q["pergunta"].lower().rstrip("?") for q in g["perguntas"] if not q["confirmado"]))
    falta = C.faltam(ctx, C.CAMPOS_CONTRATO)
    if falta:
        msg = C.msg_pedir_dados(ctx, [r for _, r in falta])
        C.mensagem(cid, "sistema", "pedido", "Faltam dados para o contrato. Mensagem para pedir ao cliente:",
                   {"mensagem_pronta": msg})
        raise HTTPException(status_code=409, detail="falta: " + ", ".join(r for _, r in falta))
    doc = ctx["solicitante_doc"]
    pj = len("".join(ch for ch in doc if ch.isdigit())) == 14
    p = await gerar_contrato(cli["proposta_id"], NovoContrato(contratante=Contratante(
        nome=ctx["solicitante_nome"], doc_tipo="CNPJ" if pj else "CPF", doc=doc,
        endereco=ctx["solicitante_endereco"], email=ctx.get("solicitante_email", ""),
        telefone=ctx.get("solicitante_telefone", ""), pj=pj), pagamento=body.pagamento), _u=_u)
    C.juntar_contexto(cid, {"contrato_status": "gerado"})
    C.mensagem(cid, "sistema", "contrato", "Contrato pronto (PDF) para assinar no gov.br. Mensagem para você mandar:",
               {"mensagem_pronta": "Segue o contrato para assinatura pelo gov.br. Depois de assinado, me devolva por aqui.",
                "arquivos": p["arquivos"], "proposta_id": p["id"]})
    return _estado(cid)


class Agenda(BaseModel):
    quando: str = Field(max_length=40)
    aviso_min: int = Field(default=120, ge=0, le=7 * 24 * 60)


@router.post("/clientes/{cid}/visita")
async def marcar_visita(cid: str, body: Agenda, _u: dict = Depends(_dono)):
    _cli(cid)
    C.juntar_contexto(cid, {"visita": body.quando})
    C.agendar(cid, body.quando, "Visita", body.aviso_min)
    C.mensagem(cid, "sistema", "texto", f"Visita marcada para {C.quando_legivel(body.quando)}.")
    return _estado(cid)


@router.get("/clientes/{cid}/vistoria", response_class=HTMLResponse)
async def pagina_vistoria(cid: str, app: str = "", _u: dict = Depends(_dono)):
    """ORDEM 067 / D-054: a página da vistoria sai do P11 (a vistoria padrão do Alan), sob medida para o caso.
    Funciona no celular sem internet; "Concluir vistoria" envia ao trabalho pelo código do cliente."""
    import secrets
    from . import vistoria_p11 as V
    cli = _cli(cid)
    ctx = cli["contexto"]
    token = ctx.get("vistoria_token") or secrets.token_urlsafe(16)
    if not ctx.get("vistoria_token"):
        DC._gravar(cid, {"vistoria_token": token})
    numero = cid
    if cli.get("job_id") and C.job_existe(cli["job_id"]):
        numero = str(db.job(cli["job_id"])["numero"])
    destino = app if app.startswith(("http://", "https://")) else ""
    html = V.pagina(V.caso(numero, ctx), f"/api/avaliacao/vistoria/{cid}/{token}",
                    (destino + f"#/cliente/{cid}") if destino else "")
    (C.pasta(cid) / "vistoria.html").write_text(html, encoding="utf-8")
    return HTMLResponse(html)


class VistoriaEnviada(BaseModel):
    texto: str = Field(min_length=10, max_length=60_000)
    marcas: dict = Field(default_factory=dict)
    feitos: int = 0
    total: int = 0


@router.post("/vistoria/{cid}/{token}")
async def receber_vistoria(cid: str, token: str, body: VistoriaEnviada):
    """"Concluir vistoria" (067): o texto e as marcações vão direto para o trabalho (a conversa do cliente).
    Sem login (a página fica no celular): vale o código do cliente, criado com a página."""
    import secrets
    cli = C.obter(cid)
    if not cli or not secrets.compare_digest(str(cli["contexto"].get("vistoria_token") or ""), token):
        raise HTTPException(status_code=404)
    C.mensagem(cid, "avaliador", "vistoria", body.texto, {"feitos": body.feitos, "total": body.total})
    C.juntar_contexto(cid, {"checklist": body.texto, "visita_feita": True})
    DC._gravar(cid, {"vistoria_respostas": body.marcas})
    C.mensagem(cid, "sistema", "texto", f"Recebi a vistoria ({body.feitos} de {body.total} itens feitos).")
    await _analisar_visita(cid, body.texto)
    return {"ok": True}


async def _analisar_visita(cid: str, texto: str) -> None:
    """072-C10: o relato da vistoria passa pela análise do João antes do "Montar o laudo"."""
    from . import analise_visita, ia
    try:
        await analise_visita.analisar(cid, texto)
    except (ia.IAFalhou, Exception) as e:                 # a análise é ajuda: nunca derruba o recebimento
        log.warning("análise da vistoria %s: %s", cid, type(e).__name__)
        C.mensagem(cid, "sistema", "texto", "Recebi o relato da vistoria. Não consegui conferir as medidas agora. "
                                            "Quando as fotos chegarem, aperte “Montar o laudo”.")


# ------------------------------------------------------------------ documentos e fotos na conversa
# ORDEM 066: a leitura devolve as PESSOAS com o papel que têm no documento (ninguém vira solicitante)
_DocLido = DC.DocLido
INSTR_DOC = DC.INSTR_DOC


@router.post("/clientes/{cid}/arquivo")
async def anexar(cid: str, tipo: str = Form("documento"), arquivo: UploadFile = File(...), _u: dict = Depends(_dono)):
    from . import ia, imagens_ia
    from .agentes.leitor_anuncio import modelo_leve
    _cli(cid)
    if tipo not in ("documento", "foto", "solicitante"):
        raise HTTPException(status_code=400, detail="tipo inválido")
    dados = await arquivo.read(50 * 1024 * 1024 + 1)
    if not dados or len(dados) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="arquivo vazio ou maior que 50 MB")
    nome = "".join(ch for ch in (arquivo.filename or "arquivo") if ch.isalnum() or ch in "._- ")[:120] or "arquivo"
    destino = C.pasta(cid) / tipo
    destino.mkdir(parents=True, exist_ok=True)
    (destino / nome).write_bytes(dados)
    rel = f"{tipo}/{nome}"
    if tipo == "foto":
        C.mensagem(cid, "avaliador", "arquivo", f"Foto: {nome}", {"arquivo": rel})
        return _estado(cid)
    C.mensagem(cid, "avaliador", "arquivo", f"Documento: {nome}", {"arquivo": rel})
    try:     # a IA leve lê o documento e o dado vai para o contrato e para o laudo (sem pedir de novo)
        await asyncio.to_thread(imagens_ia.preparar, C.pasta(cid), [rel], imagens_ia.LADO_IA, None)
        ia.definir_contexto(f"conversa-{cid}", "conversa")
        from . import joao
        lido: _DocLido = await ia.perguntar(INSTR_DOC + "\n\n" + joao.trecho("1"), f"Documento: {nome}", _DocLido,
                                            arquivos=[C.pasta(cid) / rel], cwd=C.pasta(cid))      # modelo forte (071-C2)
        texto, _ = DC.aplicar_documento(cid, lido, nome)       # a pergunta "Quem está contratando?" já vai junto
        C.mensagem(cid, "sistema", "texto", texto)
        if tipo == "solicitante":                               # L200: o titular vira opção do card
            DC.marcar_documento_do_solicitante(cid, [p.nome for p in lido.pessoas if p.papel == "titular do documento"])  # pais da CNH, não
    except Exception as e:  # o arquivo fica guardado mesmo sem leitura
        log.warning("documento do cliente %s não lido: %s", cid, type(e).__name__)
        C.mensagem(cid, "sistema", "texto", "Guardei o documento, mas não consegui ler agora.")
    return _estado(cid)


class Escolha(BaseModel):
    pergunta: str = Field(pattern="^(solicitante|cpf|fotos)$")
    valor: str = Field(min_length=2, max_length=200)


@router.post("/clientes/{cid}/escolha")
async def escolher(cid: str, body: Escolha, _u: dict = Depends(_dono)):
    """ORDEM 066: o avaliador diz quem está contratando o laudo (card "Quem está contratando?")."""
    _cli(cid)
    if body.pergunta == "cpf":
        ctx = C.obter(cid)["contexto"]
        DC._gravar(cid, {"solicitante_doc": body.valor.strip(), "_doc_de": ctx.get("solicitante_nome") or "",
                         "_corrigidos": sorted(DC.protegidos(ctx) | {"solicitante_doc"}),
                         "_fonte": {**(ctx.get("_fonte") or {}), "solicitante_doc": "você confirmou"}})
        for m in C.mensagens(cid):
            if m["tipo"] == "escolha" and m["dados"].get("pergunta") == "cpf" and not m["dados"].get("respondida"):
                C.marcar_dados(m["id"], {**m["dados"], "respondida": C.mascarar(body.valor)})
        C.mensagem(cid, "sistema", "texto", f"Combinado: o CPF do solicitante é {C.mascarar(body.valor)}. O rascunho já usa esse.")
        return _estado(cid)
    if body.pergunta == "fotos":                      # 072-C9: "Essas N fotos são da sua vistoria?"
        from . import rotas_whatsapp as W
        card = next((m for m in reversed(C.mensagens(cid)) if m["tipo"] == "escolha"
                     and m["dados"].get("pergunta") == "fotos" and not m["dados"].get("respondida")), None)
        if not card:
            raise HTTPException(status_code=409, detail="essa pergunta já foi respondida")
        n = 0
        if body.valor == "vistoria":
            for rel in card["dados"].get("arquivos") or []:
                if (C.pasta(cid) / rel).is_file():
                    W._mover(cid, rel, "foto")
                    n += 1
        C.marcar_dados(card["id"], {**card["dados"], "respondida": "Sim, são da vistoria" if body.valor == "vistoria" else "Não, o cliente mandou"})
        C.mensagem(cid, "sistema", "texto", f"Combinado: {n} {'foto foi' if n == 1 else 'fotos foram'} para as fotos da vistoria."
                   if body.valor == "vistoria" else "Combinado: ficam como fotos que o cliente mandou (não entram como vistoria).")
        return _estado(cid)
    DC.escolher_solicitante(cid, body.valor)
    nome = C.obter(cid)["contexto"]["solicitante_nome"]
    C.mensagem(cid, "avaliador", "texto", f"Quem contrata é {nome}.")
    C.mensagem(cid, "sistema", "texto", f"Combinado: o solicitante é {nome}. As pessoas dos documentos "
                                        "ficam com o papel que têm neles.")
    return _estado(cid)


class Correcao(BaseModel):
    campo: str = Field(max_length=40)
    valor: str = Field(default="", max_length=500)


@router.get("/clientes/{cid}/dados")
async def dados_guardados(cid: str, _u: dict = Depends(_dono)):
    """ORDEM 066: os dados guardados do cliente, em português, com o que pode ser corrigido."""
    return {"linhas": DC.linhas(_cli(cid)["contexto"])}


@router.post("/clientes/{cid}/dado")
async def corrigir_dado(cid: str, body: Correcao, _u: dict = Depends(_dono)):
    """ORDEM 066: [Corrigir] — grava, registra que foi o avaliador e protege da leitura automática.
    O rascunho da proposta e do contrato se refaz sozinho com o dado novo (065)."""
    _cli(cid)
    try:
        texto = DC.corrigir(cid, body.campo, body.valor)
    except ValueError:
        raise HTTPException(status_code=400, detail="esse dado não pode ser corrigido aqui")
    C.mensagem(cid, "avaliador", "correcao", texto)
    return _estado(cid)


class RespostaPortao(BaseModel):
    id: str = Field(max_length=40)
    valor: str = Field(max_length=500)
    rotulo: str = Field(default="", max_length=500)


@router.get("/clientes/{cid}/portao/{etapa}")
async def ver_portao(cid: str, etapa: str, _u: dict = Depends(_dono)):
    """ORDEM 071: "Antes de seguir, confirme:" — as perguntas da etapa, com a sugestão e a fonte."""
    from . import portoes
    _cli(cid)
    if etapa not in portoes.PERGUNTAS:
        raise HTTPException(status_code=404)
    return portoes.montar(cid, etapa)


@router.post("/clientes/{cid}/portao/{etapa}")
async def responder_portao(cid: str, etapa: str, body: RespostaPortao, _u: dict = Depends(_dono)):
    from . import portoes
    _cli(cid)
    try:
        return portoes.confirmar(cid, etapa, body.id, body.valor, body.rotulo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Escreva a data assim: 28/10/2026." if str(e) == "data_base"
                            else "resposta inválida")


@router.post("/clientes/{cid}/proposta/pular")
async def pular_proposta(cid: str, _u: dict = Depends(_dono)):
    """072-C5 [Pular a proposta]: o contrato já foi assinado; a proposta fica "feita fora do JdB" (056)
    e o contrato que ele mandou passa a valer."""
    from . import portoes
    cli = _cli(cid)
    ctx = cli["contexto"]
    if not portoes.contrato_existente(ctx):
        raise HTTPException(status_code=409, detail="não achei contrato já mandado nesta conversa")
    DC._gravar(cid, {"proposta_status": "fora"})
    if ctx.get("contrato_status") not in ("gerado", "existente"):
        portoes.usar_contrato_existente(cid)
    C.mensagem(cid, "sistema", "texto", "Combinado: a proposta não vai, porque o contrato já foi assinado. "
                                        "A proposta fica como feita fora do JdB, e o contrato que você mandou vale.")
    return _estado(cid)


@router.post("/clientes/{cid}/proposta/mesmo-assim")
async def proposta_mesmo_assim(cid: str, _u: dict = Depends(_dono)):
    """072-C5 [Fazer a proposta assim mesmo]."""
    _cli(cid)
    DC._gravar(cid, {"proposta_mesmo_assim": True})
    return _estado(cid)


@router.post("/clientes/{cid}/contrato/existente")
async def usar_contrato(cid: str, _u: dict = Depends(_dono)):
    """[Usar esse contrato]: o avaliador já mandou, o cliente assinou — a etapa Contrato fica feita com o arquivo."""
    from . import portoes
    _cli(cid)
    try:
        portoes.usar_contrato_existente(cid)
    except ValueError:
        raise HTTPException(status_code=404, detail="não achei contrato já mandado nesta conversa")
    ctx = C.obter(cid)["contexto"]
    C.mensagem(cid, "sistema", "texto", f"Combinado: uso o contrato que você já mandou ({ctx.get('contrato_arquivo')})"
               + (" — o sinal já foi pago." if ctx.get("sinal_pago") else ".") + " A etapa Contrato está feita.")
    return _estado(cid)


@router.post("/clientes/{cid}/trabalho")
async def seguir_para_laudo(cid: str, aceito_extra: bool = False, _u: dict = Depends(_dono)):
    """Pós-visita (D-093): abre o trabalho com o que a conversa já tem (nada é redigitado), leva
    documentos, fotos e checklist, e o sistema segue sozinho até a parada "Referenciais e
    alinhamento"."""
    from . import orquestrador
    from .modelos import Trabalho
    from .routes import _sincronizar_vistoria
    cli = _cli(cid)
    ctx = cli["contexto"]
    if cli["job_id"] and C.job_existe(cli["job_id"]):
        return _estado(cid)
    if precisa_entender(cid):               # ORDEM 062: o laudo só começa depois do "É isso, pode começar"
        raise HTTPException(status_code=409, detail="antes de abrir o trabalho, confirme o entendimento do caso")
    # 074-A2 (P5 §C): sem foto da vistoria o laudo não começa — o portão pergunta antes
    if not any(f.is_file() for f in (C.pasta(cid) / "foto").glob("*")) if (C.pasta(cid) / "foto").is_dir() else True:
        raise HTTPException(status_code=409, detail="faltam as fotos da vistoria: mande as fotos ou confirme no próximo passo "
                                                    "que as que você mandou são da vistoria")
    falta = C.falta_para_montar(ctx)        # 099-1 (b/c): nunca abre trabalho sem imóvel, modalidade ou finalidade
    if falta:
        raise HTTPException(status_code=409, detail="Antes de montar o laudo, falta: " + "; ".join(falta) + ".")
    from . import planos as _pl                 # 155-1 / 156: o aviso do laudo extra vem ANTES de abrir e de a IA começar
    _ex = _pl.extra_para_avaliador(cli["avaliador_id"] or "AV-0001")
    if _ex and not aceito_extra:
        raise HTTPException(status_code=402, detail=_ex["texto"])
    n = db.proximo_numero()
    while db.numero_usado(n):
        n += 1
    d = C.trabalho_do_contexto(ctx, n)
    d["pin_maps"] = C.pin_do_contexto(ctx, cid)          # 074-B: o pin da conversa ou da vistoria
    t = Trabalho(id="", avaliador_id=cli["avaliador_id"], **{**d, "data_base": date.fromisoformat(d["data_base"]),
                           "data_vistoria": date.fromisoformat(d["data_vistoria"]),
                           "checklist_vistoria": ctx.get("checklist", ""), "data_emissao": None})
    jid = db.criar_job(t)
    t2 = _sincronizar_vistoria(jid, t.model_copy(update={"id": jid}))
    if t2.contexto != t.contexto:
        db.atualizar_dados(jid, t2)
    # ORDEM 061: foto e vídeo vindos do cliente vão junto, marcados "enviados pelo cliente" (não são de vistoria)
    for tipo in ("documento", "solicitante", "foto", "foto_cliente", "video_cliente"):
        origem = C.pasta(cid) / tipo
        if not origem.is_dir():
            continue
        (db.pasta(jid) / tipo).mkdir(parents=True, exist_ok=True)
        for f in sorted(origem.iterdir()):
            if f.is_file():
                shutil.copy2(f, db.pasta(jid) / tipo / f.name)
                db.adicionar_arquivo(jid, f.name, tipo, f"{tipo}/{f.name}", "", "")
    if aceito_extra:
        db.set_setting(f"aceito_extra:{jid}", "1")
    C.atualizar(cid, job_id=jid)
    C.mensagem(cid, "sistema", "texto", f"Abri o trabalho nº {n} com os dados da conversa. Sigo sozinho até a "
                                        "lista de referenciais.")
    orquestrador.enfileirar(jid)
    return _estado(cid)


def _base_do_relato(jid: str) -> dict | None:
    """084-5: o avaliador escreveu a base no relato ("área construída do IPTU 2025") → grava a escolha (a opção
    daquela base que cita a fonte dele, senão a sugerida) e a pergunta não volta."""
    from . import tela_trabalho
    from .agentes import selecao
    b = (((tela_trabalho._cliente(jid) or {}).get("contexto") or {}).get("base_calculo") or {})
    if b.get("base") not in ("construida", "terreno"):
        return None
    try:
        ops = selecao.opcoes_area(jid)[b["base"]]
    except Exception:
        return None
    if not ops:
        return None
    fonte = C._n(b.get("fonte") or "") if hasattr(C, "_n") else (b.get("fonte") or "").lower()
    pal = [w for w in fonte.split() if len(w) >= 4 or w.isdigit()]
    op = next((o for o in ops if pal and all(w in (str(o.get("campo")) + " " + str(o.get("origem"))).lower().replace("_", " ")
                                              for w in pal)), None) or next((o for o in ops if o.get("sugerida")), ops[0])
    try:
        return selecao.gravar_escolha_area(jid, b["base"], op["campo"])
    except ValueError:
        return None


# ------------------------------------------------------------------ alinhamento (D-093)
@router.post("/jobs/{jid}/comparacao/nao-tenho")
async def sem_comparacao(jid: str, _u: dict = Depends(_dono)):
    """097-1: [Não tenho] na pergunta da comparação (D-069): não pergunta de novo neste trabalho."""
    from . import pendencias_simples as PS
    db.set_setting(f"sem_comparacao:{jid}", "1")
    PS.aceitar(jid, "comparacao_d069")
    return {"ok": True}


@router.get("/jobs/{jid}/alinhamento")
async def alinhamento(jid: str, _u: dict = Depends(_dono)):
    """A PARADA ÚNICA "Referenciais e alinhamento": candidatos (D-056) + perguntas + pontos a
    alinhar (base do cálculo, divergência de área, objeto inteiro ou parte, data da vistoria)."""
    from .agentes import selecao
    from .routes import _alerta_datas
    from .routes import _job
    j = _job(jid)
    t = j["dados"]
    pontos = []
    esc = selecao.escolha_area(jid) or _base_do_relato(jid)
    if esc is None:
        pontos.append({"id": "base", "pergunta": "O cálculo usa a área construída ou a área total do terreno?",
                       "opcoes": ["Área construída", "Área total do terreno"], "recomendada": "Área construída"})
    # 093-2: casa/apartamento sem nenhum sinal de "parte" (galpão, unidade, sala, fração) no caso → imóvel inteiro,
    # sem perguntar
    sinais = " ".join(str(t.get(k) or "") for k in ("tipo", "finalidade", "objeto_parte", "contexto", "checklist_vistoria"))
    if (not t.get("objeto_parte") and not db.setting(f"objeto:{jid}")
            and re.search(r"(?i)\b(casa|sobrado|apartamento|resid)", str(t.get("tipo") or ""))
            and not re.search(r"(?i)parte ideal|s[oó] uma parte|fra[cç][aã]o ideal|um pavimento|unidade aut[oô]noma|"
                              r"s[oó] o (?:galp|pavimento|t[eé]rreo|andar)|sala comercial|galp[aã]o 0?\d", sinais)):   # 096-2
        db.set_setting(f"objeto:{jid}", "inteiro")
    if not t.get("objeto_parte") and not db.setting(f"objeto:{jid}"):   # 073-1: "inteiro" também é resposta
        pontos.append({"id": "objeto", "pergunta": "O laudo avalia o imóvel inteiro ou só uma parte?",
                       "opcoes": ["Imóvel inteiro", "Só uma parte"], "recomendada": "Imóvel inteiro"})
    # L200 (Caso W): o padrão e a idade do avaliando decidem a escolha dos referenciais e saem no laudo; sem eles
    # o laudo saía com "Tipologia / padrão: n/i". Sem resposta recomendada: quem viu o imóvel é o avaliador.
    nomes_c = {c.nome for c in db.campos(jid) if str(c.valor or "").strip() not in ("", "n/i", "None")}
    if not ({"padrao", "padrao_construtivo"} & nomes_c):
        pontos.append({"id": "padrao", "pergunta": "Qual o padrão construtivo do imóvel avaliado?",
                       "opcoes": ["Simples", "Normal", "Alto"], "recomendada": None})
    if "idade_aparente" not in nomes_c:
        pontos.append({"id": "idade", "pergunta": "Qual a idade aparente do imóvel avaliado?",
                       "opcoes": ["Novo (até 5 anos)", "5 a 15 anos", "15 a 30 anos", "Mais de 30 anos"],
                       "recomendada": None})
    datas = _alerta_datas(jid, j)
    if datas and not datas.startswith("CONFIRMADA"):
        pontos.append({"id": "data", "pergunta": "As fotos têm outra data. A data da vistoria está certa?",
                       "opcoes": ["A data está certa", "Corrigir a data"], "recomendada": "A data está certa"})
    from .leitura_pagina import fotos_unicas
    from .routes import _NAO_E_FOTO
    cands = [{**c.model_dump(mode="json"),       # 096-7: a galeria sem a mesma foto em vários tamanhos nem banner
              "fotos_url": fotos_unicas([u for u in c.fotos_url if not _NAO_E_FOTO.search(u)], 12)}
             for c in db.candidatos(jid)]
    # 097-1: laudo para o fisco → a pergunta da comparação (D-069) vem junto com a escolha, antes de montar
    from .pendencias_simples import valor_referencia_fisco
    ref_fisco = None
    if not any(c.get("decisao") == "comparacao" for c in cands) and not db.setting(f"sem_comparacao:{jid}"):
        ref_fisco = valor_referencia_fisco(jid)
    return {"job": jid, "pontos": pontos, "candidatos": cands, "referencia_fisco": ref_fisco,
            "recomendados": [c["n"] for c in cands if c.get("recomendado")],
            "situacao": situacao_pesquisa(jid, t, cands),
            # 074-F2: as respostas que o avaliador já deu (base do cálculo, objeto inteiro/parte, data)
            "respondidos": sum([esc is not None, bool(t.get("objeto_parte") or db.setting(f"objeto:{jid}")),
                                bool(datas and datas.startswith("CONFIRMADA"))])}


def versao_extensao_atual() -> str:
    """A versão da extensão do Chrome que está nesta pasta (a que o avaliador deve ter instalada)."""
    import json as _json
    from pathlib import Path as _P
    try:
        m = _P(__file__).resolve().parents[3] / "extensao-chrome" / "manifest.json"
        return str(_json.loads(m.read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return ""


def situacao_pesquisa(jid: str, t: dict, cands: list[dict]) -> dict:
    """070-B5 / 112: a linha do que fazer na lista de anúncios e o estado da extensão do Chrome. Sem busca
    automática (D-117): os anúncios vêm da extensão "Enviar ao JdB" ou do cadastro à mão."""
    # 091-2: uma conta só — o que está "entra" conta, mesmo com aviso; descartado é só o que está "descarta"
    vivos = [c for c in cands if c.get("decisao") != "descarta"
             and (not c.get("nao_recomendado") or c.get("decisao") == "entra")]
    seus = [c for c in vivos if c.get("fonte_coleta") in ("manual", "avaliador")]     # 073-4: quem achou foi o avaliador
    motivo = "Escolha os anúncios. Pesquise no seu Chrome e envie com a extensão, ou cadastre à mão."
    if seus:
        motivo = f"Você adicionou {len(seus)} {'anúncio' if len(seus) == 1 else 'anúncios'}. " + (
            motivo if len(seus) < 5 else "Escolha os que entram no laudo.")
    vista, atual = db.setting("extensao_versao") or "", versao_extensao_atual()
    return {"motivo": motivo,
            "extensao": {"vista": vista, "atual": atual, "atualizar": bool(atual) and vista != atual}}


# ------------------------------------------------------------------ push (D-092)
@router.get("/push/chave")
async def push_chave(_u: dict = Depends(_dono)):
    return {"chave": webpush.chave_publica()}


class Inscricao(BaseModel):
    endpoint: str
    keys: dict


@router.post("/push/inscrever")
async def push_inscrever(body: Inscricao, _u: dict = Depends(_dono)):
    try:
        webpush.inscrever(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "inscricoes": len(webpush.inscricoes())}


@router.post("/push/teste")
async def push_teste(_u: dict = Depends(_dono)):
    a = C.registrar_aviso("TESTE – aviso do JdB Laudo", "Se você está vendo isto, o aviso chega no navegador.")
    st = await asyncio.to_thread(webpush.enviar_todos, a["titulo"], a["corpo"])
    return {"enviados": st}


@router.get("/avisos")
async def avisos(_u: dict = Depends(_dono)):
    return {"avisos": C.lista_avisos()}


class AvisoMin(BaseModel):
    minutos: int = Field(ge=0, le=7 * 24 * 60)


@router.put("/configuracoes/aviso-visita")
async def config_aviso(body: AvisoMin, _u: dict = Depends(_dono)):
    db.set_setting("aviso_visita_min", str(body.minutos))
    return {"minutos": body.minutos}


async def verificar_avisos() -> int:
    """Compromisso cuja hora do aviso chegou: aviso no app + push. Devolve quantos avisou."""
    n = 0
    for comp in C.avisos_vencidos():
        cli = C.obter(comp["cliente"]) or {"contexto": {}, "nome": ""}
        titulo = f"Hoje: {comp['descricao'] or 'visita'}"
        corpo = f"{cli['nome'] or cli['contexto'].get('solicitante_nome') or 'Cliente'} – {C.quando_legivel(comp['quando'])}"
        C.registrar_aviso(titulo, corpo, comp["cliente"])
        await asyncio.to_thread(webpush.enviar_todos, titulo, corpo)
        C.marcar_avisado(comp["id"])
        n += 1
    return n


async def _laco_avisos() -> None:
    while True:
        try:
            await verificar_avisos()
        except Exception:
            log.exception("agendador de avisos")
        await asyncio.sleep(30)


@router.on_event("startup")
async def _iniciar_avisos() -> None:
    asyncio.get_event_loop().create_task(_laco_avisos())


class Resposta(BaseModel):
    id: str = Field(pattern="^(base|objeto|data|decide|padrao|idade)$")
    resposta: str = Field(default="", max_length=120)
    texto: str = Field(default="", max_length=120)      # nome da parte ("Galpão 01")


def _aplicar(jid: str, pid: str, resposta: str, texto: str = "") -> str:
    from . import datas_fotos
    from .agentes import _comum, selecao
    if pid in ("padrao", "idade"):        # L200: resposta do avaliador (da vistoria), vira dado do imóvel
        from .modelos import Campo
        if not (resposta or "").strip():
            raise HTTPException(status_code=400, detail="escolha uma opção")
        nome = "padrao_construtivo" if pid == "padrao" else "idade_aparente"
        db.salvar_campos(jid, [Campo(nome=nome, valor=resposta.strip()[:60], origem="vistoria",
                                     fonte="avaliador (vistoria)")])
        return f"{'padrão construtivo' if pid == 'padrao' else 'idade aparente'} do avaliando: {resposta.strip()}"
    if pid == "base":
        base = "terreno" if "terreno" in resposta.lower() else "construida"
        ops = selecao.opcoes_area(jid)[base]
        if not ops:
            raise HTTPException(status_code=409, detail="nenhuma área dessa base nos dados do imóvel")
        op = next((o for o in ops if o.get("sugerida")), ops[0])     # a do imóvel avaliado
        selecao.gravar_escolha_area(jid, base, op["campo"])
        return f"base do cálculo: {selecao.ROTULO_BASE[base]} ({op['campo']})"
    if pid == "objeto":
        t = _comum.trabalho(jid)
        parte = "" if "inteiro" in resposta.lower() else (texto.strip() or "parte")
        db.atualizar_dados(jid, t.model_copy(update={"objeto_parte": parte}))
        db.set_setting(f"objeto:{jid}", "inteiro" if not parte else "parte")   # 073-1: a resposta fica guardada
        return "objeto: imóvel inteiro" if not parte else f"objeto: só {parte}"
    if pid == "data":
        dv = str((db.job(jid)["dados"] or {}).get("data_vistoria") or "")[:10]
        if "certa" in resposta.lower() and dv:
            db.set_setting(datas_fotos.chave_confirmada(jid), dv)
            return f"data da vistoria {dv} confirmada"
        return "data da vistoria a corrigir nos dados do trabalho"
    raise HTTPException(status_code=400)


def _unit(c) -> float | None:
    return c.preco / c.area_m2 if c.preco and c.area_m2 else None


def _cv(refs) -> float | None:
    import statistics
    us = [u for u in (_unit(c) for c in refs) if u]
    return statistics.pstdev(us) / statistics.mean(us) * 100 if len(us) >= 2 else None


def _janela(refs: list, n: int) -> list:
    com = sorted([c for c in refs if _unit(c)], key=_unit)
    if len(com) <= n:
        return com
    janelas = [com[i:i + n] for i in range(len(com) - n + 1)]
    return min(janelas, key=lambda j: (round(_cv(j) or 0, 1), -sum(c.pontos or 0 for c in j)))


def _mais_homogeneos(pool: list, n: int) -> list:
    """L200: entre os mais parecidos, os `n` de R$/m² mais próximos entre si (menor CV); empate: mais pontos.
    Primeiro só entre os anúncios já abertos (foto e prova); se não der CV até 15%, mistura com os outros."""
    abertos = [c for c in pool if c.foto]
    if len(abertos) >= n:
        j = _janela(abertos, n)
        if (_cv(j) or 0) <= 15:
            return j
    return _janela(pool, n)


@router.post("/jobs/{jid}/alinhamento")
async def responder_alinhamento(jid: str, body: Resposta, _u: dict = Depends(_dono)):
    """Resposta de um ponto, ou "decide você" (D-063): o sistema aplica a recomendação de cada
    ponto, marca os referenciais ★ (os mais parecidos, até 5) e registra o porquê de cada escolha.
    Depois o avaliador confirma o valor (ou o sistema segue, se ele mandar seguir)."""
    from .routes import _job
    _job(jid)
    if body.id != "decide":
        feito = _aplicar(jid, body.id, body.resposta, body.texto)
        db.evento(jid, "selecao", "edicao_manual", f"alinhamento: {feito}")
        return await alinhamento(jid, _u=_u)
    ali = await alinhamento(jid, _u=_u)
    feitos = []
    for p in ali["pontos"]:
        if p.get("recomendada") is None:
            continue                     # L200: padrão e idade do avaliando são do avaliador, o sistema não decide
        feitos.append(_aplicar(jid, p["id"], p["recomendada"]))
    # F-K021 (D-063): já existe escolha do avaliador para este imóvel -> mantém o critério dele;
    # senão: tira contraditórios e cartão = terreno, e completa até 5 com os mais parecidos
    sel = db.resultado(jid, "selecao") or {}
    ja = [r["n"] for r in sel.get("refs") or [] if r.get("escolhido")]
    cands = db.candidatos(jid)
    if ja:
        rec = [c for c in cands if c.n in ja]
        criterio = "mantidos os referenciais já escolhidos pelo avaliador para este imóvel (F-K021)"
    else:
        def ruim(c):
            o = (c.observacao or "").upper()
            # L200: o "fora da curva" da lista usa a mediana de TODOS os anúncios (os novos e de padrão alto puxam);
            # aqui ele não barra: a homogeneidade é a da amostra escolhida (CV até 15%), sem os que destoam
            curva = (c.motivo or "").startswith("preço fora da curva")
            return (c.nao_recomendado and not curva) or c.decisao == "descarta" or "CONTRADIT" in o or "TERRENO" in o
        from . import candidatos as Cand
        from .agentes import pesquisa
        av = pesquisa.avaliando(jid)

        def destoa(c):       # L200/L201-3: padrão superior ou mais novo que o avaliando (regra 6) — a mesma da lista
            return bool(Cand.destoa(c, av))
        def grupo(c):        # o mesmo imóvel em portais diferentes: mesma área e mesmo preço
            return (round(c.area_m2), int(round(c.preco, -3))) if c.area_m2 and c.preco else ("n", c.n)
        # se a leitura de UM dos anúncios do imóvel achou padrão alto ou novo, o imóvel todo fica de fora
        fora = {grupo(c) for c in cands if destoa(c)}
        classe = Cand.tipologia_classe(av.tipo)
        # L200: só a mesma tipologia do avaliando (sobrado com sobrado); tipologia que o anúncio não diz não barra
        mesma = lambda c: Cand.tipologia_classe(c.tipologia or "") in (classe, "")
        boas = [c for c in cands if not ruim(c) and grupo(c) not in fora and mesma(c)]
        pool, vistos = [], set()
        # L200: os mais parecidos primeiro (★ e pontos); o mesmo imóvel dos portais entra uma vez só
        # o anúncio já aberto (foto e prova, padrão e idade lidos) vem antes do que só tem o cartão da busca
        for c in sorted(boas, key=lambda c: (not c.foto, not c.recomendado, -(c.pontos or 0), c.n)):
            k = grupo(c)
            if k in vistos:
                continue
            vistos.add(k)
            pool.append(c)
        pool = pool[:10]
        rec = _mais_homogeneos(pool, 5)
        criterio = ("os mais parecidos, sem anúncio contraditório nem área de terreno, sem repetir o mesmo imóvel e sem "
                    "padrão alto ou imóvel novo para um avaliando que não é (D-056, D-010, F-S003)")
        novos = [c.model_copy(update={"decisao": "entra", "justificativa": (c.justificativa or "")
                                      + ("; " if c.justificativa else "") + "escolhido pelo sistema: "
                                      + (c.motivo or "mais parecido da lista")}) for c in rec]
        db.salvar_candidatos(jid, novos)
    porque = "; ".join(feitos + [f"referenciais nº {', '.join(str(c.n) for c in rec)} ({criterio})"])
    cv = _cv(rec)
    if not ja and cv is not None:        # L200: a amostra mais homogênea entre os 10 mais parecidos (CV até 15%)
        porque += f"; CV da amostra {cv:.1f}%" + (" — acima de 15%: troque ou acrescente referenciais" if cv > 15 else "")
    if not ja and len(rec) < 5:          # L200: falta referencial da mesma tipologia: diz quantos, não completa com outra
        porque += (f"; só {len(rec)} da mesma tipologia e padrão do avaliando: faltam {5 - len(rec)} "
                   "(pesquise em bairros vizinhos no seu Chrome e envie com a extensão, ou cadastre à mão)")
    db.evento(jid, "selecao", "edicao_manual", f"o avaliador pediu \"decide você\": {porque}")
    return {**(await alinhamento(jid, _u=_u)), "decidido": porque, "escolhidos": [c.n for c in rec]}


# ------------------------------------------------------------------ ORDEM 045 / D-100: pendências simples
@router.get("/jobs/{jid}/pendencias-simples")
async def pendencias_simples(jid: str, _u: dict = Depends(_dono)):
    from . import pendencias_simples as PS
    from .routes import _job
    _job(jid)
    ent = db.resultado(jid, "entrega") or {}
    return PS.classificar(jid, ent.get("pendencias") or [])


class Aceite(BaseModel):
    chave: str = Field(max_length=120)


@router.post("/jobs/{jid}/pendencias/aceitar")
async def aceitar_pendencia(jid: str, body: Aceite, _u: dict = Depends(_dono)):
    """"Seguir sem foto", "Seguir assim": a decisão do avaliador fica registrada e o cartão some."""
    from . import pendencias_simples as PS
    from .routes import _job
    _job(jid)
    import json as _json
    ja = body.chave in set(_json.loads(db.setting(PS.CHAVE_ACEITAS.format(jid)) or "[]"))
    PS.aceitar(jid, body.chave)
    if not ja:                                  # 162-2: toque em dobro (duas abas) não registra duas vezes
        db.evento(jid, "entrega", "info", f"pendência aceita pelo avaliador: {body.chave}")
    return await pendencias_simples(jid, _u=_u)


@router.post("/jobs/{jid}/corrigir-sozinho")
async def corrigir_sozinho(jid: str, _u: dict = Depends(_dono)):
    """Erros do sistema: remonta o laudo SEM IA (montagem, planilha, PDF, coerência e dossiê) e
    mantém as pendências que são do avaliador. Nada de redação nova."""
    from . import orquestrador as O
    from . import pendencias_simples as PS
    from .routes import _livre
    _livre(jid)
    ent = db.resultado(jid, "entrega") or {}
    antes = PS.classificar(jid, ent.get("pendencias") or [])
    # a coerência roda de novo (conta, sem IA); a contestação anterior é mantida (não chama a IA)
    manter = [p for p in ent.get("pendencias") or [] if p.get("texto") not in antes["sozinho"]
              and p.get("texto") not in antes["descartadas"]
              and not str(p.get("texto") or "").startswith("conferência de coerência")]
    # da contestação, só os pontos da última rodada (sem repetir rodadas antigas)
    atuais = {pt.get("ponto", "") for pt in (ent.get("contestacao") or {}).get("pontos", [])}
    manter = [p for p in manter if not str(p.get("texto") or "").startswith("contestação simulada")
              or any(a and a in p["texto"] for a in atuais)]
    pp = O._Pipeline(jid)
    pp.r = pp._resultado()
    await pp._montagem()
    await pp._conferencias(contestar=False)
    if ent.get("contestacao"):
        pp.extra["contestacao"] = ent["contestacao"]
    for p in manter:
        pp.pendencia(p["texto"], grave=bool(p.get("grave")))
    status = pp._entregar(None)
    db.evento(jid, "entrega", "info", f"corrigido sozinho (sem IA): {len(antes['sozinho'])} ajustes de montagem")
    return {"status": status, **(await pendencias_simples(jid, _u=_u))}


# ------------------------------------------------------------------ ORDEM 053 (L9 e L10): imagens das telas
@router.get("/jobs/{jid}/candidatos/{n}/foto")
async def foto_candidato(jid: str, n: int, _u: dict = Depends(_dono)):
    """Foto principal do anúncio (L9). Só arquivo de dentro da pasta do trabalho."""
    from fastapi.responses import FileResponse
    from .routes import _job
    _job(jid)
    c = next((x for x in db.candidatos(jid) if x.n == n), None)
    if c is None or not c.foto or c.foto.startswith(("http:", "https:")):
        raise HTTPException(status_code=404)
    base = db.pasta(jid).resolve()
    p = (base / c.foto).resolve()
    if not p.is_file() or not p.is_relative_to(base):
        raise HTTPException(status_code=404)
    return FileResponse(p)


def _dentro_do_trabalho(jid: str, caminho: str):
    """Arquivo existente e de dentro da pasta do trabalho (senão 404)."""
    base = db.pasta(jid).resolve()
    p = (base / caminho).resolve()
    if not caminho or not p.is_file() or not p.is_relative_to(base):
        raise HTTPException(status_code=404)
    return p


@router.get("/jobs/{jid}/documentos")
async def documentos_trabalho(jid: str, _u: dict = Depends(_dono)):
    """ORDEM 059 (L13): arquivos enviados, com o tipo que a leitura dos documentos detectou
    (`rotulo`, vazio se ainda não leu) e a data em que o arquivo chegou ao sistema."""
    from .routes import _job
    _job(jid)
    ext = db.resultado(jid, "extracao") or {}
    rot = {d.get("arquivo"): d.get("rotulo_curto") or "" for d in ext.get("documentos") or [] if isinstance(d, dict)}
    desc = {d.get("arquivo"): d.get("motivo") or "" for d in ext.get("documentos_descartados") or [] if isinstance(d, dict)}
    base = db.pasta(jid)
    out = []
    for a in db.arquivos(jid):
        try:
            recebido = datetime.fromtimestamp((base / a["caminho"]).stat().st_mtime).date().isoformat()
        except OSError:
            recebido = ""
        out.append({"nome": a["nome"], "tipo": a["tipo"], "caminho": a["caminho"], "rotulo": rot.get(a["caminho"], ""),
                    "descartado": desc.get(a["caminho"], ""), "recebido": recebido})
    return out


@router.get("/jobs/{jid}/anuncios")
async def anuncios_analisados(jid: str, _u: dict = Depends(_dono)):
    """ORDEM 059 (L13): os anúncios analisados como no dossiê de pesquisa (D-085): escolhidos e
    descartados com o motivo, a data e hora de acesso e se há prova guardada (D-082)."""
    import asyncio
    from . import dossie
    from .routes import _job
    j = _job(jid)
    regs = await asyncio.to_thread(dossie.registros, jid)
    base = db.pasta(jid).resolve()

    def tem(c: str) -> bool:
        try:
            p = (base / c).resolve()
            return bool(c) and p.is_file() and p.is_relative_to(base)
        except (OSError, ValueError):
            return False
    pdf = db.pasta(jid) / "provas" / f"dossie_pesquisa_{j['numero']}.pdf"
    fotos = {c.n: {"foto": c.foto, "fotos_url": list(getattr(c, "fotos_url", []) or []),          # 173: fotos à mostra
                   "foto_url_escolhida": c.foto_url_escolhida, "foto_avaliador": c.foto_avaliador,
                   "foto_arte": bool(getattr(c, "foto_arte", False))} for c in db.candidatos(jid)}
    return {"anuncios": [{k: r[k] for k in ("n", "link", "portal", "preco", "area_m2", "unitario", "acessado_em",
                                           "escolhido", "motivos")} | {"tem_prova": tem(r["prova"])}
                         | fotos.get(r["n"], {}) for r in regs],
            "dossie": pdf.is_file()}


@router.get("/jobs/{jid}/anuncios/{n}/prova")
async def prova_anuncio(jid: str, n: int, _u: dict = Depends(_dono)):
    """Prova do anúncio nº n (captura com data, hora e link — D-082)."""
    from fastapi.responses import FileResponse
    from . import dossie
    from .routes import _job
    _job(jid)
    r = next((x for x in dossie.registros(jid) if x["n"] == n), None)
    if r is None:
        raise HTTPException(status_code=404)
    return FileResponse(_dentro_do_trabalho(jid, r["prova"]))


@router.get("/jobs/{jid}/dossie.pdf")
async def dossie_pdf(jid: str, _u: dict = Depends(_dono)):
    """Dossiê de pesquisa do trabalho (D-085), se já foi gerado."""
    from fastapi.responses import FileResponse
    from .routes import _job
    j = _job(jid)
    p = _dentro_do_trabalho(jid, f"provas/dossie_pesquisa_{j['numero']}.pdf")
    return FileResponse(p, filename=p.name)


@router.get("/jobs/{jid}/capa-pdf.png")
async def capa_pdf(jid: str, _u: dict = Depends(_dono)):
    """Miniatura da 1ª página do PDF do laudo (L10). Gerada uma vez por PDF e guardada."""
    import asyncio
    from fastapi.responses import FileResponse
    from .routes import _job
    _job(jid)
    ent = db.resultado(jid, "entrega") or {}
    pdfs = [a for a in ent.get("arquivos") or [] if a.lower().endswith(".pdf") and "_assinado" not in a.lower()]
    if not pdfs:
        raise HTTPException(status_code=404)
    pdf = next((p for p in (db.pasta(jid) / pdfs[0], db.pasta(jid) / "entrega" / pdfs[0]) if p.is_file()), None)
    if pdf is None:
        raise HTTPException(status_code=404)
    png = db.pasta(jid) / "entrega" / "capa-miniatura.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    if not png.is_file() or png.stat().st_mtime < pdf.stat().st_mtime:
        def _gerar():
            import pymupdf
            with pymupdf.open(pdf) as d:
                d[0].get_pixmap(dpi=60).save(png)
        await asyncio.to_thread(_gerar)
    return FileResponse(png, media_type="image/png")
