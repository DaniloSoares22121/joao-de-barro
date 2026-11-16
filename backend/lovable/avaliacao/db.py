"""Persistência do João de Barro (SQLite cru, tabelas `av_*`, no mesmo app.db do Brixly)."""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from lovable import config

from .modelos import Campo, Referencial, Trabalho

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS av_jobs (
    id TEXT PRIMARY KEY, numero INTEGER NOT NULL, dados_json TEXT NOT NULL,
    etapa TEXT NOT NULL DEFAULT 'nova', status TEXT NOT NULL DEFAULT 'pendente',
    criado TEXT NOT NULL, atualizado TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS av_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL, nome TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT '', caminho TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_av_files_job ON av_files(job);
CREATE TABLE IF NOT EXISTS av_fields (
    job TEXT NOT NULL, nome TEXT NOT NULL, json TEXT NOT NULL, PRIMARY KEY (job, nome));
CREATE TABLE IF NOT EXISTS av_candidates (
    job TEXT NOT NULL, n INTEGER NOT NULL, json TEXT NOT NULL, PRIMARY KEY (job, n));
CREATE TABLE IF NOT EXISTS av_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL, etapa TEXT NOT NULL,
    nivel TEXT NOT NULL, msg TEXT NOT NULL DEFAULT '', dados_json TEXT, ts TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_av_events_job ON av_events(job, etapa, nivel);
CREATE TABLE IF NOT EXISTS av_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT, data TEXT NOT NULL, laudo TEXT NOT NULL DEFAULT '',
    decisao TEXT NOT NULL, regra TEXT NOT NULL DEFAULT '', tipo TEXT NOT NULL DEFAULT '',
    escopo TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'ativa');
