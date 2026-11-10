import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import conexao  # noqa: E402
from websockets.asyncio.server import serve  # noqa: E402


class NavFalso:
    def __init__(self):
        self.chamadas = []

    async def capturar(self, url, acao):
        self.chamadas.append((url, acao))
        return {"ok": True, "bloqueado": False, "url_final": url, "texto": "oi", "links": []}


async def _cenario(tarefas, quedas=0):
    """Servidor falso: derruba as `quedas` primeiras conexões, depois manda as tarefas."""
    recebidos, conexoes, auths = [], [], []
    pronto = asyncio.Event()

    async def handler(ws):
        conexoes.append(ws.request.path)
        auths.append(ws.request.headers.get("Authorization"))
        ola = json.loads(await ws.recv())
        recebidos.append(ola)
        if len(conexoes) <= quedas:
            await ws.close()
            return
        for t in tarefas:
            await ws.send(json.dumps(t))
            recebidos.append(json.loads(await ws.recv()))
        pronto.set()
        await ws.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as srv:
        porta = srv.sockets[0].getsockname()[1]
        cfg = {"servidor": f"http://127.0.0.1:{porta}", "token": "tok"}
        nav, parar = NavFalso(), asyncio.Event()
        t = asyncio.create_task(conexao.loop(cfg, nav, esperas=(0.05,), parar=parar))
        await asyncio.wait_for(pronto.wait(), 10)
        parar.set()
        await asyncio.wait_for(t, 5)
    return recebidos, conexoes, nav, auths


def test_tarefa_permitida_e_proibida():
    url = "https://www.zapimoveis.com.br/imovel/x/"
    rec, cons, nav, auths = asyncio.run(_cenario([
        {"tipo": "tarefa", "id": "1", "job": "j", "acao": "anuncio", "url": url},
        {"tipo": "tarefa", "id": "2", "job": "j", "acao": "busca", "url": "https://evil.com/"},
    ]))
    assert rec[0]["tipo"] == "ola" and rec[0]["versao"]
    assert rec[1]["tipo"] == "resultado" and rec[1]["id"] == "1" and rec[1]["ok"]
    assert rec[2] == {"tipo": "resultado", "id": "2", "ok": False, "bloqueado": False,
                      "erro": "url não permitida"}
    assert nav.chamadas == [(url, "anuncio")]
    assert cons[0] == "/ws/avaliacao/coletor"   # token nunca na URL
    assert auths[0] == "Bearer tok"


def test_reconecta_apos_queda():
    rec, cons, nav, auths = asyncio.run(_cenario(
        [{"tipo": "tarefa", "id": "9", "acao": "busca", "url": "https://www.olx.com.br/imoveis"}],
        quedas=2))
    assert len(cons) == 3
    assert rec[-1]["id"] == "9" and rec[-1]["ok"]


def test_token_recusado_para_de_tentar():
    tentativas, status = [], []

    def recusar(conn, req):
        tentativas.append(req.path)
        return conn.respond(403, "proibido\n")

    async def go():
        async with serve(lambda ws: None, "127.0.0.1", 0, process_request=recusar) as srv:
            porta = srv.sockets[0].getsockname()[1]
            cfg = {"servidor": f"http://127.0.0.1:{porta}", "token": "velho"}
            await asyncio.wait_for(conexao.loop(cfg, NavFalso(), esperas=(0.01,),
                                                ao_status=status.append), 5)
    asyncio.run(go())
    assert len(tentativas) == 1 and status == [conexao.PAREAR]


def test_modulos_importam():
    import bandeja  # noqa: F401
    import joaodebarro_coletor  # noqa: F401
