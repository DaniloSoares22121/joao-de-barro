"""ORDEM 076-A: mexer nos anúncios pelos Detalhes (barra "Anúncios"), sem voltar à tela de escolha.

- GET  /jobs/{jid}/amostra              valor do laudo × valor com a amostra de agora (média, CV, faixa)
- POST /jobs/{jid}/amostra              grava a amostra nova (tirar / pôr), SEM gerar o laudo
- POST /jobs/{jid}/amostra/gerar        "Gerar a REVISÃO N com a amostra nova" (o toque do avaliador, D-070)
- POST /jobs/{jid}/amostra/{n}/corrigir corrige preço, área, lote e foto de um anúncio

Tudo passa pela mesma confirmação do "Confirmar valor" (PUT /referenciais): mesmos filtros, mesma prévia.
"""
from __future__ import annotations

import re
import statistics
from decimal import Decimal

from fastapi import Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from . import db
from .routes import EscolhaReferenciais, _dono, _job, _livre, _num_form, escolher_referenciais, router

MINIMO = 5


def _laudo(jid: str) -> tuple[dict | None, list[int]]:
    """O cálculo do último laudo gerado e a amostra que ele usou."""
    with db._conn() as c:
        calc = c.execute("SELECT id, dados_json FROM av_events WHERE job=? AND etapa='calculo' AND nivel='resultado' "
                         "AND dados_json IS NOT NULL ORDER BY id DESC LIMIT 1", (jid,)).fetchone()
        if not calc:
            return None, []
        sel = c.execute("SELECT dados_json FROM av_events WHERE job=? AND etapa='selecao' AND nivel='resultado' "
                        "AND dados_json IS NOT NULL AND id < ? ORDER BY id DESC LIMIT 1", (jid, calc["id"])).fetchone()
    import json
    d = json.loads(calc["dados_json"])
    esc = [r["n"] for r in (json.loads(sel["dados_json"]).get("refs") or []) if r.get("escolhido")] if sel else []
    return d, esc


def _agora(jid: str) -> dict:
    from . import calculo
    from .agentes import selecao
    sel = db.resultado(jid, "selecao") or {}
    # 094-1: "Só comparação" (D-069) nunca entra na conta, mesmo que tenha ficado marcado
    esc = [r for r in db.candidatos(jid) if r.escolhido and r.decisao != "comparacao"]
    out = {"escolhidos": [r.n for r in esc], "n": len(esc), "valor": None, "media": None, "cv": None,
           "valor_min": None, "valor_max": None}
    if not esc or not selecao.escolha_area(jid):
        return out
    try:
        area = selecao.area_construida(jid)
        unit = Decimal(str(sel["unitario_adotado"])) if sel.get("unitario_adotado") not in (None, "") else None
        faixa = Decimal(str(sel.get("faixa_pct") or selecao.FAIXA_PADRAO))
        na_base = selecao.refs_na_base(jid, esc, selecao.base_area(jid))
        try:
            res = calculo.calcular(area, na_base, unit, faixa)
        except ValueError:                       # unitário antigo fora do intervalo novo: vale a média
            res = calculo.calcular(area, na_base, None, faixa)
    except (ValueError, TypeError):
        return out
    us = [float(x) for x in res.unitarios]
    cv = statistics.stdev(us) / statistics.mean(us) if len(us) >= 2 and statistics.mean(us) else None
    return {**out, "valor": str(res.valor_adotado), "media": str(res.media), "cv": round(cv * 100, 2) if cv else None,
            "valor_min": str(res.valor_min), "valor_max": str(res.valor_max)}


