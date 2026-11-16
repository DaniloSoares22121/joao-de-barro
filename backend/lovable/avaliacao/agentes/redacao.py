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
from . import selecao as selecao_mod
from .selecao import Selecao, area_construida
from ..plural import pl

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
  * "1": UM parágrafo da finalidade ("A finalidade do presente parecer é ..."). NÃO escreva a
    definição de valor de mercado ("Entende-se por valor de mercado..."): ela já é fixa no
    modelo e sairia duplicada.
  * "5" (OV): SOMENTE o trecho que descreve os referenciais, para completar a frase fixa do
    modelo P1-OV "...a partir de ofertas de imóveis semelhantes – <TRECHO> – localizados na
    mesma região...". Ex.: "sobrados residenciais de padrão construtivo simples e construção
    antiga" (sem ponto final, até 160 caracteres). O resto da metodologia é fixo.
  * "5" (AM/AMJ): metodologia no modelo do A1: Método Comparativo Direto de Dados de
    Mercado, tipologia/padrão dos referenciais, unitário de cada referencial (preço ÷ área),
    valor = área × unitário adotado, faixa de variação, e declaração de que não foram
    aplicados fatores de homogeneização.
  * "4" (AM/AMJ): SÓ o parágrafo da limitação de uso conforme a P7 §3 para o destino. As
    referências normativas (Res. 1.066/2007, Ato 001/2011, NBR 14653-1 como referência
    técnica) JÁ SÃO FIXAS no modelo: não as repita.
  * "6" (opcional): uma linha por documento USADO, no formato
    "Documento | Fornecido por | Data / emissão | Observação" (sem as fotos da vistoria).
    UM DOCUMENTO POR LINHA: várias fotos/páginas do mesmo documento (ex.: 2 fotos da
    escritura) são UMA linha ("Escritura pública – 2 imagens"). "Data / emissão" só com a
    data (dd/mm/aaaa) ou "—"; qualquer explicação vai na Observação.
  * "7.4": tópicos Tipo, Composição, Estrutura e cobertura, Piso e revestimentos,
    Esquadrias, Fechamento, Benfeitorias fixas incorporadas, Idade aparente, Estado de
    conservação, Padrão construtivo, Topografia — com os itens observados em vistoria;
    omita o que não tiver fonte. OV: NO MÁXIMO 8 tópicos (D-039) — junte "Idade aparente e
    estado de conservação" e "Padrão construtivo e topografia" se precisar. O tópico
    "Benfeitorias fixas incorporadas" lista o que houver (ex.: sistema fotovoltaico, ar-
    condicionado, garagem para N vagas, edícula): o RESUMO do laudo é montado a partir dele.
    Nada de afirmação negativa ("sem móveis planejados", "sem piscina") que não esteja nos
    dados da vistoria.
  * "7.2" e "anexo4" — VÍNCULO do solicitante com o titular (P0 itens 7/10, P6 A): quando
    solicitante ≠ titular e um DOCUMENTO mostra a relação (filiação na CNH/RG/OAB, certidão,
    procuração), o 7.2 registra o vínculo e "anexo4" traz UMA frase, no modelo: "A solicitante
    consta como filha de <TITULAR>, titular do cadastro municipal do imóvel, conforme
    filiação registrada nos documentos de identificação apresentados." Sem documento que
    mostre o vínculo (ex.: empresa contratante), D-030: "anexo4" vazio e não afirmar vínculo.
  * seção da pesquisa (introdução): critérios de seleção, nº de candidatos analisados,
    quantos foram excluídos e por quê, data da consulta.
  * seção da determinação do valor: 2 parágrafos. (1) "Os N referenciais apresentaram
    valores unitários entre R$ mín./m² e R$ máx./m², com média de R$ X/m²." (2) "Considerando
    o comportamento dos imóveis pesquisados e as características do bem avaliando –
    <diferenciais comprovados> –, adota-se o valor unitário de R$ <UNITÁRIO ADOTADO>/m²,
    <posição no intervalo e justificativa>, sem ultrapassar os limites observados para
    imóveis de padrão semelhante." Use EXATAMENTE a frase "adota-se o valor unitário de
    R$ .../m²" com o unitário adotado informado. Sem a fórmula e sem a faixa (montadas em
    código). OV: NÃO cite mediana, desvio padrão nem coeficiente de variação (D-039).
    TODA modalidade (D-068, regra do projeto): NUNCA escreva sobre dispersão, espalhamento, heterogeneidade,
    variabilidade ou variação entre os valores dos referenciais, nem cite coeficiente de variação ou desvio padrão,
    nem remeta à planilha para isso. A faixa ± é declarada como "faixa de variação mercadológica admitida".
  * seção de ressalvas: só as ressalvas ESPECÍFICAS do imóvel (no máximo 2 em OV). As
    genéricas JÁ ESTÃO no modelo e não podem ser repetidas nem reescritas: documentação
    considerada verdadeira e de boa-fé; áreas extraídas dos documentos/divergências de
    medição; atualização do valor após 90 dias.
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
- L201-4: cômodo contado pelas FOTOS (quartos, banheiros) é "ao menos N" — nunca menos do que as fotos mostram — e
  NUNCA serve de justificativa (ajuste, semelhança, item 9). Se a contagem for duvidosa, escreva "conferir a
  contagem na revisão". Legenda "Fachada" só em foto que mostra a fachada pela rua (hall, portaria por dentro e
  áreas internas têm a legenda do que mostram).
