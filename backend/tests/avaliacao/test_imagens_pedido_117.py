"""117-4 (imagem): o lote da Prefeitura sobre o print do Maps (zoom 19, ancorado no pino) e a troca de foto pela descrição."""
import asyncio
import io

from PIL import Image

from lovable.avaliacao import coletor_fonte as F, db, ia, imagens_pedido as IP
from lovable.avaliacao.modelos import Referencial
from tests.avaliacao.test_pagina_enviada import _job


def test_utm_e_projecao():
    la, lo = F.utm_para_latlon(677463.8443, 8162632.8111)          # um ponto em Goiânia (zona 22 Sul)
    assert abs(la + 16.611974) < 1e-5 and abs(lo + 49.336367) < 1e-5
    anel = [[500000 + dx, 8160000 + dy] for dx, dy in ((-6, -12), (6, -12), (6, 12), (-6, 12))]
    pin = F.utm_para_latlon(500000, 8160000)
    pol = F.projetar(anel, pin, (683, 450))
    larg, alt = pol[1][0] - pol[0][0], pol[0][1] - pol[2][1]
    assert 38 <= larg <= 46 and 80 <= alt <= 90                     # 12 × 24 m no zoom 19 (~0,29 m/px)
    assert all(abs(x - 683) < 30 and abs(y - 450) < 50 for x, y in pol)   # em volta do pino


def test_url_do_mapa(monkeypatch):
    class R:
        url = "https://www.google.com/maps/place/-16.612083,-49.336409/data=!4m6!3m5!1s0x0:0x0!8m2!3d-16.612083!4d-49.336409"
    monkeypatch.setattr("httpx.get", lambda *a, **k: R())
    url, ll = F.url_do_mapa("https://maps.app.goo.gl/x")
    assert ll == (-16.612083, -49.336409) and "@-16.612083,-49.336409,19z" in url and url.endswith("!1e3")


def test_trocar_foto_pela_descricao(monkeypatch):
    jid = _job()
    db.salvar_candidatos(jid, [Referencial(n=7, link="https://x.test/a", portal="x", bairro="B", tipologia="Casa",
                                           padrao="", idade_aparente="", descricao="", decisao="comparacao",
                                           fotos_url=["https://x.test/1.jpg", "https://x.test/2.jpg"])])

    class R:
        def __init__(self, cor):
            b = io.BytesIO()
            Image.new("RGB", (40, 30), cor).save(b, "PNG")
            self.content = b.getvalue()

        def raise_for_status(self):
            return None
    monkeypatch.setattr("httpx.get", lambda u, **k: R("blue" if u.endswith("2.jpg") else "gray"))
    monkeypatch.setattr(ia, "definir_contexto", lambda *a: None)

    async def olha(sistema, prompt, esquema, arquivos=(), **kw):
        assert len(arquivos) == 2 and "piscina" in prompt
        return esquema(numero=2, motivo="piscina no quintal")
    monkeypatch.setattr(ia, "perguntar", olha)
    r = asyncio.run(IP.trocar_foto(jid, 7, "a da piscina"))
    assert r["ok"] and r["foto"] == "mercado/enviado-7-foto-escolhida.jpg"
    assert next(x for x in db.candidatos(jid) if x.n == 7).foto == r["foto"]
    assert not asyncio.run(IP.trocar_foto(jid, 99, "a da piscina"))["ok"]


def test_refazer_sem_programa_do_mapa(monkeypatch):
    jid = _job()
    monkeypatch.setattr(IP.coletor_hub, "online", lambda: False)
    r = asyncio.run(IP.refazer_demarcacao(jid, "contorno fino"))
    assert r["ok"] is False and r["motivo"] in ("programa do mapa desligado", "o trabalho não tem o link do Google Maps (pino)")


def test_alvo_da_comparacao_126():
    """126-3c: "imóvel 2 do 9.3" é o 2º item da comparação, não o anúncio nº 2."""
    jid = _job()
    base = dict(portal="x", bairro="B", tipologia="Casa", padrao="", idade_aparente="", descricao="")
    db.salvar_candidatos(jid, [Referencial(n=k, link=f"https://x.test/{k}", escolhido=k <= 5, decisao="entra" if k <= 5 else "comparacao", **base)
                               for k in range(1, 8)])
    assert IP.n_do_alvo(jid, "imóvel 2 do item 9.3") == 7
    assert IP.n_do_alvo(jid, "comparação 1") == 6
    assert IP.n_do_alvo(jid, "referencial 3") == 3
    assert IP.n_do_alvo(jid, "anúncio 4") == 4
    assert IP.n_do_alvo(jid, "imóvel 9 do 9.3") is None
    r = asyncio.run(IP.trocar_foto_alvo(jid, "sem número", "a da piscina"))
    assert not r["ok"] and "não entendi" in r["motivo"]
