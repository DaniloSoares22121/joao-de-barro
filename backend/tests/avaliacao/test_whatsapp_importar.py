"""ORDEM 061: importar a conversa exportada do WhatsApp (zip com mídias) — leitura do .txt (Android e
iPhone), segurança do zip, formatos aceitos/recusados e o processamento em segundo plano (com a
transcrição e a leitura da IA simuladas: o teste não gasta nada)."""
import asyncio
import json
import zipfile

from lovable.avaliacao import conversa as C
from lovable.avaliacao import rotas_whatsapp as R
from lovable.avaliacao import whatsapp as W
from lovable.avaliacao.rotas_conversa import _DocLido

ANDROID = """14/11/2026 09:00 - As mensagens e as ligações são protegidas com a criptografia de ponta a ponta.
14/11/2026 09:01 - Maria Teste: Bom dia!
14/11/2026 09:01 - Maria Teste: PTT-20261114-WA0001.opus (arquivo anexado)
14/11/2026 09:03 - Alan: Me conta do imóvel
segunda linha da mesma mensagem
14/11/2026 09:05 - Maria Teste: IMG-20261114-WA0004.jpg (arquivo anexado)
"""
IOS = """[14/11/2026, 09:00:00] Maria Teste: ‎As mensagens e as ligações são protegidas com a criptografia de ponta a ponta.
[14/11/2026, 09:01:02] Maria Teste: Bom dia!
[14/11/2026, 09:01:10] Maria Teste: \u200e<anexado: 00000003-AUDIO-2026-11-14-09-01-10.opus>
[14/11/2026, 09:03:00] Alan: Me conta: tem edícula?
"""


def test_le_android_com_anexos_e_continuacao():
    m = W.ler_conversa(ANDROID)
    assert [x.autor for x in m] == ["", "Maria Teste", "Maria Teste", "Alan", "Maria Teste"]
    assert m[2].anexo == "PTT-20261114-WA0001.opus" and m[2].texto == ""
    assert m[3].texto == "Me conta do imóvel\nsegunda linha da mesma mensagem"
    assert m[1].quando.strftime("%d/%m/%Y %H:%M") == "14/11/2026 09:01"
    assert W.nome_do_contato("Conversa do WhatsApp com Maria Teste.txt", m) == "Maria Teste"


def test_le_iphone():
    m = W.ler_conversa(IOS)
    assert [x.autor for x in m] == ["", "Maria Teste", "Maria Teste", "Alan"]     # aviso do sistema sem autor
    assert m[2].anexo == "00000003-AUDIO-2026-11-14-09-01-10.opus"
    assert m[3].texto == "Me conta: tem edícula?"                    # dois-pontos no texto não confunde o autor
    assert W.nome_do_contato("_chat.txt", m) == "Maria Teste"


def test_formatos():
    for n, t in (("a.opus", "audio"), ("a.M4A", "audio"), ("a.amr", "audio"), ("f.HEIC", "foto"), ("f.webp", "foto"),
                 ("d.pdf", "documento"), ("d.xlsx", "documento"), ("d.csv", "documento"), ("v.3gp", "video"),
                 ("c.vcf", "contato"), ("x.zip", "zip"), ("c.txt", "texto"), ("p.exe", "recusado"), ("s.ps1", "recusado"),
                 ("a.apk", "recusado"), ("b.bat", "recusado"), ("j.js", "recusado"), ("z.xyz", "outro")):
        assert W.tipo_de(n) == t, n


def test_zip_seguro(tmp_path):
    z = tmp_path / "x.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../../fora.txt", "x")
        f.writestr("/abs.txt", "x")
        f.writestr("C:/Windows/abs2.txt", "x")
        f.writestr("__MACOSX/._lixo", "x")
        f.writestr("pasta/ok.txt", "x")
    dest = tmp_path / "dest"
    saidos = W.abrir_zip(z, dest)
    assert [p.name for p in saidos] == ["ok.txt"]
    assert not (tmp_path / "fora.txt").exists() and all(p.resolve().is_relative_to(dest.resolve()) for p in saidos)


def test_zip_com_arquivos_demais(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "LIMITE_ARQUIVOS_ZIP", 3)
    z = tmp_path / "x.zip"
    with zipfile.ZipFile(z, "w") as f:
        for i in range(4):
            f.writestr(f"{i}.txt", "x")
    try:
        W.abrir_zip(z, tmp_path / "d")
        assert False, "devia recusar"
    except W.ZipInvalido:
        pass


