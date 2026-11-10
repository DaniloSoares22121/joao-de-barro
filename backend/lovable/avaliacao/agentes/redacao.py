"""Agente de Redação: escreve os textos variáveis do laudo (seções, legendas, descrições
das amostras). Números vêm do cálculo determinístico; a montagem é do docx_builder.

Cada seção recebe no prompt o trecho correspondente do P8 (OV) ou do A1 (PTAM) como
exemplo de estilo e profundidade, e um mínimo verificado em código (`deficiencias`): seção
abaixo do mínimo vira aviso grave SECOES_SEM_TEXTO e o orquestrador refaz a redação."""
from __future__ import annotations

import json
import re
import statistics
import unicodedata
from functools import lru_cache

from pydantic import BaseModel

from .. import calculo, conhecimento, db, ia
from ..modelos import Referencial
from . import _comum
from .selecao import Selecao, area_construida

# Seções de texto livre por modalidade (numeração do P1 correspondente). As demais partes
# do laudo são fixas do modelo ou montadas em código (tabelas, valores, anexos).
CHAVES: dict[str, tuple[str, ...]] = {
    "OV": ("1", "5", "6", "7.1", "7.2", "7.3", "7.4", "8", "9", "10"),
    "AM": ("1", "4", "5", "6", "7.1", "7.2", "7.3", "7.4", "8", "9", "10", "11"),
    "AM_GARANTIA": ("1", "4", "5", "6", "7.1", "7.2", "7.3", "7.4", "8", "9", "10", "11"),
    "AMJ": ("1", "4", "5", "6", "7.1", "7.2", "7.3", "7.4", "8", "9", "10", "11", "12"),
}

INSTRUCAO = """\
ETAPA ATUAL: REDAÇÃO DO LAUDO.
Escreva os textos variáveis do laudo, em português formal, no estilo exato dos exemplos A1 e
P8 (laudo final do caso-modelo). Regras:
- "secoes": um texto por chave pedida (numeração do modelo P1 da modalidade). Parágrafos
  separados por linha em branco. Nas seções em tópicos (7.4 descrição; ressalvas
  específicas) escreva uma linha por tópico no formato "Rótulo: texto".
  * "1": parágrafo da finalidade ("A finalidade do presente parecer é ...").
  * "5": metodologia no modelo do P8: Método Comparativo Direto de Dados de Mercado,
    tipologia/padrão dos referenciais, unitário de cada referencial (preço ÷ área), valor =
    área × unitário adotado, faixa de variação, e declaração de que não foram aplicados
    fatores de homogeneização.
  * "4" (AM/AMJ): limitação de uso conforme a P7 §3 para o destino.
  * "6" (opcional): uma linha por documento USADO, no formato
    "Documento | Fornecido por | Data / emissão | Observação" (sem as fotos da vistoria).
  * "7.4": tópicos Tipo, Composição, Estrutura e cobertura, Piso e revestimentos,
    Esquadrias, Fechamento, Benfeitorias fixas incorporadas, Idade aparente, Estado de
    conservação, Padrão construtivo, Topografia — com os itens observados em vistoria;
    omita o que não tiver fonte.
  * seção da pesquisa (introdução): critérios de seleção, nº de candidatos analisados,
    quantos foram excluídos e por quê, data da consulta.
  * seção da determinação do valor: intervalo e média da amostra + justificativa da posição
    do unitário adotado no intervalo pelos diferenciais do imóvel + justificativa da faixa ±
    pela dispersão da amostra (coeficiente de variação informado). Sem a fórmula, que é
    montada em código.
  * seção de ressalvas: só as ressalvas ESPECÍFICAS do imóvel (as genéricas são fixas).
  * AMJ "12": responda os quesitos UM A UM, na ordem dada, no formato
    "Quesito N: <transcrição>" e "Resposta: <resposta objetiva e conclusiva>", cada um em
    parágrafo próprio (linha em branco entre eles). Responda SOMENTE com dados deste laudo
    (campos, vistoria, pesquisa, cálculo). Quesito sem base nesses dados, ou que dependa de
    engenharia (ensaios, patologias, estrutura, normas de desempenho), recebe exatamente
    "Resposta: Prejudicado — fora do escopo da avaliação mercadológica".
    Os dados do processo e a qualificação do perito são montados em código.
- "legendas": arquivo da foto -> legenda curta ("Fachada frontal – vista da rua").
- "descricao_amostras": n do referencial -> descrição curta (tipologia, quartos/suítes,
  diferenciais, padrão/estado; por que é comparável).
- Use SOMENTE dados com origem documento ou vistoria. Nunca invente.
- OV nunca usa a palavra "PTAM". Nunca escreva "sem inspeção de engenharia" nem frases de
  engenharia (D-012).
- Nunca escreva nome de arquivo (ex.: "iptu.pdf", "foto3.jpg") em nenhum texto: cite cada
  documento pelo rótulo dado em "Documentos (rótulos)".
"""

