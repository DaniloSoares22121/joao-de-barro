"""Substituto local do envio por WhatsApp: localmente nunca há instância conectada."""


def situacao() -> dict:
    return {"conectado": False, "numero": ""}


def enviar(tel: str, corpo: str, **_kw) -> tuple[bool, str]:
    return False, "WhatsApp não configurado nesta instalação local"