- PRAZO, NÚMERO OU DATA SÓ COM FONTE (Instruções §2.1): um documento do trabalho, norma
  confirmada na P4 ou decisão do P3. Sem fonte, a frase SAI — ex.: nada de "certidão com
  validade de 30 dias" se nenhum documento diz isso. (A atualização após 90 dias acima tem
  fonte: é o padrão do avaliador.)
- Referências normativas SÓ as confirmadas na P4: Lei 6.530/78, Res. COFECI 1.066/2007, Ato
  Normativo COFECI 001/2011 e NBR 14653-1:2019 só como referência técnica. PROIBIDO citar a
  Res. COFECI 957/2006 (revogada, D-001) e o "item 3.34" da NBR 14653-1 (D-008), mesmo que o
  exemplo A1 os cite. CPC (Lei 13.105/2015, art. 473; P4 N7): SÓ no AMJ — metodologia (III:
  método predominantemente aceito pelos especialistas) e quesitos (IV: respostas
  conclusivas). OV e AM NUNCA citam o CPC.
- Informação verbal do contratante (contexto: reforma, venda de vizinho, preço pretendido)
  NUNCA entra no laudo nem justifica o valor (D-013).
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
        (r"interval|entre|limite|m[eé]dia|faixa", "situar o unitário no intervalo da amostra")]),   # 106: sem dispersão
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
                 "das Acácias", "móveis planejados", "3,40 m")
FATO_COPIADO = "fato do exemplo copiado"
# Citações confirmadas na P4 (aparecem nos exemplos, mas não são "fato do exemplo")
CITACOES_NORMATIVAS = ("Lei nº 6.530, de 12 de maio de 1978 (D.O.U. de 15/05/1978); Resolução COFECI "
                       "nº 1.066, de 22 de novembro de 2007; Ato Normativo COFECI nº 001/2011; "
                       "ABNT NBR 14653-1:2019; Lei nº 13.105/2015 (Código de Processo Civil), "
                       "art. 473, III e IV (só AMJ)")
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
        conhecimento.texto("P0", "P3", "P6", "P7", "K0") + " " + INSTRUCAO)]
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
        if modalidade == "OV" and nome == "metodologia":
            ex, mi = "", ("SÓ o trecho dos referenciais (até 160 caracteres), ex.: "
                          "\"sobrados residenciais de padrão construtivo simples e construção "
                          "antiga\"")
        if modalidade == "OV" and nome == "determinacao":
            mi = mi.replace("; justificar a faixa ± pela dispersão (coeficiente de variação) "
                            "da amostra", "") + '; frase "adota-se o valor unitário de R$ .../m²"; sem CV/desvio/mediana'
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
                out.append(f"{k} ({nome}): {pl(n, 'tópico', 'tópicos')}, mínimo {MIN_TOPICOS_DESCRICAO}")
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
        if modalidade == "OV" and nome == "metodologia":
            # OV: só o trecho dos referenciais, encaixado na frase fixa do P1-OV
            if len(txt) > 200 or "\n" in txt.strip():
                out.append(f"{k} ({nome}): na OV escreva só o trecho dos referenciais "
                           f"(até 160 caracteres, uma linha); veio com {len(txt)}")
            continue
        m = MINIMOS.get(nome)
        if not m:
            continue
        exig = m[1]
        if modalidade == "OV" and nome == "determinacao":
            # D-039: OV sem dispersão; exige a frase do D-018
            exig = [e for e in exig if "dispers" not in e[0]] + [
                (r"adota-se o valor unit[aá]rio de R\$", 'usar a frase "adota-se o valor '
                                                          'unitário de R$ .../m²"')]
        if nome == "pesquisa" and fontes and re.search(r"exclu[ií]dos: 0\b", fontes):
            exig = [e for e in exig if "excluídos" not in e[1]]      # 102-8: sem excluídos, não há o que informar
        if nome == "determinacao" and fontes and db.cv_so_na_planilha_txt(fontes):
            exig = [e for e in exig if "dispers" not in e[0]]        # D-068: a conta da dispersão fica na planilha
        falta = [o for rx, o in exig if not re.search(rx, txt, re.I)]
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


