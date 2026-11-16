"""ORDEM 095-1: a conferência mede no PDF as páginas do corpo quase vazias (menos de 12 linhas)."""
import pymupdf

from lovable.avaliacao import coerencia as C


def _laudo(tmp_path, linhas_por_pagina, anexo_em=None):
    arq = tmp_path / "laudo.pdf"
    with pymupdf.open() as d:
        for k, n in enumerate(linhas_por_pagina, 1):
            pg = d.new_page()
            if anexo_em and k >= anexo_em:
                pg.insert_text((40, 90), "ANEXO III – DOCUMENTAÇÃO DO IMÓVEL", fontsize=10)
            for j in range(n):
                pg.insert_text((40, 90 + 16 * (j + (1 if anexo_em and k >= anexo_em else 0))), f"linha {j + 1} do texto do laudo", fontsize=10)
        d.save(arq)
    return arq


def test_acha_a_pagina_quase_vazia_do_corpo(tmp_path):
    # capa (3 linhas) | corpo cheio | corpo com 5 linhas (o defeito) | corpo cheio | assinatura (4) | anexos
    pdf = _laudo(tmp_path, [3, 30, 5, 30, 4, 2, 2], anexo_em=6)
    assert C.paginas_curtas(pdf) == [{"pagina": 3, "linhas": 5}]


def test_sem_defeito(tmp_path):
    assert C.paginas_curtas(_laudo(tmp_path, [3, 30, 30, 30, 4, 2], anexo_em=6)) == []
