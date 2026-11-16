"""ORDEM 105-2b: idade aparente pelo anúncio e, se ele não diz, pelas fotos (IA leve, aqui simulada)."""
import asyncio
from datetime import date
from types import SimpleNamespace

from lovable.avaliacao import idade_anuncio as ia_
from lovable.avaliacao.idade_anuncio import idade_do_texto, idade_valida


def test_texto():
    h = date(2026, 11, 15)
    assert idade_do_texto("Casa nova no Jardim Curitiba", h) == "novo"
    assert idade_do_texto("Sobrado recém-construído, 3 quartos", h) == "novo"
    assert idade_do_texto("Nunca habitada, escriturada", h) == "novo"
    assert idade_do_texto("Casa seminova com piscina", h) == "seminovo"
    assert idade_do_texto("imóvel com 8 anos de construção", h) == "8 anos"
    assert idade_do_texto("Construída em 2015, ótimo acabamento", h) == "11 anos"
    assert idade_do_texto("Casa em excelente estado, reformada", h) is None
    assert idade_do_texto("Casa bem conservada, 3 quartos", h) is None


def test_valida():
    assert idade_valida("excelente") is None and idade_valida("bom") is None and idade_valida("n/i") is None
    assert idade_valida("novo") == "novo" and idade_valida("cerca de 10 anos") == "10 anos"
    assert idade_valida("5") == "5 anos"


def test_fotos(monkeypatch, tmp_path):
    (tmp_path / "f.jpg").write_bytes(b"x")
    monkeypatch.setattr(ia_.db, "pasta", lambda j: tmp_path)
    monkeypatch.setattr(ia_.ia, "definir_contexto", lambda *a: None)
    chamadas = []

    async def falso(sis, prompt, esquema, **kw):
        chamadas.append(kw)
        return esquema(idade="cerca de 3 anos", motivo="acabamento atual")
    monkeypatch.setattr(ia_.ia, "perguntar", falso)
    r = SimpleNamespace(idade_aparente="excelente", titulo="Casa 3 quartos", descricao="Ótima localização", foto="f.jpg")
    assert asyncio.run(ia_.estimar("j", r)) == ("3 anos", "fotos")
    assert len(chamadas) == 1
    # o anúncio diz: não chama a IA
    r2 = SimpleNamespace(idade_aparente="", titulo="Casa nova", descricao="", foto="f.jpg")
    assert asyncio.run(ia_.estimar("j", r2)) == ("novo", "anúncio") and len(chamadas) == 1
    # sem foto: n/i, sem IA
    r3 = SimpleNamespace(idade_aparente="", titulo="Casa", descricao="", foto="")
    assert asyncio.run(ia_.estimar("j", r3)) == ("n/i", "") and len(chamadas) == 1


def test_bairro_nao_e_idade():
    h = date(2026, 11, 15)
    assert idade_do_texto("Casa 3 quartos na Vila Nova", h) is None
    assert idade_do_texto("Sobrado no Nova Suíça", h) is None
    assert idade_do_texto("Casa nova na Vila Nova", h) == "novo"
    assert idade_do_texto("Apartamento novo, nunca habitado", h) == "novo"


def test_completar_um_anuncio_rele_antes_de_gravar(monkeypatch):
    """109-5: o anúncio que chegou ganha a idade; se o avaliador deu a idade enquanto isso, a dele fica."""
    base = [SimpleNamespace(n=1, escolhido=True, decisao="entra", idade_aparente="", titulo="Casa nova", descricao="",
                            foto="")]
    gravados = []

    class R(SimpleNamespace):
        model_fields = {"idade_aparente": None, "idade_fonte": None}

        def model_copy(self, update):
            return R(**{**self.__dict__, **update})
    estado = {"v": [R(**base[0].__dict__)]}
    monkeypatch.setattr(ia_.db, "candidatos", lambda j: estado["v"])
    monkeypatch.setattr(ia_.db, "salvar_candidatos", lambda j, rs: gravados.extend(rs))
    monkeypatch.setattr(ia_.db, "evento", lambda *a, **k: None)
    assert asyncio.run(ia_.completar("j", 1)) == [{"n": 1, "idade": "novo", "fonte": "anúncio"}]
    assert gravados[0].idade_aparente == "novo" and gravados[0].idade_fonte == "anúncio"
    # o avaliador já deu "5 anos": não troca
    estado["v"] = [R(**{**base[0].__dict__, "idade_aparente": "5 anos"})]
    assert asyncio.run(ia_.completar("j", 1)) == []


