"""Exemplo para clientes (D-041): cópia do laudo pronto sem dados que identifiquem o imóvel
ou as pessoas. Só código, sem IA.

- TROCADOS por █ no texto (substituídos, não cobertos): rua, quadra, lote, CEP, nomes do
  solicitante e do proprietário/contribuinte, inscrição do IPTU e link do Maps (hiperlink
  desativado). Vale também para o referencial da mesma rua/CEP.
- DESFOCADOS: o mapa, a foto que mostra esquina/placa com endereço e os documentos dos
  anexos de documentação (imóvel e solicitante).
- MANTIDOS: fotos do imóvel, valores e links dos anúncios.
"""
from __future__ import annotations

import io
import re
import shutil
import unicodedata
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from PIL import Image, ImageFilter

from . import db, pdf
from .agentes import _comum

BLOCO = "█"
_PARADAS = {"de", "da", "das", "do", "dos", "e", "rua", "avenida", "av", "r", "alameda", "travessa",
            "quadra", "lote", "s/n", "sn", "jardim", "setor", "vila"}
FOTO_COM_ENDERECO = re.compile(r"(?i)placa|esquina|n[úu]mero|endere[cç]o|numera[cç][aã]o|nome da rua")


def _n(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return s.casefold()


def _flex(s: str) -> str:
    """Regex que casa o texto com ou sem acento e com espaços variáveis."""
    out = []
    for ch in s:
        if ch.isspace():
            out.append(r"\s+")
        elif ch.isalpha():
            base = _n(ch)
            variantes = {ch.lower(), ch.upper(), base, base.upper()}
            for a, bs in (("a", "áàâãä"), ("e", "éèêë"), ("i", "íìîï"), ("o", "óòôõö"),
                          ("u", "úùûü"), ("c", "ç")):
                if base == a:
                    variantes |= set(bs) | {x.upper() for x in bs}
            out.append("[" + "".join(sorted(re.escape(v) for v in variantes)) + "]")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def _campo(cs, *rx: str):
    for c in cs:
        if c.valor in (None, "") or c.origem not in ("documento", "vistoria"):
            continue
        if any(re.search(r, _n(c.nome)) for r in rx):
            return str(c.valor)
    return ""


def padroes(job_id: str, nome_avaliador: str = "") -> list[re.Pattern]:
    """O que vira █: construído dos campos do próprio trabalho (nada fixo de um caso)."""
    t = _comum.trabalho(job_id)
    cs = db.campos(job_id)
    pads: list[str] = []
    # rua (só o nome: "Rua das Flores, s/n" -> "das Flores")
    rua = _campo(cs, r"^logradouro", r"^endereco")
    if rua:
        nome_rua = re.split(r",|\s-\s|\bs/?n\b|\bqd\b|\bquadra\b|\bn[º°o]\b", rua, flags=re.I)[0]
        nome_rua = re.sub(r"(?i)^\s*(rua|r\.|avenida|av\.|alameda|al\.|travessa|tv\.|rodovia)\s+", "",
                          nome_rua).strip()
        if len(nome_rua) >= 3:
            pads.append(_flex(nome_rua))
    # quadra / lote: o valor depois do rótulo
    for chave, rot in ((r"^quadra", r"(?:Quadra|Qd\.?|QD\.?)"), (r"^lote", r"(?:Lote|Lt\.?|LT\.?)")):
        v = _campo(cs, chave)
        if v:
            alvo = re.escape(v.strip()).replace(r"\-", "-?")
            pads.append(rf"\b{rot}\s*({alvo})\b")   # só o grupo (o número) vira █
    # CEP (com e sem hífen; o prefixo de 5 dígitos também)
    cep = re.sub(r"\D", "", _campo(cs, r"^cep"))
    if len(cep) == 8:
        pads.append(rf"{cep[:5]}-?{cep[5:]}|\b{cep[:5]}\b")
    # inscrição do IPTU (pontuada ou só dígitos)
    for c in cs:
        if re.search(r"inscri", _n(c.nome)) and c.valor:
            dig = re.sub(r"\D", "", str(c.valor))
            if len(dig) >= 6:
                pads.append(re.escape(str(c.valor).strip()))
                pads.append(r"[.\s-]?".join(dig))
                pads.append(re.escape(str(c.valor).strip()[:7]))   # "330.042" (prefixo)
    # nomes: solicitante e proprietário/contribuinte, inteiros e cada nome (sem o avaliador)
    meus = {_n(x) for x in re.split(r"\s+", nome_avaliador or "") if x}
    nomes = [t.cliente, _campo(cs, r"^solicitante"), _campo(cs, r"propriet"), _campo(cs, r"contribuinte")]
    for c in cs:
        if re.search(r"propriet|contribuinte|outorgad|comprador|vendedor", _n(c.nome)) and c.valor:
            nomes.append(str(c.valor))
    for nome in {x.strip() for x in nomes if x and x.strip()}:
        pads.append(_flex(nome))
        for parte in re.split(r"\s+", nome):
            if len(parte) >= 3 and _n(parte) not in _PARADAS and _n(parte) not in meus:
                pads.append(r"\b" + _flex(parte) + r"\b")
    # link do Maps
    if t.pin_maps:
        pads.append(re.escape(t.pin_maps.strip()))
    pads.append(r"https?://(?:maps\.app\.goo\.gl|goo\.gl/maps|(?:www\.)?google\.[a-z.]+/maps)\S*")
    return [re.compile(p) for p in pads if p]


def _redigir_par(p, pads: list[re.Pattern]) -> int:
    """Troca por █, caractere a caractere, tudo o que casar no texto do parágrafo (mesmo
    quebrado em vários runs)."""
    ts = [t for t in p.iter(qn("w:t"))]
    if not ts:
        return 0
    texto = "".join(t.text or "" for t in ts)
    marcar = set()
    for rx in pads:
        for m in rx.finditer(texto):
            a, b = m.span(1) if rx.groups and m.group(1) else m.span()
            marcar.update(i for i in range(a, b) if not texto[i].isspace())
    if not marcar:
        return 0
    pos = 0
    for t in ts:
        s = t.text or ""
        t.text = "".join(BLOCO if (pos + i) in marcar else ch for i, ch in enumerate(s))
        pos += len(s)
    return len(marcar)


def _desativar_links(doc, pads: list[re.Pattern]) -> None:
    """Hiperlink do Maps (ou cujo texto foi redigido): vira texto comum, sem destino."""
    for parte in _partes(doc):
        el = _el(parte)
        for h in list(el.iter(qn("w:hyperlink"))):
            rid = h.get(qn("r:id"))
            alvo = ""
            if rid and rid in parte.part.rels:
                alvo = parte.part.rels[rid].target_ref
            txt = "".join(t.text or "" for t in h.iter(qn("w:t")))
            if any(rx.search(alvo) for rx in pads) or BLOCO in txt:
                pai = h.getparent()
                i = list(pai).index(h)
                for r in list(h):
                    for u in r.iter(qn("w:u")):
                        u.getparent().remove(u)
                    pai.insert(i, r)
                    i += 1
                pai.remove(h)


def _el(parte):
    return parte.element if hasattr(parte, "element") else parte._element


def _partes(doc):
    yield doc
    for s in doc.sections:
        for hf in (s.header, s.footer, s.first_page_header, s.first_page_footer):
            if not hf.is_linked_to_previous:
                yield hf


def _desfocar_blip(doc, blip) -> None:
    rid = blip.get(qn("r:embed"))
    if not rid or rid not in doc.part.related_parts:
        return
    parte = doc.part.related_parts[rid]
    im = Image.open(io.BytesIO(parte.blob)).convert("RGB")
    raio = max(12, max(im.size) // 40)
    im = im.filter(ImageFilter.GaussianBlur(raio))
    buf = io.BytesIO()
    im.save(buf, "PNG" if parte.partname.ext == "png" else "JPEG", quality=85)
    parte._blob = buf.getvalue()


def placas(im: Image.Image) -> list[tuple[int, int, int, int]]:
    """Placas de endereço na foto da fachada, sem IA: retângulo pequeno, claro e pouco
    saturado, com texto escuro dentro. Devolve caixas (com margem) na escala da imagem."""
    import numpy as np
    esc = min(1.0, 1400 / max(im.size))
    peq = im.convert("RGB").resize((max(1, int(im.width * esc)), max(1, int(im.height * esc))))
    a = np.asarray(peq).astype(int)
    lum = a.mean(axis=2)
    sat = a.max(axis=2) - a.min(axis=2)
    claro = (a.min(axis=2) > 140) & (sat < 40)
    h, w = claro.shape
    visto = np.zeros_like(claro, dtype=bool)
    caixas = []
    total = h * w
    for y0 in range(h):
        for x0 in np.nonzero(claro[y0] & ~visto[y0])[0]:
            pilha = [(y0, int(x0))]
            visto[y0, x0] = True
            ys, xs = [], []
            while pilha:
                y, x = pilha.pop()
                ys.append(y)
                xs.append(x)
                if len(ys) > total * 0.02:   # região grande (céu, parede clara): não é placa
                    break
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and claro[ny, nx] and not visto[ny, nx]:
                        visto[ny, nx] = True
                        pilha.append((ny, nx))
            if len(ys) > total * 0.02 or len(ys) < 12:
                continue
            y1, y2, x1, x2 = min(ys), max(ys) + 1, min(xs), max(xs) + 1
            bw, bh = x2 - x1, y2 - y1
            area = bw * bh
            if not (total * 0.00008 <= area <= total * 0.003) or not (1.4 <= bw / max(1, bh) <= 4.5):
                continue
            if y1 == 0 or x1 == 0 or y2 >= h or x2 >= w:   # encostado na borda (céu)
                continue
            if len(ys) / area < 0.55:   # placa é um retângulo cheio; nuvem/fio não
                continue
            # a parede em volta é bem mais escura que a placa (nuvem: céu claro em volta)
            r = max(3, bh // 2)
            anel = np.concatenate([lum[max(0, y1 - r):y1, x1:x2].ravel(), lum[y2:y2 + r, x1:x2].ravel(),
                                   lum[y1:y2, max(0, x1 - r):x1].ravel(), lum[y1:y2, x2:x2 + r].ravel()])
            if anel.size == 0 or anel.mean() > lum[y1:y2, x1:x2][claro[y1:y2, x1:x2]].mean() - 45:
                continue
            escuro = (lum[y1:y2, x1:x2] < 120).mean()
            if 0.04 <= escuro <= 0.5:   # texto escuro dentro do retângulo claro
                m = int(max(bw, bh) * 0.35) + 2
                caixas.append((int((x1 - m) / esc), int((y1 - m) / esc), int((x2 + m) / esc), int((y2 + m) / esc)))
    return caixas


def _desfocar_placas_blip(doc, blip) -> int:
    rid = blip.get(qn("r:embed"))
    if not rid or rid not in doc.part.related_parts:
        return 0
    parte = doc.part.related_parts[rid]
    im = Image.open(io.BytesIO(parte.blob)).convert("RGB")
    cx = placas(im)
    for x1, y1, x2, y2 in cx:
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(im.width, x2), min(im.height, y2)
        reg = im.crop((x1, y1, x2, y2)).filter(ImageFilter.GaussianBlur(max(6, (x2 - x1) // 6)))
        im.paste(reg, (x1, y1))
    if cx:
        buf = io.BytesIO()
        im.save(buf, "PNG" if parte.partname.ext == "png" else "JPEG", quality=88)
        parte._blob = buf.getvalue()
    return len(cx)


def _placas_fachada(doc) -> int:
    """Só a capa (1ª imagem do corpo, ~15 cm): é onde a placa fica legível. Na grade do
    relatório (7,2 cm, ~570 px) a placa tem ~15 px e não se lê; ali o detector só criaria
    manchas falsas."""
    body = doc.element.body
    alvos = []
    capa = next((p for p in body.iter(qn("w:p")) if p.find(".//" + qn("w:drawing")) is not None), None)
    if capa is not None:
        alvos.append(capa)
    n, vistos = 0, set()
    for el in alvos:
        for blip in el.iter(qn("a:blip")):
            if blip.get(qn("r:embed")) not in vistos:
                vistos.add(blip.get(qn("r:embed")))
                n += _desfocar_placas_blip(doc, blip)
    return n


def _desfocar(doc) -> int:
    """Mapa (imagem antes da legenda "Imagem 02"), foto do relatório com placa/esquina e as
    imagens dos anexos de documentação."""
    body = doc.element.body
    ps = list(body.iter(qn("w:p")))
    alvos = []
    for i, p in enumerate(ps):
        t = "".join(x.text or "" for x in p.iter(qn("w:t"))).strip()
        # ORDEM 034-4 / D-062: os prints de medição por satélite (7.3) mostram onde fica o imóvel
        if t.startswith("Imagem 02") or t.startswith(("Medição ", "Localização e contorno")):
            for q in reversed(ps[max(0, i - 3):i]):
                if q.find(".//" + qn("w:drawing")) is not None:
                    alvos.append(q)
                    break
    # anexos de documentação: do título "Anexo III" (corpo, não o sumário) até o próximo
    # título de anexo que não seja de documentação
    dentro = False
    for p in ps:
        t = "".join(x.text or "" for x in p.iter(qn("w:t"))).strip()
        if re.match(r"Anexo [IVX]+ – ", t) and not t.endswith("\t") and p.find(".//" + qn("w:hyperlink")) is None:
            dentro = "Documenta" in t
            continue
        if dentro and p.find(".//" + qn("w:drawing")) is not None:
            alvos.append(p)
    # fotos do relatório cuja legenda fala de placa/esquina/número
    for tc in body.iter(qn("w:tc")):
        t = "".join(x.text or "" for x in tc.iter(qn("w:t")))
        if re.match(r"\s*Foto \d+", t) and FOTO_COM_ENDERECO.search(t) and tc.find(".//" + qn("w:drawing")) is not None:
            alvos.append(tc)
    n = 0
    vistos = set()
    for el in alvos:
        for blip in el.iter(qn("a:blip")):
            rid = blip.get(qn("r:embed"))
            if rid in vistos:
                continue
            vistos.add(rid)
            _desfocar_blip(doc, blip)
            n += 1
    return n


def nome_exemplo(t, telefone: str = "62 99306-8692", avaliador: str = "Alan Soares") -> str:
    mod = {"OV": "Opinião de Valor - Simples", "AM": "PTAM", "AM_GARANTIA": "PTAM",
           "AMJ": "PTAM Judicial"}.get(t.modalidade, "PTAM")
    return f"EXEMPLO - {mod} - {avaliador} {telefone}"


def gerar(job_id: str, docx_origem: Path, destino: Path | None = None,
          avaliador: dict | None = None) -> dict:
    """Gera DOCX (+ PDF) do exemplo; devolve {"docx", "pdf", "trocas", "imagens"}."""
    av = avaliador or {}
    t = _comum.trabalho(job_id)
    tel = re.sub(r"[()]", "", av.get("telefone") or "(62) 9 9306-8692")
    tel = re.sub(r"^\s*(\d{2})\s+9\s*(\d{4})-?(\d{4})", r"\1 9\2-\3", tel).strip()
    nome_av = " ".join((av.get("nome") or "Alan Soares da Silva").split()[:2])
    pads = padroes(job_id, av.get("nome") or "Alan Soares da Silva")
    doc = Document(str(docx_origem))
    trocas = 0
    for parte in _partes(doc):
        for p in _el(parte).iter(qn("w:p")):
            trocas += _redigir_par(p, pads)
    _desativar_links(doc, pads)
    imagens = _desfocar(doc)
    placas_n = _placas_fachada(doc)
    cp = doc.core_properties
    cp.title, cp.subject, cp.keywords, cp.comments = "Exemplo de laudo", "", "", ""
    destino = destino or (db.pasta(job_id) / "exemplo")
    destino.mkdir(parents=True, exist_ok=True)
    saida = destino / f"{nome_exemplo(t, tel, nome_av)}.docx"
    doc.save(str(saida))
    pdf_out = None
    try:
        pdf_out = pdf.converter(saida)
    except Exception:   # sem LibreOffice: entrega só o Word
        pdf_out = None
    return {"docx": saida, "pdf": pdf_out, "trocas": trocas, "imagens": imagens, "placas": placas_n}


def copiar(arqs: dict, pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    for k in ("docx", "pdf"):
        if arqs.get(k):
            shutil.copy2(arqs[k], pasta / Path(arqs[k]).name)
