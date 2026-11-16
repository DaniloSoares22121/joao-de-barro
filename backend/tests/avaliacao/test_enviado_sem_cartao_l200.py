"""L200 (Caso M): anúncio enviado pela extensão cujo texto não vira cartão (Imovelweb) dava erro 500 (campo
obrigatório "padrão" de fora). Agora entra, com os dados que a página tem."""
import asyncio
from datetime import date

from lovable.avaliacao import db, routes
from lovable.avaliacao.agentes import leitor_anuncio
from lovable.avaliacao.modelos import Campo, Trabalho
from tests.avaliacao.conftest import numero_unico


def test_anuncio_sem_cartao_entra_sem_erro(monkeypatch):
    async def sem_ia(*a, **k):
        raise RuntimeError("IA fora no teste")
    monkeypatch.setattr(leitor_anuncio, "ler", sem_ia)
    db.init()
    jid = db.criar_job(Trabalho(id="", numero=numero_unico(), modalidade="AM", finalidade="Venda", cliente="Teste",
                                tipo="Apartamento", bairro="Setor Exemplo", cidade="Aparecida de Goiânia", pin_maps="",
                                data_base=date(2026, 6, 29), data_vistoria=date(2026, 6, 29)))
    db.salvar_campos(jid, [Campo(nome="area_privativa", valor=60.0, origem="documento", fonte="iptu.pdf")])
    body = routes.AnuncioEnviado(link="https://www.imovelweb.com.br/propriedades/apto-exemplo-999.html",
                                 titulo="", texto="Apartamento", preco=360000.0, area_m2=57.0)
    r = asyncio.run(routes.anuncio_enviado(jid, body, _u={}))
    assert r["preco"] == 360000.0           # sem erro 500; a área sem confirmação no anúncio fica para o avaliador (082-3)
