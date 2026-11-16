"""ORDEM L198: o laudo continua no padrão JdB e pega do modelo do avaliador só a formatação (fonte, tamanho e cores)
e os itens que o nosso não tem (antes da Assinatura). Sem IA na leitura; IA simulada na parte de "regras"."""
import asyncio
import io
import uuid

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from fastapi import UploadFile

from lovable.avaliacao import avaliadores as A
from lovable.avaliacao import db, docx_builder, ia
from lovable.avaliacao import docx_partes as X
from lovable.avaliacao import modelo_avaliador as MA
from lovable.avaliacao import rotas_avaliadores as RA

from .test_docx import _job, _textos


def _modelo_inventado() -> bytes:
    d = Document()
    st = d.styles["Normal"]; st.font.name = "Georgia"; st.font.size = Pt(12)
    def titulo(t):
        p = d.add_paragraph(); r = p.add_run(t); r.bold = True; r.font.color.rgb = RGBColor(0x8B, 0x00, 0x00); r.font.size = Pt(14)
    def corpo(t):
        p = d.add_paragraph(); r = p.add_run(t); r.font.color.rgb = RGBColor(0x2E, 0x7D, 0x32)
    for t, c in (("1. Finalidade da avaliação", "Texto da finalidade."),
                 ("2. Glossário de termos técnicos", "Valor de mercado: quantia mais provável pela qual se negocia um bem."),
                 ("3. Metodologia", "Método comparativo."),
                 ("4. Política de privacidade dos dados", "Os dados recebidos são usados só para este trabalho e guardados com sigilo."),
                 ("5. Conclusão", "O valor do imóvel de Fulano Inventado é R$ 500.000,00 em 10/10/2026.")):
        titulo(t); corpo(c)
    b = io.BytesIO(); d.save(b); return b.getvalue()


def test_le_formato_e_itens_sem_ia():
    dados = _modelo_inventado()
    f = MA.ler_formato("meu.docx", dados)
    assert f["fonte"] == "Georgia" and f["tamanho"] == 12.0
    assert (f["cor_principal"], f["cor_destaque"]) == ("8B0000", "2E7D32")          # a dos títulos é a principal
    itens = MA.ler_itens("meu.docx", dados)
    assert [x["titulo"] for x in itens] == ["Glossário de termos técnicos", "Política de privacidade dos dados"]
    assert not any(x["depende_do_trabalho"] for x in itens)              # "Conclusão" já temos; ela tinha nome e valor


def test_laudo_sai_com_a_formatacao_e_os_itens_dele(monkeypatch):
    async def falsa(sistema, prompt, esquema, **k):
        return esquema(topicos=["Glossário no fim"])
    monkeypatch.setattr(ia, "perguntar", falsa)
    monkeypatch.setattr(ia, "definir_contexto", lambda *a, **k: None)
    av = A.cadastrar(f"l198-{uuid.uuid4().hex[:8]}@teste.local", "senha-l198-ok", {"nome": "Avaliador L198", "cnai": "1"})
    u = {"avaliador_id": av}
    r = asyncio.run(RA.subir_modelo(qual="laudo", arquivo=UploadFile(file=io.BytesIO(_modelo_inventado()), filename="meu.docx"),
                                    modalidade="OV", _u=u))
    assert r["formato"]["fonte"] == "Georgia" and len(r["itens"]) == 2
    asyncio.run(RA.confirmar_topicos(RA.Confirmados(topicos=r["topicos"], modalidade="OV", guardado=r["guardado"],
                                                    itens=[0, 1]), _u=u))
    jid, sel, res = _job()
    j = db.job(jid)
    from lovable.avaliacao.modelos import Trabalho
    db.atualizar_dados(jid, Trabalho.model_validate({**j["dados"], "avaliador_id": av}))
    docx_path = docx_builder.montar(jid, _textos(), res, sel)
    d = Document(str(docx_path))
    assert d.styles["Normal"].font.name == "Georgia" and d.styles["Normal"].font.size == Pt(12)
    textos = [p.text for p in d.paragraphs]
    i_gl = next(i for i, t in enumerate(textos) if "GLOSSÁRIO DE TERMOS TÉCNICOS" in t)
    i_pr = next(i for i, t in enumerate(textos) if "POLÍTICA DE PRIVACIDADE DOS DADOS" in t)
    i_as = next(i for i, t in enumerate(textos) if t.strip().endswith("ASSINATURA"))
    assert i_gl < i_pr < i_as                                           # antes da Assinatura, renumerados
    assert any("quantia mais provável" in t for t in textos)
    assert all("Fulano Inventado" not in t and "500.000" not in t for t in textos)   # a "Conclusão" dele (com dados) não entrou
    cores = {c.get(qn("w:val")) for c in d.element.body.iter(qn("w:color"))}
    assert "8B0000" in cores                                            # a cor principal dele no lugar do azul
    assert "18283B" not in cores
    # o restante igual: os itens do nosso modelo continuam
    for t in ("FINALIDADE DA AVALIAÇÃO", "METODOLOGIA", "DETERMINAÇÃO DO VALOR DE MERCADO", "DECLARAÇÕES DO AVALIADOR"):
        assert any(t in x for x in textos), t


