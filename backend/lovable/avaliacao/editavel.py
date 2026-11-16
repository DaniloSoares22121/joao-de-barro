"""ORDEM 138: o avaliador corrige o laudo DIRETO numa cópia editável (os cartões da lista só apontam onde mexer).

- abrir(jid): cria (uma vez) <trabalho>/editavel/<nome> - editável.docx a partir do .docx atual e abre no editor do
  PC (Word ou LibreOffice Writer). O laudo original não é tocado.
- situacao(jid): existe a cópia? quando foi salva? já foi alterada?
- usar(jid): a cópia editada vira o laudo — guarda o par atual em revisoes/editavel-<hora>/, gera o PDF no padrão com
  o mesmo conversor da montagem (sumário e campos atualizados) e roda SÓ a conferência por regra (sem IA, sem
  remontar). Número diferente da conta (valor, área, unitário) volta como ponto; nada é corrigido sozinho (138-4).
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db

_trava = threading.Lock()                           # um de cada vez no arquivo editável
ABRIR_NO_PC = "pytest" not in sys.modules          # nos testes automáticos nada é aberto na tela
PASTA = "editavel"


def _agora() -> datetime:
    return datetime.now(timezone(timedelta(hours=-3)))


def _finais(jid: str) -> dict[str, Path]:
    from .orquestrador import _arquivos_finais
    return _arquivos_finais(jid)


def caminho(jid: str) -> Path:
    docx = _finais(jid)["docx"]
    return db.pasta(jid) / PASTA / f"{docx.stem} - editável.docx"


def _marca(jid: str) -> Path:
    return db.pasta(jid) / PASTA / ".criado_em"


def _criado(jid: str, c: Path) -> float:
    m = _marca(jid)
    try:
        return float(m.read_text()) if m.is_file() else c.stat().st_mtime
    except ValueError:
        return c.stat().st_mtime


def situacao(jid: str) -> dict:
    """existe a cópia? já tem mudanças do avaliador? o laudo foi refeito pelo sistema depois dela (laudo_mudou)?"""
    c = caminho(jid)
    if not c.is_file():
        return {"existe": False, "arquivo": c.name, "alterado": False, "modificado_em": None, "laudo_mudou": False,
                "revisao_concluida_em": concluida_em(jid)}
    criado = _criado(jid, c)
    mod = c.stat().st_mtime
    docx = _finais(jid)["docx"]
    return {"existe": True, "arquivo": c.name, "alterado": mod > criado + 1,
            "laudo_mudou": docx.is_file() and docx.stat().st_mtime > criado + 2,
            "modificado_em": datetime.fromtimestamp(mod, timezone(timedelta(hours=-3))).isoformat(timespec="seconds"),
            "revisao_concluida_em": concluida_em(jid)}


def _marca_concluida(jid: str) -> Path:
    return db.pasta(jid) / PASTA / ".revisao_concluida_em"


def concluida_em(jid: str) -> str | None:
    """151-5: quando o avaliador tocou em [Concluir a revisão humana] (a tela do JdB mostra o PDF final e [Aprovar])."""
    m = _marca_concluida(jid)
    try:
        return m.read_text(encoding="utf-8").strip() or None if m.is_file() else None
    except OSError:
        return None


def _copiar(jid: str, docx: Path, c: Path) -> None:
    c.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(docx, c)
    _marca(jid).write_text(str(max(c.stat().st_mtime, docx.stat().st_mtime)))


def abrir(jid: str, externo: bool = False) -> dict:
    docx = _finais(jid)["docx"]
    if not docx.is_file():
        raise ValueError("Este trabalho ainda não tem o laudo em Word para editar.")
    c = caminho(jid)
    criado = False
    if not c.is_file():
        _copiar(jid, docx, c)
        criado = True
        db.evento(jid, "revisao", "info", "cópia editável do laudo criada para o avaliador corrigir direto no documento")
    else:
        s = situacao(jid)
        if s["laudo_mudou"] and not s["alterado"]:
            # automático e seguro: o sistema refez o laudo e a cópia não tinha nenhuma mudança do avaliador -> a cópia
            # passa a ser a do laudo novo (nunca se edita um laudo velho sem saber)
            _copiar(jid, docx, c)
            criado = True
            db.evento(jid, "revisao", "info", "cópia editável atualizada sozinha: o laudo tinha sido refeito e a cópia "
                      "não tinha mudanças do avaliador")
    aberto = False
    if ABRIR_NO_PC and externo:              # o padrão é o editor do próprio sistema; o do PC só se pedido
        try:
            os.startfile(str(c))              # noqa: S606 — o editor do PC do avaliador (Word ou Writer)
            aberto = True
        except OSError:
            aberto = False
    s = situacao(jid)
    if s["laudo_mudou"] and s["alterado"]:
        s["aviso"] = ("O sistema refez o laudo depois que você começou a editar. O que você editou está guardado aqui; "
                      "se usar este documento, ele substitui o laudo refeito.")
    return {**s, "criado": criado, "aberto": aberto}


def descartar(jid: str) -> dict:
    """Joga fora as mudanças da cópia (guardando-a em revisoes/) e recomeça do laudo atual."""
    c = caminho(jid)
    docx = _finais(jid)["docx"]
    if not docx.is_file():
        raise ValueError("Este trabalho ainda não tem o laudo em Word para editar.")
    if c.is_file():
        guarda = db.pasta(jid) / "revisoes" / f"edit-desc-{_agora().strftime('%Y%m%d-%H%M%S')}"
        guarda.mkdir(parents=True, exist_ok=True)
        shutil.copy2(c, guarda / c.name)
    _copiar(jid, docx, c)
    db.evento(jid, "revisao", "info", "mudanças do documento editável descartadas pelo avaliador (cópia guardada em revisoes/)")
    return situacao(jid)


def _conferir(jid: str, finais: dict):
    from . import coerencia
    from .orquestrador import _Pipeline
    try:
        r = _Pipeline(jid)._resultado()
    except BaseException as e:               # noqa: BLE001 — sem a conta, a conferência compara com o próprio PDF
        r, motivo = None, f"conta não refeita ({type(e).__name__})"
    else:
        motivo = ""
    xlsx = finais["xlsx"] if finais["xlsx"].exists() else None
    co = coerencia.do_trabalho(jid, finais["pdf"], xlsx, r) if r is not None else coerencia.conferir(finais["pdf"], xlsx)
    return co, motivo


def _gerar_pdf(finais: dict) -> None:
    from . import pdf as _pdf
    pdf = _pdf.converter(finais["docx"])
    if pdf != finais["pdf"] and pdf.is_file():
        shutil.move(str(pdf), finais["pdf"])


_gerando: dict[str, threading.Lock] = {}
_gerando_trava = threading.Lock()


def usar(jid: str, concluir: bool = False) -> dict:
    """162-2: um pedido de cada vez por trabalho, no SERVIDOR (duas abas, dois navegadores ou dois toques): enquanto um
    gera o PDF, o outro volta na hora com 409 e a frase abaixo — não gera de novo."""
    with _gerando_trava:
        t = _gerando.setdefault(jid, threading.Lock())
    if not t.acquire(blocking=False):
        raise ValueError("Já estou gerando o PDF deste laudo (pedido por outra aba ou outro toque). Espere o resultado.")
    try:
        return _usar(jid, concluir)
    finally:
        t.release()


def _usar(jid: str, concluir: bool = False) -> dict:
    """`concluir` (151-5, [Concluir a revisão humana]): sem mudança no documento, não refaz o PDF — confere o atual."""
    from . import coerencia, docx_builder
    from .orquestrador import ocupado
    if ocupado(jid):
        raise ValueError("O laudo está sendo montado agora. Espere terminar e toque de novo.")
    from . import google_doc                  # 169-6: com o laudo no Google Docs, o que vale é o que está lá
    do_google = google_doc.puxar(jid)
    c = caminho(jid)
    if not c.is_file():
        raise ValueError("Ainda não há cópia editável. Toque em “Abrir o laudo editável” primeiro.")
    try:                                      # o editor ainda com o arquivo aberto e não salvo: o Windows trava a leitura
        with open(c, "rb"):
            pass
    except OSError:
        raise ValueError("Feche (ou salve) o documento no editor e toque de novo.")
    finais = _finais(jid)
    mudou = do_google or situacao(jid)["alterado"] or not finais["pdf"].is_file()
    if not mudou and not concluir:
        raise ValueError("Você ainda não mudou nada no documento. O laudo continua o mesmo.")
    guarda = db.pasta(jid) / "revisoes" / f"editavel-{_agora().strftime('%Y%m%d-%H%M%S')}"
    guarda.mkdir(parents=True, exist_ok=True)
    for k in ("docx", "pdf"):
        if finais[k].is_file():
            shutil.copy2(finais[k], guarda / finais[k].name)
    if mudou:
        with _trava:
            shutil.copyfile(c, finais["docx"])
        _gerar_pdf(finais)
    co, motivo = _conferir(jid, finais)
    # automático e seguro: o que a conferência já corrige sozinha na montagem (data da assinatura, nº do laudo, CNAI,
    # "data-base" que sobrou) também se corrige aqui — troca exata de texto, uma volta só, e a tela diz o que trocou.
    # Número de conta (valor, área, unitário) NUNCA é trocado sozinho: volta como ponto para o avaliador.
    sozinho: list[str] = []
    pares = coerencia.substituicoes(co)
    if pares:
        n = docx_builder.aplicar_substituicoes(finais["docx"], pares)
        if n:
            sozinho = [f"“{de}” → “{para}”" for de, para in pares]
            _gerar_pdf(finais)
            co, motivo = _conferir(jid, finais)
    with _trava:                              # a cópia editável fica igual ao laudo (sem mudanças pendentes)
        _copiar(jid, finais["docx"], c)
    _previa(jid).unlink(missing_ok=True)      # 157: as folhas passam a seguir o PDF novo do laudo
    difs = [{"dado": d.dado, "pagina": d.pagina, "encontrado": d.encontrado, "esperado": d.esperado,
             "texto": d.texto(), "lugares": d.lugares, "do_avaliador": d.do_avaliador,
             "sugestao": d.sugestao, "valor_sugerido": d.valor_sugerido} for d in co.diferencas]
    aviso = "; ".join(x for x in (("Corrigi sozinho: " + "; ".join(sozinho)) if sozinho else "", motivo) if x)
    # 143-3: número diferente da conta/planilha não deixa seguir para a revisão humana (volta à lista, numa frase)
    trava = [d for d in difs if _de_conta(d["dado"])]
    bloqueia_texto = ""
    if trava:
        um = trava[0]
        bloqueia_texto = (f"Achei {len(trava)} {'número diferente' if len(trava) == 1 else 'números diferentes'} da conta "
                          f"ou da planilha: {um['dado']} — {um['pagina']} traz {um['encontrado']}, o esperado é {um['esperado']}.")
    if concluir:
        _marca_concluida(jid).write_text(_agora().isoformat(timespec="seconds"), encoding="utf-8")
    db.evento(jid, "revisao", "info", ("revisão humana concluída no editável" if concluir else
                                       "laudo editado pelo avaliador passou a ser o laudo")
              + f" ({'PDF gerado' if mudou or sozinho else 'sem mudança: PDF mantido'}; conferência "
              f"por regra: {'tudo igual' if co.ok else str(len(difs)) + ' ponto(s)'})"
              + (f"; {aviso}" if aviso else ""), dados={"guardado_em": str(guarda.relative_to(db.pasta(jid))),
                                                       "diferencas": difs, "corrigido_sozinho": sozinho})
    return {"ok": co.ok, "pdf": finais["pdf"].name, "guardado_em": guarda.name, "diferencas": difs, "mudou": mudou,
            "concluida_em": concluida_em(jid) if concluir else None,
            "corrigido_sozinho": sozinho, "aviso": aviso, "bloqueia": len(trava), "bloqueia_texto": bloqueia_texto}


_CONTA = ("valor adotado", "valor por extenso", "mínimo da faixa", "máximo da faixa", "unitário", "área do cálculo",
          "resultado da conta", "R$/m² da amostra", "nº de amostras", "amostras", "arredondamento", "planilha:",
          "coeficiente de variação", "conta da FIPE")


def _de_conta(dado: str) -> bool:
    """Ponto de conta/número (valor, área, unitário, faixa, planilha): o avaliador não conserta colando texto."""
    return any(str(dado or "").startswith(c) for c in _CONTA)


# ------------------------------------------------------------------ editor do próprio sistema (pedido do avaliador)
# O laudo editável abre DENTRO do João de Barro, no navegador, e salva sozinho a cada mudança. A edição troca só o
# TEXTO dentro do Word: negrito, tamanhos, tabelas, imagens, cabeçalho e rodapé ficam como estão.
import copy  # noqa: E402
import re  # noqa: E402

from docx import Document  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402

_NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_NS_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_ESPACO = "{http://www.w3.org/XML/1998/namespace}space"
_CONTROLE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _garantir(jid: str) -> Path:
    c = caminho(jid)
    if not c.is_file():
        abrir(jid, externo=False)
    return c


def _ligado(el) -> bool:
    return el is not None and el.get(qn("w:val")) not in ("0", "false", "none")


def _fmt_run(r) -> dict:
    rpr = r.find(qn("w:rPr"))
    f: dict = {}
    if rpr is None:
        return f
    if _ligado(rpr.find(qn("w:b"))):
        f["b"] = 1
    if _ligado(rpr.find(qn("w:i"))):
        f["i"] = 1
    if _ligado(rpr.find(qn("w:u"))):
        f["u"] = 1
    sz = rpr.find(qn("w:sz"))
    if sz is not None and (sz.get(qn("w:val")) or "").isdigit():
        f["sz"] = int(sz.get(qn("w:val"))) / 2
    cor = rpr.find(qn("w:color"))
    if cor is not None and (cor.get(qn("w:val")) or "auto") != "auto":
        f["cor"] = cor.get(qn("w:val"))
    fo = rpr.find(qn("w:rFonts"))
    if fo is not None and fo.get(qn("w:ascii")):
        f["fonte"] = fo.get(qn("w:ascii"))
    hl = rpr.find(qn("w:highlight"))
    if hl is not None and _REALCE_HEX.get(hl.get(qn("w:val")) or ""):
        f["realce"] = _REALCE_HEX[hl.get(qn("w:val"))]
    else:
        shd = rpr.find(qn("w:shd"))
        if shd is not None and (shd.get(qn("w:fill")) or "auto") != "auto":
            f["realce"] = shd.get(qn("w:fill"))
    return f


# 151-3: o realce é o "marca-texto" do Word (abre igual no Word, no LibreOffice e no Google Docs)
_REALCE_HEX = {"yellow": "FFFF00", "green": "00FF00", "cyan": "00FFFF", "magenta": "FF00FF", "lightGray": "C0C0C0",
               "red": "FF0000", "blue": "0000FF", "darkYellow": "808000", "darkGray": "808080"}
_HEX_REALCE = {v: k for k, v in _REALCE_HEX.items()}
_INDICE = {"yellow": "YELLOW", "green": "BRIGHT_GREEN", "cyan": "TURQUOISE", "magenta": "PINK", "lightGray": "GRAY_25",
           "red": "RED", "blue": "BLUE", "darkYellow": "DARK_YELLOW", "darkGray": "GRAY_50"}
FONTES = ("Arial", "Calibri", "Cambria", "Georgia", "Times New Roman", "Verdana", "Tahoma", "Courier New")


def _editavel(p) -> bool:
    """Só texto simples é editável: sumário e campos (nº de página), quebras e tabulações dentro da frase ficam fora."""
    for r in p.iter(qn("w:r")):
        if any(r.find(qn(t)) is not None for t in ("w:fldChar", "w:instrText", "w:tab", "w:br")):
            return False
    return p.find(qn("w:fldSimple")) is None


def _texto(p) -> str:
    return "".join(t.text or "" for t in p.iter(qn("w:t")))


def _paragrafo(p, pid: int) -> dict:
    ppr = p.find(qn("w:pPr"))
    b: dict = {"t": "p", "id": pid, "runs": [], "ed": _editavel(p)}
    if ppr is not None:
        jc = ppr.find(qn("w:jc"))
        if jc is not None:
            b["al"] = {"both": "justify", "center": "center", "right": "right", "end": "right"}.get(jc.get(qn("w:val")), "left")
        sp = ppr.find(qn("w:spacing"))
        if sp is not None:
            for k, nome in (("before", "antes"), ("after", "depois")):
                v = sp.get(qn(f"w:{k}"))
                if v and v.lstrip("-").isdigit():
                    b[nome] = int(v) / 20
        ind = ppr.find(qn("w:ind"))
        if ind is not None:
            v = ind.get(qn("w:left")) or ind.get(qn("w:start"))
            if v and v.lstrip("-").isdigit():
                b["recuo"] = int(v) / 20
        shd = ppr.find(qn("w:shd"))
        if shd is not None and (shd.get(qn("w:fill")) or "auto") != "auto":
            b["fundo"] = shd.get(qn("w:fill"))
        if _ligado(ppr.find(qn("w:pageBreakBefore"))):
            b["quebra"] = 1
        st = ppr.find(qn("w:pStyle"))
        if st is not None:
            nome = st.get(qn("w:val")) or ""
            if nome.startswith("ListBullet"):
                b["lista"] = 1
            if nome.startswith("ListNumber"):
                b["lista"] = 2
            if nome.startswith("TOC"):
                b["sumario"] = 1
        bd = ppr.find(qn("w:pBdr"))
        if bd is not None and bd.find(qn("w:bottom")) is not None:
            b["linha"] = bd.find(qn("w:bottom")).get(qn("w:color")) or "999999"
    imgs = []
    for d in p.iter(qn("w:drawing")):
        ext = d.find(f".//{_NS_WP}extent")
        imgs.append({"w": round(int(ext.get("cx")) / 9525) if ext is not None else 300,
                     "h": round(int(ext.get("cy")) / 9525) if ext is not None else 200})
    if imgs:
        b["imgs"] = imgs
    for r in p.iter(qn("w:r")):
        # quebra de linha e tabulação só aparecem na tela (o trecho com elas não é editável)
        x = "".join((c.text or "") if c.tag == qn("w:t") else chr(10) if c.tag == qn("w:br")
                    else chr(9) if c.tag == qn("w:tab") else "" for c in r)
        if x:
            b["runs"].append({"x": x, **_fmt_run(r)})
    return b


def _chave(s: str) -> str:
    """Texto para comparar PDF × Word: sem marcadores de lista, espaços e caixa."""
    s = (s or "").replace("", " ").replace("•", " ").replace(" ", " ")
    return " ".join(s.split()).casefold()


def textos_para_paginas(body, ids: dict) -> list[tuple[int, str]]:
    """Os textos do documento na ordem de leitura: cada parágrafo e, nas tabelas, cada linha inteira (ligada ao 1º
    parágrafo da linha) antes das células."""
    out: list[tuple[int, str]] = []
    for el in body:
        if el.tag == qn("w:p"):
            out.append((ids[id(el)], _texto(el)))
        elif el.tag == qn("w:tbl"):
            for tr in el.iter(qn("w:tr")):
                ps = list(tr.iter(qn("w:p")))
                if not ps:
                    continue
                out.append((ids[id(ps[0])], " ".join(_texto(p) for p in ps)))
                out.extend((ids[id(p)], _texto(p)) for p in ps)
    return out


def marcas_de_pagina(pdf: Path, paragrafos: list[tuple[int, str]], quebras: set | None = None,
                     imagens: set | None = None) -> dict:
    """142: onde começa cada página do ÚLTIMO PDF, no editor. A página N do editor é a página N do PDF que os cartões
    citam. Para cada página, o começo do texto (sem cabeçalho e rodapé) é procurado nos parágrafos, sempre adiante da
    página anterior. Devolve {"N": nº do parágrafo}; página sem texto (só imagem) fica de fora."""
    if not Path(pdf).is_file():
        return {}
    import pymupdf
    try:
        doc = pymupdf.open(pdf)
    except Exception:                        # noqa: BLE001 — PDF que não abre: o editor segue sem marcas
        return {}
    textos = [(k, _chave(t)) for k, t in paragrafos]
    marcas: dict[str, int] = {}
    desde = 0
    ultimo = -1                              # onde terminou o texto da página anterior
    anteriores: set = set()
    with doc:
        for n, pg in enumerate(doc, 1):
            h = pg.rect.height
            corpo = [b for b in pg.get_text("blocks") if b[4].strip() and h * 0.07 < b[1] < h * 0.92]
            if not corpo:
                # 157: página só com imagem (ex.: tabela do anexo em figura): começa na próxima imagem do Word depois
                # do fim da página anterior
                figs = [i for i in pg.get_image_info() if h * 0.07 < i["bbox"][1] < h * 0.92]
                if imagens and figs:
                    for pos in range(max(ultimo + 1, desde + (1 if marcas else 0)), len(textos)):
                        if textos[pos][0] in imagens and not textos[pos][1]:
                            marcas[str(n)] = textos[pos][0]
                            desde = ultimo = pos
                            break
                continue
            achado = None
            # a página pode começar pelo cabeçalho repetido de uma tabela: os blocos iguais aos do começo da página
            # anterior são pulados; vale o 1º bloco novo
            chaves = [_chave(b[4])[:60] for b in corpo[:12]]
            novos = [k for k in chaves if len(k) >= 4 and k not in anteriores] or [k for k in chaves if len(k) >= 4]
            anteriores = set(chaves)
            # 157: o mesmo começo pode aparecer antes (ex.: a lista de anexos repete o título do anexo); se um parágrafo
            # com "quebra de página" antes começa exatamente assim, é ele (a página começa nele, como no Word)
            if quebras and novos:
                for pos in range(desde, len(textos)):
                    k, t = textos[pos]
                    if k in quebras and t and len(novos[0]) >= 8 and (t.startswith(novos[0]) or novos[0].startswith(t)):
                        achado = pos
                        break
            for inicio in ([] if achado is not None else novos[:3]):
                for alvo in (inicio, inicio[:30], inicio[:18]):
                    for pos in range(desde, len(textos)):
                        k, t = textos[pos]
                        if t and (alvo in t or (len(t) >= 8 and alvo.startswith(t))):
                            achado = pos
                            break
                    if achado is not None:
                        break
                if achado is not None:
                    break
            if achado is not None:
                marcas[str(n)] = textos[achado][0]
                desde = achado
            fim = _chave(corpo[-1][4])[:40]
            ultimo = desde
            if len(fim) >= 6:
                for pos in range(desde, len(textos)):
                    t = textos[pos][1]
                    if t and (fim in t or (len(t) >= 8 and fim.startswith(t))):
                        ultimo = pos
                        break
    return marcas


def documento(jid: str) -> dict:
    """O laudo editável em blocos para a tela: parágrafos (com a formatação de cada trecho), tabelas e imagens."""
    aberto = abrir(jid)                          # cria a cópia, ou atualiza sozinho a que ficou velha sem mudanças
    c = caminho(jid)
    with _trava:
        d = Document(str(c))
    body = d.element.body
    todos = list(body.iter(qn("w:p")))           # a lista fica viva: o número de cada parágrafo é a posição nela
    ids = {id(p): k for k, p in enumerate(todos)}
    blocos = []
    for el in body:
        if el.tag == qn("w:p"):
            blocos.append(_paragrafo(el, ids[id(el)]))
        elif el.tag == qn("w:tbl"):
            grid = [int(g.get(qn("w:w")) or 0) for g in el.iter(qn("w:gridCol"))]
            linhas = []
            for tr in el.findall(qn("w:tr")):
                cels = []
                for tc in tr.findall(qn("w:tc")):
                    tcpr = tc.find(qn("w:tcPr"))
                    cel: dict = {"ps": [_paragrafo(p, ids[id(p)]) for p in tc.findall(qn("w:p"))]}
                    if tcpr is not None:
                        gs = tcpr.find(qn("w:gridSpan"))
                        if gs is not None and (gs.get(qn("w:val")) or "").isdigit():
                            cel["span"] = int(gs.get(qn("w:val")))
                        shd = tcpr.find(qn("w:shd"))
                        if shd is not None and (shd.get(qn("w:fill")) or "auto") != "auto":
                            cel["fundo"] = shd.get(qn("w:fill"))
                        vm = tcpr.find(qn("w:vMerge"))
                        if vm is not None and vm.get(qn("w:val")) != "restart":
                            cel["junta"] = 1
                    cels.append(cel)
                linhas.append(cels)
            blocos.append({"t": "tab", "larguras": grid, "linhas": linhas})
    sec = d.sections[0]
    pdf, origem = pdf_das_folhas(jid)
    quebras = {ids[id(p)] for p in todos if (pp := p.find(qn("w:pPr"))) is not None and _ligado(pp.find(qn("w:pageBreakBefore")))}
    imagens = {ids[id(p)] for p in todos if p.find(f".//{qn('w:drawing')}") is not None}
    paginas = marcas_de_pagina(pdf, textos_para_paginas(body, ids), quebras, imagens)

    def mm(v):
        return round(v.mm, 1) if v is not None else 20
    return {"arquivo": c.name, "blocos": blocos, **situacao(jid), "aviso": aberto.get("aviso", ""),
            "paginas": paginas, "total_paginas": _total(pdf), "folhas_de": origem,
            "demarcaveis": _demarcaveis(jid, body, ids),
            "pagina": {"largura": mm(sec.page_width), "esq": mm(sec.left_margin), "dir": mm(sec.right_margin),
                       "topo": mm(sec.top_margin), "altura": mm(sec.page_height), "baixo": mm(sec.bottom_margin),
                       "corpo": _corpo_topo(pdf, sec.top_margin.pt if sec.top_margin is not None else 57)}}


def _corpo_topo(pdf: Path, topo_pt: float) -> float | None:
    """157: onde o texto começa na folha do PDF (mm) — o cabeçalho empurra o corpo para baixo da margem."""
    if not Path(pdf).is_file():
        return None
    import pymupdf
    try:
        with pymupdf.open(pdf) as doc:
            ys = []
            for pg in list(doc)[1:8]:
                b = [x[1] for x in pg.get_text("blocks") if x[4].strip() and topo_pt + 4 < x[1] < pg.rect.height * 0.5]
                if b:
                    ys.append(min(b))
    except Exception:                        # noqa: BLE001
        return None
    return round(min(ys) * 25.4 / 72, 1) if ys else None


def _demarcaveis(jid: str, body, ids: dict) -> dict:
    from . import editavel_imagem
    try:
        return editavel_imagem.demarcaveis(jid, body, ids)
    except Exception:                        # noqa: BLE001 — sem o botão de ajustar, o editor segue
        return {}


# ------------------------------------------------------------------ 157: as folhas do editor seguem o PDF
_trava_previa = threading.Lock()


def _previa(jid: str) -> Path:
    return db.pasta(jid) / PASTA / ".previa.pdf"


def pdf_das_folhas(jid: str) -> tuple[Path, str]:
    """O PDF que dá as folhas do editor: a prévia da cópia editável ([Atualizar páginas]) quando é mais nova que o
    PDF do laudo; senão, o próprio PDF do laudo."""
    final = _finais(jid)["pdf"]
    p = _previa(jid)
    if p.is_file() and (not final.is_file() or p.stat().st_mtime > final.stat().st_mtime):
        return p, "previa"
    return final, "laudo"


def _total(pdf: Path) -> int:
    if not Path(pdf).is_file():
        return 0
    import pymupdf
    try:
        with pymupdf.open(pdf) as doc:
            return doc.page_count
    except Exception:                        # noqa: BLE001
        return 0


def paginar(jid: str) -> dict:
    """[Atualizar páginas]: um PDF de prévia da cópia editável, só para o editor cortar as folhas como o PDF. O laudo
    (Word e PDF oficiais) não é tocado."""
    from . import pdf as _pdf
    c = _garantir(jid)
    pasta = db.pasta(jid) / PASTA / "_previa"
    with _trava_previa:
        pasta.mkdir(parents=True, exist_ok=True)
        tmp = pasta / "previa.docx"
        with _trava:
            shutil.copyfile(c, tmp)
        try:
            gerado = _pdf.converter(tmp)
        except Exception as e:               # noqa: BLE001
            raise ValueError(f"Não consegui refazer as páginas agora ({type(e).__name__}). Tente de novo.")
        shutil.move(str(gerado), _previa(jid))
        shutil.rmtree(pasta, ignore_errors=True)
    return {"total_paginas": _total(_previa(jid)), "feito_em": _agora().strftime("%H:%M:%S")}


def faixa(jid: str, n: int, parte: str) -> bytes:
    """157-2: o cabeçalho (parte="cab") ou o rodapé ("rod") da página N, recortado do PDF das folhas — igual ao PDF,
    com logo, linha amarela e "Pág. N". Só imagem: no editor não se edita."""
    import pymupdf
    pdf, _o = pdf_das_folhas(jid)
    if not pdf.is_file():
        raise LookupError("sem PDF")
    chave = (str(pdf), pdf.stat().st_mtime, n, parte)
    if chave in _FAIXAS:
        return _FAIXAS[chave]
    c = _garantir(jid)
    mc = (str(c), "margens")
    if mc not in _FAIXAS:                    # as margens do modelo: lidas uma vez (o Word tem 3 MB)
        with _trava:
            sec = Document(str(c)).sections[0]
        _FAIXAS[mc] = (sec.top_margin.pt if sec.top_margin is not None else 57,
                       sec.bottom_margin.pt if sec.bottom_margin is not None else 57)
    topo, baixo = _FAIXAS[mc]
    with pymupdf.open(pdf) as doc:
        if not 1 <= n <= doc.page_count:
            raise LookupError("página fora do PDF")
        pg = doc[n - 1]
        r = pg.rect
        # o cabeçalho vai até a linha amarela (logo abaixo da margem); o rodapé ocupa a margem de baixo
        clip = pymupdf.Rect(0, 0, r.width, topo + 4) if parte == "cab" else pymupdf.Rect(0, r.height - baixo, r.width, r.height)
        png = pg.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=clip).tobytes("png")
    if len(_FAIXAS) > 400:
        _FAIXAS.clear()
    _FAIXAS[chave] = png
    return png


_FAIXAS: dict = {}


def _trocar_texto(p, novo: str) -> None:
    """Põe `novo` no parágrafo mexendo só no pedaço que mudou: o começo e o fim iguais ficam nos seus trechos, com a
    formatação de cada um (o rótulo em negrito continua em negrito quando se corrige o resto da frase)."""
    ts = list(p.iter(qn("w:t")))
    velho = "".join(t.text or "" for t in ts)
    if velho == novo:
        return
    if not ts:
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = novo
        t.set(_ESPACO, "preserve")
        r.append(t)
        p.append(r)
        return
    a = 0
    while a < len(velho) and a < len(novo) and velho[a] == novo[a]:
        a += 1
    s = 0
    while s < len(velho) - a and s < len(novo) - a and velho[-1 - s] == novo[-1 - s]:
        s += 1
    fim = len(velho) - s                     # o miolo antigo é velho[a:fim]
    miolo = novo[a:len(novo) - s]
    # onde entra o miolo novo: no trecho que tem o 1º caractere trocado; inserção pura: no trecho que termina ali
    alvo, pos = None, 0
    for t in ts:
        n = len(t.text or "")
        if (a < fim and pos <= a < pos + n) or (a == fim and pos < a <= pos + n) or (a == fim == 0):
            alvo = t
            break
        pos += n
    if alvo is None:
        alvo = ts[-1]
    pos = 0
    for t in ts:
        x = t.text or ""
        n = len(x)
        antes = x[:max(0, min(n, a - pos))]
        depois = x[max(0, min(n, fim - pos)):]
        t.text = antes + (miolo if t is alvo else "") + depois
        t.set(_ESPACO, "preserve")
        pos += n


def _rodadas(p) -> list:
    return [r for r in p.iter(qn("w:r")) if r.find(qn("w:t")) is not None]


def _pt(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if 4 <= x <= 96 else None


def _hex(v) -> str:
    v = str(v or "").strip().lstrip("#").upper()
    return v if re.fullmatch("[0-9A-F]{6}", v) else ""


def _tirar(r, tag: str) -> None:
    rpr = r.find(qn("w:rPr"))
    if rpr is not None:
        for x in rpr.findall(qn(tag)):
            rpr.remove(x)


def _aplicar(r, quer: dict) -> None:
    """Põe no trecho só o que a tela diz que é diferente; o resto do trecho (estilo, espaçamento…) fica como está.
    Valor vazio (0 ou "") volta ao do estilo do Word."""
    from docx.enum.text import WD_COLOR_INDEX
    from docx.shared import Pt, RGBColor
    from docx.text.run import Run
    tem = _fmt_run(r)
    run = Run(r, None)
    for k, attr in (("b", "bold"), ("i", "italic"), ("u", "underline")):
        if k in quer and bool(quer[k]) != bool(tem.get(k)):
            setattr(run, attr, bool(quer[k]))
    if "sz" in quer:
        v = _pt(quer["sz"])
        if not quer["sz"]:
            if "sz" in tem:
                run.font.size = None
        elif v and v != tem.get("sz"):
            run.font.size = Pt(round(v * 2) / 2)
    if "cor" in quer:
        v = _hex(quer["cor"])
        if not v:
            if "cor" in tem:
                _tirar(r, "w:color")
        elif v != (tem.get("cor") or "").upper():
            run.font.color.rgb = RGBColor.from_string(v)
    if "fonte" in quer:
        v = str(quer["fonte"] or "").strip()
        if not v:
            if "fonte" in tem:
                _tirar(r, "w:rFonts")
        elif v in FONTES and v != tem.get("fonte"):
            run.font.name = v
            fo = r.find(qn("w:rPr")).find(qn("w:rFonts"))
            for a in ("w:eastAsia", "w:cs"):
                fo.set(qn(a), v)
    if "realce" in quer:
        v = _hex(quer["realce"])
        if v != (tem.get("realce") or "").upper():
            _tirar(r, "w:shd")
            _tirar(r, "w:highlight")
            if v in _HEX_REALCE:
                run.font.highlight_color = getattr(WD_COLOR_INDEX, _INDICE[_HEX_REALCE[v]])


def _formatar_trechos(p, runs: list) -> None:
    """151-3: a tela manda o parágrafo em trechos com a formatação de cada um. O texto já foi trocado; aqui cada trecho
    do Word é partido onde a formatação muda e recebe só o que mudou (o resto da formatação dele fica)."""
    quer: list[tuple[int, int, dict]] = []
    pos = 0
    for r in runs:
        x = _limpo(str(r.get("x") or ""))
        if x:
            quer.append((pos, pos + len(x), {k: v for k, v in r.items() if k != "x"}))
            pos += len(x)
    if not quer:
        return
    pos = 0
    for r in _rodadas(p):
        x = "".join(t.text or "" for t in r.findall(qn("w:t")))
        n = len(x)
        cortes = sorted({pos, pos + n, *[a for a, _b, _f in quer if pos < a < pos + n],
                         *[b for _a, b, _f in quer if pos < b < pos + n]})
        pedacos = []
        for a, b in zip(cortes, cortes[1:]):
            f = next((f for qa, qb, f in quer if qa <= a < qb), None)
            pedacos.append((x[a - pos:b - pos], f))
        if len(pedacos) == 1:
            if pedacos[0][1] is not None:
                _aplicar(r, pedacos[0][1])
        elif len(pedacos) > 1:
            modelo = copy.deepcopy(r)
            ant = r
            for k, (txt, f) in enumerate(pedacos):
                novo = r if k == 0 else copy.deepcopy(modelo)
                tt = novo.findall(qn("w:t"))
                for t in tt[1:]:
                    novo.remove(t)
                tt[0].text = txt
                tt[0].set(_ESPACO, "preserve")
                if k:
                    ant.addnext(novo)
                if f is not None:
                    _aplicar(novo, f)
                ant = novo
        pos += n


_LISTAS = {1: "ListBullet", 2: "ListNumber"}


def _formatar_p(d, p, formato: dict) -> None:
    """151-3: o que vale para o parágrafo todo — alinhamento, recuo, lista com marcador/numerada e quebra de página."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    from docx.text.paragraph import Paragraph
    par = Paragraph(p, None)
    if "al" in formato:
        par.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                         "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}.get(
            str(formato["al"]), WD_ALIGN_PARAGRAPH.LEFT)
    if "recuo" in formato:
        try:
            v = max(0.0, min(300.0, float(formato["recuo"] or 0)))
        except (TypeError, ValueError):
            v = 0.0
        par.paragraph_format.left_indent = Pt(v) if v else None
    if "lista" in formato:
        ppr = p.get_or_add_pPr()
        atual = ppr.style or ""
        try:
            quer = _LISTAS.get(int(formato["lista"] or 0))
        except (TypeError, ValueError):
            quer = None
        if quer:
            if quer not in {s.style_id for s in d.styles}:
                raise ValueError("Este documento não tem o estilo de lista do Word.")
            ppr.style = quer
        elif atual.startswith(("ListBullet", "ListNumber")):
            ppr.style = None
    if "quebra" in formato:
        par.paragraph_format.page_break_before = True if formato["quebra"] else None


