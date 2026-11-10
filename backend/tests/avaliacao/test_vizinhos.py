"""D4: setores vizinhos de Goiânia na 2ª rodada da pesquisa."""
import asyncio
from datetime import date

from lovable.avaliacao import db, fonte_mercado, ia
from lovable.avaliacao.agentes import pesquisa
from lovable.avaliacao.fonte_mercado import Consulta
from lovable.avaliacao.modelos import Trabalho
from lovable.avaliacao.portais import slug
from tests.avaliacao.conftest import numero_livre


def _job(bairro: str, cidade="Goiânia") -> str:
    db.init()
    return db.criar_job(Trabalho(
        id="", numero=numero_livre(130), modalidade="OV", finalidade="Venda", cliente="W", tipo="Sobrado",
        bairro=bairro, cidade=cidade, pin_maps="", data_base=date(2026, 10, 20),
        data_vistoria=date(2026, 10, 18)))


class _Fonte:
    def __init__(self):
        self.pedidas: list[list[Consulta]] = []

    async def buscar(self, job_id, consultas):
        self.pedidas.append(consultas)
        return []

    def online(self):
        return True


def _rodar(monkeypatch, bairro, cidade="Goiânia"):
    chamadas = []

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo=""):
        chamadas.append(prompt)
        return esquema(consultas=[Consulta(tipologia="Sobrado", bairro=bairro, cidade=cidade,
                                           area_min=200, area_max=500)])
    monkeypatch.setattr(ia, "perguntar", fake)
    f = _Fonte()
    fonte_mercado.registrar(f)
    asyncio.run(pesquisa.rodar(_job(bairro, cidade)))
    return chamadas, f.pedidas


def test_lista_de_vizinhos_valida():
    viz = pesquisa.vizinhos_goiania()
    assert len(viz) >= 25 and "jardim-vila-boa" in viz
    assert set(viz["jardim-vila-boa"]) == {"Parque Anhanguera", "Setor Faiçalville",
                                           "Jardim Planalto"}
    for k, vs in viz.items():
        assert k == slug(k) and vs and slug(k) not in {slug(v) for v in vs}


def test_segunda_rodada_usa_a_lista_sem_ia(monkeypatch):
    chamadas, pedidas = _rodar(monkeypatch, "Jardim Vila Boa")
    assert len(chamadas) == 1                     # só a 1ª rodada pediu à IA
    assert {c.bairro for c in pedidas[1]} == {"Parque Anhanguera", "Setor Faiçalville",
                                              "Jardim Planalto"}
    assert all(c.tipologia == "Sobrado" and c.area_min == 200 for c in pedidas[1])


def test_bairro_fora_da_lista_pede_a_ia(monkeypatch):
    chamadas, pedidas = _rodar(monkeypatch, "Bairro Inexistente")
    assert len(chamadas) == 2 and "Relaxe o bairro" in chamadas[1]


def test_outra_cidade_pede_a_ia(monkeypatch):
    chamadas, _ = _rodar(monkeypatch, "Setor Bueno", cidade="Anápolis")
    assert len(chamadas) == 2
