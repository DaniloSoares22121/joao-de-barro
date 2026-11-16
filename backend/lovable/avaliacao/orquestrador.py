"""Orquestrador do João de Barro: encadeia as etapas num pipeline retomável.

Cada etapa persiste sua saída como evento "resultado"; uma etapa com resultado salvo é
pulada (retomada sem nova chamada de IA) desde que seja mais nova que o resultado da etapa
anterior (cadeia monotônica de ids de evento) e que a última volta do revisor que a mandou
refazer. Assim, refazer uma etapa invalida todas as seguintes, inclusive após reinício. Fila: um único worker asyncio por processo (sem trava
entre processos; o backend roda num processo só)."""
from __future__ import annotations

import asyncio
from decimal import Decimal
import json
import logging
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import aviso, calculo, db, docx_builder, fonte_mercado, ia, nomes, pdf, planilha
from .agentes import _comum, extracao, redacao, revisor, selecao, triagem
from .agentes.selecao import (MIN_ESCOLHIDOS, Selecao, area_construida, escolha_area,
                              origem_area_construida, refs_na_base)
from .plural import pl

log = logging.getLogger(__name__)

ETAPAS = ["triagem", "extracao", "pesquisa", "selecao", "calculo", "redacao", "montagem",
          "revisao", "entrega"]
BLOQUEADO = "BLOQUEADO"
NL = chr(10)
PARCIAL = "PARCIAL — PENDÊNCIAS"
PRONTO = "PRONTO PARA REVISÃO"
CANCELADO = "CANCELADO"          # o avaliador tocou em "Cancelar" (ORDEM 007)
FINAIS = {BLOQUEADO, PARCIAL, PRONTO, "ERRO TÉCNICO", CANCELADO}
CUSTO_NAO_VOLTA = ("Trabalho cancelado pelo avaliador. O custo de IA já gasto não volta; "
                   "use \"Reabrir\" para continuar de onde parou ou exclua o trabalho.")
MAX_VOLTAS = 2
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
INTERROMPIDA = "IA interrompida repetidamente"


