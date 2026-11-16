"""ORDEM L198: do modelo de laudo que o avaliador sobe, o sistema pega só duas coisas, sem IA:
(a) a formatação (fonte, tamanho do corpo e cores), lida do próprio arquivo (estilos do Word; fontes do PDF);
(b) os itens que o modelo dele tem e o nosso não tem (por título), com o texto fixo dele, sem dados de clientes.
O laudo continua no padrão JdB (estrutura, ordem e redação); os itens a mais entram antes da Assinatura."""
from __future__ import annotations

import io
import re
import unicodedata
from collections import Counter

_TITULO = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2})*)\s*[.)–-]?\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][^\n]{2,88})$")
_PALAVRAS_VAZIAS = {"de", "da", "do", "das", "dos", "e", "a", "o", "as", "os", "em", "no", "na", "nos", "nas", "para",
                    "por", "com", "ao", "aos", "um", "uma", "item", "itens", "laudo", "parecer", "avaliacao", "imovel",
                    "somente", "amj", "opcional", "ptam"}
NOSSOS = [  # títulos do modelo JdB (OV e PTAM), para saber o que já temos
    "finalidade da avaliação", "número do parecer", "da competência", "dados do processo", "referências normativas",
    "limitação de uso", "metodologia", "documentação analisada", "identificação e caracterização do imóvel",
    "situação e localização", "matrícula e registro imobiliário", "áreas e dimensões", "descrição do imóvel e acessórios",
    "relatório fotográfico", "diagnóstico de mercado", "pesquisa de imóveis referenciais", "amostra", "tratamento dos dados",
    "determinação do valor de mercado", "pressupostos ressalvas e condições limitantes", "respostas aos quesitos",
    "resumo da avaliação", "declarações do avaliador", "qualificação do perito", "assinatura", "anexos", "sumário",
    # sinônimos comuns nos modelos de mercado
    "objetivo", "objeto", "solicitante", "interessado", "proprietário", "vistoria", "caracterização da região",
    "localização", "conclusão", "valor", "encerramento", "fotos", "considerações finais", "ressalvas", "identificação",
    "documentos", "pesquisa de mercado", "cálculo", "homogeneização", "especificação", "grau de fundamentação",
    "grau de precisão", "data base", "currículo", "termo de encerramento"]


def _n(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", (s or "").casefold()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", s)


def _chave(s: str) -> set[str]:
    return {w for w in _n(s).split() if len(w) > 2 and w not in _PALAVRAS_VAZIAS and not w.isdigit()}


_NOSSAS_CHAVES = [_chave(t) for t in NOSSOS]


def ja_temos(titulo: str) -> bool:
    k = _chave(titulo)
    if not k:
        return True
    for n in _NOSSAS_CHAVES:
        if n and (n <= k or k <= n or len(k & n) / len(k | n) >= 0.5):
            return True
    return False


# ------------------------------------------------------------------ (a) formatação
def _fonte_limpa(nome: str) -> str:
    nome = re.sub(r"^[A-Z]{6}\+", "", nome or "")                        # PDF: "ABCDEF+Calibri-Bold"
    nome = re.sub(r"[-,](Bold|Italic|BoldItalic|Regular|Oblique|MT|PS|Semibold|Light).*$", "", nome, flags=re.I)
    nome = re.sub(r"(MT|PSMT)$", "", nome)
    return nome.strip() or ""


def _cor_ok(c: str) -> bool:
    c = (c or "").upper()
    if not re.fullmatch(r"[0-9A-F]{6}", c):
        return False
    r, g, b = int(c[:2], 16), int(c[2:4], 16), int(c[4:], 16)
    return max(r, g, b) - min(r, g, b) > 40                     # cor de verdade (preto, branco e cinza não contam)


