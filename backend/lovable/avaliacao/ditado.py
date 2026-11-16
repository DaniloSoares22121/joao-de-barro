"""ORDEM 116-2: o avaliador DITA os ajustes do laudo ("Na página oito, trocar construção novo por construção nova.
Próximo: no item nove ponto três, …") e o sistema monta os pares do quadro "Onde fica: / O que mudar:".

Só texto (a transcrição é do transcritor do PC, D-107; a rota e a tela são do outro executor). Sem IA: regras.
- números falados viram algarismo só logo depois de "página", "item", "anexo"… ("nove ponto três" -> 9.3,
  "anexo três" -> anexo III); no resto da frase ficam como foram ditos ("uma casa" continua "uma casa");
- um ajuste novo começa no início de uma frase com "na página…/no item…/no anexo…/na capa…", ou depois de
  "próximo"/"outro ajuste"; "no item 9.3" no meio da frase é parte do "o que mudar";
- o que vem sem "onde" fica com onde="" e duvida=True (a tela marca em amarelo: "não entendi onde").
"""
from __future__ import annotations

import re
import unicodedata

_UNID = {"zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
         "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14,
         "quatorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19}
_DEZ = {"vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70,
        "oitenta": 80, "noventa": 90}
_CEM = {"cem": 100, "cento": 100, "duzentos": 200, "trezentos": 300}
_ROMANOS = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()


def _palavra_num(w: str) -> int | None:
    w = _sem_acento(w)
    if w.isdigit():
        return int(w)
    return _UNID.get(w, _DEZ.get(w, _CEM.get(w)))


def _numero_falado(tokens: list[str], i: int) -> tuple[int | None, int]:
    """Lê um número por extenso a partir de tokens[i] ("vinte e três", "cento e dois", "8"). (valor, tokens usados)."""
    total, usados, ultimo = 0, 0, None
    j = i
    while j < len(tokens):
        v = _palavra_num(tokens[j])
        if v is None:
            if _sem_acento(tokens[j]) == "e" and ultimo is not None and j + 1 < len(tokens) and _palavra_num(tokens[j + 1]) is not None:
                j += 1
                continue
            break
        if ultimo is not None and v >= ultimo and not (ultimo >= 100 and v < 100) and not (ultimo >= 20 and v < 10):
            break                                  # "oito nove" são dois números
        total += v
        ultimo = v
        j += 1
        usados = j - i
        if v < 10 or tokens[j - 1].isdigit():
            break
    return (total if usados else None), usados


_ROTULOS = r"p[áa]gina|pag\.?|item|itens|subitem|anexo|quadro|tabela|foto|fotografia|figura|referencial|amostra|linha|par[áa]grafo"


def _numeros_nos_rotulos(texto: str) -> str:
    """"página oito" -> "página 8"; "item nove ponto três" -> "item 9.3"; "anexo três" -> "anexo III"."""
    tokens = re.findall(r"\w+|[^\w\s]|\s+", texto)
    out, i = [], 0
    while i < len(tokens):
        t = tokens[i]
        out.append(t)
        i += 1
        if not re.fullmatch(rf"(?i){_ROTULOS}", t):
            continue
        anexo = _sem_acento(t) == "anexo"
        # pula espaço (e "de"/"número"/"nº")
        k = i
        while k < len(tokens) and (tokens[k].isspace() or _sem_acento(tokens[k]) in ("de", "numero", "n", "o", "º")):
            k += 1
        palavras = [x for x in tokens[k:k + 40] if not x.isspace()]
        v, usados = _numero_falado(palavras, 0)
        if v is None:
            continue
        partes = [str(v)]
        resto = palavras[usados:]
        while len(resto) >= 2 and _sem_acento(resto[0]) in ("ponto", ".") and _palavra_num(resto[1]) is not None:
            v2, u2 = _numero_falado(resto, 1)
            if v2 is None:
                break
            partes.append(str(v2))
            resto = resto[1 + u2:]
        consumidas = len(palavras) - len(resto)
        # avança nos tokens originais o número de palavras consumidas (mais os espaços entre elas)
        j, vistas = k, 0
        while j < len(tokens) and vistas < consumidas:
            if not tokens[j].isspace():
                vistas += 1
            j += 1
        num = ".".join(partes)
        if anexo and len(partes) == 1 and 0 < v < len(_ROMANOS):
            num = _ROMANOS[v]
        out.append(" " + num)
        i = j
    return "".join(out)


_SEPARA = re.compile(r"(?i)(?:^|(?<=[.!?;:])|(?<=\n))\s*(?:pr[óo]xim[oa]|outro\s+ajuste|outra\s+coisa|agora)\s*[:,.]?\s*")
_ONDE = re.compile(
    r"(?i)^\s*(?:e\s+)?(?:(?:n[oa]s?|em|d[oa])\s+)?(?:(p[áa]gina|item|subitem|anexo|quadro|tabela|foto|fotografia|figura|"
    r"referencial|amostra)\s+([0-9IVX]+(?:\.\d+)*)|(capa|cabe[çc]alho|rodap[ée]|resumo|conclus[ãa]o|sum[áa]rio|"
    r"t[íi]tulo|legenda|planilha|assinatura))\b")


def _frases(texto: str) -> list[str]:
    partes = re.split(r"(?<=[.!?;])\s+|\n+", texto)
    return [p.strip() for p in partes if p and p.strip()]


def _onde_inicial(frase: str) -> tuple[str, str]:
    """("página 8, item 7.4", resto) quando a frase COMEÇA pelo lugar; senão ("", frase)."""
    ondes, resto = [], frase
    while True:
        m = _ONDE.match(resto)
        if not m:
            break
        if m.group(1):
            rot = _sem_acento(m.group(1))
            rot = {"pagina": "página", "fotografia": "foto"}.get(rot, rot)
            ondes.append(f"{rot} {m.group(2)}")
        else:
            ondes.append(m.group(3).lower())
        resto = re.sub(r"^\s*[,:–-]?\s*", "", resto[m.end():])
    return ", ".join(ondes), resto


def _limpo(s: str) -> str:
    s = re.sub(r"^\s*[,:;–-]\s*", "", s).strip()
    s = re.sub(r"\s+", " ", s)
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    if s and s[-1] not in ".!?":
        s += "."
    return s


def pares_da_fala(texto: str) -> list[dict]:
    """O texto ditado -> [{"onde": "página 8", "oque": "Trocar …", "duvida": False}, …]."""
    t = _numeros_nos_rotulos(" ".join((texto or "").split()))
    blocos = [b for b in _SEPARA.split(t) if b and b.strip()]
    pares: list[dict] = []
    for bloco in blocos:
        atual: dict | None = None
        for frase in _frases(bloco):
            onde, resto = _onde_inicial(frase)
            if onde or atual is None:
                if atual and atual["oque"].strip():
                    pares.append(atual)
                elif atual and atual["onde"] and onde:          # "Na página 8." + "No item 9.3, …": um lugar só
                    onde = f"{atual['onde']}, {onde}"
                atual = {"onde": onde, "oque": resto}
            else:
                atual["oque"] = f"{atual['oque']} {frase}".strip()
        if atual and (atual["oque"].strip() or atual["onde"]):
            pares.append(atual)
    out = []
    for p in pares:
        oque = _limpo(p["oque"])
        if not oque:
            continue
        out.append({"onde": p["onde"], "oque": oque, "duvida": not p["onde"]})
    return out


def quadro(pares: list[dict]) -> str:
    """O texto do quadro da tela: um par "Onde fica: / O que mudar:" por ajuste, separados por linha em branco."""
    return "\n\n".join(f"Onde fica: {p.get('onde') or ''}\nO que mudar: {p.get('oque') or ''}" for p in pares)
