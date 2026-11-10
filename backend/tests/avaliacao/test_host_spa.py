import pytest

from lovable import main

HOST = "joaodebarro.brixly.com.br"
HTML = "<!doctype html><title>JDB-FAKE</title>"


@pytest.fixture()
def dist(tmp_path, monkeypatch):
    tmp_path = tmp_path / "dist"
    tmp_path.mkdir()
    (tmp_path.parent / "segredo.txt").write_text("SEGREDO-FORA", encoding="utf-8")
    (tmp_path / "index.html").write_text(HTML, encoding="utf-8")
    (tmp_path / "app-x.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(main, "_joaodebarro_dist", tmp_path)
    monkeypatch.setattr(main, "_JOAODEBARRO_HOST", HOST)
    return tmp_path


def test_raiz_e_rotas_devolvem_spa(client, dist):
    for p in ("/", "/qualquer/rota"):
        r = client.get(p, headers={"Host": HOST})
        assert r.status_code == 200
        assert "JDB-FAKE" in r.text


def test_api_nao_vira_html(client, dist):
    r = client.get("/api/auth/me", headers={"Host": HOST})
    assert r.status_code == 401
    assert "JDB-FAKE" not in r.text


def test_assets_servidos(client, dist):
    r = client.get("/assets-jdb/app-x.js", headers={"Host": HOST})
    assert r.status_code == 200
    assert "console.log" in r.text
    assert client.get("/assets-jdb/nao-existe.js", headers={"Host": HOST}).status_code == 404


def test_traversal_nao_serve_arquivo_fora_do_dist(client, dist):
    assert (dist.parent / "segredo.txt").is_file()
    for p in ("/assets-jdb/%2e%2e/segredo.txt", "/assets-jdb/..%2fsegredo.txt",
              "/assets-jdb/%2e%2e%2fsegredo.txt", "/assets-jdb/../segredo.txt"):
        r = client.get(p, headers={"Host": HOST})
        assert "SEGREDO-FORA" not in r.text, p
    assert client.get("/assets-jdb/%2e%2e/segredo.txt", headers={"Host": HOST}).status_code == 404


def test_assets_jdb_em_outro_host_cai_adiante(client, dist):
    r = client.get("/assets-jdb/app-x.js", headers={"Host": "app.brixly.com.br"})
    assert "console.log" not in r.text
    assert "JDB-FAKE" not in r.text


def test_cabecalhos_de_seguranca(client, dist):
    for p in ("/", "/assets-jdb/app-x.js", "/assets-jdb/nao-existe.js"):
        h = client.get(p, headers={"Host": HOST}).headers
        assert h["x-frame-options"] == "DENY", p
        assert h["content-security-policy"] == "frame-ancestors 'none'"
        assert h["x-content-type-options"] == "nosniff"
        assert h["strict-transport-security"] == "max-age=31536000"
    assert client.get("/assets-jdb/nao-existe.js", headers={"Host": HOST}).status_code == 404


def test_outro_host_comportamento_antigo(client, dist):
    r = client.get("/qualquer/rota", headers={"Host": "app.brixly.com.br"})
    assert "JDB-FAKE" not in r.text
