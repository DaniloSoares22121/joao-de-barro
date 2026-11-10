import asyncio
import io
from datetime import date

from PIL import Image

from lovable.avaliacao import coletor_fonte, coletor_hub, db, fonte_mercado, ia
from lovable.avaliacao.agentes import leitor_anuncio
from lovable.avaliacao.coletor_hub import Captura
from lovable.avaliacao.fonte_mercado import Consulta
from lovable.avaliacao.modelos import Referencial, Trabalho
from tests.avaliacao.conftest import numero_livre

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 10


def _job() -> str:
    db.init()
    return db.criar_job(Trabalho(
        id="", numero=numero_livre(120), modalidade="OV", finalidade="Venda", cliente="W", tipo="Sobrado",
        bairro="Jardim Vila Boa", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
        data_base=date(2026, 10, 20), data_vistoria=date(2026, 10, 18)))


def _avisos(jid):
    return [e["msg"] for e in db.eventos_desde(jid, 0) if e["nivel"] == "aviso"]


def _setup(monkeypatch, executar):
    pausas = []

    async def sleep(s):
        pausas.append(s)

    async def ler(job_id, cap, portal, comuns=frozenset()):
        return Referencial(n=0, link=cap.url_final, portal=portal, bairro="B", tipologia="Sobrado",
                           padrao="", idade_aparente="", descricao="", preco=1.0, area_m2=1.0)

    monkeypatch.setattr(coletor_fonte, "_sleep", sleep)
    monkeypatch.setattr(coletor_hub, "executar", executar)
    monkeypatch.setattr(leitor_anuncio, "ler", ler)

    def rede(*a, **k):
        raise AssertionError("servidor nao baixa URLs")
    import httpx
    import urllib.request
    monkeypatch.setattr(httpx.AsyncClient, "__init__", rede)
    monkeypatch.setattr(httpx.Client, "__init__", rede)
    monkeypatch.setattr(urllib.request, "urlopen", rede)
    return pausas


def test_um_portal_bloqueado(monkeypatch):
    jid = _job()
    chamadas = []

    async def executar(job_id, acao, url, timeout=120):
        chamadas.append((acao, url))
        if "olx" in url or "vivareal" in url or "imovelweb" in url:
            return Captura(bloqueado=True)
        if acao == "busca":
            return Captura(ok=True, links=["https://www.zapimoveis.com.br/imovel/a-1/",
                                           "https://www.zapimoveis.com.br/venda/x/",
                                           "https://www.zapimoveis.com.br/imovel/b-2/"])
        if url.endswith("a-1/"):
            return Captura(ok=True, url_final=url, fotos=["https://img/x.png"],
                           foto_path="mercado/f-foto.png")
        return Captura(ok=True, url_final=url, fotos=["https://img/x.png"])
    pausas = _setup(monkeypatch, executar)
    refs = asyncio.run(coletor_fonte.ColetorFonte().buscar(
        jid, [Consulta(tipologia="Sobrado", bairro="Jardim Vila Boa", cidade="Goiânia")]))
    assert [r.link for r in refs] == ["https://www.zapimoveis.com.br/imovel/a-1/",
                                      "https://www.zapimoveis.com.br/imovel/b-2/"]
    assert all(r.portal == "ZAP Imóveis" for r in refs)
    assert refs[0].foto == "mercado/f-foto.png" and refs[1].foto == ""   # URL sem fotos_b64: nada
    assert "portal bloqueado: OLX" in _avisos(jid)
    assert len(pausas) == len(chamadas) - 1 and all(4 <= p <= 9 for p in pausas)


def test_limite_20_anuncios(monkeypatch):
    jid = _job()
    abertos = []

    async def executar(job_id, acao, url, timeout=120):
        if acao == "busca":
            return Captura(ok=True, links=[f"https://www.zapimoveis.com.br/imovel/{url[-12:]}{i}/"
                                           for i in range(30)])
        abertos.append(url)
        return Captura(ok=True, url_final=url)
    _setup(monkeypatch, executar)
    f = coletor_fonte.ColetorFonte()
    c = [Consulta(tipologia="Casa", bairro=b, cidade="Goiânia") for b in ("A", "B")]
    refs = asyncio.run(f.buscar(jid, c))
    refs += asyncio.run(f.buscar(jid, c))  # segunda rodada no mesmo trabalho não estoura
    assert len(abertos) == 20 and len(refs) == 20


def test_online_e_registro():
    assert coletor_fonte.ColetorFonte().online() == coletor_hub.online()
    assert isinstance(coletor_fonte.ColetorFonte(), fonte_mercado.FonteMercado)


