"""ORDEM 042 (D-094 a D-097, K3 v1.1): entrada do avaliador novo.

- Cadastro com os campos do K3 §1 + autorização da base comum (sim/não, com data).
- Cada avaliador tem o PRÓPRIO login e vê só os dados dele (trabalhos, clientes, propostas, regras,
  preços, modelos, identidade). O Alan é o AV-0001 (o dono da instalação).
- CPF, endereço e Pix ficam só na configuração (setting "contratado:<AV>"), nunca no git nem nos
  logs.
- Modelos (D-094/D-097): para laudo, proposta e contrato, o avaliador escolhe "do sistema" ou
  "o meu". O que ele sobe é ANONIMIZADO antes de guardar (K3 §2).
- Identidade (D-095): logo e cores enviadas pelo avaliador; sem logo, visual neutro e sem marca.
  O sistema não cria logo. A identidade do Alan fica só para o Alan.
- Preço (D-097): vem da tabela do próprio avaliador; sem tabela, fica em branco (sem sugestão).
  A tabela do Alan nunca aparece para outro avaliador."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from lovable import auth, config

from . import db

ALAN = "AV-0001"
MODALIDADES = ("OV", "AM", "AM_GARANTIA", "AMJ")
NEUTRO = {"principal": "333333", "destaque": "8A8A8A", "texto": "222222"}   # sem marca (D-095)
ALAN_CORES = {"principal": "18283B", "destaque": "F5B800", "texto": "5B6470"}  # D-040, só do Alan

_DDL = """CREATE TABLE IF NOT EXISTS av_avaliadores (
  id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, dados TEXT NOT NULL DEFAULT '{}',
  criado TEXT NOT NULL, atualizado TEXT NOT NULL)"""

CAMPOS = ("nome", "creci", "cnai", "cidade", "regiao", "modalidades", "tipos", "telefone", "site",
          "instagram", "email_contato", "formacao", "cores", "precos", "prazos", "pagamento",
          "compartilhar", "compartilhar_data", "modelos")


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def init() -> None:
    db.init()
    with db._conn() as c:
        c.execute(_DDL)


def _proximo_id() -> str:
    """Código novo, NUNCA reaproveitado (um avaliador apagado não passa os dados a outro)."""
    with db._conn() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM av_avaliadores")]
    ultimo = int(db.setting("avaliador_seq") or 1)
    n = max([int(i[3:]) for i in ids if re.fullmatch(r"AV-\d{4}", i)] + [ultimo]) + 1
    db.set_setting("avaliador_seq", str(n))
    return f"AV-{n:04d}"


def cadastrar(email: str, senha: str, dados: dict) -> str:
    """Cria o login e o cadastro. Devolve o código (AV-NNNN), nunca o nome."""
    init()
    auth.init()
    if auth.user_by_email(email):
        raise ValueError("Já existe uma conta com este e-mail.")   # 186
    av = _proximo_id()
    d = {k: dados.get(k) for k in CAMPOS if k in dados}
    if d.get("compartilhar") is not None and not d.get("compartilhar_data"):
        d["compartilhar_data"] = datetime.now().strftime("%Y-%m-%d")
    auth.criar_usuario(email, senha)
    with db._conn() as c:
        c.execute("INSERT INTO av_avaliadores (id, email, dados, criado, atualizado) VALUES (?,?,?,?,?)",
                  (av, email.strip().casefold(), json.dumps(d, ensure_ascii=False), _agora(), _agora()))
    if d.get("compartilhar") is not None:
        db.set_setting(f"compartilhar:{av}", json.dumps({"sim": bool(d["compartilhar"]),
                                                          "data": d["compartilhar_data"]}))
    return av


def obter(av: str) -> dict | None:
    init()
    if av == ALAN:
        cfg = json.loads(db.setting("avaliador") or "{}")
        return {"id": ALAN, "email": db.setting("dono_email") or "", "dados": {
            **cfg, "cores": ALAN_CORES, "modalidades": list(MODALIDADES), "modelos": {}}}
    with db._conn() as c:
        r = c.execute("SELECT * FROM av_avaliadores WHERE id=?", (av,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["dados"] = json.loads(d["dados"] or "{}")
    return d


def atualizar(av: str, dados: dict) -> dict:
    atual = obter(av)
    if atual is None or av == ALAN:
        raise ValueError("avaliador inexistente")
    novo = {**atual["dados"], **{k: v for k, v in dados.items() if k in CAMPOS}}
    if "compartilhar" in dados:
        novo["compartilhar_data"] = datetime.now().strftime("%Y-%m-%d")
        db.set_setting(f"compartilhar:{av}", json.dumps({"sim": bool(dados["compartilhar"]),
                                                          "data": novo["compartilhar_data"]}))
    with db._conn() as c:
        c.execute("UPDATE av_avaliadores SET dados=?, atualizado=? WHERE id=?",
                  (json.dumps(novo, ensure_ascii=False), _agora(), av))
    return obter(av)


def apagar(av: str) -> None:
    """Remove o avaliador (login, cadastro, dados dele). Só para testes/limpeza."""
    import shutil
    a = obter(av)
    if a is None or av == ALAN:
        return
    with db._conn() as c:
        c.execute("DELETE FROM av_avaliadores WHERE id=?", (av,))
        c.execute("DELETE FROM users WHERE email=?", (a["email"],))
        for k, in list(c.execute("SELECT chave FROM av_settings")):
            if k.endswith(":" + av) or f":{av}:" in k:
                c.execute("DELETE FROM av_settings WHERE chave=?", (k,))
        c.execute("DELETE FROM av_fichas WHERE avaliador_id=?", (av,)) if _tem_tabela(c, "av_fichas") else None
        if _tem_tabela(c, "av_clientes"):
            c.execute("DELETE FROM av_clientes WHERE avaliador_id=?", (av,))
        jobs = [r[0] for r in c.execute("SELECT id, dados_json FROM av_jobs")
                if (json.loads(r[1] or "{}").get("avaliador_id") == av)]
        for jid in jobs:
            for t in ("av_events", "av_candidates", "av_fields", "av_files", "av_ia_chamadas"):
                c.execute(f"DELETE FROM {t} WHERE job=?", (jid,))
            c.execute("DELETE FROM av_jobs WHERE id=?", (jid,))
    for jid in jobs:
        shutil.rmtree(db.pasta(jid), ignore_errors=True)
    shutil.rmtree(pasta(av), ignore_errors=True)


def _tem_tabela(c, nome: str) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nome,)).fetchone() is not None


def de_usuario(user: dict) -> str:
    """Código do avaliador do usuário logado (o dono da instalação é o Alan)."""
    init()
    email = str((user or {}).get("email") or "").strip().casefold()
    if email and email == (db.setting("dono_email") or "").strip().casefold():
        return ALAN
    with db._conn() as c:
        r = c.execute("SELECT id FROM av_avaliadores WHERE email=?", (email,)).fetchone()
    return r[0] if r else ""


def pasta(av: str) -> Path:
    p = Path(config.DATA_DIR) / "avaliadores" / av
    p.mkdir(parents=True, exist_ok=True)
    return p


# ------------------------------------------------------------------ identidade (D-095)
def logo(av: str) -> Path | None:
    if av == ALAN:
        from . import identidade
        return identidade.caminho_logo()
    p = pasta(av) / "logo.png"
    return p if p.is_file() else None


def cores(av: str) -> dict:
    if av == ALAN:
        return dict(ALAN_CORES)
    c = (obter(av) or {}).get("dados", {}).get("cores") or {}
    if not logo(av) and not c:
        return dict(NEUTRO)
    ok = {k: str(v).lstrip("#").upper() for k, v in c.items() if re.fullmatch(r"#?[0-9A-Fa-f]{6}", str(v))}
    return {**NEUTRO, **ok}


def identidade_avaliador(av: str) -> dict:
    """Os campos que o laudo usa (nome, CRECI, CNAI, contatos, formação) do avaliador."""
    a = obter(av) or {"dados": {}}
    d = a["dados"]
    out = {k: str(d.get(k) or "") for k in ("nome", "creci", "cnai", "telefone", "site", "instagram",
                                             "formacao", "qualificacao")}
    out["creci"] = re.sub(r"(?i)^\s*creci[\s:-]*", "", out["creci"])     # o modelo já escreve "CRECI"
    out["cnai"] = re.sub(r"(?i)^\s*cnai[\s:nº°o.-]*", "", out["cnai"])
    return out


# ------------------------------------------------------------------ tabela de preços (ORDEM 184)
NOME_SERVICO = {"OV": "Opinião de Valor", "AM": "PTAM não judicial", "AM_GARANTIA": "PTAM para garantia", "AMJ": "PTAM judicial"}


def _cod(m: str) -> str:
    m = (m or "").strip()
    return "AM_GARANTIA" if m.replace(" ", "_").upper() == "AM_GARANTIA" else m


def tabela_precos(av: str) -> list[dict]:
    """As linhas que o avaliador salvou (vazia se nunca salvou). Cada linha: servico (OV/AM/AM_GARANTIA/AMJ ou ""),
    nome, tipo (opcional, ex.: "galpão"), valor ("450,00"), prazo_dias (opcional) e obs."""
    import json
    from . import db
    try:
        v = json.loads(db.setting(f"tabela_precos:{av}") or "[]")
    except ValueError:
        return []
    return v if isinstance(v, list) else []


def tabela_salva(av: str) -> bool:
    from . import db
    return db.setting(f"tabela_precos:{av}") is not None


def linhas_iniciais(av: str) -> list[dict]:
    """Primeira vez: as 4 modalidades da P7. Do Alan, com o piso que o sistema já usava (D-051), para ele conferir e salvar;
    dos outros, em branco (o sistema não inventa preço)."""
    out = []
    for cod, nome in NOME_SERVICO.items():
        v, dias = "", None
        if av == ALAN:
            from . import propostas
            v = f"{propostas.preco_padrao(cod):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            dias = 15 if cod == "AMJ" else 3
        out.append({"servico": cod, "nome": nome, "tipo": "", "valor": v, "prazo_dias": dias, "obs": ""})
    if av == ALAN:
        out.append({"servico": "", "nome": "Galpão (não judicial)", "tipo": "galpão",
                    "valor": "1.000,00", "prazo_dias": 3, "obs": ""})
    return out


def salvar_tabela(av: str, linhas: list[dict]) -> list[dict]:
    import json
    from . import db
    from .rotas_propostas import valor_decimal
    limpas = []
    for l in linhas[:60]:
        if not isinstance(l, dict):            # revisão 184: linha que não é objeto → 400, não 500
            raise ValueError("linha da tabela em formato errado")
        nome = str(l.get("nome") or "").strip()[:120]
        serv = _cod(str(l.get("servico") or ""))
        if serv and serv not in NOME_SERVICO:
            raise ValueError(f"serviço desconhecido: {serv}")
        if not nome and not serv:
            continue
        rot = nome or NOME_SERVICO.get(serv, serv)
        v = str(l.get("valor") or "").strip()
        if v and valor_decimal(v) is None:
            raise ValueError(f"valor sem número em “{rot}”")
        d = l.get("prazo_dias")
        try:
            d = int(d) if d not in (None, "") else None
        except (TypeError, ValueError):
            raise ValueError(f"prazo em dias sem número em “{rot}”")
        if d is not None and not 0 < d <= 365:
            raise ValueError("o prazo vai de 1 a 365 dias")
        limpas.append({"servico": serv, "nome": nome or NOME_SERVICO.get(serv, ""), "tipo": str(l.get("tipo") or "").strip()[:60],
                       "valor": v, "prazo_dias": d, "obs": str(l.get("obs") or "").strip()[:300]})
    db.set_setting(f"tabela_precos:{av}", json.dumps(limpas, ensure_ascii=False))
    return limpas


def _sem_acento(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").casefold()) if unicodedata.category(c) != "Mn")


def linha_da_tabela(av: str, modalidade: str, tipo: str = "") -> dict | None:
    """A linha que vale para este serviço: a do tipo de imóvel (ex.: galpão) ganha da linha geral da modalidade.
    Uma linha só de tipo (sem serviço) vale para os serviços não judiciais daquele tipo."""
    mod, t = _cod(modalidade), _sem_acento(tipo)

    palavras = set(re.findall(r"[a-z0-9]+", t))

    def casa_tipo(l):          # revisão 184: palavra inteira ("sala" não pega "salão de festas"); galpão/galpões
        lt = re.findall(r"[a-z0-9]+", _sem_acento(l.get("tipo") or ""))
        return bool(lt) and all(w in palavras or (w.endswith("ao") and w[:-2] + "oes" in palavras) for w in lt)

    linhas = [l for l in tabela_precos(av) if l.get("valor")]
    for l in linhas:
        if l.get("servico") == mod and casa_tipo(l):
            return l
    if mod != "AMJ":
        for l in linhas:
            if not l.get("servico") and casa_tipo(l):
                return l
    for l in linhas:
        if l.get("servico") == mod and not l.get("tipo"):
            return l
    return None


def prazo_da_linha(l: dict | None) -> str:
    d = (l or {}).get("prazo_dias")
    return f"em até {d} dias úteis após a visita técnica" if d else ""


# ------------------------------------------------------------------ preço (D-097)
def preco(av: str, modalidade: str, tipo: str = "") -> str:
    """Preço da tabela do PRÓPRIO avaliador; sem tabela, "" (o sistema não sugere valor)."""
    if tabela_salva(av):                       # 184: a tabela de preços que o avaliador salvou manda
        return str((linha_da_tabela(av, modalidade, tipo) or {}).get("valor") or "")
    if av == ALAN:
        from . import propostas
        return str(propostas.preco_padrao(modalidade, tipo))
    tab = (obter(av) or {}).get("dados", {}).get("precos") or {}
    t = (tipo or "").casefold()
    if "galp" in t and tab.get("galpao"):
        return str(tab["galpao"])
    return str(tab.get(modalidade) or tab.get("padrao") or "")


# ------------------------------------------------------------------ modelos de laudo por modalidade (ORDEM 194)
EXEMPLOS = Path(__file__).resolve().parent / "exemplos"
NOMES_EXEMPLO = {f"laudo_{m}" for m in ("OV", "AM", "AM_GARANTIA", "AMJ")} | {"proposta", "contrato"}


def modelos_laudo(av: str) -> dict:
    """{modalidade: {"uso": "sistema"|"proprio", "arquivo", "regras": [ids], "em": "dd/mm/aaaa"}}."""
    from . import db
    try:
        v = json.loads(db.setting(f"modelos_laudo:{av}") or "{}")
    except ValueError:
        v = {}
    return v if isinstance(v, dict) else {}


def _gravar_modelos_laudo(av: str, v: dict) -> None:
    from . import db
    db.set_setting(f"modelos_laudo:{av}", json.dumps(v, ensure_ascii=False))


def modelo_do_laudo(av: str, modalidade: str) -> dict:
    """L198: o que a montagem usa do modelo do avaliador nessa modalidade: {"formato": {...}, "itens": [...]} ou {}."""
    m = modelos_laudo(av).get(_cod(modalidade)) or {}
    return {"formato": m.get("formato") or {}, "itens": m.get("itens") or []} if m.get("uso") == "proprio" else {}


def modelo_em_uso(av: str, modalidade: str) -> str:
    """"proprio" quando o avaliador subiu e confirmou o modelo dessa modalidade; senão "sistema"."""
    return "proprio" if (modelos_laudo(av).get(_cod(modalidade)) or {}).get("uso") == "proprio" else "sistema"


def _desligar_regras(ids: list[str], av: str, motivo: str) -> None:
    from . import fichas
    for fid in ids or []:
        f = fichas.obter(fid)
        if f and f.get("avaliador_id") == av and f.get("ativa"):
            fichas.gravar({"id": fid, "ativa": False}, quem=av, acao="desativada", motivo=motivo)


def usar_modelo_proprio(av: str, modalidade: str, arquivo: str, regras: list[str],
                        formato: dict | None = None, itens: list[dict] | None = None) -> dict:
    """Confirmado o "o que entendi": o modelo dessa modalidade passa a ser o dele. Trocar de modelo
    desliga as regras do modelo anterior da mesma modalidade."""
    from datetime import date
    mod = _cod(modalidade)
    v = modelos_laudo(av)
    antes = v.get(mod) or {}
    _desligar_regras(antes.get("regras") or [], av, "trocou o modelo próprio da modalidade")
    v[mod] = {"uso": "proprio", "arquivo": arquivo, "regras": regras, "em": date.today().strftime("%d/%m/%Y"),
              "formato": formato or {}, "itens": itens or []}            # L198: a formatação e os itens a mais dele
    _gravar_modelos_laudo(av, v)
    return v[mod]


def voltar_modelo_sistema(av: str, modalidade: str) -> None:
    mod = _cod(modalidade)
    v = modelos_laudo(av)
    antes = v.get(mod) or {}
    _desligar_regras(antes.get("regras") or [], av, "voltou para o modelo do sistema")
    v[mod] = {"uso": "sistema"}
    _gravar_modelos_laudo(av, v)


# ------------------------------------------------------------------ modelos (D-094/D-097)
def escolha_modelo(av: str, qual: str) -> str:
    """"sistema" | "proprio" para laudo, proposta ou contrato."""
    return ((obter(av) or {}).get("dados", {}).get("modelos") or {}).get(qual, "sistema")


def anonimizar(texto: str, extras: list[str] = ()) -> str:
    """K3 §2: tira nomes de pessoas/empresas citados, CPF/CNPJ/RG, endereço, quadra, lote,
    matrícula, inscrição, links, e-mails e telefones; valores e áreas viram faixa."""
    from .protecao import proteger_texto
    t = texto or ""
    t = re.sub(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", "[CPF]", t)
    t = re.sub(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b", "[CNPJ]", t)
    t = re.sub(r"https?://\S+", "[link]", t)
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[e-mail]", t)
    t = re.sub(r"\(?\b\d{2}\)?\s?9?\s?\d{4}-?\d{4}\b", "[telefone]", t)
    t = re.sub(r"(?i)\b(rua|avenida|av\.|alameda|travessa|rodovia)\s+[^,\n]{2,60}", r"\1 [endereço]", t)
    t = re.sub(r"(?i)\b(quadra|qd\.?|lote|lt\.?|matr[íi]cula|inscri[çc][ãa]o|cep)\s*(n[ºo°.]?\s*)?[\w./-]+", r"\1 [—]", t)
    t = re.sub(r"(?i)\b(condom[íi]nio|residencial|edif[íi]cio|ed\.)\s+[A-ZÀ-Ý][^,.;\n]{1,60}", r"\1 [—]", t)
    t = re.sub(r"(?i)\b(sr\.?|sra\.?|senhor|senhora|requerente|solicitante|propriet[áa]ri[oa]|cliente)\s*:?\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ÿ]+(?:\s+(?:d[aeo]s?\s+)?[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ÿ]+){1,5})",
               r"\1 [nome]", t)
    t = re.sub(r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ]{2,}(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ&]{2,}){1,6})\s+(LTDA|S/?A|ME|EIRELI|EPP)\b", "[empresa]", t)
    for x in extras:
        if x and len(x) > 2:
            t = re.sub(re.escape(x), "[—]", t, flags=re.I)
    return proteger_texto(t)


def guardar_modelo_proprio(av: str, qual: str, nome_arquivo: str, texto: str, extras: list[str] = ()) -> Path:
    """Guarda SÓ o texto anonimizado (o arquivo original não fica guardado)."""
    p = pasta(av) / "modelos"
    p.mkdir(parents=True, exist_ok=True)
    seguro = re.sub(r"[^\w.-]+", "_", Path(nome_arquivo).stem)[:60]
    destino = p / f"{qual}_{seguro}.txt"          # 194: no laudo, qual = "laudo_<modalidade>"
    destino.write_text(anonimizar(texto, extras), encoding="utf-8")
    return destino


def ler_texto(nome: str, dados: bytes) -> str:
    """Texto de um laudo/proposta/contrato enviado (PDF ou Word), sem guardar o arquivo."""
    import io
    if nome.lower().endswith(".pdf"):
        import pymupdf
        with pymupdf.open(stream=dados, filetype="pdf") as d:
            return "\n".join(p.get_text() for p in d)
    if nome.lower().endswith(".docx"):
        import docx
        doc = docx.Document(io.BytesIO(dados))
        return "\n".join(p.text for p in doc.paragraphs) + "\n" + "\n".join(
            c.text for t in doc.tables for r in t.rows for c in r.cells)
    return dados.decode("utf-8", errors="ignore")