SECOES_SEM_TEXTO = "seções sem texto"

# Nome de cada chave (para exemplos e mínimos) por modalidade.
_NOMES_OV = {"1": "finalidade", "5": "metodologia", "7.1": "localizacao", "7.2": "matricula",
             "7.3": "areas", "7.4": "descricao", "8": "pesquisa", "9": "determinacao",
             "10": "ressalvas"}
_NOMES_AM = {"1": "finalidade", "4": "limitacao", "5": "metodologia", "7.1": "localizacao",
             "7.2": "matricula", "7.3": "areas", "7.4": "descricao", "8": "diagnostico",
             "9": "pesquisa", "10": "determinacao", "11": "ressalvas"}
NOMES: dict[str, dict[str, str]] = {
    "OV": _NOMES_OV, "AM": _NOMES_AM, "AM_GARANTIA": _NOMES_AM,
    "AMJ": {**_NOMES_AM, "12": "quesitos"}}

_NUMERO = (r"\b(\d+|um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|"
           r"treze|quatorze|catorze|quinze|dezesseis|dezessete|dezoito|dezenove|vinte)\b")
# Mínimos por seção: (caracteres, [(regex obrigatório, o que falta)]). Medidos no P8/A1:
# a metodologia do P8 tem ~7 linhas (~640 caracteres); 6 linhas ≈ 520.
MINIMOS: dict[str, tuple[int, list[tuple[str, str]]]] = {
    "finalidade": (120, []),
    "metodologia": (520, [
        (r"comparativo direto", "citar o Método Comparativo Direto de Dados de Mercado"),
        (r"[aá]rea", "explicar o valor = área × unitário adotado"),
        (r"unit[aá]rio", "explicar o valor unitário (preço ÷ área) dos referenciais"),
        (r"homogeneiza", "declarar que não foram aplicados fatores de homogeneização")]),
    "localizacao": (250, []),
    "matricula": (100, []),
    "diagnostico": (250, []),
    "pesquisa": (250, [
        (r"crit[eé]rio|selecionad", "declarar os critérios de seleção"),
        (_NUMERO, "informar o nº de candidatos analisados"),
        (r"exclu|descart", "informar os excluídos e por quê")]),
    "determinacao": (450, [
        (r"unit[aá]rio", "justificar o unitário adotado"),
        (r"interval|entre|limite|m[eé]dia|faixa", "situar o unitário no intervalo da amostra"),
        (r"dispers|coeficiente de varia", "justificar a faixa ± pela dispersão (coeficiente "
                                          "de variação) da amostra")]),
}
MIN_TOPICOS_DESCRICAO = 6
_TOPICO = re.compile(r"^\s*[-•*]?\s*[^:\n]{2,40}:\s+\S")


@lru_cache(maxsize=1)
def exemplos() -> dict:
    """Trechos do P8 (OV) e do A1 (PTAM), anonimizados (assets/conhecimento)."""
    return json.loads((conhecimento.PASTA / "exemplos_secoes.json").read_text(encoding="utf-8"))