def estado(jid: str) -> dict:
    laudo, esc_laudo = _laudo(jid)
    agora = _agora(jid)
    with db._conn() as c:
        geracoes = c.execute("SELECT COUNT(*) FROM av_events WHERE job=? AND etapa='entrega' AND nivel='resultado'",
                             (jid,)).fetchone()[0]
    valor_laudo = (laudo or {}).get("valor_adotado")
    mudou = bool(laudo) and (sorted(agora["escolhidos"]) != sorted(esc_laudo)
                             or (agora["valor"] is not None and str(agora["valor"]) != str(valor_laudo)))
    return {"laudo": {"valor": valor_laudo, "escolhidos": esc_laudo}, "agora": agora, "mudou": mudou,
            "minimo": MINIMO, "abaixo_do_minimo": agora["n"] < MINIMO, "revisao": max(1, geracoes),
            "refs": _cartoes(jid), "ultimo_envio": _ultimo_envio(jid)}


def _ultimo_envio(jid: str) -> dict | None:
    """086-5: "Recebi o anúncio 5 às 01h02" na tela do JdB (o aviso da extensão pode ficar escondido na página)."""
    import re
    with db._conn() as c:
        r = c.execute("SELECT msg, ts FROM av_events WHERE job=? AND etapa='pesquisa' AND msg LIKE '%(Chrome)%' "
                      "ORDER BY id DESC LIMIT 1", (jid,)).fetchone()
    if not r:
        return None
    m = re.search(r"n[ºo°]\s*(\d+)", r["msg"])
    return {"n": int(m.group(1)) if m else None, "quando": r["ts"]}


def _cartoes(jid: str) -> dict[str, dict]:
    """082-A1: o essencial para o avaliador reconhecer cada anúncio no cartão: foto, rua, bairro e lote."""
    out = {}
    for r in db.candidatos(jid):
        un = round(r.preco / r.area_m2, 2) if r.preco and r.area_m2 else None
        out[str(r.n)] = {"rua": (getattr(r, "rua", "") or "").strip(), "bairro": (r.bairro or "").strip(),
                         "lote_m2": r.lote_m2, "area_m2": r.area_m2, "preco": r.preco, "unitario": un,
                         "foto": bool(r.foto) and not r.foto.startswith(("http:", "https:")),
                         # 082-2: o que a página mostra hoje e é diferente do guardado (pergunta Manter/Trocar)
                         "divergencia": dict(getattr(r, "divergencia_pagina", None) or {})}
    return out


class Amostra(BaseModel):
    escolhidos: list[int]


class Gerar(BaseModel):
    confirmacao: str = ""


def _unitario(jid: str) -> tuple[str | None, str | None]:
    sel = db.resultado(jid, "selecao") or {}
    u = sel.get("unitario_adotado")
    if u in (None, ""):
        return None, None
    return str(u).replace(".", ","), sel.get("justificativa_unitario") or None


async def _gravar(jid: str, escolhidos: list[int], continuar: bool = False, conf: str = "") -> None:
    from .agentes import selecao
    esc = selecao.escolha_area(jid) or {}
    u, just = _unitario(jid)
    corpo = dict(escolhidos=escolhidos, continuar=continuar, confirmacao_alertas=conf or None,
                 base_area=esc.get("base"), area_campo=esc.get("campo"))
    try:
        await escolher_referenciais(jid, EscolhaReferenciais(**corpo, unitario_adotado=u, justificativa=just), _u={})
    except HTTPException as e:
        # o unitário antigo saiu do intervalo da amostra nova (ou pedia justificativa): vale a média
        if u is None or e.status_code != 400 or "unitário" not in str(e.detail):
            raise
        await escolher_referenciais(jid, EscolhaReferenciais(**corpo), _u={})


@router.get("/jobs/{jid}/amostra")
async def ver_amostra(jid: str, _u: dict = Depends(_dono)):
    _job(jid)
    return estado(jid)


@router.post("/jobs/{jid}/amostra")
async def mudar_amostra(jid: str, body: Amostra, _u: dict = Depends(_dono)):
    """Tirar / pôr anúncio na amostra: grava e refaz a prévia do cálculo. O laudo NÃO é refeito aqui."""
    _livre(jid)
    if not body.escolhidos:
        raise HTTPException(status_code=400, detail="A amostra não pode ficar vazia.")
    await _gravar(jid, sorted(set(body.escolhidos)))
    return estado(jid)


