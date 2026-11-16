"""ORDEM 194: gera os PDFs de exemplo da galeria "Modelos de laudo" (e da proposta e do contrato).

Tudo inventado: avaliador "Avaliador Exemplo", cliente "Cliente Exemplo", "Rua Exemplo", anúncios em
https://exemplo.invalid/… e números redondos. Nunca dado de cliente real. Sem IA (os textos estão aqui).

Uso (base temporária; não toca nos dados reais):
    LOVABLE_DATA_DIR=C:/t/exemplos194 .venv/Scripts/python.exe scripts/gerar_exemplos_modelos.py
Saída: lovable/avaliacao/exemplos/<qual>.pdf e <qual>.png (miniatura da 1ª página).
"""
import os
import shutil
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

assert os.environ.get("LOVABLE_DATA_DIR"), "rode com LOVABLE_DATA_DIR apontando para uma pasta temporária"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from lovable.avaliacao import avaliadores as A  # noqa: E402
from lovable.avaliacao import calculo, db, docx_builder, pdf  # noqa: E402
from lovable.avaliacao.agentes.redacao import Textos  # noqa: E402
from lovable.avaliacao.agentes.selecao import Selecao  # noqa: E402
from lovable.avaliacao.modelos import Campo, Referencial, Trabalho  # noqa: E402

SAIDA = Path(__file__).resolve().parents[1] / "lovable" / "avaliacao" / "exemplos"
AREA, UNIT = Decimal("180.00"), Decimal("3200.00")
END = "Rua Exemplo, Quadra 00, Lote 00, Setor Exemplo, município de Goiânia – GO, CEP 74000-000"

REFS = [  # anúncios inventados (área, preço)
    (1, 175.0, 560000.0), (2, 190.0, 610000.0), (3, 168.0, 545000.0), (4, 200.0, 650000.0), (5, 185.0, 585000.0)]


def _foto(p: Path, cor, texto: str, tam=(1200, 800)):
    p.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", tam, cor)
    d = ImageDraw.Draw(im)
    for k in range(0, tam[0], 60):
        d.line([(k, 0), (k + 300, tam[1])], fill=(255, 255, 255), width=2)
    d.rectangle([20, 20, 520, 90], fill=(255, 255, 255))
    d.text((34, 40), texto, fill=(30, 40, 58))
    im.save(p)


