"""ORDEM 043 / D-098: modelos gerais APROVADOS pelo Alan (14/11/2026), cópia fiel de
`jdb-treino/referencia/modelos-gerais/MODELOS_GERAIS_APROVADOS_2026-11-14.md`.

- Proposta (seção 1) e contrato (seção 2) para os avaliadores que não são o Alan: o texto é o
  aprovado, palavra por palavra; entre colchetes ficam os dados do avaliador (cadastro) e do
  trabalho; número entre colchetes é padrão editável por avaliador (`padroes`). Sem tabela de preço,
  o preço fica em branco (D-097).
- Laudo geral (seções 3 e 4): os modelos P1 com as 6 mudanças da seção 5 (aplicadas no
  docx_builder e nos próprios modelos), sem dado do Alan nem de cliente.
- Visual: logo e cores do avaliador; sem logo, neutro e sem marca (D-095).
Nenhum dado do Alan nem de cliente dentro destes modelos."""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from . import avaliadores as A

PADROES = {"validade_dias": "10", "sinal_pct": "50", "saldo_pct": "50", "km": "30", "visita_dias": "1 a 5",
           "entrega_dias": "7 a 15", "conversao_dias": "90", "sem_visita_dias": "30", "multa_pct": "10",
           "juros_pct": "1", "tolerancia_min": "15", "visita_frustrada": "100,00"}


def _c(v, rotulo: str) -> str:
    """Campo preenchido ou o colchete do modelo (o avaliador vê o que falta)."""
    v = (str(v).strip() if v is not None else "")
    return v if v else f"[{rotulo}]"


def _cor(hexa: str) -> RGBColor:
    return RGBColor.from_string(hexa.upper())


def _doc(av: str, cab: list[str], rodape: str):
    D = Document()
    st = D.styles["Normal"]
    st.font.name = "Arial"
    st.font.size = Pt(10.5)
    cores = _cores(av)
    s = D.sections[0]
    s.page_width, s.page_height = Cm(21), Cm(29.7)
    s.left_margin = s.right_margin = Cm(1.8)
    s.top_margin, s.bottom_margin = Cm(3.2), Cm(2.0)
    h = s.header.paragraphs[0]
    logo = _logo(av)
    if logo is not None:
        h.add_run().add_picture(str(logo), height=Cm(1.4))
        h.add_run("\n")
    for i, linha in enumerate(cab):
        r = h.add_run(("  ·  " if i else "") + linha)
        r.font.size = Pt(9)
        r.font.color.rgb = _cor(cores["principal"] if i == 0 else cores["texto"])
        r.bold = i == 0
    f = s.footer.paragraphs[0]
    r = f.add_run(rodape)
    r.font.size = Pt(8)
    r.font.color.rgb = _cor(cores["texto"])
    return D, cores


def _titulo(D, cores, t: str, sub: str = ""):
    p = D.add_paragraph()
    r = p.add_run(t)
    r.bold, r.font.size, r.font.color.rgb = True, Pt(16), _cor(cores["principal"])
    if sub:
        q = D.add_paragraph()
        rr = q.add_run(sub)
        rr.font.size, rr.font.color.rgb = Pt(10.5), _cor(cores["texto"])


def _h(D, cores, t: str):
    p = D.add_paragraph()
    r = p.add_run(t)
    r.bold, r.font.size, r.font.color.rgb = True, Pt(11.5), _cor(cores["principal"])
    pPr = p._p.get_or_add_pPr()
    bd = OxmlElement("w:pBdr")
    e = OxmlElement("w:left")
    for k, v in (("val", "single"), ("sz", "24"), ("space", "6"), ("color", cores["destaque"])):
        e.set(qn(f"w:{k}"), v)
    bd.append(e)
    pPr.append(bd)


def _par(D, t: str, italico: bool = False):
    p = D.add_paragraph()
    for parte in re.split(r"(\*\*[^*]+\*\*)", t):
        if not parte:
            continue
        r = p.add_run(parte.strip("*") if parte.startswith("**") else parte)
        r.bold = parte.startswith("**")
        r.italic = italico
    return p


