import asyncio
import json
import re
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from lovable.avaliacao import db, docx_builder, planilha, fonte_mercado, ia, nomes, orquestrador, pdf  # noqa: F401
from lovable.avaliacao.agentes import extracao, pesquisa, redacao, revisor, selecao, triagem


_REFS: list = [None]   # 112: os anúncios do teste (o avaliador traz pela extensão; não há mais busca nos portais)
from lovable.avaliacao.modelos import Referencial, Trabalho

from .textos_ok import SECOES_OV
from tests.avaliacao.conftest import numero_livre

FIX = Path(__file__).parent / "fixtures" / "ov120.json"
NOME = "120 - Marina - Sobrado - Jardim Vila Boa - Goiânia"


class _FonteOnline(fonte_mercado.FonteFixture):
    def online(self) -> bool:
        return True


def _img(p: Path, cor, tam=(1200, 800)):
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", tam, cor).save(p)


def _mapa(pasta: Path) -> None:
    """165: o mapa da localização hoje é só o maps.png, com conteúdo (o cinza liso conta como "mapa em branco")."""
    import random
    rnd = random.Random(165)
    im = Image.new("RGB", (1000, 700))
    im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(1000 * 700)])
    pasta.mkdir(parents=True, exist_ok=True)
    im.save(pasta / "maps.png")


def _job(com_maps=True) -> str:
    db.init()
    jid = db.criar_job(Trabalho(
        id="", numero=numero_livre(120), modalidade="OV", finalidade="Venda", cliente="Marina",
        tipo="Sobrado", bairro="Jardim Vila Boa", cidade="Goiânia",
        pin_maps="https://maps.app.goo.gl/cipo1JeoaUS5EEq46",
        data_base=date(2026, 10, 16), data_vistoria=date(2026, 10, 16)))
    pasta = db.pasta(jid)
    for i, cor in enumerate(["green", "gray", "blue", "white", "red"], start=1):
        _img(pasta / "fotos" / f"f{i}.jpg", cor)
        db.adicionar_arquivo(jid, f"f{i}.jpg", "foto", f"fotos/f{i}.jpg")
    _img(pasta / "docs" / "iptu.png", "white", (800, 1100))
    db.adicionar_arquivo(jid, "iptu.png", "", "docs/iptu.png")
    if com_maps:                       # 165: o mapa da localização hoje é só o maps.png (com conteúdo)
        _img(pasta / "maps_satelite.png", "black", (1000, 700))
        _mapa(pasta)
    refs = json.loads(Path(_REFS[0] or FIX).read_text(encoding="utf-8"))
    db.salvar_candidatos(jid, [Referencial.model_validate({**r, "decisao": "entra", "escolhido": True,
                                                           "fonte_coleta": "avaliador"}) for r in refs])
    return jid


def _textos() -> dict:
    s = {k: f"Texto da seção {k} do laudo." for k in redacao.CHAVES["OV"]}
    s.update(SECOES_OV)
    return {"secoes": s, "legendas": {}, "descricao_amostras": {}}


