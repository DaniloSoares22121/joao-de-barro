"""ORDEM 060: menu "⋯ Opções" de cada trabalho — Lixeira (apagar sem perder) e Exportar (.zip).

Apagar manda o trabalho para a Lixeira: ele some da lista, mas banco e arquivos ficam como estão.
Só "Esvaziar lixeira" apaga de vez, pela mesma função de excluir que já existia. Exportar junta
num .zip o que o trabalho tem (laudo, planilha, proposta/contrato, documentos, fotos, provas dos
anúncios e a conversa com o cliente), sem chamar IA."""
from __future__ import annotations

import asyncio
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, HTTPException
from fastapi.responses import Response

from . import db
from .routes import _dono, _job, _laudo_gerado, _livre, av_atual, dono_do_job, excluir_trabalho, router

CHAVE = "lixeira:"


def na_lixeira(jid: str) -> str:
    """Data/hora em que foi para a Lixeira ('' = não está)."""
    return db.setting(CHAVE + jid) or ""


def _tirar(jid: str) -> None:
    with db._conn() as c:
        c.execute("DELETE FROM av_settings WHERE chave=?", (CHAVE + jid,))


def entregue(jid: str) -> bool:
    """Laudo gerado (com arquivos) ou PDF assinado."""
    ent = db.resultado(jid, "entrega") or {}
    return _laudo_gerado(jid) or any(str(a).lower().endswith("_assinado.pdf") for a in ent.get("arquivos") or [])


def _titulo(j: dict) -> str:
    d = j.get("dados") or {}
    return " – ".join(x for x in (d.get("objeto_parte") or d.get("tipo"), d.get("bairro")) if x) or f"Trabalho nº {j['numero']}"


@router.post("/jobs/{jid}/lixeira")
async def para_lixeira(jid: str, _u: dict = Depends(_dono)):
    _livre(jid)                      # trabalho rodando não vai para a Lixeira
    db.set_setting(CHAVE + jid, datetime.now().isoformat(timespec="seconds"))
    db.evento(jid, "orquestrador", "info", "trabalho enviado para a Lixeira pelo avaliador")
    return {"ok": True}


@router.post("/jobs/{jid}/restaurar")
async def restaurar(jid: str, _u: dict = Depends(_dono)):
    _job(jid)
    if not na_lixeira(jid):
        raise HTTPException(status_code=409, detail="o trabalho não está na Lixeira")
    _tirar(jid)
    db.evento(jid, "orquestrador", "info", "trabalho restaurado da Lixeira pelo avaliador")
    return {"ok": True}


CHAVE_CLIENTE = "lixeira_cliente:"


def cliente_para_lixeira(cid: str) -> None:
    """109-2: o cliente some da lista de Clientes, mas conversa, arquivos e banco ficam como estão (restaurável)."""
    db.set_setting(CHAVE_CLIENTE + cid, datetime.now().isoformat(timespec="seconds"))


def cliente_restaurar(cid: str) -> None:
    with db._conn() as c:
        c.execute("DELETE FROM av_settings WHERE chave=?", (CHAVE_CLIENTE + cid,))


@router.post("/clientes/{cid}/lixeira")
async def cliente_lixeira(cid: str, _u: dict = Depends(_dono)):
    cliente_para_lixeira(cid)
    return {"ok": True}


@router.post("/clientes/{cid}/restaurar")
async def cliente_restaurar_rota(cid: str, _u: dict = Depends(_dono)):
    cliente_restaurar(cid)
    return {"ok": True}


