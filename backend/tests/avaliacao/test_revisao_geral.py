"""Regressões da revisão geral de 10/11/2026: cada teste aqui é um defeito que existia."""
import asyncio
import io
from decimal import Decimal, InvalidOperation

import pytest
from PIL import Image

from lovable.avaliacao import db, docx_builder, docx_partes, ia, imagens, orquestrador
from lovable.avaliacao.agentes import selecao
from lovable.avaliacao.modelos import Campo, Referencial, Trabalho

from .conftest import numero_unico


def _job() -> str:
    return db.criar_job(Trabalho(
        id="", numero=numero_unico(), modalidade="OV", finalidade="Venda", cliente="Cliente",
        tipo="Casa", bairro="Setor Bueno", cidade="Goiânia", pin_maps="https://maps.app.goo.gl/x",
        data_base="2026-11-10", data_vistoria="2026-11-09"))


# ------------------------------------------------------------------ área do avaliando
@pytest.mark.parametrize("texto, esperado", [
    ("180 m2", "180"),                       # virava 1802
    ("180m² (IPTU 2025)", "180"),            # virava 1.802.025
    ("180,5 (averbada em 12/03/2010)", "180.5"),
    ("aprox. 180", "180"),                   # virava 0,180
    ("1.234,56", "1234.56"),
    ("364,00 m²", "364.00"),
    ("1.250", "1250"),
    (148, "148"),
])
def test_decimal_br_usa_so_o_primeiro_numero(texto, esperado):
    assert selecao._decimal_br(texto) == Decimal(esperado)


def test_decimal_br_sem_numero_levanta():
    with pytest.raises(InvalidOperation):
        selecao._decimal_br("não informado")


def _campo(nome, valor, origem="documento", fonte="documento/iptu.pdf"):
    return Campo(nome=nome, valor=valor, unidade="m²", origem=origem, fonte=fonte, observacao="")


def test_area_do_documento_vence_a_da_vistoria_e_divergencia_avisa():
    jid = _job()
    db.salvar_campos(jid, [
        _campo("Área construída (estimada)", "150", origem="vistoria", fonte="foto/a.jpg"),
        _campo("Área construída (IPTU)", "180 m²"),
    ])
    assert selecao.area_construida(jid) == Decimal("180")
    assert selecao.origem_area_construida(jid) == "documento"
    aviso = selecao.areas_divergentes(jid)
    assert "divergentes" in aviso and "180,00" in aviso and "150,00" in aviso


def test_areas_iguais_nao_avisam():
    jid = _job()
    db.salvar_campos(jid, [_campo("Área construída (IPTU)", "180"),
                           _campo("Área construída (matrícula)", "180,00 m²")])
    assert selecao.areas_divergentes(jid) == ""


# ------------------------------------------------------------------ tipologia e curva
def test_classe_tipologia_junta_casa_sobrado_e_terrea():
    assert {selecao.classe_tipologia(t) for t in ("Casa", "Sobrado", "Casa térrea", "casa residencial")} == {"casa"}
    assert selecao.classe_tipologia("Apartamento") == "apartamento"
    assert selecao.classe_tipologia("Apto.") == "apartamento"
    assert selecao.classe_tipologia("Lote") == "terreno"
    assert selecao.classe_tipologia("Imóvel exótico") == "imovel exotico"


def _ref(n, tipologia, preco, area=100.0):
    return Referencial(n=n, link=f"https://x/{n}", portal="p", bairro="b", tipologia=tipologia,
                       quartos=3, suites=1, lote_m2=None, area_m2=area, preco=preco,
                       padrao="", idade_aparente="", descricao="", foto="", escolhido=False,
                       justificativa="")


def test_fora_da_curva_enxerga_o_grupo_inteiro_e_formata_em_ptbr():
    # 8 casas escritas de 3 jeitos: separadas por texto, nenhum grupo chegava a 7 e o de
    # R$ 15.000/m² passava
    tipos = ["Casa", "Sobrado", "Casa térrea", "Casa", "Sobrado", "Casa térrea", "Casa", "Sobrado"]
    refs = [_ref(i + 1, t, 300000 + i * 5000) for i, t in enumerate(tipos[:-1])]
    refs.append(_ref(8, tipos[-1], 1500000))
    fora = selecao.fora_da_curva(refs)
    assert list(fora) == [8]
    assert "1,5·IQR" in fora[8] and "1.5" not in fora[8]
    assert "15.000,00/m²" in fora[8]