def _lista(D, itens: list[str]):
    for it in itens:
        D.add_paragraph(it, style="List Bullet")


def _tabela(D, linhas: list[tuple[str, str]], cab=("Campo", "Conteúdo")):
    t = D.add_table(rows=1, cols=2)
    t.style = "Table Grid"
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = cab
    for a, b in linhas:
        c = t.add_row().cells
        c[0].text, c[1].text = a, b


def _cores(av) -> dict:
    """ORDEM 051: `av` pode ser o id de um avaliador do sistema de laudos ou um emissor de fora
    (JdB Trabalho) passado como dict — sem cores próprias, visual neutro (D-095)."""
    if isinstance(av, dict):
        ok = {k: str(v).lstrip("#").upper() for k, v in (av.get("cores") or {}).items()
              if re.fullmatch(r"#?[0-9A-Fa-f]{6}", str(v))}
        return {**A.NEUTRO, **ok}
    return A.cores(av)


def _logo(av):
    if isinstance(av, dict):
        p = av.get("logo")
        return Path(p) if p and Path(p).is_file() else None
    return A.logo(av)


def _ident(av) -> dict:
    if isinstance(av, dict):     # emissor de fora (ORDEM 051): nome, creci, cnai, site, whatsapp, cidade
        creci = av.get("creci") or ""
        uf = (re.search(r"\b([A-Z]{2})\b", creci) or [None, ""])[1] if creci else ""
        num = (re.findall(r"\d{3,}", creci) or [""])[-1] if creci else ""
        cnai = (re.findall(r"\d{3,}", av.get("cnai") or "") or [""])[-1]
        return {"nome": av.get("nome", ""), "uf": uf, "creci": num, "cnai": cnai, "site": av.get("site", ""),
                "whatsapp": av.get("whatsapp", ""), "cidade": av.get("cidade", ""), "comarca": av.get("comarca", "")}
    i = A.identidade_avaliador(av)
    d = (A.obter(av) or {}).get("dados", {})
    creci = i["creci"]
    uf = (re.search(r"\b([A-Z]{2})\b", creci) or [None, ""])[1] if creci else ""
    num = (re.findall(r"\d{3,}", creci) or [""])[-1] if creci else ""
    return {"nome": i["nome"], "uf": uf, "creci": num, "cnai": i["cnai"], "site": i["site"],
            "whatsapp": i["telefone"], "cidade": d.get("cidade", ""), "comarca": d.get("comarca", "")}


def _registro(I: dict) -> str:
    return f"CRECI-{_c(I['uf'], 'UF')} {_c(I['creci'], 'nº')} · CNAI {_c(I['cnai'], 'nº')}"


