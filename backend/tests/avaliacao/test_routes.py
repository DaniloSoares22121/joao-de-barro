import itertools

import pytest

from lovable import auth
from lovable.avaliacao import conhecimento, db, ia, orquestrador
from tests.conftest import make_user


@pytest.fixture(autouse=True)
def _fotos_falsas(monkeypatch):
    """Estes testes exercitam nome/idempotência do envio com "fotos" de poucos bytes; a
    normalização de imagem de verdade (e a recusa da que não abre) fica em test_imagens.py."""
    from lovable.avaliacao import imagens
    monkeypatch.setattr(imagens, "normalizar", lambda p: False)


DONO = "alan@test.local"
TRAB = {"numero": 121, "modalidade": "OV", "finalidade": "Venda", "cliente": "Fulano",
        "tipo": "Casa", "bairro": "Centro", "cidade": "Goiânia",
        "pin_maps": "https://maps.app.goo.gl/x", "data_base": "2026-10-16",
        "data_vistoria": "2026-10-16"}


_seq = itertools.count(1000)


def _trab():
    """TRAB com número inédito (o servidor recusa número repetido com 409)."""
    return {**TRAB, "numero": next(_seq)}


def _h(email):
    return {"Authorization": f"Bearer {make_user(email)[1]}"}


@pytest.fixture()
def dono(client, monkeypatch):
    db.init()
    db.set_setting("dono_email", DONO)
    fila = []
    monkeypatch.setattr(orquestrador, "enfileirar", fila.append)
    return _h(DONO), fila


def test_sem_dono_configurado_403(client):
    db.init()
    with db._conn() as c:
        c.execute("DELETE FROM av_settings WHERE chave='dono_email'")
    assert client.get("/api/avaliacao/jobs", headers=_h(DONO)).status_code == 403


def test_admin_define_dono(client):
    adm = {"X-Admin-Token": auth.admin_make_token()}
    r = client.put("/api/admin/avaliacao/dono", json={"email": DONO}, headers=adm)
    assert r.status_code == 200
    assert db.setting("dono_email") == DONO
    assert client.put("/api/admin/avaliacao/dono", json={"email": "x@y"}).status_code in (401, 403)


def test_outro_usuario_403(client, dono):
    assert client.get("/api/avaliacao/jobs", headers=_h("outro@test.local")).status_code == 403
    assert client.post("/api/avaliacao/jobs", json=TRAB,
                       headers=_h("outro@test.local")).status_code == 403
    assert client.get("/api/avaliacao/config", headers=_h("outro@test.local")).status_code == 403


def test_criar_upload_iniciar(client, dono):
    h, fila = dono
    jid = client.post("/api/avaliacao/jobs", json=_trab(), headers=h).json()["id"]
    r = client.post(f"/api/avaliacao/jobs/{jid}/arquivos", headers=h, data={"tipo": "foto"},
                    files=[("arquivos", ("../../ev il.jpg", b"abc", "image/jpeg"))])
    assert r.status_code == 200, r.text
    arqs = r.json()
    assert arqs[0]["nome"] == "ev_il.jpg" and arqs[0]["caminho"] == "foto/ev_il.jpg"
    assert (db.pasta(jid) / "foto" / "ev_il.jpg").read_bytes() == b"abc"
    assert client.post(f"/api/avaliacao/jobs/{jid}/arquivos", headers=h, data={"tipo": "xx"},
                       files=[("arquivos", ("a.jpg", b"a", "image/jpeg"))]).status_code == 400
    assert client.post(f"/api/avaliacao/jobs/{jid}/iniciar", headers=h).status_code == 202
    assert fila == [jid]
    d = client.get(f"/api/avaliacao/jobs/{jid}", headers=h).json()
    assert d["job"]["id"] == jid and "etapas" in d and d["arquivos"]
    lista = client.get("/api/avaliacao/jobs", headers=h).json()
    item = next(j for j in lista if j["id"] == jid)
    assert (item["tipo"], item["bairro"], item["cidade"]) == (TRAB["tipo"], TRAB["bairro"], TRAB["cidade"])
    assert client.get("/api/avaliacao/jobs/naoexiste", headers=h).status_code == 404


