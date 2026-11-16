"""L201-2 (Caso M): o laudo de um avaliador que não é o dono saía com o CNAI do Alan (053569) em todas as páginas.
Nenhum dado de outra conta (nome, CRECI, CNAI, contatos, formação, logo) pode aparecer no laudo dele; o número sai
como foi cadastrado; contato vazio no Anexo V some, sem marcador."""
import re
import uuid
import zipfile

import pytest

from lovable.avaliacao import avaliadores as A, db, docx_builder
from lovable.avaliacao.modelos import Trabalho

from .test_docx import _job, _textos

# o que é só do Alan (dono) e nunca pode sair no laudo de outro avaliador, campo a campo
DO_ALAN = {
    "nome": ("Alan Soares", "ALAN SOARES"),
    "creci": ("36507",),
    "cnai": ("053569", "53569"),
    "telefone": ("9306-8692", "99306"),
    "site": ("avaliadordeimovel",),
    "instagram": ("alansoares",),
    "formacao": ("SINDIM", "Instituto Monitor"),
    "logo": ("[LOGO NO CABECALHO]",),          # sem logo cadastrada: cabeçalho sem marca (D-095), nunca a do Alan
}


def _todo_texto(arq) -> str:
    with zipfile.ZipFile(arq) as z:
        xml = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist()
                       if n.startswith("word/") and n.endswith(".xml"))
    return " ".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", xml)) + " " + " ".join(
        re.findall(r'Target="([^"]+)"', xml))


@pytest.fixture
def laudo_de_outro():
    av = A.cadastrar(f"l201-{uuid.uuid4().hex[:10]}@teste.local", "senha-l201-ok",
                     {"nome": "Beatriz Teste", "creci": "12345-GO", "cnai": "777", "telefone": "", "site": "",
                      "instagram": "", "formacao": "", "cidade": "Goiania"})
    jid, sel, r = _job()
    t = Trabalho.model_validate(db.job(jid)["dados"]).model_copy(update={"avaliador_id": av})
    db.atualizar_dados(jid, t)
    arq = docx_builder.montar(jid, _textos(), r, sel)
    with zipfile.ZipFile(arq) as z:
        cab = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist()
                       if re.match(r"word/header\d*\.xml$", n))
    return _todo_texto(arq) + ("" if "<w:drawing" not in cab else " [LOGO NO CABECALHO]")


@pytest.mark.parametrize("campo", list(DO_ALAN))
def test_nenhum_dado_do_alan(laudo_de_outro, campo):
    for s in DO_ALAN[campo]:
        assert s not in laudo_de_outro, f"{campo}: '{s}' do Alan no laudo de outro avaliador"


def test_numeros_como_cadastrados(laudo_de_outro):
    assert "Beatriz Teste" in laudo_de_outro
    assert "CNAI nº 777" in laudo_de_outro and "0777" not in laudo_de_outro
    assert "12345" in laudo_de_outro


def test_contato_vazio_some(laudo_de_outro):
    for rot in ("Telefone / WhatsApp:", "Site:", "Instagram:", "Formação:"):
        assert rot not in laudo_de_outro
    assert "Goiânia, " in laudo_de_outro and "Goiania," not in laudo_de_outro