# Pendência -> ação que a resolve na UI (C4). Ordem importa: o primeiro padrão que casa vale.
# Casam por substring no texto da pendência (normalizado por _n).
_ACOES: tuple[tuple[str, dict], ...] = (
    ("coletor offline", {"tipo": "ligar_coletor"}),
    ("mapa nao capturado", {"tipo": "ligar_coletor"}),
    (docx_builder.SEM_LOCALIZACAO, {"tipo": "preencher_trabalho", "campo": "pin_maps"}),
    (docx_builder.SEM_FOTOS, {"tipo": "enviar_arquivo", "tipo_arquivo": "foto"}),
    (docx_builder.SEM_TARJA, {"tipo": "enviar_arquivo", "tipo_arquivo": "solicitante"}),
    (docx_builder.AMJ_SEM_PROCESSO, {"tipo": "preencher_trabalho", "campo": "processo_numero"}),
    (extracao.SEM_REFERENCIA, {"tipo": "enviar_arquivo", "tipo_arquivo": "documento"}),
    ("matricula n/i", {"tipo": "enviar_arquivo", "tipo_arquivo": "documento"}),
    (AREA_AUSENTE, {"tipo": "editar_campo", "campo": "Área construída"}),
    # triagem bloqueada por falta de documento: abre as três caixas de envio
    ("triagem bloqueada", {"tipo": "enviar_arquivo"}),
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


class _CanceladoAvaliador(Exception):
    """O avaliador tocou em "Cancelar": para no fim da chamada em andamento / entre etapas."""


_cancelar: set[str] = set()             # jobs com "Cancelar" pedido


def _checar_cancelamento(job_id: str) -> None:
    if job_id in _cancelar:
        raise _CanceladoAvaliador


def marcar_cancelado(job_id: str, etapa: str = "") -> str:
    """Finaliza como CANCELADO (sem apagar nada: os resultados já pagos ficam para o Reabrir)."""
    _cancelar.discard(job_id)
    db.evento(job_id, "entrega", "resultado", CANCELADO, dados={
        "status": CANCELADO, "arquivos": [], "etapa_cancelada": etapa or "",
        "pendencias": [{"texto": CUSTO_NAO_VOLTA, "grave": True}]})
    db.set_etapa(job_id, "entrega", CANCELADO)
    return CANCELADO


def pedir_cancelamento(job_id: str) -> str:
    """"Cancelar" da tela. Rodando: marca o pedido (interrompe na próxima chance).
    Parado (aguardando o avaliador, na fila sem rodar): cancela já."""
    j = db.job(job_id)
    if j["status"] in FINAIS:
        return j["status"]
    db.evento(job_id, "orquestrador", "info", "cancelamento pedido pelo avaliador")
    if job_id in _ativos:
        _cancelar.add(job_id)
        return "CANCELANDO"
    return marcar_cancelado(job_id, j["etapa"] if j["etapa"] != "entrega" else "")


def encerrar() -> None:
    """Hook de shutdown: daqui em diante falhas de IA não finalizam jobs."""
    global _encerrando
    _encerrando = True


@dataclass
class _Pend:
    texto: str
    grave: bool
    tecnico: bool = False   # falha do sistema (IA/programa), não pendência do avaliador


ERRO_TECNICO = "ERRO TÉCNICO"


ROTULO_ETAPA = {
    "triagem": "triagem", "extracao": "extração", "pesquisa": "pesquisa", "selecao": "seleção",
    "calculo": "cálculo", "redacao": "redação", "montagem": "montagem", "revisao": "revisão",
    "entrega": "entrega", "localizacao": "localização", "fachada": "fachada",
    "orquestrador": "andamento",
}


MAX_REVISOES = 2   # ORDEM 010: no máximo 2 rodadas de revisão por geração; o resto vira pendência


def marco_avaliador(job_id: str) -> int:
    """Id da última geração pedida pelo avaliador (reabrir/confirmar/retomar — eventos "volta" com dados.correcao
    ou de confirmação); 0 = desde o início."""
    with db._conn() as c:
        voltas = c.execute("SELECT id, msg, dados_json FROM av_events WHERE job=? AND "
                           "etapa='orquestrador' AND nivel='volta' ORDER BY id", (job_id,)).fetchall()
    marco = 0
    for v in voltas:
        d = json.loads(v["dados_json"] or "{}")
        if d.get("correcao") or "confirmad" in (v["msg"] or ""):
            marco = v["id"]
    return marco


def rodadas_revisao(job_id: str) -> int:
    """Rodadas de revisão desde a última geração pedida pelo avaliador (ou desde o início)."""
    marco = marco_avaliador(job_id)
    with db._conn() as c:
        return c.execute("SELECT COUNT(*) FROM av_events WHERE job=? AND etapa='revisao' AND "
                         "nivel='resultado' AND id>?", (job_id, marco)).fetchone()[0]


def rotulo_etapa(etapa: str) -> str:
    """Nome da etapa com acento, para mensagens da tela ("redacao" -> "redação")."""
    return ROTULO_ETAPA.get(etapa, etapa)


def amigavel(e: BaseException | str, etapa: str = "") -> str:
    """Mensagem para a tela (o detalhe técnico vai só para o log)."""
    s = str(e)
    onde = f" na etapa {rotulo_etapa(etapa)}" if etapa else ""
    if "cota" in s or "limite" in s.casefold():
        return f"o limite de uso da IA foi atingido{onde}; tente de novo mais tarde"
    if "timeout" in s.casefold() or "não respondeu" in s:
        return f"a IA demorou demais para responder{onde}; tente de novo"
    if "JSON" in s or "resposta inválida" in s:
        return f"a IA devolveu uma resposta que o sistema não conseguiu ler{onde}; tente de novo"
    return f"falha técnica{onde}; tente de novo (detalhe no registro do sistema)"


def corrigir_data_base(job_id: str) -> bool:
    """086-8 / 085-1: o avaliador informou a DITCD (ou escolheu a data-base no portão) e o trabalho está com outra
    (ex.: a da vistoria) → o JdB corrige sozinho e deixa um aviso. Nunca inventa: sem data informada, não mexe."""
    # 117 / D-127 (regra do Capitão): a data de referência do laudo é SEMPRE a data da vistoria; nenhuma data de outro
    # documento (DITCD, ciência da malha, escritura) vira data-base. A DITCD continua só como fato do processo fiscal.
    try:
        t = _comum.trabalho(job_id)
        nova = t.data_vistoria
    except Exception:
        return False
    if t.data_base == nova:
        return False
    antes = t.data_base.strftime("%d/%m/%Y")
    db.atualizar_dados(job_id, t.model_copy(update={"data_base": nova}))
    db.evento(job_id, "orquestrador", "info", f"data de referência do laudo: {nova.strftime('%d/%m/%Y')}, a da vistoria "
              f"(antes {antes}; regra D-127)")
    return True


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").split())


def limpar_emissao_velha(job_id: str) -> bool:
    """090-2: a data de emissão/assinatura é a do dia da montagem; data gravada antes da última consulta aos
    anúncios (ex.: o dia em que o trabalho foi aberto) é apagada, e a montagem usa o dia de hoje."""
    from datetime import date as _date
    try:
        t = _comum.trabalho(job_id)
        if not t.data_emissao:
            return False
        acessos = [str(r.acessado_em)[:10] for r in db.candidatos(job_id) if getattr(r, "acessado_em", "")]
        ultima = max((_date.fromisoformat(a) for a in acessos if re.match(r"\d{4}-\d{2}-\d{2}$", a)), default=None)
    except Exception:
        return False
    if ultima is None or t.data_emissao >= ultima:
        return False
    db.atualizar_dados(job_id, t.model_copy(update={"data_emissao": None}))
    db.evento(job_id, "orquestrador", "aviso", f"data de emissão {t.data_emissao.strftime('%d/%m/%Y')} era anterior à "
              f"última consulta ({ultima.strftime('%d/%m/%Y')}): corrigida sozinho para o dia da montagem")
    return True


def padronizar_bairro(job_id: str) -> bool:
    """117 / D-131 (regra do Capitão, troca a 088-3): o bairro do laudo (capa, cabeçalho, corpo, resumo, nome do arquivo)
    é escrito como no documento, com o nome COMPLETO do setor — "Jardim Curitiba I" (conta de água) vale sobre
    "Jardim Curitiba" quando um é o outro com o número da etapa/setor. Nome diferente de verdade: não troca."""
    try:
        t = _comum.trabalho(job_id)
        docs = [str(c.valor).strip() for c in db.campos(job_id) if c.origem == "documento" and c.valor]
    except Exception:
        return False
    atual = (t.bairro or "").strip()
    if not atual or not docs:
        return False
    sufixo = r"(?:\s+(?:[ivx]+|\d+|etapa\s+\w+))"
    rx = re.compile(r"(?<!\w)" + re.escape(_norm(atual)) + sufixo + r"(?!\w)")
    achados = [m.group(0) for d in docs for m in [rx.search(_norm(d))] if m]       # "fatura saneago, jardim curitiba i"
    if not achados:
        return False
    fim = max(achados, key=len)[len(_norm(atual)):].strip()
    doc = f"{atual} {fim.upper() if re.fullmatch(r'[ivx]+', fim) else fim}"
    db.atualizar_dados(job_id, t.model_copy(update={"bairro": doc}))
    db.evento(job_id, "orquestrador", "info", f"bairro como no documento: \"{atual}\" → \"{doc}\" (nome completo do setor, D-131)")
    return True


# 097-3: reforço que é só texto × reforço que pede decisão do avaliador
_SO_TEXTO = re.compile(r"(?i)explic|justific|deixar claro|esclarec|mencion|citar|registr|ajust\w* a frase|reescrev|declar|informar")
_DECISAO = re.compile(r"(?i)exclu|retir|tirar|substitu|trocar (?:o |a )?referencial|homogeneiz|nova pesquisa|incluir (?:mais|outros) "
                      r"referenciais|anexar|certid|recalcul|mudar o valor|reduzir|aumentar")


VALOR_MUDOU = "Com os dados novos o valor muda"


def _brl(v) -> str:
    return "R$ " + f"{float(v):,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


class _Parar(Exception):
    """Interrompe o pipeline antes da entrega (pendência impeditiva já registrada)."""


def _eh_do_texto(descricao: str) -> bool:
    """077-4: problema que o JdB corrige sozinho reescrevendo (não depende de documento novo do avaliador)."""
    t = (descricao or "").casefold()
    return any(k in t for k in ("documentação analisada", "documentacao analisada", "sem data", "com '—'", "concord",
                                "duplicad", "repetid", "anexo trocado", "número do anexo", "numero do anexo",
                                "campo interno", "fora do lugar", "legenda", "hífen", "hifen", "lista de caracter",
                                "presente parecer", "sindim", "ordem dos documentos", "ordem do quadro"))


class _SemFotos(Exception):
    """074-A2 (P5 §C): sem foto da vistoria o laudo para ANTES de escrever (não gera PDF vazio)."""


SEM_FOTOS = ("Faltam as fotos da vistoria (com uma de fachada boa para a capa). Mande as fotos e toque em "
             "Conferir os documentos de novo.")


class _Aguardar(Exception):
    """Pausa até o avaliador confirmar referenciais, unitário e faixa (antes da redação)."""


AGUARDANDO = "AGUARDANDO_AVALIADOR"   # retorno de executar() e status do job na pausa


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


_FALHOU_CONTORNO = "demarcado quadrado em volta do pino"


def _ultimo_aviso_mapa(job_id: str) -> int:
    with db._conn() as c:
        r = c.execute("SELECT MAX(id) FROM av_events WHERE job=? AND etapa='localizacao' AND nivel='aviso' AND msg LIKE ?",
                      (job_id, f"%{_FALHOU_CONTORNO}%")).fetchone()
    return int(r[0] or 0)


async def _mapa_com_retentativa(job_id: str, maps) -> None:
    """111-3e: o contorno do lote não saiu (a IA não pegou o lote do pin) → refaz pelo pin sozinho, uma vez, antes de
    mostrar ao avaliador. Só se falhar de novo vira o cartão "O mapa precisa ser refeito"."""
    antes = _ultimo_aviso_mapa(job_id)
    await maps(job_id, _comum.trabalho(job_id))
    if _ultimo_aviso_mapa(job_id) <= antes:
        return
    db.evento(job_id, "localizacao", "info", "contorno do lote não saiu; refazendo o mapa pelo pin sozinho (uma vez)")
    meio = _ultimo_aviso_mapa(job_id)
    from . import coletor_fonte                 # a captura do módulo aceita "refazer" (a do método não)
    await coletor_fonte.capturar_maps(job_id, _comum.trabalho(job_id), refazer=True)
    if _ultimo_aviso_mapa(job_id) <= meio:
        db.evento(job_id, "localizacao", "info", "mapa refeito sozinho pelo pin: lote demarcado")
        _tirar_aviso_mapa(job_id, meio)


def _tirar_aviso_mapa(job_id: str, ev: int) -> None:
    """O aviso da 1ª tentativa deixa de valer quando a 2ª deu certo (não vira cartão)."""
    with db._conn() as c:
        c.execute("UPDATE av_events SET nivel='aviso_resolvido' WHERE id=?", (ev,))


def _guardar_arquivos_velhos(job_id: str, entrega: Path) -> list[str]:
    """125-3: quando o nome do laudo muda (ex.: "Jardim Curitiba" → "Jardim Curitiba I"), o Word/PDF/planilha com o
    nome antigo não fica lado a lado com o novo: vai para revisoes/arquivos-antigos/ (nada é apagado). O assinado fica."""
    atuais = {p.name for p in _arquivos_finais(job_id).values()}
    guarda = db.pasta(job_id) / "revisoes" / "arquivos-antigos"
    movidos = []
    for pasta in (db.pasta(job_id), entrega):
        for f in pasta.glob("*"):
            if (f.is_file() and f.suffix.lower() in (".docx", ".pdf", ".xlsx") and f.name not in atuais
                    and not f.stem.lower().endswith("_assinado")):
                guarda.mkdir(parents=True, exist_ok=True)
                alvo = guarda / (f"entrega-{f.name}" if pasta == entrega else f.name)
                shutil.move(str(f), str(alvo))
                movidos.append(f.name)
    if movidos:
        db.evento(job_id, "entrega", "info", "arquivos com o nome antigo guardados em revisoes/arquivos-antigos: "
                  + ", ".join(sorted(set(movidos))))
    return movidos


class _Pipeline:
    def __init__(self, job_id: str):
        self.job = job_id
        self.pend: list[_Pend] = []
        self.ultimo_id = 0          # id do resultado da etapa anterior (cadeia)
        self.etapa_atual = "triagem"
        self.r: calculo.Resultado | None = None
        self.extra: dict = {}       # ORDEM 039: coerência (D-084) e contestação (D-083) na entrega
        voltas = _eventos(job_id, "volta")
        # 113-1: as voltas automáticas contam desde o último pedido do avaliador (antes: o histórico todo, e depois de
        # algumas remontagens o JdB parava de corrigir sozinho o que o revisor apontava)
        marco = marco_avaliador(job_id)
        self.voltas = sum(1 for v in voltas if not (v["dados"] or {}).get("correcao") and v["id"] > marco)
        self.reforcar_agora = False
        self.barreira: dict[str, int] = (
            {(voltas[-1]["dados"] or {}).get("etapa", ""): voltas[-1]["id"]} if voltas else {})

    def pendencia(self, texto: str, grave: bool = True, tecnico: bool = False) -> None:
        if all(p.texto != texto for p in self.pend):
            self.pend.append(_Pend(texto, grave, tecnico))

    async def passo(self, etapa: str, fn, valido=lambda d: True):
        """Resultado salvo da etapa (se ainda vale na cadeia), ou roda `fn`."""
        self.etapa_atual = etapa
        rid, d = _ultimo(self.job, etapa)
        minimo = max(self.ultimo_id, self.barreira.get(etapa, 0))
        if d is not None and rid > minimo and valido(d):
            self.ultimo_id = rid
            return d
        _checar_cancelamento(self.job)   # "Cancelar": entre etapas / fim da chamada anterior
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
            log.warning("avaliação %s: IA falhou em %s: %s", self.job, etapa, e)
            db.evento(self.job, etapa, "erro", amigavel(e, etapa).capitalize(),
                      dados={"detalhe": str(e)[:2000], "tecnico": True})
            self.pendencia(amigavel(e, etapa).capitalize(), tecnico=True)
            raise _Parar from e
        finally:
            ia._ctx.reset(ctx)
        self.ultimo_id = _ultimo(self.job, etapa)[0]
        _checar_cancelamento(self.job)   # a chamada terminou (resultado guardado): para aqui
        return out

    def interrupcao(self, e: BaseException) -> None:
        """Registra a interrupção; abaixo do teto reenfileira, no teto vira pendência grave."""
        anteriores = len(_eventos(self.job, "interrompido"))
        db.evento(self.job, self.etapa_atual, "interrompido", f"IA interrompida: {e}")
        if anteriores < MAX_INTERRUPCOES:
            raise _Reenfileirar from e
        self.pendencia(f"{INTERROMPIDA} ({rotulo_etapa(self.etapa_atual)}): {e}")
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

    def _manuais(self) -> list:
        return [r for r in db.candidatos(self.job)
                if r.fonte_coleta == selecao.MANUAL and r.area_m2 and r.preco]

    async def _so_manuais(self, fonte, refs: list | None = None) -> list:
        """Amostra completa cadastrada pelo avaliador: dispensa os portais (funciona com o
        Coletor desligado); o Coletor, se online, só captura o mapa."""
        refs = self._manuais() if refs is None else refs
        maps = getattr(fonte, "capturar_maps", None)
        if maps is not None and fonte.online():
            try:
                await _mapa_com_retentativa(self.job, maps)
            except Exception as e:
                if not any(db.pasta(self.job).glob("maps*.png")):      # 095-9: a imagem que já existe vale
                    db.evento(self.job, "pesquisa", "aviso", f"{docx_builder.SEM_LOCALIZACAO}: {e}")
        elif maps is not None and not any(db.pasta(self.job).glob("maps*.png")):
            # 095-9: imagem de localização que já existe vale; o aviso só quando não há imagem nenhuma
            db.evento(self.job, "localizacao", "aviso", "mapa não capturado (coletor offline)")
        refs = await self._fotos_dos_anuncios(fonte, refs)
        db.evento(self.job, "pesquisa", "resultado",
                  f"{pl(len(refs), 'referencial cadastrado', 'referenciais cadastrados')} pelo avaliador; portais não consultados",
                  dados={"consultas": [], "candidatos": [r.model_dump(mode="json") for r in refs]})
        return [r.model_dump(mode="json") for r in refs]

    async def _fotos_dos_anuncios(self, fonte, refs: list) -> list:
        """074-F4 (D-014): a tabela de amostras leva a foto principal de cada anúncio. Referencial cadastrado
        sem foto: a foto vem pela extensão (112: o Coletor não abre mais anúncio); sem ela, avisa antes da revisão."""
        faltam = [r.n for r in refs if not r.foto]
        if faltam:
            self.pendencia(f"Sem a foto principal dos anúncios nº {', '.join(map(str, faltam))}: abra cada um no seu Chrome "
                           "e toque em Enviar ao JdB (a tabela de amostras leva a foto).", grave=False)
        return refs

    def _entra(self) -> list:
        """Escolhidos pelo avaliador na lista ("Entra no laudo") + cadastrados à mão."""
        return [r for r in db.candidatos(self.job)
                if (r.decisao == "entra" or (r.fonte_coleta == selecao.MANUAL and r.decisao != "descarta"))
                and r.area_m2 and r.preco]

    async def _pesquisa(self):
        """D-117 / 112: sem busca nos portais. Os anúncios vêm do Chrome do avaliador (extensão "Enviar ao JdB") ou
        do cadastro à mão; com 5 ou mais escolhidos, segue (o programa do PC só captura o mapa)."""
        fonte = fonte_mercado.atual()
        entra = self._entra()
        if len(entra) < MIN_ESCOLHIDOS:
            db.evento(self.job, "pesquisa", "info",
                      f"aguardando o avaliador trazer os anúncios ({len(entra)} de no mínimo {MIN_ESCOLHIDOS}): "
                      "pesquise no seu Chrome e envie com a extensão, ou cadastre à mão")
            db.set_etapa(self.job, "pesquisa", AGUARDANDO)
            raise _Aguardar
        por_n = {r.n: r.model_copy(update={"escolhido": r.n in {e.n for e in entra}}) for r in db.candidatos(self.job)}
        db.salvar_candidatos(self.job, list(por_n.values()))
        return await self._so_manuais(fonte, [por_n[r.n] for r in entra])

    async def _selecao(self):
        """Escolha manual do avaliador vale enquanto os candidatos forem os mesmos; com
        candidatos novos roda a seleção automática e registra a perda da escolha."""
        ant = db.resultado(self.job, "selecao")
        if ant and ant.get("manual"):
            # 094-2: só a amostra DA CONTA decide (link, preço, área); incluir/tirar comparação, trocar foto ou
            # reenviar com o mesmo preço e área mantém a escolha e o valor confirmados
            cands = db.candidatos(self.job)

            def _conta(lst):
                # L200 (Caso W): só os ESCOLHIDOS para a conta. Antes entrava a lista inteira: trocar quem entra
                # (mesmos candidatos) mantinha a escolha antiga e o laudo saía com os referenciais velhos
                return {(r.get("link"), r.get("preco"), r.get("area_m2")) for r in lst
                        if r.get("escolhido") and r.get("decisao") != "comparacao" and r.get("decisao") != "descarta"}
            atuais = [c.model_dump(mode="json") for c in cands]
            if _conta(ant.get("refs") or []) == _conta(atuais):
                por_n = {c.n: c.model_dump(mode="json") for c in cands}
                ant = {**ant, "refs": [({**por_n[r["n"]], "escolhido": r.get("escolhido", False) and por_n[r["n"]].get("decisao") != "comparacao",
                                         "justificativa": r.get("justificativa", "")} if r.get("n") in por_n else r)
                                       for r in ant.get("refs") or []]
                       + [{**c, "escolhido": False} for n, c in por_n.items()
                          if n not in {r.get("n") for r in ant.get("refs") or []}]}
                if ant.get("confirmado"):
                    ant["proposta_ia"] = None      # 094-3: valor confirmado → a proposta velha da IA sai da tela
                db.evento(self.job, "selecao", "resultado", "escolha manual do avaliador mantida", dados=ant)
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
        from .agentes import selecao as _s
        unit, problema = _s.unitario_valido(sel)
        if problema:          # 082-4: amostra mudou com unitário fixo → para e pergunta (nunca sai média ≠ adotado)
            media = calculo.calcular(area, refs_na_base(self.job, [x for x in sel.refs if x.escolhido]),
                                     None, sel.faixa_pct).media
            br = lambda v: f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")   # L200: só nos números
            self.pendencia(f"{problema}: a média agora é R$ {br(media)}/m²; você tinha adotado "
                           f"R$ {br(sel.unitario_adotado)}/m². Usar a média ou confirmar de novo o unitário, "
                           "com a sua justificativa.")
            raise _Parar
        try:
            return calculo.calcular(area, refs_na_base(self.job, [x for x in sel.refs if x.escolhido]),
                                    unit, sel.faixa_pct)
        except ValueError as e:
            db.evento(self.job, "calculo", "erro", str(e))
            self.pendencia(f"cálculo impossível: {e}")
            raise _Parar from e

    async def _calculo(self):
        r = self._resultado()
        conf = db.setting(f"valor_confirmado:{self.job}") or ""
        if conf and Decimal(conf) != r.valor_adotado:
            # 082-5: mudança que altera o valor não remonta calada — o avaliador confere os anúncios
            self.pendencia(f"{VALOR_MUDOU}: passaria de {_brl(Decimal(conf))} para {_brl(r.valor_adotado)}. "
                           "Conferir os anúncios e confirmar o valor de novo?")
            raise _Parar
        d = {"area": str(area_construida(self.job)), "valor_adotado": str(r.valor_adotado),
             "valor_min": str(r.valor_min), "valor_max": str(r.valor_max),
             "unitario_adotado": str(r.unitario_adotado)}
        db.evento(self.job, "calculo", "resultado", f"valor adotado {r.valor_adotado}", dados=d)
        return d

    async def _redacao(self):
        if db.setting(f"so_numeros:{self.job}"):       # 153-3: troca de referencial — só os números, sem a IA
            feito = self._redacao_so_numeros()
            if feito is not None:
                return feito
        return (await redacao.rodar(self.job)).model_dump(mode="json")

    def _redacao_so_numeros(self) -> dict | None:
        """153-3 (D-147): depois de trocar referencial, o texto do laudo NÃO é reescrito. Reaproveita a última redação e
        troca só os números da conta (valor, faixa, unitário — também por extenso). Tabela e planilha saem da montagem."""
        from .calculo import por_extenso
        ant = redacao.carregar(self.job)
        if not ant:
            return None
        # o "antes" é a conta que ESTE texto usou (a última conta antes da redação reaproveitada), não a conta anterior
        rid = _ultimo(self.job, "redacao")[0]
        with db._conn() as c:
            n_ = c.execute("SELECT dados_json FROM av_events WHERE job=? AND etapa='calculo' AND nivel='resultado' "
                           "ORDER BY id DESC LIMIT 1", (self.job,)).fetchone()
            v_ = c.execute("SELECT dados_json FROM av_events WHERE job=? AND etapa='calculo' AND nivel='resultado' "
                           "AND id < ? ORDER BY id DESC LIMIT 1", (self.job, rid or 0)).fetchone()
        if not n_ or not v_:
            return None
        novo, velho = json.loads(n_[0] or "{}"), json.loads(v_[0] or "{}")
        s = json.dumps(ant.model_dump(mode="json"), ensure_ascii=False)
        trocas = []
        for k in ("valor_adotado", "valor_min", "valor_max", "unitario_adotado", "area"):   # 159-1: a área também
            a, b = velho.get(k), novo.get(k)
            if not a or not b or Decimal(str(a)) == Decimal(str(b)):
                continue
            fa, fb = _brl(a)[3:], _brl(b)[3:]
            if fa in s:
                s = s.replace(fa, fb)
                trocas.append(f"{fa} → {fb}")
            try:
                ea, eb = por_extenso(Decimal(str(a))), por_extenso(Decimal(str(b)))
                if ea and ea in s:
                    s = s.replace(ea, eb)
            except Exception:
                pass
        # a memória de cálculo: "(R$ a + R$ b + …) ÷ n = R$ soma ÷ n = R$ média/m²" refeita com a amostra nova
        try:
            sel = db.resultado(self.job, "selecao") or {}
            us = []
            for x in sorted((r for r in sel.get("refs") or [] if r.get("escolhido")), key=lambda r: r.get("n") or 0):
                if x.get("preco") and x.get("area_m2"):
                    us.append(Decimal(str(x["preco"])) / Decimal(str(x["area_m2"])))
            us = [u.quantize(Decimal("0.01")) for u in us]
            mem = re.compile(r"\((?:R\$\s?[\d.]+,\d{2}\s*\+\s*)*R\$\s?[\d.]+,\d{2}\)\s*÷\s*(\d+)\s*=\s*R\$\s?[\d.]+,\d{2}"
                             r"\s*÷\s*\d+\s*=\s*R\$\s?[\d.]+,\d{2}")
            m = mem.search(s)
            if us and m and novo.get("unitario_adotado"):
                n_velho, n = m.group(1), len(us)
                frase = (f"({' + '.join(_brl(u) for u in us)}) ÷ {n} = {_brl(sum(us))} ÷ {n} = "
                         f"{_brl(Decimal(str(novo['unitario_adotado'])))}")
                s = s[:m.start()] + frase + s[m.end():]
                if n_velho != str(n):
                    s = re.sub(rf"\b{n_velho} referenciais", f"{n} referenciais", s)
                trocas.append(f"memória de cálculo com {n} referenciais")
        except Exception as e:                        # a conferência por regra aponta o que não bater
            log.warning("so_numeros: memória de cálculo não refeita: %s", e)
        novo_t = json.loads(s)
        db.evento(self.job, "redacao", "resultado", "texto do laudo reaproveitado: só os números da conta foram trocados "
                  f"(sem IA){': ' + '; '.join(trocas) if trocas else ''}", dados=novo_t)
        return novo_t

    async def _montagem(self):
        arqs = _arquivos_finais(self.job)
        sel, textos = self._sel(), redacao.carregar(self.job)
        from .agentes import fachada
        await fachada.garantir(self.job)   # contorno do imóvel na foto da capa (1×/foto)
        from . import mapa_digital                          # 085-4: anexo do Mapa Digital Fácil em todo trabalho de Goiânia
        await asyncio.to_thread(mapa_digital.garantir, self.job)   # já existe/fora de Goiânia: nada; falha: só aviso
        # Trabalho pesado e síncrono (python-docx, openpyxl, LibreOffice até 2×120 s): fora do
        # event loop, que é o MESMO do painel do Brixly, dos websockets e dos webhooks.
        db.set_setting(f"quebra_valor_antes:{self.job}", "")    # 095-1: a quebra é medida de novo a cada montagem
        db.set_setting(f"sem_quebra:{self.job}", "[]")
        docx = await asyncio.to_thread(docx_builder.montar, self.job, textos, self.r, sel)
        escolhidos = refs_na_base(self.job, [x for x in sel.refs if x.escolhido])
        await asyncio.to_thread(
            planilha.gerar, arqs["xlsx"], _comum.trabalho(self.job), area_construida(self.job),
            escolhidos, self.r, origem_area=origem_area_construida(self.job))
        if arqs["pdf"].exists():
            arqs["pdf"].unlink()
        try:
            await asyncio.to_thread(pdf.converter, docx)
            # 095-1: página quase vazia antes do bloco do valor → a quebra sobe e o trecho desce junto (uma volta)
            curta, titulos = docx_builder.ajustes_de_quebra(arqs["pdf"]) if arqs["pdf"].exists() else ("", [])
            if curta or titulos:
                db.set_setting(f"quebra_valor_antes:{self.job}", curta)
                db.set_setting(f"sem_quebra:{self.job}", json.dumps(titulos, ensure_ascii=False))
                docx = await asyncio.to_thread(docx_builder.montar, self.job, textos, self.r, sel)
                arqs["pdf"].unlink(missing_ok=True)
                await asyncio.to_thread(pdf.converter, docx)
                db.evento(self.job, "montagem", "info", "página quase vazia: quebra ajustada e PDF refeito")
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
            _cancelar.discard(self.job)
            return fim["status"]
        if self.job in _cancelar:          # cancelado ainda na fila
            return self._cancelar()
        mudou_db = corrigir_data_base(self.job)   # 086-8: a DITCD que o avaliador informou vale (corrige e só avisa)
        mudou_b = padronizar_bairro(self.job)     # 088-3: o bairro do título/IPTU, não o da fatura da Saneago
        limpar_emissao_velha(self.job)            # 090-2: emissão nunca antes da última consulta
        if mudou_db or mudou_b:
            reabrir(self.job, "redacao", motivo="dados do trabalho padronizados pelos documentos")
        try:
            tri = await self.passo("triagem", self._triagem)
            if tri.get("bloqueado"):
                self.pendencia(f"triagem bloqueada: {tri.get('motivo', '')}")
                return self._entregar(BLOQUEADO)
            await self._ate_revisao()
            await self._conferencias(contestar=not db.setting(f"correcao_rapida:{self.job}"))   # 129
            if self.reforcar_agora:
                await self._reforcar_e_conferir()
            await self._conferir_pedidos()            # 117-2/3: pedido do avaliador é ordem
        except _Parar:
            pass
        except _SemFotos:
            db.evento(self.job, "redacao", "aviso", SEM_FOTOS)
            return self._entregar(BLOQUEADO)
        except _Aguardar:
            return AGUARDANDO
        except _Reenfileirar:
            return REENFILEIRAR
        except _CanceladoAvaliador:
            return self._cancelar()
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
            db.evento(self.job, self.etapa_atual, "erro", amigavel(e, self.etapa_atual).capitalize(),
                      dados={"detalhe": f"{type(e).__name__}: {e}"[:2000], "tecnico": True})
            self.pendencia(amigavel(e, self.etapa_atual).capitalize(), tecnico=True)
        return self._entregar(None)

    async def _ate_revisao(self) -> None:
        i = ETAPAS.index("extracao")
        while True:
            etapa = ETAPAS[i]
            if etapa == "revisao":
                rev = await self._revisao()
                if rev is None or rev.aprovado:
                    return
                if (self.voltas >= MAX_VOLTAS or not rev.problemas
                        or rodadas_revisao(self.job) >= MAX_REVISOES):
                    for p in rev.problemas:
                        camada = {"juridica": "jurídica", "matematica": "matemática",
                                  "redacao": "redação"}.get(p.camada, p.camada)
                        self.pendencia(f"revisor ({camada}/{rotulo_etapa(p.etapa_responsavel)}): "
                                       f"{p.descricao}")
                    return
                # ORDEM 025: reextrair não resolve dado n/i, data das fotos, CNPJ no anexo…: o que
                # cai na extração vira pendência para o avaliador, sem voltar nem gastar IA
                # 077-4: o que é do JdB corrigir no TEXTO (tabela da documentação, datas, concordância, frase
                # duplicada, anexo trocado) volta para a redação/montagem, mesmo que o revisor aponte a extração
                rev = rev.model_copy(update={"problemas": [
                    p.model_copy(update={"etapa_responsavel": "redacao"})
                    if p.etapa_responsavel == "extracao" and _eh_do_texto(p.descricao) else p
                    for p in rev.problemas]})
                fica = [p for p in rev.problemas if p.etapa_responsavel == "extracao"]
                volta = [p for p in rev.problemas if p.etapa_responsavel != "extracao"]
                for p in fica:
                    self.pendencia(f"revisor (dado do imóvel): {p.descricao}")
                if not volta:
                    return
                rev = rev.model_copy(update={"problemas": volta})
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
            elif etapa == "selecao":
                await self.passo("selecao", self._selecao)
                # ORDEM 021: sem base/área escolhidas o avaliador decide, mesmo com a seleção
                # manual já confirmada
                if not self._sel().confirmado or escolha_area(self.job) is None:
                    # o avaliador confirma/troca referenciais, unitário e faixa na tela
                    db.evento(self.job, "selecao", "info",
                              "aguardando o avaliador confirmar referenciais, unitário, faixa, "
                              "base do cálculo e área do imóvel")
                    db.set_etapa(self.job, "selecao", AGUARDANDO)
                    raise _Aguardar
            elif etapa == "redacao":
                if not any(a.get("tipo") == "foto" for a in db.arquivos(self.job)):
                    self.pendencia(SEM_FOTOS)
                    raise _SemFotos
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

        if db.setting(f"correcao_rapida:{self.job}"):
            # 129: depois de uma correção de texto/montagem/imagem, a revisão do sistema confere só por regra (coerência
            # + os pedidos no PDF); a revisão completa de IA só volta quando conta ou referenciais mudam
            db.evento(self.job, "revisao", "info", "correção: revisão do sistema por regra (só o que mudou)")
            return revisor.Revisao(aprovado=True)

        async def rodar():
            return (await revisor.rodar(self.job, p, self.r)).model_dump(mode="json")
        try:
            d = await self.passo("revisao", rodar)
        except _Parar:  # IA falhou: pendência já registrada
            return None
        return revisor.Revisao.model_validate(d)

    async def _conferir_pedidos(self) -> None:
        """117-3: relê o PDF com a lista dos pedidos do avaliador. O que não foi feito volta UMA vez para a etapa
        certa (com "AINDA NÃO FEITO" na instrução); o que ainda sobrar vira passo "Não consegui fazer: … — porque …"."""
        from . import ajustes
        if not ajustes.abertos(self.job):
            return
        pdf_ = _arquivos_finais(self.job)["pdf"]
        if not pdf_.exists():
            return
        try:
            refazer, nao = await ajustes.conferir_no_pdf(self.job, pdf_)
        except Exception as e:                    # noqa: BLE001 — sem conferência, nada é dado como feito
            log.exception("conferência dos pedidos %s", self.job)
            self.pendencia(f"{ajustes.NAO_CONSEGUI} a conferência dos seus pedidos no PDF ({type(e).__name__}); "
                           "confira você antes de aprovar", grave=True)
            return
        if refazer:
            for p in refazer:
                txt = f"AINDA NÃO FEITO (pedido {p['i']} do avaliador, obrigatório): {p['instrucao']}"
                db.evento(self.job, p["etapa"], "correcao", txt, dados={"pedido": p["i"], "refazer": True, "eco": True})
                if p["etapa"] != "redacao" and p["etapa"] in ("extracao", "selecao", "calculo"):
                    db.evento(self.job, "redacao", "correcao", txt, dados={"pedido": p["i"], "refazer": True, "eco": True})
            # 126-3d: a volta é curta — nunca relê os documentos nem refaz a pesquisa (só do cálculo/redação em diante)
            etapa = min((p["etapa"] if p["etapa"] in ETAPAS and ETAPAS.index(p["etapa"]) >= ETAPAS.index("calculo")
                         else "redacao" for p in refazer), key=ETAPAS.index)
            self.pend = [p for p in self.pend if not p.texto.startswith(("revisor", "conferência de coerência",
                                                                          "montagem:"))]
            db.evento(self.job, "orquestrador", "volta", "pedidos do avaliador ainda não feitos: refazendo",
                      dados={"etapa": etapa, "correcao": True, "auto": True})
            self.barreira = {etapa: _eventos(self.job, "volta")[-1]["id"]}
            self.ultimo_id = 0
            await self._ate_revisao()
            await self._conferencias(contestar=False)
            refazer2, nao2 = await ajustes.conferir_no_pdf(self.job, pdf_)
            nao += nao2 + refazer2
        for p in nao:
            self.pendencia(ajustes.linha_nao_consegui(p), grave=True)

    async def _reforcar_e_conferir(self) -> None:
        """113-3: o reforço pedido pela contestação simulada entra na MESMA passada: refaz o texto, monta, revisa e
        confere antes de entregar — o avaliador vê uma revisão só, já com o reforço e o que o revisor apontou."""
        self.reforcar_agora = False
        self.pend = [p for p in self.pend if not p.texto.startswith(
            ("revisor", "conferência de coerência", "montagem:"))]      # a contestação não roda de novo: as dela ficam
        db.evento(self.job, "orquestrador", "volta", "reforço do texto pedido pela contestação simulada",
                  dados={"etapa": "redacao", "correcao": True, "auto": True})
        self.barreira = {"redacao": _eventos(self.job, "volta")[-1]["id"]}
        self.ultimo_id = 0
        await self._ate_revisao()
        await self._conferencias(contestar=False)

    # ------------------------------------------------------------- ORDEM 039: antes de entregar
    async def _conferencias(self, contestar: bool = True) -> None:
        """Depois das 5 camadas: D-084 (coerência, por conta, sem IA: qualquer diferença bloqueia),
        D-083 (contestação simulada: gravidade alta vira pendência; não altera o laudo) e D-085
        (dossiê de pesquisa, guardado com as provas). Nenhuma delas derruba a entrega."""
        arqs = _arquivos_finais(self.job)
        if not arqs["pdf"].exists() or self.r is None:
            return
        destino = db.pasta(self.job) / "entrega"
        destino.mkdir(parents=True, exist_ok=True)
        from . import coerencia, dossie
        from .agentes import contestacao
        try:
            co = await asyncio.to_thread(coerencia.do_trabalho, self.job, arqs["pdf"],
                                         arqs["xlsx"] if arqs["xlsx"].exists() else None, self.r)
            # 087: o que a conferência acha é erro do JdB — troca no texto, refaz o PDF e confere de novo (uma volta só)
            pares = coerencia.substituicoes(co)
            if pares and arqs["docx"].exists():
                from . import pdf as _pdf
                n = await asyncio.to_thread(docx_builder.aplicar_substituicoes, arqs["docx"], pares)
                if n:
                    await asyncio.to_thread(_pdf.converter, arqs["docx"])
                    db.evento(self.job, "revisao", "info", f"{coerencia.PREFIXO}: corrigido sozinho no texto — "
                              + "; ".join(f"{de} → {para}" for de, para in pares)[:900])
                    co = await asyncio.to_thread(coerencia.do_trabalho, self.job, arqs["pdf"],
                                                 arqs["xlsx"] if arqs["xlsx"].exists() else None, self.r)
            self.extra["coerencia"] = {"ok": co.ok, "diferencas": [d.texto() for d in co.diferencas],
                                       # 120: para a lista numerada (lugares, quem decide e a sugestão de um toque)
                                       "itens": [{"texto": d.texto(), "dado": d.dado, "lugares": list(d.lugares or []),
                                                  "do_avaliador": bool(d.do_avaliador), "sugestao": d.sugestao or "",
                                                  "valor_sugerido": d.valor_sugerido or "",
                                                  "encontrado": d.encontrado, "esperado": d.esperado,
                                                  "pagina": d.pagina} for d in co.diferencas]}
            (destino / "coerencia.md").write_text(co.resumo() + NL, encoding="utf-8")
            db.evento(self.job, "revisao", "info", co.resumo()[:1500])
            if not co.ok:
                self.pendencia(co.resumo()[:1500], grave=True)
        except Exception as e:
            log.exception("coerência %s", self.job)
            self.pendencia(f"conferência de coerência (D-084) não rodou: {e}", grave=True)
        if not contestar:          # ORDEM 047: "Corrigir agora" não chama a IA (mantém a contestação anterior)
            try:
                await asyncio.to_thread(dossie.gerar, self.job)
            except Exception as e:
                self.pendencia(f"dossiê de pesquisa (D-085) não gerado: {e}", grave=False)
            return
        try:
            ia.definir_contexto(self.job, "contestacao")
            ct = await contestacao.rodar(arqs["pdf"], self.job)
            self.extra["contestacao"] = ct
            (destino / "contestacao.md").write_text(
                "# Contestação simulada (D-083)" + NL * 2 + "Não altera o laudo: o avaliador decide o que reforçar."
                + NL * 2 + contestacao.tabela_md(ct["pontos"]) + NL, encoding="utf-8")
            reforcar = False
            for p in ct["pontos"]:
                if p["gravidade"] != "alta":
                    continue
                if p.get("so_conversa"):      # 106-4: ponto sobre dispersão fica só na conversa, nunca no laudo
                    continue
                ponto_txt = f"{p['ponto']} {p['como_reforcar']}"
                if (db.cv_so_na_planilha(self.job) or "decisao:cv" in json.loads(db.setting(f"pendencias_aceitas:{self.job}") or "[]"))                         and re.search(r"(?i)dispers|coeficiente|\bcv\b|desvio", ponto_txt):
                    # 101-1 (a): a decisão escrita do avaliador (D-068: conta só na planilha) vale mais que o reforço
                    db.evento(self.job, "contestacao", "aviso", "ponto da contestação sobre a dispersão: vale a sua decisão "
                              "(conta só na planilha); o laudo não muda (aviso ao avaliador, não é reprovação)")
                    continue
                if _SO_TEXTO.search(f"{p['como_reforcar']}") and not _DECISAO.search(f"{p['como_reforcar']}"):
                    # 097-3: reforço só de texto (explicar, justificar, ajustar a frase): o JdB reescreve na próxima
                    # redação (nota do revisor) e o avaliador vê como aviso, não como passo
                    nota = f"{p['ponto']}. Como: {p['como_reforcar']}"
                    if db.setting(f"reforco_desfeito:{self.job}"):
                        continue                              # 101-1 (d): o avaliador desfez o reforço
                    atuais = json.loads(db.setting(f"reforcos:{self.job}") or "[]")
                    if nota not in atuais:                    # 101-1: reforço guardado à parte (não é correção do avaliador)
                        db.set_setting(f"reforcos:{self.job}", json.dumps((atuais + [nota])[-6:], ensure_ascii=False))
                        reforcar = True
                    db.evento(self.job, "contestacao", "aviso", f"o JdB reforça no texto na próxima montagem (aviso ao avaliador, "
                              f"não é reprovação): {p['ponto']}")
                    continue
                self.pendencia(f"contestação simulada (D-083), gravidade alta — {p['pagina']}: {p['ponto']}. "
                               f"Como reforçar: {p['como_reforcar']}", grave=True)
            if reforcar and not db.setting(f"reforco_contestacao:{self.job}"):
                # 097-3: o JdB reescreve sozinho uma vez (só as seções atingidas, 081-7); depois, só aviso
                db.set_setting(f"reforco_contestacao:{self.job}", "1")
                self.reforcar_agora = True           # 113-3: na mesma passada, antes de entregar (não remonta depois)
        except Exception as e:
            self.pendencia(f"contestação simulada (D-083) não rodou: {e}", grave=False)
        try:
            await asyncio.to_thread(dossie.gerar, self.job)
        except Exception as e:
            self.pendencia(f"dossiê de pesquisa (D-085) não gerado: {e}", grave=False)

    # ------------------------------------------------------------- entrega
    def _coletar(self) -> None:
        inicio = {e["etapa"]: e["id"] for e in _eventos(self.job, "inicio")}
        # 092-8: a lista é a da revisão ATUAL — a ressalva do revisor (gravada na etapa da seleção, que não roda de
        # novo) só vale da última revisão; aviso do orquestrador, só desta execução; o mesmo texto, uma vez
        ult_rev = inicio.get("revisao", 0)
        ult_volta = max((e["id"] for e in _eventos(self.job, "volta")), default=0)
        vistos: set[str] = set()
        for e in _eventos(self.job, "aviso"):
            if e["id"] < inicio.get(e["etapa"], 0):
                continue  # aviso de uma execução anterior da etapa (já refeita)
            msg = str(e["msg"] or "")
            if msg.startswith("revisor") and e["id"] < ult_rev:
                continue
            if e["etapa"] == "orquestrador" and e["id"] < ult_volta:
                continue
            if msg in vistos:
                continue
            vistos.add(msg)
            self.pendencia(f"{e['etapa']}: {msg}", grave=_grave(msg))
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

    def _cancelar(self) -> str:
        return marcar_cancelado(self.job, self.etapa_atual)

    def _entregar(self, status: str | None) -> str:
        if status is None:
            self._coletar()
            sem_laudo = not any(p.exists() for p in _arquivos_finais(self.job).values())
            if any(p.tecnico for p in self.pend) and sem_laudo:
                status = ERRO_TECNICO        # falha do sistema: botão "Tentar de novo"
            else:
                status = PARCIAL if any(p.grave for p in self.pend) else PRONTO
        destino = db.pasta(self.job) / "entrega"
        destino.mkdir(parents=True, exist_ok=True)
        _guardar_arquivos_velhos(self.job, destino)   # 125-3: o nome mudou (ex.: bairro) → os de antes saem da frente
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
            "status": status, "arquivos": copiados, **self.extra,
            "pendencias": pendencias_estruturadas(
                [{"texto": p.texto, "grave": p.grave} for p in self.pend])})
        db.set_etapa(self.job, "entrega", status)
        db.set_setting(f"correcao_rapida:{self.job}", "")      # 129: a correção rápida vale só para esta entrega
        db.set_setting(f"so_numeros:{self.job}", "")           # 153-3: idem para "só os números"
        try:                                 # 109-4: fotografia da revisão (o que mudou; desfazer)
            from . import revisoes
            revisoes.fotografar(self.job, _arquivos_finais(self.job))
        except Exception:
            log.exception("avaliação %s: não guardou a revisão", self.job)
        return status