# ------------------------------------------------------------------ L199: "Regras de escrita" só com regra de escrita
QUATRO = ["Sumário com 5 itens numerados", "Conclusão em parágrafo único com o valor por extenso",
          "Fotos em grade de 2 colunas, com legenda curta", "Assinatura com CRECI e CNAI no fim"]


def test_l199_separa_escrita_de_estrutura():
    escrita, fora = MA.separar_regras(QUATRO + ["Tom formal e frases curtas"])
    assert escrita == ["Legenda curta", "Tom formal e frases curtas"]
    assert fora == QUATRO[:2] + ["Fotos em grade de 2 colunas"]         # a assinatura com CRECI/CNAI já é nossa: nem aparece


def test_l199_subir_e_regra_antiga_de_estrutura_deixa_de_valer(monkeypatch):
    from lovable.avaliacao import fichas
    async def falsa(sistema, prompt, esquema, **k):
        assert "SÓ as regras de ESCRITA" in sistema                     # o pedido que já existe, com o filtro (sem IA a mais)
        return esquema(topicos=QUATRO + ["Tom formal e frases curtas"])
    monkeypatch.setattr(ia, "perguntar", falsa)
    monkeypatch.setattr(ia, "definir_contexto", lambda *a, **k: None)
    av = A.cadastrar(f"l199-{uuid.uuid4().hex[:8]}@teste.local", "senha-l199-ok", {"nome": "Avaliador L199", "cnai": "1"})
    u = {"avaliador_id": av}
    r = asyncio.run(RA.subir_modelo(qual="laudo", arquivo=UploadFile(file=io.BytesIO(_modelo_inventado()), filename="meu.docx"),
                                    modalidade="OV", _u=u))
    assert r["topicos"] == ["Legenda curta", "Tom formal e frases curtas"] and r["fora_estrutura"] == QUATRO[:2] + ["Fotos em grade de 2 colunas"]
    # a tela mandando uma regra de estrutura mesmo assim: o servidor não grava
    ok = asyncio.run(RA.confirmar_topicos(RA.Confirmados(topicos=["Sumário com 5 itens numerados", "Tom formal"], modalidade="OV",
                                                         guardado=r["guardado"]), _u=u))
    assert [fichas.obter(f)["decisao"] for f in ok["regras"]] == ["Tom formal"]
    # regra de estrutura salva antes (L198) continua guardada, mas não vale mais no laudo
    fichas.gravar({"id": "F-9199", "titulo": "Sumário", "situacao": "laudo do próprio avaliador", "decisao": "Sumário com 5 itens numerados",
                   "porque": "teste", "tipo": "regra", "nivel": "aprendido", "escopo": "avaliador", "avaliador_id": av,
                   "fonte": "laudo próprio (anonimizado)"}, quem=av, acao="teste")
    assert fichas.obter("F-9199")["ativa"]
    decisoes = [f["decisao"] for f in fichas.buscar(av, modalidade="OV")]
    assert "Sumário com 5 itens numerados" not in decisoes and "Tom formal" in decisoes
