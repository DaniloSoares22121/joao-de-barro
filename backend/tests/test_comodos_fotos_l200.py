"""L200 (Caso W): "Dois quartos" tirado de uma foto só, com a vistoria mostrando 3 quartos e 2 banheiros."""
from lovable.avaliacao.agentes import extracao as E


def test_instrucao_pede_contagem_de_todas_as_fotos():
    assert "Ao menos" in E.INSTRUCAO and "TODAS as fotos" in E.INSTRUCAO
    assert "Ao menos N" in E.LOTE_FOTOS and "soma" in E.LOTE_FOTOS
    E.LOTE_FOTOS.format(i=1, n=2, cota=6)          # o texto do lote continua formatável


def test_redacao_nao_justifica_com_contagem_das_fotos():
    from lovable.avaliacao.agentes import redacao as R
    assert "NUNCA serve de justificativa" in R.INSTRUCAO and "conferir a" in R.INSTRUCAO
    assert 'Legenda "Fachada" só em foto que mostra a fachada' in R.INSTRUCAO