def _da_lixeira() -> list[dict]:
    out = []
    for j in db.listar_jobs():
        quando = na_lixeira(j["id"])
        if not quando or dono_do_job(j) != av_atual():
            continue
        d = j.get("dados") or {}
        out.append({"id": j["id"], "numero": j["numero"], "titulo": _titulo(j), "cliente": d.get("cliente") or "",
                    "quando": quando, "entregue": entregue(j["id"]), "tipo": "trabalho"})
    # 183: o cliente apagado também aparece na Lixeira (para restaurar ou apagar de vez)
    from . import conversa as C
    with db._conn() as c:
        cli = [(r[0][len(CHAVE_CLIENTE):], r[1]) for r in c.execute(
            "SELECT chave, valor FROM av_settings WHERE chave LIKE ?", (CHAVE_CLIENTE + "%",)) if r[1]]
    for cid, quando in cli:
        x = C.obter(cid)
        if not x or x.get("avaliador_id") != av_atual():
            continue
        nome = x.get("nome") or "Cliente"
        out.append({"id": cid, "numero": 0, "titulo": f"Cliente: {nome}", "cliente": nome, "quando": quando,
                    "entregue": False, "tipo": "cliente"})
    return sorted(out, key=lambda x: x["quando"], reverse=True)


@router.get("/lixeira")
async def ver_lixeira(_u: dict = Depends(_dono)):
    return _da_lixeira()


@router.post("/lixeira/esvaziar")
async def esvaziar_lixeira(_u: dict = Depends(_dono)):
    """Apaga de vez (banco e arquivos) só o que está na Lixeira do avaliador."""
    apagados, ficaram = [], []
    for item in _da_lixeira():
        jid = item["id"]
        if item.get("tipo") == "cliente":          # 183: o cliente da Lixeira sai de vez (conversa e arquivos)
            from . import conversa as C
            C.apagar(jid)
            cliente_restaurar(jid)
            continue
        try:
            await excluir_trabalho(jid, _u)
        except HTTPException:
            ficaram.append(item["numero"])          # em execução: fica para a próxima
            continue
        with db._conn() as c:                        # tira também as escolhas guardadas do trabalho
            c.execute("DELETE FROM av_settings WHERE chave LIKE ?", (f"%:{jid}",))
        apagados.append(item["numero"])
    return {"apagados": apagados, "ficaram": ficaram}


# ------------------------------------------------------------------ exportar
def _nome_zip(jid: str) -> str:
    from . import nomes
    from .agentes import _comum
    try:
        return nomes.nome_arquivo(_comum.trabalho(jid))
    except Exception:
        return str(db.job(jid)["numero"])


def _quando(ts: str) -> str:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(ts)