def _instrucao_objeto(job_id: str) -> list[str]:
    """ORDEM 032-2 (D-059): objeto = parte do imóvel -> descrever sem ambiguidade."""
    parte = selecao_mod._parte(job_id)
    if not parte:
        return []
    return [f"OBJETO (obrigatório, D-059): o objeto desta avaliação é SÓ \"{parte}\", parte do imóvel. "
            "Diga isso na identificação (item 7), na descrição e no resumo. O lote/terreno inteiro é "
            "CONTEXTO (localização, documentos); o valor é o da parte. Nunca escreva como se o valor "
            "fosse do lote inteiro."]


def _instrucao_areas(job_id: str) -> list[str]:
    """ORDEM 029-4 (D-027, D-059): área do objeto medida por satélite -> o 7.3 e a ressalva dizem
    isso e citam a área edificada cadastral do lote inteiro, que NÃO é a do cálculo."""
    esc = selecao_mod.escolha_area(job_id)
    if not esc or esc.get("base") != "construida" or esc.get("origem") == "documento":
        return []
    c = next((x for x in db.campos(job_id) if x.nome == esc.get("campo")), None)
    if c is None or not re.search(r"(?i)sat[ée]lite|google|medi[dç]", f"{c.nome} {c.fonte or ''}"):
        return []
    doc = next((x for x in selecao_mod.opcoes_area(job_id)["construida"] if x["origem"] == "documento"), None)
    ref = (f"; o cadastro municipal traz a área edificada do lote inteiro ({selecao_mod._br(doc['valor'])} m²), "
           "que NÃO é a do cálculo") if doc else ""
    return [f"ÁREAS (obrigatório no 7.3 e na ressalva do item de pressupostos): a área do cálculo é a "
            f"{c.nome.lower()} = {selecao_mod._br(float(esc['valor']))} m², medida por imagem de satélite "
            f"(Google Maps), com o print no item 7.3{ref}. Escreva isso com essas palavras; nunca diga que a "
            "área adotada vem do cadastro ou dos documentos."]


