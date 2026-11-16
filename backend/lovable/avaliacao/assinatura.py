"""D-086 (ORDEM 039-5): PDF assinado digitalmente.

Depois do "Aprovo", o avaliador assina o PDF final no assinador do gov.br
(https://assinador.iti.br) ou com certificado ICP-Brasil e sobe o arquivo assinado. O sistema
confere, SÓ LENDO o arquivo, se há assinatura digital (campo de assinatura com valor, ou
dicionário /Sig com /ByteRange e /Contents) e guarda essa versão como a final, com `_assinado`
no nome, junto do Word e da planilha.
Proibido: assinar pelo avaliador, usar imagem de assinatura, pedir ou guardar senha."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ASSINADOR = "https://assinador.iti.br"
INSTRUCAO = [
    "1. Baixe o PDF final aprovado e abra o assinador do gov.br (botão acima), com a sua conta gov.br.",
    "2. Envie o PDF, escolha onde a assinatura aparece e assine. O gov.br devolve o PDF assinado.",
    "3. Suba aqui o PDF assinado: o sistema confere a assinatura e guarda como versão final.",
]


@dataclass
class Conferencia:
    assinado: bool
    assinaturas: list[dict] = field(default_factory=list)   # {campo, nome, data, cobre_tudo}
    motivo: str = ""


def conferir(pdf: Path | bytes) -> Conferencia:
    """Só leitura. Assinatura = campo de assinatura preenchido (/V → /Sig com /ByteRange e
    /Contents). Imagem de assinatura NÃO conta."""
    import pymupdf
    try:
        doc = pymupdf.open(stream=pdf, filetype="pdf") if isinstance(pdf, (bytes, bytearray)) else pymupdf.open(pdf)
    except Exception as e:
        return Conferencia(False, motivo=f"arquivo não é um PDF legível ({e})")
    tam = len(pdf) if isinstance(pdf, (bytes, bytearray)) else Path(pdf).stat().st_size
    achadas: list[dict] = []
    with doc:
        if not doc.is_pdf:
            return Conferencia(False, motivo="o arquivo não é PDF")
        for xref in range(1, doc.xref_length()):
            try:
                tipo = doc.xref_get_key(xref, "Type")
                filtro = doc.xref_get_key(xref, "Filter")
                br = doc.xref_get_key(xref, "ByteRange")
                ct = doc.xref_get_key(xref, "Contents")
            except Exception:
                continue
            eh_sig = (tipo[1] in ("/Sig", "/DocTimeStamp")) or (filtro[0] == "name" and br[0] == "array")
            if not eh_sig or br[0] != "array" or ct[0] not in ("string", "xref"):
                continue
            nums = [int(x) for x in re.findall(r"\d+", br[1])]
            cobre = len(nums) == 4 and nums[0] == 0 and nums[2] + nums[3] >= tam - 2048
            nome = doc.xref_get_key(xref, "Name")[1].strip("()") if doc.xref_get_key(xref, "Name")[0] == "string" else ""
            data = doc.xref_get_key(xref, "M")[1].strip("()") if doc.xref_get_key(xref, "M")[0] == "string" else ""
            achadas.append({"xref": xref, "filtro": filtro[1], "subfiltro": doc.xref_get_key(xref, "SubFilter")[1],
                            "nome": nome, "data": data, "cobre_o_arquivo": cobre})
        if not achadas:
            return Conferencia(False, motivo="nenhuma assinatura digital no arquivo (campo de assinatura vazio "
                                             "ou ausente; imagem de assinatura não conta)")
    return Conferencia(True, achadas)


def nome_assinado(pdf_final: Path) -> str:
    return f"{Path(pdf_final).stem.removesuffix('_assinado')}_assinado.pdf"