def test_entrega_traversal_404(client, dono):
    h, _ = dono
    jid = client.post("/api/avaliacao/jobs", json=_trab(), headers=h).json()["id"]
    ent = db.pasta(jid) / "entrega"
    ent.mkdir(exist_ok=True)
    (ent / "pendencias.md").write_text("ok", encoding="utf-8")
    assert client.get(f"/api/avaliacao/jobs/{jid}/entrega/pendencias.md", headers=h).text == "ok"
    for alvo in ("../../app.db", "..%2F..%2Fapp.db", "%2E%2E%2F%2E%2E%2Fapp.db"):
        assert client.get(f"/api/avaliacao/jobs/{jid}/entrega/{alvo}",
                          headers=h).status_code == 404


def test_corrigir_vira_regra(client, dono, monkeypatch):
    h, fila = dono
    conhecimento.importar_decisoes()
    with db._conn() as c:
        maior = max(int(r["codigo"][2:]) for r in c.execute(
            "SELECT codigo FROM av_decisions WHERE codigo LIKE 'D-%'"))
    jid = client.post("/api/avaliacao/jobs", json=_trab(), headers=h).json()["id"]

    async def falso(sistema, prompt, esquema, **kw):
        return esquema(etapa="selecao", instrucao="Descartar o referencial 3.")
    monkeypatch.setattr(ia, "perguntar", falso)
    r = client.post(f"/api/avaliacao/jobs/{jid}/corrigir", headers=h,
                    json={"texto": "tira o 3", "virar_regra": True})
    assert r.status_code == 202, r.text
    codigo = f"D-{maior + 1:03d}"
    assert r.json()["etapa"] == "selecao" and r.json()["decisao"] == codigo
    with db._conn() as c:
        assert c.execute("SELECT decisao FROM av_decisions WHERE codigo=?",
                         (codigo,)).fetchone()["decisao"] == "Descartar o referencial 3."
    assert db.correcoes(jid, "selecao") == ["Descartar o referencial 3."]
    assert "Descartar o referencial 3." in db.texto_correcoes(jid, "selecao")
    assert fila == [jid]
    assert db.job(jid)["etapa"] == "selecao"


def test_config(client, dono):
    h, _ = dono
    r = client.put("/api/avaliacao/config", headers=h,
                   json={"avaliador": {"nome": "Alan", "creci": "36507"}})
    assert r.status_code == 200
    d = client.get("/api/avaliacao/config", headers=h).json()
    assert d["avaliador"]["nome"] == "Alan" and "decisoes" in d and "normas" in d


def test_config_lista_normas_nao_vigentes(client, dono):
    h, _ = dono
    r = client.put("/api/avaliacao/config", headers=h, json={"normas": [
        {"codigo": "N90", "titulo": "Vigente", "itens": {}, "vigente": True},
        {"codigo": "N91", "titulo": "Revogada", "itens": {}, "vigente": False}]})
    assert r.status_code == 200, r.text
    normas = {n["codigo"]: n for n in client.get("/api/avaliacao/config", headers=h).json()["normas"]}
    assert normas["N90"]["vigente"] is True and normas["N91"]["vigente"] is False
    assert "N91" not in {n["codigo"] for n in conhecimento.normas_vigentes()}
    # dá para reativar
    client.put("/api/avaliacao/config", headers=h, json={"normas": [
        {"codigo": "N91", "titulo": "Revogada", "itens": {}, "vigente": True}]})
    normas = {n["codigo"]: n for n in client.get("/api/avaliacao/config", headers=h).json()["normas"]}
    assert normas["N91"]["vigente"] is True


