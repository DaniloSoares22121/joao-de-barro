"""ORDEM 167-1: as imagens demarcadas do laudo (foto da fachada da capa e mapa da localização) ajustadas DENTRO do
editor, sem pedir no chat e sem refazer o laudo.

- demarcaveis(body, ids): quais linhas de imagem do Word editável são a capa ("Imagem 01") e o mapa ("Imagem 02").
- limpa(jid, qual): a imagem limpa, sem contorno (_laudo/capa_recorte.jpg ou _laudo/mapa_recorte.png), e o contorno
  de agora (o do mapa sai da localização gravada; o da capa começa vazio — o avaliador desenha).
- ajustar(jid, qual, pontos): o avaliador desenhou o contorno (retângulo no mapa; contorno livre na fachada) em pixels
  da imagem limpa; refaz a imagem demarcada (linha fina, D-129/D-130) e troca a figura no Word editável, do mesmo
  tamanho. Sai igual no PDF no [Concluir].
- refazer_mapa(jid): nova captura do Google Maps no zoom do lote (a do 132/134, imagens_pedido.refazer_demarcacao) e
  a imagem do mapa refeita no Word editável. Se a captura falhar, a imagem atual fica e a frase diz por quê.
"""
from __future__ import annotations

from pathlib import Path

from docx.oxml.ns import qn

from . import db

LEGENDA = {"capa": "Imagem 01", "mapa": "Imagem 02"}
LIMPA = {"capa": "capa_recorte.jpg", "mapa": "mapa_recorte.png"}


def _texto(p) -> str:
    return "".join(t.text or "" for t in p.iter(qn("w:t")))


def _paragrafo_da_imagem(body, qual: str):
    """A linha com a figura logo antes da legenda "Imagem 01"/"Imagem 02" (a montagem põe a figura antes dela)."""
    alvo = LEGENDA[qual]
    for p in body.iter(qn("w:p")):
        if _texto(p).strip().startswith(alvo):
            ant = p.getprevious()
            while ant is not None and ant.tag == qn("w:p") and ant.find(f".//{qn('w:drawing')}") is None \
                    and not _texto(ant).strip():
                ant = ant.getprevious()          # linha vazia entre a figura e a legenda
            if ant is not None and ant.tag == qn("w:p") and ant.find(f".//{qn('w:drawing')}") is not None:
                return ant
            return None
    return None


def demarcaveis(jid: str, body, ids: dict) -> dict:
    """{nº do parágrafo da figura: "capa"|"mapa"} — só quando há a imagem limpa para ajustar."""
    out = {}
    for qual in ("capa", "mapa"):
        p = _paragrafo_da_imagem(body, qual)
        if p is not None and id(p) in ids and (_pasta(jid) / LIMPA[qual]).is_file():
            out[str(ids[id(p)])] = qual
    return out


def _pasta(jid: str) -> Path:
    return db.pasta(jid) / "_laudo"


def _poligono_mapa(jid: str) -> list:
    """O contorno de agora do mapa, em pixels da imagem limpa (o mesmo cálculo da montagem)."""
    from . import imagens
    from .docx_builder import MAPA
    maps = db.pasta(jid) / "maps.png"
    loc = db.resultado(jid, "localizacao") or {}
    pol = loc.get("poligono") or []
    if not maps.is_file() or len(pol) < 3:
        return []
    tmp = _pasta(jid) / "_tmp_recorte.png"
    try:
        _img, pol2 = imagens.recortar_mapa(maps, pol, tmp, proporcao=MAPA[0] / MAPA[1], avisos=[])
    except Exception:                          # noqa: BLE001
        return []
    finally:
        tmp.unlink(missing_ok=True)
    return [[int(x), int(y)] for x, y in pol2]


def limpa(jid: str, qual: str) -> dict:
    from PIL import Image
    if qual not in LIMPA:
        raise LookupError("imagem desconhecida")
    arq = _pasta(jid) / LIMPA[qual]
    if not arq.is_file():
        raise LookupError("Esta imagem não tem a versão limpa guardada; refaça o laudo uma vez para ajustar.")
    with Image.open(arq) as im:
        w, h = im.size
    return {"qual": qual, "largura": w, "altura": h, "contorno": _poligono_mapa(jid) if qual == "mapa" else [],
            "forma": "retangulo" if qual == "mapa" else "livre"}