# ------------------------------------------------------------------ 1. Proposta modelo
def proposta(av: str, d: dict, padroes: dict | None = None):
    P = {**PADROES, **(padroes or {})}
    I = _ident(av)
    ov = (d.get("modalidade") or "OV") == "OV"
    servico = "Opinião de Valor" if ov else "Parecer Técnico de Avaliação Mercadológica (PTAM)"
    cidade = _c(d.get("cidade_emissao") or I["cidade"], "Cidade")
    rodape = f"{_c(I['nome'], 'Nome')} · {_registro(I)} · {_c(I['site'], 'site')} · {_c(I['whatsapp'], 'WhatsApp')}"
    D, cores = _doc(av, [f"PROPOSTA Nº {_c(d.get('numero'), 'ANO-SEQUÊNCIA')}", f"{cidade}, {_c(d.get('data'), 'data')}",
                         f"Válida por {P['validade_dias']} dias"], rodape)
    _titulo(D, cores, "PROPOSTA DE AVALIAÇÃO", f"{servico} de imóvel {_c(d.get('categoria'), 'residencial | comercial')}")
    im = d.get("imovel") or {}
    sol = d.get("solicitante") or {}
    linhas = [("Solicitante", f"{_c(sol.get('nome'), 'nome')} – {_c(sol.get('doc'), 'CPF/CNPJ')}")]
    if d.get("proprietario"):
        linhas.append(("Proprietário", d["proprietario"]))
    linhas += [("Imóvel", f"{_c(im.get('descricao'), 'descrição')} · {_c(im.get('endereco'), 'endereço')} · "
                          f"Matrícula nº {_c(im.get('matricula'), 'número')} – {_c(im.get('cartorio'), 'cartório')}"),
               ("Áreas (m²)", "; ".join(f"{a}: {v} m²" for a, v in (d.get("areas") or {}).items()) or "[área]: [valor] m²"),
               ("Finalidade", _c(d.get("finalidade"), "finalidade"))]
    _tabela(D, linhas)
    preco = d.get("valor") or ""
    _par(D, f"**Investimento: R$ {_c(preco, 'VALOR — da tabela do avaliador')}** · {P['sinal_pct']}% na contratação · "
            f"{P['saldo_pct']}% na entrega do documento")
    _h(D, cores, "O que está incluído")
    _lista(D, ["Visita técnica ao imóvel com registro fotográfico", "Análise da documentação (matrícula, IPTU)",
               "Pesquisa de mercado e comparação com imóveis semelhantes da região", "Documento com o método explicado",
               "Uma ligação após a entrega para esclarecer dúvidas", f"Deslocamento incluído em até {P['km']} km de {cidade}"])
    _h(D, cores, "Prazo")
    _lista(D, [f"Visita técnica: de {P['visita_dias']} dias úteis após a contratação.",
               f"Entrega do documento: de {P['entrega_dias']} dias úteis após a visita técnica."])
    if ov:
        _h(D, cores, "Se o caso for para litígio")
        _lista(D, [f"Em até {P['conversao_dias']} dias da entrega, a Opinião de Valor pode ser convertida em PTAM "
                   f"(R$ {_c(d.get('valor_ptam'), 'VALOR DO PTAM')}): paga-se só a diferença.",
                   f"Se a conversão for pedida em até {P['sem_visita_dias']} dias da entrega, não é preciso nova visita ao imóvel."])
    _par(D, ("Opinião de valor elaborada por corretor de imóveis avaliador (CRECI/CNAI), conforme a Lei nº 6.530/1978, art. 3º."
             if ov else "Parecer Técnico de Avaliação Mercadológica elaborado por corretor de imóveis avaliador (CRECI/CNAI), "
                        "conforme a Lei nº 6.530/1978 e a Resolução COFECI nº 1.066/2007."), italico=True)
    p = _par(D, f"**{_c(I['nome'], 'NOME DO AVALIADOR')}** · Corretor e Avaliador de Imóveis · {_registro(I)}")
    p.paragraph_format.space_before = Pt(24)
    return D


