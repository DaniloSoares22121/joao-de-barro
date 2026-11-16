"""ORDEM 071-C1: a "cabeça" do João — cada etapa que usa IA recebe as partes do guia que valem para ela
(princípios sempre; a etapa da seção 2; as regras do ITCD de Goiás quando o caso for de ITCD)."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

ARQ = Path(__file__).parent / "assets" / "conhecimento" / "JOAO_COMO_TRABALHA.md"


@lru_cache(maxsize=1)
def _secoes() -> dict[str, str]:
    t = ARQ.read_text(encoding="utf-8")
    out, atual = {}, ""
    for linha in t.splitlines():
        m = re.match(r"^(#{2,3}) (\d+(?:\.\d+)?)\.? ", linha)
        if m:
            atual = m.group(2)
            out[atual] = ""
        if atual:
            out[atual] += linha + "\n"
    return out


def trecho(*chaves: str) -> str:
    s = _secoes()
    partes = []
    for k in chaves:
        if k in s:
            partes.append(s[k].strip())
        else:   # "2" pega a seção inteira (2, 2.1, 2.2…)
            partes += [v.strip() for kk, v in s.items() if kk == k or kk.startswith(k + ".")]
    return "\n\n".join(partes)


def eh_itcd(texto: str) -> bool:
    return bool(re.search(r"\bITC(?:M)?D\b|herança|doação|malha fiscal|DITCD", texto or "", re.I))


REGRAS_EXTRA = """\
Regras do João que valem aqui:
- O que o AVALIADOR escreveu nas mensagens dele MANDA: nunca troque pelo que um documento diz; se discordar, pergunte.
- Documento do PRÓPRIO avaliador (proposta ou contrato que ele mandou ao cliente) é a melhor fonte para quem contrata,
  valor e forma de pagamento. Comprovante de Pix do cliente = sinal pago.
- Valor venal (IPTU) é a BASE sobre a qual um imposto foi calculado — não é o imposto pago.
- Em Goiás o imposto de herança e doação chama ITCD (não ITCMD). Na malha fiscal do ITCD, a Secretaria da Economia
  compara o valor declarado com a referência da tabela FIPE: o laudo serve para JUSTIFICAR o valor declarado (não é
  "contestar o valor venal").
- Nunca peça um dado que já está num documento recebido ou nos DADOS JÁ GUARDADOS: use e diga a fonte.
- Nunca repita uma pergunta que o avaliador já respondeu.
- Nomes de pessoas completos e em Maiúsculas Só no Começo ("Beltrana Alves de Souza")."""
