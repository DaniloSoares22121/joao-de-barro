"""117: os 9 pedidos do Capitão viram 9 pedidos; ações de modelo gravadas; conferência marca ✓/✗ (1 volta)."""
import asyncio
from datetime import date
from pathlib import Path

from lovable.avaliacao import ajustes, db
from lovable.avaliacao.modelos import Trabalho
from lovable.avaliacao.pedidos_revisao import dividir

TEXTO = ("Não usar data base de nem um outro documento\n=================================\n"
         "Documentação analisada, não precisa entrar a CNH do solicitante\n======================\n"
         "no item 9.3 mude o titulo\n===\nretire cadastro imobiliário 300,00 m²")


def _job():
    db.init()
    return db.criar_job(Trabalho(id="", numero=1, modalidade="AM", finalidade="ITCD", cliente="F", tipo="Casa",
                                 bairro="Jardim Curitiba", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
                                 data_base=date(2026, 11, 13), data_vistoria=date(2026, 11, 13)))


def test_separadores_viram_pedidos():
    assert len(dividir(TEXTO)) == 4


def test_acoes_de_modelo_e_conferencia(monkeypatch):
    jid = _job()
    p1 = ajustes.novo(jid, "mude o título do 9.3", "montagem", "título", [
        {"tipo": "titulo", "alvo": "9.3", "valor": "9.3. Imóveis ofertados pelo mercado abaixo de R$ 300 mil"}])
    p2 = ajustes.novo(jid, "tire a CNH", "montagem", "doc", [{"tipo": "tirar_documento", "alvo": "CNH"}])
    for p in (p1, p2):
        ajustes.aplicar_modelo(jid, p["acoes"])
    assert ajustes.titulos(jid) == {"9.3": "Imóveis ofertados pelo mercado abaixo de R$ 300 mil"}
    assert ajustes.docs_fora(jid) == ["CNH"]
    respostas = iter([[{"i": p1["i"], "feito": True, "onde_viu": "pág. 11"}, {"i": p2["i"], "feito": False, "motivo": "ainda no quadro"}],
                      [{"i": p2["i"], "feito": False, "motivo": "ainda no quadro"}]])

    import sys, types
    mod = types.ModuleType("lovable.avaliacao.conferir_pedidos")

    async def conferir(job_id, pdf, pedidos):
        return next(respostas)
    mod.conferir = conferir
    monkeypatch.setitem(sys.modules, "lovable.avaliacao.conferir_pedidos", mod)
    refazer, nao = asyncio.run(ajustes.conferir_no_pdf(jid, Path("x.pdf")))
    assert [p["i"] for p in refazer] == [p2["i"]] and nao == []          # 1ª falha: volta uma vez
    refazer, nao = asyncio.run(ajustes.conferir_no_pdf(jid, Path("x.pdf")))
    assert refazer == [] and [p["i"] for p in nao] == [p2["i"]]          # 2ª: "não consegui"
    res = ajustes.resumo(jid)
    assert res[0].startswith("✓ Feito: mude o título") and res[1].startswith("✗ Não consegui: tire a CNH — porque ainda no quadro")
    assert ajustes.linha_nao_consegui(nao[0]).startswith("Não consegui fazer: tire a CNH")


def test_126_pedido_com_duas_fotos_vira_dois(monkeypatch):
    from lovable.avaliacao import ia, imagens_pedido, orquestrador, routes
    jid = _job()

    async def fake(sistema, prompt, esquema, **kw):
        return esquema(etapa="montagem", instrucao="trocar fotos", acoes=[
            {"tipo": "trocar_foto", "alvo": "imóvel 2 do 9.3", "valor": "a da piscina"},
            {"tipo": "trocar_foto", "alvo": "imóvel 1 do 9.3", "valor": "a da fachada com blindex"}])
    chamadas = []

    async def troca(job_id, alvo, desc):
        chamadas.append((alvo, desc))
        return {"ok": alvo.startswith("imóvel 2"), "motivo": "" if alvo.startswith("imóvel 2") else "nenhuma foto mostra a fachada"}
    monkeypatch.setattr(ia, "perguntar", fake)
    monkeypatch.setattr(imagens_pedido, "trocar_foto_alvo", troca)
    monkeypatch.setattr(orquestrador, "enfileirar", lambda j: None)
    r = asyncio.run(routes.corrigir(jid, routes.Correcao(texto="no imóvel 2 do item 9.3 a foto com piscina; no imóvel 1 a fachada"), _u={}))
    itens = ajustes.lista(jid)
    assert r["pedidos"] == 2 and len(itens) == 2 and len(chamadas) == 2
    assert itens[0]["status"] == "pendente" and itens[1]["status"] == "nao_feito"     # cada um com o seu ✓/✗
    assert "fachada" in r["nao_deu"][0]