async def executar(job_id: str) -> str:
    """Roda (ou retoma) o pipeline do job; devolve o status final. Ao finalizar agora (não
    numa retomada de job já entregue) avisa o avaliador; erro no aviso nunca falha o job."""
    ja_entregue = db.resultado(job_id, "entrega") is not None
    status = await _Pipeline(job_id).executar()
    if status in FINAIS and status != CANCELADO and not ja_entregue:
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
    if etapa in ("triagem", "extracao"):
        db.set_setting(f"fotos_novas:{job_id}", "0")     # 074-B: as fotos novas entram nesta rodada
    db.arquivar_entrega(job_id)
    db.set_etapa(job_id, etapa, "pendente")


# ------------------------------------------------------------------- fila
_fila: asyncio.Queue | None = None
_worker: asyncio.Task | None = None
_ativos: set[str] = set()   # na fila ou executando


def ocupado(job_id: str) -> bool:
    return job_id in _ativos


# 086-1: remontagem UMA vez, depois que o avaliador para de enviar (envio no meio de uma montagem → uma vez no fim)
ESPERA_REMONTAR = 120.0
_remontar: dict[str, asyncio.Task] = {}


def _ordem_etapa(e: str) -> int:
    return ETAPAS.index(e) if e in ETAPAS else len(ETAPAS)