def _abrir_doc(jid: str):
    c = _garantir(jid)
    d = Document(str(c))
    return c, d, list(d.element.body.iter(qn("w:p")))


def _limpo(s: str) -> str:
    s = (s or "").replace(" ", " ").replace("\r", " ").replace("\n", " ")
    return _CONTROLE.sub("", s)


def gravar(jid: str, pid: int, texto: str, base: str | None = None, runs: list | None = None,
           formato: dict | None = None, manter: bool = False) -> dict:
    """Salva o texto de um parágrafo (o salvar sozinho da tela). `base` = o texto que a tela tinha: se o documento já
    é outro (duas janelas abertas), não grava por cima e pede para recarregar."""
    from .orquestrador import ocupado
    if ocupado(jid):
        raise ValueError("O laudo está sendo montado agora. Espere terminar para editar.")
    texto = _limpo(texto)
    with _trava:
        c, d, ps = _abrir_doc(jid)
        if not 0 <= pid < len(ps):
            raise LookupError("O documento mudou. Recarregue o editor.")
        p = ps[pid]
        if base is not None and _limpo(base) != _limpo(_texto(p)):
            raise LookupError("Este trecho foi mudado em outra janela. Recarregue o editor.")
        if not _editavel(p) and (runs or texto != _limpo(_texto(p)) or not formato):
            raise ValueError("Este trecho é montado pelo sistema (sumário ou numeração) e não se edita aqui.")
        removido = False
        if runs is not None:                     # 151-3: o texto vem dos trechos (o que a tela formatou)
            runs = [r for r in runs if isinstance(r, dict)]
            texto = _limpo("".join(str(r.get("x") or "") for r in runs))
        if formato:
            _formatar_p(d, p, formato)
        if (not texto.strip() and p.getparent().tag == qn("w:body") and not list(p.iter(qn("w:drawing")))
                and not formato and not manter):
            p.getparent().remove(p)              # apagou a frase inteira: a linha some (não fica um buraco)
            removido = True
        else:
            _trocar_texto(p, texto)
            if runs:
                _formatar_trechos(p, runs)
        d.save(str(c))
        bloco = None if removido else _paragrafo(p, pid)
    return {"salvo_em": _agora().strftime("%H:%M:%S"), "removido": removido, "bloco": bloco}


