"""ORDEM 092 (6 e 7): a linha do Mapa Digital Fácil no quadro do item 6 tem data; os anexos seguem a ordem do quadro."""
from types import SimpleNamespace

from lovable.avaliacao import docx_builder as D

QUADRO = "\n".join([
    "Escritura pública de doação | Contratante | 30/10/2014 | Anexo III",
    "Carnê do IPTU 2025 | Contratante | 2025 | Anexo III",
    "Comunicado de malha fiscal do ITCD | Contratante | 28/10/2026 | Anexo III",
    "Relatório FIPE | SEFAZ-GO | — | Anexo III",
    "Consulta ao cadastro imobiliário – Mapa Digital Fácil | Avaliador | — | Anexo III",
    "Fatura Saneago | Contratante | JAN/2026 | Anexo III",
])
EXT = {"documentos": [
    {"arquivo": "documento/fatura.pdf", "rotulo_curto": "Fatura Saneago JAN/2026"},
    {"arquivo": "documento/escritura.pdf", "rotulo_curto": "Escritura de doação"},
    {"arquivo": "documento/comunicado.jpg", "rotulo_curto": "Comunicado ITCD"},
    {"arquivo": "documento/iptu.pdf", "rotulo_curto": "IPTU 2025"},
    {"arquivo": "documento/fipe.pdf", "rotulo_curto": "Relatório FIPE – SEFAZ-GO"},
]}


def _ctx():
    return SimpleNamespace(job="nao-existe", ext=EXT, cs=[], textos=SimpleNamespace(secoes={"6": QUADRO}))


def test_anexos_na_ordem_do_quadro(monkeypatch):
    monkeypatch.setattr(D, "mapa_digital", lambda jid: ("mapa_digital/mapa_digital_facil.png", {}))
    rels = ["documento/fatura.pdf", "documento/escritura.pdf", "documento/comunicado.jpg", "documento/iptu.pdf",
            "documento/fipe.pdf", "mapa_digital/mapa_digital_facil.png"]
    assert D._na_ordem_do_quadro(_ctx(), rels) == [
        "documento/escritura.pdf", "documento/iptu.pdf", "documento/comunicado.jpg", "documento/fipe.pdf",
        "mapa_digital/mapa_digital_facil.png", "documento/fatura.pdf"]


def test_data_do_mapa_no_quadro(monkeypatch):
    monkeypatch.setattr(D, "_quando_mapa", lambda ctx: "14/11/2026")
    linhas = [ln.split(" | ") for ln in QUADRO.splitlines()]
    D._data_mapa_no_quadro(_ctx(), linhas)
    assert linhas[4][2] == "14/11/2026" and linhas[3][2] == "—"


def test_093a_linha_sem_data_leva_a_do_documento(monkeypatch):
    from lovable.avaliacao.modelos import Campo
    monkeypatch.setattr(D, "_quando_mapa", lambda ctx: "14/11/2026")
    ctx = _ctx()
    ctx.cs = [Campo(nome="Data de emissão do comunicado ITCD", valor="28/10/2026", origem="documento"),
              Campo(nome="Data da escritura de doação", valor="30/10/2014", origem="documento")]
    linhas = [["Anexo do comunicado ITCD", "Contratante", "—", "Anexo III"],
              ["Relatório FIPE", "SEFAZ-GO", "—", "Anexo III"],
              ["Consulta ao cadastro – Mapa Digital Fácil", "Avaliador", "—", "Anexo III"]]
    D._data_mapa_no_quadro(ctx, linhas)
    assert [x[2] for x in linhas] == ["28/10/2026", "—", "14/11/2026"]     # FIPE sem campo de data: não inventa


def test_095_10_data_dentro_do_texto_e_nome_interno(monkeypatch):
    """O 9121 não tem campo "data de emissão": a data está no texto do comunicado ("emitido … em 28/10/2026")."""
    from lovable.avaliacao.modelos import Campo
    monkeypatch.setattr(D, "_quando_mapa", lambda ctx: "")
    ctx = _ctx()
    ctx.cs = [Campo(nome="itcd_comunicado", valor="Comunicado nº 000; emitido em Goiânia em 28/10/2026; prazo de 30 dias",
                    origem="documento"),
              Campo(nome="data_titulo", valor="30/10/2014", origem="documento")]
    linhas = [["Anexo do comunicado ITCD", "Solicitante", "—", "Anexo III"], ["Relatório FIPE", "SEFAZ-GO", "—", "Anexo III"]]
    D._data_mapa_no_quadro(ctx, linhas)
    assert [x[2] for x in linhas] == ["28/10/2026", "—"]