# ------------------------------------------------- fatos do exemplo copiados (B1)
# Fatos do caso-modelo (P8/A1) que já apareceram copiados em laudos de outros imóveis.
FATOS_EXEMPLO = ("metalon", "sobre pilares", "30 anos", "4 vagas", "Jardim Vila Boa",
                 "das Acácias")
FATO_COPIADO = "fato do exemplo copiado"
# Siglas/termos institucionais que qualquer laudo usa (não são fatos do caso-modelo).
_SIGLAS_COMUNS = {"cep", "iptu", "quadra", "lote", "d.o.u", "cofeci", "creci", "resolucoes",
                  "resolucao", "conselho", "federal", "corretores", "comarca", "circunscricao",
                  "cartorio", "registro", "goiania", "goiania/go", "go", "lei", "nbr", "abnt"}
_PALAVRA = re.compile(r"[\wÀ-ÿ/,.%-]+")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.casefold().split())


def _tokens(txt: str) -> list[str]:
    return [t.strip(",.;:") for t in _PALAVRA.findall(txt or "") if t.strip(",.;:")]


def _distintivo(tok: str, inicio: bool) -> bool:
    """Número ou nome próprio (maiúscula fora do início de frase). Anos e datas antigas
    (citações de lei/resolução) não contam."""
    if re.fullmatch(r"(?:\d{1,2}/\d{1,2}/)?(?:19\d\d|200\d|201\d)", tok):
        return False
    return bool(re.search(r"\d", tok)) or (not inicio and tok[:1].isupper() and len(tok) > 2)


@lru_cache(maxsize=1)
def _ngramas_raros() -> dict[str, tuple[str, ...]]:
    """3-gramas (normalizados) que aparecem uma única vez nos exemplos, têm número ou nome
    próprio e não estão nos textos gerais da base (P0/P3/P6/P7) nem na instrução ->
    tokens distintivos do 3-grama."""
    ex = exemplos()
    palavras = [_norm(t) for t in _tokens(
        conhecimento.texto("P0", "P3", "P6", "P7") + " " + INSTRUCAO)]
    comum, vocab = " " + " ".join(palavras) + " ", set(palavras)
    # palavra escrita em minúscula em algum exemplo é palavra comum, não nome próprio
    vocab |= {_norm(t) for g in ("OV", "PTAM") for v in ex[g].values()
              for t in _tokens(v) if t[:1].islower()} | _SIGLAS_COMUNS
    cont: dict[str, int] = {}
    dist: dict[str, tuple[str, ...]] = {}
    for g in ("OV", "PTAM"):
        for v in ex[g].values():
            for frase in re.split(r"(?<=[.;:!?])\s+|\n+", v):
                toks = _tokens(frase)
                for i in range(len(toks) - 2):
                    tri = toks[i:i + 3]
                    if any("[" in t or "]" in t for t in tri):
                        continue
                    d = tuple(t for j, t in enumerate(tri) if _distintivo(t, i + j == 0)
                              and _norm(t) not in vocab)
                    if not d:
                        continue
                    k = _norm(" ".join(tri))
                    cont[k] = cont.get(k, 0) + 1
                    dist[k] = d
    return {k: dist[k] for k, n in cont.items() if n == 1 and f" {k} " not in comum}


def _canon(s: str) -> str:
    """Normaliza para comparar com as fontes: datas ISO -> dd/mm/aaaa e números pt-BR
    (1.234,56) -> 1234.56."""
    s = _norm(s)
    s = re.sub(r"(\d{4})-(\d{2})-(\d{2})", lambda m: f"{m[3]}/{m[2]}/{m[1]}", s)
    s = re.sub(r"(?<=\d)\.(?=\d{3}(?!\d))", "", s)
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)
    s = re.sub(r"(?<=\d)\.0+(?!\d)", "", s)       # 10,00 -> 10
    return re.sub(r"(?<=\d)/m2", "", s)            # 2.735,85/m² -> 2735.85


