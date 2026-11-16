"""ORDEM 166: antes do [✓ Aprovar] só o PDF (com "(REVISÃO N)"); depois, PDF, Word, planilha e o .zip com os três."""
import io
import zipfile

from lovable.avaliacao import db, planos
from lovable.avaliacao.orquestrador import _arquivos_finais
from tests.avaliacao.test_controle import API, _novo, dono  # noqa: F401 (fixture)


def _arquivos(jid):
    for tipo, p in _arquivos_finais(jid).items():
        p.write_bytes(f"conteudo-{tipo}".encode())


def test_antes_do_aprovar_so_pdf_depois_tudo(client, dono):
    h, _ = dono
    jid = _novo(client, h)
    _arquivos(jid)
    u = f"{API}/jobs/{jid}/baixar"
    r = client.get(f"{u}/pdf", headers=h)
    assert r.status_code == 200 and "REVIS" in r.headers["content-disposition"]
    for t in ("docx", "xlsx", "tudo"):
        assert client.get(f"{u}/{t}", headers=h).status_code == 409
    planos.aprovar(jid)
    for t in ("pdf", "docx", "xlsx"):
        r = client.get(f"{u}/{t}", headers=h)
        assert r.status_code == 200 and "REVIS" not in r.headers["content-disposition"], t
    r = client.get(f"{u}/tudo", headers=h)
    assert r.status_code == 200
    nomes = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert sorted(n.rsplit(".", 1)[1] for n in nomes) == ["docx", "pdf", "xlsx"]
    assert client.get(f"{u}/exe", headers=h).status_code == 404
