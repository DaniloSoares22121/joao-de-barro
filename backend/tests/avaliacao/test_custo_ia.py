"""ORDEM 008 — cortes de custo de IA (sem IA: as chamadas são simuladas)."""
import asyncio
from datetime import date
from pathlib import Path

from PIL import Image

from lovable.avaliacao import db, ia, imagens_ia
from lovable.avaliacao.agentes import extracao, triagem
from lovable.avaliacao.modelos import Trabalho
from tests.avaliacao.conftest import numero_unico


def _job(n_fotos=5) -> str:
    db.init()
    jid = db.criar_job(Trabalho(
        id="", numero=numero_unico(), modalidade="OV", finalidade="Venda", cliente="Teste",
        tipo="Sobrado", bairro="Jardim Vila Boa", cidade="Goiânia",
        pin_maps="https://maps.app.goo.gl/x", data_base=date(2026, 11, 11),
        data_vistoria=date(2026, 11, 11)))
    p = db.pasta(jid)
    (p / "documento").mkdir(parents=True, exist_ok=True)
    (p / "foto").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 1100), "white").save(p / "documento/iptu.jpg")
    db.adicionar_arquivo(jid, "iptu.jpg", "documento", "documento/iptu.jpg")
    for i in range(n_fotos):
        Image.new("RGB", (1600, 1200), "green").save(p / f"foto/f{i}.jpg")
        db.adicionar_arquivo(jid, f"f{i}.jpg", "foto", f"foto/f{i}.jpg",
                             papel="fachada" if i == 0 else "")
    return jid


def test_triagem_nao_abre_as_fotos(monkeypatch):
    """Corte seguro: a triagem abre documentos + a foto da capa; as fotos só são contadas."""
    jid = _job(5)
    vistos = {}

    async def perguntar(sistema, prompt, esquema, arquivos=[], cwd=None, modelo="", **_kw):
        vistos["arquivos"] = sorted(str(a).replace("\\", "/") for a in arquivos)
        vistos["prompt"] = prompt
        return esquema(quadro={}, bloqueado=False)
    monkeypatch.setattr(ia, "perguntar", perguntar)
    asyncio.run(triagem.rodar(jid))
    assert vistos["arquivos"] == ["documento/iptu.jpg", "foto/f0.jpg"]
    assert "5 foto" in vistos["prompt"] and "foto/f4.jpg" in vistos["prompt"]


def test_miniaturas_desfazem_nomes_e_coordenadas(monkeypatch):
    """Foto vai como cópia de LADO_FOTO_IA px (ORDEM 013: em _ia/<lado>/) e a resposta volta
    com o nome original e as caixas na escala da foto original; documento vai em 1568 px."""
    monkeypatch.setattr(extracao, "LADO_FOTO_IA", 800)
    jid = _job(2)
    pasta = db.pasta(jid)
    rels = [a["caminho"] for a in db.arquivos(jid)]
    itens, ign = imagens_ia.preparar(pasta, rels, lado_por_arquivo=extracao._lados(jid))
    assert ign == []
    por_orig = {it.original: it for it in itens}
    assert por_orig["foto/f0.jpg"].ia == "_ia/800/foto/f0.jpg.jpg"
    assert Image.open(pasta / por_orig["foto/f0.jpg"].ia).size == (800, 600)
    assert por_orig["documento/iptu.jpg"].escala == 1.0        # 800×1100 < 1568: não reduz
    # a IA cita a cópia; ia.perguntar devolve o nome original (ia._nomes_originais)
    txt = ia._nomes_originais('{"fotos": [{"arquivo": "_ia/800/foto/f0.jpg.jpg", "ordem": 1, '
                              '"legenda": "Fachada"}], "fachada_caixa": [100, 50, 400, 300], '
                              '"tarjas": {"_ia/800/foto/f1.jpg.jpg": [[10, 10, 20, 20]], '
                              '"documento/iptu.jpg": [[1, 2, 3, 4]]}}', itens)
    bruto = extracao._RespostaIA.model_validate_json(txt)
    d = extracao._converter(bruto, itens)
    assert d.fotos[0].arquivo == "foto/f0.jpg"
    assert d.fachada_caixa == [200, 100, 800, 600]
    assert d.tarjas["foto/f1.jpg"] == [[20, 20, 40, 40]]
    assert d.tarjas["documento/iptu.jpg"] == [[1, 2, 3, 4]]   # documento na escala original


def test_miniaturas_desligadas_com_zero(monkeypatch):
    # ORDEM 010: ligado por padrão (1024); JDB_LADO_FOTO_IA=0 = fotos também em 1568 px
    monkeypatch.setattr(extracao, "LADO_FOTO_IA", 0)
    jid = _job(1)
    assert extracao.LADO_FOTO_IA == 0
    assert extracao._lados(jid) == {}