def fatos_copiados(texto: str, fontes: str) -> list[str]:
    """Trechos distintivos dos exemplos presentes no texto gerado mas ausentes das fontes do
    trabalho (dados, campos, vistoria, pesquisa e cálculo)."""
    t, f = _norm(texto), _canon(fontes)
    t_pad = f" {' '.join(_norm(x) for x in _tokens(texto))} "
    achados: list[str] = []
    for fato in FATOS_EXEMPLO:
        nf = _norm(fato)
        if re.search(rf"\b{re.escape(nf)}\b", t) and _canon(fato) not in f:
            achados.append(fato)
    for k, dist in _ngramas_raros().items():
        if f" {k} " in t_pad and not all(_canon(d) in f for d in dist):
            if not any(_norm(a) in k or k in _norm(a) for a in achados):
                achados.append(k)
    return achados


def _exemplo(modalidade: str, nome: str) -> str:
    ex = exemplos()
    for g in (("OV", "PTAM") if modalidade == "OV" else ("PTAM", "OV")):
        if ex[g].get(nome):
            return f"[{'P8' if g == 'OV' else 'A1'}] {ex[g][nome]}"
    return ""


def _minimo_txt(nome: str) -> str:
    if nome == "descricao":
        return (f"pelo menos {MIN_TOPICOS_DESCRICAO} tópicos \"Rótulo: texto\" com os itens "
                "observados em vistoria")
    if nome == "quesitos":
        return "todos os quesitos, um a um (\"Quesito N: ...\" + \"Resposta: ...\")"
    m = MINIMOS.get(nome)
    if not m:
        return ""
    exig = "; ".join(o for _, o in m[1])
    return f"pelo menos {m[0]} caracteres" + (f"; obrigatório: {exig}" if exig else "")


def guia_secoes(modalidade: str) -> str:
    """Bloco do prompt: por seção, o exemplo de estilo (P8/A1) e o mínimo exigido."""
    linhas = ["GUIA POR SEÇÃO (exemplos reais de estilo e profundidade — dados entre colchetes "
              "foram anonimizados; nunca copie dados do exemplo):"]
    for k in CHAVES[modalidade]:
        nome = NOMES[modalidade].get(k, "")
        ex, mi = _exemplo(modalidade, nome), _minimo_txt(nome)
        if not (ex or mi):
            continue
        linhas.append(f"\n### Seção \"{k}\" ({nome})")
        if mi:
            linhas.append(f"Mínimo: {mi}.")
        if ex:
            linhas.append("Exemplo (os fatos do exemplo NÃO pertencem a este imóvel — use "
                          "só os dados deste trabalho):\n" + ex)
    return "\n".join(linhas)


# D-012: termos de engenharia que não cabem numa avaliação mercadológica (quesitos AMJ).
TERMOS_ENGENHARIA = re.compile(
    r"\bensaios?\b|fissuras?\s+estrutura\w*|laudo\s+de\s+engenharia|patologias?\s+construtivas?|"
    r"NBR\s*(?:de\s+desempenho|15\.?575)|norma\s+de\s+desempenho|\bsondage\w*|"
    r"inspe[cç][aã]o\s+predial|recalques?\s+de\s+funda\w*|prova\s+de\s+carga", re.I)
PREJUDICADO = "Prejudicado — fora do escopo da avaliação mercadológica"


