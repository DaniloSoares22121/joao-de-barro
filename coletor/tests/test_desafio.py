"""ORDEM 018: verificação do portal ("Confirme que é humano") — o Coletor traz a janela à frente
e espera a PESSOA resolver; não clica, não contorna. Sem liberar, devolve o print do que viu."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import navegador as nv  # noqa: E402

DESAFIO = ("Just a moment...", "Verifique se você é humano. Isso pode levar alguns segundos.")
NORMAL = ("Galpões à venda | ZAP", "206 Galpões, Depósitos e Armazéns para venda")
DEFINITIVO = ("Attention Required!", "Sorry, you have been blocked. You are unable to access")


class Pagina:
    """Página falsa: `telas` é a sequência do que aparece a cada consulta."""

    def __init__(self, telas, url="https://www.zapimoveis.com.br/venda/x/"):
        self.telas, self.i, self.url = list(telas), 0, url
        self.na_frente = False
        self.cliques = 0

    def _tela(self):
        return self.telas[min(self.i, len(self.telas) - 1)]

    async def title(self):
        return self._tela()[0]

    async def evaluate(self, js):
        if "innerText" in js:
            t = self._tela()[1]
            self.i += 1
            return t
        return False   # nenhum iframe de desafio visível

    async def bring_to_front(self):
        self.na_frente = True

    def is_closed(self):
        return False

    async def screenshot(self, **_k):
        return b"\xff\xd8\xff" + b"x" * 20

    async def click(self, *_a, **_k):   # o Coletor NUNCA clica na verificação
        self.cliques += 1


async def _nada(_s):
    return None


def test_pessoa_resolve_e_segue():
    pg = Pagina([DESAFIO, DESAFIO, DESAFIO, NORMAL])
    status = {"s": 403}

    async def go():
        # a página recarrega depois da verificação: o documento novo chega com 200
        assert await nv.bloqueado(pg, status["s"]) is True
        status["s"] = 200
        return await nv.esperar_liberacao(pg, status, limite=60, passo=0, dormir=_nada)
    assert asyncio.run(go()) is True
    assert pg.na_frente and pg.cliques == 0


def test_ninguem_resolve_devolve_falso_no_prazo():
    pg = Pagina([DESAFIO])
    relogio = iter(range(0, 1000, 10))
    ok = asyncio.run(nv.esperar_liberacao(pg, {"s": 403}, limite=60, passo=0, dormir=_nada,
                                          agora=lambda: next(relogio)))
    assert ok is False and pg.na_frente and pg.cliques == 0


def test_bloqueio_definitivo_nao_espera():
    pg = Pagina([DEFINITIVO])
    esperas = []

    async def dormir(s):
        esperas.append(s)
    assert asyncio.run(nv.esperar_liberacao(pg, {"s": 403}, limite=60, passo=2, dormir=dormir)) is False
    assert esperas == []


def test_sem_espera_configurada():
    assert asyncio.run(nv.esperar_liberacao(Pagina([DESAFIO]), {"s": 403}, limite=0)) is False


def test_resposta_de_bloqueio_tem_print_e_titulo():
    r = asyncio.run(nv.resposta_bloqueio(Pagina([DESAFIO]), {"s": 403}))
    assert r["ok"] is False and r["bloqueado"] is True and r["status"] == 403
    assert r["erro"] == "bloqueado: Just a moment..."
    assert r["print_b64"].startswith("/9j/")
    assert r["url_final"].startswith("https://www.zapimoveis.com.br/")
