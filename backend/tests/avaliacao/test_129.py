"""129: corrigir erro só refaz o que o pedido toca — nunca a leitura dos documentos; correção rápida sem revisão de IA."""
import asyncio
from datetime import date

from lovable.avaliacao import db, ia, imagens_pedido, orquestrador, routes
from lovable.avaliacao.modelos import Trabalho


def _job():
    db.init()
    return db.criar_job(Trabalho(id="", numero=1, modalidade="AM", finalidade="ITCD", cliente="F", tipo="Casa",
                                 bairro="Jardim Curitiba", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
                                 data_base=date(2026, 11, 13), data_vistoria=date(2026, 11, 13)))


def test_5_textos_e_1_mapa_nao_voltam_a_extracao(monkeypatch):
    jid = _job()
    respostas = iter(
        [{"etapa": "extracao", "instrucao": "escreva o bairro como Jardim Curitiba I",
          "dados": [{"campo": "bairro", "valor": "Jardim Curitiba I"}]},
         {"etapa": "extracao", "instrucao": "refazer o laudo inteiro"},            # "refazer" solto
         {"etapa": "redacao", "instrucao": "trocar construção novo por nova"},
         {"etapa": "redacao", "instrucao": "tirar 'data-base' do item 10"},
         {"etapa": "redacao", "instrucao": "concordância no item 9.3"},
         {"etapa": "montagem", "instrucao": "refazer o mapa", "acoes": [{"tipo": "refazer_mapa", "valor": "contorno fino"}]}])

    async def fake(sistema, prompt, esquema, **kw):
        return esquema.model_validate(next(respostas))

    async def mapa(jid_, pedido):
        return {"ok": True, "motivo": ""}
    monkeypatch.setattr(ia, "perguntar", fake)
    monkeypatch.setattr(imagens_pedido, "refazer_demarcacao", mapa)
    monkeypatch.setattr(orquestrador, "enfileirar", lambda j: None)
    reab = []
    monkeypatch.setattr(orquestrador, "reabrir", lambda j, e, motivo="": reab.append(e))
    texto = "\n=====\n".join(["bairro com I", "refazer", "construção nova", "sem data-base", "concordância", "refazer o mapa"])
    r = asyncio.run(routes.corrigir(jid, routes.Correcao(texto=texto), _u={}))
    assert r["pedidos"] == 6 and reab == ["redacao"]                     # nunca extração nem cálculo
    assert db.setting(f"correcao_rapida:{jid}") == "1"                   # revisão do sistema por regra
    assert db.job(jid)["dados"]["bairro"] == "Jardim Curitiba I"


def test_correcao_rapida_pula_a_revisao_de_ia(monkeypatch, tmp_path):
    jid = _job()
    db.set_setting(f"correcao_rapida:{jid}", "1")
    pipe = orquestrador._Pipeline(jid)
    pdf = orquestrador._arquivos_finais(jid)["pdf"]
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4")

    async def nunca(*a, **k):
        raise AssertionError("a revisão completa de IA não roda numa correção")
    monkeypatch.setattr(orquestrador.revisor, "rodar", nunca)
    rev = asyncio.run(pipe._revisao())
    assert rev is not None and rev.aprovado
