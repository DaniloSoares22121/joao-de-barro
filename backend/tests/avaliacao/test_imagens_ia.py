"""ORDEM 013: a IA só lê cópias (≤ 1568 px, sem EXIF), no máximo 20 imagens por chamada,
pedido < 32 MB; 400 por tamanho não vira "todas as contas falharam"."""
import asyncio
import io
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from lovable.avaliacao import db, ia, imagens_ia, nomes
from lovable.avaliacao.agentes import extracao, triagem
from lovable.avaliacao.modelos import Trabalho
from tests.avaliacao.conftest import numero_livre

LIMITE_PEDIDO = 32 * 1024 * 1024


def _foto_grande(destino: Path) -> None:
    """6000×4000 com ruído (JPEG ~15 MB, como as fotos do laudo 15)."""
    im = Image.frombytes("RGB", (6000, 4000), os.urandom(6000 * 4000 * 3))
    im.save(destino, "JPEG", quality=92)


@pytest.fixture(scope="module")
def foto_grande(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("fotos") / "grande.jpg"
    _foto_grande(p)
    return p


def _job(foto: Path, n_fotos: int = 70, docs: tuple[str, ...] = ()) -> str:
    db.init()
    jid = db.criar_job(Trabalho(
        id="", numero=numero_livre(130), modalidade="OV", finalidade="Venda",
        cliente="ALFA PARTICIPACOES E EMPREENDIMENTOS LTDA, inscrita no CNPJ 12.345.678/0001-90, "
                "neste ato representada por João da Silva, CPF 123.456.789-00",
        tipo="Galpão comercial", bairro="Setor Industrial", cidade="Goiânia",
        pin_maps="", data_base=date(2026, 11, 12), data_vistoria=date(2026, 5, 29)))
    pasta = db.pasta(jid)
    (pasta / "foto").mkdir(parents=True, exist_ok=True)
    for i in range(n_fotos):
        nome = f"IMG_{i:03d}.jpg"
        shutil.copyfile(foto, pasta / "foto" / nome)
        db.adicionar_arquivo(jid, nome, "foto", f"foto/{nome}")
    for nome in docs:
        (pasta / "documento").mkdir(exist_ok=True)
        shutil.copyfile(foto, pasta / "documento" / nome)
        db.adicionar_arquivo(jid, nome, "documento", f"documento/{nome}")
    return jid


class _Espiao:
    """Substitui ia._chamar: guarda cada pedido (arquivos citados) e responde JSON fixo."""

    def __init__(self, pasta: Path, respostas=None):
        self.pasta = pasta
        self.pedidos: list[list[str]] = []
        self.respostas = list(respostas or [])

    async def __call__(self, sistema, prompt, opts):
        arqs = re.findall(r"^- (\S+)", prompt.split("Arquivos para ler")[-1], re.M) \
            if "Arquivos para ler" in prompt else []
        self.pedidos.append(arqs)
        if self.respostas:
            r = self.respostas.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        if '"ok"' in sistema:
            return json.dumps({"ok": True})
        if "LEITURA EM LOTES" in sistema:
            return json.dumps({"notas": [{"arquivo": a, "conteudo": "foto"} for a in arqs]})
        return json.dumps({"quadro": {}, "bloqueado": False, "motivo": ""}) \
            if "TRIAGEM" in sistema else json.dumps({"campos": []})

    def conferir(self):
        for arqs in self.pedidos:
            imgs = [a for a in arqs if imagens_ia.tipo(a) == "imagem"]
            assert len(imgs) <= imagens_ia.MAX_IMAGENS, len(imgs)
            total = 0
            for a in imgs:
                assert a.startswith("_ia/"), a                      # só cópias
                with Image.open(self.pasta / a) as im:
                    assert max(im.size) <= imagens_ia.LADO_IA, im.size
                    assert not im.getexif(), a                       # sem EXIF
                tam = (self.pasta / a).stat().st_size
                assert tam <= imagens_ia.MAX_BYTES_IMAGEM
                total += tam * 4 // 3                                # base64
            assert total < LIMITE_PEDIDO, total


def test_extracao_70_fotos_grandes_em_lotes(monkeypatch, foto_grande):
    jid = _job(foto_grande, 70, docs=("escritura_p1.jpg", "iptu.jpg"))
    pasta = db.pasta(jid)
    esp = _Espiao(pasta)
    monkeypatch.setattr(ia, "_chamar", esp)
    asyncio.run(extracao.rodar(jid))
    esp.conferir()
    # documentos e fotos em chamadas separadas: 1 de documentos + 4 de fotos (20+20+20+10)
    assert len(esp.pedidos) == 5
    assert all(not any("/foto/" in a for a in esp.pedidos[0]) for _ in [0])
    assert all(all("foto/" in a for a in p) for p in esp.pedidos[1:])
    assert sorted(len(p) for p in esp.pedidos[1:]) == [10, 20, 20, 20]


def test_triagem_mais_de_20_documentos_vira_notas(monkeypatch, foto_grande):
    jid = _job(foto_grande, 0, docs=tuple(f"escritura_p{i:02d}.jpg" for i in range(1, 26)))
    esp = _Espiao(db.pasta(jid))
    monkeypatch.setattr(ia, "_chamar", esp)
    r = asyncio.run(triagem.rodar(jid))
    esp.conferir()
    assert [len(p) for p in esp.pedidos] == [20, 5]          # 1 lote de notas + a leitura final
    assert r.bloqueado is False


def test_cdr_ignorado_com_aviso(monkeypatch, foto_grande):
    jid = _job(foto_grande, 1)
    pasta = db.pasta(jid)
    (pasta / "foto" / "fachada.cdr").write_bytes(b"CDR")
    db.adicionar_arquivo(jid, "fachada.cdr", "foto", "foto/fachada.cdr")
    esp = _Espiao(pasta)
    monkeypatch.setattr(ia, "_chamar", esp)
    asyncio.run(extracao.rodar(jid))
    assert not any(a.endswith(".cdr") for p in esp.pedidos for a in p)
    with db._conn() as c:
        msgs = [r[0] for r in c.execute("SELECT msg FROM av_events WHERE job=? AND nivel='aviso'", (jid,))]
    assert any("arquivo ignorado" in m and "fachada.cdr" in m for m in msgs)


def test_copia_sem_gps_e_com_rotacao(tmp_path):
    im = Image.new("RGB", (4000, 3000), "white")
    exif = Image.Exif()
    exif[0x0112] = 6                       # girar 90°
    exif[0x8825] = {1: "S", 2: (16.0, 40.0, 0.0)}   # GPS
    im.save(tmp_path / "f.jpg", "JPEG", exif=exif.tobytes())
    it = imagens_ia.copia_imagem(tmp_path, "f.jpg")
    with Image.open(tmp_path / it.ia) as c:
        assert c.size == (1176, 1568)      # em pé (EXIF aplicado) e ≤ 1568
        assert not c.getexif()
    assert it.escala == pytest.approx(1568 / 4000, rel=0.01)   # em pé: 3000×4000


def test_pdf_vira_paginas_e_caixa_volta_a_pontos(tmp_path):
    import pymupdf
    d = pymupdf.open()
    for _ in range(2):
        d.new_page(width=595, height=842)
    d.save(tmp_path / "e.pdf")
    itens = imagens_ia.paginas_pdf(tmp_path, "e.pdf")
    assert [i.chave for i in itens] == ["e.pdf#p1", "e.pdf#p2"]
    with Image.open(tmp_path / itens[0].ia) as im:
        assert max(im.size) <= imagens_ia.LADO_IA
        # A4 a 150 dpi daria 1240×1754: o limite de 1568 px manda (≈ 134 dpi)
        assert im.size[1] == 1568 and abs(im.size[0] - round(595 * 1568 / 842)) <= 1
    larg = round(595 * itens[0].escala)
    assert imagens_ia.converter_caixa([0, 0, larg, 100], itens[0].escala)[2] == pytest.approx(595, abs=1)


def test_classifica_400_e_429():
    e = ia.classificar(400, "API Error: 400 Todas as contas Claude falharam (limite ou erro de token)")
    assert isinstance(e, ia._PedidoInvalido)                    # 400 NÃO é cota
    e = ia.classificar(400, "image exceeds 5 MB maximum: 19962880 bytes > 5242880 bytes")
    assert isinstance(e, ia._PedidoInvalido) and e.grande
    assert isinstance(ia.classificar(413, "request_too_large"), ia._PedidoInvalido)
    for st in (401, 403, 429, 529):
        assert isinstance(ia.classificar(st, "x"), ia._RateLimit)
    assert isinstance(ia.classificar(None, "JSON message exceeded maximum buffer size"), ia._PedidoInvalido)
    assert ia._status("x", "API Error: 400 bla") == 400


def test_400_por_tamanho_reduz_e_tenta_uma_vez(monkeypatch, foto_grande):
    jid = _job(foto_grande, 2)
    pasta = db.pasta(jid)
    esp = _Espiao(pasta, [ia._PedidoInvalido("image exceeds 5 MB maximum", True)])
    monkeypatch.setattr(ia, "_chamar", esp)

    async def sem_espera(*a):
        raise AssertionError("400 não pode esperar cota")
    monkeypatch.setattr(ia, "_sleep", sem_espera)
    r = asyncio.run(ia.perguntar("s", "p", _Simples, arquivos=[Path("foto/IMG_000.jpg")], cwd=pasta))
    assert r.ok is True
    assert len(esp.pedidos) == 2
    assert esp.pedidos[1][0].startswith(f"_ia/{ia.LADO_REDUZIDO}/")   # 2ª vez, cópia menor


def test_400_que_nao_e_tamanho_falha_com_mensagem_clara(monkeypatch, foto_grande):
    jid = _job(foto_grande, 1)
    esp = _Espiao(db.pasta(jid), [ia._PedidoInvalido("invalid media type", False)])
    monkeypatch.setattr(ia, "_chamar", esp)
    with pytest.raises(ia.IAFalhou) as e:
        asyncio.run(ia.perguntar("s", "p", _Simples, arquivos=[Path("foto/IMG_000.jpg")],
                                 cwd=db.pasta(jid)))
    assert "a IA recusou o pedido" in str(e.value) and "contas" not in str(e.value)
    assert len(esp.pedidos) == 1


from pydantic import BaseModel  # noqa: E402


class _Simples(BaseModel):
    ok: bool = True


def test_solicitante_so_nome_e_laudo_sem_cpf():
    q = ("ALFA PARTICIPACOES E EMPREENDIMENTOS LTDA, pessoa jurídica de direito privado, inscrita "
         "no CNPJ sob o nº 12.345.678/0001-90, com sede na Rua 1, Qd. 2, Lt. 3, Goiânia-GO, neste "
         "ato representada por seu sócio administrador João da Silva, inscrito no CPF sob o nº "
         "123.456.789-00")
    assert nomes.nome_solicitante(q) == "ALFA PARTICIPACOES E EMPREENDIMENTOS LTDA"
    lau = nomes.qualificacao_laudo(q)
    assert "12.345.678/0001-90" in lau and "com sede" in lau
    assert "123.456.789-00" not in lau and "João da Silva" not in lau and "CPF" not in lau
    assert nomes.qualificacao_laudo("Maria Souza Lima, brasileira, CPF 123.456.789-00") == "Maria Souza Lima"
    assert nomes.cliente_curto(q) == "ALFA PARTICIPACOES E EMPREENDIMENTOS LTDA"
