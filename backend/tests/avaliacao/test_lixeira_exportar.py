"""ORDEM 060: Apagar vai para a Lixeira (restaurar / esvaziar) e Exportar junta o trabalho num .zip."""
import asyncio
import io
import zipfile
from datetime import date

from lovable.avaliacao import db, routes, rotas_lixeira as L
from lovable.avaliacao.modelos import Referencial, Trabalho
from tests.avaliacao.conftest import numero_unico


def _novo(cliente="Fulano de Tal"):
    db.init()
    n = numero_unico()
    jid = db.criar_job(Trabalho(id="", numero=n, modalidade="OV", finalidade="Venda", cliente=cliente,
                                tipo="Casa", bairro="Setor Teste", cidade="Goiânia", pin_maps="",
                                data_base=date(2026, 11, 14), data_vistoria=date(2026, 11, 14)))
    base = db.pasta(jid)
    for pasta, nome, tipo in (("documento", "IPTU.pdf", "documento"), ("foto", "frente.jpg", "foto")):
        (base / pasta).mkdir(parents=True, exist_ok=True)
        (base / pasta / nome).write_bytes(b"x")
        db.adicionar_arquivo(jid, nome, tipo, f"{pasta}/{nome}")
    return jid, n


def _ids_da_lista():
    return {j["id"] for j in asyncio.run(routes.listar(_u={}))}


def test_apagar_vai_para_lixeira_e_restaura():
    jid, n = _novo()
    assert jid in _ids_da_lista()
    asyncio.run(L.para_lixeira(jid, _u={}))
    assert jid not in _ids_da_lista()                                   # sai da lista
    lix = asyncio.run(L.ver_lixeira(_u={}))
    assert [x["numero"] for x in lix if x["id"] == jid] == [n]
    assert (db.pasta(jid) / "foto" / "frente.jpg").is_file()            # nada apagado de vez
    assert db.numero_usado(n)                                           # o número continua reservado
    asyncio.run(L.restaurar(jid, _u={}))
    assert jid in _ids_da_lista()
    assert all(x["id"] != jid for x in asyncio.run(L.ver_lixeira(_u={})))


def test_esvaziar_apaga_so_o_que_esta_na_lixeira():
    fica, _ = _novo()
    vai, n = _novo()
    asyncio.run(L.para_lixeira(vai, _u={}))
    r = asyncio.run(L.esvaziar_lixeira(_u={}))
    assert n in r["apagados"]
    assert not db.numero_usado(n) and not db.pasta(vai).joinpath("foto", "frente.jpg").exists()
    assert fica in _ids_da_lista() and (db.pasta(fica) / "foto" / "frente.jpg").is_file()
    assert db.setting(f"lixeira:{vai}") is None


def test_entregue_avisa():
    jid, _ = _novo()
    assert not L.entregue(jid)
    (db.pasta(jid) / "entrega").mkdir(exist_ok=True)
    (db.pasta(jid) / "entrega" / "laudo.pdf").write_bytes(b"pdf")
    db.evento(jid, "entrega", "resultado", "ok", dados={"status": "PRONTO PARA REVISÃO", "arquivos": ["laudo.pdf"]})
    assert L.entregue(jid)


def test_exportar_zip_com_tudo_o_que_existe():
    jid, n = _novo("Maria Teste")
    ent = db.pasta(jid) / "entrega"
    ent.mkdir(exist_ok=True)
    for nome in ("laudo.pdf", "laudo.docx", "laudo.xlsx", "laudo_assinado.pdf", "pendencias.md", "antigo.pdf"):
        (ent / nome).write_bytes(b"x")
    db.evento(jid, "entrega", "resultado", "ok",
              dados={"status": "PRONTO PARA REVISÃO", "arquivos": ["laudo.docx", "laudo.pdf", "laudo.xlsx", "pendencias.md"]})
    prov = db.pasta(jid) / "provas" / "anuncios"
    prov.mkdir(parents=True)
    (prov / "anuncio_01.jpg").write_bytes(b"jpg")
    db.salvar_candidatos(jid, [Referencial(n=1, link="https://x/1", portal="ZAP", bairro="B", tipologia="casa",
                                           preco=1000, area_m2=10, padrao="", idade_aparente="", descricao="",
                                           prova="provas/anuncios/anuncio_01.jpg")])
    dados, conta = L.montar_zip(jid)
    nomes = set(zipfile.ZipFile(io.BytesIO(dados)).namelist())
    assert {"laudo/laudo.pdf", "laudo/laudo.docx", "laudo/laudo_assinado.pdf", "planilha/laudo.xlsx",
            "documentos/IPTU.pdf", "fotos/frente.jpg", "anuncios/anuncio_01.jpg",
            "anuncios/lista_de_anuncios.txt", "LEIA-ME.txt"} <= nomes
    assert not any(x.endswith(".md") for x in nomes)
    assert "laudo/antigo.pdf" not in nomes                     # só a última revisão
    assert L._nome_zip(jid) == f"{abs(n)} - Maria - Casa - Setor Teste - Goiânia"   # Nº - Cliente - Tipo - Bairro - Cidade
    assert conta["fotos"] == 1 and conta["documentos"] == 1