def _mock(monkeypatch, refs_json=FIX, revisao=None, bloqueado=False):
    """IA mockada por esquema; devolve o contador de chamadas por esquema."""
    n = Counter()
    fonte_mercado.registrar(_FonteOnline(refs_json))
    _REFS[0] = refs_json
    # 112: o avaliador confirma referenciais, unitário, faixa e área na tela (aqui, já confirmado)
    real_sel = orquestrador._Pipeline._sel
    # 165: o unitário é o que o avaliador confirma na tela (limite inferior do OV 120)
    def _sel_confirmada(self):
        s0 = real_sel(self)
        from decimal import Decimal as _D
        return s0.model_copy(update={            # unitário fixo só com a decisão escrita do avaliador, para esta amostra
            "confirmado": True, "unitario_adotado": s0.unitario_adotado or _D("2735.85"),
            "justificativa_unitario": s0.justificativa_unitario or "limite inferior",
            "amostra": selecao.assinatura_amostra(s0.refs)})
    monkeypatch.setattr(orquestrador._Pipeline, "_sel", _sel_confirmada)
    # o OV 120 usa o limite inferior (2.735,85) como unitário confirmado pelo avaliador; aqui (sem a tela) ele vale
    # para todas as etapas que conferem o unitário (cálculo, revisor de matemática, coerência)
    def _unit_ov120(sel):
        from decimal import Decimal as _D
        if sel.unitario_adotado is not None:
            return sel.unitario_adotado, ""
        return (_D("2735.85") if len([x for x in sel.refs if x.escolhido]) >= 5 else None), ""
    monkeypatch.setattr(selecao, "unitario_valido", _unit_ov120)
    monkeypatch.setattr(orquestrador, "escolha_area", lambda j: {"base": "construida", "campo": "area_construida"})

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo="", **_kw):
        n[esquema.__name__ + "@" + esquema.__module__.rsplit(".", 1)[-1]] += 1
        if esquema is triagem.Triagem:
            return esquema(quadro={}, bloqueado=bloqueado, motivo="sem documentos")
        if esquema is extracao._RespostaIA:
            return esquema.model_validate({
                "campos": [
                    {"nome": "area_construida", "valor": 364.0, "unidade": "m2",
                     "origem": "documento", "fonte": "docs/iptu.png"},
                    {"nome": "endereco", "valor": "Rua das Acácias, Quadra 12, Lote 07",
                     "origem": "documento", "fonte": "docs/iptu.png"},
                    {"nome": "quadra", "valor": "50", "origem": "documento",
                     "fonte": "docs/iptu.png"},
                    {"nome": "lote", "valor": "29", "origem": "documento",
                     "fonte": "docs/iptu.png"},
                    # 165: o laudo de hoje exige área do terreno, matrícula e cartório
                    {"nome": "area_terreno", "valor": 360.0, "unidade": "m2", "origem": "documento",
                     "fonte": "docs/iptu.png"},
                    {"nome": "matricula", "valor": "2025", "origem": "documento", "fonte": "docs/iptu.png"},
                    {"nome": "padrao_construtivo", "valor": "simples", "origem": "vistoria",
                     "fonte": "fotos/f1.jpg"},
                    # vistoria do OV 120 (o caso-modelo): fatos que também estão no P8
                    {"nome": "observacoes_vistoria", "origem": "vistoria", "fonte": "fotos/f2.jpg",
                     "valor": "garagem sobre pilares com 4 vagas; janelas de metalon; "
                              "idade aparente de 30 anos"}],
                "quadras_lotes": [{"arquivo": "docs/iptu.png", "papel": "iptu",
                                   "quadra": "50", "lote": "29"}],
                "fachada_caixa": [100, 50, 1100, 760],
                "fotos": [{"arquivo": f"fotos/f{i}.jpg", "legenda": f"Ambiente {i}",
                           "ordem": i} for i in range(1, 6)],
                "documentos": [{"arquivo": "docs/iptu.png", "rotulo_curto": "IPTU 2025",
                                "rotulo_completo": "Notificação do IPTU 2025"}]})
        if esquema is selecao._RespostaIA:
            cands = db.candidatos(_box[0])
            return esquema.model_validate({
                "decisoes": [{"n": c.n, "escolhido": True, "justificativa": "compatível"}
                             for c in cands],
                "unitario_adotado": "2735.85" if len(cands) >= 5 else None,
                "justificativa_unitario": "limite inferior"})
        if esquema is redacao.Textos:
            return esquema.model_validate(_textos())
        if esquema is revisor.Revisao:
            return revisao or esquema(aprovado=True)
        raise AssertionError(esquema)

    _box: list = []
    monkeypatch.setattr(ia, "perguntar", fake)

    def converter(docx: Path, timeout=0) -> Path:
        """PDF fake com os parágrafos de valores do Word montado."""
        with zipfile.ZipFile(docx) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        pars = [" ".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", p))
                for p in re.findall(r"<w:p[ >].*?</w:p>", xml)]
        out = Path(docx).with_suffix(".pdf")
        with pymupdf.open() as d:       # 165: o texto INTEIRO do Word numa página (a conferência procura extenso etc.)
            pg, y = d.new_page(), 10
            for t in [p for p in pars if p.strip()]:
                for i in range(0, len(t), 300):
                    pg.insert_text((5, y), t[i:i + 300], fontsize=1)
                    y += 1.1
            d.save(out)
        return out
    monkeypatch.setattr(pdf, "converter", converter)
    return n, _box


def _rodar(jid):
    return asyncio.run(orquestrador.executar(jid))