def agendar_remontagem(job_id: str, motivo: str, etapa: str = "montagem", atraso: float | None = None,
                       esperar: bool = False) -> dict:
    """Guarda o pedido (a etapa mais cedo pedida vale) e remonta quando passar `atraso` sem pedido novo e o
    trabalho estiver parado. Persistente: sobrevive ao reinício (retomar_remontagens)."""
    import time
    atraso = ESPERA_REMONTAR if atraso is None else atraso
    try:
        ant = json.loads(db.setting(f"remontar:{job_id}") or "null") or {}
    except ValueError:
        ant = {}
    if ant.get("etapa") and _ordem_etapa(ant["etapa"]) < _ordem_etapa(etapa):
        etapa = ant["etapa"]
    motivos = [m for m in (ant.get("motivos") or []) if m != motivo][-5:] + [motivo]
    # 086-2: resposta de um passo com outros abertos espera o "Respondi tudo: atualizar o laudo"
    # 113-2: pedido já liberado pelo "Atualizar" continua liberado — resposta que chega enquanto ele espera a montagem
    # em curso entra junto nessa mesma atualização (antes voltava a "esperar" e a tela pedia para atualizar de novo)
    liberado = bool(ant.get("liberado"))
    pedido = {"quando": time.time() + max(0.0, atraso), "etapa": etapa, "motivos": motivos,
              "esperar": False if liberado else bool(esperar or ant.get("esperar")), "liberado": liberado}
    db.set_setting(f"remontar:{job_id}", json.dumps(pedido, ensure_ascii=False))
    _garantir_espera(job_id)
    return pedido


