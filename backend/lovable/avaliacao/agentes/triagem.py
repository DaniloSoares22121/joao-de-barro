"""Agente de Triagem: monta o quadro de entrada (P5) e decide se o trabalho pode seguir."""
from __future__ import annotations

import os
import re

from pydantic import BaseModel

from .. import conhecimento, db, ia
from . import _comum

TRIAGEM_ENXUTA = (os.environ.get("JDB_TRIAGEM_ENXUTA") or "") == "1"

CHAVES = ("TRABALHO", "MODALIDADE", "FINALIDADE", "ARQUIVOS", "DADOS COMPROVADOS",
          "PENDÊNCIAS", "EXECUÇÃO")

INSTRUCAO = """\
ETAPA ATUAL: TRIAGEM DE ENTRADA.
Você é o agente de triagem do João de Barro. Com base no formulário do trabalho e nos
arquivos enviados (leia-os com a ferramenta Read), monte o quadro de entrada conforme o
checklist P5 e a matriz de modalidades P7.
- O campo "quadro" deve ter exatamente as chaves: TRABALHO, MODALIDADE, FINALIDADE,
  ARQUIVOS, DADOS COMPROVADOS, PENDÊNCIAS, EXECUÇÃO (valores em texto pt-BR).
- DADOS COMPROVADOS só lista o que está em documento (IPTU, matrícula etc.). Informação
  verbal do contratante (campo "contexto" do formulário) NUNCA é dado comprovado (D-013).
- "bloqueado" = true apenas se faltar algo que impeça o laudo (ex.: nenhum documento do
  imóvel, modalidade incompatível com a finalidade); explique em "motivo".
- Nunca invente dados.
- Use a CONTAGEM DE ARQUIVOS informada no pedido (não conte de cabeça).
- Nunca escreva CPF, RG, CNH, OAB ou outro número de documento pessoal no quadro: escreva só
  "documento de identificação conferido".
"""

_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_DOC_NUM = re.compile(r"(?i)\b(CPF|RG|CNH|OAB|registro|inscri[çc][ãa]o|identidade|doc\.?)\b"
                      r"([^\n;]{0,25}?)\b\d[\d.\-/ ]{3,}\d\b")


def sem_dados_pessoais(s: str) -> str:
    """Tira números de documentos pessoais do texto do quadro (o laudo e a tela mostram)."""
    s = _CPF.sub("documento de identificação conferido", s or "")
    return _DOC_NUM.sub(lambda m: f"{m.group(1)}{m.group(2)}documento de identificação conferido", s)


class Triagem(BaseModel):
    quadro: dict[str, str]
    bloqueado: bool
    motivo: str = ""


async def rodar(job_id: str) -> Triagem:
    t = _comum.trabalho(job_id)
    pasta, rels = _comum.arquivos(job_id)
    # ORDEM 010 (custo): instruções enxutas — só P5 (checklist) e P7 (modalidades), sem P0/P3
    # inteiros, que eram reenviados a cada leitura de arquivo
    docs = ("P5", "P7") if TRIAGEM_ENXUTA else ("P0", "P3", "P5", "P7")
    sistema = conhecimento.base(job_id, docs, ("documentos",)) + "\n\n" + INSTRUCAO
    cont: dict[str, int] = {}
    for a in db.arquivos(job_id):
        cont[a["tipo"] or "outro"] = cont.get(a["tipo"] or "outro", 0) + 1
    contagem = ", ".join(f"{n} {k}" for k, n in sorted(cont.items())) or "nenhum"
    prompt = (
        "Formulário do trabalho (JSON):\n" + t.model_dump_json(indent=2)
        + f"\n\nCONTAGEM DE ARQUIVOS (real, use esta): {contagem}."
        + "\n\nArquivos do trabalho (caminhos relativos à pasta de trabalho):\n"
        + _comum.lista(rels))
    # ORDEM 008 (custo, corte "seguro"): a triagem confere SE os documentos existem e são do
    # imóvel; as fotos ela só precisa contar (a contagem real está no prompt e a lista de nomes
    # também). Abre só documentos + a foto da capa — antes abria as ~27 fotos, uma por uma.
    fotos = {a["caminho"] for a in db.arquivos(job_id) if a["tipo"] == "foto"}
    capa = db.fachada(job_id)
    ler = [r for r in rels if r.as_posix() not in fotos or r.as_posix() == capa]
    if fotos:
        prompt += ("\n\nAs fotos da vistoria NÃO precisam ser abertas (só a da capa, se houver): "
                   "considere-as presentes conforme a contagem e a lista acima.")
    r: Triagem = await ia.perguntar(sistema, prompt, Triagem, arquivos=ler, cwd=pasta)
    _comum.avisar_ignorados(job_id, "triagem", ia.ultimos_ignorados())
    r.quadro = {k: sem_dados_pessoais(v) for k, v in r.quadro.items()}
    r.motivo = sem_dados_pessoais(r.motivo)
    for k in CHAVES:
        r.quadro.setdefault(k, "")
    db.evento(job_id, "triagem", "resultado",
              "bloqueado: " + r.motivo if r.bloqueado else "triagem concluída",
              dados=r.model_dump(mode="json"))
    return r