def test_vcf():
    assert W.ler_vcf("BEGIN:VCARD\nFN:Maria Teste\nTEL;type=CELL:+55 62 99999-0000\nEND:VCARD") == ("Maria Teste", "+5562999990000")


def test_processar_importacao(monkeypatch):
    cid = C.criar("")
    imp = "20261114-090000"
    pasta = R._pasta_imp(cid, imp)
    pasta.mkdir(parents=True)
    with zipfile.ZipFile(pasta / "Conversa do WhatsApp com Maria Teste.zip", "w") as f:
        f.writestr("Conversa do WhatsApp com Maria Teste.txt", ANDROID)
        f.writestr("PTT-20261114-WA0001.opus", b"audio")
        f.writestr("IMG-20261114-WA0004.jpg", b"foto" * 100)
        f.writestr("IMG-20261114-WA0005.jpg", b"doc" * 100)
        f.writestr("STK-1.webp", b"x")                                  # figurinha: ignorada
        f.writestr("Maria Teste.vcf", "BEGIN:VCARD\nFN:Maria Teste\nTEL:62 99999-0000\nEND:VCARD")
        f.writestr("programa.exe", b"MZ")
    monkeypatch.setattr(R.transcricao, "disponivel", lambda: True)
    monkeypatch.setattr(R.transcricao, "transcrever", lambda p: ("preciso do laudo para o inventário", 10.0, 5.0))

    async def ler(cid_, rel, triagem):                                    # IA simulada
        return _DocLido(tipo_documento="Matrícula") if "WA0005" in rel else _DocLido()
    monkeypatch.setattr(R, "_ler_com_ia", ler)
    resumos = []

    async def resumir(cid_):                                              # ORDEM 062 simulada (sem IA)
        resumos.append(cid_)
    from lovable.avaliacao import entendimento
    monkeypatch.setattr(entendimento, "resumir", resumir)
    asyncio.run(R.processar(cid, imp))
    assert resumos == [cid]                                               # depois de ler tudo, o resumo
    conv = json.loads((pasta / "conversa.json").read_text(encoding="utf-8"))
    meta = conv["meta"]
    assert meta["contato"] == "Maria Teste" and meta["mensagens"] == 4 and meta["transcritos"] == 1
    assert meta["fotos"] == 1 and meta["documentos"] == ["Matrícula"]
    assert meta["recusados"] == ["programa.exe"]
    audio = next(m for m in conv["mensagens"] if m["anexo"].endswith(".opus"))
    assert audio["transcricao"] == "preciso do laudo para o inventário"
    base = C.pasta(cid)
    assert (base / "foto_cliente" / "IMG-20261114-WA0004.jpg").is_file()        # foto do cliente, não de vistoria
    assert (base / "documento" / "IMG-20261114-WA0005.jpg").is_file()           # documento fotografado
    assert not (base / "foto").exists()
    assert not any(p.suffix == ".exe" for p in base.rglob("*"))
    ctx = C.obter(cid)["contexto"]
    assert ctx.get("solicitante_telefone") == "62999990000"
    card = [m for m in C.mensagens(cid) if m["tipo"] == "importacao"][-1]
    assert card["texto"] == "Li a conversa com Maria Teste: 4 mensagens, 1 áudio transcrito, 1 foto, matrícula."
    assert R.status(cid)["estado"] == "pronto"


def test_069_a8_segundo_envio_durante_a_leitura_entra_na_fila(monkeypatch):
    """Volta 1 do 122: 31 fotos em dois envios (17 + 14); o 2º chegou enquanto o 1º estava "Lendo…" e
    era recusado. Agora entra na fila e é lido logo depois."""
    from fastapi.testclient import TestClient
    from lovable.main import app
    cid = C.criar("")
    lidos = []

    async def processar_falso(cid_, imp):
        lidos.append(sorted(p.name for p in R._pasta_imp(cid_, imp).iterdir()))
        R._status(cid_, estado="pronto", importacao=imp, texto="")
    monkeypatch.setattr(R, "processar", processar_falso)
    monkeypatch.setattr(R, "_iniciar", lambda c, i: None)       # o 1º fica "lendo"
    app.dependency_overrides[R._dono] = lambda: {}
    try:
        cli = TestClient(app)
        um = [("arquivos", (f"IMG_{i}.jpg", b"foto" * 50, "image/jpeg")) for i in range(17)]
        dois = [("arquivos", (f"IMG_b{i}.jpg", b"foto" * 50, "image/jpeg")) for i in range(14)]
        assert cli.post(f"/api/avaliacao/clientes/{cid}/importar", files=um).status_code == 200
        assert R.status(cid) is not None
        R._rodando[cid] = type("Lendo", (), {"done": lambda self: False})()   # a leitura em andamento
        r2 = cli.post(f"/api/avaliacao/clientes/{cid}/importar", files=dois)
        assert r2.status_code == 200
        assert any("Recebi mais 14 fotos. Leio assim que terminar os primeiros." in m["texto"] for m in C.mensagens(cid))
        fila = R._fila(cid)
        assert len(fila) == 1
        primeiro = json.loads(R.db.setting(f"wpp:{cid}"))["importacao"]
        asyncio.run(R._rodar(cid, primeiro))                      # o 1º termina → o 2º é lido em seguida
        assert [len(x) for x in lidos] == [17, 14] and R._fila(cid) == []
    finally:
        app.dependency_overrides.clear()
        R._rodando.pop(cid, None)