def deficiencias(modalidade: str, secoes: dict[str, str],
                 quesitos: list[str] | tuple = (), fontes: str | None = None) -> list[str]:
    """Seções ausentes ou abaixo do mínimo, no formato "<chave> (<nome>): <motivo>".
    Com `fontes` (dados do trabalho), também os fatos do exemplo copiados no texto."""
    out = []
    for k in CHAVES[modalidade]:
        if k == "6":
            continue
        nome = NOMES[modalidade].get(k, k)
        txt = (secoes.get(k) or "").strip()
        if not txt:
            out.append(f"{k} ({nome}): sem texto")
            continue
        if nome == "descricao":
            n = sum(1 for ln in txt.splitlines() if _TOPICO.match(ln))
            if n < MIN_TOPICOS_DESCRICAO:
                out.append(f"{k} ({nome}): {n} tópico(s), mínimo {MIN_TOPICOS_DESCRICAO}")
            continue
        if nome == "quesitos":
            resp = len(re.findall(r"^\s*Resposta\s*:", txt, re.I | re.M))
            falta = [str(i) for i in range(1, len(quesitos) + 1)
                     if not re.search(rf"Quesito\s+{i}\b", txt, re.I)]
            if falta or resp < len(quesitos):
                out.append(f"{k} ({nome}): quesitos sem resposta: {', '.join(falta) or '?'}")
            respostas = " ".join(re.findall(r"^\s*Resposta\s*:(.*)$", txt, re.I | re.M))
            termos = sorted({m.group(0) for m in TERMOS_ENGENHARIA.finditer(respostas)})
            if termos:
                out.append(f"{k} ({nome}): termo de engenharia na resposta (D-012): "
                           f"{', '.join(termos)}; sem base no laudo responda \"{PREJUDICADO}\"")
            continue
        m = MINIMOS.get(nome)
        if not m:
            continue
        falta = [o for rx, o in m[1] if not re.search(rx, txt, re.I)]
        if len(txt) < m[0]:
            falta.insert(0, f"{len(txt)} caracteres, mínimo {m[0]}")
        if falta:
            out.append(f"{k} ({nome}): " + "; ".join(falta))
    if fontes is not None:
        for k in CHAVES[modalidade]:
            achados = fatos_copiados(secoes.get(k) or "", fontes)
            if achados:
                out.append(f"{k} ({NOMES[modalidade].get(k, k)}): {FATO_COPIADO} (não consta "
                           "dos dados deste imóvel; remova): "
                           + "; ".join(f'"{a}"' for a in achados[:5]))
    return out


class Textos(BaseModel):
    secoes: dict[str, str] = {}
    legendas: dict[str, str] = {}
    descricao_amostras: dict[int, str] = {}
    faltas: list[str] = []  # preenchido em código: seções abaixo do mínimo (provoca volta)


def dispersao(unitarios) -> tuple[float, float, str]:
    """(desvio padrão amostral, coeficiente de variação %, grau) dos valores unitários."""
    us = [float(u) for u in unitarios]
    media = statistics.fmean(us) if us else 0.0
    dp = statistics.stdev(us) if len(us) > 1 else 0.0
    cv = dp / media * 100 if media else 0.0
    return dp, cv, "baixa" if cv <= 15 else ("moderada" if cv <= 30 else "elevada")


def _resumo_calculo(job_id: str, sel: Selecao | None) -> str:
    if sel is None:
        return "(seleção ainda não disponível)"
    escolhidos: list[Referencial] = [r for r in sel.refs if r.escolhido]
    area = area_construida(job_id)
    linhas = ["Referenciais escolhidos:"] + [
        r.model_dump_json(exclude={"foto", "print_"}) for r in escolhidos]
    excl = [r for r in sel.refs if not r.escolhido]
    linhas.append(f"Candidatos analisados: {len(sel.refs)}; escolhidos: {len(escolhidos)}; "
                  f"excluídos: {len(excl)}.")
    for r in excl:
        linhas.append(f"- excluído n {r.n} ({r.bairro}, {r.tipologia}): "
                      f"{r.justificativa or 'sem justificativa registrada'}")
    if sel.declaracao_amostra:
        linhas.append("Declaração da amostra: " + sel.declaracao_amostra)
    if area is not None and escolhidos:
        try:
            r = calculo.calcular(area, escolhidos, sel.unitario_adotado, sel.faixa_pct)
            dp, cv, grau = dispersao(r.unitarios)
            linhas.append(
                f"Cálculo: área {area} m²; unitários {[str(u) for u in r.unitarios]}; mínimo "
                f"{r.minimo}; máximo {r.maximo}; média {r.media}; unitário adotado "
                f"{r.unitario_adotado}; valor calculado {r.valor_calculado}; valor adotado "
                f"{r.valor_adotado}; faixa ±{r.faixa_pct}%.")
            linhas.append(
                f"Dispersão (calculada em código): desvio padrão {dp:.2f}; coeficiente de "
                f"variação {cv:.2f}% ({grau} dispersão). Use-o para justificar a faixa "
                f"±{r.faixa_pct}% na seção da determinação do valor.")
        except ValueError as e:
            linhas.append(f"Cálculo indisponível: {e}")
    if sel.justificativa_unitario:
        linhas.append("Justificativa do unitário (seleção): " + sel.justificativa_unitario)
    return "\n".join(linhas)


