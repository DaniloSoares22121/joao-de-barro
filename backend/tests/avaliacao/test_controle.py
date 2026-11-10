"""Bloco C: upload idempotente, número único, edição manual, escolha de referenciais,
reabertura, pendências acionáveis, edição do trabalho e aviso de fim."""
import itertools
import json
import sqlite3
from datetime import date
from decimal import Decimal

import pytest

from lovable.avaliacao import aviso, db, orquestrador
from lovable.avaliacao.modelos import Campo, Trabalho
from tests.avaliacao import test_orquestrador as T
from tests.avaliacao.test_routes import TRAB, dono  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def _fotos_falsas(monkeypatch):
    """Estes testes exercitam nome/idempotência do envio com "fotos" de poucos bytes; a
    normalização de imagem de verdade (e a recusa da que não abre) fica em test_imagens.py."""
    from lovable.avaliacao import imagens
    monkeypatch.setattr(imagens, "normalizar", lambda p: False)


_seq = itertools.count(50000)


def _trab():
    return {**TRAB, "numero": next(_seq)}

API = "/api/avaliacao"


def _novo(client, h):
    return client.post(f"{API}/jobs", json=_trab(), headers=h).json()["id"]


def _up(client, h, jid, nome, corpo, uid="", tipo="foto"):
    hh = {**h, **({"X-Upload-Id": uid} if uid else {})}
    return client.post(f"{API}/jobs/{jid}/arquivos", headers=hh, data={"tipo": tipo},
                       files=[("arquivos", (nome, corpo, "image/jpeg"))])


def _pipeline(monkeypatch, com_maps=True) -> str:
    _, box = T._mock(monkeypatch)
    jid = T._job(com_maps=com_maps)
    box.append(jid)
    return jid


# ------------------------------------------------------------------ A1 / A3
def test_upload_idempotente_por_upload_id(client, dono):
    h, _ = dono
    jid = _novo(client, h)
    r1 = _up(client, h, jid, "a.jpg", b"um", uid="item-1")
    r2 = _up(client, h, jid, "a.jpg", b"um", uid="item-1")   # reenvio (resposta perdida)
    assert r1.status_code == r2.status_code == 200, r2.text
    assert r2.json()[0]["caminho"] == r1.json()[0]["caminho"] == "foto/a.jpg"
    assert r2.json()[0]["bytes"] == 2
    assert [a["caminho"] for a in db.arquivos(jid)] == ["foto/a.jpg"]
    assert sorted(p.name for p in (db.pasta(jid) / "foto").iterdir()) == ["a.jpg"]
    # outro item com o mesmo nome é outro arquivo
    assert _up(client, h, jid, "a.jpg", b"dois", uid="item-2").json()[0]["nome"] == "a-2.jpg"
    # mais de um arquivo com X-Upload-Id → 400
    r = client.post(f"{API}/jobs/{jid}/arquivos", headers={**h, "X-Upload-Id": "x"},
                    data={"tipo": "foto"}, files=[("arquivos", ("b.jpg", b"b", "image/jpeg")),
                                                  ("arquivos", ("c.jpg", b"c", "image/jpeg"))])
    assert r.status_code == 400


def test_upload_id_repetido_no_banco_nao_grava_duas_vezes():
    db.init()
    jid = db.criar_job(Trabalho(**{**_trab(), "id": "", "data_base": date(2026, 1, 1),
                                   "data_vistoria": date(2026, 1, 1)}))
    db.adicionar_arquivo(jid, "a.jpg", "foto", "foto/a.jpg", upload_id="u1")
    with pytest.raises(sqlite3.IntegrityError):
        db.adicionar_arquivo(jid, "a-2.jpg", "foto", "foto/a-2.jpg", upload_id="u1")
    db.adicionar_arquivo(jid, "b.jpg", "foto", "foto/b.jpg")  # sem id: livre
    db.adicionar_arquivo(jid, "c.jpg", "foto", "foto/c.jpg")
    assert len(db.arquivos(jid)) == 3


