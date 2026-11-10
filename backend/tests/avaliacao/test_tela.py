"""O servidor entrega a tela em qualquer caminho que não seja /api ou /ws."""
import pytest

from lovable import main

HTML = "<!doctype html><title>JDB-FAKE</title>"


@pytest.fixture()
def dist(tmp_path, monkeypatch):
    d = tmp_path / "dist"
    d.mkdir()
    (tmp_path / "segredo.txt").write_text("SEGREDO-FORA", encoding="utf-8")
    (d / "index.html").write_text(HTML, encoding="utf-8")
    (d / "app-x.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(main, "_joaodebarro_dist", d)
    return d


def test_raiz_e_rotas_devolvem_a_tela(client, dist):
    for p in ("/", "/qualquer/rota"):
        r = client.get(p)
        assert r.status_code == 200 and "JDB-FAKE" in r.text
        assert r.headers["x-frame-options"] == "DENY"


def test_api_nao_vira_html(client, dist):
    r = client.get("/api/avaliacao/jobs")
    assert r.status_code == 401 and "JDB-FAKE" not in r.text


def test_assets_e_traversal(client, dist):
    assert "console.log" in client.get("/assets-jdb/app-x.js").text
    assert client.get("/assets-jdb/nao-existe.js").status_code == 404
    for p in ("/assets-jdb/%2e%2e/segredo.txt", "/assets-jdb/..%2fsegredo.txt", "/assets-jdb/../segredo.txt"):
        assert "SEGREDO-FORA" not in client.get(p).text, p