async def rodar(job_id: str) -> Textos:
    t = _comum.trabalho(job_id)
    chaves = CHAVES[t.modalidade]
    campos = [c.model_dump(mode="json") for c in db.campos(job_id)
              if c.origem in ("documento", "vistoria")]
    ext = db.resultado(job_id, "extracao") or {}
    sel_d = db.resultado(job_id, "selecao")
    sel = Selecao.model_validate(sel_d) if sel_d else None
    sistema = (conhecimento.texto("P0", "P3", "P6", "P7", "A1", "P8") + "\n\n" + INSTRUCAO
               + "\n\n" + guia_secoes(t.modalidade))
    anterior = carregar(job_id)
    quesitos = list(getattr(t, "quesitos", None) or [])
    prompt = (
        "Trabalho:\n" + t.model_dump_json(indent=2, exclude={"contexto"})
        + f"\n\nModalidade {t.modalidade}; chaves de 'secoes' pedidas: {list(chaves)}"
        + f"\n\nCampos do imóvel (documento/vistoria):\n{campos}"
        + f"\n\nFotos da vistoria: {ext.get('fotos', [])}"
        + f"\nDivergências documentais: {ext.get('divergencias', [])}"
        + "\nDocumentos (rótulos — use estes, nunca o nome do arquivo): "
        + str([{"rotulo_curto": d.get("rotulo_curto", ""),
                "rotulo_completo": d.get("rotulo_completo", "")}
               for d in ext.get("documentos") or []])
        + "\n\n" + _resumo_calculo(job_id, sel)
        + db.texto_correcoes(job_id, "redacao"))
    if quesitos:
        prompt += "\n\nQuesitos (responda um a um na seção \"12\"):\n" + "\n".join(
            f"Quesito {i}: {q}" for i, q in enumerate(quesitos, start=1))
    if anterior is not None and anterior.faltas:
        prompt += ("\n\nA VERSÃO ANTERIOR FICOU ABAIXO DO MÍNIMO nestas seções (corrija):\n"
                   + "\n".join(f"- {f}" for f in anterior.faltas))
    r: Textos = await ia.perguntar(sistema, prompt, Textos)
    fontes = "\n".join([t.model_dump_json(), json.dumps(campos, ensure_ascii=False, default=str),
                        json.dumps(ext, ensure_ascii=False, default=str),
                        _resumo_calculo(job_id, sel)])
    r.faltas = deficiencias(t.modalidade, r.secoes, quesitos, fontes=fontes)
    if r.faltas:
        db.evento(job_id, "redacao", "aviso", f"{SECOES_SEM_TEXTO}: {'; '.join(r.faltas)}")
    db.evento(job_id, "redacao", "resultado", f"{len(r.secoes)} seções redigidas",
              dados=r.model_dump(mode="json"))
    return r


def carregar(job_id: str) -> Textos | None:
    d = db.resultado(job_id, "redacao")
    return Textos.model_validate(d) if d else None