# ------------------------------------------------------------------ 2. Contrato modelo
def contrato(av: str, d: dict, contratado: dict | None = None, padroes: dict | None = None):
    P = {**PADROES, **(padroes or {})}
    I = _ident(av)
    C = contratado or {}
    ov = (d.get("modalidade") or "OV") == "OV"
    serv = "Opinião de Valor" if ov else "Parecer Técnico de Avaliação Mercadológica (PTAM)"
    serv_curto = "Opinião de Valor" if ov else "PTAM"
    cidade = _c(d.get("cidade_emissao") or I["cidade"], "Cidade")
    rodape = (f"{_c(I['nome'], 'Nome')} · {_registro(I)} · {_c(I['site'], 'site')} · {_c(I['whatsapp'], 'WhatsApp')} · Pág. X de Y")
    D, cores = _doc(av, ["CONTRATO DE PRESTAÇÃO DE SERVIÇOS", f"Referente à proposta nº {_c(d.get('numero'), 'ANO-SEQUÊNCIA')}",
                         f"{cidade}, {_c(d.get('data_contrato'), 'data')}"], rodape)
    _titulo(D, cores, "CONTRATO DE PRESTAÇÃO DE SERVIÇOS", f"Avaliação imobiliária – {serv}")
    K = d.get("contratante") or {}
    im = d.get("imovel") or {}
    rep = f", representado(a) por {_c(K.get('representante'), 'NOME E CPF DO REPRESENTANTE')}" if K.get("pj") else ""
    _tabela(D, [("CONTRATADO", f"{_c(I['nome'], 'NOME DO AVALIADOR')}, corretor de imóveis (CRECI-{_c(I['uf'], 'UF')} "
                               f"{_c(I['creci'], 'nº')}) e avaliador imobiliário (CNAI {_c(I['cnai'], 'nº')}), CPF {_c(C.get('cpf'), 'CPF')}, "
                               f"com endereço na {_c(C.get('endereco'), 'ENDEREÇO')}, e-mail {_c(C.get('email'), 'E-MAIL')}, "
                               f"WhatsApp {_c(I['whatsapp'], 'WHATSAPP')}."),
                ("CONTRATANTE", f"{_c(K.get('nome'), 'NOME OU RAZÃO SOCIAL')}, {_c(K.get('doc_tipo'), 'CPF/CNPJ')} {_c(K.get('doc'), 'nº')}, "
                                f"com endereço na {_c(K.get('endereco'), 'ENDEREÇO')}{rep}, e-mail {_c(K.get('email'), 'E-MAIL')}, "
                                f"telefone {_c(K.get('telefone'), 'TELEFONE')}.")], cab=("Parte", "Qualificação"))
    _par(D, "As partes acima firmam este contrato, que se rege pelas cláusulas seguintes.")
    cl = []
    obj = [f"Elaboração de {serv_curto} do imóvel: {_c(im.get('descricao'), 'descrição')}, {_c(im.get('endereco'), 'endereço')}, "
           f"matrícula nº {_c(im.get('matricula'), 'número')} – {_c(im.get('cartorio'), 'cartório')}.",
           f"Finalidade declarada pelo CONTRATANTE: {_c(d.get('finalidade'), 'finalidade')}. O documento só deve ser usado para essa finalidade."]
    if d.get("proprietario") and d.get("proprietario") != K.get("nome"):
        obj.append(f"O imóvel pertence a {d['proprietario']}. O CONTRATANTE declara estar autorizado a solicitar esta avaliação.")
    obj.append(f"O serviço consiste em {'opinião de valor' if ov else 'Parecer Técnico de Avaliação Mercadológica'} elaborado por "
               f"corretor de imóveis avaliador (CRECI/CNAI), conforme a Lei nº 6.530/1978{', art. 3º' if ov else ' e a Resolução COFECI nº 1.066/2007'}. "
               "Não estão incluídos vistoria estrutural, perícia judicial por nomeação nem verificação da regularidade jurídica do imóvel.")
    cl.append(("Objeto", obj))
    forma = (f"Pix (chave {_c(C.get('pix'), 'CHAVE PIX')}) ou transferência" if d.get("pagamento", "pix") == "pix"
             else "link de pagamento com cartão de crédito; juros e encargos da operadora ficam a cargo do CONTRATANTE")
    cl.append(("Preço e pagamento", [
        f"Valor total: R$ {_c(d.get('valor'), 'VALOR')} ({_c(d.get('valor_extenso'), 'valor por extenso')}).",
        f"{P['sinal_pct']}% (R$ {_c(d.get('sinal'), 'sinal')}) na assinatura deste contrato, a título de sinal, e {P['saldo_pct']}% "
        f"(R$ {_c(d.get('saldo'), 'saldo')}) na entrega do documento, por {forma}.",
        "O documento final é entregue após a quitação do saldo.",
        f"O atraso no pagamento implica mora automática do CONTRATANTE, com multa de {P['multa_pct']}% sobre o valor total do serviço "
        f"e juros de {P['juros_pct']}% ao mês, proporcionais ao período de atraso."]))
    cl.append(("Prazos e visita técnica", [
        f"Visita técnica: de {P['visita_dias']} dias úteis após a assinatura e o pagamento do sinal, em data combinada entre as partes.",
        f"Entrega: de {P['entrega_dias']} dias úteis após a visita técnica e o recebimento de todos os documentos da Cláusula 4.",
        "Atrasos causados pelo CONTRATANTE (documentos, acesso ao imóvel, remarcação) suspendem o prazo pelo mesmo período.",
        f"O CONTRATADO aguarda até {P['tolerancia_min']} minutos após o horário marcado para a visita. Se o imóvel estiver indisponível "
        "por responsabilidade do CONTRATANTE, ou ninguém comparecer nesse prazo, a visita será considerada frustrada e o CONTRATANTE "
        f"reembolsará R$ {P['visita_frustrada']} de deslocamento."]))
    cl.append(("Obrigações do CONTRATANTE", [
        "Enviar matrícula atualizada, IPTU, documento do solicitante (RG/CNH, ou cartão CNPJ e contrato social) e os demais documentos solicitados.",
        "Garantir acesso ao imóvel na data combinada e indicar pessoa para acompanhar a visita.",
        "Responder pela veracidade das informações prestadas."]))
    cl.append(("Obrigações do CONTRATADO", [
        "Executar o serviço com técnica e ética profissional, conforme as normas do Sistema COFECI/CRECI.",
        "Entregar o documento em PDF assinado e fazer uma ligação de esclarecimento após a entrega.",
        "Manter sigilo sobre os dados do CONTRATANTE e do imóvel, conforme a cláusula de confidencialidade."]))
    cl.append(("Validade e limites do documento", [
        "O valor reflete o mercado na data-base do documento e pode variar com o tempo e com as condições de mercado.",
        "O CONTRATADO não garante que o imóvel será vendido ou alugado pelo valor indicado, nem que terceiros (bancos, órgãos "
        "públicos, juízo ou outras partes) aceitarão o valor."]))
    if ov:
        cl.append(("Conversão em PTAM", [
            f"Em até {P['conversao_dias']} dias da entrega, o CONTRATANTE pode converter a Opinião de Valor em PTAM pagando só a "
            "diferença entre os valores vigentes.",
            f"Se a conversão for pedida em até {P['sem_visita_dias']} dias da entrega, não é preciso nova visita ao imóvel."]))
    cl.append(("Confidencialidade e dados pessoais (LGPD)", [
        "Os dados pessoais serão usados só para executar este contrato e guardados pelo prazo legal, conforme a Lei nº 13.709/2018 (LGPD).",
        "Nenhum dado do CONTRATANTE ou do imóvel será divulgado sem autorização por escrito, salvo quando exigido por autoridade pública."]))
    cl.append(("Desistência e sinal", [
        "As partes podem desistir deste contrato. O sinal pago na assinatura tem natureza de arras penitenciais, nos termos do art. 420 do Código Civil.",
        "Se o CONTRATANTE desistir, antes ou depois da visita técnica, o sinal não será devolvido.",
        "Se o CONTRATADO desistir, devolverá o sinal mais o equivalente, conforme o mesmo artigo."]))
    cl.append(("Assinatura eletrônica", [
        "As partes assinam este contrato eletronicamente, pelo gov.br, e reconhecem a validade dessa assinatura, nos termos do "
        "art. 10, § 2º, da Medida Provisória nº 2.200-2/2001."]))
    cl.append(("Foro", [f"Fica eleito o foro da comarca de {_c(I['comarca'] or (I['cidade'] and (I['cidade'] + ' – ' + I['uf']) if I['uf'] else ''), 'COMARCA – UF')} "
                        "para resolver qualquer questão sobre este contrato."]))
    for n, (tit, itens) in enumerate(cl, start=1):
        _h(D, cores, f"Cláusula {n} — {tit}")
        for k, it in enumerate(itens, start=1):
            _par(D, f"{k}. {it}")
    _par(D, f"{cidade}, {_c(d.get('data_contrato'), 'data')}.")
    _tabela(D, [(f"{_c(I['nome'], 'NOME DO AVALIADOR')} · {_registro(I)}",
                 f"{_c(K.get('nome'), 'NOME OU RAZÃO SOCIAL')} · {_c(K.get('doc_tipo'), 'CPF/CNPJ')} {_c(K.get('doc'), 'nº')}")],
            cab=("CONTRATADO", "CONTRATANTE"))
    return D


