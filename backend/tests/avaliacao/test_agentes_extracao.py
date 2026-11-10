import asyncio
from datetime import date

from lovable.avaliacao import conhecimento, db, ia
from lovable.avaliacao.agentes import extracao
from lovable.avaliacao.modelos import Campo, Trabalho
from tests.avaliacao.conftest import numero_livre


def _job(nomes=("iptu.pdf", "planta.pdf")) -> str:
    db.init()
    jid = db.criar_job(Trabalho(
        id="", numero=numero_livre(120), modalidade="OV", finalidade="Venda", cliente="Marina",
        tipo="Sobrado", bairro="Jardim Vila Boa", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
        data_base=date(2026, 10, 20), data_vistoria=date(2026, 10, 18),
        contexto="Dono disse que reformou em 2020"))
    p = db.pasta(jid)
    for nome in nomes:
        (p / nome).write_bytes(b"%PDF-1.4")
        db.adicionar_arquivo(jid, nome, "documento", nome)
    return jid


def _mock(monkeypatch, resposta: dict, prompts: list):
    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo=""):
        prompts.append((sistema, prompt, arquivos))
        return esquema.model_validate(resposta)
    monkeypatch.setattr(ia, "perguntar", fake)


def test_descarta_documento_de_outro_imovel(monkeypatch):
    jid = _job()
    pr = []
    _mock(monkeypatch, {
        "campos": [
            {"nome": "quadra", "valor": "50", "origem": "documento", "fonte": "iptu.pdf"},
            {"nome": "lote", "valor": "29", "origem": "documento", "fonte": "iptu.pdf"},
            {"nome": "area_construida", "valor": 180.0, "unidade": "m2", "origem": "documento",
             "fonte": "planta.pdf"},
        ],
        "quadras_lotes": [
            {"arquivo": "iptu.pdf", "papel": "iptu", "quadra": "QD 50", "lote": "LT 29"},
            {"arquivo": "planta.pdf", "quadra": "51", "lote": "29"},
        ],
    }, pr)
    r = asyncio.run(extracao.rodar(jid))
    assert "planta.pdf" in [d.arquivo for d in r.documentos_descartados]
    assert not any("planta.pdf" in c.fonte for c in r.campos)
    assert not any("planta.pdf" in c.fonte for c in db.campos(jid))
    assert db.resultado(jid, "extracao") is not None
    assert "iptu.pdf" in pr[0][1] and "planta.pdf" in pr[0][1]


def test_campo_sem_fonte_vira_pendente(monkeypatch):
    jid = _job()
    _mock(monkeypatch, {"campos": [
        {"nome": "ano_construcao", "valor": "2010", "origem": "documento", "fonte": ""}]}, [])
    asyncio.run(extracao.rodar(jid))
    c = {c.nome: c for c in db.campos(jid)}["ano_construcao"]
    assert c.origem == "pendente"


def test_caixas_degeneradas_descartadas(monkeypatch):
    jid = _job()
    _mock(monkeypatch, {"campos": [], "fachada_caixa": [10, 10, 5, 50],
                        "tarjas": {"f1.jpg": [[0, 0, 10, 10], [5, 5, 5, 9]]}}, [])
    r = asyncio.run(extracao.rodar(jid))
    assert r.fachada_caixa is None
    assert r.tarjas == {"f1.jpg": [(0, 0, 10, 10)]}


def test_normaliza_quadra_lote():
    assert extracao._norm("QD. 050") == extracao._norm("50") == extracao._norm("Q.50")
    assert extracao._norm("LT 029") == "29"
    assert extracao._norm("L") == "L" and extracao._norm("Q") == "Q" and extracao._norm("E") == "E"
    assert extracao._norm("L") != extracao._norm("Q")


def test_importar_decisoes_idempotente():
    db.init()
    conhecimento.importar_decisoes()
    with db._conn() as c:
        n1 = c.execute("SELECT COUNT(*) FROM av_decisions").fetchone()[0]
    conhecimento.importar_decisoes()
    with db._conn() as c:
        n2 = c.execute("SELECT COUNT(*) FROM av_decisions").fetchone()[0]
        codigos = [r[0] for r in c.execute("SELECT codigo FROM av_decisions")]
    assert n1 == n2 == 25
    assert "D-013" in codigos


def test_normas_e_texto():
    db.init()
    conhecimento.importar_normas()
    conhecimento.importar_normas()
    cods = {n["codigo"]: n for n in conhecimento.normas_vigentes()}
    assert "N1" in cods and "N3" not in cods
    t = conhecimento.texto("P0", "P3")
    assert "D-013" in t