def test_maps_grava_localizacao(monkeypatch):
    jid = _job()
    pasta = db.pasta(jid)
    (pasta / "mercado").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 80), "white").save(pasta / "mercado/m.jpg")
    vistos = []

    async def executar(job_id, acao, url, timeout=120):
        vistos.append((acao, url))
        return Captura(ok=True, print_path="mercado/m.jpg")

    async def perguntar(sistema, prompt, esquema, arquivos=[], cwd=None, modelo=""):
        assert [p.name for p in arquivos] == ["maps.png"] and cwd == pasta
        return esquema.model_validate({"poligono": [[10, 10], [500, 5], [50, -3], [1]]})
    monkeypatch.setattr(coletor_hub, "executar", executar)
    monkeypatch.setattr(ia, "perguntar", perguntar)
    t = Trabalho.model_validate(db.job(jid)["dados"])
    asyncio.run(coletor_fonte.capturar_maps(jid, t))
    assert vistos == [("maps", "https://maps.app.goo.gl/x")]
    assert db.resultado(jid, "localizacao") == {"imagem": "maps.png",
                                                "poligono": [[10, 10], [99, 5], [50, 0]]}
    assert (pasta / "maps.png").exists()
    asyncio.run(coletor_fonte.capturar_maps(jid, t))   # retomável: não refaz
    assert len(vistos) == 1


def test_maps_offline_aviso(monkeypatch):
    jid = _job()

    async def executar(job_id, acao, url, timeout=120):
        raise coletor_hub.ColetorOffline("coletor offline")
    monkeypatch.setattr(coletor_hub, "executar", executar)
    asyncio.run(coletor_fonte.capturar_maps(jid, Trabalho.model_validate(db.job(jid)["dados"])))
    assert db.resultado(jid, "localizacao") is None
    assert any("mapa não capturado" in a for a in _avisos(jid))


def test_offline_no_meio_propaga_e_zera_estado(monkeypatch):
    jid = _job()

    async def executar(job_id, acao, url, timeout=120):
        if acao == "anuncio":
            raise coletor_hub.ColetorOffline("caiu")
        return Captura(ok=True, links=["https://www.zapimoveis.com.br/imovel/a-1/"])
    _setup(monkeypatch, executar)
    f = coletor_fonte.ColetorFonte()
    import pytest
    with pytest.raises(coletor_hub.ColetorOffline):
        asyncio.run(f.buscar(jid, [Consulta(tipologia="Casa", bairro="A", cidade="G")]))
    assert jid not in f._estado
    f._st(jid)
    f.encerrar(jid)
    assert jid not in f._estado


def test_busca_sem_resultados_nao_abre_vitrine(monkeypatch):
    jid = _job()
    chamadas = []
    vitrine = ["https://www.zapimoveis.com.br/imovel/venda-apto-id-1/?source=showcase%2CERROR+PAGE"]

    async def executar(job_id, acao, url, timeout=120):
        chamadas.append((acao, url))
        if "zapimoveis" in url:
            return Captura(ok=True, url_final=url, links=vitrine,
                           texto="Oops.\nNão conseguimos encontrar a página solicitada.")
        return Captura(ok=True, url_final=url, status=404,
                       links=["https://www.vivareal.com.br/imovel/x-id-2/"])
    _setup(monkeypatch, executar)
    c = Consulta(tipologia="Sobrado", bairro="Jardim Vila Boa", cidade="Goiânia")
    refs = asyncio.run(coletor_fonte.ColetorFonte().buscar(jid, [c]))
    assert refs == []
    assert all(a == "busca" for a, _ in chamadas)
    av = _avisos(jid)
    assert "busca sem resultados: ZAP Imóveis" in av and "busca sem resultados: Viva Real" in av


def test_hub_status_saneado():
    assert coletor_hub._status(404) == 404
    assert coletor_hub._status("404") is None and coletor_hub._status(True) is None


def test_anuncio_indisponivel_nao_e_lido(monkeypatch):
    jid = _job()
    base = "https://www.zapimoveis.com.br/imovel/"
    links = [base + "a-1/", base + "b-2/", base + "c-3/", base + "d-4/"]

    async def executar(job_id, acao, url, timeout=120):
        if "zapimoveis" not in url:
            return Captura(bloqueado=True)
        if acao == "busca":
            return Captura(ok=True, links=links)
        if url.endswith("a-1/"):
            return Captura(ok=True, url_final=url, status=404)
        if url.endswith("b-2/"):
            return Captura(ok=True, url_final=url, texto="Oops. Não conseguimos encontrar a página solicitada.")
        if url.endswith("c-3/"):
            return Captura(ok=True, url_final="https://www.zapimoveis.com.br/venda/casas/go+goiania/", status=200)
        return Captura(ok=True, url_final=url, status=200)
    _setup(monkeypatch, executar)
    refs = asyncio.run(coletor_fonte.ColetorFonte().buscar(
        jid, [Consulta(tipologia="Sobrado", bairro="Jardim Vila Boa", cidade="Goiânia")]))
    assert [r.link for r in refs] == [base + "d-4/"]
    av = _avisos(jid)
    for l in links[:3]:
        assert f"anúncio indisponível: {l}" in av