def salvar(D, destino: Path) -> list[Path]:
    destino.parent.mkdir(parents=True, exist_ok=True)
    D.save(destino)
    out = [destino]
    try:
        from .pdf import converter
        out.append(converter(destino))
    except Exception:
        pass
    return out


# ------------------------------------------------------------------ prévias do laudo geral
def previa_laudo(modalidade: str, av: str, destino: Path) -> list[Path]:
    """O modelo P1 da modalidade com as mudanças da seção 5, a identidade do avaliador (neutra sem
    logo) e os colchetes no lugar dos dados do trabalho. Nenhum dado real."""
    from datetime import date
    from types import SimpleNamespace

    from . import docx_builder as B, identidade
    from .docx_partes import subst
    from .modelos import Trabalho
    modelo = B._CONHECIMENTO / B.MODELOS[modalidade]
    doc = Document(str(modelo))
    t = Trabalho(id="previa", numero=0, modalidade=modalidade, finalidade="[finalidade]", cliente="[solicitante]",
                 tipo="[tipo]", bairro="[bairro]", cidade="[cidade]", pin_maps="", data_base=date.today(),
                 data_vistoria=date.today(), avaliador_id=av)
    saida = destino.parent / "_previa"
    saida.mkdir(parents=True, exist_ok=True)
    avisos = []
    ctx = SimpleNamespace(doc=doc, body=doc.element.body, part=doc.part, t=t, saida=saida, aviso=avisos.append,
                          par=lambda txt: next((p for p in doc.element.body.iter(qn("w:p"))
                                                if txt in "".join(x.text or "" for x in p.iter(qn("w:t")))), None))
    with B._TROCA_AV, identidade.do_avaliador(av):
        B._trocar_identidade(ctx) if av != A.ALAN else None
        if modalidade in ("AM", "AM_GARANTIA"):
            subst(ctx.par("AVALIAÇÃO MERCADOLÓGICA"), "AVALIAÇÃO MERCADOLÓGICA", "PARECER TÉCNICO DE AVALIAÇÃO MERCADOLÓGICA – PTAM")
            pn = ctx.par("PTAM N.º [PREENCHER: nº]")
            subst(pn, "PTAM N.º [PREENCHER: nº]", "N.º [nº] · NÃO JUDICIAL")
            if pn is not None:
                import copy
                from .docx_partes import definir
                nat = copy.deepcopy(pn)
                definir(nat, "Natureza do documento: parecer extrajudicial (não judicial)")
                pn.addnext(nat)
            so_amj = ctx.par("Processo (somente AMJ):")
            if so_amj is not None:
                so_amj.getparent().remove(so_amj)
        elif modalidade == "AMJ":
            subst(ctx.par("AVALIAÇÃO MERCADOLÓGICA"), "AVALIAÇÃO MERCADOLÓGICA", "AVALIAÇÃO MERCADOLÓGICA JUDICIAL")
        if modalidade != "OV":
            for p in doc.element.body.iter(qn("w:p")):
                subst(p, "Opinião de valor elaborada", "Parecer elaborado")
                subst(p, "desta Opinião de Valor", "deste parecer")
                subst(p, "limitações descritas no item 10", "limitações descritas no item 11")
        av_d = identidade.avaliador(B._avaliador())
        logo = identidade.logo_recortada(saida)
        rot = "Opinião Profissional de Valor N.º [nº]" if modalidade == "OV" else "PTAM N.º [nº]"
        for s in doc.sections:
            identidade.cabecalho_interno(s.header, rot + "  ·  Data-base [dd/mm/aaaa]", logo)
            identidade.rodape(s.footer, av_d)
            if s.different_first_page_header_footer:
                identidade.cabecalho_capa(s.first_page_header, logo)
                identidade.rodape(s.first_page_footer, av_d)
    for p in doc.element.body.iter(qn("w:p")):
        if av != A.ALAN:
            subst(p, "Goiânia, [PREENCHER: dd de mês de aaaa]", "[Cidade], [dd de mês de aaaa]")
        subst(p, "[PREENCHER: ", "[")
    return salvar(doc, destino)