def novo_paragrafo(jid: str, pid: int) -> dict:
    """Enter no fim de um parágrafo: abre um parágrafo novo logo abaixo, com a mesma formatação."""
    with _trava:
        c, d, ps = _abrir_doc(jid)
        if not 0 <= pid < len(ps):
            raise LookupError("O documento mudou. Recarregue o editor.")
        p = ps[pid]
        n = OxmlElement("w:p")
        ppr = p.find(qn("w:pPr"))
        if ppr is not None:
            ppr2 = copy.deepcopy(ppr)
            for tag in ("w:pageBreakBefore", "w:keepNext"):
                for x in ppr2.findall(qn(tag)):
                    ppr2.remove(x)
            n.append(ppr2)
        rs = [r for r in p.iter(qn("w:r")) if r.find(qn("w:t")) is not None]
        r = OxmlElement("w:r")
        if rs and rs[-1].find(qn("w:rPr")) is not None:
            r.append(copy.deepcopy(rs[-1].find(qn("w:rPr"))))
        t = OxmlElement("w:t")
        t.text = ""
        r.append(t)
        n.append(r)
        p.addnext(n)
        d.save(str(c))
        novo_id = list(d.element.body.iter(qn("w:p"))).index(n)
    return {"id": novo_id, "salvo_em": _agora().strftime("%H:%M:%S")}


def imagem(jid: str, pid: int, k: int = 0) -> tuple[bytes, str]:
    with _trava:
        _c, d, ps = _abrir_doc(jid)
        if not 0 <= pid < len(ps):
            raise LookupError("imagem não encontrada")
        blips = list(ps[pid].iter(f"{_NS_A}blip"))
        if not 0 <= k < len(blips):
            raise LookupError("imagem não encontrada")
        parte = d.part.related_parts[blips[k].get(f"{_NS_R}embed")]
        return parte.blob, parte.content_type
