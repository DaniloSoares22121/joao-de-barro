"""117: pedido de ajuste do avaliador é ORDEM.

Cada pedido (um par "Onde fica / O que mudar", ou um bloco entre linhas "=====") é guardado com um número,
o tipo e as ações que o sistema sabe executar:
- texto  → correção para a etapa que escreve (redação etc.);
- dado   → o dado do trabalho muda em tudo (data, bairro, nome…; routes._trocar_dados);
- modelo → título de item, documento fora do quadro do item 6, trecho fixo que sai do laudo (aplicados pelo montador);
- imagem → outra foto do anúncio pela descrição, demarcação do mapa (imagens_pedido, do outro executor).
Depois da montagem o PDF é conferido pedido por pedido (conferir_pedidos): o que não foi feito volta UMA vez para a
etapa certa; o que ainda sobrar vira "Não consegui fazer: <pedido> — porque <motivo>" (passo, nunca escondido).
"""
from __future__ import annotations

import json
import re

from . import db

CHAVE = "pedidos:"
TITULOS, DOCS_FORA, TRECHOS_FORA = "titulos:", "docs_fora:", "trechos_fora:"
FOTOS_FORA = "fotos_fora:"      # L200: fotos da vistoria tiradas do relatório ({"legenda": …, "arquivo": …})
NAO_CONSEGUI = "Não consegui fazer"


def _ler(chave: str, padrao):
    try:
        v = json.loads(db.setting(chave) or "null")
    except ValueError:
        return padrao
    return v if isinstance(v, type(padrao)) else padrao


def _gravar(chave: str, v) -> None:
    db.set_setting(chave, json.dumps(v, ensure_ascii=False))


def lista(job_id: str) -> list[dict]:
    return _ler(CHAVE + job_id, [])


def _salvar(job_id: str, itens: list[dict]) -> None:
    _gravar(CHAVE + job_id, itens)


def abertos(job_id: str) -> list[dict]:
    """Os pedidos que ainda esperam conferência no PDF."""
    return [p for p in lista(job_id) if p.get("status") in ("pendente", "refazer")]


def novo(job_id: str, texto: str, etapa: str, instrucao: str, acoes: list[dict]) -> dict:
    itens = lista(job_id)
    p = {"i": (max((x["i"] for x in itens), default=0) + 1), "texto": texto.strip(), "etapa": etapa,
         "instrucao": instrucao, "acoes": acoes, "status": "pendente", "tentativas": 0, "motivo": ""}
    itens.append(p)
    _salvar(job_id, itens)
    return p


def marcar(job_id: str, i: int, **upd) -> None:
    itens = lista(job_id)
    for p in itens:
        if p["i"] == i:
            p.update(upd)
    _salvar(job_id, itens)


# ------------------------------------------------------------------ ações de modelo (o montador aplica)
TROCAS = "trocas:"


def trocas(job_id: str) -> list:
    """129: trocas de termo do avaliando (dado trocado: bairro, cliente…) aplicadas pelo montador, sem IA."""
    return _ler(TROCAS + job_id, [])


def registrar_troca(job_id: str, antes: str, depois: str) -> None:
    t = [x for x in trocas(job_id) if x and x[0] != antes]
    t.append([antes, depois])
    _gravar(TROCAS + job_id, t)


def titulos(job_id: str) -> dict:
    return _ler(TITULOS + job_id, {})


def docs_fora(job_id: str) -> list:
    return _ler(DOCS_FORA + job_id, [])


def trechos_fora(job_id: str) -> list:
    return _ler(TRECHOS_FORA + job_id, [])


def fotos_fora(job_id: str) -> list:
    return _ler(FOTOS_FORA + job_id, [])


def _norm_leg(s: str) -> str:
    s = re.sub(r"(?i)^\s*foto\s*\d+\s*[–-]\s*", "", s or "")
    return re.sub(r"[^0-9a-zà-ú]+", " ", s.casefold()).strip()


def legenda_da_foto(job_id: str, alvo: str) -> str:
    """"Foto 04" → a legenda da foto 04 no último PDF entregue; legenda escrita no pedido vale como está."""
    m = re.search(r"(?i)foto\s*(\d{1,2})\b", alvo or "")
    resto = _norm_leg(re.sub(r"(?i)\bfoto\s*\d+", "", alvo or ""))
    if m and len(resto) < 4:
        try:
            import fitz
            pdfs = sorted((db.pasta(job_id) / "entrega").glob("*.pdf"), key=lambda x: x.stat().st_mtime)
            texto = "\n".join(pg.get_text() for pg in fitz.open(str(pdfs[-1]))) if pdfs else ""
        except Exception:
            texto = ""
        achou = re.search(rf"Foto\s*0?{int(m.group(1))}\s*[–-]\s*([^\n]+)", texto)
        return achou.group(1).strip() if achou else ""
    return re.sub(r"(?i)^\s*foto\s*\d+\s*[–-]\s*", "", alvo or "").strip().strip('"“”')


def foto_fora(job_id: str, arquivo: str, legenda: str) -> bool:
    """A foto da vistoria saiu do relatório? A 1ª montagem acha a foto pela legenda e grava o arquivo (a numeração
    muda depois que ela sai: o arquivo é que vale)."""
    itens = fotos_fora(job_id)
    for it in itens:
        if it.get("arquivo") == arquivo:
            return True
        if not it.get("arquivo") and it.get("legenda") and _norm_leg(it["legenda"]) == _norm_leg(legenda):
            it["arquivo"] = arquivo
            _gravar(FOTOS_FORA + job_id, itens)
            return True
    return False


