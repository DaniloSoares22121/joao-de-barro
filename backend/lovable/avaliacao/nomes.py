"""Nome do arquivo final (D-020): `Nº - Cliente - Tipo - Bairro/Condomínio - Cidade`."""
from __future__ import annotations

import re

from .modelos import Trabalho

_PROIBIDOS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
MAX_PARTE = 60     # um solicitante de 300 letras estourava os 255 bytes do nome de arquivo
MAX_NOME = 180     # e a entrega falhava com o trabalho preso em "executando"


def _limpo(s) -> str:
    return " ".join(_PROIBIDOS.sub("", str(s)).split())[:MAX_PARTE].strip(" .")


def nome_arquivo(t: Trabalho) -> str:
    nome = " - ".join(_limpo(x) for x in (t.numero, t.cliente, t.tipo, t.bairro, t.cidade))
    return nome[:MAX_NOME].strip(" .-") or str(t.numero)
