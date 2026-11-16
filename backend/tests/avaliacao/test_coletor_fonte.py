import asyncio
from datetime import date

from PIL import Image

from lovable.avaliacao import coletor_fonte, coletor_hub, db, fonte_mercado, ia
from lovable.avaliacao.agentes import leitor_anuncio
from lovable.avaliacao.coletor_hub import Captura
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


def test_online_e_registro():
    assert coletor_fonte.ColetorFonte().online() == coletor_hub.online()
    assert isinstance(coletor_fonte.ColetorFonte(), fonte_mercado.FonteMercado)


def _mapa_de_mentira(arq):
    """Um "satélite" com variação de tom (quadradinhos), sem o vermelho do pino."""
    im = Image.new("RGB", (100, 80), (90, 110, 80))
    for x in range(0, 100, 10):
        for y in range(0, 80, 10):
            if (x + y) // 10 % 2:
                im.paste((200, 190, 170), (x, y, x + 10, y + 10))
    im.save(arq)


def test_print_em_branco_nao_substitui_o_mapa_121(monkeypatch):
    """121: o Maps devolveu a tela cinza: tenta de novo e, sem mapa, fica o de antes (imagem e resultado)."""
    jid = _job()
    pasta = db.pasta(jid)
    (pasta / "mercado").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 80), (242, 242, 242)).save(pasta / "mercado/cinza.jpg")
    _mapa_de_mentira(pasta / "maps.png")
    antes = (pasta / "maps.png").read_bytes()
    vistos = []

    async def executar(job_id, acao, url, timeout=120):
        vistos.append(url)
        return Captura(ok=True, print_path="mercado/cinza.jpg")
    monkeypatch.setattr(coletor_hub, "executar", executar)
    t = Trabalho.model_validate(db.job(jid)["dados"])
    asyncio.run(coletor_fonte.capturar_maps(jid, t, refazer=True))
    assert len(vistos) == 2                                           # tentou de novo (o link é o mesmo nos testes)
    assert (pasta / "maps.png").read_bytes() == antes                 # o mapa bom ficou
    with db._conn() as c:
        msgs = [r[0] for r in c.execute("SELECT msg FROM av_events WHERE job=? AND etapa='localizacao'", (jid,))]
    assert any("tela em branco" in m and "fica o mapa de antes" in m for m in msgs)
    assert not any(m.startswith("mapa capturado") for m in msgs)


def test_maps_grava_localizacao(monkeypatch):
    jid = _job()
    pasta = db.pasta(jid)
    (pasta / "mercado").mkdir(parents=True, exist_ok=True)
    _mapa_de_mentira(pasta / "mercado/m.jpg")
    vistos = []

    async def executar(job_id, acao, url, timeout=120):
        vistos.append((acao, url))
        return Captura(ok=True, print_path="mercado/m.jpg")

    async def perguntar(sistema, prompt, esquema, arquivos=[], cwd=None, modelo="", **_kw):
        assert [p.name for p in arquivos] == ["maps.png"] and cwd == pasta
        return esquema.model_validate({"poligono": [[10, 10], [500, 5], [50, -3], [1]]})
    monkeypatch.setattr(coletor_hub, "executar", executar)
    monkeypatch.setattr(ia, "perguntar", perguntar)
    t = Trabalho.model_validate(db.job(jid)["dados"])
    asyncio.run(coletor_fonte.capturar_maps(jid, t))
    assert vistos == [("maps", "https://maps.app.goo.gl/x")]
    # ORDEM 003 (lote do mapa a partir do pino, P6 erro 6): a localização grava também a
    # posição do pino ("pino"); nesta imagem branca não há pino -> None.
    assert db.resultado(jid, "localizacao") == {"imagem": "maps.png",
                                                "poligono": [[10, 10], [99, 5], [50, 0]], "pino": None,
                                                "fonte_poligono": "pino_ou_ia", "zoom": None}
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


def test_hub_status_saneado():
    assert coletor_hub._status(404) == 404
    assert coletor_hub._status("404") is None and coletor_hub._status(True) is None




def test_mapa_em_branco_volta_a_ultima_captura_boa_125(monkeypatch):
    """125-2: o maps.png já está em branco e a nova captura também sai em branco: volta a última captura boa."""
    import os
    import time
    jid = _job()
    pasta = db.pasta(jid)
    (pasta / "mercado").mkdir(parents=True, exist_ok=True)
    boa = pasta / "mercado" / ("a" * 32 + ".jpg")
    _mapa_de_mentira(boa)
    img = Image.open(boa).resize((1366, 900))
    import random
    px = img.load()
    for _ in range(40000):                                         # ruído: arquivo de tamanho de print real
        px[random.randrange(1366), random.randrange(900)] = tuple(random.randrange(256) for _ in range(3))
    img.save(boa, quality=95)
    db.evento(jid, "localizacao", "resultado", "mapa capturado",
              dados={"imagem": "maps.png", "poligono": [[1, 1], [9, 1], [9, 9]], "pino": [5, 5]})
    agora = time.time()
    os.utime(boa, (agora, agora))
    Image.new("RGB", (1366, 900), (242, 242, 242)).save(pasta / "maps.png")      # o mapa atual ficou em branco
    Image.new("RGB", (1366, 900), (242, 242, 242)).save(pasta / "mercado/cinza.jpg")

    async def executar(job_id, acao, url, timeout=120):
        return Captura(ok=True, print_path="mercado/cinza.jpg")
    monkeypatch.setattr(coletor_hub, "executar", executar)
    t = Trabalho.model_validate(db.job(jid)["dados"])
    asyncio.run(coletor_fonte.capturar_maps(jid, t, refazer=True))
    assert not coletor_fonte._mapa_ruim(pasta / "maps.png")
    r = db.resultado(jid, "localizacao")
    assert r["poligono"] == [[1, 1], [9, 1], [9, 9]] and r["restaurado_de"] == f"mercado/{boa.name}"
