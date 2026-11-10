"""Orquestrador do João de Barro: encadeia as etapas num pipeline retomável.

Cada etapa persiste sua saída como evento "resultado"; uma etapa com resultado salvo é
pulada (retomada sem nova chamada de IA) desde que seja mais nova que o resultado da etapa
anterior (cadeia monotônica de ids de evento) e que a última volta do revisor que a mandou
refazer. Assim, refazer uma etapa invalida todas as seguintes, inclusive após reinício. Fila: um único worker asyncio por processo (sem trava
entre processos; o backend roda num processo só)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import aviso, calculo, coletor_hub, db, docx_builder, fonte_mercado, ia, nomes, pdf, planilha
from .agentes import _comum, extracao, pesquisa, redacao, revisor, selecao, triagem
from .agentes.selecao import MIN_ESCOLHIDOS, Selecao, area_construida, origem_area_construida

log = logging.getLogger(__name__)

ETAPAS = ["triagem", "extracao", "pesquisa", "selecao", "calculo", "redacao", "montagem",
          "revisao", "entrega"]
BLOQUEADO = "BLOQUEADO"
PARCIAL = "PARCIAL — PENDÊNCIAS"
PRONTO = "PRONTO PARA REVISÃO"
FINAIS = {BLOQUEADO, PARCIAL, PRONTO}
MAX_VOLTAS = 2
INTERVALO_COLETOR_S = 60
MAX_QUEDAS_COLETOR = 4     # quedas do Coletor numa mesma pesquisa; a seguinte vira pendência
ESSENCIAIS = (("area", "constru"), ("endereco",), ("quadra",), ("lote",))
AREA_AUSENTE = "área construída do avaliando ausente"
ESCOLHA_DESCARTADA = "escolha manual descartada (novos candidatos)"
# Avisos que rebaixam a entrega a PARCIAL; casam por igualdade ou como prefixo ("<texto>: ...").
AVISOS_GRAVES = (docx_builder.SEM_LOCALIZACAO, AREA_AUSENTE, docx_builder.SEM_FOTOS,
                 docx_builder.SEM_TARJA, redacao.SECOES_SEM_TEXTO,
                 docx_builder.AMJ_SEM_PROCESSO, docx_builder.PERITO_SEM_QUALIFICACAO)
PDF_AUSENTE = "PDF não gerado (LibreOffice ausente)"

_sleep = asyncio.sleep  # injetável nos testes
_encerrando = False      # ligado pelo hook de shutdown: falha de IA agora é interrupção
# Filho do CLI morto por sinal/encerramento (não é falha da IA): o job deve ser retomado.
_MORTO = re.compile(r"\bkilled\b|\bterminated\b|\bSIG(?:TERM|KILL|INT)\b|"
                    r"exit code:?\s*(?:-9|-15|130|137|143|3221225786)\b", re.I)
MAX_INTERRUPCOES = 2       # interrupções reenfileiradas por job; a seguinte finaliza PARCIAL
REENFILEIRAR = "REENFILEIRAR"   # retorno de executar(): job volta ao fim da fila
CEDER = "CEDER"                 # idem, depois de INTERVALO_COLETOR_S (esperando o Coletor)
INTERROMPIDA = "IA interrompida repetidamente"


# Pendência -> ação que a resolve na UI (C4). Ordem importa: o primeiro padrão que casa vale.
# Casam por substring no texto da pendência (normalizado por _n).
_ACOES: tuple[tuple[str, dict], ...] = (
    ("coletor offline", {"tipo": "ligar_coletor"}),
    ("mapa nao capturado", {"tipo": "ligar_coletor"}),
    ("portal bloqueado", {"tipo": "ligar_coletor"}),
    ("busca falhou", {"tipo": "ligar_coletor"}),
    ("busca sem resultados", {"tipo": "ligar_coletor"}),
    ("amostra com menos de", {"tipo": "ligar_coletor"}),
    (docx_builder.SEM_LOCALIZACAO, {"tipo": "preencher_trabalho", "campo": "pin_maps"}),
    (docx_builder.SEM_FOTOS, {"tipo": "enviar_arquivo", "tipo_arquivo": "foto"}),
    (docx_builder.SEM_TARJA, {"tipo": "enviar_arquivo", "tipo_arquivo": "solicitante"}),
    (docx_builder.AMJ_SEM_PROCESSO, {"tipo": "preencher_trabalho", "campo": "processo_numero"}),
    (extracao.SEM_REFERENCIA, {"tipo": "enviar_arquivo", "tipo_arquivo": "documento"}),
    ("matricula n/i", {"tipo": "enviar_arquivo", "tipo_arquivo": "documento"}),
    (AREA_AUSENTE, {"tipo": "editar_campo", "campo": "Área construída"}),
)
_CAMPO_NA = re.compile(r"campo essencial pendente: (.+)$|"
                       + re.escape(revisor.CAMPO_OBRIGATORIO_NI) + r": (.+?) = n/i")


def acao_pendencia(texto: str) -> dict | None:
    """Ação acionável para a pendência (enviar arquivo, editar campo, ligar o Coletor,
    preencher o trabalho) ou None quando não há atalho na UI."""
    m = _CAMPO_NA.search(texto)
    if m:
        return {"tipo": "editar_campo", "campo": (m.group(1) or m.group(2)).strip()}
    t = _n(texto)
    for chave, acao in _ACOES:
        if _n(chave) in t:
            return dict(acao)
    return None


def pendencias_estruturadas(pends: list[dict]) -> list[dict]:
    """Completa `acao` nas pendências gravadas (inclusive entregas antigas, sem o campo)."""
    out = []
    for p in pends or []:
        p = dict(p)
        if "acao" not in p:
            a = acao_pendencia(str(p.get("texto", "")))
            if a:
                p["acao"] = a
        out.append(p)
    return out


def _grave(msg: str) -> bool:
    return any(msg == g or msg.startswith(g + ":") for g in AVISOS_GRAVES)


def _morto(e: BaseException) -> bool:
    """Falha com cara de filho do CLI morto por sinal."""
    return bool(_MORTO.search(str(e)))


class _Reenfileirar(Exception):
    """Filho da IA morto fora do encerramento: o job volta ao fim da fila."""


class _Ceder(Exception):
    """Sem Coletor e com outros trabalhos esperando: sai da frente e volta depois."""


def encerrar() -> None:
    """Hook de shutdown: daqui em diante falhas de IA não finalizam jobs."""
    global _encerrando
    _encerrando = True


@dataclass
class _Pend:
    texto: str
    grave: bool


class _Parar(Exception):
    """Interrompe o pipeline antes da entrega (pendência impeditiva já registrada)."""


def _n(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.casefold().replace("_", " ").split())


def _eventos(job_id: str, nivel: str, etapa: str | None = None) -> list[dict]:
    sql = "SELECT id, etapa, msg, dados_json FROM av_events WHERE job=? AND nivel=?"
    args: list = [job_id, nivel]
    if etapa:
        sql += " AND etapa=?"
        args.append(etapa)
    with db._conn() as c:
        rows = c.execute(sql + " ORDER BY id", args).fetchall()
    return [{"id": r["id"], "etapa": r["etapa"], "msg": r["msg"],
             "dados": json.loads(r["dados_json"]) if r["dados_json"] else None} for r in rows]


def _ultimo(job_id: str, etapa: str) -> tuple[int, dict | None]:
    """(id, dados) do último resultado da etapa; (0, None) se não houver."""
    with db._conn() as c:
        r = c.execute(
            "SELECT id, dados_json FROM av_events WHERE job=? AND etapa=? AND nivel='resultado' "
            "AND dados_json IS NOT NULL ORDER BY id DESC LIMIT 1", (job_id, etapa)).fetchone()
    return (r["id"], json.loads(r["dados_json"])) if r else (0, None)


def _arquivos_finais(job_id: str) -> dict[str, Path]:
    pasta = db.pasta(job_id)
    nome = nomes.nome_arquivo(_comum.trabalho(job_id))
    return {ext: pasta / f"{nome}.{ext}" for ext in ("docx", "pdf", "xlsx")}


class _Pipeline:
    def __init__(self, job_id: str):
        self.job = job_id
        self.pend: list[_Pend] = []
        self.ultimo_id = 0          # id do resultado da etapa anterior (cadeia)
        self.etapa_atual = "triagem"
        self.r: calculo.Resultado | None = None
        voltas = _eventos(job_id, "volta")
        self.voltas = sum(1 for v in voltas if not (v["dados"] or {}).get("correcao"))
        self.barreira: dict[str, int] = (
            {(voltas[-1]["dados"] or {}).get("etapa", ""): voltas[-1]["id"]} if voltas else {})

    def pendencia(self, texto: str, grave: bool = True) -> None:
        if all(p.texto != texto for p in self.pend):
            self.pend.append(_Pend(texto, grave))

    async def passo(self, etapa: str, fn, valido=lambda d: True):
        """Resultado salvo da etapa (se ainda vale na cadeia), ou roda `fn`."""
        self.etapa_atual = etapa
        rid, d = _ultimo(self.job, etapa)
        minimo = max(self.ultimo_id, self.barreira.get(etapa, 0))
        if d is not None and rid > minimo and valido(d):
            self.ultimo_id = rid
            return d
        db.set_etapa(self.job, etapa, "executando")
        db.evento(self.job, etapa, "inicio", "etapa iniciada")
        ctx = ia.definir_contexto(self.job, etapa)   # custo/tempo/limite de IA por job
        try:
            out = await fn()
        except ia.IAFalhou as e:
            if _encerrando:  # shutdown: fica para a retomada no próximo startup
                raise asyncio.CancelledError(f"IA interrompida: {e}") from e
            if _morto(e):
                self.interrupcao(e)
            db.evento(self.job, etapa, "erro", f"IA falhou: {e}")
            self.pendencia(f"{etapa}: IA falhou ({e})")
            raise _Parar from e
        finally:
            ia._ctx.reset(ctx)
        self.ultimo_id = _ultimo(self.job, etapa)[0]
        return out

    def interrupcao(self, e: BaseException) -> None:
        """Registra a interrupção; abaixo do teto reenfileira, no teto vira pendência grave."""
        anteriores = len(_eventos(self.job, "interrompido"))
        db.evento(self.job, self.etapa_atual, "interrompido", f"IA interrompida: {e}")
        if anteriores < MAX_INTERRUPCOES:
            raise _Reenfileirar from e
        self.pendencia(f"{INTERROMPIDA} ({self.etapa_atual}): {e}")
        raise _Parar from e

    def volta(self, etapa: str, motivo: str) -> None:
        """Registra a volta (persistida: MAX_VOLTAS vale entre reinícios)."""
        db.evento(self.job, "orquestrador", "volta", motivo, dados={"etapa": etapa})
        self.voltas += 1
        self.barreira = {etapa: _eventos(self.job, "volta")[-1]["id"]}
        self.ultimo_id = 0

    # ------------------------------------------------------------- etapas
    async def _triagem(self):
        return (await triagem.rodar(self.job)).model_dump(mode="json")

    async def _extracao(self):
        return (await extracao.rodar(self.job)).model_dump(mode="json")

    async def _esperar_coletor(self) -> None:
        """Marca o job como aguardando e espera um intervalo. Com outros trabalhos na fila
        (o worker é um só) cede a vez: quem só falta redigir/montar não fica preso atrás de
        um PC desligado."""
        db.set_etapa(self.job, "aguardando_coletor", "aguardando")
        if _fila is not None and not _fila.empty():
            raise _Ceder
        await _sleep(INTERVALO_COLETOR_S)

    async def _pesquisa(self):
        fonte = fonte_mercado.atual()
        quedas = 0
        while True:
            while not fonte.online():
                await self._esperar_coletor()
            db.set_etapa(self.job, "pesquisa", "executando")
            try:
                return [r.model_dump(mode="json") for r in await pesquisa.rodar(self.job)]
            except coletor_hub.ColetorOffline as e:  # caiu no meio: espera e refaz do zero
                quedas += 1
                db.evento(self.job, "pesquisa", "info", f"coletor caiu, aguardando: {e}")
                if quedas > MAX_QUEDAS_COLETOR:
                    # cada volta refaz as consultas (IA): sem teto, um Coletor que cai sempre
                    # no mesmo ponto gastava a cota inteira do trabalho em silêncio
                    db.evento(self.job, "pesquisa", "erro",
                              f"coletor offline: caiu {quedas} vezes durante a pesquisa")
                    self.pendencia(f"pesquisa: coletor offline (caiu {quedas} vezes durante a "
                                   "pesquisa; confira o Coletor e use Reprocessar)")
                    raise _Parar from e
                await self._esperar_coletor()

    async def _selecao(self):
        """Escolha manual do avaliador vale enquanto os candidatos forem os mesmos; com
        candidatos novos roda a seleção automática e registra a perda da escolha."""
        ant = db.resultado(self.job, "selecao")
        if ant and ant.get("manual"):
            if {r.get("link") for r in ant.get("refs") or []} == {r.link for r in db.candidatos(self.job)}:
                db.evento(self.job, "selecao", "resultado", "escolha manual do avaliador mantida",
                          dados=ant)
                return ant
            self.pendencia(ESCOLHA_DESCARTADA, grave=False)
        return (await selecao.rodar(self.job)).model_dump(mode="json")

    def _sel(self) -> Selecao:
        return Selecao.model_validate(db.resultado(self.job, "selecao"))

    def _resultado(self) -> calculo.Resultado:
        """Cálculo determinístico (barato): refeito a partir da seleção salva."""
        area = area_construida(self.job)
        if area is None:
            self.pendencia(AREA_AUSENTE)
            raise _Parar
        sel = self._sel()
        try:
            return calculo.calcular(area, [x for x in sel.refs if x.escolhido],
                                    sel.unitario_adotado, sel.faixa_pct)
        except ValueError as e:
            db.evento(self.job, "calculo", "erro", str(e))
            self.pendencia(f"cálculo impossível: {e}")
            raise _Parar from e

    async def _calculo(self):
        r = self._resultado()
        d = {"area": str(area_construida(self.job)), "valor_adotado": str(r.valor_adotado),
             "valor_min": str(r.valor_min), "valor_max": str(r.valor_max),
             "unitario_adotado": str(r.unitario_adotado)}
        db.evento(self.job, "calculo", "resultado", f"valor adotado {r.valor_adotado}", dados=d)
        return d

    async def _redacao(self):
        return (await redacao.rodar(self.job)).model_dump(mode="json")

    async def _montagem(self):
        arqs = _arquivos_finais(self.job)
        sel, textos = self._sel(), redacao.carregar(self.job)
        # Trabalho pesado e síncrono (python-docx, openpyxl, LibreOffice até 2×120 s): fora do
        # event loop, que é o MESMO do painel do Brixly, dos websockets e dos webhooks.
        docx = await asyncio.to_thread(docx_builder.montar, self.job, textos, self.r, sel)
        escolhidos = [x for x in sel.refs if x.escolhido]
        await asyncio.to_thread(
            planilha.gerar, arqs["xlsx"], _comum.trabalho(self.job), area_construida(self.job),
            escolhidos, self.r, origem_area=origem_area_construida(self.job))
        if arqs["pdf"].exists():
            arqs["pdf"].unlink()
        try:
            await asyncio.to_thread(pdf.converter, docx)
        except Exception as e:  # LibreOffice ausente ou falha na conversão
            db.evento(self.job, "montagem", "erro", f"PDF não gerado: {e}")
        d = {"docx": docx.name, "xlsx": arqs["xlsx"].name,
             "pdf": arqs["pdf"].name if arqs["pdf"].exists() else None}
        db.evento(self.job, "montagem", "resultado", "laudo montado", dados=d)
        return d

    # ------------------------------------------------------------- execução
    async def executar(self) -> str:
        fim = db.resultado(self.job, "entrega")
        if fim is not None:
            return fim["status"]
        try:
            tri = await self.passo("triagem", self._triagem)
            if tri.get("bloqueado"):
                self.pendencia(f"triagem bloqueada: {tri.get('motivo', '')}")
                return self._entregar(BLOQUEADO)
            await self._ate_revisao()
        except _Parar:
            pass
        except _Reenfileirar:
            return REENFILEIRAR
        except _Ceder:
            return CEDER
        except Exception as e:  # falha terminal: entrega o que houver, job finalizado
            if _encerrando:  # CLI morto no encerramento: fica para a retomada
                raise asyncio.CancelledError(f"interrompido: {e}") from e
            if _morto(e):
                try:
                    self.interrupcao(e)
                except _Reenfileirar:
                    return REENFILEIRAR
                except _Parar:
                    return self._entregar(None)
            log.exception("avaliação %s: falha na etapa %s", self.job, self.etapa_atual)
            db.evento(self.job, self.etapa_atual, "erro", f"falha inesperada: {e}")
            self.pendencia(f"falha inesperada na etapa {self.etapa_atual}: "
                           f"{type(e).__name__}: {e}")
        return self._entregar(None)

    async def _ate_revisao(self) -> None:
        i = ETAPAS.index("extracao")
        while True:
            etapa = ETAPAS[i]
            if etapa == "revisao":
                rev = await self._revisao()
                if rev is None or rev.aprovado:
                    return
                if self.voltas >= MAX_VOLTAS or not rev.problemas:
                    for p in rev.problemas:
                        self.pendencia(f"revisor ({p.camada}/{p.etapa_responsavel}): "
                                       f"{p.descricao}")
                    return
                i = min(ETAPAS.index(p.etapa_responsavel) for p in rev.problemas)
                # a etapa refeita precisa saber O QUE o revisor reprovou; sem isso a volta
                # era às cegas e repetia o mesmo erro até acabar MAX_VOLTAS
                for p in rev.problemas:
                    db.evento(self.job, p.etapa_responsavel, "revisor", p.descricao)
                self.volta(ETAPAS[i], "revisor reprovou")
                continue
            if etapa == "calculo":
                await self.passo("calculo", self._calculo)
                self.r = self._resultado()
            elif etapa == "montagem":
                try:
                    await self.passo("montagem", self._montagem, lambda d: "xlsx" in d)
                except docx_builder.ConteudoProibido as e:
                    db.evento(self.job, "montagem", "erro", f"conteúdo proibido: {e}")
                    if self.voltas >= MAX_VOLTAS:
                        self.pendencia(f"conteúdo proibido no laudo: {e}")
                        raise _Parar from e
                    i = ETAPAS.index("redacao")
                    db.evento(self.job, "redacao", "revisor",
                              f"o texto anterior foi recusado por conter conteúdo proibido: {e}")
                    self.volta("redacao", f"conteúdo proibido: {e}")
                    continue
            elif etapa == "redacao":
                d = await self.passo("redacao", self._redacao)
                if d.get("faltas") and self.voltas < MAX_VOLTAS:
                    # seção abaixo do mínimo: refaz a redação (o prompt recebe as faltas)
                    self.volta("redacao", f"{redacao.SECOES_SEM_TEXTO}: "
                                          + "; ".join(d["faltas"]))
                    continue
            else:
                await self.passo(etapa, getattr(self, f"_{etapa}"))
            i += 1

    async def _revisao(self) -> revisor.Revisao | None:
        p = _arquivos_finais(self.job)["pdf"]
        if not p.exists():
            self.pendencia(PDF_AUSENTE)
            return None

        async def rodar():
            return (await revisor.rodar(self.job, p, self.r)).model_dump(mode="json")
        try:
            d = await self.passo("revisao", rodar)
        except _Parar:  # IA falhou: pendência já registrada
            return None
        return revisor.Revisao.model_validate(d)

    # ------------------------------------------------------------- entrega
    def _coletar(self) -> None:
        inicio = {e["etapa"]: e["id"] for e in _eventos(self.job, "inicio")}
        for e in _eventos(self.job, "aviso"):
            if e["id"] < inicio.get(e["etapa"], 0):
                continue  # aviso de uma execução anterior da etapa (já refeita)
            self.pendencia(f"{e['etapa']}: {e['msg']}", grave=_grave(e["msg"]))
        for c in db.campos(self.job):
            nome = _n(c.nome)
            if c.origem == "pendente" and any(all(k in nome for k in ks) for ks in ESSENCIAIS):
                self.pendencia(f"campo essencial pendente: {c.nome}")
        sel_d = db.resultado(self.job, "selecao")
        if sel_d:
            sel = Selecao.model_validate(sel_d)
            if sel.declaracao_amostra.startswith("Amostra reduzida"):
                self.pendencia(f"amostra com menos de {MIN_ESCOLHIDOS} referenciais: "
                               f"{sel.declaracao_amostra}")

    def _entregar(self, status: str | None) -> str:
        if status is None:
            self._coletar()
            status = PARCIAL if any(p.grave for p in self.pend) else PRONTO
        destino = db.pasta(self.job) / "entrega"
        destino.mkdir(parents=True, exist_ok=True)
        copiados = []
        for p in _arquivos_finais(self.job).values():
            if p.exists():
                shutil.copy2(p, destino / p.name)
                copiados.append(p.name)
        linhas = [f"# Pendências — {status}", ""]
        linhas += ([f"- {'[impeditiva] ' if p.grave else ''}{p.texto}" for p in self.pend]
                   or ["Nenhuma pendência."])
        (destino / "pendencias.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
        db.evento(self.job, "entrega", "resultado", status, dados={
            "status": status, "arquivos": copiados,
            "pendencias": pendencias_estruturadas(
                [{"texto": p.texto, "grave": p.grave} for p in self.pend])})
        db.set_etapa(self.job, "entrega", status)
        return status


async def executar(job_id: str) -> str:
    """Roda (ou retoma) o pipeline do job; devolve o status final. Ao finalizar agora (não
    numa retomada de job já entregue) avisa o avaliador; erro no aviso nunca falha o job."""
    ja_entregue = db.resultado(job_id, "entrega") is not None
    status = await _Pipeline(job_id).executar()
    if status in FINAIS and not ja_entregue:
        try:
            await asyncio.to_thread(aviso.avisar_fim, job_id)
        except Exception:
            log.exception("avaliação %s: aviso de fim falhou", job_id)
    return status


def reabrir(job_id: str, etapa: str, motivo: str = "correção do avaliador") -> None:
    """Invalida a etapa e todas as seguintes (barreira de volta, que não conta em MAX_VOLTAS)
    e desfaz a entrega, para o job voltar à fila."""
    if etapa not in ETAPAS:
        raise ValueError(etapa)
    db.evento(job_id, "orquestrador", "volta", motivo, dados={"etapa": etapa, "correcao": True})
    db.arquivar_entrega(job_id)
    db.set_etapa(job_id, etapa, "pendente")


# ------------------------------------------------------------------- fila
_fila: asyncio.Queue | None = None
_worker: asyncio.Task | None = None
_ativos: set[str] = set()   # na fila ou executando


def ocupado(job_id: str) -> bool:
    return job_id in _ativos


def enfileirar(job_id: str) -> None:
    if _fila is None:
        raise RuntimeError("fila não iniciada (chame iniciar_fila)")
    if job_id in _ativos:
        return
    _ativos.add(job_id)
    _fila.put_nowait(job_id)


_esperas: set[asyncio.Task] = set()   # jobs que cederam a vez, esperando para voltar à fila


async def _voltar_depois(jid: str) -> None:
    """Devolve à fila, depois do intervalo, o job que cedeu a vez (segue em _ativos: para
    as rotas ele continua em execução)."""
    await _sleep(INTERVALO_COLETOR_S)
    if not _encerrando and _fila is not None:
        _fila.put_nowait(jid)


def _falha_final(jid: str, e: BaseException) -> None:
    """Falha fora do pipeline (ex.: disco cheio ao entregar): sem isto o job ficava em
    "executando" para sempre, sem botão que o destravasse."""
    try:
        db.evento(jid, "orquestrador", "erro", f"falha inesperada: {type(e).__name__}: {e}")
        if db.resultado(jid, "entrega") is None:
            db.evento(jid, "entrega", "resultado", PARCIAL, dados={
                "status": PARCIAL, "arquivos": [], "pendencias": [{
                    "texto": f"falha inesperada ao finalizar o trabalho: {type(e).__name__}: {e}",
                    "grave": True}]})
        db.set_etapa(jid, "entrega", PARCIAL)
    except Exception:
        log.exception("avaliação %s: não foi possível registrar a falha", jid)


async def _trabalhar() -> None:
    while True:
        jid = await _fila.get()
        reenfileirar = False
        ceder = False
        try:
            status = await executar(jid)
            reenfileirar = status == REENFILEIRAR
            ceder = status == CEDER
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if _encerrando or (task is not None and task.cancelling()):
                raise  # o worker está sendo encerrado de verdade
            log.warning("avaliação %s: cancelamento interno; job reenfileirado", jid)
            reenfileirar = True
        except Exception as e:
            log.exception("avaliação %s falhou", jid)
            _falha_final(jid, e)
        finally:
            if ceder and not _encerrando:
                t = asyncio.get_running_loop().create_task(_voltar_depois(jid))
                _esperas.add(t)
                t.add_done_callback(_esperas.discard)
            else:
                _ativos.discard(jid)
                if reenfileirar and not _encerrando:
                    enfileirar(jid)  # vai para o fim da fila, depois dos que já esperam
            _fila.task_done()


def iniciar_fila() -> asyncio.Task:
    """No startup: cria o worker (idempotente) e reenfileira jobs não finalizados."""
    global _fila, _worker, _encerrando
    _encerrando = False
    if _worker is not None and not _worker.done():
        return _worker
    db.init()
    _fila = asyncio.Queue()
    _ativos.clear()
    for t in list(_esperas):
        t.cancel()
    _esperas.clear()
    _worker = asyncio.get_running_loop().create_task(_trabalhar())
    # 'nova' = criado mas ainda não iniciado (o avaliador pode estar subindo os documentos):
    # reiniciar o servidor não pode disparar a avaliação com metade dos arquivos.
    with db._conn() as c:
        rows = c.execute("SELECT id, status FROM av_jobs WHERE etapa NOT IN ('entrega', 'nova') "
                         "ORDER BY criado").fetchall()
    for r in rows:
        if r["status"] not in FINAIS:
            enfileirar(r["id"])
    return _worker
