"""111-3b: a idade dita na conversa vale nos anúncios e fecha os cartões da idade pela foto."""
from datetime import date

from lovable.avaliacao import db, idade_conversa, pendencias_simples as PS
from lovable.avaliacao.modelos import Referencial, Trabalho

FRASE = ("Idade aparente dos anúncios: os referenciais 1, 2, 3, 4, 5 e 8 têm 30 anos, como no meu relato da visita. "
         "O anúncio 6 (Rua JC-18, só comparação) é novo. O anúncio 7 (Rua JC-60, só comparação) não informa a idade.")


def test_ler_a_frase_do_capitao():
    assert idade_conversa.ler(FRASE) == {1: "30 anos", 2: "30 anos", 3: "30 anos", 4: "30 anos", 5: "30 anos",
                                         8: "30 anos", 6: "novo", 7: ""}
    assert idade_conversa.ler("A visita fica para amanhã às 10 horas.") == {}


def test_aplicar_grava_e_fecha_cartoes():
    db.init()
    jid = db.criar_job(Trabalho(id="", numero=1, modalidade="AM", finalidade="Garantia", cliente="F", tipo="Casa",
                                bairro="Centro", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
                                data_base=date(2026, 11, 15), data_vistoria=date(2026, 11, 14)))
    db.salvar_candidatos(jid, [Referencial(n=n, portal="X", link=f"https://x/{n}", area_m2=100, preco=200000, bairro="B",
                                           tipologia="Casa", padrao="", descricao="", decisao="entra", escolhido=True,
                                           idade_aparente="20 anos", idade_fonte="fotos") for n in (3, 6)])
    assert {c["chave"] for c in PS.classificar(jid, [])["cards"]} >= {"idade_foto:3", "idade_foto:6"}
    assert idade_conversa.aplicar(jid, FRASE) == [3, 6]
    por_n = {r.n: r for r in db.candidatos(jid)}
    assert por_n[3].idade_aparente == "30 anos" and por_n[3].idade_fonte == "avaliador"
    assert por_n[6].idade_aparente == "novo"
    assert not {c["chave"] for c in PS.classificar(jid, [])["cards"]} & {"idade_foto:3", "idade_foto:6"}