def _resumo_calculo(job_id: str, sel: Selecao | None, modalidade: str = "") -> str:
    if sel is None:
        return "(seleção ainda não disponível)"
    escolhidos: list[Referencial] = [r for r in sel.refs if r.escolhido]
    area = area_construida(job_id)
    linhas = ["Referenciais escolhidos:"] + [
        r.model_dump_json(exclude={"foto", "print_"}) for r in escolhidos]
    # 100-6: "só comparação" não é excluído: é apresentado à parte (item de comparação, D-069)
    comp = [r for r in sel.refs if not r.escolhido and getattr(r, "decisao", "") == "comparacao"]
    excl = [r for r in sel.refs if not r.escolhido and getattr(r, "decisao", "") != "comparacao"]
    linhas.append(f"Candidatos analisados: {len(sel.refs)}; escolhidos: {len(escolhidos)}; "
                  f"excluídos: {len(excl)}"
                  + (f"; apresentados apenas como referência comparativa no item de comparação (fora da amostra): "
                     f"{len(comp)} — nunca os chame de excluídos." if comp else "."))
    for r in excl:
        linhas.append(f"- excluído n {r.n} ({r.bairro}, {r.tipologia}): "
                      f"{r.justificativa or 'sem justificativa registrada'}")
    if sel.declaracao_amostra:
        linhas.append("Declaração da amostra: " + sel.declaracao_amostra)
    if area is not None and escolhidos:
        try:
            base = selecao_mod.base_area(job_id)
            linhas += _instrucao_areas(job_id)
            linhas += _instrucao_objeto(job_id)
            r = calculo.calcular(area, selecao_mod.refs_na_base(job_id, escolhidos, base),
                                 selecao_mod.unitario_valido(sel)[0], sel.faixa_pct)
            dp, cv, grau = dispersao(r.unitarios)
            linhas.append(
                f"BASE DO CÁLCULO escolhida pelo avaliador: {selecao_mod.ROTULO_BASE[base]} "
                f"(unitário = preço ÷ {selecao_mod.ROTULO_BASE[base]} de cada referencial). No texto "
                f"da determinação do valor escreva \"{selecao_mod.ROTULO_BASE[base]}\"; nunca a outra.")
            linhas.append(
                f"Cálculo: {selecao_mod.ROTULO_BASE[base]} {area} m²; unitários {[str(u) for u in r.unitarios]}; mínimo "
                f"{r.minimo}; máximo {r.maximo}; média {r.media}; unitário adotado "
                f"{r.unitario_adotado}; valor calculado {r.valor_calculado}; valor adotado "
                f"{r.valor_adotado}; faixa ±{r.faixa_pct}%.")
            # 106-1 (D-068, regra do projeto): a dispersão nunca vai ao texto — nem o número entra na redação
        except ValueError as e:
            linhas.append(f"Cálculo indisponível: {e}")
    u_ok = selecao_mod.unitario_valido(sel)[0]
    if u_ok is not None and sel.justificativa_unitario:
        linhas.append("Justificativa do unitário, ESCRITA PELO AVALIADOR (use só esta): " + sel.justificativa_unitario)
    else:
        linhas.append("O unitário adotado é a MÉDIA da amostra. Nunca escreva justificativa para adotar outro "
                      "unitário nem argumento para manter um valor (082-4).")
    return "\n".join(linhas)


def datas_dos_documentos(job_id: str) -> dict[str, str]:
    """077-4: a data de cada documento lida na conversa do cliente (tipo → data), para a tabela da seção 6."""
    from .. import tela_trabalho
    cli = tela_trabalho._cliente(job_id)
    out: dict[str, str] = {}
    for d in ((cli or {}).get("contexto") or {}).get("docs") or []:
        if d.get("data") and d.get("tipo"):
            out[f"{d['tipo']} ({d.get('arquivo', '')})"] = d["data"]
    return out


