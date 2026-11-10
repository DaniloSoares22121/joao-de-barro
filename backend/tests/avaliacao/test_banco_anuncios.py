"""D1 (banco de comparáveis av_anuncios) e D2 (leitura em paralelo, modelo leve, limpeza)."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from lovable import config
from lovable.avaliacao import coletor_fonte, coletor_hub, db, ia
from lovable.avaliacao.agentes import leitor_anuncio
from lovable.avaliacao.coletor_hub import Captura
from lovable.avaliacao.fonte_mercado import Consulta
from lovable.avaliacao.modelos import Referencial

from .test_coletor_fonte import _job

ZAP = "https://www.zapimoveis.com.br/imovel/"


def _bairro() -> str:
    return f"Setor Teste {uuid.uuid4().hex[:6]}"


def _desde(dias=30) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()


def _setup(monkeypatch, executar, ler):
    async def sleep(s):
        pass
    monkeypatch.setattr(coletor_fonte, "_sleep", sleep)
    monkeypatch.setattr(coletor_hub, "executar", executar)
    monkeypatch.setattr(leitor_anuncio, "ler", ler)


def _ref(cap, portal, bairro, preco=500000.0, area=180.0):
    return Referencial(n=0, link=cap.url_final, portal=portal, bairro=bairro,
                       tipologia="Sobrado residencial", padrao="", idade_aparente="",
                       descricao="d", preco=preco, area_m2=area, quartos=3,
                       print_=cap.print_path or "")


def test_anuncio_lido_e_gravado_e_reaproveitado_em_outro_trabalho(monkeypatch):
    bairro = _bairro()
    j1, j2 = _job(), _job()
    (db.pasta(j1) / "mercado").mkdir(parents=True, exist_ok=True)
    (db.pasta(j1) / "mercado/f.png").write_bytes(b"foto")
    abertos = []

    async def executar(job_id, acao, url, timeout=120):
        if "zapimoveis" not in url:
            return Captura(bloqueado=True)
        if acao == "busca":
            return Captura(ok=True, links=[ZAP + "a-1/?utm=x"])
        abertos.append((job_id, url))
        return Captura(ok=True, url_final=url, texto="t", foto_path="mercado/f.png")

    async def ler(job_id, cap, portal, comuns=frozenset()):
        return _ref(cap, portal, bairro)
    _setup(monkeypatch, executar, ler)
    c = [Consulta(tipologia="Sobrado", bairro=bairro, cidade="Goiânia", area_min=100,
                  area_max=300)]
    r1 = asyncio.run(coletor_fonte.ColetorFonte().buscar(j1, c))
    assert len(r1) == 1 and len(abertos) == 1
    r2 = asyncio.run(coletor_fonte.ColetorFonte().buscar(j2, c))
    assert len(abertos) == 1                     # não abriu de novo no 2º trabalho
    assert len(r2) == 1 and r2[0].link == ZAP + "a-1" and r2[0].bairro == bairro
    assert r2[0].tipologia == "Sobrado residencial" and r2[0].preco == 500000.0
    assert r2[0].foto.startswith("anuncios/")
    assert (db.pasta(j2) / r2[0].foto).read_bytes() == b"foto"
    # fora da faixa de área: não reaproveita
    assert db.anuncios_recentes(coletor_fonte.bairro_norm(bairro), "sobrado", _desde(), 200) == []
    assert len(db.anuncios_recentes(coletor_fonte.bairro_norm(bairro), "sobrado", _desde())) == 1


def test_visto_ha_mais_de_30_dias_nao_e_reaproveitado():
    bairro = _bairro()
    db.salvar_anuncio({"url_limpa": ZAP + "velho" + bairro,
                       "bairro_norm": coletor_fonte.bairro_norm(bairro), "tipologia": "casa",
                       "area_m2": 100, "preco": 1e5, "visto_em": _desde(31)})
    assert db.anuncios_recentes(coletor_fonte.bairro_norm(bairro), "casa", _desde()) == []


def test_dedup_entre_portais_por_impressao_digital():
    bairro = _bairro()
    bn = coletor_fonte.bairro_norm(bairro)
    dig = coletor_fonte.impressao_digital(bairro, 180.4, 499_600, 3)
    assert dig == coletor_fonte.impressao_digital(bairro, 179.6, 500_400, 3)
    assert dig != coletor_fonte.impressao_digital(bairro, 180, 500_000, 4)
    assert coletor_fonte.impressao_digital(bairro, None, 500_000, 3) == ""
    t0 = datetime.now(timezone.utc)
    db.salvar_anuncio({"url_limpa": ZAP + bn, "portal": "ZAP Imóveis", "bairro_norm": bn,
                       "tipologia": "casa", "area_m2": 180, "preco": 5e5, "quartos": 3,
                       "impressao_digital": dig, "visto_em": t0.isoformat()})
    db.salvar_anuncio({"url_limpa": "https://www.vivareal.com.br/imovel/" + bn,
                       "portal": "Viva Real", "bairro_norm": bn, "tipologia": "casa",
                       "area_m2": 180, "preco": 5e5, "quartos": 3, "impressao_digital": dig,
                       "visto_em": (t0 + timedelta(seconds=1)).isoformat()})
    rows = db.anuncios_recentes(bn, "casa", (t0 - timedelta(days=1)).isoformat())
    assert [r["portal"] for r in rows] == ["Viva Real"]   # mantém o mais recente


def test_captura_todos_e_le_em_paralelo_no_maximo_3(monkeypatch):
    bairro = _bairro()
    jid = _job()
    ordem, ativos, pico = [], [0], [0]

    async def executar(job_id, acao, url, timeout=120):
        if "zapimoveis" not in url:
            return Captura(bloqueado=True)
        if acao == "busca":
            return Captura(ok=True, links=[f"{ZAP}p-{i}/" for i in range(7)])
        ordem.append("captura")
        return Captura(ok=True, url_final=url, texto="t")

    async def ler(job_id, cap, portal, comuns=frozenset()):
        ordem.append("leitura")
        ativos[0] += 1
        pico[0] = max(pico[0], ativos[0])
        await asyncio.sleep(0.01)
        ativos[0] -= 1
        if cap.url_final.endswith("p-3/"):
            raise ia.IAFalhou("x")
        return _ref(cap, portal, bairro, preco=1e5 * (1 + len(ordem)))
    _setup(monkeypatch, executar, ler)
    refs = asyncio.run(coletor_fonte.ColetorFonte().buscar(
        jid, [Consulta(tipologia="Sobrado", bairro=bairro, cidade="Goiânia")]))
    assert ordem[:7] == ["captura"] * 7 and ordem.count("leitura") == 7
    assert 1 < pico[0] <= coletor_fonte.LEITURAS_PARALELAS
    assert [r.link for r in refs] == [f"{ZAP}p-{i}/" for i in range(7) if i != 3]


def test_limpar_tira_boilerplate_e_corta():
    menu = "Comprar\nAlugar\nAnunciar"
    texto = (f"{menu}\nab\n\nSobrado 3 quartos\n{menu}\nR$ 500.000\n"
             "Rodapé © 2026\nRodapé © 2026")
    out = leitor_anuncio.limpar(texto)
    assert out.splitlines() == ["Comprar", "Alugar", "Anunciar", "Sobrado 3 quartos",
                                "R$ 500.000", "Rodapé © 2026"]
    comuns = leitor_anuncio.linhas_comuns([texto, menu + "\nCasa", menu + "\nLote"])
    assert {"Comprar", "Alugar", "Anunciar"} <= comuns
    assert leitor_anuncio.limpar(texto, comuns).splitlines()[0] == "Sobrado 3 quartos"
    longo = "\n".join(f"linha {i} " + "x" * 50 for i in range(1000))
    assert len(leitor_anuncio.limpar(longo)) == leitor_anuncio.MAX_TEXTO == 20_000


def test_leitor_usa_modelo_leve_e_captura_publicacao(monkeypatch):
    usados = []

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo=""):
        usados.append((modelo, prompt))
        return esquema(negocio="venda", preco=1.0, area_m2=1.0)
    monkeypatch.setattr(ia, "perguntar", fake)
    cap = Captura(ok=True, url_final=ZAP + "z", texto="Casa\nPublicado em 05/03/2026\nok")
    r = asyncio.run(leitor_anuncio.ler("j", cap, "ZAP"))
    assert usados[0][0] == config.LIGHT_MODEL and "haiku" in config.LIGHT_MODEL
    assert r.publicado_em == "2026-03-05"
    monkeypatch.setattr(config, "LIGHT_MODEL", "")
    asyncio.run(leitor_anuncio.ler("j", cap, "ZAP"))
    assert usados[1][0] == ""                    # sem modelo leve: padrão do ia.py

    async def fake_data(sistema, prompt, esquema, arquivos=[], cwd=None, modelo=""):
        return esquema(negocio="venda", publicado_em="2026-01-02")
    monkeypatch.setattr(ia, "perguntar", fake_data)
    assert asyncio.run(leitor_anuncio.ler("j", cap, "ZAP")).publicado_em == "2026-01-02"


def _anuncio_banco(job_origem, foto, print_=""):
    return {"id": 9, "url_limpa": ZAP + uuid.uuid4().hex, "portal": "ZAP", "bairro_norm": "b",
            "bairro": "B", "tipologia": "casa", "tipologia_txt": "Casa", "quartos": 3,
            "suites": 0, "lote_m2": None, "area_m2": 100, "preco": 1e5, "padrao": "",
            "idade_aparente": "", "descricao": "", "foto_path": foto, "print_path": print_,
            "publicado_em": None, "visto_em": _desde(1)}


def test_copia_do_banco_so_aceita_imagens_de_mercado():
    j1, j2 = _job(), _job()
    (db.pasta(j1) / "mercado").mkdir(parents=True, exist_ok=True)
    (db.pasta(j1) / "mercado/ok.jpg").write_bytes(b"jpg")
    (db.pasta(j1) / "matricula.pdf").write_bytes(b"%PDF")
    (db.pasta(j1) / "iptu.png").write_bytes(b"png")
    (db.pasta(j1) / "mercado/x.pdf").write_bytes(b"%PDF")
    cp = coletor_fonte._copiar
    assert cp(j2, f"{j1}/mercado/ok.jpg", 1).startswith("anuncios/")
    assert cp(j2, f"{j1}/matricula.pdf", 1) == ""          # documento de outro job
    assert cp(j2, f"{j1}/iptu.png", 1) == ""               # fora de mercado/
    assert cp(j2, f"{j1}/mercado/x.pdf", 1) == ""          # extensão
    assert cp(j2, f"{j1}/mercado/../matricula.pdf", 1) == ""
    assert cp(j2, f"{j2}/../{j1}/iptu.png", 1) == ""       # "mesmo job" com traversal
    assert cp(j1, f"{j1}/../{j2}/x.png", 1) == ""
    assert cp(j1, f"{j1}/mercado/ok.jpg", 1) == "mercado/ok.jpg"   # mesmo job: sem cópia
    r = coletor_fonte._referencial_do_banco(j2, _anuncio_banco(j1, f"{j1}/matricula.pdf"))
    assert r.foto == ""


def test_gravar_anuncio_rejeita_caminho_fora_de_mercado():
    jid = _job()
    url = ZAP + uuid.uuid4().hex
    r = Referencial(n=0, link=url, portal="ZAP", bairro="Bx", tipologia="Casa", padrao="",
                    idade_aparente="", descricao="", preco=1e5, area_m2=90, quartos=2,
                    foto="matricula.pdf", print_="../outro/mercado/p.png")
    coletor_fonte.gravar_anuncio(jid, r)
    reg = [a for a in db.anuncios_recentes(coletor_fonte.bairro_norm("Bx"), "casa", _desde())
           if a["url_limpa"] == url][0]
    assert reg["foto_path"] == "" and reg["print_path"] == ""
    r2 = r.model_copy(update={"foto": "mercado/f.jpg", "print_": "mercado/p.png"})
    coletor_fonte.gravar_anuncio(jid, r2)
    reg = [a for a in db.anuncios_recentes(coletor_fonte.bairro_norm("Bx"), "casa", _desde())
           if a["url_limpa"] == url][0]
    assert reg["foto_path"] == f"{jid}/mercado/f.jpg" and reg["print_path"] == f"{jid}/mercado/p.png"


def _salvar(url, portal, bn, dig, t, cidade="Goiânia", **kw):
    db.salvar_anuncio({"url_limpa": url, "portal": portal, "bairro_norm": bn, "cidade": cidade,
                       "tipologia": "casa", "area_m2": 80, "preco": 3e5, "quartos": 2,
                       "impressao_digital": dig, "visto_em": t.isoformat(), **kw})


def test_dedup_mesmo_portal_mantem_as_duas_unidades_e_marca_substituido():
    bn = coletor_fonte.bairro_norm(_bairro())
    dig = coletor_fonte.impressao_digital(bn, 80, 3e5, 2)
    t0 = datetime.now(timezone.utc)
    _salvar(ZAP + bn + "-ap1", "ZAP Imóveis", bn, dig, t0)
    _salvar(ZAP + bn + "-ap2", "ZAP Imóveis", bn, dig, t0 + timedelta(seconds=1))
    desde = (t0 - timedelta(days=1)).isoformat()
    assert len(db.anuncios_recentes(bn, "casa", desde)) == 2   # 2 unidades iguais, mesmo portal
    _salvar("https://www.vivareal.com.br/imovel/" + bn, "Viva Real", bn, dig,
            t0 + timedelta(seconds=2))
    rows = db.anuncios_recentes(bn, "casa", desde)
    assert [r["portal"] for r in rows] == ["Viva Real"]
    with db._conn() as c:                                       # não apaga: marca
        velhos = c.execute("SELECT substituido_por FROM av_anuncios WHERE bairro_norm=? "
                           "AND portal='ZAP Imóveis'", (bn,)).fetchall()
    assert len(velhos) == 2 and all(v["substituido_por"] for v in velhos)


def test_impressao_so_com_quartos_conhecido():
    assert coletor_fonte.impressao_digital("B", 80, 3e5, None) == ""
    assert coletor_fonte.impressao_digital("B", 80, 3e5, 0) != ""


def test_anuncios_recentes_filtra_cidade():
    bn = coletor_fonte.bairro_norm(_bairro())
    t0 = datetime.now(timezone.utc)
    _salvar(ZAP + bn + "-gyn", "ZAP", bn, "", t0, cidade="goiania")
    _salvar(ZAP + bn + "-apa", "ZAP", bn, "", t0, cidade="aparecida-de-goiania")
    desde = (t0 - timedelta(days=1)).isoformat()
    assert [r["cidade"] for r in db.anuncios_recentes(bn, "casa", desde, cidade="goiania")] == ["goiania"]
    assert len(db.anuncios_recentes(bn, "casa", desde)) == 2