@router.post("/jobs/{jid}/amostra/gerar", status_code=202)
async def gerar_revisao(jid: str, body: Gerar, _u: dict = Depends(_dono)):
    """[Gerar a REVISÃO N com a amostra nova]: junta as mudanças e refaz o laudo (D-070)."""
    _livre(jid)
    e = estado(jid)
    if e["abaixo_do_minimo"]:
        raise HTTPException(status_code=400, detail=f"Ficam só {e['agora']['n']} anúncios. O mínimo é {MINIMO}. "
                                                    "Adicione outro antes de gerar o laudo.")
    conf = body.confirmacao.strip() or next(iter(reversed(db.instrucoes_avaliador(jid))), "")
    # 153-3 (D-147): trocar referencial refaz só a conta, a planilha, a tabela e os números do texto — nunca o laudo
    # inteiro: a redação é reaproveitada (sem IA) e a revisão/contestação da IA não rodam (correção rápida)
    db.set_setting(f"so_numeros:{jid}", "1")
    db.set_setting(f"correcao_rapida:{jid}", "1")
    await _gravar(jid, e["agora"]["escolhidos"], continuar=True, conf=conf)
    return {"revisao": e["revisao"], "status": "na fila"}


@router.post("/jobs/{jid}/amostra/{n}/corrigir")
async def corrigir_anuncio(jid: str, n: int, preco: str = Form(""), area_m2: str = Form(""), lote_m2: str = Form(""),
                           rua: str = Form("", max_length=200), foto: UploadFile | None = File(None),
                           _u: dict = Depends(_dono)):
    """[Corrigir] preço, área, lote, rua e foto de um anúncio, ali mesmo nos Detalhes (082-A2: a rua também).
    086: sempre aceito, mesmo com o trabalho montando ou na fila — o dado fica guardado e vale na próxima montagem."""
    from . import orquestrador
    r = next((x for x in db.candidatos(jid) if x.n == n), None)
    if r is None:
        raise HTTPException(status_code=404, detail="anúncio não encontrado")
    upd: dict = {}
    for campo, valor, rot in (("preco", preco, "preço"), ("area_m2", area_m2, "área"), ("lote_m2", lote_m2, "lote")):
        if valor.strip():
            upd[campo] = float(_num_form(valor, rot, obrigatorio=True))
    rua = rua if isinstance(rua, str) else ""          # chamada direta (testes antigos) sem a rua
    if rua.strip() and rua.strip() != (getattr(r, "rua", "") or "").strip():
        upd["rua"] = " ".join(rua.split())
    if foto is not None and foto.filename:
        dados = await foto.read()
        if len(dados) > 15 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="foto grande demais (máx. 15 MB)")
        ext = ".png" if (foto.content_type or "").endswith("png") else ".jpg"
        destino = db.pasta(jid) / "mercado" / f"corrigido-{n}{ext}"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(dados)
        upd["foto"] = destino.relative_to(db.pasta(jid)).as_posix()
    if not upd:
        raise HTTPException(status_code=400, detail="Nada para corrigir.")
    db.salvar_candidatos(jid, [r.model_copy(update=upd)])
    db.evento(jid, "pesquisa", "edicao_manual", f"anúncio nº {n} corrigido pelo avaliador nos Detalhes: "
              + ", ".join(sorted(upd)))
    esc = [x.n for x in db.candidatos(jid) if x.escolhido and x.decisao != "comparacao"]   # 094-1
    if esc and r.escolhido and not orquestrador.ocupado(jid):
        await _gravar(jid, esc)                 # a amostra usa o dado corrigido (refaz a prévia)
    e = estado(jid)
    e["salvo"] = {"n": n, **e["refs"].get(str(n), {})}   # 082-A4: "Salvo: 110 m² · R$ 1.445,45/m²" na hora
    return e


