"""L200 (Caso W): a foto da vistoria escolhida errada (só o chão, legenda "Entorno") não tinha como sair do
relatório pelo "Pedir ajuste". Agora: ação tirar_foto (por "Foto NN" ou pela legenda), e a montagem a deixa de fora."""
from lovable.avaliacao import ajustes, db


def test_tirar_foto_pela_legenda_e_depois_pelo_arquivo(tmp_path):
    db.init()
    jid = "tirarfoto" + tmp_path.name[-6:]
    feitas = ajustes.aplicar_modelo(jid, [{"tipo": "tirar_foto", "alvo": 'Foto 04 – Entorno – vista da via e da esquina'}])
    assert feitas == ["foto fora do relatório: “Entorno – vista da via e da esquina”"]
    assert not ajustes.foto_fora(jid, "foto/a.jpg", "Fachada frontal – vista da rua")
    assert ajustes.foto_fora(jid, "foto/chao.jpg", "Entorno – vista da via e da esquina")
    # já resolvida para o arquivo: sai mesmo com outra legenda (a redação pode reescrever a legenda)
    assert ajustes.foto_fora(jid, "foto/chao.jpg", "Vista do entorno")
    assert not ajustes.foto_fora(jid, "foto/b.jpg", "Entorno – vista da via e da esquina")


def test_foto_pelo_numero_le_o_ultimo_pdf(monkeypatch, tmp_path):
    import fitz
    db.init()
    jid = "tirarnum" + tmp_path.name[-6:]
    pasta = tmp_path / "entrega"
    pasta.mkdir()
    doc = fitz.open()
    doc.new_page().insert_text((50, 72), "Foto 03 - Garagem\nFoto 04 - Entorno - vista da via")   # fonte básica do PDF não tem o travessão
    doc.save(str(pasta / "laudo.pdf"))
    monkeypatch.setattr(db, "pasta", lambda j: tmp_path)
    assert ajustes.legenda_da_foto(jid, "Foto 04") == "Entorno - vista da via"
    assert ajustes.legenda_da_foto(jid, "a foto do chão") == "a foto do chão"