def test_ws_eventos(client, dono):
    h, _ = dono
    jid = client.post("/api/avaliacao/jobs", json=_trab(), headers=h).json()["id"]
    db.evento(jid, "triagem", "inicio", "etapa iniciada")
    tok = h["Authorization"][7:]
    with client.websocket_connect(f"/ws/avaliacao/{jid}?token={tok}") as ws:
        ev = ws.receive_json()
        assert ev["etapa"] == "triagem" and ev["msg"] == "etapa iniciada"
    outro = make_user("outro@test.local")[1]
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/avaliacao/{jid}?token={outro}") as ws:
            ws.receive_json()


# ---------------------------------------------------------------- fix round 1
def _novo(client, h):
    return client.post("/api/avaliacao/jobs", json=_trab(), headers=h).json()["id"]


def test_ws_desconecta_sem_vazar(client, dono):
    import time
    from lovable.avaliacao import routes
    h, _ = dono
    jid = _novo(client, h)
    with client.websocket_connect(f"/ws/avaliacao/{jid}?token={h['Authorization'][7:]}"):
        time.sleep(0.2)
        assert routes.ws_vivos() == 1
    for _ in range(40):
        if routes.ws_vivos() == 0:
            break
        time.sleep(0.1)
    assert routes.ws_vivos() == 0


@pytest.mark.parametrize("tok", ["lixo", None])
def test_ws_recusa_4403(client, dono, tok):
    from starlette.websockets import WebSocketDisconnect
    h, _ = dono
    jid = _novo(client, h)
    tok = tok or make_user("outro@test.local")[1]
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(f"/ws/avaliacao/{jid}?token={tok}") as ws:
            ws.receive_json()
    assert e.value.code == 4403


def test_upload_grande_413_sem_parcial(client, dono, monkeypatch):
    from lovable.avaliacao import routes
    h, _ = dono
    monkeypatch.setattr(routes, "MAX_BYTES", 3 * 1024 * 1024)
    monkeypatch.setattr(routes, "BLOCO", 1024 * 1024)
    jid = _novo(client, h)
    r = client.post(f"/api/avaliacao/jobs/{jid}/arquivos", headers=h, data={"tipo": "foto"},
                    files=[("arquivos", ("big.jpg", b"x" * (4 * 1024 * 1024), "image/jpeg"))])
    assert r.status_code == 413
    assert not (db.pasta(jid) / "foto" / "big.jpg").exists()
    assert db.arquivos(jid) == []


def test_upload_content_length_gigante_413(client, dono):
    h, _ = dono
    jid = _novo(client, h)
    r = client.post(f"/api/avaliacao/jobs/{jid}/arquivos",
                    headers={**h, "Content-Length": str(2 * 1024 ** 3),
                             "Content-Type": "multipart/form-data; boundary=x"}, content=b"")
    assert r.status_code == 413


def test_config_edita_p3_p4(client, dono):
    h, _ = dono
    conhecimento.importar_decisoes()
    conhecimento.importar_normas()
    r = client.put("/api/avaliacao/config", headers=h, json={
        "decisoes": [{"codigo": "D-013", "data": "20/10/2026", "laudo": "x", "decisao": "EDITADA",
                      "regra": "r", "tipo": "PR", "escopo": "Todos", "status": "Aprovada"},
                     {"codigo": "D-900", "data": "20/10/2026", "laudo": "", "decisao": "nova",
                      "regra": "", "tipo": "", "escopo": "", "status": "Aprovada"}],
        "normas": [{"codigo": "N99", "titulo": "Norma teste", "itens": {"a": "b"}, "vigente": True}]})
    assert r.status_code == 200, r.text
    d = client.get("/api/avaliacao/config", headers=h).json()
    decs = {x["codigo"]: x for x in d["decisoes"]}
    assert decs["D-013"]["decisao"] == "EDITADA" and decs["D-900"]["decisao"] == "nova"
    assert any(n["codigo"] == "N99" and n["itens"] == {"a": "b"} for n in d["normas"])
    # importação do startup não sobrescreve o que foi editado em tempo de execução
    conhecimento.importar_decisoes()
    conhecimento.importar_normas()
    d = client.get("/api/avaliacao/config", headers=h).json()
    assert {x["codigo"]: x for x in d["decisoes"]}["D-013"]["decisao"] == "EDITADA"
    assert any(n["codigo"] == "N99" for n in d["normas"])