# ------------------------------------------------------------------ 116-2: ditado dos ajustes do laudo
MAX_AUDIO_DITADO = 30 * 1024 * 1024        # ~30 min de fala comprimida


async def _ouvir(audio: UploadFile) -> str:
    """O áudio enviado pela tela -> texto (transcrito no PC, D-107). Erros com a frase para o avaliador."""
    import asyncio
    import tempfile
    from pathlib import Path
    from . import transcricao
    if not transcricao.disponivel():
        raise HTTPException(status_code=503, detail="O transcritor de voz não está instalado neste PC.")
    dados = await audio.read(MAX_AUDIO_DITADO + 1)
    if not dados:
        raise HTTPException(status_code=400, detail="O áudio chegou vazio. Grave de novo.")
    if len(dados) > MAX_AUDIO_DITADO:
        raise HTTPException(status_code=413, detail="Áudio grande demais (até 30 MB). Divida em partes.")
    ext = (Path(audio.filename or "").suffix or ".webm").lower()
    if not re.fullmatch(r"\.(?:webm|ogg|oga|opus|m4a|mp3|mp4|aac|wav|amr|3gp)", ext):
        ext = ".webm"
    with tempfile.TemporaryDirectory() as tmp:
        arq = Path(tmp) / f"fala{ext}"
        arq.write_bytes(dados)
        try:
            texto, _dur, _gasto = await asyncio.to_thread(transcricao.transcrever, arq)
        except Exception as e:        # noqa: BLE001 — áudio que o ffmpeg não lê
            raise HTTPException(status_code=422, detail=f"Não consegui ouvir este áudio ({type(e).__name__}). Grave de novo.")
    return " ".join((texto or "").split())


@router.post("/falar")
async def falar(audio: UploadFile = File(...), _u: dict = Depends(_dono)):
    """119-2: o [🎤 Falar] de qualquer campo de texto — só devolve o que foi dito (a tela põe onde está o cursor)."""
    return {"texto": await _ouvir(audio)}


@router.post("/jobs/{jid}/corrigir/ditado")
async def corrigir_ditado(jid: str, audio: UploadFile = File(...), so_texto: int = 0, _u: dict = Depends(_dono)):
    """116-2: o avaliador dita os ajustes (gravado na tela, ou o arquivo de áudio gravado no celular). A fala é
    transcrita NO PC (D-107: custo zero, o áudio não sai do computador) e vira os pares "Onde fica: / O que mudar:"
    do quadro — nada é enviado sozinho: a tela mostra o texto para o avaliador conferir. ?so_texto=1: só a
    transcrição (para ditar dentro do campo "O que mudar:")."""
    from . import ditado
    _job(jid)
    texto = await _ouvir(audio)
    if so_texto:
        return {"texto": texto}
    pares = ditado.pares_da_fala(texto)
    return {"texto": texto, "pares": pares, "quadro": ditado.quadro(pares)}


# ------------------------------------------------------------------ 120: [Mostrar no PDF] com o trecho realçado
def pagina_realcada(pdf, n: int, trecho: str = "", largura: int = 900) -> tuple[bytes, bool]:
    """A página n (1, 2, …) do PDF em PNG, com o trecho realçado em amarelo. (png, achou o trecho?)."""
    import pymupdf
    with pymupdf.open(pdf) as d:
        if not 1 <= n <= len(d):
            raise HTTPException(status_code=404, detail=f"O laudo tem {len(d)} páginas; não existe a página {n}.")
        pg = d[n - 1]
        achou = False
        t = " ".join((trecho or "").split())
        for alvo in ([t, t[:60], t[:30]] if t else []):
            rects = pg.search_for(alvo) if len(alvo) >= 4 else []
            if rects:
                for r in rects:
                    a = pg.add_highlight_annot(r)
                    a.set_colors(stroke=(1, 0.85, 0))
                    a.update()
                achou = True
                break
        zoom = max(0.5, min(4.0, largura / pg.rect.width))
        return pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), annots=True).tobytes("png"), achou


