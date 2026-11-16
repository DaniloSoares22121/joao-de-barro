"""ORDEM 065: a proposta e o contrato DE VERDADE antes de aprovar (D-091: passam pela revisão).

O rascunho é o mesmo documento que sai depois de aprovar (o mesmo gerador, a identidade do avaliador e
os dados do caso), com o próximo número, sem marca d'água. Fica na pasta do cliente, em rascunho/, e
não reserva número nem muda a etapa: só a aprovação faz isso. Refeito quando os dados mudam."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse

from . import conversa as C
from . import dados_cliente as DC
from .routes import _dono, router


def _rc():
    from . import rotas_conversa
    return rotas_conversa


def proposta_do_cliente(ctx: dict):
    """A NovaProposta montada do contexto do cliente (a mesma da aprovação)."""
    from .rotas_propostas import Imovel, NovaProposta
    falta = C.faltam(ctx, C.CAMPOS_PROPOSTA)
    if falta:
        raise HTTPException(status_code=409, detail="falta: " + ", ".join(r for _, r in falta))
    s = C.sugerir_proposta(ctx)
    return NovaProposta(
        modalidade=s["modalidade"], solicitante_nome=DC.nome_proprio(ctx["solicitante_nome"]),
        # 071-A1: o CPF só vai se for comprovadamente da pessoa (ligado a ela); nunca o de outra pessoa
        solicitante_doc=ctx.get("solicitante_doc", "") if (ctx.get("_doc_de") and DC.mesma_pessoa(ctx["_doc_de"], ctx["solicitante_nome"])) else "",
        proprietario=DC.nome_proprio(ctx.get("proprietario", "")),
        pagamento_texto=ctx.get("pagamento_texto", ""),
        prazo_texto=ctx.get("prazo_texto", "") or (s["prazo"] if s.get("da_tabela") else ""),      # 184: prazo da tabela
        # 071-A3: no documento vai o tipo do imóvel, nunca a conversa ("casa do pai…")
        imovel=Imovel(descricao=descricao_imovel(ctx.get("imovel_tipo") or ""),
                      endereco=ctx.get("imovel_endereco", ""), matricula=ctx.get("matricula", ""),
                      cartorio=(ctx.get("cartorio") or "")[:200],                 # 072-C7: "– Registro de Imóveis da 2ª…"
                      tipo=DC.tipo_limpo(ctx.get("imovel_tipo", "")), bairro=ctx.get("bairro", ""), cidade=ctx.get("cidade", "Goiânia")),
        finalidade=maiuscula(itcd(ctx["finalidade"])), valor=s["valor"])


def maiuscula(s: str) -> str:
    """072-C7: "justificar o valor…" → "Justificar o valor…"."""
    s = (s or "").strip()
    return s[:1].upper() + s[1:]


def descricao_imovel(tipo: str) -> str:
    t = (tipo or "").strip().lower()
    for k, r in (("casa", "Casa residencial"), ("sobrado", "Sobrado residencial"), ("apartamento", "Apartamento residencial"),
                 ("lote", "Lote"), ("terreno", "Terreno"), ("galp", "Galpão"), ("sala", "Sala comercial"), ("loja", "Loja")):
        if k in t:
            return r
    return (tipo or "Imóvel").strip()[:1].upper() + (tipo or "Imóvel").strip()[1:]


def itcd(texto: str) -> str:
    """071-A5: em Goiás o imposto é o ITCD (proposta, contrato e laudo)."""
    import re
    return re.sub(r"\bITCMD\b", "ITCD", texto or "")


def contratante_do_cliente(ctx: dict):
    from .rotas_propostas import Contratante
    falta = C.faltam(ctx, C.CAMPOS_CONTRATO)
    if falta:
        raise HTTPException(status_code=409, detail="falta: " + ", ".join(r for _, r in falta))
    doc = ctx["solicitante_doc"]
    pj = len("".join(ch for ch in doc if ch.isdigit())) == 14
    return Contratante(nome=ctx["solicitante_nome"], doc_tipo="CNPJ" if pj else "CPF", doc=doc,
                       endereco=ctx["solicitante_endereco"], email=ctx.get("solicitante_email", ""),
                       telefone=ctx.get("solicitante_telefone", ""), pj=pj)


def _pasta(cid: str) -> Path:
    p = C.pasta(cid) / "rascunho"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _capa(pdf: Path) -> Path | None:
    png = pdf.with_suffix(".png")
    if png.is_file() and png.stat().st_mtime >= pdf.stat().st_mtime:
        return png
    try:
        import pymupdf
        with pymupdf.open(pdf) as d:
            d[0].get_pixmap(dpi=80).save(png)
        return png
    except Exception:
        return None


def gerar(cid: str, qual: str, av: str = "AV-0001") -> dict:
    """Gera (ou reaproveita, se nada mudou) o rascunho da proposta ou do contrato."""
    from .rotas_propostas import _gerar, montar_dados, proximo_numero, valor_da_proposta
    cli = _rc()._cli(cid)
    ctx = cli["contexto"]
    hoje = date.today()
    body = proposta_do_cliente(ctx)
    if qual == "contrato" and cli.get("proposta_id"):
        from .rotas_propostas import _ler
        dados = dict(_ler(cli["proposta_id"])["dados"])      # o contrato sai da proposta aprovada
    else:
        dados = montar_dados(body, av, hoje.year, proximo_numero(hoje.year), valor_da_proposta(body, av))
    if qual == "contrato":
        dados = {**dados, "contratante": contratante_do_cliente(ctx).model_dump(),
                 "pagamento": ctx.get("pagamento") or "pix", "data_contrato": hoje.strftime("%d/%m/%Y")}
    pasta = _pasta(cid) / qual
    pasta.mkdir(parents=True, exist_ok=True)
    marca = hashlib.sha1(json.dumps(dados, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]
    meta_p = pasta / "rascunho.json"
    try:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    if meta.get("marca") == marca and all((pasta / n).is_file() for n in meta.get("arquivos", [])):
        return meta
    for f in pasta.iterdir():
        if f.is_file():
            f.unlink()
    arqs = _gerar(dados, pasta, qual)
    pdf = next((a for a in arqs if a.suffix.lower() == ".pdf"), None)
    capa = _capa(pdf) if pdf else None
    meta = {"marca": marca, "qual": qual, "numero": f"{dados['ano']}-{int(dados['numero']):03d}",
            "valor": C.valor_br(dados.get("valor")), "arquivos": [a.name for a in arqs] + ([capa.name] if capa else []),
            "pdf": pdf.name if pdf else "", "docx": next((a.name for a in arqs if a.suffix.lower() == ".docx"), ""),
            "capa": capa.name if capa else ""}
    meta_p.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


@router.post("/clientes/{cid}/rascunho/{qual}")
async def rascunho(cid: str, qual: str, _u: dict = Depends(_dono)):
    if qual not in ("proposta", "contrato"):
        raise HTTPException(status_code=404)
    return await asyncio.to_thread(gerar, cid, qual, (_u or {}).get("avaliador_id", "AV-0001"))


@router.get("/clientes/{cid}/rascunho/{qual}/{nome}")
async def arquivo_rascunho(cid: str, qual: str, nome: str, _u: dict = Depends(_dono)):
    _rc()._cli(cid)
    if qual not in ("proposta", "contrato"):
        raise HTTPException(status_code=404)
    base = (_pasta(cid) / qual).resolve()
    f = (base / nome).resolve()
    if f.parent != base or not f.is_file() or f.name == "rascunho.json":
        raise HTTPException(status_code=404)
    return FileResponse(f, filename=f"Rascunho - {f.name}" if f.suffix.lower() != ".png" else None)