def _formato_docx(dados: bytes) -> dict:
    import docx
    from docx.oxml.ns import qn
    d = docx.Document(io.BytesIO(dados))
    fontes, tams, cores = Counter(), Counter(), Counter()
    st = d.styles["Normal"]
    if st.font.name:
        fontes[st.font.name] += 50
    if st.font.size:
        tams[round(st.font.size.pt, 1)] += 50
    for p in d.paragraphs:
        for r in p.runs:
            n = len(r.text or "")
            if not n:
                continue
            f = r.font.name or (p.style.font.name if p.style is not None else None)
            if f:
                fontes[f] += n
            titulo = r.bold or (p.style is not None and p.style.name.lower().startswith(("heading", "título", "titulo", "title")))
            if not titulo:                                               # o tamanho do CORPO: títulos não contam
                tam = r.font.size or (p.style.font.size if p.style is not None else None) or st.font.size
                if tam:
                    tams[round(tam.pt, 1)] += n
            c = r.element.find(qn("w:rPr"))
            c = c.find(qn("w:color")) if c is not None else None
            if c is not None and _cor_ok(c.get(qn("w:val"))):           # cor de título (negrito/grande) pesa mais: vira a principal
                cores[c.get(qn("w:val")).upper()] += n * (4 if titulo or (r.font.size and r.font.size.pt > 12) else 1)
    usados = {p.style.name for p in d.paragraphs if p.style is not None and (p.text or "").strip()}
    for s in d.styles:                                                   # cores dos estilos de título EM USO
        try:
            if s.name in usados and s.name.lower().startswith(("heading", "título", "titulo", "title")) and s.font.color and s.font.color.rgb:
                c = str(s.font.color.rgb).upper()
                if _cor_ok(c):
                    cores[c] += 200
        except (AttributeError, ValueError):
            continue
    return _resumo(fontes, tams, cores)


def _formato_pdf(dados: bytes) -> dict:
    import pymupdf
    fontes, tams, cores = Counter(), Counter(), Counter()
    with pymupdf.open(stream=dados, filetype="pdf") as d:
        for pg in list(d)[:6]:
            for b in pg.get_text("dict").get("blocks", []):
                for ln in b.get("lines", []):
                    for sp in ln.get("spans", []):
                        n = len((sp.get("text") or "").strip())
                        if not n:
                            continue
                        fontes[_fonte_limpa(sp.get("font", ""))] += n
                        tams[round(float(sp.get("size", 0)) * 2) / 2] += n
                        c = f"{int(sp.get('color', 0)):06X}"
                        if _cor_ok(c):
                            cores[c] += n * (3 if sp.get("size", 0) > 12 else 1)
    return _resumo(fontes, tams, cores)


def _resumo(fontes: Counter, tams: Counter, cores: Counter) -> dict:
    fonte = next((_fonte_limpa(f) for f, _ in fontes.most_common() if _fonte_limpa(f)), "")
    tam = next((t for t, _ in tams.most_common() if 8 <= t <= 14), None)
    cs = [c for c, _ in cores.most_common(4)]
    return {"fonte": fonte[:40], "tamanho": tam, "cor_principal": cs[0] if cs else "", "cor_destaque": cs[1] if len(cs) > 1 else ""}


def ler_formato(nome: str, dados: bytes) -> dict:
    try:
        if nome.lower().endswith(".docx"):
            return _formato_docx(dados)
        if nome.lower().endswith(".pdf"):
            return _formato_pdf(dados)
    except Exception:
        pass
    return {"fonte": "", "tamanho": None, "cor_principal": "", "cor_destaque": ""}


# ------------------------------------------------------------------ (b) itens que o nosso não tem
def _blocos_docx(dados: bytes) -> list[tuple[str, list[str]]]:
    import docx
    d = docx.Document(io.BytesIO(dados))
    out: list[tuple[str, list[str]]] = []
    for p in d.paragraphs:
        t = (p.text or "").strip()
        if not t:
            continue
        estilo = (p.style.name if p.style is not None else "").lower()
        eh_titulo = estilo.startswith(("heading", "título", "titulo")) and len(t) <= 90 or bool(_TITULO.match(t))
        if eh_titulo:
            out.append((t, []))
        elif out:
            out[-1][1].append(t)
    return out


