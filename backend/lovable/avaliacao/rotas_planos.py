"""ORDEM 040 / D-087: rotas de planos, "Meu plano", margem e "Aprovar" o PDF final. Só local:
nada de pagamento nem cobrança (troca de plano simulada)."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from . import planos
from .routes import _dono, _job, router

AV = "AV-0001"   # instalação local: o Alan (a ORDEM 042 traz outros avaliadores)


def _av(u: dict) -> str:
    return (u or {}).get("avaliador_id") or AV


@router.get("/planos")
async def ver_planos(_u: dict = Depends(_dono)):
    c = planos.config()
    return {"ordem": c["ordem"], "planos": c["planos"], "atual": planos.plano_de(_av(_u)),
            "comparacao_avulso_10": float(planos.conta("avulso", 10).total)}


@router.get("/planos/publico")
async def planos_publico():
    """ORDEM 053 (S1/S2): a página pública mostra os planos sem login — só nome, preço e
    quantidades (nada de avaliador, conta ou custo)."""
    c = planos.config()
    pub = {k: {x: v[x] for x in ("nome", "preco", "incluidos", "extra") if x in v} | {"destaque": bool(v.get("destaque"))}
           for k, v in c["planos"].items()}
    return {"ordem": c["ordem"], "planos": pub, "comparacao_avulso_10": float(planos.conta("avulso", 10).total)}


class Troca(BaseModel):
    plano: str


@router.post("/planos/trocar")
async def trocar_plano(body: Troca, _u: dict = Depends(_dono)):
    """Troca SIMULADA: sem cobrança e sem pagamento (etapa 5, com o Danilo)."""
    try:
        return {"atual": planos.trocar(_av(_u), body.plano), "simulado": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/meu-plano")
async def meu_plano(_u: dict = Depends(_dono)):
    av = _av(_u)
    return {"plano": planos.plano_de(av), "mes": planos.mes_atual(av), "historico": planos.meses(av),
            "sem_limite": planos.sem_limite(av),        # 156: "Conta do dono: sem limite."
            "regra": "Conta 1 laudo quando o primeiro rascunho fica pronto. Correções e novas versões do mesmo "
                     "trabalho não contam de novo."}


@router.get("/planos/margem")
async def ver_margem(_u: dict = Depends(_dono)):
    return planos.margem()


@router.post("/jobs/{jid}/aprovar")
async def aprovar(jid: str, _u: dict = Depends(_dono)):
    """"Aprovar" o PDF final: dá o ✓ de aprovado no trabalho (155: não conta mais no plano)."""
    from . import db, orquestrador
    _job(jid)
    ent = db.resultado(jid, "entrega") or {}
    if not any(a.lower().endswith(".pdf") for a in ent.get("arquivos") or []):
        raise HTTPException(status_code=409, detail="ainda não há PDF para aprovar")
    # 096-9: nunca aprova um PDF velho — com dado corrigido ou resposta guardada, primeiro atualiza o laudo
    from .routes import _dados_alterados
    if orquestrador.ocupado(jid) or _dados_alterados(jid) or orquestrador.remontagem_pendente(jid):
        raise HTTPException(status_code=409, detail="O laudo tem atualização pendente: toque em Atualizar o laudo "
                                                    "e aprove o PDF novo.")
    if ent.get("status") not in (orquestrador.PRONTO,):
        # ORDEM 047: laudo com pendências pode ser aprovado quando o avaliador já respondeu ou
        # aceitou todos os cartões dele (D-100); o que sobrou é ajuste de montagem do sistema
        from . import pendencias_simples as PS
        if ent.get("status") != orquestrador.PARCIAL or PS.classificar(jid, ent.get("pendencias") or [])["cards"]:
            raise HTTPException(status_code=409, detail="resolva as pendências antes de aprovar")
    return planos.aprovar(jid)


@router.post("/jobs/{jid}/concluir")
async def concluir_no_download(jid: str, _u: dict = Depends(_dono)):
    """172-2: [Baixar para a revisão humana] conclui o laudo — o avaliador faz as últimas mudanças no Word dele.
    Registra o ✓ (o mesmo que levava à Assinatura) uma vez; os pontos da revisão do sistema ficam à vista."""
    from . import db, orquestrador
    _job(jid)
    ent = db.resultado(jid, "entrega") or {}
    if not any(a.lower().endswith(".pdf") for a in ent.get("arquivos") or []):
        raise HTTPException(status_code=409, detail="o laudo ainda não está pronto para baixar")
    if orquestrador.ocupado(jid):
        raise HTTPException(status_code=409, detail="Espere o laudo terminar de montar para baixar.")
    return planos.aprovar(jid, quem="avaliador ao baixar para a revisão humana")