def test_gravacao_exclusiva_nao_sobrescreve(tmp_path):
    from lovable.avaliacao import routes
    (tmp_path / "x.jpg").write_bytes(b"velho")
    tmp = tmp_path / ".x.part"
    tmp.write_bytes(b"novo")
    nome = routes._gravar_exclusivo(tmp, tmp_path, "x.jpg")  # nome tomado na corrida
    assert nome == "x-2.jpg" and not tmp.exists()
    assert (tmp_path / "x.jpg").read_bytes() == b"velho"
    assert (tmp_path / "x-2.jpg").read_bytes() == b"novo"


# ------------------------------------------------------------------ A2
def test_numero_unico_no_banco_e_409_na_corrida(client, dono, monkeypatch):
    h, _ = dono
    with db._conn() as c:
        c.execute("DELETE FROM av_jobs")
    db.init()
    with db._conn() as c:
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name='idx_av_jobs_numero'").fetchone()
    corpo = {**TRAB, "numero": 777}
    assert client.post(f"{API}/jobs", json=corpo, headers=h).status_code == 200
    monkeypatch.setattr(db, "numero_usado", lambda n: False)  # simula a corrida
    r = client.post(f"{API}/jobs", json=corpo, headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "número já usado"


def test_numero_duplicado_existente_nao_cria_indice(caplog):
    db.init()
    with db._conn() as c:
        c.execute("DROP INDEX IF EXISTS idx_av_jobs_numero")
        c.execute("DELETE FROM av_jobs")
        for i in ("d1", "d2"):
            c.execute("INSERT INTO av_jobs (id, numero, dados_json, criado, atualizado) "
                      "VALUES (?, 5, '{}', 'x', 'x')", (i,))
    db.init()
    with db._conn() as c:
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='idx_av_jobs_numero'").fetchone()
        c.execute("DELETE FROM av_jobs")
    assert "duplicados" in caplog.text


# ------------------------------------------------------------------ C1
def test_editar_campo_exige_fonte_e_registra_evento(client, dono, monkeypatch):
    h, _ = dono
    jid = _novo(client, h)
    _up(client, h, jid, "iptu.jpg", b"x", tipo="documento")
    _up(client, h, jid, "frente.jpg", b"y")
    db.salvar_campos(jid, [Campo(nome="Área construída", valor=None, unidade="m²", origem="pendente")])
    url = f"{API}/jobs/{jid}/campos/Área construída"
    sem = {"valor": "180", "origem": "documento", "fonte": "conversa com o cliente"}
    assert client.put(url, json=sem, headers=h).status_code == 400
    ok = client.put(url, json={"valor": "180,5", "origem": "documento",
                               "fonte": "documento/iptu.jpg p. 1"}, headers=h)
    assert ok.status_code == 200, ok.text
    c = next(c for c in db.campos(jid) if c.nome == "Área construída")
    assert (c.valor, c.origem, c.unidade) == ("180,5", "documento", "m²")
    evs = [e for e in db.eventos_desde(jid, 0) if e["nivel"] == "edicao_manual"]
    assert evs and evs[-1]["dados"]["campo"]["valor"] == "180,5"
    # vistoria: foto registrada ou "vistoria do avaliador em <data>"
    v = f"{API}/jobs/{jid}/campos/Padrão"
    assert client.put(v, json={"valor": "médio", "origem": "vistoria",
                               "fonte": "documento/iptu.jpg"}, headers=h).status_code == 400
    assert client.put(v, json={"valor": "médio", "origem": "vistoria",
                               "fonte": "vistoria do avaliador em 16/10/2026"},
                      headers=h).status_code == 200
    assert client.put(v, json={"valor": "médio", "origem": "vistoria", "fonte": "foto/frente.jpg"},
                      headers=h).status_code == 200
    assert client.put(v, json={"valor": "x", "origem": "pendente", "fonte": "a"},
                      headers=h).status_code == 422
    monkeypatch.setattr(orquestrador, "ocupado", lambda j: True)
    assert client.put(v, json={"valor": "m", "origem": "vistoria",
                               "fonte": "vistoria do avaliador em 16/10/2026"},
                      headers=h).status_code == 409


def test_edicao_manual_sobrevive_a_nova_extracao():
    from lovable.avaliacao.agentes import extracao
    jid = T._job()
    db.evento(jid, "extracao", "edicao_manual", "x", dados={"campo": Campo(
        nome="area_construida", valor="200", origem="vistoria",
        fonte="vistoria do avaliador em 16/10/2026").model_dump(mode="json")})
    ia = [Campo(nome="area_construida", valor=364.0, origem="documento", fonte="docs/iptu.png"),
          Campo(nome="quadra", valor="50", origem="documento", fonte="docs/iptu.png")]
    out = extracao.com_edicoes_manuais(jid, ia)
    assert [(c.nome, c.valor) for c in out] == [("area_construida", "200"), ("quadra", "50")]


# ------------------------------------------------------------------ C2 / C3
def test_escolher_referenciais_e_recalcular(client, dono, monkeypatch):
    h, fila = dono
    jid = _pipeline(monkeypatch)
    assert T._rodar(jid) == "PRONTO PARA REVISÃO"
    cands = db.candidatos(jid)
    url = f"{API}/jobs/{jid}/referenciais"
    assert client.put(url, json={"escolhidos": []}, headers=h).status_code == 400
    assert client.put(url, json={"escolhidos": [999]}, headers=h).status_code == 400
    validos = [r.n for r in cands if r.area_m2 and r.preco][:3]
    assert client.put(url, json={"escolhidos": validos, "unitario_adotado": "1"},
                      headers=h).status_code == 400            # fora do intervalo
    unit = [r.preco / r.area_m2 for r in cands if r.n in validos]
    meio = f"{(min(unit) + max(unit)) / 2:.2f}".replace(".", ",")
    r = client.put(url, json={"escolhidos": validos, "unitario_adotado": meio,
                              "justificativa": "três mais parecidos"}, headers=h)
    assert r.status_code == 200, r.text
    sel = db.resultado(jid, "selecao")
    assert sel["manual"] is True and sel["declaracao_amostra"].startswith("Amostra reduzida")
    assert {x["n"] for x in sel["refs"] if x["escolhido"]} == set(validos)
    assert all(x["justificativa"].startswith("escolha manual do avaliador") for x in sel["refs"])
    # Recalcular: reabre a partir do cálculo e enfileira
    assert client.post(f"{API}/jobs/{jid}/reabrir", json={"etapa": "selecao"},
                       headers=h).status_code == 422
    assert client.post(f"{API}/jobs/{jid}/reabrir", json={"etapa": "calculo"},
                       headers=h).status_code == 202
    assert fila == [jid] and db.resultado(jid, "entrega") is None
    assert T._rodar(jid) in orquestrador.FINAIS
    calc = db.resultado(jid, "calculo")
    assert Decimal(calc["unitario_adotado"]) == Decimal(meio.replace(",", "."))
    assert db.resultado(jid, "selecao")["manual"] is True     # IA da seleção não refeita
    monkeypatch.setattr(orquestrador, "ocupado", lambda j: True)
    assert client.post(f"{API}/jobs/{jid}/reabrir", json={"etapa": "redacao"},
                       headers=h).status_code == 409
    assert client.put(url, json={"escolhidos": validos}, headers=h).status_code == 409


# ------------------------------------------------------------------ C4
@pytest.mark.parametrize("texto,acao", [
    ("montagem: nenhuma foto de vistoria para o relatório fotográfico",
     {"tipo": "enviar_arquivo", "tipo_arquivo": "foto"}),
    ("montagem: imagem de localização ausente", {"tipo": "preencher_trabalho", "campo": "pin_maps"}),
    ("pesquisa: imagem de localização ausente: coletor offline", {"tipo": "ligar_coletor"}),
    ("campo essencial pendente: quadra", {"tipo": "editar_campo", "campo": "quadra"}),
    ("revisor (visual/extracao): campo obrigatório do imóvel sem dado: Área do terreno = n/i",
     {"tipo": "editar_campo", "campo": "Área do terreno"}),
    ("área construída do avaliando ausente", {"tipo": "editar_campo", "campo": "Área construída"}),
    ("montagem: AMJ sem dados do processo: vara",
     {"tipo": "preencher_trabalho", "campo": "processo_numero"}),
    ("montagem: documento do solicitante sem tarja: rg.pdf",
     {"tipo": "enviar_arquivo", "tipo_arquivo": "solicitante"}),
    ("amostra com menos de 5 referenciais: Amostra reduzida", {"tipo": "ligar_coletor"}),
    ("PDF não gerado (LibreOffice ausente)", None),
])
def test_acao_da_pendencia(texto, acao):
    assert orquestrador.acao_pendencia(texto) == acao


def test_entrega_grava_pendencias_com_acao(monkeypatch):
    jid = _pipeline(monkeypatch, com_maps=False)
    assert T._rodar(jid) == "PARCIAL — PENDÊNCIAS"
    pend = db.resultado(jid, "entrega")["pendencias"]
    assert any(p.get("acao") == {"tipo": "preencher_trabalho", "campo": "pin_maps"}
               for p in pend), pend


# ------------------------------------------------------------------ C5
def test_editar_trabalho(client, dono, monkeypatch):
    h, _ = dono
    jid = _novo(client, h)
    numero = db.job(jid)["numero"]
    corpo = {**{k: v for k, v in TRAB.items() if k != "numero"}, "cliente": "Beltrano", "numero": 1}
    r = client.put(f"{API}/jobs/{jid}", json=corpo, headers=h)
    assert r.status_code == 200, r.text
    j = db.job(jid)
    assert j["dados"]["cliente"] == "Beltrano" and j["numero"] == numero == j["dados"]["numero"]
    assert j["dados"]["id"] == jid
    monkeypatch.setattr(orquestrador, "ocupado", lambda x: True)
    assert client.put(f"{API}/jobs/{jid}", json=corpo, headers=h).status_code == 409


# ------------------------------------------------------------------ C6
def _avaliador(tel="62999990000"):
    db.set_setting("avaliador", json.dumps({"nome": "Alan", "telefone": tel}))


def test_aviso_de_fim_envia_uma_vez(monkeypatch):
    enviados = []
    monkeypatch.setenv("LOVABLE_JOAODEBARRO_HOST", "jdb.exemplo.com")
    monkeypatch.setattr(aviso, "_enviar", lambda tel, corpo, chave: (
        enviados.append((tel, corpo, chave)) or (True, "")))
    db.init()
    aviso.set_ligado(True)
    _avaliador()
    jid = _pipeline(monkeypatch)
    st = T._rodar(jid)
    assert len(enviados) == 1
    tel, corpo, _ = enviados[0]
    assert tel == "62999990000"
    n = len(db.resultado(jid, "entrega")["pendencias"])
    assert corpo == (f"João de Barro: laudo nº 120 – Marina (Sobrado, Jardim Vila Boa) {st}. "
                     f"{n} pendência(s). https://jdb.exemplo.com/#/job/{jid}")
    T._rodar(jid)  # já entregue: não avisa de novo
    assert len(enviados) == 1


def test_aviso_falho_ou_desligado_nao_derruba_job(monkeypatch):
    db.init()
    aviso.set_ligado(True)
    _avaliador()

    def explode(*a):
        raise RuntimeError("ponte fora")
    monkeypatch.setattr(aviso, "_enviar", explode)
    jid = _pipeline(monkeypatch)
    assert T._rodar(jid) in orquestrador.FINAIS
    nao = [e for e in db.eventos_desde(jid, 0) if e["nivel"] == "aviso_nao_enviado"]
    assert nao and "ponte fora" in nao[-1]["msg"]
    # sem instância conectada (motivo do wa_dono) → só o evento
    monkeypatch.setattr(aviso, "_enviar", lambda *a: (False, "desconectado"))
    assert aviso.avisar_fim(jid) is False
    assert "desconectado" in [e for e in db.eventos_desde(jid, 0)
                              if e["nivel"] == "aviso_nao_enviado"][-1]["msg"]
    aviso.set_ligado(False)
    n = len(db.eventos_desde(jid, 0))
    assert aviso.avisar_fim(jid) is False and len(db.eventos_desde(jid, 0)) == n
    aviso.set_ligado(True)


def test_config_liga_desliga_aviso(client, dono):
    h, _ = dono
    assert client.get(f"{API}/config", headers=h).json()["aviso_whatsapp"] is True
    client.put(f"{API}/config", json={"aviso_whatsapp": False}, headers=h)
    assert client.get(f"{API}/config", headers=h).json()["aviso_whatsapp"] is False
    client.put(f"{API}/config", json={"aviso_whatsapp": True}, headers=h)


# ------------------------------------------------------------------ Bloco D / C1
def test_reabrir_a_partir_da_extracao(client, dono, monkeypatch):
    h, _ = dono
    fila = []
    monkeypatch.setattr(orquestrador, "enfileirar", fila.append)
    jid = _novo(client, h)
    r = client.post(f"{API}/jobs/{jid}/reabrir", json={"etapa": "extracao"}, headers=h)
    assert r.status_code == 202, r.text
    assert fila == [jid]
    voltas = [e for e in db.eventos_desde(jid, 0) if e["nivel"] == "volta"]
    assert voltas[-1]["dados"] == {"etapa": "extracao", "correcao": True}


def test_escolha_manual_preservada_se_candidatos_iguais(client, dono, monkeypatch, tmp_path):
    from lovable.avaliacao import fonte_mercado
    h, _ = dono
    n, box = T._mock(monkeypatch)
    jid = T._job()
    box.append(jid)
    assert T._rodar(jid) == "PRONTO PARA REVISÃO"
    cands = db.candidatos(jid)
    validos = [r.n for r in cands if r.area_m2 and r.preco][:5]
    assert client.put(f"{API}/jobs/{jid}/referenciais", json={"escolhidos": validos},
                      headers=h).status_code == 200
    ia_sel = sum(v for k, v in n.items() if k.endswith("@selecao"))
    orquestrador.reabrir(jid, "pesquisa")        # mesma pesquisa -> mesmos candidatos
    assert T._rodar(jid) in orquestrador.FINAIS
    sel = db.resultado(jid, "selecao")
    assert sel["manual"] is True and {x["n"] for x in sel["refs"] if x["escolhido"]} == set(validos)
    assert sum(v for k, v in n.items() if k.endswith("@selecao")) == ia_sel
    # candidatos novos: roda a seleção automática e avisa que a escolha caiu
    dados = json.loads(T.FIX.read_text(encoding="utf-8"))
    dados[0]["link"] += "?novo=1"
    novo = tmp_path / "refs.json"
    novo.write_text(json.dumps(dados), encoding="utf-8")
    fonte_mercado.registrar(T._FonteOnline(novo))
    orquestrador.reabrir(jid, "pesquisa")
    assert T._rodar(jid) in orquestrador.FINAIS
    assert not db.resultado(jid, "selecao").get("manual")
    pend = [p["texto"] for p in db.resultado(jid, "entrega")["pendencias"]]
    assert any("escolha manual descartada (novos candidatos)" in p for p in pend), pend


def test_aviso_usa_telefone_avisos_e_avisa_proprio_numero(client, dono, monkeypatch):
    h, _ = dono
    enviados = []
    monkeypatch.setattr(aviso, "_enviar", lambda tel, corpo, chave: (
        enviados.append(tel) or (True, "")))
    monkeypatch.setattr(aviso, "_situacao_wa", lambda: {"conectado": True,
                                                        "numero": "5562999990000"})
    aviso.set_ligado(True)
    _avaliador("(62) 99999-0000")                        # = número conectado do dono
    st = client.get(f"{API}/aviso/status", headers=h).json()
    assert st["ok"] is False and st["motivo"] == "proprio_numero"
    assert "informe outro número" in st["mensagem"]
    db.set_setting("avaliador", json.dumps({"nome": "Alan", "telefone": "62999990000",
                                            "telefone_avisos": "62988887777"}))
    st = client.get(f"{API}/aviso/status", headers=h).json()
    assert st["ok"] is True and st["telefone"] == "62988887777"
    jid = T._job()
    aviso.avisar_fim(jid)
    assert enviados == ["62988887777"]


def test_editar_campo_valida_nome_data_e_observacao(client, dono):
    h, _ = dono
    jid = _novo(client, h)
    db.salvar_campos(jid, [Campo(nome="Cor da fachada", valor=None, origem="pendente")])
    vis = {"valor": "x", "origem": "vistoria", "fonte": "vistoria do avaliador em 16/10/2026"}
    u = f"{API}/jobs/{jid}/campos"
    assert client.put(f"{u}/campo_inventado", json=vis, headers=h).status_code == 400
    assert client.put(f"{u}/Cor da fachada", json=vis, headers=h).status_code == 200   # existente
    assert client.put(f"{u}/area_construida", json=vis, headers=h).status_code == 200  # conhecido
    assert client.put(f"{u}/Estado de conservação", json=vis, headers=h).status_code == 200
    ruim = {**vis, "fonte": "vistoria do avaliador em 31/02/2026"}
    assert client.put(f"{u}/area_construida", json=ruim, headers=h).status_code == 400
    assert client.put(f"{u}/area_construida", json={**vis, "fonte": "vistoria do avaliador em 2026-02-30"},
                      headers=h).status_code == 400
    longa = {**vis, "observacao": "x" * 301}
    assert client.put(f"{u}/area_construida", json=longa, headers=h).status_code == 422
    assert client.put(f"{u}/area_construida", json={**vis, "observacao": "x" * 300},
                      headers=h).status_code == 200


def test_reextracao_divergente_da_edicao_registra_divergencia():
    from lovable.avaliacao.agentes import extracao
    jid = T._job()
    db.evento(jid, "extracao", "edicao_manual", "x", dados={"campo": Campo(
        nome="area_construida", valor="200", origem="vistoria",
        fonte="vistoria do avaliador em 16/10/2026").model_dump(mode="json")})
    novos = [Campo(nome="area_construida", valor=364.0, origem="documento", fonte="docs/iptu.png"),
             Campo(nome="quadra", valor="50", origem="documento", fonte="docs/iptu.png")]
    divs = extracao.divergencias_manuais(jid, novos)
    assert len(divs) == 1 and "area_construida" in divs[0] and "200" in divs[0] and "364" in divs[0]
    igual = [Campo(nome="area_construida", valor="200", origem="documento", fonte="docs/iptu.png")]
    assert extracao.divergencias_manuais(jid, igual) == []


def test_detalhe_marca_dados_alterados_ate_recalcular(client, dono, monkeypatch):
    h, _ = dono
    jid = _pipeline(monkeypatch)
    assert T._rodar(jid) in orquestrador.FINAIS
    det = lambda: client.get(f"{API}/jobs/{jid}", headers=h).json()
    assert det()["dados_alterados"] is False
    vis = {"valor": "200", "origem": "vistoria", "fonte": "vistoria do avaliador em 16/10/2026"}
    assert client.put(f"{API}/jobs/{jid}/campos/area_construida", json=vis,
                      headers=h).status_code == 200
    assert det()["dados_alterados"] is True
    orquestrador.reabrir(jid, "calculo")
    assert T._rodar(jid) in orquestrador.FINAIS
    assert det()["dados_alterados"] is False
