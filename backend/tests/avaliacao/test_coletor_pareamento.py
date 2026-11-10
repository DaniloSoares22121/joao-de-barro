import pytest

from lovable import config
from lovable.avaliacao import coletor_hub, db
from tests.conftest import make_user

DONO = "alan@test.local"
B = "/api/avaliacao/coletor"


def _h(email):
    return {"Authorization": f"Bearer {make_user(email)[1]}"}


@pytest.fixture()
def h(client):
    db.init()
    db.set_setting("dono_email", DONO)
    coletor_hub.hub.codigos.clear()
    coletor_hub.hub.visto_em = coletor_hub.hub.versao = None
    return _h(DONO)


def test_exigem_dono(client, h):
    o = _h("outro@test.local")
    assert client.post(f"{B}/codigo", headers=o).status_code == 403
    assert client.get(f"{B}/status", headers=o).status_code == 403
    assert client.get(f"{B}/download", headers=o).status_code == 403


def test_parear_uso_unico_e_token(client, h):
    r = client.post(f"{B}/codigo", headers=h).json()
    cod = r["codigo"]
    assert len(cod) == 8 and r["expira_em"]
    assert set(cod) <= set(coletor_hub.ALFABETO)
    t1 = client.post(f"{B}/parear", json={"codigo": cod}).json()["token"]
    assert coletor_hub.validar_token(t1)
    assert not coletor_hub.validar_token("x")
    assert client.post(f"{B}/parear", json={"codigo": cod}).status_code == 401
    assert db.setting("coletor_token_sha256") != t1
    cod2 = client.post(f"{B}/codigo", headers=h).json()["codigo"]
    t2 = client.post(f"{B}/parear", json={"codigo": cod2.lower()}).json()["token"]
    assert coletor_hub.validar_token(t2) and not coletor_hub.validar_token(t1)


def test_codigo_expira(client, h, monkeypatch):
    agora = [1000.0]
    monkeypatch.setattr(coletor_hub.hub, "relogio", lambda: agora[0])
    cod = client.post(f"{B}/codigo", headers=h).json()["codigo"]
    agora[0] += 601
    assert client.post(f"{B}/parear", json={"codigo": cod}).status_code == 401


def test_status_e_download(client, h):
    s = client.get(f"{B}/status", headers=h).json()
    assert s == {"online": False, "visto_em": None, "versao": None}
    exe = config.DATA_DIR / "avaliacao" / "coletor" / "joaodebarro-coletor.exe"
    exe.unlink(missing_ok=True)
    assert client.get(f"{B}/download", headers=h).status_code == 404
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ")
    r = client.get(f"{B}/download", headers=h)
    assert r.status_code == 200 and r.content == b"MZ"
