"""D-056 (Alan, 12/11/2026): a lista de candidatos vem SEMPRE do mais parecido para o menos
parecido, e cada um traz por que foi indicado (bairro, tipologia, área, região)."""
from datetime import date

from lovable.avaliacao import candidatos as C
from lovable.avaliacao import db
from lovable.avaliacao.agentes import pesquisa
from lovable.avaliacao.modelos import Campo, Referencial, Trabalho
from tests.avaliacao.conftest import numero_livre

AV = C.Avaliando(tipo="Galpão", bairro="Polo Empresarial Goiás", cidade="Aparecida de Goiânia",
                 area=1983.0)


def _r(n, bairro, area, preco, titulo="Galpão/Depósito/Armazém"):
    return Referencial(n=n, link=f"https://www.zapimoveis.com.br/imovel/x-id-{n}/", portal="ZAP Imóveis",
                       bairro=bairro, tipologia="comercial", area_m2=area, preco=preco, padrao="",
                       idade_aparente="", descricao="", titulo=titulo)


def test_motivo_diz_por_que_com_numeros():
    r = C.avaliar(_r(1, "Polo Empresarial Goiás", 2170, 6_000_000), AV)
    assert "mesmo bairro (Polo Empresarial Goiás)" in r.motivo
    assert "mesma tipologia" in r.motivo
    assert "área parecida (2.170 m², +9% do avaliando)" in r.motivo


def test_galpao_em_regiao_industrial_conta_ponto():
    polo = C.avaliar(_r(2, "All Park Polo Empresarial", 1800, 4_800_000), AV)
    bairro_comum = C.avaliar(_r(3, "Vila Santa", 1800, 4_800_000), AV)
    assert "região industrial/empresarial, como o avaliando" in polo.motivo
    assert "industrial" not in bairro_comum.motivo
    assert polo.pontos > bairro_comum.pontos


def test_area_longe_pesa_menos():
    perto = C.avaliar(_r(4, "Vila Santa", 2100, 5_000_000), AV)
    meio = C.avaliar(_r(5, "Vila Santa", 2700, 5_000_000), AV)
    longe = C.avaliar(_r(6, "Vila Santa", 4100, 9_000_000), AV)
    assert perto.pontos > meio.pontos > longe.pontos
    assert "área compatível (2.700 m², +36% do avaliando)" in meio.motivo


def test_ordem_do_mais_parecido_para_o_menos():
    refs = [C.avaliar(x, AV) for x in (_r(1, "Vila Santa", 4100, 9_000_000),
                                      _r(2, "All Park Polo Empresarial", 1800, 4_800_000),
                                      _r(3, "Polo Empresarial Goiás", 2170, 6_000_000))]
    assert [r.n for r in C.ordenar(refs)] == [3, 2, 1]


def test_area_inferida_vale_so_para_comparar():
    campos = [Campo(nome="Área edificada cadastrada (IPTU)", valor="6363.65", origem="documento"),
              Campo(nome="Área construída do Galpão 01 – medida por satélite", valor=1982.96,
                    origem="inferido")]
    # com área de documento, ela manda
    assert pesquisa.area_para_comparar(campos) == 6363.65
    # sem documento/vistoria, a medida inferida serve para ordenar os candidatos
    assert pesquisa.area_para_comparar(campos[1:]) == 1982.96
    assert pesquisa.area_para_comparar([]) is None


def test_reavaliar_reordena_e_explica_sem_mexer_na_decisao():
    db.init()
    jid = db.criar_job(Trabalho(
        id="", numero=numero_livre(9118), modalidade="OV", finalidade="Venda", cliente="X",
        tipo="Galpão", bairro="Polo Empresarial Goiás – Etapa III", cidade="Aparecida de Goiânia",
        pin_maps="https://maps.app.goo.gl/x", data_base=date(2026, 11, 12),
        data_vistoria=date(2026, 11, 12)))
    db.salvar_campos(jid, [Campo(nome="Área construída do Galpão 01 – medida por satélite",
                                 valor=1982.96, origem="inferido")])
    a = _r(1, "Vila Santa", 4100, 9_000_000).model_copy(update={"decisao": "descarta",
                                                                "motivo_descarte": "grande"})
    b = _r(2, "Polo Empresarial Goiás", 2170, 6_000_000)
    db.salvar_candidatos(jid, [a, b])
    refs = pesquisa.reavaliar(jid)
    assert [r.n for r in refs] == [2, 1]                     # mais parecido primeiro
    novos = {r.n: r for r in db.candidatos(jid)}
    assert novos[1].decisao == "descarta" and novos[1].motivo_descarte == "grande"
    assert "mesmo bairro (Polo Empresarial Goiás)" in novos[2].motivo
    assert novos[2].pontos > novos[1].pontos
