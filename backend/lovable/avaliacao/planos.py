"""ORDEM 040 / D-087: planos e cobrança do sistema web — SÓ LOCAL.

Proibido aqui: meio de pagamento, publicação, cobrar alguém. A troca de plano é simulada.
Preços ficam na CONFIGURAÇÃO (av_settings "planos"), nunca fixos no código: os valores abaixo
são só o padrão inicial (tabela do Alan, 14/11/2026).

Regras:
- 155: "Laudo" que conta = trabalho cujo PRIMEIRO RASCUNHO (o 1º PDF entregue) ficou pronto. Uma vez por
  trabalho; correções, revisão humana, novas versões e [Aprovar] não contam de novo. Trabalho apagado depois
  do 1º rascunho continua contado. O mês é o do 1º rascunho. Trabalho de teste (cliente "TESTE", cópia de
  teste, ou marcado "teste" no servidor) não conta.
- 156: conta SEM LIMITE (o dono do sistema) fica numa lista do servidor ("sem_limite"), nunca pela tela/API:
  não bloqueia nem cobra; a contagem dele é só medição. Os demais nascem no plano padrão (com limite).
- Primeiro laudo grátis, uma vez por avaliador (o 1º laudo da vida dele).
- Conta do mês = preço do plano + extras × preço do extra.
- Aviso de economia: quando a conta do mês chega a 85% ou mais do preço do plano de cima; o texto
  sai da conta real do mês (nunca inventada)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from . import db

PADRAO = {
    "ordem": ["avulso", "entrada", "profissional"],
    "planos": {
        "avulso": {"nome": "Avulso", "preco": 0, "incluidos": 0, "extra": 49},
        "entrada": {"nome": "Entrada", "preco": 149, "incluidos": 5, "extra": 39},
        "profissional": {"nome": "Profissional", "preco": 249, "incluidos": 10, "extra": 39, "destaque": True},
    },
    "limiar_aviso": 0.85,
    # custos para o painel "Margem" (A CONFIRMAR com o Danilo: servidor e câmbio reais)
    "custo_servidor_usd_por_laudo": 0.10,
    "cotacao_usd_brl": 5.50,
    "laudos_para_medir": 20,
}
_TESTE = ("TESTE", "CÓPIA DE TESTE", "COPIA DE TESTE")


def config() -> dict:
    try:
        c = json.loads(db.setting("planos") or "{}")
    except ValueError:
        c = {}
    out = json.loads(json.dumps(PADRAO))
    for k, v in c.items():
        if k == "planos" and isinstance(v, dict):
            for p, d in v.items():
                out["planos"].setdefault(p, {}).update(d)
        else:
            out[k] = v
    return out


def gravar_config(c: dict) -> dict:
    db.set_setting("planos", json.dumps(c, ensure_ascii=False))
    return config()


def plano_de(avaliador_id: str) -> str:
    p = db.setting(f"plano:{avaliador_id}") or "avulso"
    return p if p in config()["planos"] else "avulso"


def trocar(avaliador_id: str, plano: str) -> str:
    """Troca SIMULADA (sem cobrança): só muda o plano usado na conta dos próximos meses."""
    if plano not in config()["planos"]:
        raise ValueError("plano inexistente")
    db.set_setting(f"plano:{avaliador_id}", plano)
    return plano


# ------------------------------------------------------------------ conta
def _rs(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def brl(v) -> str:
    return "R$ " + f"{_rs(v):,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


@dataclass
class Conta:
    plano: str
    laudos: int          # laudos aprovados no mês (inclui o grátis)
    gratis: int          # 0 ou 1
    incluidos: int
    extras: int
    preco_plano: Decimal
    total: Decimal

    def dict(self) -> dict:
        c = config()["planos"][self.plano]
        return {"plano": self.plano, "nome": c["nome"], "limite": int(c["incluidos"]), "laudos": self.laudos, "gratis": self.gratis,
                "incluidos": self.incluidos, "extras": self.extras, "preco_plano": float(self.preco_plano),
                "preco_extra": float(c["extra"]), "total": float(self.total)}


def conta(plano: str, laudos: int, gratis: int = 0) -> Conta:
    p = config()["planos"][plano]
    cobrados = max(0, laudos - gratis)
    inc = min(cobrados, int(p["incluidos"]))
    extras = max(0, cobrados - int(p["incluidos"]))
    total = _rs(p["preco"]) + extras * _rs(p["extra"])
    return Conta(plano, laudos, gratis, inc, extras, _rs(p["preco"]), total)


def acima(plano: str) -> str | None:
    o = config()["ordem"]
    i = o.index(plano)
    return o[i + 1] if i + 1 < len(o) else None


def aviso_economia(c: Conta) -> dict | None:
    """Aviso para subir de plano, com os números reais do mês. None = não mostrar."""
    cfg = config()
    prox = acima(c.plano)
    if prox is None or c.laudos == 0:
        return None
    pn = cfg["planos"][prox]
    if c.total < _rs(pn["preco"]) * Decimal(str(cfg["limiar_aviso"])):
        return None
    alt = conta(prox, c.laudos, c.gratis)
    atual_nome = cfg["planos"][c.plano]["nome"]
    base = f"Este mês você pagou {brl(c.total)} no {atual_nome}."
    if alt.total < c.total:
        txt = (f"{base} No {pn['nome']}, teria pago {brl(alt.total)} com {pn['incluidos']} laudos incluídos: "
               f"economia de {brl(c.total - alt.total)}.")
        tipo = "economia"
    elif alt.total > c.total:
        inc_atual = int(cfg["planos"][c.plano]["incluidos"])
        txt = (f"{base} Por {brl(alt.total - c.total)} a mais, no {pn['nome']} você teria "
               f"{pn['incluidos']} laudos incluídos ({pn['incluidos'] - inc_atual} a mais).")
        tipo = "mais_incluidos"
    else:
        txt = f"{base} No {pn['nome']}, pelo mesmo valor, teria {pn['incluidos']} laudos incluídos."
        tipo = "mesmo_valor"
    return {"para": prox, "nome": pn["nome"], "tipo": tipo, "texto": txt,
            "total_atual": float(c.total), "total_no_plano": float(alt.total)}


# ------------------------------------------------------------------ laudos aprovados
def _eh_teste(job: dict) -> bool:
    d = job.get("dados") or {}
    cli = str(d.get("cliente") or "").upper()
    ctx = str(d.get("contexto") or "").upper()
    return (any(x in cli for x in _TESTE) or "CÓPIA DE TESTE" in ctx or "COPIA DE TESTE" in ctx
            or int(job.get("numero") or 0) < 0 or bool(db.setting(f"teste:{job.get('id')}")))
    # (a marca antiga "job_teste:" é da NUMERAÇÃO de teste — o nº 1 a tem — e não quer dizer trabalho de teste)


def marcar_teste(job_id: str) -> None:
    """155-3: cópia/trabalho de teste fica fora da contagem, da cobrança e da medição de custo."""
    db.set_setting(f"teste:{job_id}", "1")


def sem_limite(avaliador_id: str) -> bool:
    """156: lista do SERVIDOR (av_settings "sem_limite"); só o dono a muda, direto no servidor."""
    try:
        lista = json.loads(db.setting("sem_limite") or "[]")
    except ValueError:
        lista = []
    return avaliador_id in lista


def _primeiro_rascunho(job_id: str) -> str | None:
    with db._conn() as c:
        r = c.execute("SELECT ts FROM av_events WHERE job=? AND etapa='entrega' AND nivel='resultado' "
                      "ORDER BY id LIMIT 1", (job_id,)).fetchone()
    return r[0] if r else None


def rascunhos(avaliador_id: str) -> list[dict]:
    """155: [{job, numero, mes 'AAAA-MM', data}] — 1 por trabalho, no 1º rascunho; sem testes. Trabalho na Lixeira
    continua contado (apagar não desconta)."""
    out = []
    for j in db.listar_jobs():
        dono = (j.get("dados") or {}).get("avaliador_id") or "AV-0001"
        if dono != avaliador_id or _eh_teste(j):
            continue
        ts = _primeiro_rascunho(j["id"])
        if ts:
            out.append({"job": j["id"], "numero": j["numero"], "data": ts, "mes": ts[:7]})
    return sorted(out, key=lambda x: x["data"])


aprovacoes = rascunhos      # nome antigo (quem chamava "aprovacoes" passa a ver a contagem nova)


def extra_antes_de_comecar(job_id: str, agora: datetime | None = None) -> dict | None:
    """155-1: ANTES de a IA começar — o trabalho ainda sem rascunho vai contar como laudo EXTRA (o plano não tem mais
    laudo incluído no mês)? Devolve {preco, texto} para avisar; None = pode começar. Dono sem limite: sempre None."""
    j = db.job(job_id)
    av = (j.get("dados") or {}).get("avaliador_id") or "AV-0001"
    if _eh_teste(j) or _primeiro_rascunho(job_id):
        return None
    return extra_para_avaliador(av, agora)


def extra_para_avaliador(av: str, agora: datetime | None = None) -> dict | None:
    """155-1: um trabalho NOVO deste avaliador contaria como laudo extra? (dono sem limite: nunca)"""
    if sem_limite(av):
        return None
    plano = plano_de(av)
    p = config()["planos"][plano]
    feitos = rascunhos(av)
    mes = (agora or datetime.now(timezone.utc)).strftime("%Y-%m")
    no_mes = len([x for x in feitos if x["mes"] == mes])
    gratis = 0 if feitos else 1                                    # o 1º laudo da vida é grátis
    if no_mes < int(p["incluidos"]) + gratis:
        return None
    preco = brl(p["extra"])
    return {"preco": float(_rs(p["extra"])),
            "texto": f"Seu plano {p['nome']} não tem mais laudo incluído este mês. Este trabalho conta como laudo extra "
                     f"({preco}) quando o primeiro rascunho ficar pronto. Quer começar assim mesmo?"}


def aprovar(job_id: str, quem: str = "avaliador") -> dict:
    """Registra o "Aprovar" do PDF final (uma vez por trabalho). 155: não conta mais no plano (conta o 1º rascunho)."""
    with db._conn() as c:
        ja = c.execute("SELECT ts FROM av_events WHERE job=? AND etapa='entrega' AND nivel='aprovado'",
                       (job_id,)).fetchone()
    if ja:
        return {"aprovado_em": ja[0], "novo": False}
    db.evento(job_id, "entrega", "aprovado", f"PDF final aprovado pelo {quem}")
    # ORDEM 042 (D-094): o 1º laudo aprovado de cada modalidade vira o modelo do avaliador
    j = db.job(job_id)
    av = (j.get("dados") or {}).get("avaliador_id") or "AV-0001"
    mod = (j.get("dados") or {}).get("modalidade") or "OV"
    if not db.setting(f"modelo:{av}:{mod}"):
        db.set_setting(f"modelo:{av}:{mod}", job_id)
    with db._conn() as c:
        ts = c.execute("SELECT ts FROM av_events WHERE job=? AND etapa='entrega' AND nivel='aprovado'",
                       (job_id,)).fetchone()[0]
    return {"aprovado_em": ts, "novo": True}


def meses(avaliador_id: str) -> list[dict]:
    """Conta de cada mês com laudo (1º rascunho; o grátis cai no mês do 1º laudo da vida)."""
    aps = rascunhos(avaliador_id)
    plano = plano_de(avaliador_id)
    por: dict[str, list] = {}
    for a in aps:
        por.setdefault(a["mes"], []).append(a)
    primeiro = aps[0]["mes"] if aps else None
    out = []
    for mes in sorted(por):
        c = conta(plano, len(por[mes]), 1 if mes == primeiro else 0)
        d = {"mes": mes, **c.dict(), "aviso": aviso_economia(c), "laudos_lista": [x["numero"] for x in por[mes]]}
        if sem_limite(avaliador_id):           # 156: dono — só medição, sem cobrança nem aviso de plano
            d.update(total=0.0, extras=0, aviso=None, sem_limite=True)
        out.append(d)
    return out


def mes_atual(avaliador_id: str, agora: datetime | None = None) -> dict:
    mes = (agora or datetime.now(timezone.utc)).strftime("%Y-%m")
    m = next((x for x in meses(avaliador_id) if x["mes"] == mes), None)
    if m is None:
        c = conta(plano_de(avaliador_id), 0, 0)
        m = {"mes": mes, **c.dict(), "aviso": None, "laudos_lista": []}
        if sem_limite(avaliador_id):
            m.update(total=0.0, sem_limite=True)
    return m


# ------------------------------------------------------------------ margem (custo real de IA)
def custos_por_laudo() -> list[dict]:
    """Custo de IA por trabalho aprovado/entregue (todas as etapas), sem testes."""
    out = []
    with db._conn() as c:
        rows = c.execute("SELECT job, etapa, SUM(COALESCE(custo_usd,0)) FROM av_ia_chamadas GROUP BY job, etapa").fetchall()
    por: dict[str, dict] = {}
    for job, etapa, v in rows:
        por.setdefault(job, {})[etapa] = float(v or 0)
    for j in db.listar_jobs():
        if _eh_teste(j) or j["id"] not in por or not db.resultado(j["id"], "entrega"):
            continue
        etapas = por[j["id"]]
        out.append({"job": j["id"], "numero": j["numero"], "modalidade": (j.get("dados") or {}).get("modalidade"),
                    "custo_ia_usd": round(sum(etapas.values()), 4), "por_etapa": etapas})
    return out


def margem() -> dict:
    cfg = config()
    ls = custos_por_laudo()
    serv = float(cfg["custo_servidor_usd_por_laudo"])
    cot = float(cfg["cotacao_usd_brl"])
    medio = sum(x["custo_ia_usd"] for x in ls) / len(ls) if ls else 0.0
    caro = max(ls, key=lambda x: x["custo_ia_usd"]) if ls else None
    custo_brl = (medio + serv) * cot
    planos = []
    for k in cfg["ordem"]:
        p = cfg["planos"][k]
        receita = (p["preco"] / p["incluidos"]) if p["incluidos"] else p["extra"]
        planos.append({"plano": k, "nome": p["nome"], "receita_por_laudo": round(receita, 2),
                       "receita_extra": p["extra"], "custo_por_laudo_brl": round(custo_brl, 2),
                       "margem_por_laudo": round(receita - custo_brl, 2),
                       "margem_extra": round(p["extra"] - custo_brl, 2)})
    return {"laudos_medidos": len(ls), "minimo_para_medir": cfg["laudos_para_medir"],
            "provisorio": len(ls) < int(cfg["laudos_para_medir"]),
            "custo_medio_ia_usd": round(medio, 4), "custo_servidor_usd": serv, "cotacao": cot,
            "mais_caro": caro, "planos": planos, "laudos": ls}
