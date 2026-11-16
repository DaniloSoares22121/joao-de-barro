"""ORDEM 032-3: data das fotos (EXIF ou nome do arquivo) × data da vistoria."""
from datetime import date

from PIL import Image

from lovable.avaliacao import datas_fotos, db
from lovable.avaliacao.modelos import Trabalho
from tests.avaliacao.conftest import numero_unico


def _job(vistoria: date) -> str:
    db.init()
    return db.criar_job(Trabalho(
        id="", numero=numero_unico(), modalidade="OV", finalidade="Venda", cliente="Teste", tipo="Casa",
        bairro="Centro", cidade="Goiânia", pin_maps="", data_base=vistoria, data_vistoria=vistoria))


def _foto(jid: str, nome: str, exif: str | None = None) -> None:
    p = db.pasta(jid) / "foto" / nome
    p.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (20, 20), "gray")
    ex = Image.Exif()
    if exif:
        ex.get_ifd(0x8769)[0x9003] = exif
    im.save(p, exif=ex)
    db.adicionar_arquivo(jid, nome, "foto", f"foto/{nome}", upload_id=f"t-{nome}")


def test_fotos_de_outra_data_geram_alerta():
    jid = _job(date(2026, 11, 12))
    _foto(jid, "a.jpg", "2026:05:29 09:41:00")
    _foto(jid, "b.jpg", "2026:05:29 10:02:00")
    _foto(jid, "IMG_20260529_100000.jpg")          # sem EXIF: data do nome
    assert datas_fotos.data_das_fotos(jid) == date(2026, 5, 29)
    assert datas_fotos.alerta(jid, "2026-11-12") == (
        "As fotos são de 29/05/2026 e a vistoria está como 12/11/2026. Confirme a data da vistoria.")


def test_mesma_data_ou_sem_data_sem_alerta():
    jid = _job(date(2026, 10, 16))
    _foto(jid, "IMG_20261016_122417.jpg")
    assert datas_fotos.alerta(jid, "2026-10-16") == ""
    jid2 = _job(date(2026, 10, 16))
    _foto(jid2, "sem_data.jpg")
    assert datas_fotos.alerta(jid2, "2026-10-16") == ""


def test_data_confirmada_pelo_avaliador():
    jid = _job(date(2026, 11, 12))
    _foto(jid, "IMG_20260529_100000.jpg")
    assert not datas_fotos.confirmada(jid, "2026-11-12")
    db.set_setting(datas_fotos.chave_confirmada(jid), "2026-11-12")
    assert datas_fotos.confirmada(jid, "2026-11-12")
    assert not datas_fotos.confirmada(jid, "2026-11-13")     # mudou a data: pergunta de novo
