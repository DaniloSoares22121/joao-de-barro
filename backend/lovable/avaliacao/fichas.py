"""ORDEM 026 v2 (D-058 + D-061): módulo de aprendizado — fichas de conhecimento.

A ficha é a unidade de conhecimento: situação → decisão → porquê, com etiquetas (tipo de
imóvel, modalidade, etapa), nível (oficial | validado | aprendido | recusado) e escopo
(geral | avaliador). Ordem de busca em toda chamada de IA e pergunta de regra:
  1º oficial → 2º regras do próprio avaliador → 3º validado → 4º aprendido (só sugestão).
Se a regra do avaliador bater de frente com a oficial, vale a oficial (e o sistema avisa).
Só vão as fichas com as etiquetas do caso, com limite de tamanho.

Fase F1: tabela, importação do P3 (RN → oficial com fonte do P4, senão validado; RG/PM/PR →
validado geral; CP → caso do Alan) e das fichas-semente, e a ordem de busca ligada às IAs.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .plural import pl

NIVEIS = ("oficial", "validado", "aprendido", "recusado")
TIPOS = ("regra", "caso", "modelo")
ETAPAS = ("documentos", "áreas", "vistoria", "fotos", "pesquisa", "cálculo", "redação", "revisão",
          "proposta/contrato")
TIPOS_IMOVEL = ("casa", "sobrado", "apartamento", "lote", "galpão", "sala/loja", "rural")
MODALIDADES = ("OV", "AM", "AM garantia", "AMJ")
AVALIADOR_ALAN = "AV-0001"      # código, nunca nome (D-061)
LIMITE_CHARS = 14000            # fichas por chamada de IA (sem mandar a base inteira)
SEMENTE = Path(__file__).parent / "assets" / "conhecimento" / "fichas-semente.md"
K1 = Path(__file__).parent / "assets" / "conhecimento" / "K1.md"   # ORDEM 038: F-K001..F-K024

_DDL = """
CREATE TABLE IF NOT EXISTS av_fichas (
  id TEXT PRIMARY KEY, titulo TEXT NOT NULL, situacao TEXT NOT NULL DEFAULT '',
  decisao TEXT NOT NULL DEFAULT '', porque TEXT NOT NULL DEFAULT '',
  tipo TEXT NOT NULL DEFAULT 'regra', tipo_imovel TEXT NOT NULL DEFAULT '[]',
  modalidade TEXT NOT NULL DEFAULT '[]', etapa TEXT NOT NULL DEFAULT '[]',
  nivel TEXT NOT NULL DEFAULT 'aprendido', escopo TEXT NOT NULL DEFAULT 'geral',
  avaliador_id TEXT NOT NULL DEFAULT '', trabalho_id TEXT NOT NULL DEFAULT '',
  fonte TEXT NOT NULL DEFAULT '', concordam INTEGER NOT NULL DEFAULT 1,
  historico TEXT NOT NULL DEFAULT '[]', ativa INTEGER NOT NULL DEFAULT 1,
  editada INTEGER NOT NULL DEFAULT 0, conflita_com TEXT NOT NULL DEFAULT '',
  criado TEXT NOT NULL, atualizado TEXT NOT NULL)
