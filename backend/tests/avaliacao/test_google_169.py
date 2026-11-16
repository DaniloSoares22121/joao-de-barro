"""ORDEM 169: ligação com o Google do avaliador — com um Google SIMULADO (nada sai para a internet)."""
import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest

from lovable.avaliacao import db, google_drive as G
from lovable.avaliacao.orquestrador import _arquivos_finais
from tests.avaliacao.test_controle import API, _novo, dono  # noqa: F401 (fixture)


class _Resp:
    def __init__(self, status=200, corpo=None, conteudo=b""):
        self.status_code, self._c, self.content = status, corpo or {}, conteudo

    def json(self):
        return self._c


class GoogleFalso:
    """Faz o papel do Google: token, pastas, upload com conversão, export e revogação."""

    def __init__(self):
        self.chamadas, self.arquivos, self.revogados, self.n = [], {}, [], 0

    def __call__(self, metodo, url, **kw):
        self.chamadas.append((metodo, url, kw))
        if url == G.TOKEN:
            d = kw["data"]
            idt = "x." + base64.urlsafe_b64encode(json.dumps({"email": "capitao@exemplo.com"}).encode()).decode().rstrip("=") + ".y"
            if d["grant_type"] == "authorization_code":
                return _Resp(200, {"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600, "id_token": idt})
            return _Resp(200, {"access_token": "AT2", "expires_in": 3600})
        if url == G.REVOGAR:
            self.revogados.append(kw["data"]["token"])
            return _Resp(200)
        assert kw.get("headers", {}).get("Authorization", "").startswith("Bearer "), "sem token no pedido ao Drive"
        if url == f"{G.DRIVE}/files" and metodo == "POST":            # pasta
            self.n += 1
            fid = f"pasta{self.n}"
            self.arquivos[fid] = kw["json"]
            return _Resp(200, {"id": fid})
        if url == G.UPLOAD and metodo == "POST":                      # upload com conversão
            self.n += 1
            fid = f"doc{self.n}"
            self.arquivos[fid] = {"corpo": kw["content"]}
            return _Resp(200, {"id": fid})
        if url.startswith(f"{G.UPLOAD}/") and metodo == "PATCH":
            self.arquivos[url.rsplit("/", 1)[1]]["corpo"] = kw["content"]
            return _Resp(200, {"id": url.rsplit("/", 1)[1]})
        if url.endswith("/export"):
            return _Resp(200, conteudo=b"%PDF-falso" if kw["params"]["mimeType"] == "application/pdf" else b"PK-docx")
        return _Resp(404)


@pytest.fixture()
def google(monkeypatch):
    f = GoogleFalso()
    monkeypatch.setattr(G, "_http", f)
    return f


def test_conectar_abrir_uma_vez_e_desligar(client, dono, google):  # noqa: F811
    h, _ = dono
    st = client.get(f"{API}/google/status", headers=h).json()
    assert st == {"configurado": False, "conectado": False, "email": ""}
    assert client.get(f"{API}/google/conectar", headers=h).status_code == 409            # sem a chave do app
    assert client.put(f"{API}/google/cliente", json={"client_id": "CID", "client_secret": "SEG"}, headers=h).status_code == 200
    url = client.get(f"{API}/google/conectar", headers=h).json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["scope"][0].startswith(G.ESCOPO) and "drive.file" in q["scope"][0] and "SEG" not in url
    r = client.get(f"{API}/google/retorno", params={"code": "COD", "state": q["state"][0]})
    assert r.status_code == 200 and "conectado" in r.text
    st = client.get(f"{API}/google/status", headers=h).json()
    assert st["conectado"] and st["email"] == "capitao@exemplo.com"
    assert "RT1" not in json.dumps(st) and "SEG" not in json.dumps(st)                    # nada de segredo na tela
    # o mesmo estado não serve duas vezes
    assert "expirou" in client.get(f"{API}/google/retorno", params={"code": "COD", "state": q["state"][0]}).text
    jid = _novo(client, h)
    _arquivos_finais(jid)["docx"].write_bytes(b"PK-laudo")
    a = client.post(f"{API}/jobs/{jid}/google/abrir", headers=h).json()
    b = client.post(f"{API}/jobs/{jid}/google/abrir", headers=h).json()
    assert a["novo"] is True and b["novo"] is False and a["file_id"] == b["file_id"]      # nunca sobe outro por cima
    assert a["url"] == f"https://docs.google.com/document/d/{a['file_id']}/edit"
    pastas = [v for v in google.arquivos.values() if v.get("mimeType") == G.MIME_PASTA]
    assert [p["name"] for p in pastas] == [G.PASTA_RAIZ, G.nome_do_trabalho(jid)]
    assert pastas[1]["parents"] == ["pasta1"]
    corpo = google.arquivos[a["file_id"]]["corpo"]
    assert G.MIME_DOCS.encode() in corpo and b"PK-laudo" in corpo                          # sobe convertendo
    assert not any("permissions" in u for _, u, _ in google.chamadas)                      # nunca compartilha
    assert G.exportar(jid, "pdf") == b"%PDF-falso" and G.exportar(jid, "html") == b"PK-docx"
    assert G.atualizar_conteudo(jid, b"PK-novo") == a["file_id"]
    assert b"PK-novo" in google.arquivos[a["file_id"]]["corpo"]
    st = client.post(f"{API}/google/desligar", headers=h).json()
    assert st["conectado"] is False and google.revogados == ["RT1"]
    assert client.post(f"{API}/jobs/{jid}/google/abrir", headers=h).status_code == 409    # sem Google: pede para conectar


def test_so_o_dono_cadastra_a_chave(client, google):
    from tests.conftest import make_user
    (G._pasta() / "cliente.json").unlink(missing_ok=True)
    h = {"Authorization": f"Bearer {make_user('outro169@test.local')[1]}"}
    r = client.put(f"{API}/google/cliente", json={"client_id": "X", "client_secret": "Y"}, headers=h)
    assert r.status_code in (403, 401)
    assert not G.configurado()