@router.get("/jobs/{jid}/pdf/pagina")
async def ver_pagina(jid: str, n: int, trecho: str = "", largura: int = 900, _u: dict = Depends(_dono)):
    """120: [Mostrar no PDF] — a página do erro, com o trecho realçado (header X-Achado: 1/0)."""
    import asyncio
    from fastapi import Response
    from .orquestrador import _arquivos_finais
    _job(jid)
    pdf = _arquivos_finais(jid)["pdf"]
    if not pdf.is_file():
        raise HTTPException(status_code=404, detail="Este trabalho ainda não tem o PDF do laudo.")
    png, achou = await asyncio.to_thread(pagina_realcada, pdf, n, trecho[:300], max(300, min(largura, 2000)))
    return Response(png, media_type="image/png", headers={"X-Achado": "1" if achou else "0", "Cache-Control": "no-store"})


# ------------------------------------------------------------------ 138: corrigir direto no documento editável
@router.post("/jobs/{jid}/editavel/abrir")
async def editavel_abrir(jid: str, _u: dict = Depends(_dono)):
    """138: [Abrir o laudo editável] — cópia do .docx do laudo, aberta no editor do PC."""
    import asyncio
    from . import editavel
    _job(jid)
    try:
        return await asyncio.to_thread(editavel.abrir, jid)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/jobs/{jid}/editavel")
async def editavel_situacao(jid: str, _u: dict = Depends(_dono)):
    from . import editavel
    _job(jid)
    return editavel.situacao(jid)


class _Usar(BaseModel):
    concluir: bool = False                # 151-5: [Concluir a revisão humana] — sem mudança, só confere o PDF atual


@router.post("/jobs/{jid}/editavel/usar")
async def editavel_usar(jid: str, body: _Usar | None = None, _u: dict = Depends(_dono)):
    """138: [Usar este documento como laudo] — PDF no padrão a partir da cópia editada + conferência por regra."""
    import asyncio
    from . import editavel
    _job(jid)
    try:
        return await asyncio.to_thread(editavel.usar, jid, bool(body and body.concluir))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ------------------------------------------------------------------ editor do laudo dentro do sistema (salva sozinho)
class _TextoParagrafo(BaseModel):
    texto: str = ""
    base: str | None = None
    runs: list[dict] | None = None        # 151-3: a formatação de cada trecho (negrito, fonte, tamanho, cor, realce)
    formato: dict | None = None           # 151-3: alinhamento, recuo, lista e quebra de página do parágrafo
    manter: bool = False                  # 151-3: o desfazer nunca apaga a linha (mesmo voltando a ficar vazia)


def _erro_editor(e: Exception) -> HTTPException:
    return HTTPException(status_code=409 if isinstance(e, LookupError) else 400, detail=str(e))


@router.get("/jobs/{jid}/editavel/documento")
async def editavel_documento(jid: str, _u: dict = Depends(_dono)):
    """O laudo editável em blocos (parágrafos com a formatação, tabelas, imagens) para o editor da tela."""
    import asyncio
    from . import editavel
    _job(jid)
    try:
        return await asyncio.to_thread(editavel.documento, jid)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put("/jobs/{jid}/editavel/paragrafo/{pid}")
async def editavel_gravar(jid: str, pid: int, body: _TextoParagrafo, _u: dict = Depends(_dono)):
    """O salvar sozinho: grava o texto de um parágrafo no Word editável, sem mexer na formatação."""
    import asyncio
    from . import editavel
    _job(jid)
    try:
        return await asyncio.to_thread(editavel.gravar, jid, pid, body.texto, body.base,
                                       body.runs, body.formato, body.manter)
    except (ValueError, LookupError) as e:
        raise _erro_editor(e)