def _br(v: Decimal) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _textos(mod: str) -> Textos:
    us = sorted(Decimal(str(p)) / Decimal(str(a)) for _, a, p in REFS)
    faixa = f"R$ {_br(us[0])}/m² e R$ {_br(us[-1])}/m²"
    valor = _br(AREA * UNIT)
    desc = "\n".join(f"- {x}" for x in (
        "Tipo: casa residencial térrea (exemplo).", "Composição: 3 quartos, sendo 1 suíte; sala; cozinha; área de serviço.",
        "Garagem para 2 veículos.", "Padrão construtivo: normal.", "Estado de conservação: regular.",
        "Cobertura em telha cerâmica; piso cerâmico; esquadrias de alumínio."))
    s = {
        "1": "A finalidade do presente trabalho é a determinação do valor de mercado do imóvel avaliando, na data-base "
             "indicada, para subsidiar a negociação entre as partes. Documento de EXEMPLO, com dados inventados.",
        "5": "casas residenciais térreas de padrão normal, localizadas na mesma região de influência mercadológica",
        "6": "",
        "7.1": f"O imóvel avaliando localiza-se na {END}, em via pavimentada, com infraestrutura urbana completa "
               "(exemplo inventado para mostrar o modelo).",
        "7.2": "Não foi apresentada certidão de matrícula. Os dados do imóvel vêm do cadastro municipal (exemplo).",
        "7.3": f"Foi adotada a área construída de {_br(AREA)} m², conforme o cadastro municipal (exemplo).",
        "7.4": desc,
        "8": "Foram selecionadas casas residenciais térreas ofertadas em portais imobiliários de acesso público, na "
             "mesma região do avaliando, com área e padrão semelhantes. Os anúncios deste exemplo são inventados.",
        "9": f"Os cinco referenciais apresentaram valores unitários entre {faixa}. Adotou-se o valor unitário de "
             f"R$ {_br(UNIT)}/m², que aplicado à área de {_br(AREA)} m² resulta em R$ {valor}. Valores de exemplo.",
        "10": "Este é um documento de exemplo, com dados inventados, para mostrar o modelo do sistema.",
    }
    if mod != "OV":  # PTAM: limitação, metodologia completa, diagnóstico; pesquisa e determinação mudam de número
        s.update({
            "4": "Não houve limitação relevante à vistoria. A vistoria foi feita de forma visual, sem ensaios. Exemplo.",
            "5": "Foi adotado o Método Comparativo Direto de Dados de Mercado, conforme a ABNT NBR 14653-1 e 14653-2, "
                 "com tratamento por fatores e saneamento da amostra. Os referenciais deste exemplo são inventados, "
                 "escolhidos entre casas residenciais térreas de padrão normal da mesma região.",
            "8": "O mercado da região apresenta liquidez média para imóveis residenciais deste padrão, com oferta "
                 "regular de casas térreas. Diagnóstico de mercado de exemplo, com dados inventados.",
            "9": s["8"], "10": s["9"], "11": s["10"]})
    if mod == "AMJ":
        s["12"] = ("Quesito 1: Qual o valor de mercado do imóvel?\nResposta: R$ " + valor + ", conforme o item de "
                   "determinação do valor (exemplo).\n\nQuesito 2: O imóvel está em bom estado?\nResposta: O estado de "
                   "conservação é regular, conforme a vistoria (exemplo).")
    return Textos(secoes=s, legendas={f"fotos/f{i}.jpg": f"Ambiente {i} (foto de exemplo)" for i in range(1, 6)},
                  descricao_amostras={})


def _job(mod: str, av: str) -> tuple[str, Selecao, object]:
    extra = {}
    if mod == "AMJ":
        from lovable.avaliacao.modelos import Partes
        extra = {"processo_numero": "0000000-00.2026.8.09.0000", "vara_juizo": "Vara Cível de Exemplo",
                 "acao": "Ação de exemplo", "partes": Partes(autor="Autor Exemplo", reu="Réu Exemplo"),
                 "quesitos": ["Qual o valor de mercado do imóvel?", "O imóvel está em bom estado?"]}
    jid = db.criar_job(Trabalho(
        id="", numero=900 + ["OV", "AM", "AM_GARANTIA", "AMJ"].index(mod), modalidade=mod,
        finalidade="Garantia bancária" if mod == "AM_GARANTIA" else "Venda" if mod in ("OV", "AM") else "Processo judicial",
        cliente="Cliente Exemplo", tipo="Casa", bairro="Setor Exemplo", cidade="Goiânia", pin_maps="",
        data_base=date(2026, 11, 16), data_vistoria=date(2026, 11, 16), avaliador_id=av, **extra))
    pasta = db.pasta(jid)
    for i, cor in enumerate([(120, 160, 120), (150, 150, 150), (110, 140, 180), (200, 190, 170), (170, 120, 110)], 1):
        _foto(pasta / "fotos" / f"f{i}.jpg", cor, f"FOTO DE EXEMPLO {i}")
        db.adicionar_arquivo(jid, f"f{i}.jpg", "foto", f"fotos/f{i}.jpg")
    _foto(pasta / "docs" / "cadastro.png", (245, 245, 245), "DOCUMENTO DE EXEMPLO", (800, 1100))
    db.adicionar_arquivo(jid, "cadastro.png", "", "docs/cadastro.png")
    campos = [Campo(nome="endereco", valor=END, origem="documento", fonte="docs/cadastro.png"),
              Campo(nome="area_construida", valor=float(AREA), unidade="m2", origem="documento", fonte="docs/cadastro.png"),
              Campo(nome="padrao_construtivo", valor="normal", origem="vistoria", fonte="fotos/f1.jpg"),
              Campo(nome="estado_conservacao", valor="regular", origem="vistoria", fonte="fotos/f1.jpg"),
              Campo(nome="solicitante", valor="Cliente Exemplo", origem="documento", fonte="docs/cadastro.png")]
    db.salvar_campos(jid, campos)
    db.evento(jid, "extracao", "resultado", "ok", dados={
        "campos": [c.model_dump(mode="json") for c in campos], "fachada_caixa": [100, 50, 1100, 760],
        "fotos": [{"arquivo": f"fotos/f{i}.jpg", "legenda": f"Ambiente {i} (exemplo)", "ordem": i} for i in range(1, 6)],
        "documentos": [{"arquivo": "docs/cadastro.png", "rotulo_curto": "Cadastro (exemplo)",
                        "rotulo_completo": "Cadastro municipal de exemplo"}], "tarjas": {}})
    refs = [Referencial(n=n, link=f"https://exemplo.invalid/anuncio-{n}", portal="Portal Exemplo", bairro="Setor Exemplo",
                        tipologia="Casa", quartos=3, suites=1, area_m2=a, preco=p, padrao="Normal", idade_aparente="Média",
                        descricao=f"Casa de exemplo nº {n}, inventada para mostrar a tabela.", escolhido=True) for n, a, p in REFS]
    sel = Selecao(refs=refs, unitario_adotado=UNIT, faixa_pct=Decimal("10"))
    return jid, sel, calculo.calcular(AREA, refs, UNIT)