def test_ponta_a_ponta_ov120(monkeypatch):
    n, box = _mock(monkeypatch)
    jid = _job()
    box.append(jid)
    st = _rodar(jid)
    ent = db.pasta(jid) / "entrega"
    assert st == "PRONTO PARA REVISÃO", (ent / "pendencias.md").read_text(encoding="utf-8")
    for ext in ("docx", "pdf", "xlsx"):
        assert (ent / f"{NOME}.{ext}").exists()
    assert (ent / "pendencias.md").exists()
    assert db.job(jid)["etapa"] == "entrega" and db.job(jid)["status"] == st
    with pymupdf.open(ent / f"{NOME}.pdf") as d:
        txt = " ".join(p.get_text() for p in d)
    assert "R$ 996.000,00" in txt
    # já finalizado: não refaz nada
    antes = sum(n.values())
    assert _rodar(jid) == st and sum(n.values()) == antes


def test_retoma_sem_refazer_ia(monkeypatch):
    n, box = _mock(monkeypatch)
    jid = _job()
    box.append(jid)
    real = orquestrador._Pipeline._calculo
    falhar = {"sim": True}

    async def calc(self):
        if falhar["sim"]:
            raise asyncio.CancelledError  # processo interrompido
        return await real(self)
    monkeypatch.setattr(orquestrador._Pipeline, "_calculo", calc)
    with pytest.raises(asyncio.CancelledError):
        _rodar(jid)
    assert db.resultado(jid, "selecao") is not None
    assert db.resultado(jid, "calculo") is None
    antes = dict(n)                       # 165: a extração hoje lê em 2 chamadas; o que importa é não repetir na retomada
    falhar["sim"] = False
    assert _rodar(jid) == "PRONTO PARA REVISÃO"
    assert n["Triagem@triagem"] == antes["Triagem@triagem"] == 1
    assert n["_RespostaIA@extracao"] == antes["_RespostaIA@extracao"]
    assert n["_RespostaIA@selecao"] == antes["_RespostaIA@selecao"] == 1


def test_menos_de_cinco(monkeypatch, tmp_path):
    refs = json.loads(FIX.read_text(encoding="utf-8"))[:3]
    p = tmp_path / "tres.json"
    p.write_text(json.dumps(refs, ensure_ascii=False), encoding="utf-8")
    n, box = _mock(monkeypatch, refs_json=p)
    jid = _job()
    box.append(jid)
    # ORDEM 003 (lista de candidatos, D-021): com menos de 5 escolhidos o pipeline NÃO segue
    # sozinho para um laudo PARCIAL — ele pausa na pesquisa (AGUARDANDO_AVALIADOR) até o
    # avaliador marcar pelo menos 5 (a tela recusa "Continuar" com menos; completar com menos
    # semelhantes ou referencial manual, justificando). Antes: laudo PARCIAL com aviso.
    assert _rodar(jid) == orquestrador.AGUARDANDO
    assert db.job(jid)["etapa"] == "pesquisa"
    msgs = [e["msg"] for e in db.eventos_desde(jid, 0)]
    assert any("no mínimo 5" in m for m in msgs)
    assert db.resultado(jid, "entrega") is None


def test_revisor_reprova_duas_vezes(monkeypatch):
    rev = revisor.Revisao(aprovado=False, problemas=[revisor.Problema(
        camada="redacao", etapa_responsavel="redacao", descricao="texto da seção 9 fraco")])
    n, box = _mock(monkeypatch, revisao=rev)
    jid = _job()
    box.append(jid)
    assert _rodar(jid) == "PARCIAL — PENDÊNCIAS"
    assert n["Textos@redacao"] == orquestrador.MAX_REVISOES      # 165: no máximo 2 rodadas de revisão (ORDEM 010)
    assert n["Revisao@revisor"] == orquestrador.MAX_REVISOES
    md = (db.pasta(jid) / "entrega" / "pendencias.md").read_text(encoding="utf-8")
    assert "seção 9 fraco" in md


def test_sem_maps_parcial(monkeypatch):
    n, box = _mock(monkeypatch)
    jid = _job(com_maps=False)
    box.append(jid)
    assert _rodar(jid) == "PARCIAL — PENDÊNCIAS"
    md = (db.pasta(jid) / "entrega" / "pendencias.md").read_text(encoding="utf-8")
    assert "imagem de localização ausente" in md


