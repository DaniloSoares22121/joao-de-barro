"""L200 (Caso W): trocar quem entra na conta (mesmos candidatos, outros escolhidos) e confirmar a escolha não pode
manter a escolha antiga — o laudo saía com os referenciais velhos ("escolha manual do avaliador mantida")."""
import asyncio
from datetime import date
from decimal import Decimal

from lovable.avaliacao import db, orquestrador
from lovable.avaliacao.agentes import selecao
from lovable.avaliacao.modelos import Referencial, Trabalho
from tests.avaliacao.conftest import numero_unico


def _r(n, esc):
    return Referencial(n=n, link=f"https://www.exemplo.invalid/{n}", portal="Exemplo", bairro="Setor Exemplo",
                       tipologia="sobrado", padrao="", idade_aparente="", descricao="x", area_m2=300.0,
                       preco=900000.0 + n * 1000, escolhido=esc, decisao="entra" if esc else "")


def test_trocar_escolhidos_refaz_a_selecao(monkeypatch):
    db.init()
    jid = db.criar_job(Trabalho(id="", numero=numero_unico(), modalidade="OV", finalidade="Venda", cliente="Teste",
                                tipo="Sobrado", bairro="Setor Exemplo", cidade="Goiânia", pin_maps="",
                                data_base=date(2026, 10, 16), data_vistoria=date(2026, 10, 16)))
    antigos = [_r(n, n <= 5) for n in range(1, 8)]
    s = selecao.Selecao(refs=antigos, unitario_adotado=Decimal("3000"), faixa_pct=Decimal("10"), confirmado=True)
    db.evento(jid, "selecao", "resultado", "x", dados={**s.model_dump(mode="json"), "manual": True})
    db.salvar_candidatos(jid, [_r(n, n >= 3) for n in range(1, 8)])     # agora entram 3..7
    chamou = {}

    async def rodar(job):
        chamou["sim"] = True
        return selecao.Selecao(refs=db.candidatos(job), faixa_pct=Decimal("10"))
    monkeypatch.setattr(selecao, "rodar", rodar)
    asyncio.run(orquestrador._Pipeline(jid)._selecao())
    assert chamou.get("sim")                                            # não manteve a escolha velha


def test_mesma_escolha_continua_mantida(monkeypatch):
    db.init()
    jid = db.criar_job(Trabalho(id="", numero=numero_unico(), modalidade="OV", finalidade="Venda", cliente="Teste",
                                tipo="Sobrado", bairro="Setor Exemplo", cidade="Goiânia", pin_maps="",
                                data_base=date(2026, 10, 16), data_vistoria=date(2026, 10, 16)))
    refs = [_r(n, n <= 5) for n in range(1, 8)]
    s = selecao.Selecao(refs=refs, unitario_adotado=Decimal("3000"), faixa_pct=Decimal("10"), confirmado=True)
    db.evento(jid, "selecao", "resultado", "x", dados={**s.model_dump(mode="json"), "manual": True})
    db.salvar_candidatos(jid, refs)

    async def nao(job):
        raise AssertionError("a mesma escolha não pode refazer a seleção")
    monkeypatch.setattr(selecao, "rodar", nao)
    r = asyncio.run(orquestrador._Pipeline(jid)._selecao())
    assert sorted(x["n"] for x in r["refs"] if x["escolhido"]) == [1, 2, 3, 4, 5]