def test_072_c9_fotos_do_avaliador_depois_da_visita_sao_de_vistoria(monkeypatch):
    async def ler(cid_, rel, triagem):
        return _DocLido()
    monkeypatch.setattr(R, "_ler_com_ia", ler)
    from lovable.avaliacao import entendimento

    async def resumir(cid_):
        return None
    monkeypatch.setattr(entendimento, "resumir", resumir)
    # visita feita: as fotos que o avaliador manda (sem conversa exportada) vão para as fotos da vistoria
    cid = C.criar("")
    C.juntar_contexto(cid, {"visita_feita": True})
    imp = "20261114-200000"
    pasta = R._pasta_imp(cid, imp)
    pasta.mkdir(parents=True)
    for i in range(3):
        (pasta / f"IMG_{i}.jpg").write_bytes(b"foto" * 100)
    asyncio.run(R.processar(cid, imp))
    assert len(list((C.pasta(cid) / "foto").glob("*.jpg"))) == 3 and not (C.pasta(cid) / "foto_cliente").exists()
    card = [m for m in C.mensagens(cid) if m["tipo"] == "importacao"][-1]
    assert "3 fotos da vistoria" in card["texto"]
    # sem visita feita: um card pergunta; "Sim" leva as fotos para a vistoria
    cid2 = C.criar("")
    pasta = R._pasta_imp(cid2, imp)
    pasta.mkdir(parents=True)
    for i in range(2):
        (pasta / f"IMG_{i}.jpg").write_bytes(b"foto" * 100)
    asyncio.run(R.processar(cid2, imp))
    perg = [m for m in C.mensagens(cid2) if m["tipo"] == "escolha" and m["dados"].get("pergunta") == "fotos"]
    assert len(perg) == 1 and perg[0]["texto"] == "Essas 2 fotos são da sua vistoria?"
    from lovable.avaliacao import rotas_conversa as RC
    asyncio.run(RC.escolher(cid2, RC.Escolha(pergunta="fotos", valor="vistoria"), _u={}))
    assert len(list((C.pasta(cid2) / "foto").glob("*.jpg"))) == 2
    assert not list((C.pasta(cid2) / "foto_cliente").glob("*.jpg"))


def test_074_b_fotos_novas_chegam_ao_trabalho_aberto(monkeypatch):
    from lovable.avaliacao import db
    from tests.avaliacao.test_pagina_enviada import _job

    async def ler(cid_, rel, triagem):
        return _DocLido()
    monkeypatch.setattr(R, "_ler_com_ia", ler)
    cid = C.criar("")
    jid = _job()
    C.atualizar(cid, job_id=jid)
    C.juntar_contexto(cid, {"visita_feita": True})
    imp = "20261114-220500"
    pasta = R._pasta_imp(cid, imp)
    pasta.mkdir(parents=True)
    for i in range(3):
        (pasta / f"IMG_{i}.jpg").write_bytes(b"foto" * 100 + bytes([i]))
    asyncio.run(R.processar(cid, imp))
    assert sum(1 for a in db.arquivos(jid) if a["tipo"] == "foto") == 3
    assert db.setting(f"fotos_novas:{jid}") == "3"
    assert any("Chegaram 3 fotos da vistoria no trabalho" in m["texto"] for m in C.mensagens(cid))
    from lovable.avaliacao import orquestrador
    orquestrador.reabrir(jid, "extracao")
    assert db.setting(f"fotos_novas:{jid}") == "0"           # "Refazer o laudo com as fotos" zera o aviso


