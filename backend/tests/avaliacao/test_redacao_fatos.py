"""B1 (fatos do exemplo copiados) e B2 (quesitos AMJ sem termos de engenharia)."""
import json

from lovable.avaliacao import conhecimento
from lovable.avaliacao.agentes import redacao

from .textos_ok import SECOES_OV as SECOES


def test_json_dos_exemplos_sem_caractere_de_controle():
    bruto = (conhecimento.PASTA / "exemplos_secoes.json").read_text(encoding="utf-8")
    assert chr(0xF0B7) not in bruto  # marcador de lista da extração do PDF
    assert not [c for c in bruto if ord(c) < 32 and c not in "\n\r\t"]
    assert "\n\n" in json.loads(bruto)["OV"]["descricao"]


def test_fato_do_exemplo_copiado_vira_deficiencia():
    fontes = json.dumps({"bairro": "Setor Bueno", "cidade": "Goiânia",
                         "campos": [{"nome": "esquadrias", "valor": "alumínio"}]})
    secoes = dict(SECOES, **{"7.4": SECOES["7.4"] + "\nEsquadrias: janelas de metalon."})
    f = redacao.deficiencias("OV", secoes, fontes=fontes)
    assert any(x.startswith("7.4 (descricao)") and redacao.FATO_COPIADO in x
               and '"metalon"' in x for x in f)


def test_fato_presente_nos_dados_do_imovel_nao_e_copia():
    txt = "Esquadrias: janelas de metalon; garagem sobre pilares com 4 vagas."
    assert redacao.fatos_copiados(txt, "esquadrias de metalon; garagem sobre pilares, 4 vagas") == []
    assert set(redacao.fatos_copiados(txt, "esquadrias de alumínio")) == {
        "metalon", "sobre pilares", "4 vagas"}


def test_ngrama_raro_do_exemplo_detectado():
    # "altura de 3,40" vem do muro do P8; outro imóvel não tem esse dado
    assert any("3,40" in a for a in redacao.fatos_copiados(
        "Fechamento: muro em alvenaria com altura de 3,40 m.", "muro de 2 m"))
    assert redacao.fatos_copiados("Fechamento: muro com altura de 3,40 m.", "muro 3,40 m") == []


def test_sem_fontes_nao_checa_copia():
    assert redacao.deficiencias("OV", SECOES) == []


def test_guia_avisa_que_fatos_do_exemplo_nao_sao_do_imovel():
    assert "NÃO pertencem a este imóvel" in redacao.guia_secoes("OV")


def test_quesito_com_termo_de_engenharia_vira_deficiencia():
    secoes = {"12": "Quesito 1: Há vícios construtivos?\n\nResposta: Seria necessário ensaio "
                    "e laudo de engenharia para avaliar fissura estrutural."}
    f = [x for x in redacao.deficiencias("AMJ", secoes, ["Há vícios construtivos?"])
         if x.startswith("12 (quesitos)")]
    assert f and "D-012" in f[0] and "ensaio" in f[0] and redacao.PREJUDICADO in f[0]
    secoes["12"] = ("Quesito 1: Há vícios construtivos?\n\nResposta: "
                    + redacao.PREJUDICADO + ".")
    assert not [x for x in redacao.deficiencias("AMJ", secoes, ["x"]) if x.startswith("12 ")]


def test_instrucao_pede_prejudicado():
    assert redacao.PREJUDICADO in redacao.INSTRUCAO
