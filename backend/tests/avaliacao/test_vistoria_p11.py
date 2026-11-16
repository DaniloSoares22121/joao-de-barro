"""ORDEM 067 / 067-A: a página da vistoria sai do P11 (a vistoria padrão do Alan, D-054).

Conta os itens por caso rodando o próprio JavaScript da página no Node (pula sem Node), confere as contas
(terreno, construção, prazo do ITCD), o "Mostrar só o que falta" e o envio de "Concluir vistoria" ao trabalho."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node") or (r"C:\Program Files\nodejs\node.exe" if Path(r"C:\Program Files\nodejs\node.exe").is_file() else None)


def _ctx(tipo, mod, fin, **mais):
    return {"imovel_tipo": tipo, "modalidade": mod, "finalidade": fin, "imovel_endereco": "Rua Fictícia 1, Qd. 3, Lt. 04",
            "bairro": "Setor Teste", "cidade": "Goiânia", "solicitante_nome": "Maria Fictícia", **mais}


def _rodar_js(c: dict, codigo: str):
    """Roda montarSecoes + o filtro "so" da página, igual ao navegador, e devolve o que o `codigo` imprimir."""
    from lovable.avaliacao import vistoria_p11 as V
    js = ("var C = " + json.dumps(c, ensure_ascii=False) + ";\n"
          "function fmt(n){ return Number(n).toFixed(2).replace('.', ','); }\n"
          "function areasTexto(){ return ''; }\n" + V.P11_JS + "\n"
          "function vale(so){ if (!so) return true; for (var k in so) { if (so[k].indexOf(C[k]) < 0) return false; } return true; }\n"
          "var SECOES = montarSecoes(C).filter(function(s){ return vale(s.so); }).map(function(s){ s.itens = s.itens.filter("
          "function(i){ return vale(i.so); }); return s; }).filter(function(s){ return s.itens.length; });\n" + codigo)
    r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


CASOS = {
    "casa_itcd": _ctx("Casa", "AM", "Justificar o valor na malha fiscal do ITCD"),
    "apartamento_ov": _ctx("Apartamento", "OV", "venda"),
    "galpao_am": _ctx("Galpão", "AM", "venda"),
    "lote_ov": _ctx("Lote", "OV", "venda"),
}


@pytest.mark.skipif(not NODE, reason="sem Node para rodar o JavaScript da página")
@pytest.mark.parametrize("nome", list(CASOS))
def test_itens_por_caso(nome):
    from lovable.avaliacao import vistoria_p11 as V
    c = V.caso("9119", CASOS[nome])
    r = _rodar_js(c, "var ids = []; SECOES.forEach(function(s){ s.itens.forEach(function(i){ ids.push(i.id); }); });"
                     "console.log(JSON.stringify({ids: ids, secoes: SECOES.map(function(s){ return s.t; })}));")
    ids = r["ids"]
    assert len(ids) == len(set(ids))
    print(f"\n{nome}: {len(ids)} itens em {len(r['secoes'])} etapas")
    if nome == "casa_itcd":
        assert {"b5", "b5e", "c1", "c2", "d1"} <= set(ids)       # hidrômetro, padrão de energia (Alan), ITCD
        assert ids.index("b5e") == ids.index("b5") + 1           # logo depois do hidrômetro
        assert "Conversa com Maria" in " ".join(r["secoes"])
    if nome == "apartamento_ov":
        assert "c8" in ids and "b5e" not in ids and "c1" not in ids
    if nome == "galpao_am":
        assert "b5e" in ids and "f1" not in ids
    if nome == "lote_ov":
        assert "b5e" not in ids and not any(i.startswith("f") for i in ids)


def test_dados_do_caso_sem_inventar():
    from lovable.avaliacao import vistoria_p11 as V
    c = V.caso("9119", _ctx("Casa", "AM", "ITCD", imovel_endereco="Rua XV 9, Qd. 59, Lt. 02, CEP 74000-000"))
    assert c["rua"] == "Rua XV 9" and c["quadraLote"] == "Qd. 59, Lt. 02" and c["cep"] == "74000-000"
    assert c["fin"] == "itcd" and c["tipo"] == "casa"
    vazio = V.caso("1", {})
    assert vazio["rua"] == "" and vazio["matricula"] == "" and vazio["terrenoDoc"] is None


def test_pagina_tem_so_o_que_falta_e_concluir():
    from lovable.avaliacao import vistoria_p11 as V
    h = V.pagina(V.caso("9119", CASOS["casa_itcd"]), "/api/avaliacao/vistoria/x/tok", "http://app/#/cliente/x")
    assert "Mostrar só o que falta" in h and "Mostrar todos" in h
    assert "Ir para o que falta" not in h                       # 067-A: esse botão não existe
    assert "Faltam " in h and "Mostrar o que falta" in h and "Concluir assim mesmo" in h
    assert "Vistoria enviada ao trabalho" in h and "Envio sozinho quando a internet voltar" in h
    assert "Copiar o texto" in h and "localStorage" in h


@pytest.mark.skipif(not NODE, reason="sem Node para rodar o JavaScript da página")
def test_contas():
    """As contas do P11: terreno pela média das frentes × laterais; construção; prazo de 30 dias do ITCD."""
    from lovable.avaliacao import vistoria_p11 as V
    h = V.pagina(V.caso("9119", CASOS["casa_itcd"]), "/x", "")
    corpo = h.split("function n(v)", 1)[1].split("var SO_FALTA", 1)[0]
    r = _rodar_js({**V.caso("9119", CASOS["casa_itcd"]), "terrenoIptu": 360.0, "construidaIptu": 120.0, "entrega": "2026-12-30"},
                  "var EST = {v: {e1: '12', e2: '12', e3: '30', e4: '30', f2: {comp: '10', larg: '8'}, f4: '6', c2: '2026-10-28'}};"
                  "function n(v)" + corpo + "console.log(JSON.stringify(contas()));")
    assert r["terreno"][0].startswith("Estimativa de campo do terreno: 360,00 m²")
    assert "86,00 m²" in r["casa"][0]                          # 10 × 8 + 6
    assert "27/11/2026" in r["prazo"][0] and r["prazo"][1] is True   # vence antes da entrega → alerta


def test_concluir_envia_ao_trabalho(tmp_path, monkeypatch):
    """POST da página (sem login, com o código do cliente): o texto e as marcações vão para a conversa."""
    from lovable.avaliacao import analise_visita
    analisados = []

    async def analisar(cid_, texto):                     # 072-C10: a análise com IA fica simulada (o teste não gasta)
        analisados.append(texto)
    monkeypatch.setattr(analise_visita, "analisar", analisar)
    from fastapi.testclient import TestClient
    from lovable.main import app
    from lovable.avaliacao import conversa as C, dados_cliente as DC
    cid = C.criar("")
    DC._gravar(cid, {"vistoria_token": "codigo-certo"})
    cli = TestClient(app)
    corpo = {"texto": "VISTORIA Nº 1 · Casa\n[x] Fachada", "marcas": {"m": {"b2": True}}, "feitos": 1, "total": 63}
    assert cli.post(f"/api/avaliacao/vistoria/{cid}/errado", json=corpo).status_code == 404
    assert cli.post(f"/api/avaliacao/vistoria/{cid}/codigo-certo", json=corpo).json() == {"ok": True}
    ctx = C.obter(cid)["contexto"]
    assert ctx["visita_feita"] is True and "Fachada" in ctx["checklist"] and ctx["vistoria_respostas"]["m"]["b2"]
    textos = [m["texto"] for m in C.mensagens(cid)]
    assert any("Recebi a vistoria (1 de 63 itens feitos)" in t for t in textos)
    assert analisados and "Fachada" in analisados[0]          # o relato passou pela análise do João