class _Contorno(BaseModel):
    pontos: list[list[float]] = []


@router.get("/jobs/{jid}/editavel/demarcacao/{qual}")
async def editavel_demarcacao(jid: str, qual: str, _u: dict = Depends(_dono)):
    """167-1: a imagem limpa (capa/mapa) e o contorno de agora, para o avaliador ajustar a demarcação."""
    from . import editavel_imagem
    _job(jid)
    try:
        return editavel_imagem.limpa(jid, qual)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/jobs/{jid}/editavel/demarcacao/{qual}/imagem")
async def editavel_demarcacao_imagem(jid: str, qual: str, _u: dict = Depends(_dono)):
    from fastapi import Response
    from . import editavel_imagem
    _job(jid)
    try:
        dados, tipo = editavel_imagem.arquivo_limpo(jid, qual)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(dados, media_type=tipo, headers={"Cache-Control": "no-store"})


@router.post("/jobs/{jid}/editavel/demarcacao/{qual}")
async def editavel_demarcacao_salvar(jid: str, qual: str, body: _Contorno, _u: dict = Depends(_dono)):
    """167-1: [Salvar a demarcação] — refaz a imagem demarcada e troca a figura no Word editável."""
    import asyncio
    from . import editavel_imagem
    _job(jid)
    try:
        return await asyncio.to_thread(editavel_imagem.ajustar, jid, qual, body.pontos)
    except (ValueError, LookupError) as e:
        raise _erro_editor(e)


@router.post("/jobs/{jid}/editavel/refazer-mapa")
async def editavel_refazer_mapa(jid: str, _u: dict = Depends(_dono)):
    """167-1: [Refazer o mapa] — nova captura no zoom do lote; falhou: o mapa atual fica e a frase diz por quê."""
    from . import editavel_imagem
    _job(jid)
    try:
        return await editavel_imagem.refazer_mapa(jid)
    except (ValueError, LookupError) as e:
        raise _erro_editor(e)


# ------------------------------------------------------------------ 172-3: imagens aprovadas antes da montagem
@router.get("/jobs/{jid}/imagens-laudo")
async def imagens_laudo_estado(jid: str, _u: dict = Depends(_dono)):
    """O mapa e a capa como vão entrar no laudo (prévia), para aprovar na escolha dos referenciais."""
    import asyncio
    from . import imagens_laudo
    _job(jid)
    await imagens_laudo.preparar_capa(jid)
    return await asyncio.to_thread(imagens_laudo.estado, jid)


@router.get("/jobs/{jid}/imagens-laudo/lista")
async def imagens_laudo_lista(jid: str, _u: dict = Depends(_dono)):
    from . import imagens_laudo
    _job(jid)
    return imagens_laudo.lista(jid)


@router.get("/jobs/{jid}/imagens-laudo/baixar/{ident}")
async def imagens_laudo_baixar(jid: str, ident: str, _u: dict = Depends(_dono)):
    from urllib.parse import quote
    from fastapi import Response
    from . import imagens_laudo
    _job(jid)
    try:
        dados, tipo, nome = imagens_laudo.baixar(jid, ident)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(dados, media_type=tipo, headers={"Cache-Control": "no-store",
                                                     "Content-Disposition": f"attachment; filename*=UTF-8''{quote(nome)}"})