def test_sem_pdf_parcial(monkeypatch):
    n, box = _mock(monkeypatch)

    def sem_soffice(docx, timeout=0):
        raise RuntimeError("LibreOffice (soffice) não encontrado")
    monkeypatch.setattr(pdf, "converter", sem_soffice)
    jid = _job()
    box.append(jid)
    assert _rodar(jid) == "PARCIAL — PENDÊNCIAS"
    ent = db.pasta(jid) / "entrega"
    assert "LibreOffice ausente" in (ent / "pendencias.md").read_text(encoding="utf-8")
    assert (ent / f"{NOME}.docx").exists() and not (ent / f"{NOME}.pdf").exists()


def test_triagem_bloqueada(monkeypatch):
    n, box = _mock(monkeypatch, bloqueado=True)
    jid = _job()
    box.append(jid)
    assert _rodar(jid) == "BLOQUEADO"
    assert n["_RespostaIA@extracao"] == 0


def test_sem_coletor_nao_espera(monkeypatch):
    """112: sem busca nos portais, o programa do PC desligado não segura o trabalho (nada de "aguardando o Coletor");
    com a imagem de localização que já existe, segue até o fim."""
    n, box = _mock(monkeypatch)
    fonte_mercado.registrar(fonte_mercado.FonteFixture(FIX))  # online() = False
    jid = _job()
    box.append(jid)
    etapas = []

    async def sleep(s):
        etapas.append(db.job(jid)["etapa"])
    monkeypatch.setattr(orquestrador, "_sleep", sleep)
    assert _rodar(jid) in orquestrador.FINAIS               # chega ao fim (não fica esperando o programa do PC)
    assert "aguardando_coletor" not in etapas and db.resultado(jid, "entrega") is not None


def test_fila_retoma_nao_finalizados(monkeypatch):
    n, box = _mock(monkeypatch)
    jid = _job()
    box.append(jid)
    db.set_etapa(jid, "extracao", "executando")   # já iniciado: o reinício retoma
    feito = _job()
    db.set_etapa(feito, "entrega", "PRONTO PARA REVISÃO")
    nao_iniciado = _job()   # criado, ainda recebendo arquivos: o reinício NÃO pode iniciar
    rodados = []

    async def fake_exec(j):
        rodados.append(j)
        return "PRONTO PARA REVISÃO"
    monkeypatch.setattr(orquestrador, "executar", fake_exec)

    async def main():
        monkeypatch.setattr(orquestrador, "_worker", None)
        w = orquestrador.iniciar_fila()
        assert orquestrador.iniciar_fila() is w
        await orquestrador._fila.join()
        w.cancel()
    asyncio.run(main())
    assert jid in rodados and feito not in rodados
    assert nao_iniciado not in rodados


def test_revisor_reprova_sem_problema_nao_fica_pronto(monkeypatch):
    n, box = _mock(monkeypatch, revisao=revisor.Revisao(aprovado=False))
    jid = _job()
    box.append(jid)
    assert _rodar(jid) == "PARCIAL — PENDÊNCIAS"
    md = (db.pasta(jid) / "entrega" / "pendencias.md").read_text(encoding="utf-8")
    assert "sem apontar problema" in md


def _revisoes(monkeypatch, seq):
    """Revisor mockado: devolve as revisões de `seq` em ordem (a última se repete)."""
    real = ia.perguntar
    cont = {"i": 0}

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo="", **_kw):
        if esquema is revisor.Revisao:
            i = min(cont["i"], len(seq) - 1)
            cont["i"] += 1
            r = seq[i]
            return r() if callable(r) else r
        return await real(sistema, prompt, esquema, arquivos, cwd, modelo)
    monkeypatch.setattr(ia, "perguntar", fake)
    return cont


_REPROVA_REDACAO = revisor.Revisao(aprovado=False, problemas=[revisor.Problema(
    camada="redacao", etapa_responsavel="redacao", descricao="refazer a seção 9")])


