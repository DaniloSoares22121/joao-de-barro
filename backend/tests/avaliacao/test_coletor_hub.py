import asyncio
import base64
import threading
import uuid

import pytest
from starlette.websockets import WebSocketDisconnect

from lovable.avaliacao import coletor_hub, db
from lovable.avaliacao.modelos import Trabalho

TRAB = {"id": "colhub", "numero": 121, "modalidade": "OV", "finalidade": "Venda", "cliente": "Fulano",
        "tipo": "Casa", "bairro": "Centro", "cidade": "Goiânia",
        "pin_maps": "https://maps.app.goo.gl/x", "data_base": "2026-10-16",
        "data_vistoria": "2026-10-16"}


@pytest.fixture()
def tok(client):
    db.init()
    coletor_hub.hub.codigos.clear()
    cod, _ = coletor_hub.hub.novo_codigo()
    return coletor_hub.hub.parear(cod), db.criar_job(Trabalho(**{**TRAB, "id": uuid.uuid4().hex[:12]}))


def _em_thread(coro):
    out = {}

    def run():
        try:
            out["r"] = asyncio.run(coro)
        except BaseException as e:  # noqa: BLE001
            out["e"] = e
    t = threading.Thread(target=run)
    t.start()
    return t, out


W = "/ws/avaliacao/coletor"


def test_token_na_query_recusado(client, tok):
    token, _ = tok
    for kw in ({}, {"headers": {"Authorization": token}}):
        with pytest.raises(WebSocketDisconnect) as e:
            with client.websocket_connect(f"{W}?token={token}", **kw) as ws:
                ws.receive_json()
        assert e.value.code == 4403


def test_token_invalido_4403(client, tok):
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/ws/avaliacao/coletor",
                                      headers={"Authorization": "Bearer errado"}) as ws:
            ws.receive_json()
    assert e.value.code == 4403


def test_tarefa_resultado_e_print(client, tok):
    token, jid = tok
    assert not coletor_hub.online()
    with client.websocket_connect(W, headers={"Authorization": f"Bearer {token}"}) as ws:
        ws.send_json({"tipo": "ola", "versao": "1.0"})
        t, out = _em_thread(coletor_hub.executar(jid, "busca", "https://www.zapimoveis.com.br/x", timeout=10))
        m = ws.receive_json()
        assert m["tipo"] == "tarefa" and m["job"] == jid and m["acao"] == "busca"
        assert coletor_hub.online() and coletor_hub.hub.versao == "1.0"
        ws.send_json({"tipo": "resultado", "id": m["id"], "ok": True, "bloqueado": False,
                      "url_final": "https://u", "texto": "abc", "links": ["l"],
                      "print_b64": base64.b64encode(b"\xff\xd8\xffJPG").decode(), "fotos": [], "erro": None})
        t.join(10)
    cap = out["r"]
    assert cap.ok and cap.texto == "abc" and cap.links == ["l"]
    assert (db.pasta(jid) / cap.print_path).read_bytes() == b"\xff\xd8\xffJPG"
    assert any(a["tipo"] == "mercado" and a["caminho"] == cap.print_path for a in db.arquivos(jid))
    assert coletor_hub.hub.visto_em


def test_desconexao_coletor_offline(client, tok):
    token, jid = tok
    with client.websocket_connect(W, headers={"Authorization": f"Bearer {token}"}) as ws:
        t, out = _em_thread(coletor_hub.executar(jid, "anuncio", "https://www.olx.com.br/a", timeout=10))
        ws.receive_json()
    t.join(10)
    assert isinstance(out.get("e"), coletor_hub.ColetorOffline)
    assert not coletor_hub.online()


def test_sem_coletor_offline(client, tok):
    with pytest.raises(coletor_hub.ColetorOffline):
        asyncio.run(coletor_hub.executar(tok[1], "maps", "https://maps.app.goo.gl/x"))


# ---------------------------------------------------------------- endurecimento
class _WsFake:
    def __init__(self, hub, resposta=None):
        self.hub, self.resposta = hub, resposta

    async def send_json(self, m):
        if self.resposta is not None:
            asyncio.get_running_loop().call_soon(self.hub.receber, self, {**self.resposta, "id": m["id"]})


def _rodar(resposta, jid="x", timeout=5):
    async def main():
        h = coletor_hub.Hub()
        ws = _WsFake(h, resposta)
        await h.conectar(ws)
        task = asyncio.ensure_future(h.executar(jid, "busca", "https://www.zapimoveis.com.br/", timeout))
        try:
            return await task, h
        except BaseException as e:  # noqa: BLE001
            return e, h
    return asyncio.run(main())


def test_print_invalido_recusado(client, tok):
    _, jid = tok
    for b64 in ("@@nao-b64@@", base64.b64encode(b"GIF89a....").decode(),
                base64.b64encode(b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024)).decode(), 123):
        cap, h = _rodar({"tipo": "resultado", "ok": True, "print_b64": b64}, jid)
        assert cap.ok and cap.print_path is None and not h.pendentes


def test_png_aceito_texto_cortado_erro_str(client, tok):
    _, jid = tok
    cap, _ = _rodar({"tipo": "resultado", "ok": False, "texto": "a" * 70000, "erro": {"x": 1},
                     "print_b64": base64.b64encode(b"\x89PNG\r\n\x1a\nzz").decode()}, jid)
    assert len(cap.texto) == 60000 and cap.erro == "{'x': 1}"
    assert cap.print_path.endswith(".png")


def test_timeout_e_cancelamento_limpam_pendentes():
    cap, h = _rodar(None, timeout=0.05)
    assert cap.erro == "timeout" and not h.pendentes

    async def main():
        h = coletor_hub.Hub()
        await h.conectar(_WsFake(h, None))
        t = asyncio.ensure_future(h.executar("x", "busca", "https://u", 30))
        await asyncio.sleep(0.01)
        assert h.pendentes
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        return h
    assert not asyncio.run(main()).pendentes


def test_foto_b64_salva_e_validada(client, tok):
    _, jid = tok
    png = b"\x89PNG\r\n\x1a\nfoto"
    cap, _ = _rodar({"tipo": "resultado", "ok": True, "fotos": ["https://x/1.png"],
                     "fotos_b64": [base64.b64encode(png).decode()]}, jid)
    assert cap.foto_path.endswith("-foto.png") and (db.pasta(jid) / cap.foto_path).read_bytes() == png
    cap, _ = _rodar({"tipo": "resultado", "ok": True, "fotos_b64": ["@@"]}, jid)
    assert cap.foto_path is None
