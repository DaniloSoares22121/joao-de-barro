"""Pesquisa: a lista de anúncios (páginas enviadas pela extensão e a reserva), os links de busca para o
avaliador abrir no Chrome dele e a planilha exportada. 112: a busca automática nos portais saiu (D-117)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .. import db
from ..fonte_mercado import Consulta
from ..modelos import Referencial
from ..portais import slug
from . import _comum
from ..plural import pl


_RASTREIO = re.compile(r"(?i)^(utm(_.*)?|source|gclid|fbclid|ref|origin|origem|from|sl|pos|position|"
                       r"trackid|campaign|_ga|mc_.*|"
                       r"n_(?:src|exp|pills|pg|pos|search_id))$")      # L200 (Caso M): rastreio do Imovelweb


def link_limpo(link: str) -> str:
    """Tira fragmento, barra final e parâmetros de RASTREIO (utm, source…). ORDEM 035: mantém os
    que identificam o imóvel ("detalhes.php?id=83" perdia o id e o link do laudo não abria)."""
    from urllib.parse import parse_qsl, urlencode
    p = urlsplit(link.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _RASTREIO.match(k)]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), urlencode(q), ""))


@lru_cache(maxsize=1)
def vizinhos_goiania() -> dict[str, list[str]]:
    """assets/goiania_vizinhos.json: bairro normalizado -> setores limítrofes."""
    d = json.loads((Path(__file__).resolve().parent.parent / "assets" / "goiania_vizinhos.json")
                   .read_text(encoding="utf-8"))
    return {k: v for k, v in d.items() if not k.startswith("_")}


# ------------------------------------------------------------------ lista de candidatos (ORDEM 003)
from .. import candidatos as C   # noqa: E402

_CONDO = re.compile(r"(?i)^(ed\.?|edif[íi]cio|residencial|condom[íi]nio|res\.)\s")


def _campo_txt(job_id: str, *chaves: str) -> str:
    for c in db.campos(job_id):
        n = C._n(c.nome)
        if all(k in n for k in chaves) and c.valor not in (None, "") and c.origem in ("documento", "vistoria"):
            return str(c.valor)
    return ""


def local_do_trabalho(t) -> tuple[str, str]:
    """(bairro para a busca, condomínio/edifício) — o formulário pode trazer
    "Ed. Residencial Exemplo – Setor Exemplo Continuação"."""
    partes = [p.strip() for p in re.split(r"\s+[–—-]\s+", t.bairro or "") if p.strip()]
    condo = next((p for p in partes if _CONDO.match(p)), "")
    bairro = next((p for p in partes if p != condo), t.bairro)
    return bairro, condo


def area_para_comparar(campos) -> float | None:
    """Área do avaliando só para ORDENAR os candidatos (não vai para o laudo): documento ou
    vistoria primeiro; sem elas, a medida inferida (satélite, D-027). Ex.: Galpão 01 do 9118."""
    from .selecao import _decimal_br, eh_area_construida
    ordem = {"documento": 0, "vistoria": 1, "inferido": 2}
    achadas = []
    for c in campos:
        if c.origem in ordem and eh_area_construida(c.nome):
            try:
                v = float(_decimal_br(c.valor))
            except Exception:
                continue
            if v > 0:
                achadas.append((ordem[c.origem], v))
    return sorted(achadas, key=lambda x: x[0])[0][1] if achadas else None


def avaliando(job_id: str) -> C.Avaliando:
    from .selecao import area_construida
    t = _comum.trabalho(job_id)
    bairro, condo = local_do_trabalho(t)
    condo = condo or _campo_txt(job_id, "condominio") or _campo_txt(job_id, "edificio")
    area = area_construida(job_id)
    if area is None:   # apartamento: área privativa
        v = _campo_txt(job_id, "area", "privativa")
        m = re.search(r"[\d.,]+", v)
        area = C._num(m.group()) if m else None
    if area is None:   # só para comparar: aceita a medida inferida (não entra no laudo)
        area = area_para_comparar(db.campos(job_id))
    q = re.search(r"(\d+)\s*quartos?", _campo_txt(job_id, "quarto") + " " + _campo_txt(job_id, "composicao"))
    padrao = C._n(_campo_txt(job_id, "padrao")).split(" ")[0] if _campo_txt(job_id, "padrao") else ""
    # L200: "idade" achava "cidade"/"unidade" ("Apartamento nº 1.203") e o avaliando virava sempre "antigo"
    idade = _campo_txt(job_id, "idade_aparente") or next(
        (str(c.valor) for c in db.campos(job_id) if C._n(c.nome).startswith("idade") and c.valor not in (None, "")), "")
    # L200 (Caso M): faixa "5 a 15 anos" vale o começo (5), não o 15 colado em "anos" (virava "antigo")
    anos = re.search(r"(\d+)(?:\s*(?:a|e|-)\s*\d+)?\s*anos", idade)
    faixa = re.search(r"(\d+)(?:\s*(?:a|e|-)\s*(\d+))?\s*anos", idade)     # L201-3: o meio da faixa
    idade_anos = (((float(faixa.group(1)) + float(faixa.group(2))) / 2 if faixa.group(2) else float(faixa.group(1))) if faixa else (2.0 if re.search(r"(?i)\bnovo\b", idade) else None))
    return C.Avaliando(tipo=t.tipo, bairro=bairro, cidade=t.cidade,
                       area=float(area) if area else None,
                       quartos=int(q.group(1)) if q else None, padrao=padrao,
                       antigo=not anos or int(anos.group(1)) >= 15, condominio=condo, idade_anos=idade_anos,
                       vizinhos=tuple(vizinhos_goiania().get(slug(bairro), []))
                       if slug(t.cidade) == "goiania" else (),
                       conhecidos=tuple(dict.fromkeys(
                           [bairro] + [v for vs in vizinhos_goiania().values() for v in vs]
                           + [k.replace("-", " ") for k in vizinhos_goiania()])))


def _tip_busca(tipo: str) -> str:
    # galpão/barracão: os portais têm categoria própria (portais._TIPOS["…"]["galpao"]); a
    # classe "comercial" juntaria loja e sala e a busca saía em "imóveis" genérico
    if re.search(r"galpao|barracao|deposito|armazem", C._n(tipo)):
        return "galpao"
    cls = C.tipologia_classe(tipo)
    return {"casa térrea": "casa", "kitnet": "apartamento", "": tipo}.get(cls, cls) or tipo


def _chave(c: Consulta) -> str:
    return f"{c.portal or '*'}|{slug(c.tipologia)}|{slug(c.bairro)}|{slug(c.cidade)}"


def consultas_da_orientacao(t, a: C.Avaliando, orientacao: str, feitas: set[str],
                            primeira: bool) -> tuple[list[Consulta], dict]:
    """Consultas por regra (sem IA): bairro do avaliando (+ condomínio no OLX); "Pedir mais"
    sem orientação -> vizinhos; orientação com "limítrofe/vizinho", nome de bairro conhecido,
    tipologia ou faixa de área. Devolve também filtros {area_min, area_max, mesma_rua}."""
    tip = _tip_busca(t.tipo)
    o = C._n(orientacao)
    filtros: dict = {}
    m = re.search(r"(\d{2,4})\s*(?:a|e|-|ate)\s*(\d{2,4})\s*m", o)
    if m:
        filtros["area_min"], filtros["area_max"] = float(m.group(1)), float(m.group(2))
    if "mesma rua" in o:
        filtros["mesma_rua"] = True
    for palavra, cls in (("sobrado", "sobrado"), ("terrea", "casa"), ("casa", "casa"),
                         ("apartamento", "apartamento")):
        if palavra in o:
            tip = cls
            break
    bairros: list[str] = []
    if primeira:
        bairros = [a.bairro]
    if "limitrofe" in o or "vizinh" in o or "proxim" in o or (not primeira and not o):
        bairros += list(a.vizinhos)
    conhecidos = {C._n(b): b for k, vs in vizinhos_goiania().items() for b in vs}
    bairros += [nome for nn, nome in conhecidos.items() if nn and nn in o]
    if "mesmo bairro" in o or "mesma rua" in o:
        bairros.append(a.bairro)
    out = []
    for b in dict.fromkeys(bairros):
        c = Consulta(tipologia=tip, bairro=b, cidade=t.cidade)
        if _chave(c) not in feitas:
            out.append(c)
    if a.condominio and primeira:   # OLX aceita texto livre: o nome do edifício/condomínio
        c = Consulta(portal="OLX", tipologia=tip, bairro=a.condominio, cidade=t.cidade)
        if _chave(c) not in feitas:
            out.append(c)
    if a.condominio and primeira and tip == "apartamento":
        # ORDEM 010: o Imovelweb não reconhece bairro de condomínio ("Vila Brasília
        # Continuação") e devolvia o país inteiro — apartamento busca pela CIDADE e a lista
        # filtra pelos nomes do condomínio/edifício, área (±25%) e quartos
        out = [x for x in out if not (x.portal in (None, "") and x.bairro == a.bairro)] + [
            Consulta(portal=p, tipologia=tip, bairro=a.bairro, cidade=t.cidade)
            for p in ("ZAP Imóveis", "Viva Real", "OLX")]
        c = Consulta(portal="Imovelweb", tipologia=tip, bairro="", cidade=t.cidade)
        if _chave(c) not in feitas:
            out.append(c)
        unicos: dict[str, Consulta] = {}
        for x in out:
            if _chave(x) not in feitas:
                unicos.setdefault(_chave(x), x)
        out = list(unicos.values())
    if tip == "galpao" and primeira:
        # galpão é raro no bairro (Polo Empresarial Goiás: 4 no ZAP/Viva Real em 12/11/2026, 206
        # na cidade): a 1ª rodada já busca também a cidade inteira; a lista filtra pela cidade
        c = Consulta(tipologia=tip, bairro="", cidade=t.cidade)
        if _chave(c) not in feitas and all(_chave(c) != _chave(x) for x in out):
            out.append(c)
    if not out and not primeira and not o:   # sem vizinhos conhecidos: a cidade toda no OLX
        c = Consulta(portal="OLX", tipologia=tip, bairro="", cidade=t.cidade)
        if _chave(c) not in feitas:
            out.append(c)
    return out, filtros


def _ultima_lista(job_id: str) -> dict:
    with db._conn() as c:
        r = c.execute("SELECT id, dados_json FROM av_events WHERE job=? AND etapa='pesquisa' "
                      "AND nivel='lista' ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
    if not r:
        return {}
    d = json.loads(r["dados_json"] or "{}")
    d["_id"] = r["id"]
    return d


def exportar(job_id: str) -> tuple[Path, Path]:
    """Lista inteira (todas as rodadas) em <job>/pesquisa/candidatos.md e .xlsx."""
    t = _comum.trabalho(job_id)
    refs = db.candidatos(job_id)
    titulo = f"Candidatos a referencial – nº {t.numero} – {t.tipo} – {t.bairro}, {t.cidade}"
    pasta = db.pasta(job_id) / "pesquisa"
    pasta.mkdir(parents=True, exist_ok=True)
    md = pasta / "candidatos.md"
    md.write_text(C.markdown(refs, titulo), encoding="utf-8")
    return md, C.planilha(refs, pasta / "candidatos.xlsx", titulo)


_GENERICOS = {"edificio", "condominio", "residencial", "torre", "bloco", "apartamento", "goiania",
              "aparecida", "jardim", "parque", "setor", "vila"}


def nomes_condominio(job_id: str, a: C.Avaliando) -> list[str]:
    """Palavras distintivas do condomínio/edifício (formulário + campos: "Exemplo",
    "Residencial Exemplo", "Rio Quente"...)."""
    fontes = [a.condominio, _campo_txt(job_id, "condominio"), _campo_txt(job_id, "edificio")]
    toks: list[str] = []
    for f in fontes:
        for t in C._n(re.sub(r"[–—(),;.]", " ", f or "")).split():
            if len(t) >= 4 and t not in _GENERICOS and t not in toks:
                toks.append(t)
    return toks


def mesmo_condominio(r: Referencial, nomes: list[str]) -> bool:
    txt = C._n(" ".join((r.titulo, r.descricao, r.bairro, r.link.replace("-", " "))))
    return any(n in txt for n in nomes)


def filtrar_apartamentos(job_id: str, pool: list[Referencial], a: C.Avaliando) -> list[Referencial]:
    """Apartamento (busca pela cidade): fica o do mesmo condomínio; os demais só com área
    ±25% da do avaliando e o mesmo número de quartos (quando os dois são conhecidos)."""
    nomes = nomes_condominio(job_id, a)
    out = []
    for r in pool:
        if mesmo_condominio(r, nomes):
            out.append(r.model_copy(update={"pontos": r.pontos + 5,
                                            "motivo": ("mesmo condomínio, " + r.motivo)[:200]
                                            if "mesmo condom" not in r.motivo else r.motivo}))
            continue
        if a.area and r.area_m2 and abs(r.area_m2 - a.area) / a.area > 0.25:
            continue
        if a.quartos and r.quartos and r.quartos != a.quartos:
            continue
        out.append(r)
    return out


def na_regiao(cartao: dict, cidade: str, a: C.Avaliando) -> bool:
    """ORDEM 009: quando o portal não reconhece o bairro (ex.: Imovelweb com "Vila Brasília
    Continuação, Aparecida de Goiânia") ele devolve anúncios do país inteiro. Fica só o cartão
    que menciona (no texto ou no link) a cidade, o bairro, o condomínio ou um bairro vizinho."""
    alvo = C._n(cartao.get("texto", "") + " " + re.sub(r"[-_/+]", " ", cartao.get("link", "")))
    termos = [cidade, a.bairro, a.condominio or "", *(a.vizinhos or [])]
    for termo in termos:
        n = C._n(termo or "")
        if len(n) >= 4 and n in alvo:
            return True
    return False


MAX_PAGINA_ENVIADA = 40   # ORDEM 019: uma página de resultados enviada pela extensão


def links_de_busca(job_id: str) -> list[dict]:
    """ORDEM 019: páginas de busca de cada portal para o avaliador abrir no Chrome DELE (sem
    robô): [{portal, local, url}]. Mesmas consultas da 1ª rodada da pesquisa."""
    from .. import portais
    t = _comum.trabalho(job_id)
    a = avaliando(job_id)
    consultas, _ = consultas_da_orientacao(t, a, "", set(), True)
    out, vistos = [], set()
    for c in consultas:
        for chave, p in portais.PORTAIS.items():
            if c.portal and c.portal.casefold() not in (chave, p.nome.casefold()):
                continue
            try:
                url = p.url_busca(c)
            except Exception:
                continue
            if url in vistos:
                continue
            vistos.add(url)
            out.append({"portal": p.nome, "local": c.bairro or c.cidade, "url": url})
            # L200 (Caso M): bairro que o portal não conhece dá página 404 (ZAP/Viva Real com "Vila Brasília
            # Continuação") e o portal mostra anúncios de outras cidades; a busca na cidade inteira vai junto
            if c.bairro and chave in ("zap", "vivareal"):
                try:
                    u2 = p.url_busca(c.model_copy(update={"bairro": ""}))
                except Exception:
                    u2 = ""
                if u2 and u2 not in vistos:
                    vistos.add(u2)
                    out.append({"portal": p.nome, "local": c.cidade, "url": u2})
    return out


async def montar_lista(job_id: str, orientacao: str = "",
                      cartoes_enviados: list[tuple[str, dict]] | None = None) -> list[Referencial]:
    """1ª rodada (lista de 10 a 20) ou "Pedir mais" (até 10 novos, sem repetir nem duplicar
    o mesmo imóvel de outro portal). Numeração estável; a reserva guarda o que sobrou.
    ORDEM 019: `cartoes_enviados` = resultados de uma página de busca que o avaliador abriu no
    Chrome dele e mandou pela extensão — entram pelos mesmos filtros e notas, sem Coletor."""
    t = _comum.trabalho(job_id)
    a = avaliando(job_id)
    existentes = db.candidatos(job_id)
    ultima = _ultima_lista(job_id)
    # 1ª lista = ainda nenhum candidato de portal (uma tentativa bloqueada não conta)
    primeira = not any(r.fonte_coleta != "manual" for r in existentes)
    feitas = set(ultima.get("consultas_feitas") or [])
    consultas, filtros = consultas_da_orientacao(t, a, orientacao, feitas, primeira)
    if cartoes_enviados is not None:
        consultas, filtros = [], {}
    # 112: a busca automática nos portais saiu (D-117): os cartões vêm só da página enviada pela extensão;
    # sem ela, "Pedir mais" usa a reserva da última lista
    cartoes: list[tuple[str, dict]] = list(cartoes_enviados or [])
    links = {link_limpo(r.link) for r in existentes}
    imps = {C.impressao(r) for r in existentes if r.area_m2 and r.preco}
    imps3 = {i[:3] for i in imps}          # L200: o cartão cru ainda não tem o bairro (o app completa depois)
    novos: list[Referencial] = []
    fora = 0
    for portal, x in cartoes:
        if not na_regiao(x, t.cidade, a):
            fora += 1
            continue
        r = C.ler_cartao(C.Cartao(link=link_limpo(x["link"]), portal=portal, texto=x.get("texto", "")),
                         t.cidade)
        if r is None or r.link in links or C.impressao(r) in imps:
            continue
        if r.area_m2 and r.preco and not r.bairro and C.impressao(r)[:3] in imps3:
            continue                       # L200 (Caso W): o mesmo imóvel no ZAP e no Viva Real entrava duas vezes
        links.add(r.link)
        imps.add(C.impressao(r))
        if r.area_m2 and r.preco:
            imps3.add(C.impressao(r)[:3])
        novos.append(r)
    if fora:
        db.evento(job_id, "pesquisa", "aviso", f"{pl(fora, 'anúncio de fora da região descartado', 'anúncios de fora da região descartados')}: "
                  "o portal não reconheceu o bairro e devolveu anúncios de outras cidades")
    reserva = [Referencial.model_validate(d) for d in ultima.get("reserva") or []]
    reserva = [r for r in reserva if r.link not in {link_limpo(e.link) for e in existentes}]
    pool = [C.avaliar(r, a) for r in novos + reserva]
    if filtros.get("area_min"):
        pool = [r for r in pool if r.area_m2 and filtros["area_min"] <= r.area_m2 <= filtros["area_max"]]
    if filtros.get("mesma_rua"):
        rua = C._n(_campo_txt(job_id, "logradouro") or _campo_txt(job_id, "endereco")).split(",")[0]
        pool = [r for r in pool if rua and rua[:15] in C._n(r.rua)]
    if "antig" in C._n(orientacao):
        pool = [r.model_copy(update={"pontos": r.pontos + (2 if C._ANTIGO.search(C._texto_util(r)) else 0)})
                for r in pool]
    apto = C.tipologia_classe(a.tipo) == "apartamento" and a.condominio
    if apto:
        pool = filtrar_apartamentos(job_id, pool, a)
    pool = C.ordenar(C.ajustar_pelo_conjunto(existentes + pool, C.tipologia_classe(a.tipo)))
    if apto:   # ORDEM 010: os do mesmo condomínio primeiro
        nomes = nomes_condominio(job_id, a)
        pool = sorted(pool, key=lambda r: not mesmo_condominio(r, nomes))
    pool = [r for r in pool if r.n == 0]          # só os novos (os existentes ficam como estão)
    limite = (MAX_PAGINA_ENVIADA if cartoes_enviados is not None
              else max(10, C.MAX_LISTA - len(existentes)) if primeira else C.MAX_MAIS)
    entram, sobra = pool[:limite], pool[limite:]
    prox = max((r.n for r in existentes), default=0) + 1
    rodada = max((r.rodada for r in existentes), default=0) + 1 if not primeira else 1
    entram = [r.model_copy(update={"n": prox + i, "rodada": rodada}) for i, r in enumerate(entram)]
    ampliou = False
    entram = C.marcar_recomendados(entram, ja=sum(r.recomendado for r in existentes))
    db.salvar_candidatos(job_id, entram)
    db.evento(job_id, "pesquisa", "lista",
              ("página enviada pelo avaliador (Chrome): " if cartoes_enviados is not None else "")
              + f"{'lista' if primeira else 'rodada ' + str(rodada)}: {pl(len(entram), 'candidato novo', 'candidatos novos')}"
              f" (nº {entram[0].n}–{entram[-1].n})" if entram else "nenhum candidato novo",
              dados={"rodada": rodada, "orientacao": orientacao, "ampliou_internet": ampliou,
                     # consulta sem nenhum cartão (portal bloqueado/Coletor fora) não conta
                     "consultas_feitas": sorted(feitas | ({_chave(c) for c in consultas}
                                                          if cartoes else set())),
                     "consultas": [c.model_dump(mode="json") for c in consultas],
                     "novos": [r.n for r in entram],
                     "reserva": [r.model_dump(mode="json") for r in sobra[:60]]})
    exportar(job_id)
    return entram


def reavaliar(job_id: str) -> list[Referencial]:
    """D-056: reavalia a lista inteira (semelhança, porquê, ★ e riscados) e a devolve do mais
    parecido para o menos. Não mexe na decisão do avaliador, no descarte nem nos dados."""
    a = avaliando(job_id)
    refs = db.candidatos(job_id)
    if not refs:
        return []
    novos = []
    for r in refs:
        x = C.avaliar(r.model_copy(update={"recomendado": False, "nao_recomendado": False}), a)
        nota = [o for o in (r.observacao or "").split("; ") if o.startswith("enviado pelo avaliador")]
        obs = "; ".join(dict.fromkeys(nota + [o for o in x.observacao.split("; ") if o]))[:300]
        novos.append(x.model_copy(update={"observacao": obs, "decisao": r.decisao,
                                          "motivo_descarte": r.motivo_descarte}))
    novos = C.marcar_recomendados(C.ordenar(C.ajustar_pelo_conjunto(novos, C.tipologia_classe(a.tipo))))
    db.salvar_candidatos(job_id, novos)
    exportar(job_id)
    db.evento(job_id, "pesquisa", "info", "lista reordenada do mais parecido para o menos parecido, "
                                         "com o porquê de cada um (D-056)")
    return novos


# ------------------------------------------------------------------ D-064 (ORDEM 037-1)
# "O sistema pode pesquisar na internet inteira [...] A preferência é dos portais, mas na
# escassez de referências pode expandir a pesquisa." Com menos de MIN_SEMELHANTES (D-021) a
# busca se amplia para sites de imobiliárias e qualquer site de anúncio.
MIN_SEMELHANTES = 5
_NOME_TIPO = {"galpao": "galpão", "casa": "casa", "apartamento": "apartamento",
              "comercial": "imóvel comercial", "lote": "lote", "sobrado": "sobrado"}


def semelhantes(refs: list[Referencial]) -> int:
    """Candidatos semelhantes que ainda contam (não descartados nem riscados pela regra)."""
    return sum(1 for r in refs if r.decisao != "descarta" and not r.nao_recomendado)


def consulta_internet(job_id: str) -> str:
    """tipologia + bairro/região + cidade + "venda" (a mesma frase no Google do avaliador e na
    busca do Coletor)."""
    t = _comum.trabalho(job_id)
    tip = _tip_busca(t.tipo)
    tip = _NOME_TIPO.get(tip, tip or t.tipo or "imóvel")
    return " ".join(x.strip() for x in (tip, t.bairro, t.cidade, "venda") if x and x.strip())


def url_google(consulta: str) -> str:
    from urllib.parse import quote_plus
    return "https://www.google.com/search?q=" + quote_plus(consulta)


