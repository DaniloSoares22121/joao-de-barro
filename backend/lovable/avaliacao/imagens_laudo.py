"""ORDEM 172-3: o mapa da localização e a foto da capa (fachada demarcada) aprovados ANTES da montagem.

Na parada da escolha dos referenciais o avaliador vê as duas imagens como vão entrar no laudo e pode:
[Ajustar a demarcação] (desenhar o contorno) · [Refazer o mapa] (nova captura no zoom do lote) · [Aprovar a imagem].
O contorno ajustado fica guardado em _laudo/contorno_<qual>.json e a MONTAGEM o usa (docx_builder chama
contorno_do_avaliador). Ele só vale para a MESMA imagem limpa: outra foto de fachada ou um mapa novo descartam o ajuste.
O ajuste feito depois, no editor (167), também é guardado aqui, para a remontagem não desfazer.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import db

QUAIS = ("mapa", "capa")


def _pasta(jid: str) -> Path:
    p = db.pasta(jid) / "_laudo"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _hash(p: Path) -> str:
    return hashlib.sha1(p.read_bytes()).hexdigest()[:16] if p.is_file() else ""


# ------------------------------------------------------------------ o contorno do avaliador (usado na montagem)
# A "chave" diz de que imagem o contorno é: o mapa capturado (+ o polígono da localização) ou a foto da fachada (+ o
# contorno automático). Com a mesma chave, o recorte da montagem é o mesmo da prévia (as contas são as mesmas; a tarja
# da montagem não muda o tamanho). Mudou a foto ou o mapa: o ajuste antigo é ignorado.
def chave_mapa(jid: str) -> str:
    pol = (db.resultado(jid, "localizacao") or {}).get("poligono") or []
    return "mapa:" + _hash(db.pasta(jid) / "maps.png") + ":" + hashlib.sha1(json.dumps(pol).encode()).hexdigest()[:12]


def chave_capa(rel: str, contorno) -> str:
    return "capa:" + str(rel) + ":" + (hashlib.sha1(json.dumps(contorno).encode()).hexdigest()[:12] if contorno else "inteira")


def chave_atual(jid: str, qual: str) -> str:
    if qual == "mapa":
        return chave_mapa(jid)
    rel, contorno, caixa = _capa_da_montagem(jid)
    return chave_capa(rel or "", contorno or (["caixa", *caixa] if caixa else None))


def chave_da_caixa(rel: str, caixa) -> str:
    """A chave da capa quando a montagem recorta pela caixa da extração (sem contorno automático)."""
    return chave_capa(rel, ["caixa", *[int(v) for v in caixa]])


def guardar_contorno(jid: str, qual: str, chave: str, pontos: list) -> None:
    arq = _pasta(jid) / f"contorno_{qual}.json"
    if arq.is_file():                         # o desenho anterior fica guardado (nada se perde)
        from . import editavel
        guarda = db.pasta(jid) / "revisoes"
        guarda.mkdir(parents=True, exist_ok=True)
        (guarda / f"contorno-{qual}-{editavel._agora().strftime('%Y%m%d-%H%M%S')}.json").write_bytes(arq.read_bytes())
    arq.write_text(json.dumps(
        {"chave": chave, "pontos": [[int(x), int(y)] for x, y in pontos]}), encoding="utf-8")


def contorno_do_avaliador(jid: str, qual: str, chave: str) -> list | None:
    """O contorno desenhado pelo avaliador, se foi desenhado na MESMA imagem (mesma chave); senão None."""
    arq = _pasta(jid) / f"contorno_{qual}.json"
    try:
        d = json.loads(arq.read_text(encoding="utf-8")) if arq.is_file() else None
    except (OSError, ValueError):
        return None
    if not d or d.get("chave") != chave or len(d.get("pontos") or []) < 3:
        return None
    return [tuple(p) for p in d["pontos"]]


def _esquecer(jid: str, qual: str) -> None:
    (_pasta(jid) / f"contorno_{qual}.json").unlink(missing_ok=True)


# ------------------------------------------------------------------ prévia (as mesmas contas da montagem)
def _foto_da_capa(jid: str) -> str | None:
    return _capa_da_montagem(jid)[0]


def _capa_da_montagem(jid: str) -> tuple[str | None, list | None, tuple | None]:
    """(foto, contorno automático, caixa da extração) — a MESMA escolha do docx_builder._capa: a fachada marcada pelo
    avaliador; senão a 1ª das fotos do relatório (escolha_laudo.escolher_fotos); a caixa só vale para a foto dela."""
    from PIL import Image

    from . import escolha_laudo
    from .agentes import fachada
    from .docx_builder import _EXT_IMG, _caixas, _campos
    pasta = db.pasta(jid)

    def arq(rel):
        p = (pasta / rel).resolve() if rel else None
        try:
            return p if p is not None and p.is_file() and p.relative_to(pasta.resolve()) else None
        except ValueError:
            return None
    ext = db.resultado(jid, "extracao") or {}
    marcada = db.fachada(jid)
    lista = escolha_laudo.escolher_fotos(list(ext.get("fotos") or []), arq, marcada,
                                         escolha_laudo.prints_medicao(_campos(jid)))
    fotos = [f.get("arquivo") for f in lista if arq(f.get("arquivo", "")) and arq(f.get("arquivo", "")).suffix.lower() in _EXT_IMG]
    if not fotos:
        return None, None, None
    rel, caixa = fotos[0], ext.get("fachada_caixa")
    exts = sorted(ext.get("fotos") or [], key=lambda f: f.get("ordem", 0))
    if marcada and exts and exts[0].get("arquivo") != marcada:
        caixa = None
    if marcada and marcada != rel:
        p = arq(marcada)
        if p is not None and p.suffix.lower() in _EXT_IMG:
            rel, caixa = marcada, None
    contorno = fachada.resultado(jid, rel)
    cx = None
    if not contorno and caixa:
        with Image.open(pasta / rel) as im:
            w, h = im.size
        c = _caixas([caixa], w, h)
        cx = tuple(int(v) for v in c[0]) if c else None
    return rel, contorno, cx


def _previa_mapa(jid: str) -> dict:
    from . import imagens
    from .docx_builder import MAPA, mapa_utilizavel
    maps = db.pasta(jid) / "maps.png"
    if not maps.is_file() or not mapa_utilizavel(maps):
        return {"existe": False, "motivo": "O mapa ainda não foi capturado (ou veio em branco). Toque em [Refazer o mapa]."}
    pol = (db.resultado(jid, "localizacao") or {}).get("poligono") or []
    limpa, pol2 = imagens.recortar_mapa(maps, pol if len(pol) >= 3 else [], _pasta(jid) / "previa_mapa_limpa.png",
                                        proporcao=MAPA[0] / MAPA[1], avisos=[])
    return {"existe": True, "limpa": Path(limpa), "auto": [tuple(map(int, p)) for p in pol2]}


def _previa_capa(jid: str) -> dict:
    from . import imagens
    from .agentes import fachada
    from .docx_builder import _recorte_fachada
    rel, contorno, caixa = _capa_da_montagem(jid)
    if not rel or not (db.pasta(jid) / rel).is_file():
        return {"existe": False, "motivo": "Ainda não há foto da fachada marcada neste trabalho."}
    origem = db.pasta(jid) / rel
    destino = _pasta(jid) / "previa_capa_limpa.jpg"
    from .agentes import _comum
    if fachada.eh_edificio(_comum.trabalho(jid).tipo) and not contorno:
        return {"existe": False, "motivo": "Foto do condomínio: sem a torre identificada com segurança, a capa sai sem "
                                           "demarcação (regra do Alan)."}
    if contorno:
        xs, ys = [p[0] for p in contorno], [p[1] for p in contorno]
        limpa, cx = _recorte_fachada(origem, (min(xs), min(ys), max(xs), max(ys)), destino, folga=1.25)
        dx, dy = min(xs) - cx[0], min(ys) - cx[1]
        auto = [(x - dx, y - dy) for x, y in contorno]
    elif caixa:                                # sem contorno: a montagem recorta pela caixa da extração (folga 1.6)
        limpa, cr = _recorte_fachada(origem, caixa, destino)
        x0, y0, x1, y1 = cr
        auto = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    else:
        limpa, auto = origem, []
    if Path(limpa) != destino:                 # a foto inteira serve (recorte ≥ 95%): a prévia limpa é ela mesma
        imagens.recortar(Path(limpa), _caixa_inteira(Path(limpa)), destino)
    return {"existe": True, "limpa": destino, "auto": auto, "foto": rel}


def _caixa_inteira(p: Path) -> tuple[int, int, int, int]:
    from PIL import Image
    with Image.open(p) as im:
        return (0, 0, im.size[0], im.size[1])


def _previa(jid: str, qual: str) -> dict:
    if qual not in QUAIS:
        raise LookupError("imagem desconhecida")
    return _previa_mapa(jid) if qual == "mapa" else _previa_capa(jid)


def _aprovadas(jid: str) -> dict:
    try:
        return json.loads(db.setting(f"imagens_aprovadas:{jid}") or "{}")
    except ValueError:
        return {}


def estado(jid: str) -> dict:
    """As duas imagens para a tela: existe? aprovada? o contorno é do avaliador? (desenha a prévia demarcada)."""
    from . import imagens
    ap = _aprovadas(jid)
    out = {}
    for qual in QUAIS:
        try:
            pv = _previa(jid, qual)
        except Exception as e:                 # noqa: BLE001 — uma imagem com problema não derruba a outra
            out[qual] = {"existe": False, "motivo": f"Não consegui preparar a imagem ({type(e).__name__})."}
            continue
        if not pv.get("existe"):
            out[qual] = {"existe": False, "motivo": pv.get("motivo", "")}
            continue
        meu = contorno_do_avaliador(jid, qual, chave_atual(jid, qual))
        pts = meu or pv["auto"]
        dem = _pasta(jid) / f"previa_{qual}.png"
        if len(pts) >= 3:
            imagens.demarcar(pv["limpa"], pts, dem)
        else:
            imagens.recortar(pv["limpa"], _caixa_inteira(pv["limpa"]), dem)
        aprov = ap.get(qual) or {}
        vale = aprov.get("chave") == chave_atual(jid, qual) and aprov.get("contorno") == _hash_pontos(pts)
        out[qual] = {"existe": True, "do_avaliador": bool(meu), "sem_contorno": len(pts) < 3,
                     "aprovada_em": aprov.get("em") if vale else None,
                     "v": _hash(dem)}
    return out


def _hash_pontos(pts) -> str:
    return hashlib.sha1(json.dumps([[int(x), int(y)] for x, y in pts or []]).encode()).hexdigest()[:12]


def _parado(jid: str) -> None:
    """6: nada de mexer nas imagens enquanto o laudo está sendo montado (a montagem lê os mesmos arquivos)."""
    from .orquestrador import ocupado
    if ocupado(jid):
        raise RuntimeError("O laudo está sendo montado agora. Espere terminar e toque de novo.")


def arquivo(jid: str, qual: str, limpa: bool) -> tuple[bytes, str]:
    nome = f"previa_{qual}_limpa.{'png' if qual == 'mapa' else 'jpg'}" if limpa else f"previa_{qual}.png"
    p = _pasta(jid) / nome
    if qual not in QUAIS or not p.is_file():
        raise LookupError("imagem ainda não preparada")
    return p.read_bytes(), "image/png" if p.suffix == ".png" else "image/jpeg"


def info(jid: str, qual: str) -> dict:
    """Para a janela de desenhar (a mesma do editor): tamanho da imagem limpa e o contorno de agora."""
    from PIL import Image
    pv = _previa(jid, qual)
    if not pv.get("existe"):
        raise LookupError(pv.get("motivo") or "imagem indisponível")
    with Image.open(pv["limpa"]) as im:
        w, h = im.size
    pts = contorno_do_avaliador(jid, qual, chave_atual(jid, qual)) or pv["auto"]
    return {"qual": qual, "largura": w, "altura": h, "contorno": [list(p) for p in pts],
            "forma": "retangulo" if qual == "mapa" else "livre"}


def ajustar(jid: str, qual: str, pontos: list) -> dict:
    from . import editavel
    _parado(jid)
    pv = _previa(jid, qual)
    if not pv.get("existe"):
        raise LookupError(pv.get("motivo") or "imagem indisponível")
    from PIL import Image
    with Image.open(pv["limpa"]) as im:
        w, h = im.size
    pts = []
    for p in pontos or []:
        try:
            pts.append((min(max(int(round(float(p[0]))), 0), w - 1), min(max(int(round(float(p[1]))), 0), h - 1)))
        except (TypeError, ValueError, IndexError):
            continue
    if len(pts) < 3:
        raise ValueError("Desenhe o contorno em volta do imóvel (pelo menos 3 pontos) e salve de novo.")
    guardar_contorno(jid, qual, chave_atual(jid, qual), pts)
    db.evento(jid, "selecao", "info", f"demarcação {'do mapa' if qual == 'mapa' else 'da capa'} ajustada pelo avaliador "
              "antes da montagem (a montagem usa este contorno)")
    return {"ok": True, "salvo_em": editavel._agora().strftime("%H:%M:%S")}


def aprovar(jid: str, qual: str) -> dict:
    from . import editavel
    _parado(jid)
    pv = _previa(jid, qual)
    if not pv.get("existe"):
        raise LookupError(pv.get("motivo") or "imagem indisponível")
    ap = _aprovadas(jid)
    em = editavel._agora().strftime("%H:%M")
    pts = contorno_do_avaliador(jid, qual, chave_atual(jid, qual)) or pv["auto"]
    ap[qual] = {"em": em, "chave": chave_atual(jid, qual), "contorno": _hash_pontos(pts)}
    db.set_setting(f"imagens_aprovadas:{jid}", json.dumps(ap))
    db.evento(jid, "selecao", "info", f"imagem {'do mapa' if qual == 'mapa' else 'da capa'} aprovada pelo avaliador")
    return {"ok": True, "aprovada_em": em}


async def refazer_mapa(jid: str) -> dict:
    _parado(jid)
    r = await refazer_com_volta(jid)
    if not r.get("ok"):
        return {"ok": False, "motivo": "Mantive o mapa atual: " + str(r.get("motivo") or "a captura não deu certo")}
    _esquecer(jid, "mapa")                    # mapa novo: o contorno desenhado no mapa velho não serve mais
    return {"ok": True, "motivo": str(r.get("motivo") or "mapa refeito")}


async def refazer_com_volta(jid: str) -> dict:
    """A captura nova (imagens_pedido.refazer_demarcacao) com o mapa de antes guardado: se não der certo, o maps.png
    de antes volta — o "Mantive o mapa atual" é verdade (a captura grava o arquivo antes de achar o contorno)."""
    import shutil

    from .imagens_pedido import refazer_demarcacao
    maps = db.pasta(jid) / "maps.png"
    copia = _pasta(jid) / "maps_antes_de_refazer.png"
    if maps.is_file():
        shutil.copy2(maps, copia)
    try:
        r = await refazer_demarcacao(jid)
    except Exception as e:                     # noqa: BLE001
        r = {"ok": False, "motivo": f"a captura falhou ({type(e).__name__})"}
    if not r.get("ok") and copia.is_file():
        shutil.copy2(copia, maps)
    copia.unlink(missing_ok=True)
    return r


async def preparar_capa(jid: str) -> None:
    """O contorno automático da fachada (IA leve, 1× por foto) normalmente sai na montagem; aqui ele sai antes, para a
    capa aparecer para aprovar. Falhou: a capa aparece sem contorno e o avaliador desenha."""
    from .agentes import fachada
    chave = (jid, db.fachada(jid) or "")
    if chave in _TENTADAS:                     # 174: uma tentativa por foto (o quadro se atualiza a cada toque)
        return
    _TENTADAS.add(chave)
    try:
        await fachada.garantir(jid)
    except Exception:                          # noqa: BLE001
        pass


_TENTADAS: set = set()


# ------------------------------------------------------------------ 172-3: [Baixar a imagem] na parte de imagens
def _itens(jid: str) -> list[dict]:
    """As imagens do laudo (172-3/182/187), cada uma com o arquivo no disco — a tela só conhece o "id"."""
    pasta, lau = db.pasta(jid), _pasta(jid)
    out: list[dict] = []

    def primeiro(*nomes):
        return next((lau / n for n in nomes if (lau / n).is_file()), None)
    for ident, rotulo, arq in (
            ("capa", "Capa – foto da fachada demarcada", primeiro("capa_demarcada.png", "previa_capa.png")),
            ("capa_limpa", "Capa – foto da fachada sem o contorno (para redesenhar)", primeiro("capa_recorte.jpg", "previa_capa_limpa.jpg")),
            ("mapa", "Mapa da localização", primeiro("mapa_demarcado.png", "previa_mapa.png")),
            ("mapa_limpa", "Mapa da localização sem o contorno (para redesenhar)", primeiro("mapa_recorte.png", "previa_mapa_limpa.png"))):
        if arq is not None:
            out.append({"id": ident, "rotulo": rotulo, "arquivo": f"{ident}{arq.suffix}", "caminho": arq})
    fotos = sorted((db.resultado(jid, "extracao") or {}).get("fotos") or [], key=lambda f: f.get("ordem", 0))
    do_laudo = set()
    for k, f in enumerate(fotos, 1):
        rel = str(f.get("arquivo") or "")
        if not rel or not (pasta / rel).is_file():
            continue
        do_laudo.add(rel)
        tarjada = lau / "tarjadas" / Path(rel).name
        out.append({"id": f"foto{k}", "rotulo": f"Foto {k:02d}" + (f" – {f['legenda']}" if f.get("legenda") else ""),
                    "arquivo": Path(rel).name, "caminho": tarjada if tarjada.is_file() else pasta / rel})
    # 187: as fotos que chegaram DEPOIS do laudo pronto (as últimas N enviadas; N = fotos_novas) aparecem aqui para o
    # avaliador pôr no Word. As fotos que a extração deixou fora do laudo não são "novas".
    try:
        n_novas = int(db.setting(f"fotos_novas:{jid}") or 0)
    except ValueError:
        n_novas = 0
    candidatas = [a for a in db.arquivos(jid) if a.get("tipo") == "foto" and str(a.get("caminho") or "") not in do_laudo
                  and Path(str(a.get("caminho") or "")).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
                  and (pasta / str(a.get("caminho"))).is_file()]
    k = 0
    for a in (candidatas[-n_novas:] if n_novas > 0 else []):
        rel = str(a.get("caminho") or "")
        k += 1
        out.append({"id": f"nova{k}", "rotulo": f"Foto nova (não está no laudo) – {Path(rel).name}",
                    "arquivo": Path(rel).name, "caminho": pasta / rel, "nova": True})
    return out


def lista(jid: str) -> list[dict]:
    """As imagens do laudo: capa e mapa (demarcados e limpos), as fotos do relatório (já com as tarjas do laudo) e as
    fotos novas. Sem caminho: a tela pede pelo "id"."""
    return [{k: v for k, v in it.items() if k != "caminho"} for it in _itens(jid)]


_TIPOS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def baixar(jid: str, ident: str) -> tuple[bytes, str, str]:
    """(dados, tipo, nome) de uma imagem da lista — só as da lista (nada de caminho vindo da tela)."""
    it = next((x for x in _itens(jid) if x["id"] == ident), None)
    if it is None or not it["caminho"].is_file():
        raise LookupError("imagem não encontrada")
    arq = it["caminho"]
    return arq.read_bytes(), _TIPOS.get(arq.suffix.lower(), "application/octet-stream"), it["arquivo"]


def miniatura(jid: str, ident: str, lado: int = 160) -> bytes:
    """182-3: miniatura leve (JPEG reduzido) de uma imagem da lista."""
    import io

    from PIL import Image, ImageOps
    it = next((x for x in _itens(jid) if x["id"] == ident), None)
    if it is None or not it["caminho"].is_file():
        raise LookupError("imagem não encontrada")
    lado = max(48, min(int(lado or 160), 480))
    with Image.open(it["caminho"]) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((lado, lado))
        b = io.BytesIO()
        im.save(b, "JPEG", quality=80)
        return b.getvalue()