async def rodar(job_id: str) -> Textos:
    t = _comum.trabalho(job_id)
    chaves = CHAVES[t.modalidade]
    campos = [c.model_dump(mode="json") for c in db.campos(job_id)
              if c.origem in ("documento", "vistoria")]
    ext = db.resultado(job_id, "extracao") or {}
    sel_d = db.resultado(job_id, "selecao")
    sel = Selecao.model_validate(sel_d) if sel_d else None
    # A1/P8 = laudos do Alan (exemplo de redação dele): só na camada do Alan, nunca na base comum
    sistema = (conhecimento.base(job_id, ("P0", "P3", "P6", "P7", "P9", "A1", "P8"),
                                 ("redação", "documentos", "áreas", "cálculo", "fotos")) + "\n\n" + INSTRUCAO
               + "\n\n" + guia_secoes(t.modalidade))
    anterior = carregar(job_id)
    quesitos = list(getattr(t, "quesitos", None) or [])
    prompt = (
        "Trabalho:\n" + t.model_dump_json(indent=2, exclude={"contexto"})
        + f"\n\nModalidade {t.modalidade}; chaves de 'secoes' pedidas: {list(chaves)} "
          "+ \"anexo4\" (frase do vínculo do solicitante, ou vazio)"
        + f"\n\nCampos do imóvel (documento/vistoria):\n{campos}"
        + f"\n\nFotos da vistoria: {ext.get('fotos', [])}"
        + f"\nDivergências documentais: {ext.get('divergencias', [])}"
        + "\nDocumentos (rótulos — use estes, nunca o nome do arquivo): "
        + str([{"rotulo_curto": d.get("rotulo_curto", ""),
                "rotulo_completo": d.get("rotulo_completo", "")}
               for d in ext.get("documentos") or []])
        + "\n\n" + _resumo_calculo(job_id, sel, t.modalidade)
        + db.texto_correcoes(job_id, "redacao"))
    # 077-A4: características enumeradas viram lista (uma por linha), nunca hífens dentro do parágrafo
    prompt += ("\n\nFORMA: nunca enumere com hífens dentro de um parágrafo; enumeração vira lista, um item por linha. "
               "Concordância: \"o presente parecer\". Entidade: \"CEP-SINDIMÓVEIS/GO\".")
    # 078: regras do João para o texto (o conferidor do próprio JdB cobra cada uma)
    from .. import tela_trabalho as _tt
    cctx = ((_tt._cliente(job_id) or {}).get("contexto") or {})
    regras = [
        "Item 12 (resumo): no estado de conservação entra SÓ a classificação (ex.: \"Entre regular e necessitando de reparos simples\"), nunca frase que termina em dois-pontos.",
        "Item 7.4: os pontos observados são SUBITENS de \"Estado de conservação\"; a frase final (ex.: \"As demais áreas…\") é texto, não tópico.",
        "Não repita a mesma informação sobre os candidatos analisados em duas frases seguidas. Cite o \"dossiê de pesquisa\" só se ele existir.",
        "Determinação do valor (D-074): não cite o maior e o menor unitário; explique o que é a média aritmética, mostre a conta com os unitários e a base (NBR 14653-1:2019 como referência técnica, Res. COFECI 1.066/2007 e Ato Normativo 001/2011, sem número de item) e diga POR QUE não houve homogeneização (mesma tipologia, padrão, composição e idade aparente).",
        "Ressalvas (090-9): sem certidão atualizada da matrícula, nunca escreva que o valor considera o imóvel livre de ônus; a ressalva é a de que a certidão atualizada não foi apresentada.",
        "ITCD / malha fiscal (093-1): no diagnóstico de mercado e na legenda do anexo do comunicado, cite COM OS NÚMEROS dos campos o valor declarado, o valor de referência da SEFAZ e o valor médio FIPE, quando estiverem nos campos.",
        "D-068 (regra do projeto, toda modalidade): NENHUMA frase sobre dispersão, espalhamento, heterogeneidade, variabilidade, amplitude ou discrepância entre os valores dos referenciais, com ou sem número, nem remetendo à planilha. 'Mercado raso' (poucas ofertas) pode. A faixa ± é a 'faixa de variação mercadológica admitida'.",
        "Descrição dos referenciais (082-6): nunca escreva nome nem CRECI de anunciante, corretor ou imobiliária; diga por que o imóvel é comparável.",
        "Endereço: use a grafia do documento do imóvel (ex.: \"Rua XV 9\") e a MESMA no laudo inteiro.",
    ]
    if cctx.get("estado_conservacao"):      # 085-3: a classificação é a do avaliador (letra da Ross-Heidecke)
        regras.append(f"Estado de conservação: use EXATAMENTE a classificação do avaliador: \"{cctx['estado_conservacao']}\". "
                      "Pode citar o que as fotos mostram, mas nunca troque a classificação.")
    if cctx.get("pontos_negativos"):        # 085-2: o que o avaliador apontou entra na localização e no diagnóstico
        regras.append("Pontos negativos informados pelo avaliador (entram na situação/localização E no diagnóstico de mercado): "
                      + "; ".join(cctx["pontos_negativos"]) + ".")
    regras.append("Estado de conservação (085-9): liste só defeitos de conservação (umidade, trincas, desgaste); "
                  "itens de acabamento ou uso (ex.: cortinas no lugar de portas) ficam na descrição de esquadrias, não como defeito.")
    regras.append("Legendas das fotos (085-7): nunca numere cômodo além do que o imóvel tem (2 quartos → Quarto 1 e Quarto 2); "
                  "na dúvida, só \"Quarto\".")
    regras.append("Datas de documentos (136, decisão do Capitão): não escreva data de emissão de nenhum documento "
                  "(comunicado, relatório, certidão, conta, escritura); as únicas datas são a da vistoria e a da consulta "
                  "ao Mapa Digital Fácil.")
    regras.append("Área do lote (decisão do Capitão): vale a da escritura registrada; não cite a área da planta da "
                  "Prefeitura (Mapa Digital Fácil) nem diga que a planta 'confirma' a área.")
    regras.append(f"Data (D-127, regra do Capitão): o valor é o da data da vistoria, {t.data_vistoria.strftime('%d/%m/%Y')}. "
                  "Nunca escreva \"data-base\" nem trate outra data (DITCD, ciência da malha, escritura, IPTU) como data da "
                  "avaliação; essas datas só aparecem como fatos do processo, quando precisarem.")
    if cctx.get("medidas_confere"):
        regras.append("Áreas (D-055): escreva só \"as medidas conferidas na vistoria são compatíveis com a escritura e com o cadastro municipal\", sem número de trena.")
    if cctx.get("idade_aparente"):
        regras.append(f"Idade aparente: {cctx['idade_aparente']} anos para o avaliando e para os referenciais; escreva só \"idade aparente de cerca de N anos\", sem dizer como foi estimada (113-4). Nunca \"n/i\".")
    prompt += "\n\nREGRAS DO TEXTO:\n" + "\n".join(f"- {r}" for r in regras)
    from ..docx_builder import mapa_digital
    _, md = mapa_digital(job_id)
    if md.get("area_planta") or md.get("area"):     # 077-B2 (D-055): a planta da Prefeitura confere o título
        prompt += (f"\n\nMAPA DIGITAL FÁCIL (Prefeitura): área do lote pela planta {md.get('area_planta') or md.get('area')} m²"
                   + (f"; cadastro imobiliário {md['area_cadastro']} m²" if md.get("area_cadastro") else "")
                   + ". No item 7.3, diga se a planta da Prefeitura confirma a área do título.")
    datas = datas_dos_documentos(job_id)
    if datas:                       # 077-4: a coluna "Data" da Documentação analisada nunca fica com "—" à toa
        prompt += ("\n\nDATAS LIDAS DE CADA DOCUMENTO (use na coluna de data da seção 6: data de emissão, "
                   "mês/ano de referência ou exercício; só use \"—\" se o documento não trouxer data):\n"
                   + "\n".join(f"- {k}: {v}" for k, v in datas.items()))
    reforcos = json.loads(db.setting(f"reforcos:{job_id}") or "[]")
    if reforcos and not db.setting(f"reforco_desfeito:{job_id}"):
        # 101-1 (b/c): reforço da contestação simulada só EXPLICA; as decisões do avaliador valem mais
        prompt += ("\n\nREFORÇOS SUGERIDOS PELA CONTESTAÇÃO SIMULADA (só explique com o que já está no laudo; NUNCA acrescente "
                   "número novo, média alternativa, coeficiente de variação, 'sem o referencial X', nem limite interno do "
                   "avaliador; se contrariar uma decisão ou instrução do avaliador, ignore):\n" + "\n".join(f"- {x}" for x in reforcos))
    instr = db.instrucoes_avaliador(job_id)
    if instr:                       # 074-F3: o que o avaliador escreveu ao confirmar vale para o texto
        prompt += ("\n\nINSTRUÇÕES DO AVALIADOR AO CONFIRMAR O VALOR (decisão INTERNA: obedeça, mas NUNCA copie nem resuma este texto no laudo; 106-2):\n"
                   + "\n".join(f"- {x}" for x in instr))
    if quesitos:
        prompt += "\n\nQuesitos (responda um a um na seção \"12\"):\n" + "\n".join(
            f"Quesito {i}: {q}" for i, q in enumerate(quesitos, start=1))
    if anterior is not None and anterior.faltas:
        prompt += ("\n\nA VERSÃO ANTERIOR FICOU ABAIXO DO MÍNIMO nestas seções (corrija):\n"
                   + "\n".join(f"- {f}" for f in anterior.faltas))
    # 081-7: texto que o avaliador já leu não muda sozinho. Mesma entrada → mesmo texto (nem chama a IA);
    # entrada diferente → só as seções atingidas pelo que mudou são reescritas; o resto fica letra por letra.
    entrada_arq = db.pasta(job_id) / "redacao_entrada.txt"
    entrada_antes = entrada_arq.read_text(encoding="utf-8") if entrada_arq.is_file() else None
    base = anterior if (anterior is not None and anterior.secoes) else None
    refazer = list(anterior.faltas) if anterior is not None else []
    if base is not None and entrada_antes == prompt and not refazer:
        db.evento(job_id, "redacao", "resultado", "nada mudou: texto mantido igual", dados=base.model_dump(mode="json"))
        _gravar_mudancas(job_id, [])
        return base
    if base is not None:
        prompt += ("\n\nTEXTO ATUAL DO LAUDO (o avaliador JÁ LEU; não reescreva o que não precisa mudar):\n"
                   + json.dumps({"secoes": base.secoes, "legendas": base.legendas,
                                 "descricao_amostras": base.descricao_amostras}, ensure_ascii=False)
                   + "\n\nO QUE MUDOU NOS DADOS DESDE ESSE TEXTO:\n" + _diferenca(entrada_antes, prompt)
                   + "\n\nDevolva em 'secoes', 'legendas' e 'descricao_amostras' SÓ o que precisa mudar por causa "
                     "dessas mudanças (dado novo, correção pedida, problema apontado) ou das seções abaixo do mínimo. "
                     "Cada parte devolvida vem inteira; o que não precisa mudar NÃO devolva (fica igual, letra por letra).")
    r: Textos = await ia.perguntar(sistema, prompt, Textos)
    if base is not None:
        mudou = sorted(k for k, v in r.secoes.items() if base.secoes.get(k) != v)
        r = Textos(secoes={**base.secoes, **r.secoes}, legendas={**base.legendas, **r.legendas},
                   descricao_amostras={**base.descricao_amostras, **r.descricao_amostras})
    else:
        mudou = sorted(r.secoes)
    entrada_arq.parent.mkdir(parents=True, exist_ok=True)
    entrada_arq.write_text(prompt.split("\n\nTEXTO ATUAL DO LAUDO")[0], encoding="utf-8")
    _gravar_mudancas(job_id, mudou if base is not None else [])
    fontes = "\n".join([CITACOES_NORMATIVAS, t.model_dump_json(),
                        # 095-7: o relato do avaliador (idade, estado, pontos negativos) também é fonte
                        json.dumps({k: cctx.get(k) for k in ("checklist", "idade_aparente", "estado_conservacao",
                                                             "pontos_negativos", "medidas_confere")},
                                   ensure_ascii=False, default=str),
                        json.dumps(campos, ensure_ascii=False, default=str),
                        json.dumps(ext, ensure_ascii=False, default=str),
                        _resumo_calculo(job_id, sel, t.modalidade)])
    r.faltas = deficiencias(t.modalidade, r.secoes, quesitos, fontes=fontes)
    if r.faltas:
        db.evento(job_id, "redacao", "aviso", f"{SECOES_SEM_TEXTO}: {'; '.join(r.faltas)}")
    db.evento(job_id, "redacao", "resultado", f"{len(r.secoes)} seções redigidas",
              dados=r.model_dump(mode="json"))
    return r


def _diferenca(antes: str | None, agora: str) -> str:
    """Linhas da entrada que entraram ou saíram (o que mudou nos dados)."""
    if antes is None:
        return ("(a entrada anterior não foi guardada: mude só o que contradiz os dados atuais, "
                "as correções pedidas e os problemas apontados)")
    import difflib
    linhas = [l for l in difflib.unified_diff(antes.splitlines(), agora.splitlines(), lineterm="", n=0)
              if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    return "\n".join(linhas[:200]) or "(nada)"


def _gravar_mudancas(job_id: str, secoes: list[str]) -> None:
    """D-073: as seções reescritas nesta remontagem (base da lista "o que mudou")."""
    db.set_setting(f"redacao_mudou:{job_id}", json.dumps(secoes, ensure_ascii=False))


def mudancas(job_id: str) -> list[str]:
    try:
        return list(json.loads(db.setting(f"redacao_mudou:{job_id}") or "[]"))
    except ValueError:
        return []


def carregar(job_id: str) -> Textos | None:
    d = db.resultado(job_id, "redacao")
    return Textos.model_validate(d) if d else None