def _base(monkeypatch, cands, relato=""):
    gravados = []
    monkeypatch.setattr(ia_.db, "candidatos", lambda j: cands)
    monkeypatch.setattr(ia_.db, "salvar_candidatos", lambda j, rs: gravados.extend(rs))
    monkeypatch.setattr(ia_.db, "evento", lambda *a, **k: None)
    monkeypatch.setattr(ia_.db, "instrucoes_avaliador", lambda j: [])
    import lovable.avaliacao.tela_trabalho as T
    monkeypatch.setattr(T, "_cliente", lambda j: {"contexto": {"checklist": relato}})
    return gravados


class _R(SimpleNamespace):
    model_fields = {"idade_aparente": None, "idade_fonte": None}

    def model_copy(self, update):
        return _R(**{**self.__dict__, **update})


def _r(n, idade="", fonte="", decisao="entra", titulo="Casa 3 quartos"):
    return _R(n=n, escolhido=decisao == "entra", decisao=decisao, idade_aparente=idade, idade_fonte=fonte,
              titulo=titulo, descricao="", foto="")


def test_relato_vale_para_os_referenciais_110(monkeypatch):
    """110-2: "30 anos nos referenciais" no relato troca a estimativa da foto (20 anos); comparação não entra."""
    cands = [_r(3, "20 anos", "fotos"), _r(4, ""), _r(6, "5 anos", "fotos", "comparacao"), _r(9, "12 anos", "avaliador")]
    g = _base(monkeypatch, cands, "lote regular; idade aparente 30 anos, e 30 anos nos referenciais; ...")
    assert ia_.idade_do_relato("j") == "30 anos"
    asyncio.run(ia_.completar("j"))
    por = {x.n: (x.idade_aparente, x.idade_fonte) for x in g}
    assert por == {3: ("30 anos", "relato"), 4: ("30 anos", "relato")}       # 6 (comparação) e 9 (avaliador) ficam


def test_estado_no_campo_da_idade_sai_110(monkeypatch):
    cands = [_r(7, "excelente estado de conservação", "", "comparacao")]
    g = _base(monkeypatch, cands)
    asyncio.run(ia_.completar("j"))
    assert g and g[0].idade_aparente == "" 


def test_avaliador_disse_nao_informa_estima_pela_foto_132(monkeypatch, tmp_path):
    """132-4: o avaliador disse "o 7 não informa" (idade vazia): estima pela foto (cartão de confirmar), nunca n/i."""
    (tmp_path / "f.jpg").write_bytes(b"x")
    cands = [_r(7, "", "avaliador", "comparacao")]
    cands[0].foto = "f.jpg"
    g = _base(monkeypatch, cands)
    monkeypatch.setattr(ia_.db, "pasta", lambda j: tmp_path)
    monkeypatch.setattr(ia_.ia, "definir_contexto", lambda *a: None)

    async def falso(sis, prompt, esquema, **kw):
        return esquema(idade="cerca de 8 anos")
    monkeypatch.setattr(ia_.ia, "perguntar", falso)
    asyncio.run(ia_.completar("j"))
    assert g and (g[0].idade_aparente, g[0].idade_fonte) == ("8 anos", "fotos")
    # idade dada pelo avaliador (não vazia) continua intocável
    g2 = _base(monkeypatch, [_r(7, "novo", "avaliador", "comparacao")])
    asyncio.run(ia_.completar("j"))
    assert g2 == []
