"""ORDEM 032-2 / D-059: objeto da avaliação = parte do imóvel -> a área sugerida é a da parte."""
from datetime import date

from lovable.avaliacao import db
from lovable.avaliacao.agentes import selecao
from lovable.avaliacao.modelos import Campo, Trabalho
from tests.avaliacao.conftest import numero_unico


def _job(parte: str) -> str:
    db.init()
    jid = db.criar_job(Trabalho(
        id="", numero=numero_unico(), modalidade="OV", finalidade="Venda", cliente="Teste",
        tipo="Galpão comercial", bairro="Polo Empresarial", cidade="Aparecida de Goiânia", pin_maps="",
        data_base=date(2026, 11, 13), data_vistoria=date(2026, 11, 13), objeto_parte=parte))
    db.salvar_campos(jid, [
        Campo(nome="Área edificada", valor=6363.65, origem="documento", fonte="documento/iptu.pdf"),
        Campo(nome="Área construída do Galpão 01 – medida por satélite", valor=1982.96, origem="inferido",
              fonte="foto/Frente.jpg (30,54 m)")])
    return jid


def _sugerida(jid: str) -> str:
    return next(o["campo"] for o in selecao.opcoes_area(jid)["construida"] if o["sugerida"])


def test_parte_do_imovel_sugere_a_area_da_parte():
    assert _sugerida(_job("Galpão 01")).startswith("Área construída do Galpão 01")


def test_imovel_inteiro_continua_como_antes():
    assert _sugerida(_job("")) == "Área edificada"