def test_enfileirar_nao_duplica(monkeypatch):
    import asyncio
    monkeypatch.setattr(orquestrador, "_fila", asyncio.Queue())
    monkeypatch.setattr(orquestrador, "_ativos", set())
    orquestrador.enfileirar("j1")
    orquestrador.enfileirar("j1")
    assert orquestrador._fila.qsize() == 1 and orquestrador.ocupado("j1")


def test_corrigir_durante_execucao_409(client, dono, monkeypatch):
    h, _ = dono
    jid = _novo(client, h)
    monkeypatch.setattr(orquestrador, "_ativos", {jid})
    r = client.post(f"/api/avaliacao/jobs/{jid}/corrigir", headers=h,
                    json={"texto": "x", "virar_regra": False})
    assert r.status_code == 409


# ---------------------------------------------------------------- fix round 2
def _multipart(nome, tamanho, bloco=64 * 1024):
    b = b"----lim"
    yield (b"--" + b + b'\r\nContent-Disposition: form-data; name="tipo"\r\n\r\nfoto\r\n'
           b"--" + b + b'\r\nContent-Disposition: form-data; name="arquivos"; filename="'
           + nome.encode() + b'"\r\nContent-Type: image/jpeg\r\n\r\n')
    enviado = 0
    while enviado < tamanho:
        yield b"x" * bloco
        enviado += bloco
    yield b"\r\n--" + b + b"--\r\n"


@pytest.mark.parametrize("chunked", [False, True])
def test_middleware_corta_corpo(client, dono, monkeypatch, chunked):
    from lovable.avaliacao import routes
    h, _ = dono
    jid = _novo(client, h)
    monkeypatch.setattr(routes, "MAX_REQUISICAO", 256 * 1024)
    chamado = []
    original = routes.db.adicionar_arquivo
    monkeypatch.setattr(routes.db, "adicionar_arquivo", lambda *a: chamado.append(a) or original(*a))
    hdr = {**h, "Content-Type": "multipart/form-data; boundary=----lim"}
    if chunked:
        corpo = _multipart("big.jpg", 1024 * 1024)
    else:
        corpo = b"".join(_multipart("big.jpg", 1024 * 1024))
    r = client.post(f"/api/avaliacao/jobs/{jid}/arquivos", headers=hdr, content=corpo)
    assert r.status_code == 413
    assert not chamado and not (db.pasta(jid) / "foto" / "big.jpg").exists()


def test_reenvio_falho_preserva_anterior(client, dono, monkeypatch):
    from lovable.avaliacao import routes
    h, _ = dono
    jid = _novo(client, h)
    up = lambda dados: client.post(f"/api/avaliacao/jobs/{jid}/arquivos", headers=h,
                                   data={"tipo": "foto"},
                                   files=[("arquivos", ("a.jpg", dados, "image/jpeg"))])
    assert up(b"bom").status_code == 200
    monkeypatch.setattr(routes, "MAX_BYTES", 10)
    monkeypatch.setattr(routes, "BLOCO", 4)
    assert up(b"y" * 100).status_code == 413
    assert (db.pasta(jid) / "foto" / "a.jpg").read_bytes() == b"bom"
    assert not [p for p in (db.pasta(jid) / "foto").iterdir() if p.name != "a.jpg"]


def test_corrigir_ocupado_apos_ia_409(client, dono, monkeypatch):
    h, fila = dono
    jid = _novo(client, h)

    async def falso(sistema, prompt, esquema, **kw):
        orquestrador._ativos.add(jid)  # job começou a rodar durante a chamada da IA
        return esquema(etapa="selecao", instrucao="x")
    monkeypatch.setattr(orquestrador, "_ativos", set())
    monkeypatch.setattr(ia, "perguntar", falso)
    r = client.post(f"/api/avaliacao/jobs/{jid}/corrigir", headers=h,
                    json={"texto": "x", "virar_regra": False})
    assert r.status_code == 409 and fila == []