# ------------------------------------------------------------------ JSON da IA
def test_json_cortado_nao_vira_resposta_vazia():
    cortado = '{"campos": [{"nome": "Área", "valor": 180}, {"nome": "Quartos", "val'
    with pytest.raises(ValueError):
        ia._extrair_json(cortado)


def test_json_em_prosa_e_em_cerca_continua_valendo():
    assert ia._extrair_json('Segue: {"a": 1} é isso.') == {"a": 1}
    assert ia._extrair_json('Usei {chaves} no texto.\n```json\n{"a": 2}\n```') == {"a": 2}
    with pytest.raises(ValueError):
        ia._extrair_json("sem objeto")


def test_erro_do_sdk_vira_nova_tentativa(monkeypatch):
    """Processo do CLI morto/conexão caída não é mais "falha inesperada" que fecha o job."""
    from pydantic import BaseModel

    class R(BaseModel):
        ok: bool

    chamadas = []

    async def fake_chamar(sistema, prompt, opts):
        chamadas.append(1)
        if len(chamadas) == 1:
            raise ia._ErroIA("ProcessError: conexão caiu")
        return '{"ok": true}'
    monkeypatch.setattr(ia, "_chamar", fake_chamar)
    monkeypatch.setattr(ia, "_opcoes", lambda *a, **k: None)
    assert asyncio.run(ia.perguntar("s", "p", R)).ok is True
    assert len(chamadas) == 2


# ------------------------------------------------------------------ Word
def test_texto_com_caractere_de_controle_nao_derruba_o_word():
    assert docx_partes.limpo("a\x0cb\x00c\x0bd\x1fe") == "a b c d e"
    assert docx_partes.limpo("linha\n\tok") == "linha\n\tok"
    r = docx_partes.novo_run("form\x0cfeed")
    assert "form feed" in r.xml if hasattr(r, "xml") else True


def test_campo_casa_por_inicio_de_palavra():
    cs = [_campo("Cidade", "Goiânia"), _campo("Unidade", "101"), _campo("Idade aparente", 30.0),
          _campo("Loteamento", "Jardim X"), _campo("Área construída", "180")]
    assert docx_builder._campo(cs, "idade").nome == "Idade aparente"
    assert docx_builder._campo(cs, "area", "constru").nome == "Área construída"
    assert docx_builder._val(docx_builder._campo(cs, "idade")) == "30"   # era "30.0"


# ------------------------------------------------------------------ imagens no envio
def _bytes(formato, tam=(40, 20), modo="RGB", **kw) -> bytes:
    b = io.BytesIO()
    Image.new(modo, tam, (200, 30, 30) if modo == "RGB" else (200, 30, 30, 128)).save(b, formato, **kw)
    return b.getvalue()


def test_normalizar_deixa_jpeg_bom_intocado(tmp_path):
    p = tmp_path / "a.jpg"
    dados = _bytes("JPEG")
    p.write_bytes(dados)
    assert imagens.normalizar(p) is False
    assert p.read_bytes() == dados


def test_normalizar_webp_vira_jpeg(tmp_path):
    p = tmp_path / "a.webp"
    p.write_bytes(_bytes("WEBP"))
    assert imagens.normalizar(p) is True
    with Image.open(p) as im:
        assert im.format == "JPEG" and im.size == (40, 20)


def test_normalizar_aplica_orientacao_exif(tmp_path):
    p = tmp_path / "retrato.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6   # girar 90° no sentido horário para exibir
    Image.new("RGB", (40, 20), (10, 200, 10)).save(p, "JPEG", exif=exif)
    assert imagens.normalizar(p) is True
    with Image.open(p) as im:
        assert im.size == (20, 40)
        assert im.getexif().get(0x0112, 1) == 1


