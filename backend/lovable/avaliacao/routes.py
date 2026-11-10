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
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from lovable import auth

from . import aviso, db, ia, imagens, orquestrador
from .modelos import Partes, Trabalho

log = logging.getLogger("lovable")

router = APIRouter()
ws_router = APIRouter()
admin_router = APIRouter()


@router.on_event("startup")
async def _avaliacao_startup():
    """Registra a fonte de mercado real (Coletor), salvo se outra ja foi registrada."""
    from . import coletor_fonte, fonte_mercado
    if fonte_mercado._atual is None:
        fonte_mercado.registrar(coletor_fonte.ColetorFonte())


@router.on_event("shutdown")
async def _avaliacao_shutdown():
    """Encerramento: falhas de IA a partir daqui (CLI morto) deixam o job retomável."""
    orquestrador.encerrar()

TIPOS = {"documento", "foto", "solicitante"}
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


async def _dono(authorization: str = Header(default="")) -> dict:
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    uid = auth.user_id_from_token(token) if token else None
    user = auth.get_user(uid) if uid else None
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    if not _eh_dono(user):
        raise HTTPException(status_code=403, detail="Sem acesso")
    return user


def _job(jid: str) -> dict:
    try:
        return db.job(jid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Trabalho não encontrado")


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
    processo_numero: str = ""
    vara_juizo: str = ""
    acao: str = ""
    partes: Partes | None = None
    quesitos: list[str] = []


class NovoTrabalho(DadosTrabalho):
    numero: int


@router.post("/jobs")
async def criar(body: NovoTrabalho, _u: dict = Depends(_dono)):
    if db.numero_usado(body.numero):
        raise HTTPException(status_code=409, detail="número já usado")
    try:
        jid = db.criar_job(Trabalho(id="", **body.model_dump()))
    except sqlite3.IntegrityError:  # corrida: outro POST levou o número entre a checagem e o insert
        raise HTTPException(status_code=409, detail="número já usado")
    return {"id": jid}


@router.get("/proximo-numero")
async def proximo_numero(_u: dict = Depends(_dono)):
    return {"numero": db.proximo_numero()}


@router.get("/jobs")
async def listar(_u: dict = Depends(_dono)):
    out = []
    for d in db.listar_jobs():
        dados = d.pop("dados")
        d.update(cliente=dados.get("cliente"), modalidade=dados.get("modalidade"),
                 tipo=dados.get("tipo"), bairro=dados.get("bairro"), cidade=dados.get("cidade"),
                 finalidade=dados.get("finalidade"))
        out.append(d)
    return out


@router.get("/jobs/{jid}")
async def detalhe(jid: str, _u: dict = Depends(_dono)):
    j = _job(jid)
    etapas = {e: db.resultado(jid, e) for e in orquestrador.ETAPAS}
    entrega = etapas.get("entrega") or {}
    return {"job": j, "etapas": etapas, "arquivos": db.arquivos(jid),
            "campos": [c.model_dump(mode="json") for c in db.campos(jid)],
            "candidatos": [r.model_dump(mode="json") for r in db.candidatos(jid)],
            "resultado": etapas.get("calculo"),
            "pendencias": orquestrador.pendencias_estruturadas(entrega.get("pendencias", [])),
            "resumo_ia": db.ia_resumo(jid), "dados_alterados": _dados_alterados(jid)}


def _dados_alterados(jid: str) -> bool:
    """Campo, referenciais ou dados do trabalho editados depois da última entrega: o laudo
    entregue ainda não reflete a edição (a UI pede "Recalcular")."""
    with db._conn() as c:
        r = c.execute(
            "SELECT (SELECT MAX(id) FROM av_events WHERE job=? AND (nivel='edicao_manual' OR "
            "(etapa='selecao' AND nivel='resultado' AND json_extract(dados_json, '$.manual')))) AS ed, "
            "(SELECT MAX(id) FROM av_events WHERE job=? AND etapa='entrega' "
            "AND nivel='resultado') AS ent", (jid, jid)).fetchone()
    return bool(r["ed"] and r["ent"] and r["ed"] > r["ent"])


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
    t = Trabalho(id=jid, numero=j["numero"], **body.model_dump())
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


@router.put("/jobs/{jid}/campos/{nome}")
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


ESCOLHA_MANUAL = "escolha manual do avaliador"


@router.put("/jobs/{jid}/referenciais")
async def escolher_referenciais(jid: str, body: EscolhaReferenciais, _u: dict = Depends(_dono)):
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
    area = selecao.area_construida(jid)
    if area is None:
        raise HTTPException(status_code=400, detail="área construída do avaliando ausente; edite o campo antes")
    unit = None
    if (body.unitario_adotado or "").strip():
        try:
            unit = selecao._decimal_br(body.unitario_adotado)
        except (InvalidOperation, ValueError):
            raise HTTPException(status_code=400, detail="unitário adotado inválido")
    anterior = db.resultado(jid, "selecao") or {}
    faixa = Decimal(str(anterior.get("faixa_pct") or "10"))
    just = (body.justificativa or "").strip()
    refs = [r.model_copy(update={
        "escolhido": r.n in ns,
        "justificativa": ESCOLHA_MANUAL + (f": {just}" if just and r.n in ns else "")})
        for r in cands]
    try:
        calculo.calcular(area, [r for r in refs if r.escolhido], unit, faixa)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    n = len(ns)
    declaracao = ("" if n >= selecao.MIN_ESCOLHIDOS else
                  f"Amostra reduzida: apenas {n} referencial(is) escolhido(s) pelo avaliador.")
    s = selecao.Selecao(refs=refs, unitario_adotado=unit,
                        justificativa_unitario=(just or ESCOLHA_MANUAL) if unit is not None else "",
                        faixa_pct=faixa, declaracao_amostra=declaracao)
    db.salvar_candidatos(jid, refs)
    db.evento(jid, "selecao", "resultado", f"{n} de {len(refs)} referenciais ({ESCOLHA_MANUAL})",
              dados={**s.model_dump(mode="json"), "manual": True})
    return {**s.model_dump(mode="json"), "manual": True}


class Reabertura(BaseModel):
    etapa: Literal["extracao", "calculo", "redacao", "montagem"]


@router.post("/jobs/{jid}/reabrir", status_code=202)
async def reabrir(jid: str, body: Reabertura, _u: dict = Depends(_dono)):
    """Reprocessar documentos (extracao) / recalcular (calculo) / regerar documento
    (redacao ou montagem)."""
    _livre(jid)
    orquestrador.reabrir(jid, body.etapa, motivo=f"reaberto pelo avaliador a partir de {body.etapa}")
    orquestrador.enfileirar(jid)
    return {"id": jid, "etapa": body.etapa, "enfileirado": True}


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
        out.append({"nome": nome, "tipo": tipo, "caminho": caminho, "bytes": total})
    return out


@router.post("/jobs/{jid}/iniciar", status_code=202)
async def iniciar(jid: str, _u: dict = Depends(_dono)):
    _job(jid)
    orquestrador.enfileirar(jid)
    return {"id": jid, "enfileirado": True}


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
    return FileResponse(p, filename=p.name)


# ------------------------------------------------------------------ correção
class Correcao(BaseModel):
    texto: str
    virar_regra: bool = False


class _Triagem(BaseModel):
    etapa: Literal[tuple(orquestrador.ETAPAS)]  # type: ignore[valid-type]
    instrucao: str


SISTEMA_CORRECAO = (
    "Você recebe uma correção do avaliador sobre um laudo de avaliação imobiliária gerado "
    "automaticamente. Identifique a PRIMEIRA etapa do pipeline que precisa ser refeita "
    f"({', '.join(orquestrador.ETAPAS)}): dados do imóvel/documentos → extracao; escolha ou "
    "descarte de referenciais/unitário → selecao; texto do laudo → redacao. Reescreva a "
    "correção como uma instrução objetiva e autossuficiente para o agente dessa etapa.")


@router.post("/jobs/{jid}/corrigir", status_code=202)
async def corrigir(jid: str, body: Correcao, _u: dict = Depends(_dono)):
    j = _job(jid)
    if not body.texto.strip():
        raise HTTPException(status_code=400, detail="texto vazio")
    if orquestrador.ocupado(jid):
        raise HTTPException(status_code=409, detail="trabalho em execução; aguarde terminar")
    prompt = (f"Trabalho: {json.dumps(j['dados'], ensure_ascii=False, default=str)}\n"
              f"Etapa atual: {j['etapa']} ({j['status']})\n\nCorreção do avaliador:\n{body.texto}")
    try:
        tri: _Triagem = await ia.perguntar(SISTEMA_CORRECAO, prompt, _Triagem)
    except ia.IAFalhou as e:
        raise HTTPException(status_code=503, detail=f"IA indisponível: {e}")
    # Antes de gravar qualquer coisa: se o job entrou na fila durante a chamada da IA, o 409
    # não pode deixar para trás a correção e a regra global (o avaliador repete e duplicava).
    if orquestrador.ocupado(jid):
        raise HTTPException(status_code=409, detail="trabalho em execução; aguarde terminar")
    db.evento(jid, tri.etapa, "correcao", tri.instrucao, dados={"texto_original": body.texto})
    codigo = None
    if body.virar_regra:
        codigo = db.proximo_codigo_decisao()
        db.upsert_decisoes([{"codigo": codigo, "data": date.today().strftime("%d/%m/%Y"),
                             "laudo": str(j["numero"]), "decisao": tri.instrucao,
                             "regra": body.texto, "escopo": "Todos os laudos",
                             "status": "Aprovada"}])
    orquestrador.reabrir(jid, tri.etapa)
    orquestrador.enfileirar(jid)
    return {"etapa": tri.etapa, "instrucao": tri.instrucao, "decisao": codigo}


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
    return {"avaliador": json.loads(db.setting("avaliador", "{}")),
            "dono_email": _email_dono(), "decisoes": db.decisoes(),
            "aviso_whatsapp": aviso.ligado(),
            "normas": conhecimento.normas_todas()}


@router.get("/aviso/status")
async def status_aviso(_u: dict = Depends(_dono)):
    return await asyncio.to_thread(aviso.status)


@router.put("/config")
async def gravar_config(body: Config, _u: dict = Depends(_dono)):
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
