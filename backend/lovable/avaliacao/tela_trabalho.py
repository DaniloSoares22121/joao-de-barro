"""ORDEM 047 / D-101: resumo da tela do trabalho — a linha de etapas
Proposta → Contrato → Visita → Laudo → Assinatura, a etapa atual e o próximo passo em poucas
palavras (usado também na lista de trabalhos).

Trabalho ligado a um cliente (ORDEM 041): as três primeiras etapas vêm da conversa do cliente.
Trabalho aberto direto (sem cliente): proposta e contrato foram feitos fora do JdB; contam como
feitos quando a visita já aconteceu (data da vistoria até hoje). Nada é inventado: sem data de
vistoria, ficam "sem registro"."""
from __future__ import annotations

from datetime import date

from . import db

# 178-2: a assinatura saiu do sistema (o avaliador assina o PDF por fora); "Laudo concluído ✓" é o fim do trabalho
ROTULOS = {"proposta": "Proposta", "contrato": "Contrato", "visita": "Visita", "laudo": "Laudo"}
ORDEM = list(ROTULOS)


def aprovado(job_id: str) -> bool:
    with db._conn() as c:
        return c.execute("SELECT 1 FROM av_events WHERE job=? AND etapa='entrega' AND nivel='aprovado' LIMIT 1",
                         (job_id,)).fetchone() is not None


def dados_alterados(job_id: str) -> bool:
    """Mesma regra de routes._dados_alterados: edição manual depois da última entrega."""
    with db._conn() as c:
        r = c.execute(
            "SELECT (SELECT MAX(id) FROM av_events WHERE job=? AND (nivel='edicao_manual' OR "
            "(etapa='selecao' AND nivel='resultado' AND json_extract(dados_json, '$.manual')))) AS ed, "
            "(SELECT MAX(id) FROM av_events WHERE job=? AND etapa='entrega' "
            "AND nivel='resultado') AS ent", (job_id, job_id)).fetchone()
    return bool(r["ed"] and r["ent"] and r["ed"] > r["ent"])


def _cliente(job_id: str) -> dict | None:
    try:
        from . import conversa
        with db._conn() as c:
            r = c.execute("SELECT id FROM av_clientes WHERE job_id=? LIMIT 1", (job_id,)).fetchone()
        return conversa.obter(r[0]) if r else None
    except Exception:
        return None


def _visita_feita(dados: dict) -> bool:
    v = str(dados.get("data_vistoria") or "")[:10]
    try:
        return bool(v) and date.fromisoformat(v) <= date.today()
    except ValueError:
        return False


def resumo(job: dict) -> dict:
    """{"etapas": [{etapa, rotulo, status}], "atual": etapa, "proximo": texto curto,
    "aprovado": bool, "assinado": bool}. status: feito | fora | atual | espera | falta | sem_registro."""
    from . import orquestrador as O
    jid = job["id"]
    dados = job.get("dados") or {}
    ent = db.resultado(jid, "entrega") or {}
    assinado = bool(ent.get("assinado"))
    ok = aprovado(jid)
    st, etapa = job.get("status") or "", job.get("etapa") or ""

    cli = _cliente(jid)
    if cli is not None:
        from . import conversa
        antes = {e["etapa"]: (e["status"] if e["status"] in ("feito", "fora") else "pendente") for e in conversa.etapas(cli)[:3]}
    else:
        # ORDEM 056: sem cliente no JdB, proposta e contrato foram feitos fora dele — "fora", sem ✓.
        # A visita só ganha ✓ se as fotos da vistoria estão no JdB (é o registro que existe).
        passou = _visita_feita(dados)
        fotos = any(a.get("tipo") == "foto" for a in db.arquivos(jid))
        antes = {"proposta": "fora" if passou else "sem_registro", "contrato": "fora" if passou else "sem_registro",
                 "visita": "feito" if fotos else ("fora" if passou else "sem_registro")}

    # laudo
    if assinado or ok:
        laudo, assin, atual, prox = "feito", "feito", "laudo", "Laudo concluído ✓"
    else:
        assin, atual, laudo = "espera", "laudo", "atual"
        if st == O.CANCELADO:
            prox = "Cancelado"
        elif st == O.ERRO_TECNICO:
            prox = "Tentar de novo"
        elif st == O.AGUARDANDO and etapa == "pesquisa":
            prox = "Escolher referenciais"
        elif st == O.AGUARDANDO:
            prox = "Confirmar o valor"
        elif st in (O.PRONTO, O.PARCIAL) and dados_alterados(jid):
            prox = "Atualizar o laudo"
        elif st == O.BLOQUEADO:
            prox = "Resolver uma pendência"
        elif st == O.PARCIAL:
            prox = "Resolver pendências"
        elif st == O.PRONTO:
            prox = "Baixar para a revisão humana"   # 172: o download conclui
        elif etapa == "nova" and st == "pendente":
            prox = "Enviar arquivos e iniciar"
        else:
            prox = "O JdB está montando"
    est = dict(antes, laudo=laudo, assinatura=assin)
    # trabalho ainda não iniciado e visita não feita: a etapa atual é a visita
    if etapa == "nova" and st == "pendente" and est["visita"] not in ("feito", "fora"):
        est["visita"], est["laudo"], atual = "atual", "espera", "visita"
        prox = "Fazer a visita" if cli is not None and not _visita_feita(dados) else prox
    for k in ("proposta", "contrato", "visita"):
        if est[k] == "pendente":
            est[k] = "falta"           # etapa do cliente que ficou para trás (a conversa mostra o quê)
    return {"etapas": [{"etapa": k, "rotulo": ROTULOS[k], "status": est[k]} for k in ORDEM],
            "atual": atual, "proximo": prox, "aprovado": ok, "assinado": assinado,
            "cliente_id": (cli or {}).get("id", ""), "revisao": _revisao(jid),
            "por_que": _por_que(jid) if O.ocupado(jid) else "",          # 111-3d: refazendo sozinho, por quê
            "fotos_novas": int(db.setting(f"fotos_novas:{jid}") or 0)}


def _por_que(job_id: str) -> str:
    try:
        from .revisoes import motivo_agora
        return motivo_agora(job_id)
    except Exception:       # noqa: BLE001 — a explicação nunca derruba a tela
        return ""


def _revisao(job_id: str) -> int:
    """Quantas vezes o laudo foi entregue (L10: "REVISÃO 1", "REVISÃO 2"…)."""
    with db._conn() as c:
        n = c.execute("SELECT COUNT(*) FROM av_events WHERE job=? AND etapa='entrega' "
                      "AND nivel IN ('resultado', 'resultado_anterior')", (job_id,)).fetchone()[0]
    # 077: as entregas anteriores ficam "arquivadas" e contam; entrega de antes da numeração (D-073) é descontada
    return max(0, n - int(db.setting(f"revisao_base:{job_id}") or 0))