def test_081_1_reinicio_no_meio_retoma_sozinho_sem_transcrever_de_novo(monkeypatch):
    """Volta 4: o servidor foi reiniciado no meio dos 15 áudios e cada "Tentar de novo" recomeçava do
    áudio 1. Agora a leitura volta sozinha e continua do áudio seguinte (o já transcrito não é pago de novo)."""
    cid = C.criar("")
    imp = "20261114-235500"
    pasta = R._pasta_imp(cid, imp)
    pasta.mkdir(parents=True)
    (pasta / "Conversa do WhatsApp com Maria Teste.txt").write_text(ANDROID, encoding="utf-8")
    for i in range(1, 4):
        (pasta / f"PTT-20261114-WA000{i}.opus").write_bytes(b"audio")
    chamadas = []
    cair = {"sim": True}

    def transcrever(p):
        if cair["sim"] and len(chamadas) == 1:            # o servidor "cai" no 2º áudio
            raise asyncio.CancelledError()
        chamadas.append(p.name)
        return (f"texto de {p.name}", 10.0, 5.0)
    monkeypatch.setattr(R.transcricao, "disponivel", lambda: True)
    monkeypatch.setattr(R.transcricao, "transcrever", transcrever)

    async def resumir(cid_):
        pass
    from lovable.avaliacao import entendimento
    monkeypatch.setattr(entendimento, "resumir", resumir)
    R._status(cid, estado="trabalhando", texto="Abrindo os arquivos…", importacao=imp)
    try:
        asyncio.run(R.processar(cid, imp))
    except asyncio.CancelledError:
        pass
    assert chamadas == ["PTT-20261114-WA0001.opus"]
    cair["sim"] = False

    async def voltar():                                  # servidor de volta: ninguém toca em nada
        st = R.status(cid)
        assert st["estado"] == "trabalhando" and "continua a leitura" in st["texto"]
        await R._rodando[cid]
    asyncio.run(voltar())
    assert chamadas == ["PTT-20261114-WA0001.opus", "PTT-20261114-WA0002.opus", "PTT-20261114-WA0003.opus"]
    assert R.status(cid)["estado"] == "pronto"
    conv = json.loads((pasta / "conversa.json").read_text(encoding="utf-8"))
    assert conv["meta"]["transcritos"] == 3
    R._rodando.pop(cid, None)


def test_081_1_leitura_no_meio_nao_vira_pergunta(monkeypatch):
    from lovable.avaliacao import rotas_conversa as RC
    cid = C.criar("")
    monkeypatch.setattr(RC, "_importacao", lambda c: {"estado": "trabalhando", "texto": "lendo", "importacao": "x"})
    assert RC._estado(cid)["pendencias"] == []


def test_083_c1_visita_com_data_passada_e_relato_depois_fecham_a_pergunta(monkeypatch):
    """Volta 4: 31 fotos (16 + 15) e o checklist. Foto mandada pelo avaliador depois da data da visita é da vistoria;
    e as que ficaram esperando "são da vistoria?" vão sozinhas quando o relato chega (o card fecha)."""
    async def ler(cid_, rel, triagem):
        return _DocLido()
    monkeypatch.setattr(R, "_ler_com_ia", ler)
    from lovable.avaliacao import entendimento, rotas_conversa as RC

    async def resumir(cid_):
        return None
    monkeypatch.setattr(entendimento, "resumir", resumir)
    cid = C.criar("")
    C.juntar_contexto(cid, {"visita": "2026-11-13T12:30"})             # visita no passado, ainda não "feita"
    imp = "20261115-000100"
    pasta = R._pasta_imp(cid, imp)
    pasta.mkdir(parents=True)
    for i in range(16):
        (pasta / f"IMG_{i}.jpg").write_bytes(b"foto" * 100)
    asyncio.run(R.processar(cid, imp))
    assert len(list((C.pasta(cid) / "foto").glob("*.jpg"))) == 16
    assert not [m for m in C.mensagens(cid) if m["tipo"] == "escolha" and m["dados"].get("pergunta") == "fotos"]
    # sem data de visita: pergunta; o relato que chega depois responde
    cid2 = C.criar("")
    pasta = R._pasta_imp(cid2, imp)
    pasta.mkdir(parents=True)
    for i in range(15):
        (pasta / f"IMG_{i}.jpg").write_bytes(b"foto" * 100)
    asyncio.run(R.processar(cid2, imp))
    RC._guardar_checklist(cid2, "VISTORIA: casa térrea, 2 quartos.")
    perg = [m for m in C.mensagens(cid2) if m["tipo"] == "escolha" and m["dados"].get("pergunta") == "fotos"]
    assert perg and perg[0]["dados"].get("respondida")
    assert len(list((C.pasta(cid2) / "foto").glob("*.jpg"))) == 15