def _miniatura(pdf_path: Path, png: Path) -> None:
    import pymupdf
    with pymupdf.open(pdf_path) as d:
        d[0].get_pixmap(matrix=pymupdf.Matrix(0.45, 0.45)).save(png)


def main() -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    db.init()
    av = next((a for a in ("AV-0002", "AV-0003") if A.obter(a)), None) or A.cadastrar(
        "exemplo@exemplo.invalid", "exemplo-194-nao-usar", {"nome": "Avaliador Exemplo", "creci": "00000-GO",
                                                            "cnai": "00000", "cidade": "Goiânia",
                                                            "formacao": "Formação de exemplo",
                                                            "qualificacao": "Qualificação de exemplo"})
    for mod in ("OV", "AM", "AM_GARANTIA", "AMJ"):
        jid, sel, r = _job(mod, av)
        docx = docx_builder.montar(jid, _textos(mod), r, sel)
        p = pdf.converter(docx)
        destino = SAIDA / f"laudo_{mod}.pdf"
        shutil.copyfile(p, destino)
        _miniatura(destino, SAIDA / f"laudo_{mod}.png")
        print(mod, destino.stat().st_size, "bytes")
    # proposta e contrato de exemplo
    from lovable.avaliacao import modelos_gerais as M
    d = {"ano": 2026, "numero": 900, "data": "16/11/2026", "modalidade": "AM", "categoria": "", "avaliador_id": av,
         "solicitante": {"nome": "Cliente Exemplo", "doc": ""}, "proprietario": "Proprietário Exemplo",
         "imovel": {"descricao": "Casa residencial", "endereco": END, "matricula": "", "cartorio": "", "tipo": "Casa",
                    "bairro": "Setor Exemplo", "cidade": "Goiânia"},
         "finalidade": "Venda", "valor": "1500.00", "cidade_emissao": "Goiânia",
         "pagamento_texto": "", "prazo_texto": "", "arquivo": "exemplo"}
    contratado = {"nome": "Avaliador Exemplo", "cpf": "000.000.000-00", "endereco": "Rua Exemplo, Goiânia – GO",
                  "email": "contato@exemplo.invalid", "pix": "chave-de-exemplo"}
    for qual, doc in (("proposta", M.proposta(av, d)), ("contrato", M.contrato(av, d, contratado))):
        tmp = Path(os.environ["LOVABLE_DATA_DIR"]) / f"{qual}_exemplo.docx"
        feitos = M.salvar(doc, tmp)
        p = next(x for x in feitos if x.suffix == ".pdf")
        shutil.copyfile(p, SAIDA / f"{qual}.pdf")
        _miniatura(SAIDA / f"{qual}.pdf", SAIDA / f"{qual}.png")
        print(qual, "ok")


if __name__ == "__main__":
    main()
