"""Aviso ao avaliador quando um laudo chega a status final (WhatsApp pelo número do dono).

Usa o mesmo envio que o Brixly usa para falar pelo número do dono (`wa_dono.enviar`): sem
ponte/instância conectada, nada sai e fica só o evento "aviso_nao_enviado". Nunca levanta."""
from __future__ import annotations

import json
import logging
import os

from . import db

log = logging.getLogger(__name__)

CHAVE_LIGADO = "aviso_whatsapp"   # av_settings: "1" (padrão) ou "0"


def ligado() -> bool:
    return (db.setting(CHAVE_LIGADO, "1") or "1") != "0"


def set_ligado(on: bool) -> None:
    db.set_setting(CHAVE_LIGADO, "1" if on else "0")


def host() -> str:
    return (os.environ.get("LOVABLE_JOAODEBARRO_HOST") or "joaodebarro.brixly.com.br").strip().lower()


def mensagem(job_id: str) -> str:
    j = db.job(job_id)
    d = j["dados"]
    ent = db.resultado(job_id, "entrega") or {}
    n = len(ent.get("pendencias") or [])
    return (f"João de Barro: laudo nº {j['numero']} – {d.get('cliente', '')} "
            f"({d.get('tipo', '')}, {d.get('bairro', '')}) {ent.get('status', j['status'])}. "
            f"{n} pendência(s). https://{host()}/#/job/{job_id}")


def telefone() -> str:
    """Destino do aviso: `telefone_avisos` da config do avaliador (se houver), senão o
    `telefone` do avaliador."""
    try:
        av = json.loads(db.setting("avaliador", "{}") or "{}")
    except ValueError:
        return ""
    return str(av.get("telefone_avisos") or "").strip() or str(av.get("telefone") or "").strip()


def _situacao_wa() -> dict:
    from lovable import wa_dono
    return wa_dono.situacao()


PROPRIO_NUMERO = ("o aviso não chega no próprio número conectado — informe outro número "
                  "em \"Telefone para avisos\"")


def status() -> dict:
    """{ok, motivo, mensagem, telefone} para a Config: avisa se o destino é o próprio número
    conectado do dono (o WhatsApp não manda mensagem para si mesmo)."""
    from lovable import evolution
    tel = telefone()
    out = {"ok": True, "motivo": "", "mensagem": "", "telefone": tel, "ligado": ligado()}
    if not tel:
        return {**out, "ok": False, "motivo": "sem_telefone",
                "mensagem": "sem telefone do avaliador na configuração"}
    try:
        st = _situacao_wa()
    except Exception as e:
        log.info("aviso: status do WhatsApp falhou: %s", e)
        st = {}
    if not st.get("conectado"):
        return {**out, "ok": False, "motivo": "desconectado",
                "mensagem": "WhatsApp da Brixly desconectado"}
    num = evolution.normalize_phone(str(st.get("numero") or ""))
    if num and num == evolution.normalize_phone(tel):
        return {**out, "ok": False, "motivo": "proprio_numero", "mensagem": PROPRIO_NUMERO}
    return out


def _enviar(tel: str, corpo: str, chave: str) -> tuple[bool, str]:
    from lovable import wa_dono
    return wa_dono.enviar(tel, corpo, motivo="joaodebarro", chave=chave, nome="avaliador",
                          ignora_horario=True)


def avisar_fim(job_id: str) -> bool:
    """Manda o aviso de fim; devolve se saiu. Registra evento em qualquer desfecho."""
    try:
        if not ligado():
            return False
        tel = telefone()
        if not tel.strip():
            db.evento(job_id, "entrega", "aviso_nao_enviado", "sem telefone do avaliador na configuração")
            return False
        corpo = mensagem(job_id)
        with db._conn() as c:
            r = c.execute("SELECT MAX(id) AS m FROM av_events WHERE job=? AND etapa='entrega' "
                          "AND nivel='resultado'", (job_id,)).fetchone()
        ok, motivo = _enviar(tel, corpo, f"joaodebarro:{job_id}:{r['m'] or 0}")
    except Exception as e:  # nunca derruba o job
        log.exception("aviso de fim do job %s", job_id)
        ok, motivo = False, f"erro: {type(e).__name__}: {e}"
    try:
        if ok:
            db.evento(job_id, "entrega", "info", "aviso enviado por WhatsApp ao avaliador")
        else:
            db.evento(job_id, "entrega", "aviso_nao_enviado", f"WhatsApp não enviado: {motivo}")
    except Exception:
        log.exception("aviso de fim do job %s: evento", job_id)
    return ok
