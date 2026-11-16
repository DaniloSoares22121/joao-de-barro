"""ORDEM 061: importar a conversa do WhatsApp (zip com mídias ou arquivos soltos) de uma vez.

POST /clientes/{cid}/importar recebe tudo (até 500 MB), recusa executáveis com aviso de uma linha e
processa em segundo plano: abre o zip, lê a conversa, transcreve os áudios NO PC (custo zero), passa
documentos e fotos pela leitura leve que já existia (documento fotografado × foto do imóvel) e
deixa um card de uma linha na conversa. O que o cliente DIZ é contexto; no laudo só entra dado de
documento ou de vistoria (a regra não muda)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import Depends, File, HTTPException, UploadFile

from . import conversa as C
from . import db, transcricao
from . import whatsapp as W
from .routes import _dono, router

log = logging.getLogger("lovable")
MAX_LEITURAS_IA = 20          # documentos + fotos lidos pela IA leve por importação (custo limitado)
_tarefas: set[asyncio.Task] = set()
_rodando: dict[str, asyncio.Task] = {}      # cliente → leitura viva NESTE servidor

TRIAGEM_EXTRA = """
Se a imagem NÃO for um documento (foto do imóvel, de cômodo, fachada, pessoa, paisagem, print de
conversa, figurinha), deixe todos os campos vazios, inclusive tipo_documento."""


def _rc():
    """rotas_conversa importado na hora (ela e routes.py se importam: evita o ciclo)."""
    from . import rotas_conversa
    return rotas_conversa


def _status(cid: str, **st) -> None:
    db.set_setting(f"wpp:{cid}", json.dumps(st, ensure_ascii=False))


def status(cid: str) -> dict | None:
    """ORDEM 070-B1: leitura que parou no meio (ex.: o sistema foi reiniciado) não fica "lendo" para sempre:
    vira um aviso com [Tentar de novo]."""
    try:
        st = json.loads(db.setting(f"wpp:{cid}") or "null")
    except ValueError:
        return None
    if st and st.get("estado") == "trabalhando":
        t = _rodando.get(cid)
        if t is None or t.done():
            if _retomar_sozinho(cid, st):              # 081-1: volta sozinha, do ponto onde parou
                return {**st, "texto": "O sistema foi reiniciado; o JdB continua a leitura de onde parou."}
            return {**st, "estado": "erro", "retomar": True,
                    "texto": "A leitura parou no meio (o sistema foi reiniciado). Toque em Tentar de novo."}
    return st


MAX_RETOMADAS = 3


def _retomar_sozinho(cid: str, st: dict) -> bool:
    """Leitura que ficou "trabalhando" sem tarefa viva (servidor reiniciado) recomeça sozinha, até 3 vezes
    seguidas (se cair sempre no mesmo ponto, para e mostra o [Tentar de novo])."""
    imp = st.get("importacao") or ""
    if not imp or not _pasta_imp(cid, imp).is_dir() or int(db.setting(f"wppret:{cid}") or 0) >= MAX_RETOMADAS:
        return False
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    db.set_setting(f"wppret:{cid}", str(int(db.setting(f"wppret:{cid}") or 0) + 1))
    _iniciar(cid, imp)
    return True


def retomar_todas() -> int:
    """Na subida do servidor: toda leitura que estava no meio continua sozinha."""
    with db._conn() as c:
        chaves = [r[0] for r in c.execute("SELECT chave FROM av_settings WHERE chave LIKE 'wpp:%'")]
    n = 0
    for ch in chaves:
        cid = ch[4:]
        try:
            st = json.loads(db.setting(ch) or "null")
        except ValueError:
            continue
        if st and st.get("estado") == "trabalhando" and not _rodando.get(cid) and _retomar_sozinho(cid, st):
            n += 1
    return n


def _fila(cid: str) -> list[str]:
    try:
        return list(json.loads(db.setting(f"wppfila:{cid}") or "[]"))
    except ValueError:
        return []


async def _rodar(cid: str, imp: str) -> None:
    """069-A8: envio que chega enquanto o anterior está sendo lido entra na fila e é lido logo depois."""
    await processar(cid, imp)
    while (fila := _fila(cid)):
        prox = fila.pop(0)
        db.set_setting(f"wppfila:{cid}", json.dumps(fila))
        _status(cid, estado="trabalhando", texto="Abrindo os arquivos do envio seguinte…", importacao=prox)
        await processar(cid, prox)
    db.set_setting(f"wppret:{cid}", "0")          # 081-1: terminou: zera a contagem de retomadas


def _iniciar(cid: str, imp: str) -> None:
    tarefa = asyncio.create_task(_rodar(cid, imp))
    _tarefas.add(tarefa)
    _rodando[cid] = tarefa
    tarefa.add_done_callback(_tarefas.discard)


def _pasta_imp(cid: str, imp: str) -> Path:
    return C.pasta(cid) / "conversa_whatsapp" / imp


def _memo(pasta: Path) -> dict:
    """081-1: o que já foi lido nesta importação (áudio transcrito, documento lido pela IA). A retomada
    continua do ponto onde parou e não paga a mesma leitura duas vezes."""
    try:
        return json.loads((pasta / "_feito.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _memo_gravar(pasta: Path, memo: dict) -> None:
    tmp = pasta / "_feito.json.tmp"
    tmp.write_text(json.dumps(memo, ensure_ascii=False), encoding="utf-8")
    tmp.replace(pasta / "_feito.json")


@router.post("/clientes/{cid}/importar")
async def importar(cid: str, arquivos: list[UploadFile] = File(...), _u: dict = Depends(_dono)):
    _rc()._cli(cid)
    st = status(cid)
    ocupado = bool(st and st.get("estado") == "trabalhando")   # 069-A8: não recusa mais; entra na fila
    imp = datetime.now().strftime("%Y%m%d-%H%M%S")
    k = 2
    while _pasta_imp(cid, imp).exists():
        imp = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{k}"
        k += 1
    pasta = _pasta_imp(cid, imp)
    pasta.mkdir(parents=True, exist_ok=True)
    total, aceitos, recusados = 0, [], []
    try:
        for up in arquivos:
            nome = W.nome_seguro(up.filename or "arquivo")
            t = W.tipo_de(nome)
            if t in ("recusado", "outro"):
                recusados.append(nome)
                continue
            alvo = pasta / nome
            k = 2
            while alvo.exists():
                alvo = pasta / f"{Path(nome).stem} ({k}){Path(nome).suffix}"
                k += 1
            with open(alvo, "wb") as f:
                while bloco := await up.read(1024 * 1024):
                    total += len(bloco)
                    if total > W.LIMITE_ENVIO:
                        raise HTTPException(status_code=413, detail="passou de 500 MB; envie em partes")
                    f.write(bloco)
            aceitos.append(alvo.name)
    except HTTPException:
        shutil.rmtree(pasta, ignore_errors=True)
        raise
    if not aceitos:
        shutil.rmtree(pasta, ignore_errors=True)
        raise HTTPException(status_code=400, detail="nenhum arquivo aceito" + (f": {', '.join(recusados[:5])} não é aceito (programa ou formato desconhecido)" if recusados else ""))
    if ocupado:
        db.set_setting(f"wppfila:{cid}", json.dumps(_fila(cid) + [imp]))
        so_fotos = all(W.tipo_de(n) == "foto" for n in aceitos)
        o_que = ("foto" if len(aceitos) == 1 else "fotos") if so_fotos else ("arquivo" if len(aceitos) == 1 else "arquivos")
        C.mensagem(cid, "sistema", "texto", f"Recebi mais {len(aceitos)} {o_que}. Leio assim que terminar os primeiros.")
    else:
        _status(cid, estado="trabalhando", texto="Abrindo os arquivos…", importacao=imp)
        _iniciar(cid, imp)
    out = _rc()._estado(cid)
    out["recusados"] = recusados
    return out


def _ler_conversa(pasta: Path) -> tuple[list[W.MsgWpp], str]:
    melhor: tuple[list[W.MsgWpp], str] = ([], "")
    for txt in sorted(pasta.rglob("*.txt")):
        try:
            texto = txt.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        msgs = W.ler_conversa(texto)
        if len(msgs) > len(melhor[0]):
            melhor = (msgs, W.nome_do_contato(txt.name, msgs))
    return melhor


async def _ler_com_ia(cid: str, rel: str, triagem: bool):
    from . import ia, imagens_ia
    from .agentes.leitor_anuncio import modelo_leve
    try:
        await asyncio.to_thread(imagens_ia.preparar, C.pasta(cid), [rel], imagens_ia.LADO_IA, None)
        ia.definir_contexto(f"conversa-{cid}", "conversa")
        rc = _rc()
        from . import dados_cliente as DC, joao
        # foto: só classificar (mecânico, modelo leve); documento: ler de verdade (modelo forte, 071-C2)
        return await ia.perguntar(DC.INSTR_DOC + (TRIAGEM_EXTRA if triagem else "\n\n" + joao.trecho("1")), f"Arquivo: {Path(rel).name}",
                                  DC.DocLido, arquivos=[C.pasta(cid) / rel], cwd=C.pasta(cid),
                                  modelo=modelo_leve() if triagem else "")
    except Exception as e:                 # sem leitura o arquivo fica guardado
        log.warning("importação %s: leitura de %s falhou: %s", cid, rel, type(e).__name__)
        return None


async def _ler_memo(cid: str, rel: str, triagem: bool, pasta: Path, memo: dict):
    """081-1: leitura pela IA guardada na importação; a retomada usa a que já foi feita."""
    from . import dados_cliente as DC
    chave = f"{'foto' if triagem else 'doc'}:{Path(rel).name}"
    feito = memo.setdefault("ia", {}).get(chave)
    if feito is not None:
        try:
            return DC.DocLido.model_validate(feito)
        except Exception:
            pass
    lido = await _ler_com_ia(cid, rel, triagem=triagem)
    if lido is not None:
        memo["ia"][chave] = lido.model_dump()
        _memo_gravar(pasta, memo)
    return lido


def _guardar(cid: str, origem: Path, tipo: str) -> str:
    """Copia para a pasta do cliente (documento/ ou foto_cliente/) e, se o trabalho já existe, para ele."""
    dest = C.pasta(cid) / tipo
    dest.mkdir(parents=True, exist_ok=True)
    alvo = dest / origem.name
    if alvo.is_file() and alvo.stat().st_size == origem.stat().st_size:
        return f"{tipo}/{alvo.name}"                    # já guardado (leitura refeita)
    k = 2
    while alvo.exists():
        alvo = dest / f"{origem.stem} ({k}){origem.suffix}"
        k += 1
    shutil.copy2(origem, alvo)
    rel = f"{tipo}/{alvo.name}"
    cli = C.obter(cid)
    if cli and cli.get("job_id") and C.job_existe(cli["job_id"]):
        jid = cli["job_id"]
        (db.pasta(jid) / tipo).mkdir(parents=True, exist_ok=True)
        shutil.copy2(alvo, db.pasta(jid) / rel)
        db.adicionar_arquivo(jid, alvo.name, tipo, rel, "", "")
    return rel


def fotos_pendentes_para_vistoria(cid: str) -> int:
    """083-C1/C3: chegou o relato da vistoria → as fotos que esperavam "são da vistoria?" vão para a vistoria e o
    card da conversa fecha (a mesma pergunta não fica aberta em dois lugares)."""
    n = 0
    for m in C.mensagens(cid):
        if m["tipo"] == "escolha" and m["dados"].get("pergunta") == "fotos" and not m["dados"].get("respondida"):
            for rel in m["dados"].get("arquivos") or []:
                if (C.pasta(cid) / rel).is_file():
                    _mover(cid, rel, "foto")
                    n += 1
            C.marcar_dados(m["id"], {**m["dados"], "respondida": "Sim, são da vistoria (você mandou depois da visita)"})
    return n


def _mover(cid: str, rel: str, novo_tipo: str) -> str:
    """Documento fotografado que estava como foto do cliente vai para documento/."""
    origem = C.pasta(cid) / rel
    novo = _guardar(cid, origem, novo_tipo)
    origem.unlink(missing_ok=True)
    cli = C.obter(cid)
    if cli and cli.get("job_id") and C.job_existe(cli["job_id"]):
        jid = cli["job_id"]
        (db.pasta(jid) / rel).unlink(missing_ok=True)
        with db._conn() as c:
            c.execute("DELETE FROM av_files WHERE job=? AND caminho=?", (jid, rel))
    return novo


def _aplicar(cid: str, lido, nome: str) -> None:
    """ORDEM 066: pessoas com papel; só preenche o vazio; pergunta quem contrata se não bater."""
    from . import dados_cliente as DC
    DC.aplicar_documento(cid, lido, nome)


SEG_POR_SEG_AUDIO = 0.6       # medido neste PC: ~31 s de trabalho por minuto de áudio (modelo small, ORDEM 061)


def _duracao(p: Path) -> float:
    try:
        import av
        with av.open(str(p)) as f:
            return float(f.duration or 0) / 1_000_000
    except Exception:
        return 60.0


def _lista(nomes: list[str]) -> str:
    nomes = list(dict.fromkeys(n for n in nomes if n))
    if len(nomes) <= 1:
        return "".join(nomes)
    return ", ".join(nomes[:-1]) + " e " + nomes[-1]


async def processar(cid: str, imp: str) -> None:
    pasta = _pasta_imp(cid, imp)
    try:
        # 1. abre o(s) zip(s)
        for k, z in enumerate(sorted(pasta.glob("*.zip")), 1):
            try:       # pasta curta: o Windows não aceita caminho com mais de 260 letras
                await asyncio.to_thread(W.abrir_zip, z, pasta / f"zip{k}")
            except W.ZipInvalido as e:
                C.mensagem(cid, "sistema", "texto", f"Não deu para abrir {z.name}: {e}.")
            z.unlink(missing_ok=True)
        arqs = [p for p in pasta.rglob("*") if p.is_file()]
        por = {t: [p for p in arqs if W.tipo_de(p.name) == t] for t in W.TIPOS}
        recusados_zip = []
        for p in arqs:
            if W.tipo_de(p.name) == "recusado":          # programa dentro do zip: apagado, nunca aberto
                recusados_zip.append(p.name)
                p.unlink(missing_ok=True)
        memo = _memo(pasta)
        # 2. a conversa
        msgs, contato = await asyncio.to_thread(_ler_conversa, pasta)
        # 3. áudios e vídeos → texto (local)
        midias = por["audio"] + por["video"]
        trans: dict[str, str] = {}
        n_ok, seg_audio, seg_gasto = 0, 0.0, 0.0
        if midias and not transcricao.disponivel():
            C.mensagem(cid, "sistema", "texto", "Não consegui transcrever os áudios: a transcrição local não está instalada.")
        elif midias:
            duracoes = [_duracao(m) for m in midias]               # 070-B3: o tempo que falta, pela duração real
            for i, m in enumerate(midias, 1):
                resta = sum(duracoes[i - 1:]) * SEG_POR_SEG_AUDIO + 20
                quanto = f"faltam uns {max(1, round(resta / 60))} min" if resta >= 60 else "falta menos de 1 min"
                _status(cid, estado="trabalhando", importacao=imp,
                        texto=f"O JdB está lendo a conversa (áudio {i} de {len(midias)}, {quanto}). "
                              "Pode sair desta tela: eu aviso quando terminar.")
                chave = m.relative_to(pasta).as_posix()
                feito = memo.setdefault("audio", {}).get(chave)
                if feito:                                      # 081-1: já transcrito antes do reinício
                    texto, dur, gasto = feito["texto"], float(feito.get("dur") or 0), 0.0
                else:
                    try:
                        texto, dur, gasto = await asyncio.to_thread(transcricao.transcrever, m)
                    except Exception as e:
                        log.warning("transcrição de %s falhou: %s", m.name, type(e).__name__)
                        texto, dur, gasto = "", 0.0, 0.0
                    if texto:
                        memo["audio"][chave] = {"texto": texto, "dur": dur}
                        _memo_gravar(pasta, memo)
                trans[m.name] = texto
                seg_audio += dur
                seg_gasto += gasto
                if texto:
                    n_ok += 1
        # 4. fotos (figurinhas fora) e documentos: leitura leve que já existia
        _status(cid, estado="trabalhando", importacao=imp,
                texto="O JdB está lendo os documentos e as fotos. Pode sair desta tela: eu aviso quando terminar.")
        fotos = [p for p in por["foto"] if not (p.suffix.lower() == ".webp" and p.stat().st_size < W.FIGURINHA_MAX)]
        leituras, docs_lidos, n_fotos_cliente = 0, [], 0
        # 072-C9: foto que o AVALIADOR manda (sem conversa exportada) depois da visita é de vistoria;
        # a que veio dentro da conversa do WhatsApp é do cliente; sem visita feita, pergunta (um card)
        sem_conversa = not any(m.autor for m in msgs)
        ctx0 = (C.obter(cid) or {}).get("contexto") or {}
        # 083-C1: o avaliador mandou (sem conversa exportada) e a visita já aconteceu (feita ou data passada) → vistoria
        from datetime import timezone as _tz
        _qv = C._dt(ctx0.get("visita") or "")
        visita_passou = bool(ctx0.get("visita_feita")) or bool(_qv and _qv <= datetime.now(_tz.utc))
        da_vistoria = sem_conversa and visita_passou
        n_vistoria, duvida = 0, []
        jid_aberto = ctx0.get("_job") or (C.obter(cid) or {}).get("job_id") or ""
        def _fotos_job() -> int:
            return sum(1 for a in db.arquivos(jid_aberto) if a.get("tipo") == "foto") if jid_aberto and C.job_existe(jid_aberto) else 0
        antes_job = _fotos_job()
        for p in por["documento"]:
            rel = _guardar(cid, p, "documento")
            if p.suffix.lower() == ".pdf" and leituras < MAX_LEITURAS_IA:
                leituras += 1
                lido = await _ler_memo(cid, rel, False, pasta, memo)
                if lido:
                    docs_lidos.append(lido.tipo_documento or "documento")
                    _aplicar(cid, lido, p.name)
            else:
                docs_lidos.append({".xls": "planilha", ".xlsx": "planilha", ".csv": "planilha"}.get(p.suffix.lower(), "documento"))
        for p in fotos:
            if da_vistoria:
                _guardar(cid, p, "foto")
                n_vistoria += 1
                continue
            rel = _guardar(cid, p, "foto_cliente")
            lido = None
            if p.suffix.lower() != ".heic" and leituras < MAX_LEITURAS_IA:
                leituras += 1
                lido = await _ler_memo(cid, rel, True, pasta, memo)
            if lido and lido.tipo_documento.strip():
                _mover(cid, rel, "documento")
                docs_lidos.append(lido.tipo_documento)
                _aplicar(cid, lido, p.name)
            else:
                n_fotos_cliente += 1
                if sem_conversa:
                    duvida.append(rel)
        novas = _fotos_job() - antes_job
        if novas > 0:                     # 074-B: trabalho já aberto — as fotos chegam a ele e o próximo passo avisa
            db.set_setting(f"fotos_novas:{jid_aberto}", str(int(db.setting(f"fotos_novas:{jid_aberto}") or 0) + novas))
            C.mensagem(cid, "sistema", "texto", f"Chegaram {novas} {'foto' if novas == 1 else 'fotos'} da vistoria no trabalho. "
                                                "No trabalho: [Refazer o laudo com as fotos].")
        if duvida:
            C.mensagem(cid, "sistema", "escolha", f"Essas {len(duvida)} {'foto é' if len(duvida) == 1 else 'fotos são'} da sua vistoria?",
                       {"pergunta": "fotos", "arquivos": duvida, "outro": False,
                        "opcoes": [{"valor": "vistoria", "rotulo": "Sim, são da vistoria", "recomendada": False},
                                   {"valor": "cliente", "rotulo": "Não, o cliente mandou", "recomendada": False}]})
        for p in por["video"]:
            _guardar(cid, p, "video_cliente")
        # 5. contato
        for p in por["contato"]:
            nome, tel = W.ler_vcf(p.read_text(encoding="utf-8", errors="replace"))
            ctx = (C.obter(cid) or {}).get("contexto") or {}
            novos = {k: v for k, v in (("solicitante_nome", nome), ("solicitante_telefone", tel)) if v and not ctx.get(k)}
            if novos:
                C.juntar_contexto(cid, novos)
        # 6. a conversa completa, em ordem, com o texto dos áudios no lugar
        citados = {m.anexo for m in msgs if m.anexo}
        saida = []
        for m in msgs:
            saida.append({"quando": m.quando.isoformat() if m.quando else "", "autor": m.autor, "texto": m.texto,
                          "anexo": m.anexo, "tipo_anexo": W.tipo_de(m.anexo) if m.anexo else "",
                          "transcricao": trans.get(m.anexo, "")})
        for nome, t in trans.items():                  # áudio solto, sem mensagem que o cite
            if nome not in citados:
                saida.append({"quando": "", "autor": "", "texto": "", "anexo": nome, "tipo_anexo": W.tipo_de(nome), "transcricao": t})
        n_msgs = sum(1 for m in msgs if m.autor)
        meta = {"importacao": imp, "contato": contato, "mensagens": n_msgs, "audios": len(por["audio"]),
                "videos": len(por["video"]), "transcritos": n_ok, "fotos": n_fotos_cliente, "documentos": docs_lidos,
                "recusados": recusados_zip, "segundos_audio": round(seg_audio, 1), "segundos_transcricao": round(seg_gasto, 1)}
        (pasta / "conversa.json").write_text(json.dumps({"meta": meta, "mensagens": saida}, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
        # 7. o card de uma linha
        partes = []
        if n_msgs:
            partes.append(f"{n_msgs} {'mensagem' if n_msgs == 1 else 'mensagens'}")
        if por["audio"] or por["video"]:
            partes.append(f"{n_ok} {'áudio transcrito' if n_ok == 1 else 'áudios transcritos'}")
        if n_vistoria:
            partes.append(f"{n_vistoria} {'foto' if n_vistoria == 1 else 'fotos'} da vistoria")
        if n_fotos_cliente:
            partes.append(f"{n_fotos_cliente} {'foto' if n_fotos_cliente == 1 else 'fotos'}")
        if docs_lidos:
            partes.append(_lista([d[:1].lower() + d[1:] if d[1:2].islower() else d for d in docs_lidos]))
        titulo = f"Li a conversa com {contato}" if (contato and n_msgs) else "Li os arquivos"
        card = C.mensagem(cid, "sistema", "importacao", f"{titulo}: {', '.join(partes) or 'nada para ler'}.",
                          {"importacao": imp, **meta})
        if recusados_zip:
            C.mensagem(cid, "sistema", "texto", f"Deixei de fora {len(recusados_zip)} {'arquivo' if len(recusados_zip) == 1 else 'arquivos'} "
                                                 "de programa (não são aceitos por segurança).")
        _status(cid, estado="trabalhando", importacao=imp, texto="Resumindo o caso…")
        if _rc().precisa_entender(cid):            # ORDEM 062: depois de ler tudo, o resumo "Entendi… É isso?"
            from . import entendimento
            try:
                await entendimento.resumir(cid)
            except Exception as e:
                log.warning("resumo depois da importação %s: %s", cid, type(e).__name__)
        _status(cid, estado="pronto", importacao=imp, texto="")
        try:                                                     # "eu aviso quando terminar" (070-B3)
            nome = ((C.obter(cid) or {}).get("contexto") or {}).get("solicitante_nome") or contato or "o cliente"
            if contato and n_msgs and nome != contato and re.fullmatch(r"[+\d\s()-]+", contato):
                # 071: o card só tinha o telefone; depois do resumo ganha o nome ("Li a conversa com Fulano (+55…)")
                C.trocar_texto(card["id"], card["texto"].replace(f"Li a conversa com {contato}",
                                                                 f"Li a conversa com {nome.split(' ')[0]} ({contato})", 1))
            C.registrar_aviso("Terminei de ler a conversa", f"Li a conversa com {nome}. O resumo está esperando você.", cid)
            from . import webpush
            await asyncio.to_thread(webpush.enviar_todos, "Terminei de ler a conversa", f"Li a conversa com {nome}.")
        except Exception:
            pass
    except Exception:
        log.exception("importação %s/%s", cid, imp)
        _status(cid, estado="erro", importacao=imp, texto="Não consegui terminar a leitura. Tente enviar de novo.")
        C.mensagem(cid, "sistema", "texto", "Não consegui terminar a leitura dos arquivos. Tente enviar de novo.")


@router.post("/clientes/{cid}/importar/retomar")
async def retomar(cid: str, _u: dict = Depends(_dono)):
    """[Tentar de novo]: refaz a leitura com os arquivos que já chegaram (sem duplicar o que já foi guardado)."""
    _rc()._cli(cid)
    st = status(cid) or {}
    imp = st.get("importacao") or ""
    if not imp or not _pasta_imp(cid, imp).is_dir():
        raise HTTPException(status_code=404, detail="não achei a importação para refazer")
    if st.get("estado") == "trabalhando":
        return _rc()._estado(cid)
    _status(cid, estado="trabalhando", texto="Lendo de novo…", importacao=imp)
    _iniciar(cid, imp)
    return _rc()._estado(cid)


@router.get("/clientes/{cid}/importacoes")
async def importacoes(cid: str, _u: dict = Depends(_dono)):
    _rc()._cli(cid)
    out = []
    base = C.pasta(cid) / "conversa_whatsapp"
    for p in sorted(base.glob("*/conversa.json"), reverse=True) if base.is_dir() else []:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8"))["meta"])
        except (OSError, ValueError, KeyError):
            continue
    return {"importacoes": out, "status": status(cid)}


@router.get("/clientes/{cid}/importacoes/{imp}")
async def conversa_importada(cid: str, imp: str, _u: dict = Depends(_dono)):
    _rc()._cli(cid)
    if not imp.replace("-", "").isdigit():
        raise HTTPException(status_code=404)
    p = _pasta_imp(cid, imp) / "conversa.json"
    if not p.is_file():
        raise HTTPException(status_code=404)
    return json.loads(p.read_text(encoding="utf-8"))
