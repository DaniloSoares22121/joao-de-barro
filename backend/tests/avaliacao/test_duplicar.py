"""ORDEM 028-5: "Duplicar trabalho" copia tudo e não muda o original."""
import asyncio
import json
from datetime import date

from lovable.avaliacao import db, routes
from lovable.avaliacao.modelos import Campo, Referencial, Trabalho
from tests.avaliacao.conftest import numero_unico


def _foto(jid):
    db.init()
    p = db.pasta(jid) / "foto"
    p.mkdir(parents=True, exist_ok=True)
    (p / "a.jpg").write_bytes(b"jpg")
    db.adicionar_arquivo(jid, "a.jpg", "foto", "foto/a.jpg")
    (db.pasta(jid) / "entrega").mkdir(exist_ok=True)
    (db.pasta(jid) / "entrega" / "laudo.pdf").write_bytes(b"pdf")


def _retrato(jid):
    with db._conn() as c:
        return json.dumps({
            "job": dict(c.execute("SELECT numero, dados_json, etapa, status FROM av_jobs WHERE id=?", (jid,)).fetchone()),
            "f": [tuple(r) for r in c.execute("SELECT nome, json FROM av_fields WHERE job=? ORDER BY nome", (jid,))],
            "c": [tuple(r) for r in c.execute("SELECT n, json FROM av_candidates WHERE job=? ORDER BY n", (jid,))],
            "e": c.execute("SELECT COUNT(*), MAX(id) FROM av_events WHERE job=?", (jid,)).fetchone()[:],
            "a": [tuple(r) for r in c.execute("SELECT nome, caminho FROM av_files WHERE job=? ORDER BY id", (jid,))],
            "s": db.setting(f"area_escolha:{jid}")}, default=str, sort_keys=True)


def test_duplicar_copia_e_original_intacto():
    db.init()
    n = abs(numero_unico()) + 50000
    jid = db.criar_job(Trabalho(id="", numero=n, modalidade="OV", finalidade="Venda", cliente="Teste",
                                tipo="Galpão", bairro="B", cidade="C", pin_maps="",
                                data_base=date(2026, 11, 13), data_vistoria=date(2026, 11, 13)))
    _foto(jid)
    db.salvar_campos(jid, [Campo(nome="Área construída", valor=100, origem="documento", fonte="x.pdf")])
    db.salvar_candidatos(jid, [Referencial(n=1, link="https://x/1", portal="ZAP", bairro="B", tipologia="galpão",
                                           preco=1000, area_m2=10, padrao="", idade_aparente="", descricao="")])
    db.evento(jid, "extracao", "resultado", "x", dados={"campos": []})
    db.set_setting(f"area_escolha:{jid}", '{"base": "construida", "campo": "Área construída", "valor": 100}')
    antes = _retrato(jid)
    r = asyncio.run(routes.duplicar_trabalho(jid, _u={}))
    assert _retrato(jid) == antes                                  # original não muda em nada
    cop = r["id"]
    assert r["numero"] == int(f"{n}1")
    assert db.campos(cop)[0].nome == "Área construída" and db.candidatos(cop)[0].link == "https://x/1"
    assert (db.pasta(cop) / "foto" / "a.jpg").is_file() and not (db.pasta(cop) / "entrega").exists()
    assert db.resultado(cop, "extracao") == {"campos": []}
    assert "CÓPIA DE TESTE (não usar)" in db.job(cop)["dados"]["contexto"]
    assert db.setting(f"area_escolha:{cop}") == db.setting(f"area_escolha:{jid}")