def _ext(monkeypatch, jid, resp):
    _mock(monkeypatch, resp, [])
    return asyncio.run(extracao.rodar(jid))


def test_sem_referencia_avisa(monkeypatch):
    jid = _job()
    r = _ext(monkeypatch, jid, {"campos": [], "quadras_lotes": [
        {"arquivo": "planta.pdf", "quadra": "51", "lote": "29"}]})
    assert extracao.SEM_REFERENCIA in r.divergencias
    assert r.documentos_descartados == []
    with db._conn() as c:
        assert c.execute("SELECT COUNT(*) FROM av_events WHERE job=? AND nivel='aviso'",
                         (jid,)).fetchone()[0] == 1


def test_matricula_como_referencia_nomes_genericos(monkeypatch):
    a, b = "WhatsApp Image 2026-10-16.jpeg", "WhatsApp Image 2026-10-17.jpeg"
    jid = _job((a, b))
    r = _ext(monkeypatch, jid, {
        "campos": [{"nome": "area", "valor": 1, "origem": "documento", "fonte": b}],
        "quadras_lotes": [{"arquivo": a, "papel": "matricula", "quadra": "50", "lote": "29"},
                          {"arquivo": b, "papel": "outro", "quadra": "51", "lote": "29"}]})
    assert [d.arquivo for d in r.documentos_descartados] == [b]
    assert r.campos == []


def test_iptu_x_matricula_divergem_vira_divergencia(monkeypatch):
    jid = _job(("x.pdf", "y.pdf"))
    r = _ext(monkeypatch, jid, {"campos": [], "quadras_lotes": [
        {"arquivo": "x.pdf", "papel": "iptu", "quadra": "50", "lote": "29"},
        {"arquivo": "y.pdf", "papel": "matricula", "quadra": "50", "lote": "30"}]})
    assert r.documentos_descartados == []
    assert any("y.pdf" in d for d in r.divergencias)


def test_fonte_nao_registrada_vira_pendente(monkeypatch):
    jid = _job(("iptu.pdf", "f1.jpg"))
    r = _ext(monkeypatch, jid, {"campos": [
        {"nome": "ano", "valor": "2010", "origem": "documento", "fonte": "informação do cliente"},
        {"nome": "reforma", "valor": "sim", "origem": "vistoria", "fonte": "informação do cliente"},
        {"nome": "piso", "valor": "cerâmica", "origem": "vistoria", "fonte": "iptu.pdf"},
        {"nome": "fachada", "valor": "pintada", "origem": "vistoria", "fonte": "f1.jpg"},
        {"nome": "area", "valor": 1, "origem": "documento", "fonte": "iptu.pdf, p. 1"}]})
    o = {c.nome: c.origem for c in r.campos}
    assert o == {"ano": "pendente", "reforma": "pendente", "piso": "pendente",
                 "fachada": "vistoria", "area": "documento"}


def test_descarte_por_nome_exato(monkeypatch):
    jid = _job(("iptu.pdf", "a.pdf", "planta_a.pdf"))
    r = _ext(monkeypatch, jid, {
        "campos": [{"nome": "x", "valor": 1, "origem": "documento", "fonte": "planta_a.pdf p.2"},
                   {"nome": "y", "valor": 2, "origem": "documento", "fonte": "a.pdf"}],
        "documentos_descartados": [{"arquivo": "a.pdf", "motivo": "outro imóvel"}]})
    assert [c.nome for c in r.campos] == ["x"]


def test_caixa_float_e_none(monkeypatch):
    jid = _job()
    r = _ext(monkeypatch, jid, {"campos": [], "fachada_caixa": [1.4, 2.6, 30.5, 40.0],
                                "tarjas": {"f.jpg": [None, [0, 0, None, 5], [0.2, 0, 9.7, 9]]}})
    assert r.fachada_caixa == (1, 3, 30, 40)
    assert r.tarjas == {"f.jpg": [(0, 0, 10, 9)]}


def test_caixa_infinita_descartada(monkeypatch):
    jid = _job()
    r = _ext(monkeypatch, jid, {"campos": [], "fachada_caixa": [0, 0, "inf", 40],
                                "tarjas": {"f.jpg": [[0, 0, 1e400, 5], [0, 0, 9, 9]],
                                           "g.pdf#p2": [[1, 1, 5, 5]]}})
    assert r.fachada_caixa is None
    assert r.tarjas == {"f.jpg": [(0, 0, 9, 9)], "g.pdf#p2": [(1, 1, 5, 5)]}
    assert "#p" in extracao.INSTRUCAO