def aplicar_modelo(job_id: str, acoes: list[dict]) -> list[str]:
    """Grava as ações de modelo do pedido; devolve o que ficou combinado, em português."""
    feitas = []
    for a in acoes:
        tipo, alvo, valor = a.get("tipo"), str(a.get("alvo") or "").strip(), str(a.get("valor") or "").strip()
        if tipo == "titulo" and alvo and valor:
            item = re.sub(r"[^\d.]", "", alvo).strip(".")
            novo_t = re.sub(rf"^\s*{re.escape(item)}\.?\s*[–-]?\s*", "", valor).strip() if item else valor
            if item and novo_t:
                t = titulos(job_id); t[item] = novo_t; _gravar(TITULOS + job_id, t)
                feitas.append(f"título do item {item}: {novo_t}")
        elif tipo == "tirar_documento" and alvo:
            d = docs_fora(job_id)
            if alvo not in d:
                d.append(alvo); _gravar(DOCS_FORA + job_id, d)
            feitas.append(f"fora do quadro do item 6: {alvo}")
        elif tipo == "tirar_foto" and alvo:
            leg = legenda_da_foto(job_id, alvo)
            if leg:
                d = fotos_fora(job_id)
                if all(_norm_leg(x.get("legenda", "")) != _norm_leg(leg) for x in d):
                    d.append({"legenda": leg, "arquivo": ""}); _gravar(FOTOS_FORA + job_id, d)
                feitas.append(f"foto fora do relatório: “{leg}”")
        elif tipo == "tirar_trecho" and alvo:
            d = trechos_fora(job_id)
            if alvo not in d:
                d.append(alvo); _gravar(TRECHOS_FORA + job_id, d)
            feitas.append(f"sai do laudo: “{alvo}”")
    return feitas


async def aplicar_imagens(job_id: str, acoes: list[dict]) -> list[tuple[bool, str]]:
    """Trocar foto do anúncio pela descrição / refazer a demarcação do mapa (funções do outro executor)."""
    out = []
    for a in acoes:
        tipo = a.get("tipo")
        try:
            if tipo == "trocar_foto":
                # 126-3c: "imóvel 2 do 9.3" é o 2º da comparação (não o anúncio nº 2) — quem resolve é trocar_foto_alvo
                from .imagens_pedido import trocar_foto_alvo
                r = await trocar_foto_alvo(job_id, str(a.get("alvo") or ""), str(a.get("valor") or ""))
                out.append((bool(r.get("ok")), str(r.get("motivo") or "")))
            elif tipo == "refazer_mapa":
                from .imagens_pedido import refazer_demarcacao
                r = await refazer_demarcacao(job_id, str(a.get("valor") or a.get("alvo") or ""))
                out.append((bool(r.get("ok")), str(r.get("motivo") or "")))
        except Exception as e:          # noqa: BLE001 — falha numa ação vira "não consegui", nunca derruba o pedido
            out.append((False, f"falhou ao executar ({type(e).__name__})"))
    return out


# ------------------------------------------------------------------ conferência no PDF (depois da montagem)
async def conferir_no_pdf(job_id: str, pdf) -> tuple[list[dict], list[dict]]:
    """(refazer, nao_feitos). Marca cada pedido aberto: feito / refazer (1ª falha) / nao_feito (2ª falha)."""
    abertos_ = abertos(job_id)
    if not abertos_:
        return [], []
    from .conferir_pedidos import conferir
    res = await conferir(job_id, pdf, [{"i": p["i"], "onde": "", "oque": p["texto"]} for p in abertos_])
    por_i = {r.get("i"): r for r in res or []}
    refazer, nao = [], []
    for p in abertos_:
        r = por_i.get(p["i"]) or {"feito": False, "motivo": "a conferência não respondeu sobre este pedido"}
        if r.get("imagem") and any(a.get("tipo") in ("trocar_foto", "refazer_mapa") for a in p.get("acoes") or []):
            # imagem: vale o resultado da troca (a que falhou já saiu como "não consegui" na hora do pedido)
            marcar(job_id, p["i"], status="feito", onde_viu="imagem trocada")
            continue
        if r.get("imagem"):
            # imagem sem ação própria (ex.: ordem das fotos): é da montagem e não dá para conferir pelo texto do PDF
            marcar(job_id, p["i"], status="feito", onde_viu="nas fotos (conferir olhando o PDF)")
            continue
        if r.get("feito"):
            marcar(job_id, p["i"], status="feito", onde_viu=str(r.get("onde_viu") or ""))
        elif int(p.get("tentativas") or 0) < 1:
            marcar(job_id, p["i"], status="refazer", tentativas=1, motivo=str(r.get("motivo") or ""))
            refazer.append({**p, "motivo": str(r.get("motivo") or "")})
        else:
            motivo = str(r.get("motivo") or p.get("motivo") or "não aparece no PDF")
            marcar(job_id, p["i"], status="nao_feito", motivo=motivo)
            nao.append({**p, "motivo": motivo})
    return refazer, nao


def linha_nao_consegui(p: dict) -> str:
    return f"{NAO_CONSEGUI}: {p['texto'][:300]} — porque {p.get('motivo') or 'não aparece no PDF'}"


def resumo(job_id: str, desde_i: int = 0) -> list[str]:
    """Para "O que mudou na Revisão N": um por um, ✓ feito / ✗ não consegui."""
    out = []
    for p in lista(job_id):
        if p["i"] <= desde_i or p.get("status") in ("pendente", "refazer", "reaplicado"):   # 130: reaplicado = refeito depois
            continue
        txt = re.sub(r"\s+", " ", p["texto"])[:220]
        if p.get("status") == "feito":
            out.append(f"✓ Feito: {txt}" + (f" ({p['onde_viu']})" if p.get("onde_viu") else ""))
        else:
            out.append(f"✗ Não consegui: {txt} — porque {p.get('motivo') or 'não aparece no PDF'}")
    return out