def test_normalizar_reduz_foto_enorme_e_achata_transparencia(tmp_path):
    p = tmp_path / "g.png"
    Image.new("RGBA", (imagens.LADO_MAX + 500, 100), (0, 0, 0, 0)).save(p, "PNG")
    assert imagens.normalizar(p) is True
    with Image.open(p) as im:
        assert max(im.size) == imagens.LADO_MAX and im.mode == "RGB"
        assert im.getpixel((5, 1))[0] > 240   # transparente vira branco, não preto


def test_normalizar_recusa_o_que_nao_abre(tmp_path):
    p = tmp_path / "ruim.jpg"
    p.write_bytes(b"isto nao e uma imagem")
    with pytest.raises(imagens.ImagemInvalida):
        imagens.normalizar(p)
    assert p.read_bytes() == b"isto nao e uma imagem"


# ------------------------------------------------------------------ banco e fila
def test_pesquisa_nova_substitui_os_candidatos_antigos():
    jid = _job()
    db.salvar_candidatos(jid, [_ref(i, "Casa", 300000) for i in range(1, 16)])
    db.salvar_candidatos(jid, [_ref(i, "Casa", 310000) for i in range(1, 9)], substituir=True)
    assert [r.n for r in db.candidatos(jid)] == list(range(1, 9))
    # sem `substituir` (seleção/escolha manual) segue sendo upsert
    db.salvar_candidatos(jid, [_ref(1, "Casa", 999000)])
    assert len(db.candidatos(jid)) == 8


def test_revisor_entra_no_prompt_da_etapa_refeita_ate_a_proxima_reabertura():
    jid = _job()
    assert db.texto_correcoes(jid, "redacao") == ""
    db.evento(jid, "redacao", "revisor", "seção 5 cita valor diferente do calculado")
    db.evento(jid, "redacao", "revisor", "seção 5 cita valor diferente do calculado")
    txt = db.texto_correcoes(jid, "redacao")
    assert "REVISOR" in txt and txt.count("seção 5 cita") == 1
    assert db.texto_correcoes(jid, "selecao") == ""
    orquestrador.reabrir(jid, "redacao")   # o avaliador reabriu: as notas antigas saem
    assert db.texto_correcoes(jid, "redacao") == ""


def test_falha_fora_do_pipeline_nao_deixa_o_job_preso():
    jid = _job()
    db.set_etapa(jid, "montagem", "executando")
    orquestrador._falha_final(jid, OSError("disco cheio"))
    j = db.job(jid)
    assert j["etapa"] == "entrega" and j["status"] == orquestrador.PARCIAL
    ent = db.resultado(jid, "entrega")
    assert ent["pendencias"][0]["grave"] and "disco cheio" in ent["pendencias"][0]["texto"]


def test_sem_coletor_cede_a_vez_quando_ha_fila(monkeypatch):
    """Um worker só: o job que espera o Coletor não pode segurar quem só falta montar."""
    ordem = []

    async def fake_exec(j):
        ordem.append(j)
        if j == "espera" and ordem.count("espera") == 1:
            return orquestrador.CEDER
        return orquestrador.PRONTO

    async def sem_espera(_s):
        await asyncio.sleep(0)
    monkeypatch.setattr(orquestrador, "executar", fake_exec)
    monkeypatch.setattr(orquestrador, "_sleep", sem_espera)

    async def main():
        monkeypatch.setattr(orquestrador, "_worker", None)
        w = orquestrador.iniciar_fila()
        while not orquestrador._fila.empty():   # jobs antigos do banco de teste
            orquestrador._fila.get_nowait()
            orquestrador._fila.task_done()
        orquestrador._ativos.clear()
        ordem.clear()
        orquestrador.enfileirar("espera")
        orquestrador.enfileirar("outro")
        for _ in range(200):
            await asyncio.sleep(0.005)
            if ordem.count("espera") == 2:
                break
        assert orquestrador.ocupado("espera") is False
        w.cancel()
    asyncio.run(main())
    assert ordem[:2] == ["espera", "outro"] and ordem.count("espera") == 2
