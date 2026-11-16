"""ORDEM 038: base de conhecimento K0 a K3 no módulo de aprendizado."""
import asyncio
import re
import zipfile
from pathlib import Path

from lovable.avaliacao import conhecimento as K
from lovable.avaliacao import fichas, identidade, rotas_fichas as R

ASSETS = Path(K.__file__).parent / "assets" / "conhecimento"


def test_k1_vira_24_fichas_sem_duplicar():
    fs = {f["id"]: f for f in fichas._sementes(fichas.K1.read_text(encoding="utf-8"))}
    assert len(fs) == 24 and set(fs) == {f"F-K{i:03d}" for i in range(1, 25)}
    assert all(f["porque"] and f["situacao"] and f["decisao"] for f in fs.values())
    # decisão em sublista (F-K023/F-K024) entra inteira
    assert "mesma estrutura da F-K023" in fs["F-K024"]["decisao"] and "unitário pela média" in fs["F-K024"]["decisao"]
    assert fs["F-K024"]["tipo"] == "modelo" and "galpão" in fs["F-K024"]["tipo_imovel"]
    # escopo com anotação fica geral/avaliador
    assert fs["F-K009"]["escopo"] == "geral" and "precedente" in fs["F-K009"]["fonte"]
    assert fs["F-K021"]["escopo"] == "avaliador" and fs["F-K021"]["avaliador_id"] == fichas.AVALIADOR_ALAN
    assert fs["F-K001"]["tipo_imovel"] == []          # "casa, sobrado, todos" = todos
    fichas.importar_tudo()
    n1 = len(fichas.todas())
    c = fichas.importar_tudo()
    assert c["k1"] == 24 and len(fichas.todas()) == n1        # roda de novo sem duplicar
    ids = [f["id"] for f in fichas.todas()]
    assert len(ids) == len(set(ids))


def test_sementes_tem_porque():
    fs = fichas._sementes(fichas.SEMENTE.read_text(encoding="utf-8"))
    assert len(fs) == 7 and all(f["porque"] for f in fs)


def test_k0_so_a_parte_da_etapa():
    p = K.k0(("pesquisa",))
    assert "## K0.1 Princípios" in p and "## K0.6 Pesquisa" in p
    assert "## K0.8" not in p and "## K0.7" not in p
    sel = K.k0(("pesquisa", "cálculo"))
    assert "## K0.6" in sel and "## K0.7 Cálculo" in sel
    red = K.k0(("redação", "documentos"))
    assert "## K0.8 Redação" in red and "## K0.2 Modalidades" in red and "## K0.6" not in red
    assert K.k0(()) == K._ler("K0").strip()                     # sem etapa: inteiro
    assert len(K.geral(("pesquisa",))) < len(K._ler("K0"))


def test_base_troca_p0_pelo_k0_e_k2():
    g = K.geral(("revisão",))
    assert "K0.9 Revisão" in g and "CNAI nº 053569" in g and "Laudos — padrões dele" in g
    assert "Comercial" not in K.k2(("revisão",)) and "Comercial" in K.k2(("proposta/contrato",))
    assert "Instruções do Projeto" not in g        # texto do P0 antigo não vai mais


def test_k3_guardado_e_nao_usado():
    assert (ASSETS / "K3.md").is_file()
    assert "K3" not in K.geral(("redação",))


def test_cnai_053569_em_todo_lugar():
    # L201-2 (substitui a D-080): o CNAI sai como foi cadastrado, sem completar com zero
    assert identidade.avaliador({"cnai": "53569"})["cnai"] == "53569"
    assert identidade.avaliador({"cnai": "nº 053569"})["cnai"] == "053569"
    assert identidade.PADRAO_AVALIADOR["cnai"] == "053569"
    velho = re.compile(r"(?<![0-9])53569(?![0-9])")
    for nome in ("P1_OV_Modelo.docx", "P1_AM_AMJ_Modelo.docx"):
        with zipfile.ZipFile(ASSETS / nome) as z:
            xml = "".join(z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".xml"))
        assert not velho.search(xml) and "053569" in xml, nome
    for nome in ("P0.txt", "P3.txt", "P7.md", "P9.md", "K2.md"):
        assert not velho.search((ASSETS / nome).read_text(encoding="utf-8")), nome


def test_perguntar_rural_sem_base_sem_ia(monkeypatch):
    from lovable.avaliacao import ia
    fichas.importar_tudo()

    async def nao_chama(*a, **k):
        raise AssertionError("não devia chamar a IA")
    monkeypatch.setattr(ia, "perguntar", nao_chama)
    r = asyncio.run(R.perguntar_regra(R.Pergunta(pergunta="Como faço um laudo rural?"), _u={}))
    assert r["sem_base"] is True and "Ainda não tenho base" in r["partes"][0]["texto"]


def test_perguntar_galpao_usa_fk024_e_k0(monkeypatch):
    from lovable.avaliacao import ia
    fichas.importar_tudo()
    visto = {}

    async def fake(sistema, prompt, esquema, **k):
        visto["prompt"] = prompt
        return esquema.model_validate({"sem_base": False, "partes": []})
    monkeypatch.setattr(ia, "perguntar", fake)
    r = asyncio.run(R.perguntar_regra(R.Pergunta(pergunta="Como faço um PTAM de galpão?"), _u={}))
    assert "F-K024" in r["fichas"] and "F-K024" in visto["prompt"]
    assert "Base geral K0" in visto["prompt"] and "## K0." in visto["prompt"]
    r2 = asyncio.run(R.perguntar_regra(R.Pergunta(pergunta="O anúncio diz 1.650 m², posso usar?"), _u={}))
    assert "F-S003" in r2["fichas"]
