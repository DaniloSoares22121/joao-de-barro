"""117-3: cada pedido do avaliador é conferido no PDF (regra quando dá; IA leve — aqui simulada — para o resto)."""
import asyncio

import pymupdf

from lovable.avaliacao import conferir_pedidos as CP, ia


def _pdf(tmp_path, paginas):
    arq = tmp_path / "l.pdf"
    with pymupdf.open() as d:
        for txt in paginas:
            pg = d.new_page()
            for k, ln in enumerate(txt.split("\n")):
                pg.insert_text((40, 60 + 14 * k), ln, fontsize=8)
        d.save(arq)
    return arq


def test_regra_ia_e_imagem(tmp_path, monkeypatch):
    pdf = _pdf(tmp_path, ["Capa – Jardim Curitiba I – Vistoria 13/11/2026",
                          "9.3 item 01: casa de construção nova, padrão superior.\n07 Carteira Nacional de Habilitação (CNH-e)"])
    vistos = []

    async def falsa(sistema, prompt, esquema, **kw):
        vistos.append(prompt)
        return esquema(pedidos=[{"i": 3, "feito": False, "onde_viu": "pág. 2", "motivo": "a linha 07 da CNH continua"}])
    monkeypatch.setattr(ia, "perguntar", falsa)
    monkeypatch.setattr(ia, "definir_contexto", lambda *a: None)
    pedidos = [{"i": 1, "onde": "item 9.3", "oque": "Trocar construção novo por construção nova."},
               {"i": 2, "onde": "", "oque": "Tirar toda menção a \"data-base\"."},
               {"i": 3, "onde": "item 6", "oque": "Tirar a CNH do solicitante do quadro."},
               {"i": 4, "onde": "localização", "oque": "Quadro exatamente em cima do lote, contorno mais fino."}]
    r = asyncio.run(CP.conferir("j", pdf, pedidos))
    por = {x["i"]: x for x in r}
    assert por[1]["feito"] and "nova" in por[1]["motivo"]                    # regra: A saiu, B está
    assert por[2]["feito"]                                                   # regra: "data-base" não aparece
    assert por[3] == {"i": 3, "feito": False, "onde_viu": "pág. 2", "motivo": "a linha 07 da CNH continua", "imagem": False}
    assert por[4]["imagem"] and not por[4]["feito"]
    assert len(vistos) == 1 and "3. Onde: item 6" in vistos[0] and "1. Onde" not in vistos[0]   # só o 3 foi à IA


def test_trocar_pela_metade_nao_e_feito(tmp_path):
    pdf = _pdf(tmp_path, ["Capa – Jardim Curitiba – Goiânia", "Item 8: Jardim Curitiba I"])
    r = CP.por_regra(CP._paginas(pdf), {"oque": "Trocar \"Jardim Curitiba,\" por \"Jardim Curitiba I\""})
    assert r["feito"] is False and r["onde_viu"] == "pág. 1"            # a capa ficou com o nome curto
    pdf2 = _pdf(tmp_path, ["Capa – Jardim Curitiba I – Goiânia", "Item 8: Jardim Curitiba I"])
    assert CP.por_regra(CP._paginas(pdf2), {"oque": "Trocar Jardim Curitiba por Jardim Curitiba I."})["feito"] is True


def test_bairro_so_no_avaliando_132(tmp_path):
    """132-5: o anúncio "Rua JC-60, Jardim Curitiba" não faz o pedido do bairro do avaliando virar ✗."""
    pdf = _pdf(tmp_path, ["Imóvel Avaliado: Casa – Rua XV 9, Qd. 59, Lt. 02, Jardim Curitiba I, Goiânia",
                          "9.3 item 02 – Localização: Rua JC-60, Jardim Curitiba, Goiânia – GO."])
    r = CP.por_regra(CP._paginas(pdf), {"oque": "Trocar o bairro \"Jardim Curitiba\" por \"Jardim Curitiba I\"."})
    assert r["feito"] is True
    pdf2 = _pdf(tmp_path, ["Imóvel Avaliado: Casa – Rua XV 9, Qd. 59, Lt. 02, Jardim Curitiba, Goiânia"])
    assert CP.por_regra(CP._paginas(pdf2), {"oque": "Trocar o bairro \"Jardim Curitiba\" por \"Jardim Curitiba I\"."})["feito"] is False