"""
_LISTAS = ("tipo_imovel", "modalidade", "etapa", "historico")


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def init() -> None:
    db.init()
    with db._conn() as c:
        c.execute(_DDL)


def _n(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.casefold().split())


def _linha(r) -> dict:
    d = dict(r)
    for k in _LISTAS:
        d[k] = json.loads(d.get(k) or "[]")
    d["ativa"] = bool(d["ativa"])
    d["editada"] = bool(d["editada"])
    return d


def todas(incluir_inativas: bool = True) -> list[dict]:
    init()
    with db._conn() as c:
        rows = c.execute("SELECT * FROM av_fichas" + ("" if incluir_inativas else " WHERE ativa=1")
                         + " ORDER BY id").fetchall()
    return [_linha(r) for r in rows]


def obter(fid: str) -> dict | None:
    init()
    with db._conn() as c:
        r = c.execute("SELECT * FROM av_fichas WHERE id=?", (fid,)).fetchone()
    return _linha(r) if r else None


TITULO_MAX = 120


def titulo_curto(s: str, n: int = TITULO_MAX) -> str:
    """ORDEM 033-2: título da ficha sem cortar palavra no meio ("…para as fotogra"): corta no
    fim de uma palavra e põe "…"."""
    s = " ".join(str(s or "").split())
    if len(s) <= n:
        return s
    corte = s[:n - 1]
    if " " in corte and not s[n - 1].isspace():
        corte = corte.rsplit(" ", 1)[0]
    return corte.rstrip(" ,;:.–-") + "…"


def gravar(f: dict, quem: str, acao: str, motivo: str = "", sobrescrever: bool = True) -> dict:
    """Insere ou atualiza; cada mudança vai para o histórico (quem, ação, quando, motivo)."""
    init()
    antes = obter(f["id"])
    if antes and not sobrescrever:
        return antes
    if antes and acao == "importada" and all(f.get(k) == antes.get(k) for k in f if k not in ("historico", "atualizado", "criado")):
        return antes      # reimportação sem mudança: não suja o histórico
    agora = _agora()
    hist = (antes or {}).get("historico", []) + [{"quem": quem, "acao": acao, "quando": agora,
                                                   "motivo": motivo}]
    reg = {**(antes or {}), **f, "historico": hist, "atualizado": agora}
    reg.setdefault("criado", agora)
    reg.setdefault("ativa", True)
    reg.setdefault("editada", False)
    reg.setdefault("conflita_com", "")
    reg.setdefault("concordam", 1)
    for k in ("situacao", "decisao", "porque", "fonte", "avaliador_id", "trabalho_id"):
        reg.setdefault(k, "")
    cols = ["id", "titulo", "situacao", "decisao", "porque", "tipo", "tipo_imovel", "modalidade",
            "etapa", "nivel", "escopo", "avaliador_id", "trabalho_id", "fonte", "concordam",
            "historico", "ativa", "editada", "conflita_com", "criado", "atualizado"]
    vals = [json.dumps(reg.get(k, []), ensure_ascii=False) if k in _LISTAS else
            (int(bool(reg.get(k))) if k in ("ativa", "editada") else reg.get(k, "")) for k in cols]
    with db._conn() as c:
        c.execute(f"INSERT OR REPLACE INTO av_fichas ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
    return obter(f["id"])


# ------------------------------------------------------------------ etiquetas por palavras
_ETAPA_PALAVRAS = {
    "documentos": ("documento", "matricula", "iptu", "escritura", "certidao", "cartorio"),
    "áreas": ("area", "m2", "m²", "terreno", "privativa", "construida"),
    "vistoria": ("vistoria", "visita"),
    "fotos": ("foto", "fachada", "capa", "imagem", "legenda"),
    "pesquisa": ("referencia", "amostra", "pesquisa", "anuncio", "portal", "candidat"),
    "cálculo": ("calculo", "unitario", "valor", "faixa", "homogene", "dispers", "cv "),
    "redação": ("texto", "redacao", "termo", "frase", "escrever", "titulo", "palavra", "sumario"),
    "revisão": ("revis", "checklist", "pagina"),
    "proposta/contrato": ("proposta", "contrato", "preco", "pagamento", "prazo", "comercial"),
}
_TIPO_PALAVRAS = {"galpão": ("galpao", "barracao", "deposito"), "apartamento": ("apartamento", "apto", "condominio"),
                  "casa": ("casa",), "sobrado": ("sobrado",), "lote": ("lote", "terreno"),
                  "sala/loja": ("sala comercial", "loja"), "rural": ("rural", "fazenda", "chacara")}


def etiquetas(texto: str, escopo: str = "") -> tuple[list[str], list[str], list[str]]:
    """(tipo_imovel, modalidade, etapa) deduzidos do texto; vazio = vale para todos."""
    t = _n(texto)
    tipos = [k for k, ps in _TIPO_PALAVRAS.items() if any(p in t for p in ps)]
    e = _n(escopo)
    mods = [m for m in ("OV", "AMJ", "AM") if re.search(rf"\b{m.lower()}\b", e)]
    if "ptam" in e and not mods:
        mods = ["AM", "AMJ"]
    etapas = [k for k, ps in _ETAPA_PALAVRAS.items() if any(p in t for p in ps)]
    return tipos, mods, etapas


# ------------------------------------------------------------------ importação F1
def _p3(texto_p3: str) -> list[dict]:
    from .conhecimento import _linhas_tabela
    out = []
    for c in _linhas_tabela(texto_p3):
        if len(c) < 8 or not re.fullmatch(r"D-\d{3,}", c[0]):
            continue
        out.append(dict(zip(("id", "data", "origem", "decisao", "regra", "tipo", "escopo", "status"), c[:8])))
    return out


def _fonte_oficial(texto: str, normas: list[dict]) -> str:
    """Norma vigente do P4 citada no texto ("6.530", "1.066", "14653"…), ou ''."""
    nums = set(re.findall(r"\d[\d.]{2,}\d", texto))
    for n in normas:
        tit = n.get("titulo", "") + " " + json.dumps(n.get("itens", {}), ensure_ascii=False)
        if nums & set(re.findall(r"\d[\d.]{2,}\d", tit)):
            return f"P4 {n['codigo']} – {n.get('titulo', '')}".strip(" –")
    return ""


def importar_p3() -> dict:
    """P3 → fichas. Roda de novo sem duplicar; ficha editada na tela não é sobrescrita."""
    from . import conhecimento
    init()
    conhecimento.importar_normas()
    normas = conhecimento.normas_vigentes()
    cont = {k: 0 for k in NIVEIS}
    for d in _p3(conhecimento._ler("P3")):
        fid = "F-" + d["id"]
        atual = obter(fid)
        if atual and atual.get("editada"):
            cont[atual["nivel"]] += 1
            continue
        tipo_p3 = d["tipo"].upper()
        texto = f"{d['decisao']} {d['regra']}"
        tipos, mods, etapas = etiquetas(texto + " " + d["origem"], d["escopo"])
        fonte = f"P3 {d['id']}"
        if tipo_p3 == "RN":
            of = _fonte_oficial(texto, normas)
            nivel, fonte = ("oficial", f"{of}; {fonte}") if of else ("validado", fonte)
            tipo, escopo, av = "regra", "geral", ""
        elif tipo_p3 == "CP":
            nivel, tipo, escopo, av = "validado", "caso", "avaliador", AVALIADOR_ALAN
        else:   # RG, PM, PR: as regras do Alan são o padrão de todos (D-058)
            nivel, tipo, escopo, av = "validado", "regra", "geral", ""
        st = _n(d["status"])
        ativa = not any(x in st for x in ("substituid", "revogad", "cancelad"))
        gravar({"id": fid, "titulo": titulo_curto(d["decisao"]), "situacao": d["origem"], "decisao": d["regra"],
                "porque": d["decisao"], "tipo": tipo, "tipo_imovel": tipos, "modalidade": mods,
                "etapa": etapas, "nivel": nivel, "escopo": escopo, "avaliador_id": av, "fonte": fonte,
                "ativa": ativa}, quem="importação P3", acao="importada")
        cont[nivel] += 1
    return cont


def _sementes(md: str) -> list[dict]:
    out = []
    for bloco in re.split(r"\n(?=### F-[SK]\d{3})", md):
        m = re.match(r"### (F-[SK]\d{3}) — (.+)", bloco.strip())
        if not m:
            continue
        campos: dict[str, str] = {}
        atual = None
        for ln in bloco.splitlines():
            m2 = re.match(r"^- ([a-zãâáçéêíóôõú_ ]+?):\s*(.*)$", ln)
            if m2:
                atual = m2.group(1).strip()
                campos[atual] = m2.group(2).strip()
            elif atual and re.match(r"^\s{2,}- ", ln):
                # ORDEM 038: campo em sublista ("- decisão:" + "  - item"): junta os itens
                item = ln.strip()[2:].strip().rstrip(";")
                campos[atual] = "; ".join(x for x in (campos[atual].rstrip(":"), item) if x)
        linha_tipo = campos.get("tipo", "")
        cab = {"tipo": linha_tipo.split("|")[0].strip()}
        cab.update({k: v.strip() for k, v in re.findall(r"(nível|escopo):\s*([^|]+)", linha_tipo)})
        et = dict(re.findall(r"(tipo_imovel|modalidade|etapa)=([^;]+)", campos.get("etiquetas", "")))

        def lista(s):
            itens = [x.strip() for x in (s or "").split(",") if x.strip()]
            if any(_n(x) in ("todos", "todas") for x in itens):
                return []          # "casa, sobrado, todos" = vale para todos
            return itens
        out.append({"id": m.group(1), "titulo": m.group(2).strip(),
                    "tipo": cab.get("tipo", "regra").strip(), "nivel": cab.get("nível", "validado").strip(),
                    "escopo": cab.get("escopo", "geral").strip(),
                    "tipo_imovel": lista(et.get("tipo_imovel")), "modalidade": lista(et.get("modalidade")),
                    "etapa": lista(et.get("etapa")), "situacao": campos.get("situação", ""),
                    "decisao": campos.get("decisão", ""), "porque": campos.get("porquê", ""),
                    "fonte": campos.get("fonte", "")})
        # escopo com anotação ("geral (precedente para galpões)", "avaliador (precedente)"):
        # fica geral/avaliador, e a anotação vai para a fonte
        bruto = out[-1]["escopo"]
        if _n(bruto) not in ("geral", "avaliador"):
            out[-1]["escopo"] = "avaliador" if _n(bruto).startswith("avaliador") else "geral"
            out[-1]["fonte"] = "; ".join(x for x in (out[-1]["fonte"], f"escopo: {bruto}") if x)
        if out[-1]["escopo"] == "avaliador":
            out[-1]["avaliador_id"] = AVALIADOR_ALAN
    return out


def importar_sementes(caminho: Path = SEMENTE, quem: str = "") -> int:
    init()
    n = 0
    for f in _sementes(caminho.read_text(encoding="utf-8")):
        atual = obter(f["id"])
        if atual and atual.get("editada"):
            continue
        gravar(f, quem=quem or ("importação K1" if caminho.name == "K1.md" else "importação semente"), acao="importada")
        n += 1
    return n


def importar_tudo() -> dict:
    cont = importar_p3()
    cont["sementes"] = importar_sementes() if SEMENTE.is_file() else 0
    cont["k1"] = importar_sementes(K1) if K1.is_file() else 0     # mesma regra: roda de novo sem duplicar
    return cont


# ------------------------------------------------------------------ ordem de busca
def _casa(lista: list[str], valor: str | None) -> bool:
    return not lista or not valor or _n(valor) in {_n(x) for x in lista} or any(
        _n(x) in _n(valor) or _n(valor) in _n(x) for x in lista)


def _classe_imovel(tipo: str) -> str:
    t = _n(tipo)
    for k, ps in _TIPO_PALAVRAS.items():
        if any(p in t for p in ps):
            return k
    return t


def _de_estrutura(texto: str) -> bool:
    from .modelo_avaliador import regra_de_estrutura
    return regra_de_estrutura(texto)


def buscar(avaliador_id: str = AVALIADOR_ALAN, tipo_imovel: str = "", modalidade: str = "",
           etapas: tuple[str, ...] | list[str] = ()) -> list[dict]:
    """Fichas do caso na ordem: oficial → do avaliador → validado → aprendido. Cada uma traz
    "camada" (o porquê da posição)."""
    tipo = _classe_imovel(tipo_imovel)
    out: list[dict] = []
    for f in todas(incluir_inativas=False):
        proprio = f["escopo"] == "avaliador" and f["avaliador_id"] == avaliador_id
        if f["nivel"] == "recusado" and not proprio:
            continue
        if proprio and str(f.get("fonte") or "").startswith("laudo próprio") and _de_estrutura(f.get("decisao") or ""):
            continue      # L199: regra de estrutura tirada do modelo deixa de valer (o laudo segue o padrão JdB); nada é apagado      # recusada só sai da base comum; para o autor continua regra dele
        if not _casa(f["tipo_imovel"], tipo) or not _casa(f["modalidade"], modalidade):
            continue
        if etapas and f["etapa"] and not any(_casa(f["etapa"], e) for e in etapas):
            continue
        if f["escopo"] == "avaliador" and f["avaliador_id"] != avaliador_id:
            if f["nivel"] != "aprendido" or not compartilha(f["avaliador_id"]):
                continue
            camada = 4      # de outro avaliador: só sugestão
        elif f["nivel"] == "oficial":
            camada = 1
        elif f["escopo"] == "avaliador":
            camada = 2
        elif f["nivel"] == "validado":
            camada = 3
        else:
            camada = 4
        out.append({**f, "camada": camada})
    out.sort(key=lambda f: (f["camada"], f["id"]))
    return out


ROTULO_CAMADA = {1: "OFICIAL", 2: "REGRA DO AVALIADOR", 3: "VALIDADO", 4: "APRENDIDO"}


def texto_ia(avaliador_id: str = AVALIADOR_ALAN, tipo_imovel: str = "", modalidade: str = "",
             etapas: tuple[str, ...] | list[str] = (), limite: int = LIMITE_CHARS) -> str:
    """Bloco de fichas para o prompt da IA, na ordem de busca e com o nível de cada uma."""
    fs = buscar(avaliador_id, tipo_imovel, modalidade, etapas)
    oficiais = {f["id"] for f in fs if f["camada"] == 1}
    linhas = ["===== FICHAS DE CONHECIMENTO (ordem de busca: oficial → regras do avaliador → "
              "validado → aprendido; cite o nível e a fonte quando usar) ====="]
    tam = len(linhas[0])
    for f in fs:
        aviso = ""
        if f["camada"] == 4:
            aviso = f" [aprendido de {pl(f.get('concordam') or 1, 'avaliador', 'avaliadores')}, ainda não validado — só sugestão]"
        if f["camada"] == 2 and f.get("conflita_com") in oficiais:
            aviso = f" [CONFLITA com a oficial {f['conflita_com']}: vale a oficial]"
        ln = (f"- [{ROTULO_CAMADA[f['camada']]}] {f['id']} — {f['titulo']}: {f['decisao']}"
              + (f" (porquê: {f['porque']})" if f.get("porque") and f["porque"] != f["titulo"] else "")
              + (f" — fonte: {f['fonte']}" if f.get("fonte") else "") + aviso)
        if tam + len(ln) > limite:
            linhas.append(f"- (mais {pl(len(fs) - len(linhas) + 1, 'ficha', 'fichas')} fora do limite)")
            break
        linhas.append(ln)
        tam += len(ln)
    return "\n".join(linhas)


def texto_ia_job(job_id: str, etapas: tuple[str, ...] | list[str]) -> str:
    from .agentes import _comum
    t = _comum.trabalho(job_id)
    return texto_ia(AVALIADOR_ALAN, t.tipo, t.modalidade, etapas)


def contagem() -> dict:
    out = {k: 0 for k in NIVEIS}
    for f in todas(incluir_inativas=False):
        out[f["nivel"]] = out.get(f["nivel"], 0) + 1
    return out


# ------------------------------------------------------------------ compartilhamento (F3)
def compartilha(avaliador_id: str) -> bool:
    """Autorização "Compartilhar meu raciocínio com a base comum". O Alan é sempre sim."""
    if avaliador_id == AVALIADOR_ALAN:
        return True
    try:
        return bool(json.loads(db.setting(f"compartilhar:{avaliador_id}") or "{}").get("sim"))
    except ValueError:
        return False
