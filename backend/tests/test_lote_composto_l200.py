"""L200 (Caso M): "Lt. 001E, Compl. Lt. 01-26" com o campo lote = "01-26" virava "Lt. 01-26-26-26…"."""
from types import SimpleNamespace as N

from lovable.avaliacao import docx_builder as B


def _ctx(lote, quadra=""):
    cs = [N(nome="lote", valor=lote, origem="documento", fonte="documento/Escritura.jpeg", unidade="")]
    if quadra:
        cs.append(N(nome="quadra", valor=quadra, origem="documento", fonte="doc", unidade=""))
    return N(cs=cs, job="x")


END = "Rua X, Qd. 58A, Lt. 001E, Compl. Lt. 01-26 – Ed. Y, Apto 1203"


def test_endereco_que_ja_traz_o_lote_do_documento_nao_muda():
    assert B._pares_quadra_lote(_ctx("01-26"), END) == []
    t = END
    for _ in range(3):                       # várias montagens seguidas
        for velho, novo in B._trocas_grafia(_ctx("01-26"), t):
            t = t.replace(velho, novo)
    assert t == END


def test_lote_diferente_ainda_troca_o_numero_inteiro():
    assert B._pares_quadra_lote(_ctx("05"), "Rua X, Qd. 3, Lt. 01-26, Setor Y") == [("Lt. 01-26", "Lt. 05")]
    assert B._pares_quadra_lote(_ctx("05"), "Rua X, Qd. 3, Lt. 02, Setor Y") == [("Lt. 02", "Lt. 05")]
