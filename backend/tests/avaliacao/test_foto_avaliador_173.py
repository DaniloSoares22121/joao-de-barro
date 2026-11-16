"""ORDEM 173: a foto (ou print) enviada pelo avaliador vira a da tabela de amostras, marcada para a rastreabilidade."""
import io

from PIL import Image

from lovable.avaliacao import db
from lovable.avaliacao.modelos import Referencial
from tests.avaliacao.test_controle import API, _novo, dono  # noqa: F401 (fixture)


def _png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (400, 300), (120, 160, 200)).save(b, "PNG")
    return b.getvalue()


def test_foto_enviada_vira_a_da_tabela(client, dono):  # noqa: F811
    h, _ = dono
    jid = _novo(client, h)
    db.salvar_candidatos(jid, [Referencial(n=1, link="https://x/1", portal="ZAP", bairro="B", tipologia="Casa",
                                           padrao="", idade_aparente="", descricao="", area_m2=100, preco=200000,
                                           foto_arte=True, fotos_url=["https://x/a.jpg"])])
    r = client.post(f"{API}/jobs/{jid}/candidatos/1/foto-enviada", headers=h,
                    files={"foto": ("print-202611152200.png", _png(), "image/png")})
    assert r.status_code == 200, r.text
    c = next(x for x in db.candidatos(jid) if x.n == 1)
    assert c.foto_avaliador is True and c.foto_arte is False and c.foto.startswith("mercado/avaliador-1-foto-")
    assert (db.pasta(jid) / c.foto).is_file()
    assert client.post(f"{API}/jobs/{jid}/candidatos/1/foto-enviada", headers=h,
                       files={"foto": ("x.txt", b"nada", "text/plain")}).status_code == 415
    assert client.post(f"{API}/jobs/{jid}/candidatos/9/foto-enviada", headers=h,
                       files={"foto": ("a.png", _png(), "image/png")}).status_code == 404
