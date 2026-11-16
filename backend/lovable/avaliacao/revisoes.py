"""109-4: revisão do laudo dentro do app.

A cada entrega com laudo, guarda uma "fotografia" da revisão em <trabalho>/revisoes/<N>/:
os arquivos finais (Word, PDF, planilha), o resultado de cada etapa e a lista do que mudou
em relação à revisão anterior (pedidos do avaliador, itens do texto reescritos, valor).

"Desfazer esta revisão" volta o laudo da revisão anterior: arquivos, texto e números;
os pedidos que geraram a revisão desfeita deixam de valer (não voltam na próxima montagem).
Dados mexidos à mão (anúncio, campo, foto) não são desfeitos aqui.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from . import db

PASTA = "revisoes"


def _pasta(job_id: str) -> Path:
    return db.pasta(job_id) / PASTA


def _numero_atual(job_id: str) -> int:
    from .tela_trabalho import _revisao
    return _revisao(job_id)


def _resultados(job_id: str) -> dict[str, dict]:
    """O resultado em vigor de cada etapa (menos a entrega, que tem tratamento próprio)."""
    with db._conn() as c:
        etapas = [r[0] for r in c.execute("SELECT DISTINCT etapa FROM av_events WHERE job=? AND nivel='resultado' "
                                           "AND dados_json IS NOT NULL", (job_id,))]
    return {e: d for e in etapas if e != "entrega" and (d := db.resultado(job_id, e)) is not None}


def _ultimo_evento(job_id: str) -> int:
    with db._conn() as c:
        r = c.execute("SELECT MAX(id) FROM av_events WHERE job=?", (job_id,)).fetchone()
    return int(r[0] or 0)


def _ler(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def listar(job_id: str) -> list[dict]:
    """As revisões guardadas, da mais nova para a mais velha: {n, quando, mudou: [...] }."""
    base = _pasta(job_id)
    if not base.is_dir():
        return []
    out = []
    for d in base.iterdir():
        if d.is_dir() and d.name.isdigit():
            info = _ler(d / "revisao.json")
            out.append({"n": int(d.name), "quando": info.get("quando", ""), "mudou": info.get("mudou") or []})
    return sorted(out, key=lambda x: x["n"], reverse=True)


def _pedidos(job_id: str, desde: int, ate: int) -> list[str]:
    with db._conn() as c:
        rows = c.execute("SELECT msg, dados_json FROM av_events WHERE job=? AND nivel='correcao' AND id>? AND id<=? "
                         "ORDER BY id", (job_id, desde, ate)).fetchall()
    out = []
    for r in rows:
        msg = str(r["msg"] or "")
        if msg.startswith("Reforce no texto (contestação simulada)"):
            continue
        try:
            if r["dados_json"] and (json.loads(r["dados_json"]) or {}).get("eco"):
                continue                       # 117: a cópia da correção para a redação não é outro pedido
        except ValueError:
            pass
        try:
            orig = (json.loads(r["dados_json"]) or {}).get("texto_original") if r["dados_json"] else None
        except ValueError:
            orig = None
        out.append(str(orig or msg).strip()[:300])
    return out


_SOZINHO = {"refor": "a conferência final pediu para reforçar o texto",
            "revisor reprovou": "a revisão achou pontos para corrigir no texto",
            "não batem com o cálculo": "os números do texto não batiam com o cálculo",
            "seções sem texto": "faltava texto em alguma seção"}


def _motivo_simples(msg: str, correcao: bool) -> str:
    m = (msg or "").strip()
    for k, v in _SOZINHO.items():         # o que o sistema faz sozinho (alguns entram marcados como correção)
        if k in m.lower():
            return v
    if correcao or m.startswith("reaberto pelo avaliador"):
        return ""                         # pedido do avaliador: já entra como "Pedido"
    return m[:200]


def _pontos_reforco(job_id: str, desde: int, ate: int) -> list[str]:
    with db._conn() as c:
        rows = c.execute("SELECT msg FROM av_events WHERE job=? AND etapa='contestacao' AND nivel='aviso' AND id>? AND id<=? "
                         "ORDER BY id", (job_id, desde, ate)).fetchall()
    out = []
    for r in rows:
        t = str(r["msg"] or "").split("):", 1)[-1].strip()
        if t and t not in out:
            out.append(t[:160].rstrip("."))
    return out


def sozinho(job_id: str, desde: int, ate: int) -> list[str]:
    """111-3d: o que o sistema refez sem toque do avaliador entre dois momentos, em português simples."""
    with db._conn() as c:
        rows = c.execute("SELECT id, msg, dados_json FROM av_events WHERE job=? AND etapa='orquestrador' AND nivel='volta' "
                         "AND id>? AND id<=? ORDER BY id", (job_id, desde, ate)).fetchall()
    out: list[str] = []
    for r in rows:
        try:
            corr = bool((json.loads(r["dados_json"]) or {}).get("correcao")) if r["dados_json"] else False
        except ValueError:
            corr = False
        mot = _motivo_simples(r["msg"], corr)
        if not mot:
            continue
        if "reforçar" in mot:
            with db._conn() as c:             # os pontos são os da última conferência antes deste retorno
                rv = c.execute("SELECT MAX(id) FROM av_events WHERE job=? AND etapa='revisao' AND nivel='resultado' AND id<?",
                               (job_id, r["id"])).fetchone()
            pts = _pontos_reforco(job_id, int(rv[0] or desde), r["id"])
            mot += (": " + "; ".join(pts)) if pts else ""
        linha = f"Refeito sozinho: {mot}."
        if linha not in out:
            out.append(linha)
    return out


def motivo_agora(job_id: str) -> str:
    """Enquanto monta: por que está montando de novo (o último retorno), se foi o sistema sozinho."""
    with db._conn() as c:
        r = c.execute("SELECT id, msg, dados_json FROM av_events WHERE job=? AND etapa='orquestrador' AND nivel='volta' "
                      "ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
        e = c.execute("SELECT MAX(id) FROM av_events WHERE job=? AND etapa='entrega' AND nivel IN ('resultado','resultado_anterior')",
                      (job_id,)).fetchone()
    if not r or not e or not e[0] or r["id"] < e[0]:
        return ""                          # 1ª montagem: nada a explicar
    linhas = sozinho(job_id, r["id"] - 1, r["id"])
    return linhas[0].replace("Refeito sozinho:", "Estou refazendo sozinho:") if linhas else ""


# 115-d: onde cada dado do trabalho aparece (o dado trocado muda em todos esses lugares)
ONDE_APARECE = {"data-base": "capa, cabeçalho de todas as páginas, itens 1 e 4, resumo (item 12) e planilha",
                "data da vistoria": "capa, item da vistoria, resumo e planilha",
                "nome do cliente": "capa, itens 1 e 2, resumo e planilha",
                "bairro": "capa, identificação do imóvel, localização, resumo e planilha",
                "cidade": "capa, identificação do imóvel, localização, resumo e planilha",
                "finalidade": "capa, itens 1 e 2, resumo e planilha",
                "tipo do imóvel": "capa, identificação e descrição do imóvel, resumo e planilha"}


def dados_trocados(job_id: str, desde: int, ate: int) -> list[str]:
    with db._conn() as c:
        rows = c.execute("SELECT dados_json FROM av_events WHERE job=? AND etapa='orquestrador' AND nivel='dado' "
                         "AND id>? AND id<=? ORDER BY id", (job_id, desde, ate)).fetchall()
    out = []
    for r in rows:
        try:
            linhas = (json.loads(r["dados_json"]) or {}).get("linhas") or []
        except ValueError:
            linhas = []
        for ln in linhas:
            nome = ln.split(":", 1)[0]
            onde = ONDE_APARECE.get(nome, "")
            out.append(f"Dado trocado — {ln}" + (f" (muda em: {onde})." if onde else "."))
    return out


def _lista_pedidos(job_id: str) -> list[dict]:
    from . import ajustes
    return ajustes.lista(job_id)


def _valor(res: dict) -> float | None:
    calc = res.get("calculo") or {}
    v = calc.get("valor_adotado")
    return float(v) if isinstance(v, (int, float)) else None


def _brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


def fotografar(job_id: str, arquivos: dict[str, Path]) -> int | None:
    """Chamado ao fim da entrega. Guarda a revisão N (a que o avaliador vê agora). Nunca derruba a entrega."""
    if not any(p.exists() for p in arquivos.values()):
        return None
    n = _numero_atual(job_id)
    if n <= 0:
        return None
    destino = _pasta(job_id) / str(n)
    destino.mkdir(parents=True, exist_ok=True)
    for p in arquivos.values():
        if p.exists():
            shutil.copy2(p, destino / p.name)
    entrada = db.pasta(job_id) / "redacao_entrada.txt"
    if entrada.is_file():
        shutil.copy2(entrada, destino / entrada.name)
    res = _resultados(job_id)
    ate = _ultimo_evento(job_id)
    ant = _ler(_pasta(job_id) / str(n - 1) / "revisao.json") if n > 1 else {}
    mudou: list[str] = []
    if n > 1:
        from . import ajustes                    # 117-2: cada pedido com ✓ feito / ✗ não consegui
        if ajustes.lista(job_id):
            mudou += ajustes.resumo(job_id, int(ant.get("ultimo_pedido") or 0))
        else:
            for p in _pedidos(job_id, int(ant.get("ultimo_evento") or 0), ate):
                mudou.append(f"Pedido: {p}")
        mudou += sozinho(job_id, int(ant.get("ultimo_evento") or 0), ate)      # 111-3d
        mudou += dados_trocados(job_id, int(ant.get("ultimo_evento") or 0), ate)   # 115-d
        try:
            from .agentes.redacao import mudancas
            itens = mudancas(job_id)
        except Exception:      # noqa: BLE001
            itens = []
        if itens:
            mudou.append("Texto reescrito: " + ", ".join(f"item {k}" for k in itens) + ".")
        va, vb = _valor(ant.get("resultados") or {}), _valor(res)
        if va is not None and vb is not None and round(va, 2) != round(vb, 2):
            mudou.append(f"Valor de mercado: de {_brl(va)} para {_brl(vb)}.")
        if not mudou:
            mudou.append("Nada mudou no texto nem no valor.")
    (destino / "revisao.json").write_text(json.dumps({
        "n": n, "quando": datetime.now().strftime("%d/%m/%Y %H:%M"), "ultimo_evento": ate,
        "arquivos": [p.name for p in arquivos.values() if p.exists()], "mudou": mudou, "resultados": res,
        "ultimo_pedido": max((x["i"] for x in _lista_pedidos(job_id)
                              if x.get("status") not in ("pendente", "refazer")), default=0),
    }, ensure_ascii=False, default=str), encoding="utf-8")
    return n


class NaoDa(Exception):
    """Não dá para desfazer (mensagem em português simples)."""


def desfazer(job_id: str, arquivos: dict[str, Path]) -> int:
    """Volta o laudo da revisão anterior. Devolve o número da revisão que ficou valendo."""
    n = _numero_atual(job_id)
    atual, anterior = _pasta(job_id) / str(n), _pasta(job_id) / str(n - 1)
    if n < 2 or not (anterior / "revisao.json").is_file():
        raise NaoDa("Não há revisão anterior guardada para voltar.")
    info_atual, info_ant = _ler(atual / "revisao.json"), _ler(anterior / "revisao.json")
    # 1) os arquivos do laudo voltam (na pasta do trabalho e na da entrega)
    entrega = db.pasta(job_id) / "entrega"
    entrega.mkdir(parents=True, exist_ok=True)
    for p in arquivos.values():
        src = anterior / p.name
        if src.is_file():
            shutil.copy2(src, p)
            shutil.copy2(src, entrega / p.name)
    if (anterior / "redacao_entrada.txt").is_file():
        shutil.copy2(anterior / "redacao_entrada.txt", db.pasta(job_id) / "redacao_entrada.txt")
    with db._conn() as c:
        # 2) os pedidos que geraram a revisão desfeita deixam de valer
        c.execute("UPDATE av_events SET nivel='correcao_desfeita' WHERE job=? AND nivel='correcao' AND id>? AND id<=?",
                  (job_id, int(info_ant.get("ultimo_evento") or 0), int(info_atual.get("ultimo_evento") or 1 << 62)))
        # 3) a entrega desfeita sai de vigor e a anterior volta (o nº da revisão volta junto)
        r = c.execute("SELECT id FROM av_events WHERE job=? AND etapa='entrega' AND nivel='resultado' "
                      "ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
        if r:
            c.execute("UPDATE av_events SET nivel='resultado_desfeito' WHERE id=?", (r[0],))
        r = c.execute("SELECT id FROM av_events WHERE job=? AND etapa='entrega' AND nivel='resultado_anterior' "
                      "ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
        if r:
            c.execute("UPDATE av_events SET nivel='resultado' WHERE id=?", (r[0],))
    # 4) o texto e os números de cada etapa voltam como estavam
    agora = _resultados(job_id)
    # 130: na ORDEM das etapas do pipeline — cada etapa precisa de resultado mais novo que a anterior; fora de ordem
    # (ex.: triagem por último) o montador acha a cadeia quebrada e relê os documentos à toa
    from .orquestrador import ETAPAS
    ordem = {e: i for i, e in enumerate(ETAPAS)}
    for etapa, dados in sorted((info_ant.get("resultados") or {}).items(), key=lambda kv: ordem.get(kv[0], -1)):
        if agora.get(etapa) != dados:
            db.evento(job_id, etapa, "resultado", f"revisão {n} desfeita: volta o da revisão {n - 1}", dados=dados)
    try:
        from .agentes.redacao import _gravar_mudancas
        _gravar_mudancas(job_id, [])
    except Exception:          # noqa: BLE001
        pass
    if atual.is_dir():
        alvo = _pasta(job_id) / f"{n}-desfeita"
        if alvo.exists():
            shutil.rmtree(alvo, ignore_errors=True)
        atual.rename(alvo)
    db.evento(job_id, "orquestrador", "info", f"revisão {n} desfeita pelo avaliador: vale de novo a revisão {n - 1}")
    db.set_etapa(job_id, "entrega", (db.resultado(job_id, "entrega") or {}).get("status") or "PRONTO")
    return n - 1
