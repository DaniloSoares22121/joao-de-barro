"""Rotas do João de Barro (/api/avaliacao/*, /ws/avaliacao/{id}) e do admin
(/api/admin/avaliacao/dono).

Acesso: o MESMO token do Brixly (Bearer HMAC) e o e-mail da conta tem de ser o
`av_settings["dono_email"]`. Sem dono configurado, tudo dá 403 (padrão seguro); quem define
o dono é o painel admin (`require_admin`, aplicado no include do main).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from lovable import auth

from . import aviso, db, ia, imagens, imagens_ia, orquestrador
from .modelos import Partes, Trabalho
from .plural import pl, sv

log = logging.getLogger("lovable")

router = APIRouter()
ws_router = APIRouter()
admin_router = APIRouter()


@router.on_event("startup")
async def _avaliacao_startup():
    """Registra a fonte de mercado real (Coletor), salvo se outra ja foi registrada."""
    from . import coletor_fonte, fichas, fonte_mercado
    if fonte_mercado._atual is None:
        fonte_mercado.registrar(coletor_fonte.ColetorFonte())
    try:   # ORDEM 026-F1: P3 + fichas-semente -> av_fichas (idempotente; editada na tela prevalece)
        fichas.importar_tudo()
    except Exception as e:  # noqa: BLE001 — base de conhecimento nunca derruba o servidor
        log.warning("fichas não importadas: %s", e)


@router.on_event("shutdown")
async def _avaliacao_shutdown():
    """Encerramento: falhas de IA a partir daqui (CLI morto) deixam o job retomável."""
    orquestrador.encerrar()

TIPOS = {"documento", "foto", "solicitante", "mapa_digital"}   # 077-1: o print do Mapa Digital Fácil
MAX_BYTES = 50 * 1024 * 1024      # por arquivo
MAX_REQUISICAO = 1024 ** 3          # corpo inteiro (o nginx deve barrar antes: client_max_body_size)
BLOCO = 1024 * 1024
INTERVALO_WS_S = 1.0


def _email_dono() -> str:
    try:
        return (db.setting("dono_email") or "").strip().casefold()
    except Exception:
        return ""


def _eh_dono(user: dict | None) -> bool:
    dono = _email_dono()
    return bool(user and not user.get("blocked") and dono
                and str(user.get("email") or "").strip().casefold() == dono)


# ORDEM 042: avaliador do pedido em curso (o dono da instalação é o Alan, AV-0001). Cada avaliador
# vê só os dados dele: _job() e as listas filtram por este código.
import contextvars  # noqa: E402
AV_ATUAL: contextvars.ContextVar[str] = contextvars.ContextVar("av_atual", default="AV-0001")


def av_atual() -> str:
    return AV_ATUAL.get()


def _modelo_laudo(j: dict) -> dict:
    """194-4: o modelo que o trabalho usa — o marcado pelo dono do trabalho para a modalidade dele."""
    from . import avaliadores as _A
    mod = str((j.get("dados") or {}).get("modalidade") or "OV")
    av = str((j.get("dados") or {}).get("avaliador_id") or "AV-0001")
    return {"modalidade": _A.NOME_SERVICO.get(_A._cod(mod), mod), "de": "seu" if _A.modelo_em_uso(av, mod) == "proprio" else "sistema"}


def dono_do_job(j: dict) -> str:
    return str((j.get("dados") or {}).get("avaliador_id") or "AV-0001")


async def _dono(authorization: str = Header(default="")) -> dict:
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    uid = auth.user_id_from_token(token) if token else None
    user = auth.get_user(uid) if uid else None
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    from . import avaliadores
    av = avaliadores.de_usuario(user) if not _eh_dono(user) else "AV-0001"
    if not av or user.get("blocked"):
        raise HTTPException(status_code=403, detail="Sem acesso")
    AV_ATUAL.set(av)
    return {**user, "avaliador_id": av}


def _ajustar_area_da_copia(nid: str) -> None:
    """159-2: a escolha de área copiada aponta para um campo pelo NOME; na cópia, a opção com o mesmo valor pode ter
    outro nome (valores repetidos aparecem uma vez só). Regrava a escolha com a opção da cópia de mesmo valor."""
    from .agentes import selecao
    esc = selecao.escolha_area(nid)
    if not esc:
        return
    ops = selecao.opcoes_area(nid).get(esc["base"]) or []
    if any(o["campo"] == esc["campo"] for o in ops):
        return
    igual = next((o for o in ops if abs(float(o["valor"]) - float(esc.get("valor") or 0)) < 0.005), None)
    if igual:
        selecao.gravar_escolha_area(nid, esc["base"], igual["campo"])
    else:
        db.set_setting(f"area_escolha:{nid}", "")       # sem opção igual: a cópia pede a escolha de novo


def _checar_extra(jid: str, aceito: bool) -> None:
    """155-1 / 156: plano sem laudo incluído no mês → 402 com o preço do extra, antes de gastar IA. O avaliador
    confirma (aceito_extra=1) e o trabalho começa; a confirmação fica guardada no trabalho."""
    from . import planos
    if db.setting(f"aceito_extra:{jid}"):
        return
    ex = planos.extra_antes_de_comecar(jid)
    if ex is None:
        return
    if not aceito:
        raise HTTPException(status_code=402, detail=ex["texto"])
    db.set_setting(f"aceito_extra:{jid}", "1")
    db.evento(jid, "orquestrador", "info", f"avaliador confirmou o laudo extra ({planos.brl(ex['preco'])}) antes de começar")


def _job(jid: str) -> dict:
    try:
        j = db.job(jid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Trabalho não encontrado")
    if j is None or dono_do_job(j) != av_atual():      # ORDEM 042: trabalho de outro avaliador
        raise HTTPException(status_code=404, detail="Trabalho não encontrado")
    return j


# ------------------------------------------------------------------ jobs
class DadosTrabalho(BaseModel):
    """Campos do Trabalho editáveis (todos menos id/numero)."""
    modalidade: Literal["OV", "AM", "AM_GARANTIA", "AMJ"]
    finalidade: str
    cliente: str
    tipo: str
    bairro: str
    cidade: str
    pin_maps: str
    data_base: date
    data_vistoria: date
    contexto: str = ""
    obs_vistoria: str = ""
    checklist_vistoria: str = ""
    data_emissao: date | None = None
    visita_por: str = Field(default="", max_length=200)   # D-043
    objeto_parte: str = Field(default="", max_length=120)  # ORDEM 032-2: vazio = imóvel inteiro
    processo_numero: str = ""
    vara_juizo: str = ""
    acao: str = ""
    partes: Partes | None = None
    quesitos: list[str] = []


class NovoTrabalho(DadosTrabalho):
    numero: int


CAMPO_VISTORIA = "Observações da vistoria"
_SO_CONTEXTO = re.compile(r"s[óo]\s*contexto", re.I)


def separar_checklist(texto: str) -> tuple[str, str]:
    """(linhas de vistoria, linhas "Só contexto") do checklist colado do celular. A marca
    "Só contexto" sai do texto; o resto da linha vai para o contexto (D-013)."""
    vist, ctx = [], []
    for ln in (texto or "").splitlines():
        if not ln.strip():
            continue
        if _SO_CONTEXTO.search(ln):
            limpa = _SO_CONTEXTO.sub("", ln).strip(" -–:|[]()✓✔☑*")
            if limpa:
                ctx.append(limpa)
        else:
            vist.append(ln.rstrip())
    return "\n".join(vist), "\n".join(ctx)


_CONVERSA = re.compile(r"(?i)conversa com o propriet")
_ROT_CONTEXTO = re.compile(r"(?i)^contexto\b")
_ROT_OBS = re.compile(r"(?i)^observa[çc][õo]es da vistoria")


def ler_checklist(texto: str) -> dict:
    """Texto do botão "Copiar para o JdB" (P5 parte A):
    1ª linha "VISTORIA – OV – Casa / Sobrado"; "## Seção"; "- rótulo: valor" (vistoria);
    "Não feito: a; b" (vai para Avisos). Vão para o CONTEXTO (nunca para o laudo): o campo
    "Contexto (não entra no laudo)" e tudo da seção "Conversa com o proprietário".
    Linhas soltas com "Só contexto" (formato antigo) também vão para o contexto."""
    out = {"cabecalho": "", "campos": [], "obs": [], "contexto": [], "nao_feito": []}
    secao = ""
    for i, bruto in enumerate((texto or "").splitlines()):
        ln = bruto.strip()
        if not ln:
            continue
        if i == 0 and ln.upper().startswith("VISTORIA"):
            out["cabecalho"] = ln
            continue
        if ln.startswith("##"):
            secao = ln.lstrip("#").strip()
            continue
        if re.match(r"(?i)^n[ãa]o feito\s*:", ln):
            itens = [x.strip() for x in ln.split(":", 1)[1].split(";") if x.strip()]
            out["nao_feito"] += [f"{secao}: {x}" if secao else x for x in itens]
            continue
        if _SO_CONTEXTO.search(ln):
            limpa = _SO_CONTEXTO.sub("", ln).strip(" -–:|[]()✓✔☑*")
            if limpa:
                out["contexto"].append(limpa)
            continue
        m = re.match(r"^[-•*]\s*([^:]{1,80}):\s*(.*)$", ln) or re.match(r"^([^:]{1,40}):\s*(.+)$", ln)
        if not m:
            (out["contexto"] if _CONVERSA.search(secao) else out["obs"]).append(ln.lstrip("-•* "))
            continue
        rot, val = m.group(1).strip(), m.group(2).strip()
        if not val:
            continue
        if _CONVERSA.search(secao) or _ROT_CONTEXTO.match(rot):
            out["contexto"].append(f"{rot}: {val}" if _CONVERSA.search(secao) else val)
        elif _ROT_OBS.match(rot):
            out["obs"].append(val)
        elif re.match(r"(?i)^data$", rot) and not secao:
            continue
        else:
            out["campos"].append((re.sub(r"\s*\(.*?\)\s*$", "", rot), val))
    return out


def separar_checklist(texto: str) -> tuple[str, str]:
    """(texto de vistoria, texto de contexto) — compatibilidade."""
    c = ler_checklist(texto)
    vist = [f"{r}: {v}" for r, v in c["campos"]] + c["obs"]
    return "\n".join(vist), "\n".join(c["contexto"])


def _sincronizar_vistoria(jid: str, t: Trabalho) -> Trabalho:
    """Checklist do celular: cada "- rótulo: valor" vira campo de vistoria (editado pelo
    avaliador); observações + texto livre viram "Observações da vistoria"; contexto e
    "Conversa com o proprietário" vão para o contexto (D-013); "Não feito" vira aviso."""
    from .modelos import Campo
    c = ler_checklist(t.checklist_vistoria)
    if c["contexto"]:
        base = (t.contexto or "").strip()
        marca = "[checklist – só contexto]"
        base = base.split(marca)[0].strip()
        t = t.model_copy(update={"contexto": (base + f"\n{marca}\n" + "\n".join(c["contexto"])).strip()})
    fonte = f"vistoria do avaliador em {t.data_vistoria.strftime('%d/%m/%Y')}"
    campos = [Campo(nome=rot[:60], valor=val[:1000], origem="vistoria", fonte=fonte,
                    observacao="checklist de vistoria") for rot, val in c["campos"]]
    texto = "\n".join(x for x in ((t.obs_vistoria or "").strip(), *c["obs"]) if x)
    if texto:
        campos.append(Campo(nome=CAMPO_VISTORIA, valor=texto, origem="vistoria", fonte=fonte,
                            observacao="informado pelo avaliador"))
    if campos:
        db.salvar_campos(jid, campos)
        for cp in campos:
            db.evento(jid, "extracao", "edicao_manual", f"{cp.nome}: registrado pelo avaliador",
                      dados={"campo": cp.model_dump(mode="json")})
    for x in c["nao_feito"]:
        db.evento(jid, "extracao", "aviso", f"checklist de vistoria – não feito: {x}")
    return t


@router.post("/jobs")
async def criar(body: NovoTrabalho, _u: dict = Depends(_dono)):
    if db.numero_usado(body.numero):
        raise HTTPException(status_code=409, detail="número já usado")
    try:
        t = Trabalho(id="", **body.model_dump(), avaliador_id=av_atual())
        if t.data_emissao is None:
            t = t.model_copy(update={"data_emissao": date.today()})
        jid = db.criar_job(t)
    except sqlite3.IntegrityError:  # corrida: outro POST levou o número entre a checagem e o insert
        raise HTTPException(status_code=409, detail="número já usado")
    t2 = _sincronizar_vistoria(jid, t.model_copy(update={"id": jid}))
    if t2.contexto != t.contexto:
        db.atualizar_dados(jid, t2)
    return {"id": jid}


@router.get("/proximo-numero")
async def proximo_numero(_u: dict = Depends(_dono)):
    return {"numero": db.proximo_numero()}


@router.get("/jobs")
async def listar(_u: dict = Depends(_dono)):
    out = []
    for d in db.listar_jobs():
        if dono_do_job(d) != av_atual():      # ORDEM 042: só os do avaliador
            continue
        if db.setting("lixeira:" + d["id"]):   # ORDEM 060: o que está na Lixeira sai da lista
            continue
        dados = d.pop("dados")
        d.update(cliente=dados.get("cliente"), modalidade=dados.get("modalidade"),
                 tipo=dados.get("tipo"), bairro=dados.get("bairro"), cidade=dados.get("cidade"),
                 finalidade=dados.get("finalidade"), objeto_parte=dados.get("objeto_parte"))
        try:                                   # ORDEM 047: etapa e próximo passo em poucas palavras
            from . import tela_trabalho
            t = tela_trabalho.resumo({**d, "dados": dados})
            d.update(etapa_tela=tela_trabalho.ROTULOS[t["atual"]], proximo=t["proximo"],
                     etapas_st=[e["status"] for e in t["etapas"]])
        except Exception:
            d.update(etapa_tela="", proximo="")
        d["entregue"] = rotas_lixeira.entregue(d["id"])    # ORDEM 060: aviso extra ao apagar
        out.append(d)
    return out


def _com_destoa(jid: str, refs: list) -> list[dict]:
    """L201-3: cada candidato leva as etiquetas do que destoa do avaliando ("padrão superior", "mais novo") — a tela
    os põe no fim da lista e avisa ao marcar; a decisão é do avaliador."""
    try:
        from . import candidatos as Cand
        from .agentes import pesquisa
        av = pesquisa.avaliando(jid)
        return [{**r.model_dump(mode="json"), "destoa": Cand.destoa(r, av)} for r in refs]
    except Exception:                    # sem avaliando lido ainda: lista sem etiquetas
        return [{**r.model_dump(mode="json"), "destoa": []} for r in refs]


@router.get("/jobs/{jid}")
async def detalhe(jid: str, _u: dict = Depends(_dono)):
    j = _job(jid)
    etapas = {e: db.resultado(jid, e) for e in orquestrador.ETAPAS}
    entrega = etapas.get("entrega") or {}
    vigente, previa = _calculo_vigente(jid)
    return {"job": j, "etapas": etapas, "arquivos": db.arquivos(jid),
            "campos": [c.model_dump(mode="json") for c in db.campos(jid)],
            "candidatos": _com_destoa(jid, db.candidatos(jid)),
            "resultado": vigente, "previa_calculo": previa,
            "pendencias": orquestrador.pendencias_estruturadas(entrega.get("pendencias", [])),
            # 181-4 (D-164): o custo da IA só vai para a conta do dono; os outros avaliadores nunca veem custo
            "resumo_ia": db.ia_resumo(jid) if _eh_dono(_u) else None, "dados_alterados": _dados_alterados(jid),
            "modelo_laudo": _modelo_laudo(j),                 # 194-4: "Modelo: PTAM não judicial — o do sistema"
            # ORDEM 032-3: data das fotos (EXIF) x data da vistoria, logo depois do envio
            "alerta_datas": _alerta_datas(jid, j),
            # ORDEM 047 / D-101: linha de etapas e próximo passo da tela simples
            "tela": _tela(j)}


def _tela(j: dict) -> dict:
    from . import tela_trabalho
    try:
        return tela_trabalho.resumo(j)
    except Exception:
        return {"etapas": [], "atual": "laudo", "proximo": "", "aprovado": False, "assinado": False}


def _alerta_datas(jid: str, j: dict) -> str:
    from . import datas_fotos
    try:
        dv = (j.get("dados") or {}).get("data_vistoria")
        msg = datas_fotos.alerta(jid, dv)
        if msg and datas_fotos.confirmada(jid, dv):
            return "CONFIRMADA: " + msg.replace(" Confirme a data da vistoria.", "") \
                + " O avaliador confirmou a data da vistoria."
        return msg
    except Exception as e:   # alerta é ajuda: nunca derruba o detalhe
        log.warning("alerta de datas: %s", e)
        return ""


def _calculo_vigente(jid: str) -> tuple[dict | None, dict | None]:
    """ORDEM 022: (cálculo vigente, prévia). O cálculo de antes de uma reabertura que chegou ao
    cálculo (ou antes) não é mais o atual; a prévia gravada pelo "Salvar" vale até o próximo
    cálculo do pipeline."""
    import json as _json
    idx_calc = orquestrador.ETAPAS.index("calculo")
    with db._conn() as c:
        rows = c.execute(
            "SELECT id, etapa, nivel, dados_json FROM av_events WHERE job=? AND ("
            "(etapa='calculo' AND nivel IN ('resultado','previa')) OR "
            "(etapa='orquestrador' AND nivel='volta')) ORDER BY id DESC", (jid,)).fetchall()
    barreira = 0
    for r in rows:
        if r["nivel"] == "volta":
            try:
                et = (_json.loads(r["dados_json"] or "{}") or {}).get("etapa")
            except ValueError:
                et = None
            if et in orquestrador.ETAPAS and orquestrador.ETAPAS.index(et) <= idx_calc:
                barreira = max(barreira, r["id"])
    vigente = previa = None
    for r in rows:   # do mais novo para o mais velho
        if r["nivel"] == "previa" and previa is None and vigente is None:
            previa = _json.loads(r["dados_json"]) if r["dados_json"] else None
        elif r["nivel"] == "resultado" and vigente is None:
            if r["id"] > barreira:
                vigente = _json.loads(r["dados_json"]) if r["dados_json"] else None
            break
    return vigente, previa


def _dados_alterados(jid: str) -> bool:
    """Campo, referenciais ou dados do trabalho editados depois da última entrega: o laudo
    entregue ainda não reflete a edição (a UI pede "Atualizar")."""
    from . import tela_trabalho
    return tela_trabalho.dados_alterados(jid)


def _livre(jid: str) -> dict:
    """Job existente e parado (nem na fila nem executando); senão 404/409."""
    j = _job(jid)
    if orquestrador.ocupado(jid):
        raise HTTPException(status_code=409, detail="trabalho em execução; aguarde terminar")
    return j


@router.put("/jobs/{jid}")
async def editar_trabalho(jid: str, body: DadosTrabalho, _u: dict = Depends(_dono)):
    """Edita os dados do trabalho (form P5) antes de reabrir; número e id não mudam."""
    j = _livre(jid)
    t = Trabalho(id=jid, numero=j["numero"], **body.model_dump(), avaliador_id=dono_do_job(j))
    t = _sincronizar_vistoria(jid, t)
    db.atualizar_dados(jid, t)
    db.evento(jid, "orquestrador", "edicao_manual", "dados do trabalho editados pelo avaliador",
              dados={"antes": j["dados"], "depois": t.model_dump(mode="json")})
    return {"job": db.job(jid)}


class EdicaoCampo(BaseModel):
    valor: str | float | None
    origem: Literal["documento", "vistoria"]
    fonte: str
    unidade: str | None = None
    observacao: str | None = Field(default=None, max_length=300)


_VISTORIA = re.compile(r"^vistoria do avaliador em (\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})$", re.I)


def _data_vistoria_valida(fonte: str) -> bool:
    m = _VISTORIA.match(fonte)
    if not m:
        return False
    d = m.group(1)
    try:
        datetime.strptime(d, "%d/%m/%Y" if "/" in d else "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _fonte_valida(jid: str, origem: str, fonte: str) -> bool:
    """D-013: fonte cita arquivo registrado do job (vistoria: foto) ou, na vistoria, é
    "vistoria do avaliador em <data>"."""
    from .agentes import extracao
    f = fonte.strip()
    if origem == "vistoria" and _VISTORIA.match(f):
        return _data_vistoria_valida(f)
    regs = db.arquivos(jid)
    if origem == "vistoria":
        regs = [a for a in regs if a["tipo"] == "foto"]
    nomes = {extracao._chave(a[k]) for a in regs for k in ("nome", "caminho") if a.get(k)}
    return bool(extracao._citados(f, nomes))


@router.put("/jobs/{jid}/campos/{nome:path}")   # :path aceita "/" no nome ("Quartos/suítes")
async def editar_campo(jid: str, nome: str, body: EdicaoCampo, _u: dict = Depends(_dono)):
    _livre(jid)
    nome = nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="nome do campo vazio")
    from .agentes import extracao as _ext
    if not _ext.nome_permitido(jid, nome):
        raise HTTPException(status_code=400, detail=f"campo desconhecido: {nome}")
    if not _fonte_valida(jid, body.origem, body.fonte):
        raise HTTPException(status_code=400, detail=(
            "fonte deve citar um arquivo enviado neste trabalho"
            + (" (foto) ou ser \"vistoria do avaliador em dd/mm/aaaa\""
               if body.origem == "vistoria" else "")))
    from .modelos import Campo
    antigo = next((c for c in db.campos(jid) if c.nome == nome), None)
    novo = Campo(nome=nome, valor=body.valor, origem=body.origem, fonte=body.fonte.strip(),
                 unidade=body.unidade if body.unidade is not None else (antigo.unidade if antigo else ""),
                 observacao=(body.observacao if body.observacao is not None else "editado pelo avaliador"))
    db.salvar_campos(jid, [novo])
    db.evento(jid, "extracao", "edicao_manual",
              f"{nome}: {antigo.valor if antigo else '—'} → {novo.valor}",
              dados={"campo": novo.model_dump(mode="json"),
                     "antes": antigo.model_dump(mode="json") if antigo else None})
    return novo.model_dump(mode="json")


class EscolhaReferenciais(BaseModel):
    escolhidos: list[int]
    unitario_adotado: str | None = None
    justificativa: str | None = None
    faixa_pct: str | None = None          # vazio = mantém (padrão ±10%)
    continuar: bool = False               # True = confirma e devolve o trabalho à fila
    # ORDEM 010: "Confirmo mesmo assim, porque…" — obrigatório quando há alertas
    confirmacao_alertas: str | None = None
    # ORDEM 021: base do cálculo ("construida" | "terreno") e o campo da área do imóvel;
    # obrigatórios com continuar=true
    base_area: str | None = None
    area_campo: str | None = None


_SUPERIOR_TXT = re.compile(r"(?i)piscina|sauna|alto padr|luxo|hidromassagem|gourmet|todas? (?:as )?su[ií]tes|"
                           r"nunca habitad|\bnovo\b|lan[cç]amento|condom[ií]nio com (?:lazer|piscina)")


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%".replace(".", ",")


def _quem_dispersa(refs) -> str:
    """Pedido do Alan (9118): o alerta diz QUAL referencial espalha a amostra — os que, tirados
    um de cada vez, mais baixam o coeficiente de variação (até 2), com o CV sem cada um."""
    import statistics
    us = {r.n: r.preco / r.area_m2 for r in refs if r.preco and r.area_m2}
    if len(us) < 4:
        return ""
    mais_alto, mais_baixo = max(us, key=us.get), min(us, key=us.get)
    sem = {}
    for n in us:
        resto = [u for k, u in us.items() if k != n]
        sem[n] = statistics.stdev(resto) / statistics.mean(resto)
    piores = sorted(sem, key=sem.get)[:2]
    partes = []
    for n in piores:
        onde = (", o mais alto" if n == mais_alto else ", o mais baixo" if n == mais_baixo else "")
        partes.append(f"nº {n} (R$ {_brl_m2(us[n])}/m²{onde}): sem ele, {_pct(sem[n])}")
    return ". Quem mais espalha a amostra: " + "; ".join(partes)


def _brl_m2(v: float) -> str:
    return f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


def alertas_confirmacao(refs, unit, media, minimo, maximo, cv) -> list[str]:
    """ORDEM 010: situações em que o avaliador tem de confirmar explicitamente o valor."""
    al = []
    if cv is not None and cv > 0.15:
        al.append(f"amostra dispersa: coeficiente de variação de {_pct(cv)} (acima de 15%)"
                  + _quem_dispersa(refs))
    sup = [r.n for r in refs if r.nao_recomendado or "indícios de padrão superior" in (r.observacao or "")
           or re.search(r"(?i)alto|superior|luxo", r.padrao or "")
           or _SUPERIOR_TXT.search(" ".join((r.descricao or "", r.titulo or "")))]
    contra = [r.n for r in refs if "contradit" in (r.observacao or "").lower()]
    if contra:   # ORDEM 034-1 / D-010: anúncio que se contradiz (preço ou área)
        al.append(sv(len(contra), "anúncio contraditório (D-010): nº ", "anúncios contraditórios (D-010): nº ")
                  + ", ".join(map(str, contra)))
    if sup:
        al.append(sv(len(sup), "escolhido com indício de padrão superior ou não recomendado: nº ",
                     "escolhidos com indício de padrão superior ou não recomendados: nº ")
                  + ", ".join(map(str, sup)))
    nao = [r.n for r in refs if r.fonte_coleta not in ("manual", "avaliador") and (r.bloqueado or not r.coletado)]
    if nao:
        al.append(sv(len(nao), "escolhido não conferido (anúncio não aberto ou bloqueado): nº ",
                     "escolhidos não conferidos (anúncio não aberto ou bloqueado): nº ")
                  + ", ".join(map(str, nao)))
    if unit is not None and (abs(unit - minimo) < Decimal("0.01") or abs(unit - maximo) < Decimal("0.01")):
        al.append("unitário adotado no " + ("mínimo" if abs(unit - minimo) < Decimal("0.01") else "máximo")
                  + " do intervalo da amostra")
    if unit is not None and media and abs(unit - media) / media > Decimal("0.15"):
        al.append(f"unitário {abs(unit - media) / media * 100:.1f}% diferente da média da amostra (acima de 15%)")
    return al


from .agentes.selecao import ESCOLHA_MANUAL  # noqa: E402


@router.get("/jobs/{jid}/areas")
async def areas_do_calculo(jid: str, _u: dict = Depends(_dono)):
    """ORDEM 021: opções de área por base (construída / terreno), a sugerida (a do imóvel
    avaliado) e a escolha gravada."""
    from .agentes import selecao
    _job(jid)
    return selecao.opcoes_area(jid)


@router.put("/jobs/{jid}/referenciais")
async def escolher_referenciais(jid: str, body: EscolhaReferenciais, _u: dict = Depends(_dono)):
    """Confirmação do avaliador (antes da redação): referenciais escolhidos, unitário
    adotado (dentro do intervalo, com justificativa se ≠ média) e faixa ±. Grava a seleção
    como `confirmado`; com `continuar`, o pipeline segue para cálculo/redação."""
    from decimal import Decimal, InvalidOperation

    from . import calculo
    from .agentes import selecao
    _livre(jid)
    cands = db.candidatos(jid)
    ns = set(body.escolhidos)
    if not ns:
        raise HTTPException(status_code=400, detail="escolha ao menos 1 referencial")
    if faltam := ns - {r.n for r in cands}:
        raise HTTPException(status_code=400, detail=f"referencial inexistente: {sorted(faltam)}")
    # ORDEM 021: base e área escolhidas pelo avaliador (sempre ao confirmar)
    if body.continuar and not ((body.base_area or "").strip() and (body.area_campo or "").strip()):
        raise HTTPException(status_code=400, detail=selecao.FALTA_ESCOLHA)
    if (body.base_area or "").strip() and (body.area_campo or "").strip():
        try:
            selecao.gravar_escolha_area(jid, body.base_area.strip(), body.area_campo.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    base = selecao.base_area(jid)
    # ORDEM 022: sem base/área escolhidas, nada de cair calado na área de documento — salva os
    # referenciais e devolve o valor vazio (o cálculo abaixo só valida os unitários)
    escolha = selecao.escolha_area(jid)
    area = selecao.area_construida(jid) if escolha else None
    if escolha and area is None:
        raise HTTPException(status_code=400, detail="área do avaliando ausente; edite o campo antes")
    unit = None
    if (body.unitario_adotado or "").strip():
        try:
            unit = selecao._decimal_br(body.unitario_adotado)
        except (InvalidOperation, ValueError):
            raise HTTPException(status_code=400, detail="unitário adotado inválido")
    anterior = db.resultado(jid, "selecao") or {}
    faixa = Decimal(str(anterior.get("faixa_pct") or selecao.FAIXA_PADRAO))
    if (body.faixa_pct or "").strip():
        try:
            faixa = selecao._decimal_br(body.faixa_pct)
        except (InvalidOperation, ValueError):
            raise HTTPException(status_code=400, detail="faixa inválida")
        if not Decimal("0") < faixa <= Decimal("30"):
            raise HTTPException(status_code=400, detail="faixa deve estar entre 0 e 30%")
    just = (body.justificativa or "").strip()
    just = just.removeprefix(ESCOLHA_MANUAL).strip(" :")      # 083-D: o rótulo padrão não se repete
    antes = {r.n: r for r in cands}
    refs = [r.model_copy(update={
        "escolhido": r.n in ns and r.decisao != "comparacao",      # 094-1: comparação nunca entra na conta
        "justificativa": (r.justificativa if r.n in ns and r.escolhido and not just
                          else ESCOLHA_MANUAL + (f": {just}" if just and r.n in ns else ""))})
        for r in cands]
    try:
        na_base = selecao.refs_na_base(jid, [r for r in refs if r.escolhido], base)
        res = calculo.calcular(area if area is not None else Decimal("1"), na_base, unit, faixa)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if unit is not None and unit != res.media and not just:
        raise HTTPException(status_code=400, detail=(
            "justifique o unitário adotado (diferente da média da amostra, "
            f"{selecao._br(float(res.media))}/m²)"))
    import statistics
    us = [float(x) for x in res.unitarios]
    cv = (statistics.stdev(us) / statistics.mean(us)) if len(us) >= 2 and statistics.mean(us) else None
    alertas = alertas_confirmacao(na_base, unit, res.media, res.minimo, res.maximo, cv)
    conf = (body.confirmacao_alertas or "").strip()
    if body.continuar and alertas and len(conf) < 10:
        raise HTTPException(status_code=400, detail=(
            "confirme explicitamente (\"Confirmo mesmo assim, porque…\"): " + "; ".join(alertas)))
    n = len(ns)
    declaracao = ("" if n >= selecao.MIN_ESCOLHIDOS else
                  f"Amostra reduzida: apenas {pl(n, 'referencial escolhido', 'referenciais escolhidos')} pelo avaliador.")
    proposta = anterior.get("proposta_ia")
    s = selecao.Selecao(refs=refs, unitario_adotado=unit,
                        justificativa_unitario=(just or ESCOLHA_MANUAL) if unit is not None else "",
                        # ORDEM 034: "Só salvar" grava a escolha mas NÃO autoriza gerar o laudo;
                        # só "Confirmar e gerar" (continuar) marca como confirmado
                        faixa_pct=faixa, declaracao_amostra=declaracao, confirmado=body.continuar,
                        proposta_ia=proposta,
                        amostra=selecao.assinatura_amostra(refs) if unit is not None else "")
    db.salvar_candidatos(jid, refs)
    mudou = sorted(k for k, r in antes.items() if r.escolhido != (k in ns))
    db.evento(jid, "selecao", "resultado",
              f"{n} de {len(refs)} referenciais; unitário "
              f"{selecao._br(float(res.unitario_adotado))}/m², faixa ±{faixa}% "
              f"({ESCOLHA_MANUAL})" + (f"; alterados: {mudou}" if mudou else ""),
              dados={**s.model_dump(mode="json"), "manual": True})
    if alertas and conf:
        db.evento(jid, "selecao", "info", "avaliador confirmou mesmo assim: " + conf[:500],
                  dados={"alertas": alertas, "confirmacao": conf})
        # 086-7: decidiu uma vez (no Confirmar valor), não pergunta de novo no passo seguinte
        from . import pendencias_simples as PS
        for al in alertas:
            tema = PS._tema(PS._n(al))
            if tema:
                PS.gravar_decisao(jid, tema, f"Confirmar valor: {conf[:120]}")
    # ORDEM 022 b: prévia do cálculo (determinística, sem IA) a cada salvamento
    if area is not None:
        previa = {"area": str(area), "valor_adotado": str(res.valor_adotado),
                  "valor_min": str(res.valor_min), "valor_max": str(res.valor_max),
                  "unitario_adotado": str(res.unitario_adotado), "base": base, "previa": True}
        db.evento(jid, "calculo", "previa", f"prévia: valor {res.valor_adotado} (confirme para gerar o laudo)",
                  dados=previa)
    else:
        db.evento(jid, "calculo", "previa", selecao.SEM_VALOR,
                  dados={"pendente": True, "mensagem": selecao.SEM_VALOR,
                         "unitario_adotado": str(res.unitario_adotado)})
    if body.continuar:
        if area is not None:      # 082-5: o valor que o avaliador viu e confirmou (a remontagem não muda calada)
            db.set_setting(f"valor_confirmado:{jid}", str(res.valor_adotado))
        orquestrador.reabrir(jid, "calculo", motivo="valor confirmado pelo avaliador")
        orquestrador.enfileirar(jid)
    sem = area is None
    return {**s.model_dump(mode="json"), "manual": True,
            "valor_adotado": None if sem else str(res.valor_adotado),
            "valor_min": None if sem else str(res.valor_min),
            "valor_max": None if sem else str(res.valor_max),
            "mensagem": selecao.SEM_VALOR if sem else "",
            "media": str(res.media), "alertas": alertas, "area": None if sem else str(area),
            "base_area": base, "escolha_area": escolha}


class AnuncioEnviado(BaseModel):
    """O que a extensão do Chrome leu da página que o Alan está vendo (ORDEM 010)."""
    link: str = Field(max_length=2000)
    titulo: str = Field(default="", max_length=500)
    texto: str = Field(default="", max_length=20000)
    preco: float | None = None
    area_m2: float | None = None
    lote_m2: float | None = None
    quartos: int | None = None
    suites: int | None = None
    bairro: str = Field(default="", max_length=200)
    imagem: str = Field(default="", max_length=8_000_000)   # data URL (jpeg/png) ou vazio
    # ORDEM 029-5 (extensão 1.0.3): recorte da foto principal do anúncio na tela do Alan
    foto_principal: str = Field(default="", max_length=8_000_000)
    # ORDEM 039-1 / D-082 (extensão 1.0.4): página inteira, PDF da página e hora do acesso
    pagina_inteira: str = Field(default="", max_length=20_000_000)
    pdf_pagina: str = Field(default="", max_length=20_000_000)
    acessado_em: str = Field(default="", max_length=40)
    fotos_url: list[str] = Field(default_factory=list, max_length=40)    # 081-5: fotos grandes da galeria


class PaginaEnviada(BaseModel):
    """ORDEM 019: resultados de uma página de busca que o avaliador abriu no Chrome dele."""
    url: str = Field(default="", max_length=2000)
    cartoes: list[dict] = Field(default_factory=list, max_length=200)


@router.get("/jobs/{jid}/pesquisa/links")
async def links_busca(jid: str, _u: dict = Depends(_dono)):
    """Links de busca de cada portal para abrir no Chrome do avaliador."""
    from .agentes import pesquisa
    _job(jid)
    q = pesquisa.consulta_internet(jid)   # D-064 (a): "Ampliar a busca na internet"
    return {"links": pesquisa.links_de_busca(jid),
            "internet": {"url": pesquisa.url_google(q), "consulta": q, "minimo": pesquisa.MIN_SEMELHANTES,
                         "semelhantes": pesquisa.semelhantes(db.candidatos(jid))}}


@router.post("/jobs/{jid}/candidatos/pagina")
async def candidatos_da_pagina(jid: str, body: PaginaEnviada, _u: dict = Depends(_dono)):
    """"Enviar resultados desta página" (extensão): os cartões entram na lista pelos mesmos
    filtros (região, duplicados, semelhança) da pesquisa do Coletor. Sem robô, sem contorno."""
    from . import portais
    from .agentes import pesquisa
    _livre(jid)
    cartoes: list[tuple[str, dict]] = []
    ignorados = 0
    for x in body.cartoes:
        link = str(x.get("link") or "")[:2000]
        texto = str(x.get("texto") or "")[:1500]
        p = next((p for p in portais.PORTAIS.values() if p.eh_anuncio(link)), None)
        if p is None or not texto:
            ignorados += 1
            continue
        cartoes.append((p.nome, {"link": link, "texto": texto}))
    if not cartoes:
        raise HTTPException(status_code=400, detail=(
            "nenhum anúncio reconhecido nesta página (abra a página de resultados de busca de "
            "ZAP, Viva Real, OLX ou Imovelweb)"))
    novos = await pesquisa.montar_lista(jid, cartoes_enviados=cartoes)
    return {"recebidos": len(body.cartoes), "reconhecidos": len(cartoes), "ignorados": ignorados,
            "novos": [r.n for r in novos]}


def _gravar_data_url(jid: str, data_url: str, nome: str) -> str:
    """Imagem (data URL jpeg/png/webp) vinda da extensão -> mercado/<nome>.<ext>; "" se inválida."""
    import base64
    m = re.match(r"^data:image/(png|jpe?g|webp);base64,(.+)$", data_url or "", re.S)
    if not m:
        return ""
    try:
        dados = base64.b64decode(m.group(2), validate=True)
    except ValueError:
        return ""
    if not dados:
        return ""
    ext = {"png": "png", "webp": "webp"}.get(m.group(1), "jpg")
    destino = db.pasta(jid) / "mercado" / f"{nome}.{ext}"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(dados)
    return destino.relative_to(db.pasta(jid)).as_posix()


def _bytes_data_url(data_url: str, tipos: str = r"image/(?:png|jpe?g|webp)") -> bytes | None:
    import base64
    m = re.match(rf"^data:{tipos};base64,(.+)$", data_url or "", re.S)
    if not m:
        return None
    try:
        return base64.b64decode(m.group(1), validate=True) or None
    except ValueError:
        return None


def _prova_enviada(jid: str, n: int, body: "AnuncioEnviado", link: str, portal: str) -> dict:
    """D-082: prova do anúncio enviado pela extensão — página inteira (1.0.4) ou a parte
    visível (versões antigas), com a faixa de data/hora/link; PDF da página quando vier.
    A hora é a do servidor no recebimento; a da extensão só vale se estiver a ±15 min."""
    from datetime import timedelta
    from . import provas
    quando = provas.agora()
    cliente = provas.em_brasilia(body.acessado_em) if body.acessado_em else None
    if cliente and abs(cliente - quando) <= timedelta(minutes=15):
        quando = cliente
    img = _bytes_data_url(body.pagina_inteira) or _bytes_data_url(body.imagem)
    pdf_pg = _bytes_data_url(body.pdf_pagina, r"application/pdf")
    try:
        return provas.gravar(jid, n, img, link, portal, quando, pdf_pg)
    except Exception as e:     # a prova nunca derruba o envio: fica só a hora
        db.evento(jid, "pesquisa", "aviso", f"anúncio nº {n}: prova não gravada ({e})")
        return {"acessado_em": quando.isoformat(timespec="seconds"), "prova": "", "prova_pdf": ""}


def _idade_em_segundo_plano(jid: str, n: int) -> None:
    """109-5: a idade aparente do anúncio é completada em segundo plano (texto; sem idade no texto, IA leve na foto)."""
    try:
        from . import idade_anuncio
        idade_anuncio.agendar(jid, n)
    except Exception:          # noqa: BLE001 — a idade nunca derruba o envio do anúncio
        log.exception("idade do anúncio %s/%s", jid, n)


async def _completar_enviado(jid: str, r, body: "AnuncioEnviado", portal: str) -> dict:
    """ORDEM 029-5: referencial que JÁ está na lista (o Coletor não abriu a página: Cloudflare)
    e o Alan mandou "Enviar este anúncio" da página aberta no Chrome dele -> o mesmo nº recebe a
    foto principal, o print e os dados da página. Não cria outro referencial."""
    from . import candidatos as C
    from .agentes import leitor_anuncio
    from .agentes import pesquisa as P
    from .coletor_hub import Captura
    # 082 (GRAVÍSSIMO): envio para referencial que JÁ existe só ACRESCENTA (foto, data/hora de acesso,
    # captura). Preço, áreas, localização, descrição, quartos e "usar" nunca mudam aqui: campo vazio é
    # preenchido; valor diferente do guardado vira pergunta ao avaliador, com o guardado valendo.
    upd: dict = {"coletado": True, "bloqueado": False}
    diverg: dict = dict(getattr(r, "divergencia_pagina", None) or {})
    pagina: dict = {}

    def _vazio(v) -> bool:
        return v in (None, "", 0, 0.0)

    def _diferente(k, guardado, novo) -> bool:
        if isinstance(guardado, (int, float)) and isinstance(novo, (int, float)):
            return abs(float(guardado) - float(novo)) > 0.01 * max(abs(float(guardado)), 1.0)
        return str(guardado).strip().casefold() != str(novo).strip().casefold()

    def _acrescentar(k, novo) -> None:
        if _vazio(novo) or k in upd:
            return
        guardado = getattr(r, k, None)
        if k == "descricao" and "a conferir" in str(guardado or "").lower():
            guardado = ""                         # o "a conferir" é só lembrete: a página foi vista
        if _vazio(guardado):
            upd[k] = novo
        elif k in CAMPOS_PERGUNTA and _diferente(k, guardado, novo):
            pagina[k] = novo
    for k in ("preco", "quartos", "suites"):
        _acrescentar(k, getattr(body, k))
    _acrescentar("bairro", body.bairro.strip())
    _acrescentar("titulo", body.titulo.strip()[:300])
    foto = _gravar_data_url(jid, body.foto_principal, f"enviado-{r.n}-foto")
    tela = _gravar_data_url(jid, body.imagem, f"enviado-{r.n}-pagina")
    if foto or tela:
        upd["foto"] = foto or tela        # sem recorte da foto: a parte visível da página
    if tela:
        upd["print_"] = tela
    if not upd.get("foto") and not r.foto:              # 096-1: envio sozinho sem foto → a 1ª da galeria que não é arte
        rel_g, arte1 = await _foto_da_galeria(jid, r.n, _fotos_url(body.fotos_url))
        if rel_g:
            upd["foto"] = rel_g
            upd["foto_arte"] = arte1
    lido = None
    from . import leitura_pagina as _LP
    texto_ad = _LP.texto_do_anuncio(body.texto or "", body.titulo or "") or (body.texto or "")   # 091-1
    # 091-4: bairro/rua claramente errados ("Deztop", "GO", rua grudada) são corrigidos pela página; bons ficam (082-2)
    from .agentes import _comum as _cm
    _cid = _cm.trabalho(jid).cidade
    rua_p, bairro_p = _LP.local_da_pagina(body.texto or "", _cid)
    if r.rua and "," in r.rua:
        r_sep, b_sep = _LP.separar_rua(r.rua, _cid)
        if r_sep:
            upd["rua"] = r_sep
        if b_sep and _LP.bairro_ruim(r.bairro):
            upd["bairro"] = b_sep
    if _LP.bairro_ruim(upd.get("bairro") or r.bairro) and bairro_p:
        upd["bairro"] = bairro_p
    if not (upd.get("rua") or r.rua) and rua_p:
        upd["rua"] = rua_p
    if (body.texto or "").strip():
        try:   # mesmo leitor do Coletor (modelo leve), sobre o texto que a extensão leu
            lido = await leitor_anuncio.ler(jid, Captura(ok=True, url_final=r.link, texto=texto_ad),
                                            portal or r.portal)
        except Exception as e:   # IA fora: ficam os dados da página (preço/área), sem padrão/idade
            db.evento(jid, "pesquisa", "aviso", f"anúncio nº {r.n} enviado: texto não lido pela IA ({e})")
    # 082-3: área e lote só quando se confirmam no próprio anúncio (leitura_pagina); número de anúncio
    # vizinho da página nem vira pergunta
    from . import leitura_pagina as LP
    try:                                   # 097-2: a área rotulada no texto do próprio anúncio também confirma
        a_pag, _ = LP.area_confirmada(body.titulo, r.link, body.area_m2 or None, lido.area_m2 if lido is not None else None,
                                      texto=texto_ad)
    except TypeError:
        a_pag, _ = LP.area_confirmada(body.titulo, r.link, body.area_m2 or None, lido.area_m2 if lido is not None else None)
    _acrescentar("area_m2", a_pag)
    lote_txt = body.lote_m2 or (lido.lote_m2 if lido is not None else None)
    if (lido is not None and lido.area_m2 and r.area_m2
            and "TERRENO" in C.conferir_area(r.area_m2, lido.area_m2, lote_txt)):
        pagina["area_m2"] = lido.area_m2          # F-S003: a área guardada é a do terreno → pergunta
    try:                                   # 098-2: lote só se estiver no texto do próprio anúncio
        lote_ok = LP.lote_confirmado(texto_ad, body.titulo or "", body.lote_m2 or (lido.lote_m2 if lido is not None else None))
    except Exception:
        lote_ok = body.lote_m2 or (lido.lote_m2 if lido is not None else None)
    _acrescentar("lote_m2", LP.lote_plausivel(lote_ok, a_pag or r.area_m2, r.tipologia))
    # L200 (Caso W): quartos/suítes ESCRITOS no anúncio aberto conferem os guardados (que vinham do cartão da
    # busca) — só o texto do próprio anúncio (a página traz anúncios vizinhos) e antes da leitura da IA, que perde
    # para ele. Vazio preenche; diferente vira pergunta; combinação impossível (mais suítes que quartos) é trocada.
    q_txt, s_txt = _LP.quartos_suites(f"{body.titulo or ''}\n{_LP.descricao_limpa(body.texto or '', body.titulo or '')}")
    do_texto = {k for k, v in (("quartos", q_txt), ("suites", s_txt)) if v}
    if _LP.combinacao_impossivel(r.quartos, r.suites) and do_texto:
        for k, v in (("quartos", q_txt), ("suites", s_txt)):
            upd[k] = v
        db.evento(jid, "pesquisa", "aviso", f"anúncio nº {r.n}: {r.quartos} quartos e {r.suites} suítes é impossível; "
                  f"ficou o que o anúncio diz ({q_txt or 'n/i'} quartos, {s_txt or 'n/i'} suítes)")
    else:
        for k, v in (("quartos", q_txt), ("suites", s_txt)):
            _acrescentar(k, v)
    if lido is not None:
        for k in ("padrao", "idade_aparente", "descricao", "publicado_em", "quartos", "suites", "preco"):
            if k in ("quartos", "suites") and do_texto:
                continue
            v = getattr(lido, k, None)
            if k == "idade_aparente":         # 104-2 / 105-2: número, "novo" ou "seminovo"; estado não é idade
                from .docx_builder import idade_valida
                v = idade_valida(str(v or ""), texto_ad) or None
            if k not in pagina:
                _acrescentar(k, v)
    elif "a conferir" in (r.descricao or "").lower():
        upd["descricao"] = ""            # tira o "a conferir": a página foi vista pelo avaliador
    if pagina:
        diverg.update(pagina)
        db.evento(jid, "pesquisa", "aviso", f"anúncio nº {r.n}: a página mostrou "
                  + "; ".join(f"{ROTULO_CAMPO.get(k, k)} {_fmt_campo(k, v)} (o laudo usa {_fmt_campo(k, getattr(r, k))})"
                              for k, v in pagina.items()) + " — nada foi trocado; pergunta ao avaliador")
    upd["divergencia_pagina"] = diverg
    nota = "foto e dados enviados pelo avaliador (Chrome)"
    obs = r.observacao or ""
    obs = obs if nota in obs else "; ".join(x for x in (obs, nota) if x)
    # ORDEM 034-1 / F-S003: área do cartão (a que estava na lista) x a do texto do anúncio
    aviso_area = C.conferir_area(r.area_m2, pagina.get("area_m2"), lote_txt) if "area_m2" in pagina else ""
    if aviso_area:
        obs = "; ".join(x for x in (obs, aviso_area) if x)
        db.evento(jid, "pesquisa", "aviso", f"anúncio nº {r.n}: {aviso_area}")
    upd["observacao"] = obs[:300]
    upd.update(_prova_enviada(jid, r.n, body, r.link, portal or r.portal))   # D-082
    upd.pop("prova_pagina_pdf", None)
    fotos = _fotos_url(body.fotos_url)
    if fotos:
        upd["fotos_url"] = fotos
    if upd.get("foto"):                                  # 081-5 / 093-A-10: a 1ª imagem é banner de venda? (sempre confere)
        upd["foto_arte"] = await _foto_e_arte(jid, upd["foto"])
        if upd["foto_arte"] and len(fotos) >= 2:          # 102-4: troca sozinho pela 1ª da galeria que não é arte e avisa
            rel_g, _ = await _foto_da_galeria(jid, r.n, fotos[1:])
            if rel_g:
                upd.update(foto=rel_g, foto_arte=False)
                db.evento(jid, "pesquisa", "aviso", f"Troquei a foto do anúncio {r.n}: a 1ª era propaganda (aviso ao "
                          "avaliador, não é reprovação; para outra, use Trocar foto na tela dos anúncios)")
    # 093-6: descrição guardada que é o menu do portal (envio antigo) vira o texto do anúncio; e o aviso é refeito
    from .docx_builder import _LIXO_PORTAL
    if _LIXO_PORTAL.search(r.descricao or "") and "descricao" not in upd:
        upd["descricao"] = _LP.descricao_limpa(body.texto or "", body.titulo or "")
    elif "descricao" not in upd and (body.texto or "").strip():
        # L200 (Caso W): a descrição era só o cartão da busca; o texto do anúncio aberto (piscina, gourmet,
        # porcelanato…) é o que mostra o padrão — antes ficava de fora e a escolha não via
        cheio = _LP.descricao_limpa(body.texto or "", body.titulo or "")
        if len(cheio) > len(r.descricao or ""):
            upd["descricao"] = cheio
    if not r.destaque:                     # 100-8
        try:
            upd["destaque"] = _LP.destaque(body.texto or "", body.titulo or "")[:200]
        except Exception:
            pass
    novo = r.model_copy(update=upd)
    x = C.avaliar(novo, P.avaliando(jid))
    if novo.fonte_coleta in ("avaliador", "manual"):
        novo = novo.model_copy(update={"motivo": x.motivo, "nao_recomendado": x.nao_recomendado,
                                       "recomendado": x.recomendado, "pontos": x.pontos})
    ind = next((p for p in (x.observacao or "").split("; ") if p.startswith("indícios de padrão superior")), "")
    # L200: o indício lido no anúncio aberto fica registrado — e o antigo sai (era de quartos/suítes errados)
    sem_velho = [p for p in (novo.observacao or "").split("; ") if p and not p.startswith("indícios de padrão superior")]
    obs_nova = "; ".join(sem_velho + ([ind] if ind else []))[:300]
    if obs_nova != (novo.observacao or ""):
        novo = novo.model_copy(update={"observacao": obs_nova})
    _salvar_ref(jid, novo, "completado pelo avaliador (Chrome)")
    P.exportar(jid)
    db.evento(jid, "pesquisa", "edicao_manual", f"anúncio nº {r.n} completado pelo avaliador (Chrome): "
              + ("foto, " if upd.get("foto") else "") + "dados da página")
    un = round(novo.preco / novo.area_m2, 2) if novo.preco and novo.area_m2 else None
    # 086-1: só remonta se a TABELA muda (foto nova ou data de acesso nova); prova sozinha fica no dossiê e não
    # remonta. A remontagem é uma só, 2 min depois do último envio (vários envios seguidos = uma montagem)
    na_tabela = (r.escolhido or r.decisao in ("entra", "comparacao"))
    mudou_tabela = bool((not r.foto and novo.foto) or (not (r.acessado_em or "") and (novo.acessado_em or "")))
    if na_tabela and mudou_tabela and db.resultado(jid, "entrega"):
        orquestrador.agendar_remontagem(jid, f"anúncio nº {r.n} com foto e data (extensão)")
    return {"n": r.n, "atualizado": True, "portal": novo.portal, "area_m2": novo.area_m2,
            "preco": novo.preco, "unitario": un, "foto": bool(upd.get("foto")),
            "observacao": novo.observacao}


CAMPOS_PERGUNTA = ("preco", "area_m2", "lote_m2", "quartos", "suites", "bairro")
ROTULO_CAMPO = {"preco": "preço", "area_m2": "área construída", "lote_m2": "lote", "quartos": "quartos",
                "suites": "suítes", "bairro": "bairro"}


def _fmt_campo(k: str, v) -> str:
    if v in (None, ""):
        return "vazio"
    if k == "preco":
        return "R$ " + f"{float(v):,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
    if k in ("area_m2", "lote_m2"):
        x = float(v)
        return (f"{x:,.0f}" if x == int(x) else f"{x:,.2f}").replace(",", "§").replace(".", ",").replace("§", ".") + " m²"
    return str(v)


def _salvar_ref(jid: str, novo, como: str) -> None:
    """Grava o referencial e, se a seleção já foi confirmada, a cópia nova do mesmo nº nela."""
    db.salvar_candidatos(jid, [novo])
    sel = db.resultado(jid, "selecao")
    if sel and any(x.get("n") == novo.n for x in sel.get("refs") or []):
        sel["refs"] = [({**novo.model_dump(mode="json"), "escolhido": x.get("escolhido", False),
                         "justificativa": x.get("justificativa", "")} if x.get("n") == novo.n else x)
                       for x in sel["refs"]]
        db.evento(jid, "selecao", "resultado", f"referencial nº {novo.n} {como}", dados=sel)


# 089-3: imagem do portal (loja de aplicativo, logotipo, selo, ícone, banner), não foto do imóvel
_NAO_E_FOTO = re.compile(r"(?i)app[-_ ]?store|google[-_ ]?play|play[-_.]google|badge|selo|logo|icon|sprite|banner|"
                         r"placeholder|avatar|whatsapp|qr[-_]?code|/static/|\.svg(?:$|\?)")


def _fotos_url(urls: list[str]) -> list[str]:
    out: list[str] = []
    for u in urls or []:
        u = (u or "").strip()
        if re.match(r"^https://[^\s]{8,1990}$", u) and u not in out and not _NAO_E_FOTO.search(u):
            out.append(u)
    from . import leitura_pagina as _LPf
    return _LPf.fotos_unicas(out, 12)             # 096-7: a mesma foto em vários tamanhos conta uma vez


class _Arte(BaseModel):
    arte: bool = Field(description="true se a imagem é arte/banner de anúncio (texto grande de venda, preço, "
                                   "telefone, logotipo) em vez de foto do imóvel")


async def _foto_e_arte(jid: str, rel: str) -> bool:
    """081-5: a foto principal é uma arte de propaganda (ex.: "À VENDA – Casa Escriturada… R$ 180.000")?
    Uma leitura leve por anúncio enviado; sem IA, fica como está (sem aviso)."""
    from . import ia
    from .agentes.leitor_anuncio import modelo_leve
    try:
        r = await ia.perguntar("Classifique a imagem de um anúncio de imóvel.",
                               "Esta imagem é foto do imóvel ou arte de anúncio com texto de venda?", _Arte,
                               arquivos=[db.pasta(jid) / rel], cwd=db.pasta(jid), modelo=modelo_leve())
        return bool(r.arte)
    except Exception as e:
        db.evento(jid, "pesquisa", "aviso", f"foto {rel}: não deu para conferir se é arte de anúncio ({type(e).__name__})")
        return False


class Adiar(BaseModel):
    etapa: str = Field(default="montagem", max_length=20)
    motivo: str = Field(default="resposta do avaliador", max_length=200)
    adiar: bool = True
    so_numeros: bool = False         # 159-1: dado do imóvel corrigido — refaz só os números, sem IA


@router.post("/jobs/{jid}/remontar")
async def pedir_remontagem(jid: str, body: Adiar, _u: dict = Depends(_dono)):
    """086-2: o passo respondido guarda o pedido de remontar; com outros passos abertos (adiar) espera o
    "Respondi tudo: atualizar o laudo"; sem (adiar=False) remonta logo, uma vez."""
    _job(jid)
    if body.etapa not in orquestrador.ETAPAS:
        raise HTTPException(status_code=400, detail="etapa inválida")
    if orquestrador.ETAPAS.index(body.etapa) >= orquestrador.ETAPAS.index("redacao"):
        db.set_setting(f"correcao_rapida:{jid}", "1")   # 132-1: remontar texto/PDF confere por regra (sem revisão de IA)
    if getattr(body, "so_numeros", False) and body.etapa == "calculo" and db.resultado(jid, "redacao"):
        # 159-1: dado do imóvel corrigido (área, base, padrão) — refaz só a conta e os números do texto, sem IA
        db.set_setting(f"so_numeros:{jid}", "1")
        db.set_setting(f"correcao_rapida:{jid}", "1")
    p = orquestrador.agendar_remontagem(jid, body.motivo, etapa=body.etapa, atraso=0, esperar=body.adiar)
    if not body.adiar:
        orquestrador.atualizar_agora(jid)
    return {"pendente": orquestrador.remontagem_pendente(jid) or p}


class CorrigirTexto(BaseModel):
    ponto: str = Field(min_length=3, max_length=600)          # o que o JdB não acertou (do passo)
    como_fica: str = Field(min_length=2, max_length=2000)     # o avaliador escreve a frase certa
    adiar: bool = False


@router.post("/jobs/{jid}/texto/corrigir")
async def corrigir_texto(jid: str, body: CorrigirTexto, _u: dict = Depends(_dono)):
    """089-4: "Escreva como deve ficar" — vira correção do avaliador para a redação (obrigatória); a remontagem
    reescreve só a seção atingida (081-7)."""
    _job(jid)
    db.evento(jid, "redacao", "correcao", f"Sobre \"{body.ponto.strip()[:300]}\": o texto deve ficar assim: "
              f"{body.como_fica.strip()}")
    orquestrador.agendar_remontagem(jid, "frase corrigida pelo avaliador", etapa="redacao", atraso=0, esperar=body.adiar)
    if not body.adiar:
        orquestrador.atualizar_agora(jid)
    return {"ok": True, "pendente": orquestrador.remontagem_pendente(jid)}


@router.get("/jobs/{jid}/pdf-previa")
async def pdf_previa(jid: str, _u: dict = Depends(_dono)):
    """093-7: o PDF já montado, enquanto a revisão ainda roda ("PDF pronto — revisando"). Só o PDF (D-073)."""
    j = _job(jid)
    if j.get("etapa") not in ("revisao", "entrega") or not db.resultado(jid, "montagem"):
        raise HTTPException(status_code=404, detail="o PDF ainda não foi montado")
    pdf = orquestrador._arquivos_finais(jid)["pdf"]
    if not pdf.is_file():
        raise HTTPException(status_code=404, detail="o PDF ainda não foi montado")
    return FileResponse(pdf, media_type="application/pdf", filename=f"{pdf.stem} (em revisão).pdf")


@router.get("/jobs/{jid}/revisoes")
async def ver_revisoes(jid: str, _u: dict = Depends(_dono)):
    """109-4: as revisões do laudo, da mais nova para a mais velha, com o que mudou em cada uma."""
    from . import revisoes
    _job(jid)
    return {"revisoes": revisoes.listar(jid)}


@router.post("/jobs/{jid}/revisoes/desfazer")
async def desfazer_revisao(jid: str, _u: dict = Depends(_dono)):
    """109-4: "Desfazer esta revisão" — volta o laudo (arquivos, texto e números) da revisão anterior."""
    from . import revisoes, tela_trabalho
    _job(jid)
    if orquestrador.ocupado(jid) or orquestrador.remontagem_pendente(jid):
        raise HTTPException(status_code=409, detail="Aguarde o laudo terminar de montar para desfazer.")
    if tela_trabalho.aprovado(jid):
        raise HTTPException(status_code=409, detail="Laudo aprovado não pode voltar de revisão.")
    try:
        n = revisoes.desfazer(jid, orquestrador._arquivos_finais(jid))
    except revisoes.NaoDa as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"revisao": n}


@router.post("/jobs/{jid}/reforco/desfazer")
async def desfazer_reforco(jid: str, _u: dict = Depends(_dono)):
    """101-1 (d): [Desfazer] o reforço automático da contestação — o texto volta sem ele (remonta a redação, uma vez)."""
    _job(jid)
    db.set_setting(f"reforco_desfeito:{jid}", "1")
    orquestrador.agendar_remontagem(jid, "reforço da contestação desfeito pelo avaliador", etapa="redacao", atraso=0)
    return {"ok": True}


@router.post("/jobs/{jid}/atualizar")
async def atualizar_laudo(jid: str, _u: dict = Depends(_dono)):
    """086-1/2: "Respondi tudo: atualizar o laudo" / "Terminei de enviar" — aplica o que ficou guardado, uma vez."""
    _job(jid)
    p = orquestrador.atualizar_agora(jid)
    if p is None:
        raise HTTPException(status_code=409, detail="nada esperando para atualizar")
    return {"pendente": p}


@router.get("/jobs/{jid}/remontar")
async def ver_remontagem(jid: str, _u: dict = Depends(_dono)):
    import time
    p = orquestrador.remontagem_pendente(jid)
    if not p:
        return {"pendente": None}
    return {"pendente": {**p, "em_segundos": None if p.get("esperar") else max(0, round(float(p.get("quando") or 0) - time.time()))}}


async def _foto_da_galeria(jid: str, n: int, fotos: list[str]) -> tuple[str, bool]:
    """096-1: (foto principal tirada da galeria do anúncio, a 1ª da galeria era arte?). Tenta até 3 fotos; a que é arte
    de propaganda é pulada. Sem galeria ou sem conseguir baixar: ("", False)."""
    pasta = db.pasta(jid) / "mercado"
    pasta.mkdir(parents=True, exist_ok=True)
    primeira_arte = False
    for i, url in enumerate(fotos[:3]):
        try:
            dados, ext = await _baixar_imagem(url)
        except HTTPException:
            continue
        destino = pasta / f"enviado-{n}-foto.{ext}"
        k = 2
        while destino.exists():
            destino = pasta / f"enviado-{n}-foto-{k}.{ext}"
            k += 1
        destino.write_bytes(dados)
        rel = destino.relative_to(db.pasta(jid)).as_posix()
        if await _foto_e_arte(jid, rel):
            primeira_arte = primeira_arte or i == 0
            destino.unlink(missing_ok=True)
            continue
        return rel, primeira_arte
    return "", primeira_arte


class TrocarFoto(BaseModel):
    url: str = Field(default="", max_length=2000)     # uma das fotos_url do anúncio; vazio + manter = fica a atual
    manter: bool = False
    adiar: bool = False                               # 086-2: há outros passos abertos — aplica no "Respondi tudo"
    sugerida: bool = False                            # 088-1: "Usar" a sugestão do JdB — ela também é conferida


async def _baixar_imagem(url: str) -> tuple[bytes, str]:
    import httpx
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as cli:
        r = await cli.get(url, headers={"User-Agent": "Mozilla/5.0"})
    tipo = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    ext = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp"}.get(tipo)
    if r.status_code != 200 or not ext or not r.content or len(r.content) > 15_000_000:
        raise HTTPException(status_code=502, detail="Não consegui baixar essa foto do anúncio. Tente outra.")
    try:                                      # 089-3: miniatura, ícone ou banner pequeno não é foto principal
        import io
        from PIL import Image
        with Image.open(io.BytesIO(r.content)) as im:
            if max(im.size) < 400:
                raise HTTPException(status_code=409, detail="Essa imagem é pequena demais (não é foto do imóvel). Escolha outra.")
    except HTTPException:
        raise
    except Exception:
        pass
    return r.content, ext


@router.post("/jobs/{jid}/candidatos/{n}/trocar-foto")
async def trocar_foto(jid: str, n: int, body: TrocarFoto, _u: dict = Depends(_dono)):
    """081-5: [Trocar foto] / [Usar] — a foto principal do referencial passa a ser outra foto da galeria
    do mesmo anúncio; [Manter] tira o aviso de arte."""
    _job(jid)                                   # 086-1: aceito mesmo com o trabalho montando ou na fila
    r = next((c for c in db.candidatos(jid) if c.n == n), None)
    if r is None:
        raise HTTPException(status_code=404, detail="referencial não encontrado")
    if body.manter:
        _salvar_ref(jid, r.model_copy(update={"foto_arte": False}), "foto mantida pelo avaliador")
        return {"n": n, "foto": r.foto, "foto_arte": False}
    if body.url not in r.fotos_url:
        raise HTTPException(status_code=400, detail="essa foto não é deste anúncio")
    pasta = db.pasta(jid) / "mercado"
    pasta.mkdir(parents=True, exist_ok=True)
    # 088-1: a sugestão do JdB também passa pela checagem "é arte de anúncio?"; se for, tenta as próximas da galeria.
    # Foto que o avaliador tocou na galeria vale como ele escolheu.
    candidatas = [body.url] + ([u for u in r.fotos_url[r.fotos_url.index(body.url) + 1:]][:3] if body.sugerida else [])
    rel = ""
    for url in candidatas:
        dados, ext = await _baixar_imagem(url)
        k = 2                                  # a foto de antes fica guardada; a nova ganha outro nome
        while (destino := pasta / f"enviado-{n}-foto-{k}.{ext}").exists():
            k += 1
        destino.write_bytes(dados)
        rel_tent = destino.relative_to(db.pasta(jid)).as_posix()
        if body.sugerida and await _foto_e_arte(jid, rel_tent):
            destino.unlink(missing_ok=True)
            continue
        rel = rel_tent
        break
    if not rel:
        raise HTTPException(status_code=409, detail="As próximas fotos também parecem arte de anúncio. "
                                                    "Toque na foto da galeria que mostra a casa.")
    _salvar_ref(jid, r.model_copy(update={"foto": rel, "foto_arte": False, "foto_avaliador": False,
                                          "foto_url_escolhida": body.url}), "com outra foto do anúncio")
    db.evento(jid, "pesquisa", "edicao_manual", f"anúncio nº {n}: foto principal trocada pelo avaliador")
    from . import tela_trabalho
    if db.resultado(jid, "entrega") and not tela_trabalho.aprovado(jid):   # depois do download, troca no Word dele (D-171)
        db.set_setting(f"correcao_rapida:{jid}", "1")       # 173 (D-147): só a tabela de amostras é refeita, sem IA
        orquestrador.agendar_remontagem(jid, f"foto do anúncio nº {n} trocada", etapa="montagem", atraso=0, esperar=body.adiar)
    return {"n": n, "foto": rel, "foto_arte": False}


@router.post("/jobs/{jid}/candidatos/{n}/foto-enviada")
async def foto_enviada(jid: str, n: int, foto: UploadFile = File(...), _u: dict = Depends(_dono)):
    """173-2: [Colar print ou enviar foto] — a foto do avaliador vira a da tabela de amostras, guardada junto do
    referencial e marcada "foto enviada pelo avaliador" (rastreabilidade, princípio 5). Antes do download, a tabela é
    refeita sem IA (D-147)."""
    _job(jid)
    r = next((c for c in db.candidatos(jid) if c.n == n), None)
    if r is None:
        raise HTTPException(status_code=404, detail="referencial não encontrado")
    dados = await foto.read()
    if not dados:
        raise HTTPException(status_code=400, detail="a imagem veio vazia")
    if len(dados) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="foto grande demais (máx. 15 MB)")
    ext = os.path.splitext(_nome_seguro(foto.filename or "foto.png"))[1].lower() or ".png"
    if ext not in imagens.EXT_IMAGEM:
        raise HTTPException(status_code=415, detail="envie uma imagem (JPG ou PNG)")
    pasta = db.pasta(jid) / "mercado"
    pasta.mkdir(parents=True, exist_ok=True)
    k = 1
    while (destino := pasta / f"avaliador-{n}-foto-{k}{ext}").exists() or destino.with_suffix(".jpg").exists():
        k += 1
    destino.write_bytes(dados)
    try:
        if await asyncio.to_thread(imagens.normalizar, destino):
            novo = destino.with_suffix(".jpg")
            destino.rename(novo)
            destino = novo
    except imagens.ImagemInvalida:
        destino.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail="não consegui abrir essa imagem")
    rel = destino.relative_to(db.pasta(jid)).as_posix()
    _salvar_ref(jid, r.model_copy(update={"foto": rel, "foto_arte": False, "foto_avaliador": True, "foto_url_escolhida": ""}),
                "com a foto enviada pelo avaliador")
    db.evento(jid, "pesquisa", "edicao_manual", f"anúncio nº {n}: foto enviada pelo avaliador (vai na tabela de amostras)")
    from . import tela_trabalho
    if db.resultado(jid, "entrega") and not tela_trabalho.aprovado(jid):
        db.set_setting(f"correcao_rapida:{jid}", "1")       # D-147: só a tabela de amostras é refeita, sem IA
        orquestrador.agendar_remontagem(jid, f"foto do anúncio nº {n} enviada pelo avaliador", etapa="montagem", atraso=0, esperar=False)
    return {"n": n, "foto": rel, "foto_arte": False, "foto_avaliador": True}


@router.post("/jobs/{jid}/unitario/media")
async def usar_media(jid: str, _u: dict = Depends(_dono)):
    """082-4: [Usar a média] — tira o unitário fixo; o valor sai da conta da amostra atual."""
    _livre(jid)
    sel = db.resultado(jid, "selecao")
    if not sel:
        raise HTTPException(status_code=409, detail="ainda não há seleção")
    sel.update(unitario_adotado=None, justificativa_unitario="", amostra="")
    db.evento(jid, "selecao", "resultado", "unitário = média da amostra (decisão do avaliador)", dados=sel)
    db.set_setting(f"valor_confirmado:{jid}", "")
    orquestrador.reabrir(jid, "calculo", motivo="avaliador escolheu usar a média")
    orquestrador.enfileirar(jid)
    return {"ok": True}


class RespostaDivergencia(BaseModel):
    campo: str = Field(max_length=20)
    manter: bool = True


@router.post("/jobs/{jid}/candidatos/{n}/divergencia")
async def responder_divergencia(jid: str, n: int, body: RespostaDivergencia, _u: dict = Depends(_dono)):
    """082-2: [Manter] fica o guardado; [Trocar] passa a valer o que a página mostra (e o valor é refeito
    pela conta — 082-4/5: a tela mostra antes quanto o valor passaria a ser)."""
    _job(jid)                                   # 086-1: aceito mesmo com o trabalho montando ou na fila
    r = next((c for c in db.candidatos(jid) if c.n == n), None)
    if r is None:
        raise HTTPException(status_code=404, detail="referencial não encontrado")
    dv = dict(r.divergencia_pagina or {})
    if body.campo not in dv:
        raise HTTPException(status_code=409, detail="essa pergunta já foi respondida")
    novo_v = dv.pop(body.campo)
    upd: dict = {"divergencia_pagina": dv}
    if not body.manter:
        upd[body.campo] = novo_v
    _salvar_ref(jid, r.model_copy(update=upd), "dado da página decidido pelo avaliador")
    db.evento(jid, "pesquisa", "edicao_manual",
              f"anúncio nº {n}: {ROTULO_CAMPO.get(body.campo, body.campo)} "
              + (f"trocado para {_fmt_campo(body.campo, novo_v)} pelo avaliador" if not body.manter
                 else f"mantido em {_fmt_campo(body.campo, getattr(r, body.campo))} pelo avaliador"))
    return {"n": n, "campo": body.campo, "manter": body.manter}


@router.post("/jobs/{jid}/candidatos/enviado")
async def anuncio_enviado(jid: str, body: AnuncioEnviado, _u: dict = Depends(_dono)):
    """"Enviar ao João de Barro": o Alan escolheu o anúncio no Chrome dele e o manda para a
    lista do trabalho como referencial ESCOLHIDO ("enviado pelo avaliador"). O sistema não
    abre nenhuma página: só usa o que veio da página que o Alan estava vendo."""
    import base64
    from . import candidatos as C
    from .agentes import pesquisa as P
    from .agentes.pesquisa import link_limpo
    from .agentes import _comum
    _job(jid)                                   # 086-1: aceito mesmo com o trabalho montando ou na fila
    t = _comum.trabalho(jid)
    link = link_limpo(body.link.strip())
    if not re.match(r"^https?://\S+$", link):
        raise HTTPException(status_code=400, detail="link inválido")
    cands = db.candidatos(jid)
    portal = _portal_do_link(link)
    # ORDEM 077-5: o anúncio cadastrado À MÃO é o mesmo, mesmo com outro jeito de escrever o link
    # (http/https, www, "m." do celular, barra final, parâmetros) ou pelo nº do anúncio no portal
    def _chave(u: str) -> tuple[str, str]:
        from urllib.parse import urlsplit
        x = urlsplit(link_limpo(u.strip()))
        host = re.sub(r"^(?:www\.|m\.|mobile\.)", "", x.netloc.lower())
        return host, (x.path.rstrip("/") + ("?" + x.query if x.query else "")).lower()

    def _id_anuncio(u: str) -> str:
        m = re.search(r"-id-(\d{6,})|/imovel/(\d{6,})(?:/|$)|/(\d{8,})(?:[/-]|$)|-(\d{8,})\.html", u)   # L200: Imovelweb
        return next((g for g in (m.groups() if m else ()) if g), "")

    chave, ident = _chave(link), _id_anuncio(link)
    ja = next((r for r in cands if _chave(r.link) == chave), None) or next(
        (r for r in cands if ident and _id_anuncio(r.link) == ident and _chave(r.link)[0] == chave[0]), None)
    if ja is not None:
        res = await _completar_enviado(jid, ja, body, portal)
        _idade_em_segundo_plano(jid, ja.n)
        return res
    from . import leitura_pagina as LP
    # 091-1/4: só o texto do anúncio (sem "imóveis semelhantes" nem propaganda da página) vai aos leitores
    texto_ad = LP.texto_do_anuncio(body.texto or "", body.titulo or "") or (body.texto or "")
    texto = "\n".join(x for x in (body.titulo, texto_ad) if x)
    lido = C.ler_cartao(C.Cartao(link=link, portal=portal, texto=texto), t.cidade)
    base = lido.model_dump() if lido else {"link": link, "portal": portal}
    # D-064 (b), ORDEM 037-1: página de QUALQUER site -> a IA leve lê preço, áreas, endereço e
    # tipologia do texto (o mesmo leitor do Coletor). IA fora: ficam os dados da página.
    ia_lido = None
    if (body.texto or "").strip():
        from .agentes import leitor_anuncio
        from .coletor_hub import Captura
        try:
            ia_lido = await leitor_anuncio.ler(jid, Captura(ok=True, url_final=link, texto=texto),
                                               portal or "site")
        except Exception as e:
            db.evento(jid, "pesquisa", "aviso", f"anúncio enviado: texto não lido pela IA ({e})")
    area_texto = (ia_lido.area_m2 if ia_lido and ia_lido.area_m2 else (lido.area_m2 if lido else None))
    lote_texto = body.lote_m2 or (ia_lido.lote_m2 if ia_lido else None) or (lido.lote_m2 if lido else None)
    aviso_area = C.conferir_area(body.area_m2, area_texto, lote_texto)
    for k in ("preco", "area_m2", "lote_m2", "quartos", "suites"):
        v = getattr(body, k)
        if v not in (None, 0):
            base[k] = v
    if ia_lido is not None:
        for k in ("preco", "lote_m2", "quartos", "suites", "padrao", "idade_aparente",
                  "publicado_em", "tipologia", "bairro", "rua"):
            v = getattr(ia_lido, k, None)
            if v not in (None, "", 0) and not base.get(k):
                base[k] = v
        if not base.get("area_m2") and ia_lido.area_m2:
            base["area_m2"] = ia_lido.area_m2
    if True:                                # 110-2: estado ("excelente estado…") nunca é gravado como idade;
        from .docx_builder import idade_valida   # "casa nova"/"recém-construída" no texto vale "novo"
        base["idade_aparente"] = idade_valida(str(base.get("idade_aparente") or ""), body.texto or "") or ""
        if base["idade_aparente"]:
            base["idade_fonte"] = "anúncio"
    if aviso_area and area_texto:
        base["area_m2"] = area_texto        # F-S003: o R$/m² usa a construída do texto
    if body.bairro.strip():
        base["bairro"] = body.bairro.strip()
    # 091-4: rua e bairro do caminho de navegação da página quando o lido está claramente errado ("Deztop", "GO",
    # rua com bairro e cidade grudados)
    rua_p, bairro_p = LP.local_da_pagina(body.texto or "", t.cidade)
    if base.get("rua") and "," in str(base.get("rua")):
        r_sep, b_sep = LP.separar_rua(str(base["rua"]), t.cidade)
        base["rua"] = r_sep or base["rua"]
        if b_sep and LP.bairro_ruim(base.get("bairro")):
            base["bairro"] = b_sep
    if LP.bairro_ruim(base.get("bairro")) and bairro_p:
        base["bairro"] = bairro_p
    if not base.get("rua") and rua_p:
        base["rua"] = rua_p
    # 082-3: só a área que se confirma no próprio anúncio (título/link) ou em que extensão e texto concordam;
    # senão "não achei" (o avaliador informa no Corrigir) — nunca o número de um anúncio vizinho da página
    from . import leitura_pagina as LP
    try:                                   # 097-2
        area_conf, motivo_area = LP.area_confirmada(body.titulo, link, body.area_m2 or None, area_texto, texto=texto_ad)
    except TypeError:
        area_conf, motivo_area = LP.area_confirmada(body.titulo, link, body.area_m2 or None, area_texto)
    if area_conf is None and area_texto and "TERRENO" in (aviso_area or ""):
        area_conf = float(area_texto)        # F-S003: o número da página é o lote do próprio texto → vale o do texto
    base["area_m2"] = area_conf
    try:                                   # 098-2: lote só se estiver no texto do próprio anúncio
        lote_ok = LP.lote_confirmado(texto_ad, body.titulo or "", base.get("lote_m2"))
    except Exception:
        lote_ok = base.get("lote_m2")
    base["lote_m2"] = LP.lote_plausivel(lote_ok, area_conf, base.get("tipologia") or t.tipo)
    if base.get("rua"):
        try:
            base["rua"] = LP.logradouro(base["rua"])   # 098-3: "Rua Jc18" → "Rua JC-18"
        except Exception:
            pass
    if not base.get("preco"):
        raise HTTPException(status_code=400, detail="não achei o preço na página: confira o anúncio "
                                                    "ou cadastre em \"Adicionar referencial\"")
    if area_conf is None:
        aviso_area = motivo_area or "área não encontrada no anúncio: informe no Corrigir"
    n = max((r.n for r in cands), default=0) + 1
    tela = _gravar_data_url(jid, body.imagem, f"enviado-{n}")
    foto = _gravar_data_url(jid, body.foto_principal, f"enviado-{n}-foto") or tela
    arte_galeria = None
    if not foto:                                         # 096-1: envio sozinho sem foto → a 1ª da galeria que não é arte
        foto, arte_galeria = await _foto_da_galeria(jid, n, _fotos_url(body.fotos_url))
    base.update(n=n, link=link, portal=portal or base.get("portal") or "", titulo=(body.titulo or base.get("titulo") or "")[:300],
                descricao=LP.descricao_limpa(body.texto or "", body.titulo or ""),   # 092-1: só o texto do anúncio
                foto=foto or base.get("foto") or "", print_=tela,
                fonte_coleta="avaliador", coletado=True, bloqueado=False, decisao="entra",
                rodada=max((r.rodada for r in cands), default=1))
    from .modelos import Referencial
    for k, f in Referencial.model_fields.items():   # L200 (Caso M): página que não vira cartão deixava campo
        if f.is_required() and k not in base:       # obrigatório de fora (ex.: padrão) e o envio dava erro 500
            base[k] = "" if f.annotation in (str, "str") else None
    r = C.avaliar(Referencial.model_validate(base), P.avaliando(jid))
    obs = "; ".join(x for x in ("enviado pelo avaliador (Chrome)", aviso_area, r.observacao) if x)
    if aviso_area:
        db.evento(jid, "pesquisa", "aviso", f"anúncio nº {n}: {aviso_area}")
    prova = _prova_enviada(jid, n, body, link, portal)     # D-082
    prova.pop("prova_pagina_pdf", None)
    try:                                   # 097-1: link colado pelo passo da comparação nasce "só comparação"
        from .rotas_extensao import destino_colado
        destino = destino_colado(jid, link)
    except Exception:
        destino = None
    dec = "comparacao" if destino == "comparacao" else "entra"
    r = r.model_copy(update={"observacao": obs[:300], "decisao": dec, **prova,
                             **({"escolhido": False, "nao_recomendado": False} if dec == "comparacao" else {})})
    fotos_n = _fotos_url(body.fotos_url)
    if fotos_n:
        r = r.model_copy(update={"fotos_url": fotos_n})
    try:                                   # 100-8: o destaque sai do texto inteiro da página (que não fica guardado)
        r = r.model_copy(update={"destaque": LP.destaque(body.texto or "", body.titulo or "")[:200]})
    except Exception:
        pass
    if arte_galeria is not None:
        r = r.model_copy(update={"foto_arte": arte_galeria})
    elif r.foto:                                         # 093-A-10: anúncio novo também passa pela checagem de arte
        r = r.model_copy(update={"foto_arte": await _foto_e_arte(jid, r.foto)})
    if r.foto_arte and len(r.fotos_url) >= 2:            # 102-4: troca sozinho pela 1ª da galeria que não é arte e avisa
        rel_g, _ = await _foto_da_galeria(jid, n, r.fotos_url[1:])
        if rel_g:
            r = r.model_copy(update={"foto": rel_g, "foto_arte": False})
            db.evento(jid, "pesquisa", "aviso", f"Troquei a foto do anúncio {n}: a 1ª era propaganda (aviso ao "
                      "avaliador, não é reprovação; para outra, use Trocar foto na tela dos anúncios)")
    db.salvar_candidatos(jid, [r])
    P.exportar(jid)
    _idade_em_segundo_plano(jid, n)
    db.evento(jid, "pesquisa", "edicao_manual", f"anúncio enviado pelo avaliador (Chrome): nº {n} "
              f"({portal or 'site'}, {r.area_m2 or 'área a informar'} m², R$ {r.preco:,.0f})".replace(",", "."))
    return {"n": n, "portal": portal, "area_m2": r.area_m2, "preco": r.preco,
            "unitario": round(r.preco / r.area_m2, 2) if r.area_m2 else None, "motivo": r.motivo, "observacao": r.observacao}


@router.post("/jobs/{jid}/datas/confirmar")
async def confirmar_datas(jid: str, _u: dict = Depends(_dono)):
    """ORDEM 034-3: "A data está certa" — o avaliador confirma a data da vistoria mesmo com fotos
    de outra data; o aviso fica como confirmado (vale para ESTA data)."""
    from . import datas_fotos
    j = _job(jid)
    dv = str((j.get("dados") or {}).get("data_vistoria") or "")[:10]
    if not dv:
        raise HTTPException(status_code=400, detail="trabalho sem data da vistoria")
    db.set_setting(datas_fotos.chave_confirmada(jid), dv)
    db.evento(jid, "orquestrador", "edicao_manual", f"data da vistoria {dv} confirmada pelo avaliador "
              "(fotos com outra data)")
    return {"alerta_datas": _alerta_datas(jid, db.job(jid))}


class Pin(BaseModel):
    link: str = Field(min_length=10, max_length=500)


@router.post("/jobs/{jid}/pin")
async def gravar_pin(jid: str, body: Pin, _u: dict = Depends(_dono)):
    """075-B: "Colar o link do Google Maps" — grava o pin no trabalho e gera a imagem demarcada."""
    from .agentes import _comum
    from .conversa import _PIN
    m = _PIN.search(body.link or "")
    if not m:
        raise HTTPException(status_code=400, detail="isso não parece um link do Google Maps")
    _livre(jid)
    t = _comum.trabalho(jid)
    db.atualizar_dados(jid, t.model_copy(update={"pin_maps": m.group(0).rstrip(".,;:!?")}))
    return await refazer_mapa(jid, _u=_u)


@router.post("/jobs/{jid}/mapa/refazer")
async def refazer_mapa(jid: str, _u: dict = Depends(_dono)):
    """ORDEM 033-1: nova captura do Google Maps pelo Coletor (só o Maps, painel recolhido) e
    nova demarcação do lote. Não abre portal nenhum. O laudo usa o mapa novo na próxima montagem."""
    from . import coletor_fonte, coletor_hub
    from .agentes import _comum
    _livre(jid)
    t = _comum.trabalho(jid)
    if not t.pin_maps:
        raise HTTPException(status_code=400, detail="trabalho sem link do Google Maps")
    if not coletor_hub.online():
        # 088-2: resposta clara, nunca silêncio — o mapa atual (quadrado em volta do pino) continua valendo
        raise HTTPException(status_code=409, detail="Não consegui refazer agora: o navegador do JdB (Coletor) está "
                                                    "desligado. O laudo segue com o lote marcado em volta do pino; "
                                                    "ligue o Coletor e toque de novo, ou toque em Seguir assim.")
    def _ultimo():
        with db._conn() as c:
            return c.execute("SELECT COALESCE(MAX(id),0) FROM av_events WHERE job=? AND etapa='localizacao' "
                             "AND nivel='resultado'", (jid,)).fetchone()[0]
    antes = _ultimo()
    ia.definir_contexto(jid, "localizacao")   # custo e limite de tentativas contam neste trabalho
    await coletor_fonte.capturar_maps(jid, t, refazer=True)
    novo = db.resultado(jid, "localizacao")
    if novo is None or _ultimo() == antes:
        raise HTTPException(status_code=502, detail="mapa não capturado (veja os avisos do trabalho)")
    db.evento(jid, "localizacao", "edicao_manual", "mapa refeito pelo avaliador (Coletor, só o Google Maps)")
    return {"poligono": novo.get("poligono"), "pino": novo.get("pino")}


@router.post("/jobs/{jid}/voltar-lista")
async def voltar_para_lista(jid: str, _u: dict = Depends(_dono)):
    """ORDEM 010: "Voltar para a lista" no Confirmar valor — volta à escolha de candidatos
    (pausa da pesquisa) sem perder o que já foi marcado; nada roda até "Continuar"."""
    j = _livre(jid)
    if j["status"] != orquestrador.AGUARDANDO:
        raise HTTPException(status_code=409, detail="só durante a confirmação do valor")
    db.evento(jid, "pesquisa", "info", "avaliador voltou para a lista de candidatos")
    db.set_etapa(jid, "pesquisa", orquestrador.AGUARDANDO)
    return {"id": jid, "etapa": "pesquisa"}


# ------------------------------------------------------------------ referencial manual
def _portal_do_link(link: str) -> str:
    from urllib.parse import urlsplit
    host = (urlsplit(link).hostname or "").lower()
    for dom, nome in (("zapimoveis", "ZAP Imóveis"), ("vivareal", "Viva Real"), ("olx", "OLX"),
                      ("imovelweb", "Imovelweb"), ("chavesnamao", "Chaves na Mão")):
        if dom in host:
            return nome
    return host.removeprefix("www.") or "—"


def _num_form(v: str | None, nome: str, obrigatorio: bool = False) -> float | None:
    from decimal import InvalidOperation

    from .agentes import selecao
    if not (v or "").strip() or (v or "").strip().lower() in ("n/i", "ni", "-", "—"):
        if obrigatorio:
            raise HTTPException(status_code=400, detail=f"{nome}: obrigatório")
        return None
    try:
        x = float(selecao._decimal_br(v))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail=f"{nome}: número inválido")
    if x <= 0:
        raise HTTPException(status_code=400, detail=f"{nome}: deve ser maior que zero")
    return x


def _n_cid(t: str) -> str:
    import unicodedata as _u
    return " ".join(_u.normalize("NFKD", t or "").encode("ascii", "ignore").decode().casefold().split())


@router.post("/jobs/{jid}/referenciais/manual")
async def adicionar_referencial(jid: str, link: str = Form(""), area_m2: str = Form(...),
                                preco: str = Form(...), portal: str = Form(""),
                                localizacao: str = Form(""), bairro: str = Form(""),
                                tipologia: str = Form(""), quartos: str = Form(""),
                                suites: str = Form(""), lote_m2: str = Form(""),
                                idade_estado: str = Form(""), padrao: str = Form(""),
                                descricao: str = Form(""),
                                foto: UploadFile | None = File(None),
                                decisao: str = Form("entra"),
                                pesquisa_campo: str = Form(""), data_pesquisa: str = Form(""),
                                informante: str = Form(""), negocio: str = Form(""), cidade: str = Form(""),
                                _u: dict = Depends(_dono)):
    """Referencial cadastrado pelo avaliador (funciona com o Coletor desligado). Entra
    escolhido; a IA da seleção não o exclui (só avisa). R$/m² calculado pelo sistema.
    153-4: de PESQUISA DE CAMPO (pesquisa_campo=1): sem link; a data da pesquisa é obrigatória."""
    from .agentes.pesquisa import link_limpo
    from .modelos import Referencial
    _livre(jid)
    # 153-4: chamada direta (sem o FastAPI preencher o Form) — os campos novos valem vazio
    pesquisa_campo, data_pesquisa, informante, negocio, cidade = (
        x if isinstance(x, str) else "" for x in (pesquisa_campo, data_pesquisa, informante, negocio, cidade))
    link = link if isinstance(link, str) else ""
    link = link.strip()
    campo = pesquisa_campo.strip().lower() in ("1", "true", "sim", "on")
    data_iso = ""
    if campo:
        m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$", data_pesquisa) or re.match(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$", data_pesquisa)
        if not m:
            raise HTTPException(status_code=400, detail="informe a data da pesquisa de campo (dd/mm/aaaa)")
        g = m.groups()
        data_iso = f"{g[2]}-{int(g[1]):02d}-{int(g[0]):02d}" if "/" in data_pesquisa else f"{g[0]}-{g[1]}-{g[2]}"
        if link and not re.match(r"^https?://\S+$", link):
            link = ""
    elif not re.match(r"^https?://\S+$", link):
        raise HTTPException(status_code=400, detail="link inválido (comece com http:// ou https://)")
    link = link_limpo(link) if link else ""
    area = _num_form(area_m2, "área construída", obrigatorio=True)
    valor = _num_form(preco, "preço", obrigatorio=True)
    lote = _num_form(lote_m2, "terreno")

    def _int(v: str, nome: str) -> int | None:
        x = _num_form(v, nome)
        return int(x) if x is not None else None
    cands = db.candidatos(jid)
    if link and any(r.link and link_limpo(r.link) == link for r in cands):
        raise HTTPException(status_code=409, detail="esse link já está na lista de referenciais")
    n = max((r.n for r in cands), default=0) + 1
    rel_foto = ""
    if foto is not None and (foto.filename or "").strip():
        pasta = db.pasta(jid) / "mercado"
        pasta.mkdir(parents=True, exist_ok=True)
        ext = os.path.splitext(_nome_seguro(foto.filename))[1].lower() or ".jpg"
        if ext not in imagens.EXT_IMAGEM:
            raise HTTPException(status_code=415, detail="foto: envie JPG ou PNG")
        destino = pasta / f"manual-{n}-{uuid.uuid4().hex[:6]}{ext}"
        dados = await foto.read()
        if len(dados) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="foto maior que 50 MB")
        destino.write_bytes(dados)
        try:
            if await asyncio.to_thread(imagens.normalizar, destino):
                novo = destino.with_suffix(".jpg")
                destino.rename(novo)
                destino = novo
        except imagens.ImagemInvalida:
            destino.unlink(missing_ok=True)
            raise HTTPException(status_code=415, detail="foto: não foi possível abrir a imagem")
        rel_foto = f"mercado/{destino.name}"
    loc = localizacao.strip()
    # 153-4: a cidade da pesquisa de campo só entra no endereço quando é outra (o laudo já põe a cidade do trabalho)
    try:
        cid_job = str((db.job(jid).get("dados") or {}).get("cidade") or "")
    except Exception:
        cid_job = ""
    if cidade.strip() and _n_cid(cidade) != _n_cid(cid_job) and _n_cid(cidade) not in _n_cid(loc):
        loc = ", ".join(x for x in (loc, cidade.strip()) if x)
    if campo and negocio.strip().lower() == "venda":
        descricao = ("Venda realizada (não é oferta). " + descricao.strip()).strip()
    r = Referencial(
        n=n, link=link, portal=("Pesquisa de campo" if campo else (portal.strip() or _portal_do_link(link))),
        bairro=bairro.strip() or loc, tipologia=tipologia.strip() or "—",
        quartos=_int(quartos, "quartos"), suites=_int(suites, "suítes"), lote_m2=lote,
        area_m2=area, preco=valor, padrao=padrao.strip(), idade_aparente=idade_estado.strip(),
        descricao=(f"Localização: {loc}. " if loc else "") + descricao.strip(),
        # 084-3: "Só comparação" nasce fora da amostra (nunca conta na média, nem por um instante)
        foto=rel_foto, fonte_coleta="manual", escolhido=decisao != "comparacao",
        decisao="comparacao" if decisao == "comparacao" else "entra", coletado=True,
        justificativa="escolhido pelo avaliador", rodada=max((x.rodada for x in cands), default=1),
        titulo=(descricao.strip() or tipologia.strip())[:160], rua=loc[:80],
        pesquisa_campo=campo, data_pesquisa=data_iso, acessado_em=data_iso, informante=informante.strip()[:120],
        negocio=negocio.strip().lower() if negocio.strip().lower() in ("oferta", "venda") else "")
    db.salvar_candidatos(jid, [r])
    db.evento(jid, "pesquisa", "edicao_manual",
              f"referencial {n} cadastrado pelo avaliador: {r.portal}, {r.bairro}, "
              f"{selecao_br(area)} m², R$ {selecao_br(valor)}",
              dados={"referencial": r.model_dump(mode="json")})
    return {**r.model_dump(mode="json"), "unitario": round(valor / area, 2)}


class Links(BaseModel):
    links: list[str] = Field(min_length=1, max_length=10)


@router.post("/jobs/{jid}/referenciais/ler-links")
async def ler_links(jid: str, body: Links, _u: dict = Depends(_dono)):
    """073-3 / 112: o avaliador cola um ou vários links. Sem busca automática (D-117), o JdB não abre o anúncio:
    quem traz foto e dados é a extensão "Enviar ao JdB" no Chrome do avaliador (ou o cadastro à mão)."""
    from .agentes.pesquisa import link_limpo
    _livre(jid)
    ja = {link_limpo(r.link) for r in db.candidatos(jid)}
    out = []
    for bruto in body.links:
        link = bruto.strip()
        if not re.match(r"^https?://\S+$", link):
            out.append({"link": link, "erro": "Isso não parece um link de anúncio (comece com http:// ou https://)."})
            continue
        link = link_limpo(link)
        if link in ja:
            out.append({"link": link, "erro": "Esse anúncio já está na lista."})
            continue
        out.append({"link": link, "erro": "Abra o anúncio no seu Chrome: vai aparecer o botão Enviar ao JdB no canto da "
                                          "página, para trazer foto e dados. Ou preencha à mão aqui."})
    return {"anuncios": out}


def selecao_br(x: float) -> str:
    from .agentes.selecao import _br
    return _br(x)


@router.delete("/jobs/{jid}/referenciais/{n}")
async def remover_referencial(jid: str, n: int, _u: dict = Depends(_dono)):
    """Remove um referencial cadastrado pelo avaliador (os do Coletor só se desmarcam)."""
    _livre(jid)
    cands = db.candidatos(jid)
    alvo = next((r for r in cands if r.n == n), None)
    if alvo is None:
        raise HTTPException(status_code=404, detail="referencial não encontrado")
    if alvo.fonte_coleta != "manual":
        raise HTTPException(status_code=400, detail="só referencial cadastrado à mão pode ser removido; desmarque os demais")
    db.salvar_candidatos(jid, [r for r in cands if r.n != n], substituir=True)
    db.evento(jid, "pesquisa", "edicao_manual", f"referencial {n} removido pelo avaliador",
              dados={"removido": alvo.model_dump(mode="json")})
    return {"ok": True}


# ------------------------------------------------------------------ lista de candidatos
class Decisao(BaseModel):
    decisao: Literal["", "entra", "descarta", "comparacao"]
    motivo: str = Field(default="", max_length=200)


@router.put("/jobs/{jid}/candidatos/{n}")
async def decidir_candidato(jid: str, n: int, body: Decisao, _u: dict = Depends(_dono)):
    """"Entra no laudo" / "Descartar" (motivo opcional) / "" (desfaz) num candidato da lista."""
    _livre(jid)
    cands = db.candidatos(jid)
    r = next((x for x in cands if x.n == n), None)
    if r is None:
        raise HTTPException(status_code=404, detail="candidato não encontrado")
    if body.decisao == "entra" and not (r.area_m2 and r.preco):
        raise HTTPException(status_code=400, detail="candidato sem área ou preço: complete os "
                                                    "dados (cadastre como referencial manual)")
    upd: dict = {"decisao": body.decisao,
                 "motivo_descarte": body.motivo.strip() if body.decisao == "descarta" else ""}
    if body.decisao == "comparacao":      # 080-4 / 084-3: só comparação nunca entra na conta
        upd["escolhido"] = False
    novo = r.model_copy(update=upd)
    _salvar_ref(jid, novo, "marcado pelo avaliador")
    db.evento(jid, "pesquisa", "edicao_manual",
              f"candidato nº {n}: " + {"entra": "entra no laudo", "descarta": "descartado",
                                       "comparacao": "só comparação (fora da amostra)",
                                       "": "decisão desfeita"}[body.decisao]
              + (f" ({body.motivo.strip()})" if body.motivo.strip() else ""))
    from .agentes import pesquisa as _p
    _p.exportar(jid)
    entra = sum(1 for x in db.candidatos(jid) if x.decisao == "entra")
    return {**novo.model_dump(mode="json"), "total_entra": entra}


class IdadeAnuncio(BaseModel):
    idade: str = Field(min_length=1, max_length=60)


@router.put("/jobs/{jid}/candidatos/{n}/idade")
async def corrigir_idade(jid: str, n: int, body: IdadeAnuncio, _u: dict = Depends(_dono)):
    """110-2: o avaliador corrige a idade aparente do anúncio na tela de Escolha (vale a dele)."""
    from . import pendencias_simples as PS
    _livre(jid)
    r = next((x for x in db.candidatos(jid) if x.n == n), None)
    if r is None:
        raise HTTPException(status_code=404, detail="anúncio não encontrado")
    idade = body.idade.strip()
    if re.fullmatch(r"\d{1,3}", idade):
        idade += " anos"
    _salvar_ref(jid, r.model_copy(update={"idade_aparente": idade, "idade_fonte": "avaliador"}), "idade corrigida")
    PS.aceitar(jid, f"idade_foto:{n}")
    db.evento(jid, "pesquisa", "edicao_manual", f"anúncio {n}: idade aparente corrigida pelo avaliador: {idade}")
    return {"n": n, "idade_aparente": idade, "idade_fonte": "avaliador"}


@router.post("/jobs/{jid}/candidatos/reordenar")
async def reordenar_candidatos(jid: str, _u: dict = Depends(_dono)):
    """D-056: reavalia a lista do mais parecido para o menos, com o porquê de cada um."""
    from .agentes import pesquisa as _p
    _livre(jid)
    refs = await asyncio.to_thread(_p.reavaliar, jid)
    return {"ordem": [r.n for r in refs]}


class PedidoMais(BaseModel):
    orientacao: str = Field(default="", max_length=300)


@router.post("/jobs/{jid}/pesquisa/mais", status_code=202)
async def pedir_mais(jid: str, body: PedidoMais, _u: dict = Depends(_dono)):
    """"Pedir mais referenciais" (orientação opcional): roda em segundo plano, continua a
    numeração, sem repetir nem duplicar. O andamento sai na linha do tempo."""
    from .agentes import pesquisa as _p
    _livre(jid)
    orquestrador._ativos.add(jid)

    async def _rodar():
        tok = ia.definir_contexto(jid, "pesquisa")
        try:
            db.evento(jid, "pesquisa", "info", "pedido de mais referenciais"
                      + (f": {body.orientacao.strip()}" if body.orientacao.strip() else ""))
            novos = await _p.montar_lista(jid, body.orientacao.strip())
            if not novos:
                db.evento(jid, "pesquisa", "aviso", "nenhum candidato novo encontrado")
        except Exception as e:
            log.exception("pedir mais %s", jid)
            db.evento(jid, "pesquisa", "erro", f"pedido de mais referenciais falhou: {e}"[:300])
        finally:
            ia._ctx.reset(tok)
            orquestrador._ativos.discard(jid)
    asyncio.get_running_loop().create_task(_rodar())
    return {"id": jid, "pedido": True}


@router.post("/jobs/{jid}/pesquisa/continuar", status_code=202)
async def continuar_pesquisa(jid: str, _u: dict = Depends(_dono)):
    """Confirma a escolha (≥ 5 "Entra no laudo"): abre os anúncios escolhidos e segue."""
    from .agentes.selecao import MIN_ESCOLHIDOS
    _livre(jid)
    entra = [x for x in db.candidatos(jid)
             if x.decisao == "entra" or (x.fonte_coleta == "manual" and x.decisao != "descarta")]
    if len(entra) < MIN_ESCOLHIDOS:
        raise HTTPException(status_code=400, detail=(
            f"escolha pelo menos {MIN_ESCOLHIDOS} referenciais (marcados: {len(entra)}); "
            "se faltar semelhante, complete com menos semelhantes e justifique (D-021)"))
    db.evento(jid, "pesquisa", "escolha", f"{len(entra)} referenciais escolhidos: "
              + ", ".join(f"nº {x.n}" for x in sorted(entra, key=lambda x: x.n)),
              dados={"entra": [x.n for x in entra]})
    orquestrador.reabrir(jid, "pesquisa", motivo="escolha de referenciais confirmada")
    orquestrador.enfileirar(jid)
    return {"id": jid, "entra": [x.n for x in entra]}


@router.get("/jobs/{jid}/candidatos.{fmt}")
async def exportar_candidatos(jid: str, fmt: Literal["md", "xlsx"], _u: dict = Depends(_dono)):
    from .agentes import pesquisa as _p
    _job(jid)
    md, xlsx = _p.exportar(jid)
    p = md if fmt == "md" else xlsx
    return FileResponse(p, filename=f"candidatos-{db.job(jid)['numero']}.{fmt}")


# ------------------------------------------------------------------ excluir / número
def _laudo_gerado(jid: str) -> bool:
    ent = db.resultado(jid, "entrega") or {}
    return bool(ent.get("arquivos"))


@router.delete("/jobs/{jid}")
async def excluir_trabalho(jid: str, _u: dict = Depends(_dono)):
    """Exclui o trabalho (dados, arquivos e eventos) e libera o número. Não exclui trabalho em execução."""
    j = _livre(jid)
    with db._conn() as c:
        for tab in ("av_events", "av_candidates", "av_fields", "av_files", "av_ia_chamadas"):
            c.execute(f"DELETE FROM {tab} WHERE job=?", (jid,))
        c.execute("DELETE FROM av_jobs WHERE id=?", (jid,))
    shutil.rmtree(db.pasta(jid), ignore_errors=True)
    log.info("trabalho %s (nº %s) excluído pelo avaliador", jid, j["numero"])
    return {"ok": True, "numero_liberado": j["numero"]}


class NovoNumero(BaseModel):
    numero: int


@router.put("/jobs/{jid}/numero")
async def trocar_numero(jid: str, body: NovoNumero, _u: dict = Depends(_dono)):
    """Troca o número enquanto o laudo não foi gerado."""
    j = _livre(jid)
    if _laudo_gerado(jid):
        raise HTTPException(status_code=409, detail="o laudo já foi gerado com este número; "
                                                    "exclua o trabalho para reaproveitar")
    if body.numero == j["numero"]:
        return {"numero": body.numero}
    if db.numero_usado(body.numero):
        raise HTTPException(status_code=409, detail="número já usado")
    t = Trabalho(**{**j["dados"], "id": jid, "numero": body.numero})
    with db._conn() as c:
        c.execute("UPDATE av_jobs SET numero=?, dados_json=? WHERE id=?",
                  (body.numero, t.model_dump_json(), jid))
    db.evento(jid, "orquestrador", "edicao_manual", f"número alterado: {j['numero']} → {body.numero}")
    return {"numero": body.numero}


# ------------------------------------------------------------------ conferir tarjas
DPI_PAGINA = 144      # PDF na tela de tarjas: 144 dpi = 2 px por ponto PDF
_ESC_PAGINA = DPI_PAGINA / 72


def _paginas_pdf(jid: str, rel: str) -> list[Path]:
    """Páginas do PDF enviado em PNG (cache em <job>/_paginas/<arquivo>/), geradas no envio
    ou na primeira abertura. As caixas da extração ficam em pontos PDF (chave "<arquivo>#pN")."""
    p = db.pasta(jid) / rel
    pasta = db.pasta(jid) / "_paginas" / rel.replace("/", "__")
    prontas = sorted(pasta.glob("pagina-*.png")) if pasta.is_dir() else []
    if prontas and prontas[0].stat().st_mtime >= p.stat().st_mtime:
        return prontas
    return imagens.pdf_paginas_png(p, pasta, dpi=DPI_PAGINA)


def _chave_tarja(arquivo: str) -> tuple[str, int | None]:
    """"solicitante/x.pdf#p2" -> ("solicitante/x.pdf", 2); imagem -> (arquivo, None)."""
    m = re.fullmatch(r"(.+\.pdf)#p(\d+)", arquivo, re.I)
    return (m.group(1), int(m.group(2))) if m else (arquivo, None)


@router.get("/jobs/{jid}/tarjas")
async def ler_tarjas(jid: str, _u: dict = Depends(_dono)):
    """Documentos do solicitante com as caixas de tarja propostas (pixels da imagem). PDF:
    uma entrada por página ("<arquivo>#pN"), com a página em imagem e as caixas convertidas
    de pontos PDF para pixels."""
    _job(jid)
    ext = db.resultado(jid, "extracao") or {}
    tj = ext.get("tarjas") or {}
    conferidas = ext.get("tarjas_conferidas") or []
    out = []
    for a in db.arquivos(jid):
        if a["tipo"] != "solicitante":
            continue
        p = db.pasta(jid) / a["caminho"]
        if p.suffix.lower() == ".pdf" and p.is_file():
            from PIL import Image
            pags = await asyncio.to_thread(_paginas_pdf, jid, a["caminho"])
            for n, png in enumerate(pags, start=1):
                with Image.open(png) as im:
                    w, h = im.size
                caixas = tj.get(f"{a['caminho']}#p{n}") or tj.get(f"{a['nome']}#p{n}") or []
                out.append({"arquivo": f"{a['caminho']}#p{n}",
                            "nome": a["nome"] + (f" – página {n}" if len(pags) > 1 else ""),
                            "largura": w, "altura": h, "imagem": True,
                            "url": f"/jobs/{jid}/pagina/{n}/{a['caminho']}",
                            "caixas": [[round(float(v) * _ESC_PAGINA) for v in c[:4]]
                                       for c in caixas if len(c) >= 4],
                            "conferido": f"{a['caminho']}#p{n}" in conferidas})
            continue
        dims = None
        if p.suffix.lower() in imagens.EXT_IMAGEM and p.is_file():
            from PIL import Image
            with Image.open(p) as im:
                dims = im.size
        out.append({"arquivo": a["caminho"], "nome": a["nome"], "largura": dims[0] if dims else None,
                    "altura": dims[1] if dims else None, "imagem": dims is not None,
                    "caixas": tj.get(a["caminho"]) or tj.get(a["nome"]) or [],
                    "conferido": a["caminho"] in (ext.get("tarjas_conferidas") or [])})
    return out


class Tarjas(BaseModel):
    arquivo: str
    caixas: list[list[int]]


@router.put("/jobs/{jid}/tarjas")
async def gravar_tarjas(jid: str, body: Tarjas, _u: dict = Depends(_dono)):
    """Caixas conferidas pelo avaliador (mover/apagar/desenhar): gravadas no resultado da
    extração e marcadas como conferidas (a montagem usa folga mínima nelas)."""
    _livre(jid)
    base, pagina = _chave_tarja(body.arquivo)
    if base not in {a["caminho"] for a in db.arquivos(jid) if a["tipo"] == "solicitante"}:
        raise HTTPException(status_code=404, detail="documento do solicitante não encontrado")
    caixas = [c[:4] for c in body.caixas if len(c) >= 4 and c[2] > c[0] and c[3] > c[1]]
    if pagina is not None:   # pixels da página na tela -> pontos PDF (como a extração grava)
        caixas = [[round(v / _ESC_PAGINA, 1) for v in c] for c in caixas]
    with db._conn() as c:
        r = c.execute("SELECT id, dados_json FROM av_events WHERE job=? AND etapa='extracao' AND "
                      "nivel='resultado' ORDER BY id DESC LIMIT 1", (jid,)).fetchone()
        if r is None:
            raise HTTPException(status_code=409, detail="a extração ainda não rodou")
        d = json.loads(r["dados_json"] or "{}")
        d.setdefault("tarjas", {})[body.arquivo] = caixas
        d["tarjas_conferidas"] = sorted(set(d.get("tarjas_conferidas") or []) | {body.arquivo})
        c.execute("UPDATE av_events SET dados_json=? WHERE id=?", (json.dumps(d, ensure_ascii=False), r["id"]))
    db.evento(jid, "extracao", "edicao_manual", f"tarjas conferidas pelo avaliador: {body.arquivo} "
              f"({len(caixas)} caixas)")
    return {"arquivo": body.arquivo, "caixas": caixas, "conferido": True}


@router.get("/jobs/{jid}/pagina/{n}/{caminho:path}")
async def ver_pagina(jid: str, n: int, caminho: str, _u: dict = Depends(_dono)):
    """Página N (a partir de 1) de um PDF enviado, em PNG — prévia na tela de tarjas."""
    _job(jid)
    if caminho not in {a["caminho"] for a in db.arquivos(jid)} or not caminho.lower().endswith(".pdf"):
        raise HTTPException(status_code=404)
    pags = await asyncio.to_thread(_paginas_pdf, jid, caminho)
    if not 1 <= n <= len(pags):
        raise HTTPException(status_code=404)
    return FileResponse(pags[n - 1], media_type="image/png")


@router.get("/jobs/{jid}/arquivo/{caminho:path}")
async def ver_arquivo(jid: str, caminho: str, _u: dict = Depends(_dono)):
    """Arquivo enviado (só os registrados no trabalho) — prévia na tela de tarjas."""
    _job(jid)
    if caminho not in {a["caminho"] for a in db.arquivos(jid)}:
        raise HTTPException(status_code=404)
    p = (db.pasta(jid) / caminho).resolve()
    if not p.is_file() or not p.is_relative_to(db.pasta(jid).resolve()):
        raise HTTPException(status_code=404)
    return FileResponse(p)


# ------------------------------------------------------------------ logo do avaliador
@router.get("/config/logo")
async def ver_logo(_u: dict = Depends(_dono)):
    from . import avaliadores, identidade
    p = identidade.caminho_logo() if av_atual() == "AV-0001" else avaliadores.logo(av_atual())
    if p is None:
        raise HTTPException(status_code=404, detail="sem logo cadastrada")
    return FileResponse(p, media_type="image/png")


@router.post("/config/logo")
async def enviar_logo(arquivo: UploadFile = File(...), _u: dict = Depends(_dono)):
    """Logo horizontal do avaliador (PNG, de preferência com fundo transparente)."""
    if av_atual() != "AV-0001":       # ORDEM 042: outro avaliador envia a logo dele (não troca a do Alan)
        from . import rotas_avaliadores
        return await rotas_avaliadores.enviar_logo(arquivo, _u=_u)
    from PIL import Image

    from . import identidade
    dados = await arquivo.read()
    if len(dados) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="logo maior que 10 MB")
    import io
    try:
        with Image.open(io.BytesIO(dados)) as im:
            im.load()
            if im.format != "PNG":
                raise HTTPException(status_code=415, detail="envie a logo em PNG")
            larg, alt = im.size
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=415, detail="não foi possível abrir a imagem")
    destino = identidade.LOGO_ENVIADA
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(dados)
    return {"ok": True, "largura": larg, "altura": alt}


class Reabertura(BaseModel):
    etapa: Literal["triagem", "extracao", "pesquisa", "selecao", "calculo", "redacao", "montagem"]


@router.post("/jobs/{jid}/reabrir", status_code=202)
async def reabrir(jid: str, body: Reabertura, _u: dict = Depends(_dono)):
    """Reprocessar documentos (extracao) / recalcular (calculo) / regerar documento
    (redacao ou montagem)."""
    _livre(jid)
    orquestrador.reabrir(jid, body.etapa, motivo=f"reaberto pelo avaliador a partir de {body.etapa}")
    orquestrador.enfileirar(jid)
    return {"id": jid, "etapa": body.etapa, "enfileirado": True}


@router.post("/jobs/{jid}/cancelar")
async def cancelar(jid: str, _u: dict = Depends(_dono)):
    """"Cancelar" (ORDEM 007): rodando, interrompe no fim da chamada de IA em andamento ou
    entre etapas; parado/esperando, cancela na hora. Status final CANCELADO (o custo já gasto
    não volta); depois dá para "Reabrir" (retomar) ou excluir."""
    _job(jid)
    st = orquestrador.pedir_cancelamento(jid)
    return {"id": jid, "status": st, "mensagem": orquestrador.CUSTO_NAO_VOLTA
            if st == orquestrador.CANCELADO else "cancelamento pedido; para no fim da etapa em andamento"}


@router.post("/jobs/{jid}/retomar", status_code=202)
async def retomar(jid: str, _u: dict = Depends(_dono)):
    """Reabre um trabalho CANCELADO de onde parou, reaproveitando tudo o que já foi feito
    (sem barreira de volta: nada já pago é refeito)."""
    j = _livre(jid)
    if j["status"] != orquestrador.CANCELADO:
        raise HTTPException(status_code=409, detail="só trabalho cancelado pode ser retomado")
    db.evento(jid, "orquestrador", "info", "retomado pelo avaliador depois de cancelado")
    db.arquivar_entrega(jid)
    db.set_etapa(jid, "triagem", "pendente")
    orquestrador.enfileirar(jid)
    return {"id": jid, "enfileirado": True}


_INSEGURO = re.compile(r"[^A-Za-z0-9._\-]+")


def _nome_seguro(nome: str) -> str:
    base = re.split(r"[\\/]", nome or "")[-1]
    base = _INSEGURO.sub("_", base).strip("._") or "arquivo"
    return base[:120]


def _nome_livre(pasta, nome: str) -> str:
    """`nome` se livre na pasta; senão `base-2.ext`, `base-3.ext`… (nunca sobrescreve)."""
    if not (pasta / nome).exists():
        return nome
    p = os.path.splitext(nome)
    base = p[0]
    n = 2
    while (pasta / f"{base}-{n}{p[1]}").exists():
        n += 1
    return f"{base}-{n}{p[1]}"


class _Excedeu(Exception):
    pass


class LimiteCorpoAvaliacao:
    """ASGI puro: corta o corpo do upload do João de Barro acima de MAX_REQUISICAO ANTES do
    FastAPI parsear o multipart. Content-Length grande → 413 na hora; chunked → conta os
    bytes de cada http.request e responde 413 quando passa do limite."""

    def __init__(self, app):
        self.app = app

    @staticmethod
    def _alvo(scope) -> bool:
        p = scope.get("path", "")
        return (scope["type"] == "http" and p.startswith("/api/avaliacao/")
                and p.endswith("/arquivos"))

    @staticmethod
    async def _413(send) -> None:
        corpo = json.dumps({"detail": "envio grande demais"}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(corpo)).encode())]})
        await send({"type": "http.response.body", "body": corpo})

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":                     # 070-C: a extensão do Chrome diz a versão dela
            ver = dict(scope.get("headers") or []).get(b"x-jdb-extensao")
            if ver:
                try:
                    v = ver.decode("ascii", "ignore")[:20]
                    if db.setting("extensao_versao") != v:
                        db.set_setting("extensao_versao", v)
                except Exception:
                    pass
        if not self._alvo(scope):
            return await self.app(scope, receive, send)
        limite = MAX_REQUISICAO
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    if int(v) > limite:
                        return await self._413(send)
                except ValueError:
                    pass
        estado = {"total": 0, "excedeu": False, "iniciou": False}

        async def receber():
            msg = await receive()
            if msg["type"] == "http.request":
                estado["total"] += len(msg.get("body", b""))
                if estado["total"] > limite:
                    estado["excedeu"] = True
                    raise _Excedeu
            return msg

        async def enviar_(msg):
            if estado["excedeu"]:
                return  # a resposta do app (erro de parse) é trocada pelo 413
            estado["iniciou"] = True
            await send(msg)

        try:
            await self.app(scope, receber, enviar_)
        except Exception:
            if not estado["excedeu"]:
                raise
        if estado["excedeu"] and not estado["iniciou"]:
            await self._413(send)


def _gravar_exclusivo(tmp, destino, nome: str) -> str:
    """Põe `tmp` em `destino/nome` sem nunca sobrescrever (os.link/open 'x' falham se o nome
    já existe; aí tenta o próximo nome livre). Devolve o nome final; `tmp` é removido."""
    while True:
        alvo = destino / nome
        try:
            try:
                os.link(tmp, alvo)
            except FileExistsError:
                raise
            except OSError:  # sistema de arquivos sem hard link: cópia exclusiva
                with open(tmp, "rb") as src, open(alvo, "xb") as dst:
                    shutil.copyfileobj(src, dst, BLOCO)
        except FileExistsError:
            nome = _nome_livre(destino, nome)
            continue
        tmp.unlink(missing_ok=True)
        return nome


def _registro_existente(jid: str, upload_id: str) -> dict | None:
    a = db.arquivo_por_upload(jid, upload_id)
    if a is None:
        return None
    p = db.pasta(jid) / a["caminho"]
    return {"nome": a["nome"], "tipo": a["tipo"], "caminho": a["caminho"],
            "bytes": p.stat().st_size if p.is_file() else 0, "repetido": True}


@router.post("/jobs/{jid}/arquivos")
async def enviar(jid: str, tipo: str = Form(...), arquivos: list[UploadFile] = File(...),
                 fachada: bool = Form(False), x_upload_id: str = Header(default=""),
                 _u: dict = Depends(_dono)):
    """`fachada=true` (só tipo foto, um arquivo) marca a foto como capa do laudo.
    `X-Upload-Id` (id estável do item no cliente, um arquivo por requisição) torna o envio
    idempotente: repetir devolve o registro existente sem gravar de novo."""
    _job(jid)
    if tipo not in TIPOS:
        raise HTTPException(status_code=400, detail=f"tipo inválido (use {sorted(TIPOS)})")
    if orquestrador.ocupado(jid):
        # arquivo que chega com a extração já rodando fica fora do laudo, sem aviso nenhum
        raise HTTPException(status_code=409, detail="trabalho em execução; envie quando terminar")
    upload_id = x_upload_id.strip()[:80]
    if upload_id:
        if len(arquivos) != 1:
            raise HTTPException(status_code=400, detail="X-Upload-Id exige um arquivo por envio")
        if (ex := _registro_existente(jid, upload_id)) is not None:
            return [ex]
    destino = db.pasta(jid) / tipo
    destino.mkdir(parents=True, exist_ok=True)
    out = []
    for up in arquivos:
        nome = _nome_seguro(up.filename or "")
        tmp = destino / f".{nome}.{uuid.uuid4().hex[:8]}.part"
        total = 0
        try:
            with open(tmp, "xb") as f:
                while bloco := await up.read(BLOCO):
                    total += len(bloco)
                    if total > MAX_BYTES:
                        raise HTTPException(status_code=413, detail=f"{nome}: maior que 50 MB")
                    f.write(bloco)
            if total == 0:
                raise HTTPException(status_code=400, detail=f"{nome}: arquivo vazio")
            if os.path.splitext(nome)[1].lower() in imagens.EXT_IMAGEM:
                try:
                    if await asyncio.to_thread(imagens.normalizar, tmp):
                        nome = os.path.splitext(nome)[0] + ".jpg"
                        total = tmp.stat().st_size
                except imagens.ImagemInvalida:
                    raise HTTPException(status_code=415, detail=(
                        f"{nome}: não foi possível abrir a imagem. Envie em JPG ou PNG."))
            nome = _gravar_exclusivo(tmp, destino, _nome_livre(destino, nome))
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        caminho = f"{tipo}/{nome}"
        papel = "fachada" if fachada and tipo == "foto" else ""
        try:
            db.adicionar_arquivo(jid, nome, tipo, caminho, papel, upload_id)
        except sqlite3.IntegrityError:  # mesmo upload_id gravado por um envio simultâneo
            (destino / nome).unlink(missing_ok=True)
            if (ex := _registro_existente(jid, upload_id)) is not None:
                return [ex]
            raise
        if nome.lower().endswith(".pdf"):
            try:   # PDF vira imagem já no envio (tela de tarjas); falha aqui não barra o envio
                await asyncio.to_thread(_paginas_pdf, jid, caminho)
            except Exception as e:  # noqa: BLE001
                log.warning("PDF %s não renderizado: %s", caminho, e)
        # ORDEM 013 a/d: cópia para a IA já no envio (≤ 1568 px, sem EXIF/GPS; PDF em
        # páginas); formato que a IA não lê fica guardado e vira aviso
        if not imagens_ia.suportado(caminho):
            db.evento(jid, "triagem", "aviso",
                      f"arquivo ignorado (formato que a IA não lê): {nome}")
        else:
            try:
                from .agentes import extracao as _ext
                lados = _ext._lados(jid)
                await asyncio.to_thread(imagens_ia.preparar, db.pasta(jid), [caminho],
                                        imagens_ia.LADO_IA, lados)
            except Exception as e:  # noqa: BLE001
                log.warning("cópia para a IA de %s não gerada: %s", caminho, e)
        out.append({"nome": nome, "tipo": tipo, "caminho": caminho, "bytes": total})
    return out


@router.post("/jobs/{jid}/iniciar", status_code=202)
async def iniciar(jid: str, aceito_extra: bool = False, _u: dict = Depends(_dono)):
    _job(jid)
    _checar_extra(jid, aceito_extra)            # 155-1: o aviso do laudo extra vem ANTES de a IA começar
    orquestrador.enfileirar(jid)
    return {"id": jid, "enfileirado": True}


@router.get("/jobs/{jid}/capa.png")
async def capa_demarcada(jid: str, _u: dict = Depends(_dono)):
    """079-4: a capa com o contorno vermelho, para o avaliador conferir no próprio card."""
    _job(jid)
    p = db.pasta(jid) / "_laudo" / "capa_demarcada.png"
    if not p.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(p, media_type="image/png")


@router.get("/jobs/{jid}/entrega/{arquivo:path}")
async def entrega(jid: str, arquivo: str, _u: dict = Depends(_dono)):
    _job(jid)
    raiz = (db.pasta(jid) / "entrega").resolve()
    try:
        p = (raiz / arquivo).resolve()
    except Exception:
        raise HTTPException(status_code=404)
    if p.parent != raiz or not p.is_file():
        raise HTTPException(status_code=404)
    # 074-E5 (D-073): para revisão vai só o PDF, com "(REVISÃO N)" no nome; Word e planilha depois do ok
    from . import tela_trabalho
    if not tela_trabalho.aprovado(jid):
        if p.suffix.lower() in (".docx", ".xlsx"):
            raise HTTPException(status_code=409, detail="o Word e a planilha saem depois do seu ok no PDF")
        if p.suffix.lower() == ".pdf":
            return FileResponse(p, filename=f"{p.stem} (REVISÃO {max(1, tela_trabalho._revisao(jid))}).pdf")
    return FileResponse(p, filename=p.name)


# ------------------------------------------------------------------ 166: downloads (revisão só PDF; entrega PDF+Word+planilha)
_TIPOS_BAIXAR = {"pdf": ".pdf", "docx": ".docx", "xlsx": ".xlsx"}


def _arquivo_atual(jid: str, tipo: str) -> Path | None:
    """O arquivo da versão ATUAL: o da pasta do trabalho (o editável e a revisão humana gravam ali); senão o da entrega."""
    from .orquestrador import _arquivos_finais
    p = _arquivos_finais(jid)[tipo]
    if p.is_file():
        return p
    ent = db.pasta(jid) / "entrega" / p.name
    return ent if ent.is_file() else None


@router.get("/jobs/{jid}/baixar/{tipo}")
async def baixar_arquivo(jid: str, tipo: str, _u: dict = Depends(_dono)):
    """166-1/2: antes do [✓ Aprovar] só o PDF, com "(REVISÃO N)" no nome; depois do ✓, PDF, Word e planilha com o nome
    do padrão ("Nº - Cliente - Tipo - Bairro - Cidade") e "tudo" (.zip com os três)."""
    import io
    import zipfile
    from fastapi import Response
    from . import tela_trabalho
    _job(jid)
    aprovado = tela_trabalho.aprovado(jid)
    if tipo == "tudo":
        if not aprovado:
            raise HTTPException(status_code=409, detail="o Word e a planilha saem depois do seu ✓ Aprovar")
        arqs = [a for a in (_arquivo_atual(jid, t) for t in _TIPOS_BAIXAR) if a]
        if not arqs:
            raise HTTPException(status_code=404, detail="este trabalho ainda não tem os arquivos do laudo")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for a in arqs:
                z.write(a, arcname=a.name)
        nome = f"{arqs[0].stem}.zip"
        from urllib.parse import quote
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(nome)}"})
    if tipo not in _TIPOS_BAIXAR:
        raise HTTPException(status_code=404)
    if tipo != "pdf" and not aprovado:
        raise HTTPException(status_code=409, detail="o Word e a planilha saem depois do seu ✓ Aprovar")
    a = _arquivo_atual(jid, tipo)
    if a is None:
        raise HTTPException(status_code=404, detail="este trabalho ainda não tem esse arquivo")
    nome = a.name if aprovado else f"{a.stem} (REVISÃO {max(1, tela_trabalho._revisao(jid))}).pdf"
    return FileResponse(a, filename=nome)


# ------------------------------------------------------------------ D-086: PDF assinado
MAX_ASSINADO = 60 * 1024 * 1024


@router.get("/assinatura/instrucao")
async def instrucao_assinatura(_u: dict = Depends(_dono)):
    from . import assinatura
    return {"assinador": assinatura.ASSINADOR, "instrucao": assinatura.INSTRUCAO}


@router.post("/jobs/{jid}/assinado")
async def enviar_assinado(jid: str, arquivo: UploadFile = File(...), _u: dict = Depends(_dono)):
    """D-086 (ORDEM 039-5): o avaliador sobe o PDF que ELE assinou no gov.br/ICP-Brasil. O
    sistema só lê e confere a assinatura; com assinatura, guarda como versão final
    "<nome>_assinado.pdf" na entrega, junto do Word e da planilha. Sem assinatura: recusa.
    Nunca assina pelo avaliador, nunca usa imagem de assinatura e nunca pede senha."""
    from . import assinatura
    _job(jid)
    ent = db.resultado(jid, "entrega") or {}
    pdf_final = next((a for a in ent.get("arquivos") or [] if a.lower().endswith(".pdf")
                      and not a.lower().endswith("_assinado.pdf")), None)
    if ent.get("status") != orquestrador.PRONTO or not pdf_final:
        raise HTTPException(status_code=409, detail="só depois do laudo aprovado (PRONTO PARA REVISÃO)")
    dados = await arquivo.read(MAX_ASSINADO + 1)
    if len(dados) > MAX_ASSINADO or not dados.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="envie o PDF assinado (até 60 MB)")
    conf = await asyncio.to_thread(assinatura.conferir, dados)
    if not conf.assinado:
        raise HTTPException(status_code=422, detail=f"não achei assinatura digital neste PDF: {conf.motivo}")
    nome = assinatura.nome_assinado(pdf_final)
    destino = db.pasta(jid) / "entrega" / nome
    destino.write_bytes(dados)
    arquivos = [a for a in ent.get("arquivos") or [] if a != nome] + [nome]
    db.evento(jid, "entrega", "resultado", ent.get("status"), dados={
        **ent, "arquivos": arquivos, "assinado": nome,
        "assinaturas": [{k: v for k, v in a.items() if k in ("subfiltro", "data", "cobre_o_arquivo")}
                        for a in conf.assinaturas]})
    db.evento(jid, "entrega", "info", f"PDF assinado digitalmente guardado como versão final: {nome} (D-086)")
    return {"arquivo": nome, "assinaturas": len(conf.assinaturas)}


# ------------------------------------------------------------------ exemplo para clientes
@router.post("/jobs/{jid}/exemplo")
async def gerar_exemplo(jid: str, _u: dict = Depends(_dono)):
    """D-041 (ORDEM 007): cópia do laudo pronto para mostrar a clientes — endereço, nomes,
    inscrição e link do Maps trocados por █, mapa/documentos/foto com placa desfocados. Sem IA."""
    from . import exemplo
    j = _livre(jid)
    if j["status"] != orquestrador.PRONTO:   # ORDEM 008: laudo com pendência não vai a cliente
        raise HTTPException(status_code=409, detail="o exemplo só sai de laudo PRONTO PARA REVISÃO "
                                                    "(sem pendências)")
    ent = db.resultado(jid, "entrega") or {}
    docx = next((db.pasta(jid) / "entrega" / a for a in ent.get("arquivos") or []
                 if a.lower().endswith(".docx")), None)
    if docx is None or not docx.is_file():
        raise HTTPException(status_code=409, detail="laudo Word não encontrado na entrega")
    from .docx_builder import _avaliador
    av = _avaliador()
    r = await asyncio.to_thread(exemplo.gerar, jid, docx, db.pasta(jid) / "exemplo", av)
    db.evento(jid, "entrega", "info", f"exemplo para clientes gerado: {r['docx'].name} "
              f"({r['trocas']} caracteres trocados, {r['imagens']} imagens desfocadas)")
    return {"docx": r["docx"].name, "pdf": r["pdf"].name if r["pdf"] else None,
            "trocas": r["trocas"], "imagens": r["imagens"]}


@router.get("/jobs/{jid}/exemplo/{arquivo:path}")
async def baixar_exemplo(jid: str, arquivo: str, _u: dict = Depends(_dono)):
    _job(jid)
    raiz = (db.pasta(jid) / "exemplo").resolve()
    p = (raiz / arquivo).resolve()
    if p.parent != raiz or not p.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(p, filename=p.name)


# ------------------------------------------------------------------ correção
class Correcao(BaseModel):
    texto: str
    virar_regra: bool = False


# 115-b: dados do PRÓPRIO trabalho que um pedido pode trocar (o dado muda e tudo o que depende dele é refeito)
DADOS_TROCAVEIS = {"data_base": "data-base", "data_vistoria": "data da vistoria", "cliente": "nome do cliente",
                   "bairro": "bairro", "cidade": "cidade", "finalidade": "finalidade", "tipo": "tipo do imóvel"}


class _Dado(BaseModel):
    campo: Literal[tuple(DADOS_TROCAVEIS)]  # type: ignore[valid-type]
    valor: str


class _Acao(BaseModel):
    """117: o que o sistema sabe executar fora do texto (modelo do laudo e imagens)."""
    tipo: Literal["titulo", "tirar_documento", "tirar_trecho", "trocar_foto", "refazer_mapa", "tirar_foto"]
    alvo: str = ""      # titulo: nº do item ("9.3"); tirar_documento: nome do documento; tirar_trecho: o trecho exato;
    valor: str = ""     # trocar_foto: nº do anúncio/comparação | titulo: o título novo; trocar_foto: a foto descrita


class _Triagem(BaseModel):
    etapa: Literal[tuple(orquestrador.ETAPAS)]  # type: ignore[valid-type]
    instrucao: str
    dados: list[_Dado] = []
    acoes: list[_Acao] = []


SISTEMA_CORRECAO = (
    "Você recebe uma correção do avaliador sobre um laudo de avaliação imobiliária gerado "
    "automaticamente. Identifique a PRIMEIRA etapa do pipeline que precisa ser refeita "
    f"({', '.join(orquestrador.ETAPAS)}): dados do imóvel/documentos → extracao; escolha ou "
    "descarte de referenciais/unitário → selecao; texto do laudo → redacao. Reescreva a "
    "correção como uma instrução objetiva e autossuficiente para o agente dessa etapa. "
    "Se o pedido MUDA UM DADO do trabalho (" + ", ".join(f"{k} = {v}" for k, v in DADOS_TROCAVEIS.items())
    + "), preencha também 'dados' com o campo e o valor novo que o avaliador disse (datas em AAAA-MM-DD); "
    "nunca invente valor. O dado é trocado no trabalho inteiro (capa, cabeçalho, corpo, resumo e planilha). "
    "117: o que NÃO é texto do redator vai em 'acoes' (etapa montagem): mudar o TÍTULO de um item → "
    "{tipo: titulo, alvo: nº do item, valor: título novo}; tirar um documento do quadro 'Documentação analisada' "
    "(item 6) → {tipo: tirar_documento, alvo: nome curto do documento, ex. CNH}; tirar um trecho fixo do laudo "
    "(legenda, capa, quadro) → {tipo: tirar_trecho, alvo: o trecho exato a apagar, copiado do pedido}; trocar a foto "
    "de um anúncio/imóvel de comparação → {tipo: trocar_foto, alvo: nº do imóvel, valor: a foto descrita, ex. 'a da "
    "piscina'}; refazer a demarcação do mapa da localização → {tipo: refazer_mapa, valor: o que pediu}; tirar uma "
    "FOTO DA VISTORIA do relatório fotográfico → {tipo: tirar_foto, alvo: 'Foto NN' ou a legenda dela}. Um pedido "
    "pode ter várias ações. Ordem das fotos e estrutura dos anexos são da montagem (sem ação).")


def _pede_documento(pedido: str) -> bool:
    """126-3d: o pedido precisa reler os documentos? (documento novo, área/medida/matrícula do documento)"""
    return bool(re.search(r"(?i)reler|ler de novo|documento novo|mandei (?:o|a|um|uma)|anexei|matr[ií]cula|escritura diz|"
                          r"iptu diz|[áa]rea (?:do|da) (?:documento|escritura|iptu)", pedido or ""))


def _trocar_dados(jid: str, dados: list) -> list[str]:
    """115-b: o pedido muda o DADO do trabalho (não só uma frase). Data-base também vale como escolha do avaliador
    (a correção automática da 086-8 não a desfaz). Devolve o que mudou, em português ("data-base: de X para Y")."""
    from datetime import date as _d
    from . import conversa as C, tela_trabalho
    t = Trabalho.model_validate(db.job(jid)["dados"])
    upd, linhas = {}, []
    for d in dados:
        v = (d.valor or "").strip()
        if not v:
            continue
        if d.campo in ("data_base", "data_vistoria"):
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", v) or re.match(r"(\d{2})/(\d{2})/(\d{4})$", v)
            if not m:
                continue
            g = m.groups()
            novo = _d(int(g[0]), int(g[1]), int(g[2])) if len(g[0]) == 4 else _d(int(g[2]), int(g[1]), int(g[0]))
            antes = getattr(t, d.campo)
            if novo == antes:
                continue
            upd[d.campo] = novo
            linhas.append(f"{DADOS_TROCAVEIS[d.campo]}: de {antes.strftime('%d/%m/%Y')} para {novo.strftime('%d/%m/%Y')}")
        else:
            antes = str(getattr(t, d.campo) or "")
            if v == antes:
                continue
            upd[d.campo] = v
            linhas.append(f"{DADOS_TROCAVEIS[d.campo]}: de {antes or '—'} para {v}")
            if antes and d.campo in ("cliente", "bairro", "cidade"):
                from . import ajustes as _aj      # 129: o texto que cita o dado é trocado por regra (sem reescrever)
                _aj.registrar_troca(jid, antes, v)
    if not upd:
        return []
    db.atualizar_dados(jid, t.model_copy(update=upd))
    if "data_base" in upd:
        cli = tela_trabalho._cliente(jid)
        if cli:
            C.juntar_contexto(cli["id"], {"data_base_escolhida": upd["data_base"].isoformat()})
    db.evento(jid, "orquestrador", "dado", "dado do trabalho trocado pelo avaliador: " + "; ".join(linhas),
              dados={"linhas": linhas})
    db.evento(jid, "pesquisa", "edicao_manual", "dado do trabalho trocado pelo avaliador")
    return linhas


@router.get("/jobs/{jid}/corrigir/ultimo")
async def ultimo_pedido(jid: str, _u: dict = Depends(_dono)):
    """121: o texto do último pedido de ajuste que o avaliador mandou (para "Usar os últimos pedidos": o mecanismo
    da 117 separa e reaplica; nada é editado à mão)."""
    _job(jid)
    with db._conn() as c:
        rows = c.execute("SELECT dados_json, ts FROM av_events WHERE job=? AND nivel='correcao' ORDER BY id DESC LIMIT 60",
                         (jid,)).fetchall()
    lote, quando = [], None
    for r in rows:
        try:
            d = json.loads(r["dados_json"] or "{}") or {}
        except ValueError:
            continue
        if not d.get("texto_original") or d.get("eco"):
            continue
        ts = str(r["ts"] or "")[:19]
        if quando is None:
            quando = ts
        if ts != quando:
            break                               # só o último envio (todos os pedidos dele saem no mesmo segundo)
        lote.append(str(d["texto_original"]).strip())
    return {"texto": "\n\n=====\n\n".join(reversed(lote))}


@router.post("/jobs/{jid}/corrigir", status_code=202)
async def corrigir(jid: str, body: Correcao, _u: dict = Depends(_dono)):
    j = _job(jid)
    if not body.texto.strip():
        raise HTTPException(status_code=400, detail="texto vazio")
    if orquestrador.ocupado(jid):
        raise HTTPException(status_code=409, detail="trabalho em execução; aguarde terminar")
    # 114: o quadro único — cada par "Onde fica: / O que mudar:" é um pedido separado (texto livre continua valendo)
    from .pedidos_revisao import dividir
    pedidos = dividir(body.texto)
    if not pedidos:
        raise HTTPException(status_code=400, detail="texto vazio")
    tris: list[tuple[str, _Triagem]] = []
    for ped in pedidos:
        prompt = (f"Trabalho: {json.dumps(j['dados'], ensure_ascii=False, default=str)}\n"
                  f"Etapa atual: {j['etapa']} ({j['status']})\n\nCorreção do avaliador:\n{ped}")
        try:
            tris.append((ped, await ia.perguntar(SISTEMA_CORRECAO, prompt, _Triagem)))
        except ia.IAFalhou as e:
            raise HTTPException(status_code=503, detail=f"IA indisponível: {e}")
    # Antes de gravar qualquer coisa: se o job entrou na fila durante a chamada da IA, o 409
    # não pode deixar para trás a correção e a regra global (o avaliador repete e duplicava).
    if orquestrador.ocupado(jid):
        raise HTTPException(status_code=409, detail="trabalho em execução; aguarde terminar")
    codigos = []
    mudou_dado = _trocar_dados(jid, [d for _, tri in tris for d in tri.dados])      # 115-b
    from . import ajustes
    nao_deu: list[str] = []
    # 126-3c: um pedido com duas trocas de foto (ex.: "imóvel 2: a da piscina; imóvel 1: a da fachada") vira dois
    # pedidos, cada um com o seu ✓/✗
    separados: list[tuple[str, _Triagem]] = []
    for ped, tri in tris:
        fotos = [a for a in tri.acoes if a.tipo == "trocar_foto"]
        if len(fotos) < 2:
            separados.append((ped, tri))
            continue
        for a in fotos:
            separados.append((f"Trocar a foto do {a.alvo}: {a.valor}",
                              tri.model_copy(update={"acoes": [a], "instrucao": f"trocar a foto do {a.alvo}: {a.valor}"})))
        resto = [a for a in tri.acoes if a.tipo != "trocar_foto"]
        if resto:
            separados.append((ped, tri.model_copy(update={"acoes": resto})))
    tris = separados
    # 126-3d: pedido de dado (bairro, data…), de texto ou de modelo/imagem não refaz a leitura dos documentos (a
    # extração levava ~4 min por passada e não muda nada nesses casos): a etapa mais cedo é o cálculo (dado) ou a redação
    # 129 (regra do Capitão): cada pedido só refaz o que ele toca. Texto → redação; modelo/imagem → montagem; dado que
    # não muda conta (bairro, data, nome…) → montagem (o texto que cita o dado é trocado por regra, sem IA). Só documento
    # novo volta à leitura dos documentos. "Refazer" solto nunca vira "refazer o laudo inteiro".
    def _alcance(ped: str, tri: _Triagem) -> _Triagem:
        if tri.etapa in ("triagem", "extracao", "pesquisa") and _pede_documento(ped):
            return tri
        if tri.etapa in ("triagem", "extracao", "pesquisa", "calculo") and (tri.dados or tri.acoes):
            return tri.model_copy(update={"etapa": "montagem"})   # dado sem conta / modelo / imagem: só remonta
        if tri.etapa in ("triagem", "extracao", "pesquisa"):
            return tri.model_copy(update={"etapa": "redacao"})
        return tri
    tris = [(ped, _alcance(ped, tri)) for ped, tri in tris]
    for ped, tri in tris:
        acoes = [a.model_dump() for a in tri.acoes]
        p = ajustes.novo(jid, ped, tri.etapa, tri.instrucao, acoes)            # 117-2: cada pedido guardado, com nº
        ajustes.aplicar_modelo(jid, acoes)                                     # título, documento fora, trecho fora
        for ok, motivo in await ajustes.aplicar_imagens(jid, acoes):           # foto do anúncio, mapa
            if not ok:
                ajustes.marcar(jid, p["i"], status="nao_feito", motivo=motivo or "a imagem não foi trocada")
                nao_deu.append(ajustes.linha_nao_consegui({**p, "motivo": motivo}))
        db.evento(jid, tri.etapa, "correcao", tri.instrucao, dados={"texto_original": ped, "pedido": p["i"]})
        if tri.etapa in ("extracao", "selecao", "calculo"):
            # 117-1: a correção marcada para uma etapa cedo só chegava ao agente dela; o texto do laudo é da redação
            db.evento(jid, "redacao", "correcao", tri.instrucao, dados={"texto_original": ped, "pedido": p["i"],
                                                                       "eco": True})
        if body.virar_regra:
            codigo = db.proximo_codigo_decisao()
            db.upsert_decisoes([{"codigo": codigo, "data": date.today().strftime("%d/%m/%Y"),
                                 "laudo": str(j["numero"]), "decisao": tri.instrucao,
                                 "regra": ped, "escopo": "Todos os laudos",
                                 "status": "Aprovada"}])
            codigos.append(codigo)
    etapas = [tri.etapa for _, tri in tris] + (["montagem"] if mudou_dado else [])   # 129: dado sem conta só remonta
    etapas += ["montagem" for _, tri in tris if tri.acoes]                    # ação de modelo/imagem: remonta
    etapa = min(etapas, key=orquestrador.ETAPAS.index)   # refaz uma vez, da mais cedo
    if orquestrador.ETAPAS.index(etapa) >= orquestrador.ETAPAS.index("redacao"):
        # 129: correção de texto/montagem/imagem — a revisão do sistema confere só por regra (sem a revisão completa
        # de IA nem a contestação simulada); vale até a próxima entrega
        db.set_setting(f"correcao_rapida:{jid}", "1")
    if any(re.search(r"(?i)\bidade", ped) for ped, _ in tris):
        # 132-4: pedido de idade (ex.: imóvel 2 do 9.3 com "n/i") → estima pela foto antes de montar (IA leve, por anúncio
        # sem idade; idade do avaliador não é trocada) e vira o cartão "Confere?"
        try:
            from . import idade_anuncio
            await idade_anuncio.completar(jid)
        except Exception:      # noqa: BLE001 — sem a estimativa, o pedido sai ✗ com o motivo
            log.exception("idade pela foto no pedido de %s", jid)
    orquestrador.reabrir(jid, etapa)
    orquestrador.enfileirar(jid)
    return {"etapa": etapa, "instrucao": "; ".join(tri.instrucao for _, tri in tris),
            "decisao": ", ".join(codigos) or None, "pedidos": len(tris), "nao_deu": nao_deu}


# ------------------------------------------------------------------ config
class DecisaoIn(BaseModel):
    codigo: str
    data: str = ""
    laudo: str = ""
    decisao: str
    regra: str = ""
    tipo: str = ""
    escopo: str = ""
    status: str = "Aprovada"


class NormaIn(BaseModel):
    codigo: str
    titulo: str = ""
    itens: dict = {}
    vigente: bool = True


class Config(BaseModel):
    avaliador: dict | None = None
    aviso_whatsapp: bool | None = None
    decisoes: list[DecisaoIn] | None = None
    normas: list[NormaIn] | None = None


@router.get("/config")
async def ler_config(_u: dict = Depends(_dono)):
    from . import conhecimento
    if av_atual() != "AV-0001":       # ORDEM 042: outro avaliador vê só os dados DELE
        from . import avaliadores
        return {"avaliador": avaliadores.identidade_avaliador(av_atual()), "dono_email": "",
                "decisoes": db.decisoes(), "aviso_whatsapp": False, "normas": conhecimento.normas_todas()}
    return {"avaliador": json.loads(db.setting("avaliador", "{}")),
            "dono_email": _email_dono(), "decisoes": db.decisoes(),
            "aviso_whatsapp": aviso.ligado(),
            "normas": conhecimento.normas_todas()}


@router.get("/aviso/status")
async def status_aviso(_u: dict = Depends(_dono)):
    return await asyncio.to_thread(aviso.status)


@router.put("/config")
async def gravar_config(body: Config, _u: dict = Depends(_dono)):
    if av_atual() != "AV-0001":       # ORDEM 042: nunca grava por cima dos dados do Alan
        from . import avaliadores
        if body.avaliador is not None:
            avaliadores.atualizar(av_atual(), body.avaliador)
        return {"ok": True}
    if body.avaliador is not None:
        db.set_setting("avaliador", json.dumps(body.avaliador, ensure_ascii=False))
    if body.aviso_whatsapp is not None:
        aviso.set_ligado(body.aviso_whatsapp)
    if body.decisoes:
        db.upsert_decisoes([d.model_dump() for d in body.decisoes])
    if body.normas:
        db.upsert_normas([n.model_dump() for n in body.normas])
    return {"ok": True}


# ------------------------------------------------------------------ admin
class Dono(BaseModel):
    email: str


@admin_router.put("/avaliacao/dono")
async def definir_dono(body: Dono):
    email = body.email.strip().casefold()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="e-mail inválido")
    # Sem conta, o primeiro que se cadastrasse com esse e-mail viraria o dono.
    if auth.user_by_email(email) is None:
        raise HTTPException(status_code=400, detail="não existe conta Brixly com esse e-mail")
    db.init()
    db.set_setting("dono_email", email)
    return {"dono_email": email}


# ------------------------------------------------------------------ websocket
_vivos = 0


def ws_vivos() -> int:
    """Handlers de WS ainda rodando (teste de vazamento)."""
    return _vivos


@ws_router.websocket("/ws/avaliacao/{jid}")
async def ws_avaliacao(ws: WebSocket, jid: str, token: str = ""):
    uid = auth.user_id_from_token(token) if token else None
    user = auth.get_user(uid) if uid else None
    if not _eh_dono(user):
        await ws.close(code=4403)
        return
    try:
        db.job(jid)
    except KeyError:
        await ws.close(code=4404)
        return
    await ws.accept()
    global _vivos
    _vivos += 1

    async def _ate_desconectar():
        try:
            while True:
                await ws.receive_text()
        except (WebSocketDisconnect, RuntimeError):
            return

    async def _transmitir():
        ultimo = 0
        while True:
            for ev in db.eventos_desde(jid, ultimo):
                await ws.send_json(ev)
                ultimo = ev["id"]
            await asyncio.sleep(INTERVALO_WS_S)

    tarefas = [asyncio.create_task(_ate_desconectar()), asyncio.create_task(_transmitir())]
    try:
        feitas, _ = await asyncio.wait(tarefas, return_when=asyncio.FIRST_COMPLETED)
        for t in feitas:
            e = None if t.cancelled() else t.exception()
            if e and not isinstance(e, (WebSocketDisconnect, RuntimeError)):
                log.error("avaliacao ws %s", jid, exc_info=e)
    finally:
        for t in tarefas:
            t.cancel()
        await asyncio.gather(*tarefas, return_exceptions=True)
        _vivos -= 1


# ORDEM 026 v2: rotas do módulo de aprendizado (mesmo router)
from . import rotas_fichas  # noqa: E402,F401

# ORDEM 024 item 6: proposta -> contrato -> trabalho
from . import rotas_propostas  # noqa: E402,F401

# ORDEM 040: planos, "Meu plano", margem e "Aprovar" (só local, sem cobrança)
from . import rotas_planos  # noqa: E402,F401

# ORDEM 041: conversa por cliente (proposta → assinatura), push e avisos
from . import rotas_conversa  # noqa: E402,F401

# ORDEM 042: avaliador novo (cadastro, modelos, identidade, Minhas regras)
from . import rotas_avaliadores  # noqa: E402,F401

# ORDEM 060: Lixeira e Exportar (menu "Opções" de cada trabalho)
from . import rotas_lixeira  # noqa: E402,F401
from . import rotas_google  # noqa: E402,F401  — 169: Google Docs do avaliador

# ORDEM 061: importar a conversa do WhatsApp (zip com mídias), áudios transcritos no PC
from . import rotas_whatsapp  # noqa: E402,F401

# ORDEM 065: rascunho real da proposta e do contrato antes de aprovar
from . import rascunho  # noqa: E402,F401


@router.post("/jobs/{jid}/duplicar")
async def duplicar_trabalho(jid: str, _u: dict = Depends(_dono)):
    """ORDEM 028-5: cópia do trabalho com nº novo (o original não muda)."""
    _livre(jid)
    base = db.job(jid)["numero"]
    novo = (db.proximo_numero() if db.modo_teste()         # 109-3: cópia de teste segue a numeração dos testes
            else int(f"{base}1") if not db.numero_usado(int(f"{base}1")) else db.proximo_numero())
    while db.numero_usado(novo):
        novo += 1
    nid = db.duplicar_job(jid, novo)
    from . import planos
    planos.marcar_teste(nid)                    # 155-3: cópia fica fora da contagem, da cobrança e da medição
    _ajustar_area_da_copia(nid)                 # 159-2
    return {"id": nid, "numero": novo}