@router.get("/jobs/{jid}/imagens-laudo/miniatura/{ident}")
async def imagens_laudo_miniatura(jid: str, ident: str, lado: int = 160, _u: dict = Depends(_dono)):
    """182: miniatura leve de uma imagem da lista."""
    import asyncio
    from fastapi import Response
    from . import imagens_laudo
    _job(jid)
    try:
        dados = await asyncio.to_thread(imagens_laudo.miniatura, jid, ident, lado)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(dados, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.post("/jobs/{jid}/imagens-laudo/mapa/refazer")
async def imagens_laudo_refazer_mapa(jid: str, _u: dict = Depends(_dono)):
    from . import imagens_laudo
    _job(jid)
    try:
        return await imagens_laudo.refazer_mapa(jid)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/jobs/{jid}/imagens-laudo/{qual}")
async def imagens_laudo_info(jid: str, qual: str, _u: dict = Depends(_dono)):
    import asyncio
    from . import imagens_laudo
    _job(jid)
    try:
        return await asyncio.to_thread(imagens_laudo.info, jid, qual)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/jobs/{jid}/imagens-laudo/{qual}/imagem")
async def imagens_laudo_imagem(jid: str, qual: str, demarcada: int = 0, _u: dict = Depends(_dono)):
    from fastapi import Response
    from . import imagens_laudo
    _job(jid)
    try:
        dados, tipo = imagens_laudo.arquivo(jid, qual, limpa=not demarcada)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(dados, media_type=tipo, headers={"Cache-Control": "no-store"})


@router.post("/jobs/{jid}/imagens-laudo/{qual}")
async def imagens_laudo_ajustar(jid: str, qual: str, body: _Contorno, _u: dict = Depends(_dono)):
    import asyncio
    from . import imagens_laudo
    _job(jid)
    try:
        return await asyncio.to_thread(imagens_laudo.ajustar, jid, qual, body.pontos)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (ValueError, LookupError) as e:
        raise _erro_editor(e)


@router.post("/jobs/{jid}/imagens-laudo/{qual}/aprovar")
async def imagens_laudo_aprovar(jid: str, qual: str, _u: dict = Depends(_dono)):
    import asyncio
    from . import imagens_laudo
    _job(jid)
    try:
        return await asyncio.to_thread(imagens_laudo.aprovar, jid, qual)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/jobs/{jid}/editavel/paginar")
async def editavel_paginar(jid: str, _u: dict = Depends(_dono)):
    """157: [Atualizar páginas] — PDF de prévia da cópia editável para as folhas do editor (o laudo não muda)."""
    import asyncio
    from . import editavel
    _job(jid)
    try:
        return await asyncio.to_thread(editavel.paginar, jid)
    except (ValueError, LookupError) as e:
        raise _erro_editor(e)


@router.get("/jobs/{jid}/editavel/faixa/{n}")
async def editavel_faixa(jid: str, n: int, parte: str = "cab", _u: dict = Depends(_dono)):
    """157-2: cabeçalho/rodapé da página N recortado do PDF (imagem)."""
    import asyncio
    from fastapi import Response
    from . import editavel
    _job(jid)
    try:
        png = await asyncio.to_thread(editavel.faixa, jid, n, "rod" if parte == "rod" else "cab")
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/jobs/{jid}/editavel/paragrafo/{pid}/novo")
async def editavel_novo(jid: str, pid: int, _u: dict = Depends(_dono)):
    import asyncio
    from . import editavel
    _job(jid)
    try:
        return await asyncio.to_thread(editavel.novo_paragrafo, jid, pid)
    except (ValueError, LookupError) as e:
        raise _erro_editor(e)


@router.get("/jobs/{jid}/editavel/imagem/{pid}")
async def editavel_imagem(jid: str, pid: int, k: int = 0, _u: dict = Depends(_dono)):
    import asyncio
    from fastapi import Response
    from . import editavel
    _job(jid)
    try:
        dados, tipo = await asyncio.to_thread(editavel.imagem, jid, pid, k)
    except (ValueError, LookupError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    return Response(dados, media_type=tipo, headers={"Cache-Control": "no-store"})


@router.post("/jobs/{jid}/editavel/descartar")
async def editavel_descartar(jid: str, _u: dict = Depends(_dono)):
    """Joga fora as mudanças do documento editável (ficam guardadas em revisoes/) e recomeça do laudo atual."""
    import asyncio
    from . import editavel
    _job(jid)
    try:
        return await asyncio.to_thread(editavel.descartar, jid)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
