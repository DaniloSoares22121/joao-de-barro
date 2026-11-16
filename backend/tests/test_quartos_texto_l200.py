"""L200 (Caso W): quartos/suítes da planilha divergiam do texto do anúncio aberto (2/2 vs "4 Quartos, sendo 2
Suítes"; 3 quartos e 4 suítes, impossível)."""
from lovable.avaliacao import leitura_pagina as LP


def test_le_quartos_e_suites_do_texto():
    assert LP.quartos_suites("SOBRADO NO SETOR X. - 4 Quartos, sendo 2 Suítes. (OBS)") == (4, 2)
    assert LP.quartos_suites("Sobrado com 3 Quartos à venda, 295m²") == (3, None)
    assert LP.quartos_suites("casa com três dormitórios, sendo uma suíte") == (3, 1)


def test_texto_que_se_contradiz_nao_vale():
    assert LP.quartos_suites("3 quartos ... ótimos 5 quartos") == (None, None)
    assert LP.quartos_suites("") == (None, None)


def test_combinacao_impossivel():
    assert LP.combinacao_impossivel(3, 4) is True
    assert LP.combinacao_impossivel(4, 2) is False
    assert LP.combinacao_impossivel(None, 2) is False


# ------------------------------------------------------------- envio do anúncio aberto (extensão)
import asyncio
from datetime import date


def _job_com_ref(quartos, suites):
    from lovable.avaliacao import db
    from lovable.avaliacao.modelos import Trabalho
    from tests.avaliacao.conftest import numero_unico
    from lovable.avaliacao import routes
    db.init()
    jid = db.criar_job(Trabalho(id="", numero=numero_unico(), modalidade="OV", finalidade="Venda", cliente="Teste",
                                tipo="Sobrado", bairro="Setor Exemplo", cidade="Goiânia", pin_maps="",
                                data_base=date(2026, 6, 29), data_vistoria=date(2026, 6, 29)))
    link = "https://www.olx.com.br/imoveis/sobrado-exemplo-1234567890"
    body = routes.AnuncioEnviado(link=link, titulo="Sobrado 286 m²", texto="Sobrado", preco=1100000.0, area_m2=286.0)
    asyncio.run(routes.anuncio_enviado(jid, body, _u={}))
    ref = next(x for x in db.candidatos(jid) if x.link.startswith(link[:40]))
    routes._salvar_ref(jid, ref.model_copy(update={"quartos": quartos, "suites": suites, "divergencia_pagina": {}}), "teste")
    return jid, link


def _enviar(jid, link, texto):
    from lovable.avaliacao import db, routes
    body = routes.AnuncioEnviado(link=link, titulo="SOBRADO NO SETOR EXEMPLO", texto=texto, preco=1100000.0, area_m2=286.0)
    asyncio.run(routes.anuncio_enviado(jid, body, _u={}))
    return next(x for x in db.candidatos(jid) if x.link.startswith(link[:40]))


TEXTO = ("SOBRADO NO SETOR EXEMPLO. - 4 Quartos, sendo 2 Suítes. Área construída de 286 m². Ótima localização, "
         "próximo a escolas e comércio.")


def _sem_ia(monkeypatch):
    from lovable.avaliacao.agentes import leitor_anuncio
    async def sem_ia(*a, **k):
        raise RuntimeError("IA fora no teste")
    monkeypatch.setattr(leitor_anuncio, "ler", sem_ia)


def test_quartos_diferentes_viram_pergunta(monkeypatch):
    _sem_ia(monkeypatch)
    jid, link = _job_com_ref(2, 2)
    r = _enviar(jid, link, TEXTO)
    assert r.quartos == 2 and r.divergencia_pagina.get("quartos") == 4      # guardado vale; pergunta ao avaliador


def test_combinacao_impossivel_e_trocada(monkeypatch):
    _sem_ia(monkeypatch)
    jid, link = _job_com_ref(3, 4)
    r = _enviar(jid, link, TEXTO)
    assert (r.quartos, r.suites) == (4, 2) and "quartos" not in r.divergencia_pagina


def test_indicio_velho_de_suites_sai(monkeypatch):
    from lovable.avaliacao import db, routes
    _sem_ia(monkeypatch)
    jid, link = _job_com_ref(3, 4)
    ref = next(x for x in db.candidatos(jid) if x.link.startswith(link[:40]))
    routes._salvar_ref(jid, ref.model_copy(update={"observacao": "nota; indícios de padrão superior/mais novo: todos os quartos são suítes"}), "t")
    r = _enviar(jid, link, TEXTO)
    assert "todos os quartos são suítes" not in (r.observacao or "") and "nota" in r.observacao
