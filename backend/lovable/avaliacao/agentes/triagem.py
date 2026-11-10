"""Agente de Triagem: monta o quadro de entrada (P5) e decide se o trabalho pode seguir."""
from __future__ import annotations

from pydantic import BaseModel

from .. import conhecimento, db, ia
from . import _comum

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
"""


class Triagem(BaseModel):
    quadro: dict[str, str]
    bloqueado: bool
    motivo: str = ""


async def rodar(job_id: str) -> Triagem:
    t = _comum.trabalho(job_id)
    pasta, rels = _comum.arquivos(job_id)
    sistema = conhecimento.texto("P0", "P3", "P5", "P7") + "\n\n" + INSTRUCAO
    prompt = (
        "Formulário do trabalho (JSON):\n" + t.model_dump_json(indent=2)
        + "\n\nArquivos do trabalho (caminhos relativos à pasta de trabalho):\n"
        + _comum.lista(rels))
    r: Triagem = await ia.perguntar(sistema, prompt, Triagem, arquivos=rels, cwd=pasta)
    for k in CHAVES:
        r.quadro.setdefault(k, "")
    db.evento(job_id, "triagem", "resultado",
              "bloqueado: " + r.motivo if r.bloqueado else "triagem concluída",
              dados=r.model_dump(mode="json"))
    return r