def test_upload_nome_repetido_nao_sobrescreve(client, dono):
    h, _ = dono
    jid = client.post("/api/avaliacao/jobs", json=_trab(), headers=h).json()["id"]
    nomes = []
    for corpo in (b"um", b"dois"):
        r = client.post(f"/api/avaliacao/jobs/{jid}/arquivos", headers=h, data={"tipo": "foto"},
                        files=[("arquivos", ("image.jpg", corpo, "image/jpeg"))])
        assert r.status_code == 200, r.text
        nomes.append(r.json()[0]["nome"])
    assert nomes == ["image.jpg", "image-2.jpg"]
    pasta = db.pasta(jid) / "foto"
    assert (pasta / "image.jpg").read_bytes() == b"um"
    assert (pasta / "image-2.jpg").read_bytes() == b"dois"
    assert [a["caminho"] for a in db.arquivos(jid)] == ["foto/image.jpg", "foto/image-2.jpg"]


def test_upload_fachada_grava_papel(client, dono):
    h, _ = dono
    jid = client.post("/api/avaliacao/jobs", json=_trab(), headers=h).json()["id"]
    url = f"/api/avaliacao/jobs/{jid}/arquivos"
    client.post(url, headers=h, data={"tipo": "foto"}, files=[("arquivos", ("a.jpg", b"a", "image/jpeg"))])
    r = client.post(url, headers=h, data={"tipo": "foto", "fachada": "true"},
                    files=[("arquivos", ("b.jpg", b"b", "image/jpeg"))])
    assert r.status_code == 200, r.text
    assert {a["nome"]: a["papel"] for a in db.arquivos(jid)} == {"a.jpg": "", "b.jpg": "fachada"}
    assert db.fachada(jid) == "foto/b.jpg"
    # documento nunca vira fachada
    client.post(url, headers=h, data={"tipo": "documento", "fachada": "true"},
                files=[("arquivos", ("c.pdf", b"c", "application/pdf"))])
    assert db.fachada(jid) == "foto/b.jpg"


def test_proximo_numero_e_numero_repetido_409(client, dono):
    h, _ = dono
    n = client.get("/api/avaliacao/proximo-numero", headers=h).json()["numero"]
    assert client.post("/api/avaliacao/jobs", json={**TRAB, "numero": n}, headers=h).status_code == 200
    assert client.get("/api/avaliacao/proximo-numero", headers=h).json()["numero"] == n + 1
    r = client.post("/api/avaliacao/jobs", json={**TRAB, "numero": n}, headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "número já usado"
    assert client.get("/api/avaliacao/proximo-numero",
                      headers=_h("outro@test.local")).status_code == 403


def test_criar_amj_com_processo_e_quesitos(client, dono):
    h, _ = dono
    corpo = dict(_trab(), modalidade="AMJ", processo_numero="0001", vara_juizo="1ª Vara",
                 numero=90000 + next(_seq),
                 partes={"autor": "A", "reu": "B"}, quesitos=["Qual o valor?", "Há ônus?"])
    resp = client.post("/api/avaliacao/jobs", json=corpo, headers=h)
    assert resp.status_code == 200, resp.text
    jid = resp.json()["id"]
    d = client.get(f"/api/avaliacao/jobs/{jid}", headers=h).json()["job"]["dados"]
    assert d["processo_numero"] == "0001" and d["partes"] == {"autor": "A", "reu": "B"}
    assert d["quesitos"] == ["Qual o valor?", "Há ônus?"]


def test_config_avaliador_formacao_qualificacao(client, dono):
    h, _ = dono
    client.put("/api/avaliacao/config", headers=h, json={"avaliador": {
        "nome": "Alan", "formacao": "Técnico TTI", "qualificacao": "Perito há 10 anos"}})
    av = client.get("/api/avaliacao/config", headers=h).json()["avaliador"]
    assert av["formacao"] == "Técnico TTI" and av["qualificacao"] == "Perito há 10 anos"