def _blocos_pdf(dados: bytes) -> list[tuple[str, list[str]]]:
    import pymupdf
    out: list[tuple[str, list[str]]] = []
    with pymupdf.open(stream=dados, filetype="pdf") as d:
        for pg in d:
            for ln in pg.get_text().splitlines():
                t = ln.strip()
                if not t:
                    continue
                if _TITULO.match(t):
                    out.append((t, []))
                elif out:
                    out[-1][1].append(t)
    return out


def _depende_do_trabalho(texto: str) -> bool:
    """Texto que muda a cada trabalho (nome, endereço, valor, área, data): não entra como texto fixo."""
    return bool(re.search(r"\[(?:nome|endereço|CPF|CNPJ|—|telefone|e-mail|link|empresa)\]|R\$\s*\d|\d+[.,]?\d*\s*m²|\d{1,2}/\d{1,2}/\d{2,4}",
                          texto or ""))


def ler_itens(nome: str, dados: bytes) -> list[dict]:
    from . import avaliadores as A
    try:
        blocos = _blocos_docx(dados) if nome.lower().endswith(".docx") else _blocos_pdf(dados) if nome.lower().endswith(".pdf") else []
    except Exception:
        blocos = []
    out, vistos = [], set()
    for titulo, corpo in blocos:
        limpo = re.sub(r"^\s*\d{1,2}(?:\.\d{1,2})*\s*[.)–-]?\s*", "", titulo).strip(" :.")
        if not limpo or ja_temos(limpo) or _n(limpo) in vistos:
            continue
        vistos.add(_n(limpo))
        bruto = "\n".join(corpo)
        texto = A.anonimizar(bruto)[:1500].strip()
        if not texto:
            continue
        out.append({"titulo": A.anonimizar(limpo)[:90], "texto": texto,
                    "depende_do_trabalho": _depende_do_trabalho(bruto) or _depende_do_trabalho(texto)})
    return out[:8]


# ------------------------------------------------------------------ L199: regra de escrita × regra de estrutura
_ESTRUTURA = re.compile(
    r"sum[áa]rio|ordem d[aoe]s? (?:se[çc][õo]es|itens|t[óo]picos)|n[úu]mero de (?:se[çc][õo]es|itens|p[áa]ginas)|"
    r"\b\d+\s+(?:itens|se[çc][õo]es|p[áa]ginas|colunas)\b|colunas?|grade|diagrama|capa\b|cabe[çc]alho|rodap[ée]|"
    r"\bfonte\b|\bcor(?:es)?\b|margem|numera[çc][ãa]o|bloco do valor|caixa (?:azul|do valor)|mem[óo]ria de c[áa]lculo|"
    r"\bfaixa\b|por extenso|anexos?\b|tabela de amostras|lugar da assinatura|assinatura (?:no|ao) (?:fim|final)", re.I)
_JA_NOSSO = re.compile(r"assinatura.*(creci|cnai)|(creci|cnai).*assinatura", re.I)


def regra_de_estrutura(texto: str) -> bool:
    return bool(_ESTRUTURA.search(texto or "")) or bool(_JA_NOSSO.search(texto or ""))


def separar_regras(topicos: list[str]) -> tuple[list[str], list[str]]:
    """(regras de escrita, o que fica de fora por ser estrutura). O que já é igual ao padrão JdB some sem aviso.
    Regra mista ("Fotos em grade de 2 colunas, com legenda curta") fica só com a parte de escrita ("Legenda curta")."""
    escrita, fora = [], []
    for t in topicos or []:
        t = (t or "").strip()
        if not t:
            continue
        if _JA_NOSSO.search(t):
            continue
        if not _ESTRUTURA.search(t):
            escrita.append(t)
            continue
        partes = [p.strip() for p in re.split(r",|;|\s+e\s+(?=com\b)", t) if p.strip()]
        sobra = [p for p in partes if not _ESTRUTURA.search(p)]
        if sobra and len(partes) > 1:
            s = re.sub(r"^(com|e)\s+", "", " ".join(sobra), flags=re.I).strip(" .")
            if len(s) >= 6:
                escrita.append(s[:1].upper() + s[1:])
                t = ", ".join(p for p in partes if _ESTRUTURA.search(p))     # em "fica de fora", só a parte de estrutura
        fora.append(t)
    return escrita, fora