def montar_zip(jid: str) -> tuple[bytes, dict[str, int]]:
    """(.zip em memória, quantos arquivos em cada pasta)."""
    from . import conversa, dossie, tela_trabalho
    base = db.pasta(jid)
    buf = io.BytesIO()
    conta: dict[str, int] = {}
    usados: set[str] = set()

    def pôr(pasta: str, origem: Path, nome: str | None = None) -> None:
        if not origem.is_file():
            return
        nome = (nome or origem.name).replace("/", "-")
        alvo, i = f"{pasta}/{nome}", 2
        while alvo in usados:
            p = Path(nome)
            alvo, i = f"{pasta}/{p.stem} ({i}){p.suffix}", i + 1
        usados.add(alvo)
        z.write(origem, alvo)
        conta[pasta] = conta.get(pasta, 0) + 1

    def texto(pasta: str, nome: str, conteudo: str) -> None:
        z.writestr(f"{pasta}/{nome}", conteudo)
        usados.add(f"{pasta}/{nome}")
        conta[pasta] = conta.get(pasta, 0) + 1

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # laudo e planilha da última revisão (a lista da entrega; arquivos antigos que sobraram na
        # pasta ficam de fora) + o PDF assinado, se houver
        ent = base / "entrega"
        atuais = [a for a in (db.resultado(jid, "entrega") or {}).get("arquivos") or [] if isinstance(a, str)]
        assinados = [f.name for f in ent.glob("*_assinado.pdf")] if ent.is_dir() else []
        for n in dict.fromkeys(atuais + assinados):
            f = ent / Path(n).name
            if f.suffix.lower() in (".md", ".png", ".json"):
                continue
            pôr("planilha" if f.suffix.lower() == ".xlsx" else "laudo", f)
        # proposta e contrato (do cliente ligado ao trabalho)
        cli = tela_trabalho._cliente(jid)
        if cli and cli.get("proposta_id"):
            from .rotas_propostas import _ler, _pasta
            try:
                p = _ler(cli["proposta_id"], checar=False)
                for n in p.get("arquivos") or []:
                    pôr("proposta e contrato", _pasta(p["id"]) / n)
            except HTTPException:
                pass
        # documentos e fotos enviados
        for a in db.arquivos(jid):
            pasta_zip = {"foto": "fotos", "foto_cliente": "fotos do cliente", "video_cliente": "videos do cliente"}.get(a["tipo"], "documentos")
            pôr(pasta_zip, base / a["caminho"], a["nome"])
        # anúncios: provas com data e hora (D-082), dossiê (D-085) e a lista
        prov = base / "provas"
        if prov.is_dir():
            for f in sorted(prov.rglob("*")):
                if f.is_file() and f.suffix.lower() != ".json":
                    pôr("anuncios", f)
        try:
            regs = dossie.registros(jid)
        except Exception:
            regs = []
        if regs:
            linhas = ["Anúncios analisados — escolhidos e descartados, com a data e hora de acesso", ""]
            for r in regs:
                linhas.append(f"{r['n']:02d}. {'ESCOLHIDO' if r['escolhido'] else 'DESCARTADO'} · {r['portal']} · "
                              f"acesso: {r['acessado_em']}" + (f" · motivo: {'; '.join(r['motivos'])}" if not r['escolhido'] and r['motivos'] else ""))
                linhas.append(f"    {r['link']}")
            texto("anuncios", "lista_de_anuncios.txt", "\n".join(linhas) + "\n")
        # conversa com o cliente (texto; áudio transcrito quando houver — ORDEM 061)
        if cli:
            msgs = conversa.mensagens(cli["id"])
            if msgs:
                linhas = [f"Conversa com {cli.get('nome') or 'o cliente'}", ""]
                for m in msgs:
                    t = (m.get("texto") or "").strip()
                    tr = (m.get("dados") or {}).get("transcricao") if isinstance(m.get("dados"), dict) else ""
                    if tr:
                        t = (t + "\n    [áudio transcrito] " + str(tr).strip()).strip()
                    linhas.append(f"{_quando(m['ts'])} · {m['autor']}: {t}")
                texto("conversa", "conversa.txt", "\n".join(linhas) + "\n")
            # ORDEM 061: conversa do WhatsApp importada, com o texto de cada áudio no lugar
            for cj in sorted((conversa.pasta(cli["id"]) / "conversa_whatsapp").glob("*/conversa.json")):
                try:
                    dados = json.loads(cj.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                linhas = [f"Conversa do WhatsApp com {dados['meta'].get('contato') or 'o cliente'}", ""]
                for m in dados.get("mensagens", []):
                    t = m.get("texto") or ""
                    if m.get("anexo"):
                        t = (t + f" [{m.get('tipo_anexo') or 'arquivo'}: {m['anexo']}]").strip()
                    if m.get("transcricao"):
                        t += f"\n    [áudio em texto] {m['transcricao']}"
                    linhas.append(f"{_quando(m['quando']) if m.get('quando') else '—'} · {m.get('autor') or 'aviso'}: {t}")
                texto("conversa", f"whatsapp_{cj.parent.name}.txt", "\n".join(linhas) + "\n")
            anexos = conversa.pasta(cli["id"])
            for f in sorted(anexos.rglob("*")) if anexos.is_dir() else []:
                if f.is_file():
                    pôr("conversa/anexos", f)
        resumo = [f"Trabalho nº {db.job(jid)['numero']} — exportado em {datetime.now().strftime('%d/%m/%Y %H:%M')}", ""]
        resumo += [f"{k}: {v} arquivo(s)" for k, v in sorted(conta.items())] or ["(sem arquivos)"]
        z.writestr("LEIA-ME.txt", "\n".join(resumo) + "\n")
    return buf.getvalue(), conta


@router.get("/jobs/{jid}/exportar.zip")
async def exportar(jid: str, _u: dict = Depends(_dono)):
    _job(jid)
    dados, _ = await asyncio.to_thread(montar_zip, jid)
    nome = _nome_zip(jid) + ".zip"
    return Response(dados, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(nome)}"})