def atualizar_agora(job_id: str) -> dict | None:
    """ "Respondi tudo: atualizar o laudo" / "Terminei de enviar": aplica tudo o que ficou guardado, uma vez."""
    import time
    p = remontagem_pendente(job_id)
    if not p:
        return None
    p.update(quando=time.time(), esperar=False, liberado=True)
    db.set_setting(f"remontar:{job_id}", json.dumps(p, ensure_ascii=False))
    _garantir_espera(job_id)
    return p


def remontagem_pendente(job_id: str) -> dict | None:
    try:
        return json.loads(db.setting(f"remontar:{job_id}") or "null") or None
    except ValueError:
        return None


def _garantir_espera(job_id: str) -> None:
    t = _remontar.get(job_id)
    if t is not None and not t.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return                                  # sem servidor rodando (teste síncrono): fica gravado
    _remontar[job_id] = loop.create_task(_esperar_e_remontar(job_id))


async def _esperar_e_remontar(job_id: str) -> None:
    import time
    while True:
        p = remontagem_pendente(job_id)
        if not p:
            return
        if p.get("esperar"):
            return                               # só com o "Respondi tudo" (atualizar_agora)
        falta = float(p.get("quando") or 0) - time.time()
        if falta > 0:
            await asyncio.sleep(min(falta, 30))
            continue
        if ocupado(job_id):                      # montando: espera terminar e remonta uma vez no fim
            await asyncio.sleep(10)
            continue
        db.set_setting(f"remontar:{job_id}", "")
        motivo = "; ".join(p.get("motivos") or []) or "atualizar o laudo"
        try:
            reabrir(job_id, p.get("etapa") or "montagem", motivo=motivo[:300])
            enfileirar(job_id)
        except Exception:
            log.exception("remontagem agendada de %s", job_id)
        return