CREATE TABLE IF NOT EXISTS av_norms (
    codigo TEXT PRIMARY KEY, titulo TEXT NOT NULL, itens_json TEXT NOT NULL DEFAULT '[]',
    vigente INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS av_settings (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS av_ia_chamadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL, etapa TEXT NOT NULL DEFAULT '',
    modelo TEXT NOT NULL DEFAULT '', tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0, custo_usd REAL, ms INTEGER NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 1, ts TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_av_ia_chamadas_job ON av_ia_chamadas(job);
CREATE TABLE IF NOT EXISTS av_anuncios (
    id INTEGER PRIMARY KEY AUTOINCREMENT, url_limpa TEXT NOT NULL UNIQUE,
    portal TEXT NOT NULL DEFAULT '', bairro_norm TEXT NOT NULL DEFAULT '',
    cidade TEXT NOT NULL DEFAULT '', tipologia TEXT NOT NULL DEFAULT '', quartos INTEGER,
    suites INTEGER, area_m2 REAL, lote_m2 REAL, preco REAL, padrao TEXT NOT NULL DEFAULT '',
    idade_aparente TEXT NOT NULL DEFAULT '', descricao TEXT NOT NULL DEFAULT '',
    foto_path TEXT NOT NULL DEFAULT '', print_path TEXT NOT NULL DEFAULT '',
    publicado_em TEXT, visto_em TEXT NOT NULL, impressao_digital TEXT NOT NULL DEFAULT '',
    bairro TEXT NOT NULL DEFAULT '', tipologia_txt TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_av_anuncios_busca ON av_anuncios(bairro_norm, tipologia, visto_em);
CREATE INDEX IF NOT EXISTS idx_av_anuncios_dig ON av_anuncios(impressao_digital);
"""


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    """Conexão nova por chamada (mesmo motivo de auth._conn: evita snapshot WAL velho)."""
    c = sqlite3.connect(config.DATA_DIR / "app.db", timeout=10)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    return c


def init() -> None:
    try:
        _conn().execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    with _conn() as c:
        c.executescript(_SCHEMA)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(av_decisions)")}
        if "codigo" not in cols:
            c.execute("ALTER TABLE av_decisions ADD COLUMN codigo TEXT")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_av_decisions_codigo ON av_decisions(codigo)")
        if "papel" not in {r["name"] for r in c.execute("PRAGMA table_info(av_files)")}:
            c.execute("ALTER TABLE av_files ADD COLUMN papel TEXT NOT NULL DEFAULT ''")
        if "upload_id" not in {r["name"] for r in c.execute("PRAGMA table_info(av_files)")}:
            c.execute("ALTER TABLE av_files ADD COLUMN upload_id TEXT NOT NULL DEFAULT ''")
        cols_an = {r["name"] for r in c.execute("PRAGMA table_info(av_anuncios)")}
        for col in ("bairro", "tipologia_txt"):
            if col not in cols_an:
                c.execute(f"ALTER TABLE av_anuncios ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        if "substituido_por" not in cols_an:   # id do anúncio de outro portal que o substitui
            c.execute("ALTER TABLE av_anuncios ADD COLUMN substituido_por INTEGER")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_av_files_upload ON av_files(job, upload_id) "
                  "WHERE upload_id != ''")
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_av_jobs_numero'"
                     ).fetchone() is None:
            dup = c.execute("SELECT numero FROM av_jobs GROUP BY numero HAVING COUNT(*) > 1").fetchall()
            if dup:
                log.warning("av_jobs: números duplicados %s; índice único de número NÃO criado",
                            [r["numero"] for r in dup])
            else:
                c.execute("CREATE UNIQUE INDEX idx_av_jobs_numero ON av_jobs(numero)")


def pasta(job_id: str) -> Path:
    p = config.DATA_DIR / "avaliacao" / job_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def criar_job(t: Trabalho) -> str:
    jid = t.id or uuid.uuid4().hex[:12]
    t = t.model_copy(update={"id": jid})
    agora = _agora()
    with _conn() as c:
        c.execute(
            "INSERT INTO av_jobs (id, numero, dados_json, etapa, status, criado, atualizado) "
            "VALUES (?,?,?,?,?,?,?)",
            (jid, t.numero, t.model_dump_json(), "nova", "pendente", agora, agora))
    if modo_teste():                          # 109-3: trabalho de teste fica marcado e não conta na numeração real
        set_setting(TESTE_JOB + jid, str(t.numero))
    pasta(jid)
    return jid


def job(job_id: str) -> dict:
    with _conn() as c:
        r = c.execute("SELECT * FROM av_jobs WHERE id=?", (job_id,)).fetchone()
    if r is None:
        raise KeyError(job_id)
    d = dict(r)
    d["dados"] = json.loads(d.pop("dados_json"))
    return d


def set_etapa(job_id: str, etapa: str, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE av_jobs SET etapa=?, status=?, atualizado=? WHERE id=?",
                  (etapa, status, _agora(), job_id))


def evento(job_id: str, etapa: str, nivel: str, msg: str, dados=None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO av_events (job, etapa, nivel, msg, dados_json, ts) VALUES (?,?,?,?,?,?)",
            (job_id, etapa, nivel, msg,
             None if dados is None else json.dumps(dados, ensure_ascii=False, default=str),
             _agora()))


def resultado(job_id: str, etapa: str) -> dict | None:
    """`dados` do último evento nivel='resultado' da etapa (saída persistida de cada etapa)."""
    with _conn() as c:
        r = c.execute(
            "SELECT dados_json FROM av_events WHERE job=? AND etapa=? AND nivel='resultado' "
            "AND dados_json IS NOT NULL ORDER BY id DESC LIMIT 1", (job_id, etapa)).fetchone()
    return json.loads(r["dados_json"]) if r else None


def salvar_campos(job_id: str, campos: list[Campo]) -> None:
    """Upsert por nome (preserva a ordem de inserção)."""
    with _conn() as c:
        c.executemany(
            "INSERT INTO av_fields (job, nome, json) VALUES (?,?,?) "
            "ON CONFLICT(job, nome) DO UPDATE SET json=excluded.json",
            [(job_id, f.nome, f.model_dump_json()) for f in campos])


def campos(job_id: str) -> list[Campo]:
    with _conn() as c:
        rows = c.execute("SELECT json FROM av_fields WHERE job=? ORDER BY rowid", (job_id,)).fetchall()
    return [Campo.model_validate_json(r["json"]) for r in rows]


def salvar_candidatos(job_id: str, refs: list[Referencial], substituir: bool = False) -> None:
    """Upsert por n. `substituir` (pesquisa nova) apaga os que não vieram: sem isso, uma
    2ª pesquisa com menos anúncios deixava os da 1ª na seleção e no laudo."""
    with _conn() as c:
        if substituir:
            c.execute("DELETE FROM av_candidates WHERE job=?", (job_id,))
        c.executemany(
            "INSERT INTO av_candidates (job, n, json) VALUES (?,?,?) "
            "ON CONFLICT(job, n) DO UPDATE SET json=excluded.json",
            [(job_id, r.n, r.model_dump_json()) for r in refs])


def candidatos(job_id: str) -> list[Referencial]:
    with _conn() as c:
        rows = c.execute("SELECT json FROM av_candidates WHERE job=? ORDER BY n", (job_id,)).fetchall()
    return [Referencial.model_validate_json(r["json"]) for r in rows]


def adicionar_arquivo(job_id: str, nome: str, tipo: str, caminho: str, papel: str = "",
                      upload_id: str = "") -> None:
    """Registra um arquivo do job; `caminho` relativo à pasta do job. papel='fachada' marca a
    foto da capa (única por job: a marcação nova desmarca as anteriores). `upload_id` (do
    cliente) é único por job: repetir levanta sqlite3.IntegrityError sem gravar nada."""
    with _conn() as c:
        c.execute("INSERT INTO av_files (job, nome, tipo, caminho, papel, upload_id) "
                  "VALUES (?,?,?,?,?,?)", (job_id, nome, tipo, caminho, papel, upload_id))
        if papel == "fachada":
            c.execute("UPDATE av_files SET papel='' WHERE job=? AND papel='fachada' "
                      "AND id != last_insert_rowid()", (job_id,))


def arquivo_por_upload(job_id: str, upload_id: str) -> dict | None:
    if not upload_id:
        return None
    with _conn() as c:
        r = c.execute("SELECT * FROM av_files WHERE job=? AND upload_id=?",
                      (job_id, upload_id)).fetchone()
    return dict(r) if r else None


def atualizar_dados(job_id: str, t: Trabalho) -> None:
    with _conn() as c:
        c.execute("UPDATE av_jobs SET dados_json=?, atualizado=? WHERE id=?",
                  (t.model_dump_json(), _agora(), job_id))


def fachada(job_id: str) -> str | None:
    """Caminho da foto marcada como fachada (capa) pelo avaliador, se houver."""
    with _conn() as c:
        r = c.execute("SELECT caminho FROM av_files WHERE job=? AND papel='fachada' "
                      "ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
    return r["caminho"] if r else None


# 109-3: numeração dos testes do Capitão (1, 2, 3…) separada da numeração real do Alan.
# "numeracao_modo" = "teste" liga; o trabalho criado nesse modo ganha "job_teste:{id}". A numeração real ignora
# os trabalhos de teste (os marcados e os da lista de testes antigos); "numeracao_real_proximo", se o Alan informar,
# é o piso do próximo número real.
TESTE_JOB = "job_teste:"
TESTES_ANTIGOS = {9119, 9120, 9121, 9122, 9123, 9124, 9125, 9126, 9127}


def modo_teste() -> bool:
    return (setting("numeracao_modo") or "") == "teste"


def eh_teste(job_id: str) -> bool:
    return bool(setting(TESTE_JOB + job_id))


def proximo_numero() -> int:
    with _conn() as c:
        linhas = c.execute("SELECT id, numero FROM av_jobs").fetchall()
        marcados = {r[0][len(TESTE_JOB):] for r in c.execute("SELECT chave FROM av_settings WHERE chave LIKE ?",
                                                               (TESTE_JOB + "%",))}
    usados = {int(r["numero"]) for r in linhas}
    if modo_teste():
        testes = [int(r["numero"]) for r in linhas if r["id"] in marcados]
        n = max(testes, default=0) + 1
    else:
        reais = [int(r["numero"]) for r in linhas if r["id"] not in marcados and int(r["numero"]) not in TESTES_ANTIGOS]
        n = max(max(reais, default=0) + 1, int(setting("numeracao_real_proximo") or 0))
    while n in usados:
        n += 1
    return n


def numero_usado(numero: int) -> bool:
    with _conn() as c:
        return c.execute("SELECT 1 FROM av_jobs WHERE numero=? LIMIT 1", (numero,)).fetchone() is not None


def instrucoes_avaliador(job_id: str) -> list[str]:
    """074-F3: o que o avaliador escreveu em "Confirmo mesmo assim, porque…" (vale para o laudo)."""
    with _conn() as c:
        rows = c.execute("SELECT dados_json FROM av_events WHERE job=? AND etapa='selecao' AND msg LIKE "
                         "'avaliador confirmou mesmo assim:%' ORDER BY id", (job_id,)).fetchall()
    out = []
    for r in rows:
        try:
            v = (json.loads(r["dados_json"] or "{}") or {}).get("confirmacao") or ""
        except ValueError:
            v = ""
        if v.strip() and v.strip() not in out:
            out.append(v.strip())
    return out


def cv_so_na_planilha_txt(txt: str) -> bool:
    """A mesma regra de cv_so_na_planilha, aplicada a um texto (ex.: as instruções que entram nas fontes)."""
    return bool(re.search(r"planilha", txt or "", re.I) and re.search(r"coeficiente|\bcv\b|dispers", txt or "", re.I)
                and re.search(r"s[oó] na planilha|apenas na planilha|somente na planilha", txt or "", re.I))


def cv_so_na_planilha(job_id: str) -> bool:
    """O avaliador pediu a conta do coeficiente só na planilha (decisão do Alan no 122, D-068)."""
    return any(re.search(r"planilha", x, re.I) and re.search(r"coeficiente|\bcv\b|dispers", x, re.I)
               for x in instrucoes_avaliador(job_id))


def arquivos(job_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM av_files WHERE job=? ORDER BY id", (job_id,)).fetchall()
    return [dict(r) for r in rows]


def correcoes(job_id: str, etapa: str) -> list[str]:
    """Textos das correções do dono para a etapa (eventos nivel='correcao'), em ordem."""
    with _conn() as c:
        rows = c.execute("SELECT msg FROM av_events WHERE job=? AND etapa=? AND nivel='correcao' "
                         "ORDER BY id", (job_id, etapa)).fetchall()
    # 101-1: o reforço automático da contestação não é correção do avaliador (os gravados assim deixam de valer)
    return [r["msg"] for r in rows if not str(r["msg"] or "").startswith("Reforce no texto (contestação simulada)")]


def texto_correcoes(job_id: str, etapa: str) -> str:
    """Bloco para anexar ao prompt do agente ('' se não houver correções)."""
    cs = correcoes(job_id, etapa)
    out = ""
    if cs:
        out += ("\n\nCORREÇÕES DO AVALIADOR (obrigatórias; a última prevalece):\n"
                + "\n".join(f"- {x}" for x in cs))
    rs = notas_revisor(job_id, etapa)
    if rs:
        out += ("\n\nPROBLEMAS QUE O REVISOR APONTOU NA VERSÃO ANTERIOR (corrija todos; as "
                "correções do avaliador prevalecem):\n" + "\n".join(f"- {x}" for x in rs))
    return out


def notas_revisor(job_id: str, etapa: str, limite: int = 12) -> list[str]:
    """Problemas que o revisor apontou para a etapa (nivel='revisor') depois da última
    reabertura pelo avaliador, sem repetição, os mais recentes por último."""
    with _conn() as c:
        rows = c.execute(
            "SELECT msg FROM av_events WHERE job=? AND etapa=? AND nivel='revisor' AND id > "
            "COALESCE((SELECT MAX(id) FROM av_events WHERE job=? AND etapa='orquestrador' "
            "AND nivel='volta' AND json_extract(dados_json, '$.correcao')), 0) ORDER BY id",
            (job_id, etapa, job_id)).fetchall()
    vistos: list[str] = []
    for r in rows:
        if r["msg"] not in vistos:
            vistos.append(r["msg"])
    return vistos[-limite:]


def setting(chave: str, padrao: str | None = None) -> str | None:
    with _conn() as c:
        r = c.execute("SELECT valor FROM av_settings WHERE chave=?", (chave,)).fetchone()
    return r["valor"] if r else padrao


def set_setting(chave: str, valor: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO av_settings (chave, valor) VALUES (?,?) "
                  "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (chave, valor))


def listar_jobs() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM av_jobs ORDER BY criado DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["dados"] = json.loads(d.pop("dados_json"))
        out.append(d)
    return out


def eventos_desde(job_id: str, ultimo: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT id, etapa, nivel, msg, dados_json, ts FROM av_events "
                         "WHERE job=? AND id>? ORDER BY id", (job_id, ultimo)).fetchall()
    return [{"id": r["id"], "etapa": r["etapa"], "nivel": r["nivel"], "msg": r["msg"],
             "dados": json.loads(r["dados_json"]) if r["dados_json"] else None, "ts": r["ts"]}
            for r in rows]


def arquivar_entrega(job_id: str) -> None:
    """Tira o resultado da entrega de vigor (o job volta a ser executável)."""
    with _conn() as c:
        c.execute("UPDATE av_events SET nivel='resultado_anterior' WHERE job=? AND etapa='entrega' "
                  "AND nivel='resultado'", (job_id,))


_DEC = ("codigo", "data", "laudo", "decisao", "regra", "tipo", "escopo", "status")


def decisoes() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM av_decisions ORDER BY id")]


def proximo_codigo_decisao() -> str:
    nums = [int(d["codigo"][2:]) for d in decisoes()
            if (d["codigo"] or "").startswith("D-") and d["codigo"][2:].isdigit()]
    return f"D-{max(nums, default=0) + 1:03d}"


def upsert_decisoes(regs: list[dict], sobrescrever: bool = True) -> None:
    """Upsert por código; sobrescrever=False só insere códigos ausentes."""
    conflito = ("DO UPDATE SET " + ", ".join(f"{k}=excluded.{k}" for k in _DEC[1:])
                if sobrescrever else "DO NOTHING")
    with _conn() as c:
        c.executemany(
            f"INSERT INTO av_decisions ({', '.join(_DEC)}) VALUES ({','.join('?' * len(_DEC))}) "
            f"ON CONFLICT(codigo) {conflito}",
            [tuple(str(r.get(k) or "") for k in _DEC) for r in regs])


def upsert_normas(regs: list[dict], sobrescrever: bool = True) -> None:
    conflito = ("DO UPDATE SET titulo=excluded.titulo, itens_json=excluded.itens_json, "
                "vigente=excluded.vigente" if sobrescrever else "DO NOTHING")
    with _conn() as c:
        c.executemany(
            f"INSERT INTO av_norms (codigo, titulo, itens_json, vigente) VALUES (?,?,?,?) "
            f"ON CONFLICT(codigo) {conflito}",
            [(r["codigo"], r.get("titulo", ""), json.dumps(r.get("itens") or {}, ensure_ascii=False),
              1 if r.get("vigente", True) else 0) for r in regs])


# ------------------------------------------------------------------ IA (custo e tempo)
def registrar_ia(job_id: str, etapa: str, modelo: str, tokens_in: int, tokens_out: int,
                 custo_usd: float | None, ms: int, ok: bool = True) -> None:
    with _conn() as c:
        c.execute("INSERT INTO av_ia_chamadas (job, etapa, modelo, tokens_in, tokens_out, "
                  "custo_usd, ms, ok, ts) VALUES (?,?,?,?,?,?,?,?,?)",
                  (job_id, etapa, modelo, int(tokens_in or 0), int(tokens_out or 0), custo_usd,
                   int(ms or 0), 1 if ok else 0, _agora()))


def ia_chamadas_ciclo(job_id: str) -> int:
    """Chamadas de IA desde a última reabertura/correção do job (cota do ciclo atual)."""
    with _conn() as c:
        r = c.execute(
            "SELECT COUNT(*) AS n FROM av_ia_chamadas WHERE job=? AND ts > COALESCE(("
            "SELECT MAX(ts) FROM av_events WHERE job=? AND etapa='orquestrador' "
            "AND nivel='volta' AND json_extract(dados_json, '$.correcao')), '')",
            (job_id, job_id)).fetchone()
    return int(r["n"])


def ia_resumo(job_id: str) -> dict:
    """{chamadas, custo_usd, tempo_s, tokens_in, tokens_out} das chamadas de IA do job."""
    with _conn() as c:
        r = c.execute("SELECT COUNT(*) AS n, COALESCE(SUM(custo_usd), 0) AS custo, "
                      "COALESCE(SUM(ms), 0) AS ms, COALESCE(SUM(tokens_in), 0) AS tin, "
                      "COALESCE(SUM(tokens_out), 0) AS tout FROM av_ia_chamadas WHERE job=?",
                      (job_id,)).fetchone()
    return {"chamadas": int(r["n"]), "custo_usd": round(float(r["custo"]), 4),
            "tempo_s": round(int(r["ms"]) / 1000, 1), "tokens_in": int(r["tin"]),
            "tokens_out": int(r["tout"])}


# ------------------------------------------------------------------ banco de comparáveis
_ANUNCIO_COLS = ("url_limpa", "portal", "bairro_norm", "cidade", "tipologia", "quartos", "suites",
                 "area_m2", "lote_m2", "preco", "padrao", "idade_aparente", "descricao",
                 "foto_path", "print_path", "publicado_em", "visto_em", "impressao_digital",
                 "bairro", "tipologia_txt")  # bairro/tipologia_txt: texto original do anúncio


def salvar_anuncio(a: dict) -> None:
    """Upsert por url_limpa. Mesma impressão digital em OUTRO portal (o mesmo imóvel
    anunciado de novo): as linhas mais antigas ficam marcadas `substituido_por` (não são
    apagadas). No mesmo portal são unidades distintas (ex.: 2 aptos iguais) e ficam as duas."""
    reg = {k: a.get(k) for k in _ANUNCIO_COLS}
    reg["visto_em"] = reg.get("visto_em") or _agora()
    for k in ("portal", "bairro_norm", "cidade", "tipologia", "padrao", "idade_aparente",
              "descricao", "foto_path", "print_path", "impressao_digital", "bairro",
              "tipologia_txt"):
        reg[k] = reg.get(k) or ""
    with _conn() as c:
        c.execute(
            f"INSERT INTO av_anuncios ({', '.join(_ANUNCIO_COLS)}) "
            f"VALUES ({','.join('?' * len(_ANUNCIO_COLS))}) ON CONFLICT(url_limpa) DO UPDATE SET "
            + ", ".join(f"{k}=excluded.{k}" for k in _ANUNCIO_COLS[1:]) + ", substituido_por=NULL",
            tuple(reg[k] for k in _ANUNCIO_COLS))
        if reg["impressao_digital"]:
            novo = c.execute("SELECT id FROM av_anuncios WHERE url_limpa=?",
                             (reg["url_limpa"],)).fetchone()["id"]
            c.execute("UPDATE av_anuncios SET substituido_por=? WHERE impressao_digital=? "
                      "AND id!=? AND portal!=? AND visto_em<=? AND substituido_por IS NULL",
                      (novo, reg["impressao_digital"], novo, reg["portal"], reg["visto_em"]))


def anuncios_recentes(bairro_norm: str, tipologia: str, desde: str,
                      area_min: float | None = None, area_max: float | None = None,
                      cidade: str | list[str] | None = None) -> list[dict]:
    """Anúncios do bairro/tipologia (e cidade, se dada; aceita lista de grafias) vistos desde
    `desde` (ISO), na faixa de área se dada, que não foram substituídos por outro portal."""
    sql = ("SELECT * FROM av_anuncios WHERE bairro_norm=? AND tipologia=? AND visto_em>=? "
           "AND substituido_por IS NULL")
    args: list = [bairro_norm, tipologia, desde]
    if cidade:
        cs = [cidade] if isinstance(cidade, str) else list(cidade)
        sql += f" AND cidade IN ({','.join('?' * len(cs))})"
        args += cs
    if area_min is not None:
        sql += " AND area_m2>=?"
        args.append(area_min)
    if area_max is not None:
        sql += " AND area_m2<=?"
        args.append(area_max)
    with _conn() as c:
        return [dict(r) for r in c.execute(sql + " ORDER BY visto_em DESC", args)]


COPIA_MARCA = "CÓPIA DE TESTE (não usar)"
_SEM_COPIA = ("entrega", "_revisao", "anexos")


def duplicar_job(job_id: str, numero_novo: int) -> str:
    """ORDEM 028-5: "Duplicar trabalho". Cópia com nº novo: arquivos, campos, candidatos, todos os
    eventos (resultados das etapas já feitas) e a escolha de base/área. O laudo entregue não é
    copiado. O original só é LIDO."""
    import shutil
    orig = job(job_id)
    dados = dict(orig["dados"])
    novo_id = uuid.uuid4().hex[:12]
    dados.update({"id": novo_id, "numero": numero_novo,
                  "contexto": f"{COPIA_MARCA} do trabalho nº {orig['numero']}. " + (dados.get("contexto") or "")})
    agora = _agora()
    with _conn() as c:
        c.execute("INSERT INTO av_jobs (id, numero, dados_json, etapa, status, criado, atualizado) VALUES (?,?,?,?,?,?,?)",
                  (novo_id, numero_novo, json.dumps(dados, ensure_ascii=False, default=str), orig["etapa"],
                   orig["status"], agora, agora))
        for r in c.execute("SELECT nome, tipo, caminho, papel, upload_id FROM av_files WHERE job=? ORDER BY id",
                           (job_id,)).fetchall():
            c.execute("INSERT INTO av_files (job, nome, tipo, caminho, papel, upload_id) VALUES (?,?,?,?,?,?)",
                      (novo_id, r["nome"], r["tipo"], r["caminho"], r["papel"], r["upload_id"]))
        for t, cols in (("av_fields", "nome, json"), ("av_candidates", "n, json")):
            for r in c.execute(f"SELECT {cols} FROM {t} WHERE job=?", (job_id,)).fetchall():
                c.execute(f"INSERT INTO {t} (job, {cols}) VALUES (?,?,?)", (novo_id, r[0], r[1]))
        for r in c.execute("SELECT etapa, nivel, msg, dados_json, ts FROM av_events WHERE job=? ORDER BY id",
                           (job_id,)).fetchall():
            c.execute("INSERT INTO av_events (job, etapa, nivel, msg, dados_json, ts) VALUES (?,?,?,?,?,?)",
                      (novo_id, r["etapa"], r["nivel"], r["msg"], r["dados_json"], r["ts"]))
    origem, destino = pasta(job_id), pasta(novo_id)
    for item in origem.iterdir():
        if item.name in _SEM_COPIA:
            continue
        if item.is_dir():
            shutil.copytree(item, destino / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, destino / item.name)
    esc = setting(f"area_escolha:{job_id}")
    if esc:
        set_setting(f"area_escolha:{novo_id}", esc)
    evento(novo_id, "orquestrador", "info", f"trabalho duplicado do nº {orig['numero']} ({COPIA_MARCA})")
    return novo_id
