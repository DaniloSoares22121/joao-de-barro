"""Aviso por WhatsApp quando o laudo termina: não existe nesta versão (a tela e o
navegador avisam). As funções existem para o módulo de aviso responder "desconectado"."""


def situacao() -> dict:
    return {"conectado": False, "numero": ""}


def enviar(tel: str, corpo: str, **_kw) -> tuple[bool, str]:
    return False, "WhatsApp não configurado nesta instalação"