def test_retoma_nao_reaproveita_revisao_velha(monkeypatch):
    n, box = _mock(monkeypatch)
    cont = _revisoes(monkeypatch, [_REPROVA_REDACAO, revisor.Revisao(aprovado=True)])
    jid = _job()
    box.append(jid)
    real = orquestrador._Pipeline._montagem
    montagens = {"n": 0}

    async def mont(self):
        montagens["n"] += 1
        if montagens["n"] == 2:  # cai na montagem da volta 1
            raise asyncio.CancelledError
        return await real(self)
    monkeypatch.setattr(orquestrador._Pipeline, "_montagem", mont)
    with pytest.raises(asyncio.CancelledError):
        _rodar(jid)
    assert n["Textos@redacao"] == 2 and cont["i"] == 1
    assert _rodar(jid) == "PRONTO PARA REVISÃO"
    assert montagens["n"] == 3          # montagem refeita na retomada
    assert cont["i"] == 2               # revisão refeita (aprovou)
    assert n["Textos@redacao"] == 2     # a reprovação velha não foi reaplicada


def test_falha_inesperada_e_terminal(monkeypatch):
    n, box = _mock(monkeypatch)

    def quebra(*a, **k):
        raise ValueError("planilha corrompida")
    monkeypatch.setattr(planilha, "gerar", quebra)
    jid = _job()
    box.append(jid)
    assert _rodar(jid) == "PARCIAL — PENDÊNCIAS"
    # 165: a falha vira pendência técnica em linguagem simples; o detalhe ("planilha corrompida") fica no registro
    with db._conn() as c:
        ev = c.execute("SELECT msg, dados_json FROM av_events WHERE job=? AND etapa='montagem' AND nivel='erro'",
                       (jid,)).fetchall()
    assert any("montagem" in m.lower() and "planilha corrompida" in (d or "") for m, d in ev), ev
    j = db.job(jid)
    assert j["etapa"] == "entrega" and j["status"] == "PARCIAL — PENDÊNCIAS"


def test_aviso_corrigido_na_volta_nao_rebaixa(monkeypatch):
    n, box = _mock(monkeypatch)
    jid = _job(com_maps=False)
    box.append(jid)

    def reprova_e_poe_mapa():
        _mapa(db.pasta(jid))                                      # 165: o mapa de hoje (maps.png com conteúdo)
        return revisor.Revisao(aprovado=False, problemas=[revisor.Problema(
            camada="visual", etapa_responsavel="montagem", descricao="sem mapa")])
    _revisoes(monkeypatch, [reprova_e_poe_mapa, revisor.Revisao(aprovado=True)])
    st = _rodar(jid)
    md = (db.pasta(jid) / "entrega" / "pendencias.md").read_text(encoding="utf-8")
    assert st == "PRONTO PARA REVISÃO", md
    assert "localização ausente" not in md


def test_voltas_de_conteudo_proibido_persistem(monkeypatch):
    n, box = _mock(monkeypatch)
    jid = _job()
    box.append(jid)
    for _ in range(orquestrador.MAX_VOLTAS):
        db.evento(jid, "orquestrador", "volta", "volta anterior ao reinício")

    def proibido(*a, **k):
        raise docx_builder.ConteudoProibido("PTAM em OV")
    monkeypatch.setattr(docx_builder, "montar", proibido)
    assert _rodar(jid) == "PARCIAL — PENDÊNCIAS"
    assert n["Textos@redacao"] == 1


def test_ia_morta_no_encerramento_fica_retomavel(monkeypatch):
    n, box = _mock(monkeypatch)
    jid = _job()
    box.append(jid)
    real = ia.perguntar

    async def fake(sistema, prompt, esquema, **kw):
        if esquema is extracao._RespostaIA:
            raise ia.IAFalhou("resposta inválida após 3 tentativas: Command failed with "
                              "exit code 143 (terminated)")
        return await real(sistema, prompt, esquema, **kw)
    monkeypatch.setattr(ia, "perguntar", fake)
    assert _rodar(jid) == orquestrador.REENFILEIRAR  # sem encerramento: volta à fila
    assert db.resultado(jid, "entrega") is None
    assert db.job(jid)["status"] not in orquestrador.FINAIS


def test_encerrando_qualquer_falha_de_ia_fica_retomavel(monkeypatch):
    n, box = _mock(monkeypatch)
    jid = _job()
    box.append(jid)

    async def fake(*a, **kw):
        raise ia.IAFalhou("cota")
    monkeypatch.setattr(ia, "perguntar", fake)
    monkeypatch.setattr(orquestrador, "_encerrando", True)
    with pytest.raises(asyncio.CancelledError):
        _rodar(jid)
    assert db.resultado(jid, "entrega") is None