def retomar_remontagens() -> int:
    """Na subida do servidor: os pedidos de remontagem que ficaram esperando continuam."""
    with db._conn() as c:
        ids = [r[0][len("remontar:"):] for r in c.execute(
            "SELECT chave FROM av_settings WHERE chave LIKE 'remontar:%' AND valor NOT IN ('', 'null')")]
    for jid in ids:
        _garantir_espera(jid)
    return len(ids)


def enfileirar(job_id: str) -> None:
    if _fila is None:
        raise RuntimeError("fila não iniciada (chame iniciar_fila)")
    if job_id in _ativos:
        return
    _ativos.add(job_id)
    _fila.put_nowait(job_id)




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
        try:
            status = await executar(jid)
            reenfileirar = status == REENFILEIRAR
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
    _worker = asyncio.get_running_loop().create_task(_trabalhar())
    # 'nova' = criado mas ainda não iniciado (o avaliador pode estar subindo os documentos):
    # reiniciar o servidor não pode disparar a avaliação com metade dos arquivos.
    with db._conn() as c:
        rows = c.execute("SELECT id, status FROM av_jobs WHERE etapa NOT IN ('entrega', 'nova') "
                         "ORDER BY criado").fetchall()
    for r in rows:
        # ORDEM 034: trabalho ESPERANDO o avaliador (Confirmar valor, lista de candidatos) fica
        # parado: só volta à fila pela ação dele ("Confirmar e gerar", "Continuar"). Reiniciar o
        # servidor depois de um "Só salvar" fazia o 9118 seguir sozinho até a revisão.
        if r["status"] not in FINAIS and r["status"] != AGUARDANDO:
            enfileirar(r["id"])
    return _worker
