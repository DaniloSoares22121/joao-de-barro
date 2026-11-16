"""ORDEM 043 / D-098: modelos gerais aprovados — proposta e contrato fiéis ao texto, sem dados do
Alan nem de cliente; preço em branco sem tabela; 11 cláusulas na OV e 10 no PTAM."""
import uuid

from lovable.avaliacao import avaliadores as A
from lovable.avaliacao import modelos_gerais as M

ALAN = ("Alan", "36507", "053569", "9306", "avaliadordeimovel", "alansoares", "Goiânia")


def _texto(D) -> str:
    partes = [p.text for p in D.paragraphs] + [c.text for t in D.tables for r in t.rows for c in r.cells]
    for s in D.sections:
        partes += [p.text for p in s.header.paragraphs] + [p.text for p in s.footer.paragraphs]
    return "\n".join(partes)


def _av():
    return A.cadastrar(f"{uuid.uuid4().hex[:8]}@teste.invalid", "senha-123",
                       {"nome": "Avaliador TESTE", "creci": "1234/SP", "cnai": "12345", "cidade": "Cidade Teste"})


def test_proposta_fiel_e_sem_dados_do_alan():
    t = _texto(M.proposta(_av(), {"modalidade": "OV"}))
    assert "PROPOSTA DE AVALIAÇÃO" in t and "Investimento: R$ [VALOR — da tabela do avaliador]" in t
    assert "Uma ligação após a entrega para esclarecer dúvidas" in t
    assert "Em até 90 dias da entrega, a Opinião de Valor pode ser convertida em PTAM" in t
    assert "Opinião de valor elaborada por corretor de imóveis avaliador (CRECI/CNAI), conforme a Lei nº 6.530/1978, art. 3º." in t
    assert "CRECI-SP 1234 · CNAI 12345" in t
    assert not any(x in t for x in ALAN)


def test_contrato_clausulas_ov_e_ptam():
    av = _av()
    ov = _texto(M.contrato(av, {"modalidade": "OV"}))
    am = _texto(M.contrato(av, {"modalidade": "AM"}))
    import re
    assert len(re.findall(r"Cláusula \d+ —", ov)) == 11 and len(re.findall(r"Cláusula \d+ —", am)) == 10
    assert "Cláusula 7 — Conversão em PTAM" in ov and "Conversão em PTAM" not in am
    assert "arras penitenciais, nos termos do art. 420 do Código Civil" in ov
    assert "art. 10, § 2º, da Medida Provisória nº 2.200-2/2001" in ov
    assert "[CHAVE PIX]" in ov and not any(x in ov for x in ALAN)