def test_planilha_origem_da_area(monkeypatch):
    import openpyxl
    n, box = _mock(monkeypatch)
    jid = _job()
    box.append(jid)
    _rodar(jid)
    xlsx = db.pasta(jid) / f"{NOME}.xlsx"
    im = openpyxl.load_workbook(xlsx)["Imovel"]
    assert im["E9"].value == "Comprovado"
    assert im["E2"].value == "Informado"


def test_fila_sobrevive_a_interrupcao_e_limita(monkeypatch):
    n, box = _mock(monkeypatch)
    j1, j2 = _job(), _job()
    box.append(j2)
    real = ia.perguntar
    mortes = []

    async def fake(sistema, prompt, esquema, arquivos=[], cwd=None, modelo="", **_kw):
        if esquema is extracao._RespostaIA and cwd and j1 in str(cwd):
            mortes.append(1)
            raise ia.IAFalhou("Command failed with exit code 143 (terminated)")
        return await real(sistema, prompt, esquema, arquivos=arquivos, cwd=cwd, modelo=modelo)
    monkeypatch.setattr(ia, "perguntar", fake)
    monkeypatch.setattr(orquestrador, "_fila", None)
    monkeypatch.setattr(orquestrador, "_worker", None)

    async def main():
        orquestrador._fila = asyncio.Queue()
        orquestrador._ativos.clear()
        w = asyncio.get_running_loop().create_task(orquestrador._trabalhar())
        orquestrador.enfileirar(j1)
        orquestrador.enfileirar(j2)
        await asyncio.wait_for(orquestrador._fila.join(), 60)
        vivo = not w.done()
        w.cancel()
        return vivo
    assert asyncio.run(main())
    # ORDEM 002/003: o pipeline PAUSA para o avaliador confirmar referenciais/valor
    # (AGUARDANDO_AVALIADOR) — o j2 sai da fila parado na pausa, sem entrega; o que o teste
    # garante (a fila sobrevive à morte do j1 e processa o j2) continua valendo.
    assert db.job(j2)["status"] in orquestrador.FINAIS | {orquestrador.AGUARDANDO}
    fim = db.resultado(j1, "entrega")
    assert len(mortes) == 3
    assert fim["status"] == orquestrador.PARCIAL
    assert any("IA interrompida repetidamente" in p["texto"] for p in fim["pendencias"])


def test_maps_falha_nao_aborta_pesquisa(monkeypatch):
    n, box = _mock(monkeypatch)

    class _FonteMaps(_FonteOnline):
        async def capturar_maps(self, job_id, t):
            raise RuntimeError("pane")
    fonte_mercado.registrar(_FonteMaps(FIX))
    jid = _job(com_maps=False)
    box.append(jid)
    _rodar(jid)
    assert db.resultado(jid, "pesquisa")["candidatos"]
    avisos = [e["msg"] for e in db.eventos_desde(jid, 0) if e["nivel"] == "aviso"]
    sem_loc = [a for a in avisos if a.startswith(docx_builder.SEM_LOCALIZACAO)]
    assert sem_loc and orquestrador._grave(sem_loc[-1])


def test_redacao_abaixo_do_minimo_provoca_volta(monkeypatch):
    n, box = _mock(monkeypatch)
    orig = redacao.deficiencias
    chamadas = {"i": 0}

    def defic(*a, **k):
        chamadas["i"] += 1
        return ["5 (metodologia): curta"] if chamadas["i"] == 1 else orig(*a, **k)
    monkeypatch.setattr(redacao, "deficiencias", defic)
    jid = _job()
    box.append(jid)
    assert _rodar(jid) == "PRONTO PARA REVISÃO"
    assert n["Textos@redacao"] == 2
    voltas = orquestrador._eventos(jid, "volta")
    assert voltas and "metodologia" in voltas[0]["msg"]


def test_redacao_sempre_curta_fica_parcial(monkeypatch):
    n, box = _mock(monkeypatch)
    monkeypatch.setattr(redacao, "deficiencias", lambda *a, **k: ["5 (metodologia): curta"])
    jid = _job()
    box.append(jid)
    assert _rodar(jid) == "PARCIAL — PENDÊNCIAS"
    assert n["Textos@redacao"] == orquestrador.MAX_VOLTAS + 1
    pend = (db.pasta(jid) / "entrega" / "pendencias.md").read_text(encoding="utf-8")
    assert "[impeditiva] redacao: seções sem texto: 5 (metodologia)" in pend