def arquivo_limpo(jid: str, qual: str) -> tuple[bytes, str]:
    arq = _pasta(jid) / LIMPA.get(qual, "-")
    if not arq.is_file():
        raise LookupError("sem imagem limpa")
    return arq.read_bytes(), "image/png" if arq.suffix == ".png" else "image/jpeg"


def _trocar_no_word(jid: str, qual: str, img: Path) -> int:
    """Troca a figura (capa ou mapa) no Word editável, do mesmo tamanho de agora. Devolve o nº do parágrafo."""
    from docx import Document

    from . import editavel
    from .docx_partes import medida_imagem, trocar_imagem
    with editavel._trava:
        c = editavel._garantir(jid)
        d = Document(str(c))
        body = d.element.body
        p = _paragrafo_da_imagem(body, qual)
        if p is None:
            raise LookupError("Não achei a imagem no documento (a legenda “%s” sumiu?)." % LEGENDA[qual])
        cx, cy = medida_imagem(p)
        trocar_imagem(p, d.part, img, cx, cy)
        d.save(str(c))
        return list(body.iter(qn("w:p"))).index(p)


def ajustar(jid: str, qual: str, pontos: list) -> dict:
    """O contorno desenhado pelo avaliador vira a demarcação da imagem (linha fina, vermelha)."""
    from PIL import Image

    from . import editavel, imagens
    from .orquestrador import ocupado
    if ocupado(jid):
        raise ValueError("O laudo está sendo montado agora. Espere terminar para ajustar a imagem.")
    if qual not in LIMPA:
        raise LookupError("imagem desconhecida")
    arq = _pasta(jid) / LIMPA[qual]
    if not arq.is_file():
        raise LookupError("Esta imagem não tem a versão limpa guardada.")
    with Image.open(arq) as im:
        w, h = im.size
    pts = []
    for p in pontos or []:
        try:
            x, y = int(round(float(p[0]))), int(round(float(p[1])))
        except (TypeError, ValueError, IndexError):
            continue
        pts.append((min(max(x, 0), w - 1), min(max(y, 0), h - 1)))
    if len(pts) < 3:
        raise ValueError("Desenhe o contorno em volta do imóvel (pelo menos 3 pontos) e salve de novo.")
    destino = _pasta(jid) / f"{qual}_demarcada_avaliador.png"
    img = imagens.demarcar(arq, pts, destino)
    try:                                       # 172-3: a remontagem também usa este contorno (mesma imagem)
        from . import imagens_laudo
        imagens_laudo.guardar_contorno(jid, qual, imagens_laudo.chave_atual(jid, qual), pts)
    except Exception:                          # noqa: BLE001
        pass
    pid = _trocar_no_word(jid, qual, img)
    db.evento(jid, "revisao", "info", f"demarcação da {'capa' if qual == 'capa' else 'imagem do mapa'} ajustada pelo "
              "avaliador no editor (contorno desenhado à mão)", dados={"pontos": pts[:200]})
    return {"ok": True, "id": pid, "salvo_em": editavel._agora().strftime("%H:%M:%S")}


async def refazer_mapa(jid: str) -> dict:
    """[Refazer o mapa]: nova captura no zoom do lote; se der certo, a imagem do mapa é refeita no Word editável."""
    import asyncio

    from . import editavel, imagens
    from .docx_builder import MAPA
    from .imagens_laudo import refazer_com_volta
    r = await refazer_com_volta(jid)        # 174-1: se falhar, o maps.png de antes volta
    if not r.get("ok"):
        return {"ok": False, "motivo": "Mantive o mapa atual: " + str(r.get("motivo") or "a captura não deu certo")}
    maps = db.pasta(jid) / "maps.png"
    loc = db.resultado(jid, "localizacao") or {}
    pol = loc.get("poligono") or []

    def _montar():
        img, pol2 = imagens.recortar_mapa(maps, pol if len(pol) >= 3 else [], _pasta(jid) / "mapa_recorte.png",
                                          proporcao=MAPA[0] / MAPA[1], avisos=[])
        if len(pol2) >= 3:
            img = imagens.demarcar(img, [tuple(map(int, p)) for p in pol2], _pasta(jid) / "mapa_demarcado.png")
        return _trocar_no_word(jid, "mapa", img)
    pid = await asyncio.to_thread(_montar)
    db.evento(jid, "revisao", "info", "mapa da localização refeito pelo avaliador no editor: " + str(r.get("motivo")))
    return {"ok": True, "motivo": str(r.get("motivo") or "mapa refeito"), "id": pid,
            "salvo_em": editavel._agora().strftime("%H:%M:%S")}

