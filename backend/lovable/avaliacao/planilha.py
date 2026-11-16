"""Geração da planilha P2 (cálculo) preenchida, mantendo as fórmulas do modelo."""
from __future__ import annotations

import os
import re
import shutil
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl

from .calculo import Resultado
from .modelos import Referencial, Trabalho

# ORDEM 008: modelo oficial V2 (colunas M–P em Amostras, conferência "≥ 5" em Calculo!B20 e
# lista padrão de pendências). A V1 fica no repositório só como histórico.
MODELO = Path(__file__).parent / "assets" / "P2_Planilha_Mestre_Calculo_V2.xlsx"
_SOFFICE_WINDOWS = r"C:\Program Files\LibreOffice\program\soffice.exe"
_LINHA_INI, _LINHA_FIM = 2, 21  # Amostras!A2:L21 (20 linhas)
# origem do Campo -> vocabulário da coluna Status (Imovel!E, lista de validação do modelo)
STATUS_ORIGEM = {"documento": "Comprovado", "vistoria": "Observado", "pesquisa": "Pesquisa",
                 "inferido": "Inferido", "pendente": "Pendente"}
INFORMADO = "Informado"  # campos do formulário do trabalho


def soffice_path() -> str | None:
    """Caminho do LibreOffice (soffice) ou None se não instalado."""
    achado = shutil.which("soffice")
    if achado:
        return achado
    if os.path.exists(_SOFFICE_WINDOWS):
        return _SOFFICE_WINDOWS
    return None


def _num(v: Decimal | float | int) -> float:
    return float(v)


def semelhanca(ref: Referencial) -> str:
    """Coluna P da V2 a partir da lista de candidatos: ★ = Alta; riscado = Baixa; pontuado
    sem ★ = Média. Referencial manual sem pontuação: vazio (o avaliador preenche)."""
    if ref.recomendado:
        return "Alta"
    if ref.nao_recomendado:
        return "Baixa"
    if ref.pontos:
        return "Média"
    return ""


def _link_ou_campo(ref) -> str:
    """153-4: na pesquisa de campo, no lugar do link vai a data da pesquisa (e o informante, se houver)."""
    if not getattr(ref, "pesquisa_campo", False):
        return ref.link
    dp = getattr(ref, "data_pesquisa", "") or ""
    dbr = f"{dp[8:10]}/{dp[5:7]}/{dp[:4]}" if len(dp) >= 10 else dp
    inf = (getattr(ref, "informante", "") or "").strip()
    return f"pesquisa de campo em {dbr}" + (f"; informante: {inf}" if inf else "")


def _fonte(c) -> str:
    """080-2: "documento/INSCRIÇÃO DA CASA.pdf#p2; …" -> "INSCRIÇÃO DA CASA.pdf, pág. 2" (a 1ª fonte); vistoria -> "Vistoria"."""
    if c is None:
        return ""
    if c.origem == "vistoria":
        return "Vistoria"
    f = (c.fonte or "").split(";")[0].strip()
    m = re.match(r"(?:[^/]*/)*([^#]+?)(?:#p(\d+))?$", f)
    if not m:
        return f
    return m.group(1) + (f", pág. {m.group(2)}" if m.group(2) else "")


def _do_laudo(jid: str) -> dict[int, tuple]:
    """080-2: a aba Imovel sai dos MESMOS dados do laudo (campos comprovados e o texto do item 7.4), com a fonte.
    {linha: (valor, unidade, fonte, status)}; o que o laudo não tem fica fora (a linha segue "Pendente")."""
    from . import docx_partes as X
    from .agentes import redacao
    from .docx_builder import _campo, _campos, _constru, _val
    from .agentes.selecao import _decimal_br
    cs = _campos(jid)
    out: dict[int, tuple] = {}
    end = _campo(cs, "endereco")
    if end:
        out[3] = (_endereco_completo(jid, cs, _val(end)), None, _fonte(end), STATUS_ORIGEM[end.origem])
    mat = next((c for c in cs if re.search(r"(?i)matr[ií]cula atual", c.nome)), None) or _campo(cs, "matricula")
    cart = _campo(cs, "cartorio")
    if mat:
        v = _val(mat) + (f" – {_val(cart)}" if cart else "")
        fontes = "; ".join(dict.fromkeys(x for x in (_fonte(mat), _fonte(cart)) if x))
        out[4] = (v, None, fontes, STATUS_ORIGEM[mat.origem])
    ter = _campo(cs, "area", "terreno")
    if ter:
        try:
            out[8] = (float(_decimal_br(ter.valor)), "m²", _fonte(ter), STATUS_ORIGEM[ter.origem])
        except Exception:
            pass
    con = _constru(cs, jid)
    if con:
        out[9] = (None, None, _fonte(con), None)       # o valor e o status já vêm do cálculo; aqui só a fonte
    textos = redacao.carregar(jid)
    d74 = {X.norm(k): v.strip().rstrip(".") for k, v in X.linhas_rotulo((textos.secoes.get("7.4") if textos else "") or "").items()}

    def do74(*chaves: str) -> str:
        return next((v for k, v in d74.items() if all(c in k for c in chaves)), "")
    padrao = re.split(r"[;.,]", do74("padrao") or _val(_campo(cs, "padrao")))[0].strip()   # só a classificação
    if padrao:
        out[10] = (padrao, None, "Laudo, item 7.4" if do74("padrao") else _fonte(_campo(cs, "padrao")), "Observado")
    estado = re.split(r"[;:.]", do74("conservacao") or _val(_campo(cs, "conservacao")))[0].strip()  # 086-6: só a classificação
    if estado:
        out[11] = (estado[:1].upper() + estado[1:], None,
                   "Laudo, item 7.4 (vistoria)" if do74("conservacao") else _fonte(_campo(cs, "conservacao")), "Observado")
    return out


def _endereco_completo(jid: str, cs, end: str) -> str:
    """088-4: o endereço da planilha igual ao do laudo: a grafia da rua do documento do imóvel ("Rua XV 9"), e o
    bairro (do título/IPTU, nunca o "I" da fatura), a cidade e o CEP quando faltam."""
    from types import SimpleNamespace
    from .docx_builder import _campo, _grafia_rua, _val
    try:
        g = _grafia_rua(SimpleNamespace(job=jid))
    except Exception:
        g = None
    if g:
        end = g[0].sub(g[1], end)
    bairro = next((_val(c) for c in cs if re.search(r"(?i)^bairro", c.nome) and c.origem == "documento"), "")
    cidade = _val(_campo(cs, "municipio")) or _val(_campo(cs, "cidade"))
    cep = _val(_campo(cs, "cep"))
    norm = lambda x: re.sub(r"\W+", " ", x).lower()
    end = re.sub(r"\s*\((?:R|Av|Rua)\.?\s*[A-Z]{1,3}\s*\d+[A-Z]?\)", "", end)   # 102-8: sem "(R XV9)"
    partes = [end.rstrip(" .")]
    if bairro and norm(bairro) not in norm(end):
        partes.append(bairro)
    if cidade and norm(cidade.split("–")[0].split("-")[0].strip()) not in norm(end):
        partes.append(cidade)
    if cep and re.sub(r"\D", "", cep) not in re.sub(r"\D", "", end):
        partes.append(f"CEP {cep}")
    return ", ".join(partes)


def _pendencias_abertas(jid: str, trabalho) -> dict[str, bool]:
    """088-4: quais itens do modelo (aba Pendencias) já estão resolvidos NESTE trabalho."""
    import json
    from . import db
    from .agentes import selecao
    cs = db.campos(jid)
    try:
        from .pendencias_simples import CHAVE_ACEITAS
        aceitas = set(json.loads(db.setting(CHAVE_ACEITAS.format(jid)) or "[]"))
    except Exception:
        aceitas = set()
    cheio = lambda rx: any(re.search(rx, c.nome, re.I) and c.valor not in (None, "") for c in cs)
    return {
        "matr": cheio(r"certid[ãa]o.*matr[ií]cula|matr[ií]cula.*atualizada"),
        "pin": bool((trabalho.pin_maps or "").strip()),
        "capa": "capa" in aceitas,
        "solicitante": (any(a.get("tipo") == "solicitante" for a in db.arquivos(jid))
                        or cheio(r"solicitante.{0,3}(cpf|doc|cnh|rg)|(cpf|cnh|documento).{0,6}solicitante")
                        or any(re.search(r"(?i)(cnh|rg|documento).*solicitante", str(d.get("rotulo_curto") or ""))
                               for d in ((db.resultado(jid, "extracao") or {}).get("documentos") or []) if isinstance(d, dict))),
        "areas": bool(selecao.escolha_area(jid)),
    }


def _data_acesso(iso: str) -> date | None:
    """080-1: a data em que o anúncio foi aberto (horário de Brasília). Sem registro: None (célula vazia, nunca a data-base)."""
    if not iso:
        return None
    try:
        from . import provas
        return provas.em_brasilia(iso).date()
    except Exception:
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).date()
        except ValueError:
            return None


def _idade_estimada(jid: str) -> str:
    """080-3: mesma regra do laudo (078-7): a idade que o avaliador respondeu vale para os referenciais sem idade."""
    try:
        from . import tela_trabalho
        v = ((tela_trabalho._cliente(jid) or {}).get("contexto") or {}).get("idade_aparente") or ""
    except Exception:
        return ""
    return f"{v} anos (estimada)" if str(v).isdigit() else str(v)


def _obs(t: str) -> str:
    from .pendencias_simples import limpar_titulo
    return limpar_titulo(t or "", max_palavras=60) if (t or "").strip() else ""


def gerar(
    destino: Path,
    trabalho: Trabalho,
    area: Decimal,
    refs: list[Referencial],
    r: Resultado,
    origem_area: str = "pendente",
) -> Path:
    """Preenche as células de ENTRADA da P2; as fórmulas do modelo são preservadas."""
    if len(refs) > _LINHA_FIM - _LINHA_INI + 1:
        raise ValueError("a planilha P2 comporta no máximo 20 referenciais")
    wb = openpyxl.load_workbook(MODELO)

    im = wb["Imovel"]
    entradas = {
        2: trabalho.cliente,
        3: f"{trabalho.bairro}, {trabalho.cidade}",
        5: trabalho.finalidade,
        6: trabalho.data_base,
        7: trabalho.data_vistoria,
        9: _num(area),
        10: trabalho.tipo,
    }
    for lin, valor in entradas.items():
        im.cell(lin, 2, valor)
        im.cell(lin, 5, STATUS_ORIGEM.get(origem_area, "Pendente") if lin == 9 else INFORMADO)
        if lin in (2, 5, 6, 7, 10):
            im.cell(lin, 4, "Dados do trabalho")
    jid = trabalho.id or ""
    laudo = _do_laudo(jid) if jid else {}
    if 3 not in laudo:                       # sem o endereço do documento: só bairro/cidade, e fica pendente
        im.cell(3, 5, "Pendente")
        im.cell(3, 4, "falta o endereço do documento do imóvel")
    for lin, (valor, unidade, fonte, status) in laudo.items():
        if lin == 10:
            valor = f"{trabalho.tipo} / {valor}"
        if valor is not None:
            im.cell(lin, 2, valor)
        if unidade:
            im.cell(lin, 3, unidade)
        im.cell(lin, 4, fonte or "")
        if status:
            im.cell(lin, 5, status)

    am = wb["Amostras"]
    excluidos = {n for n, _ in r.excluidos}
    sem_data: list[int] = []
    for i, ref in enumerate(refs):
        lin = _LINHA_INI + i
        am.cell(lin, 1, ref.n)
        am.cell(lin, 2, "N" if ref.n in excluidos else "S")
        am.cell(lin, 3, "pesquisa de campo" if getattr(ref, "pesquisa_campo", False) else ref.portal)   # 153-4
        am.cell(lin, 4, _link_ou_campo(ref))
        rua = (getattr(ref, "rua", "") or "").strip()      # 088-4: "Rua JC-58, Jardim Curitiba"
        am.cell(lin, 5, ", ".join(x for x in (rua, (ref.bairro or "").strip()) if x) or None)
        am.cell(lin, 6, ref.lote_m2)
        am.cell(lin, 7, ref.area_m2)
        am.cell(lin, 8, ref.idade_aparente or (_idade_estimada(jid) if jid else "") or None)
        am.cell(lin, 9, ref.preco)
        # 080-1: a data em que o anúncio foi ABERTO; sem registro fica vazia (nunca a data-base)
        quando = _data_acesso(ref.acessado_em)
        am.cell(lin, 11, quando)
        if quando:
            am.cell(lin, 11).number_format = "DD/MM/YYYY"
        else:
            sem_data.append(ref.n)
        if _obs(ref.observacao):
            am.cell(lin, 12, _obs(ref.observacao))
        # J (R$/m²) mantém a fórmula do modelo
        # V2: M tipologia, N quartos/suítes, O padrão/estado, P semelhança (lista Alta/Média/
        # Baixa). Só o que o anúncio/lista trouxe — vazio quando não há dado (não inventar).
        if ref.tipologia and ref.tipologia != "—":
            am.cell(lin, 13, ref.tipologia)
        qs = "/".join(str(x) for x in (ref.quartos, ref.suites) if x is not None)
        if qs:
            am.cell(lin, 14, qs)
        pe = " · ".join(x for x in (ref.padrao, ref.idade_aparente) if x)
        if pe:
            am.cell(lin, 15, pe)
        sem = semelhanca(ref)
        if sem:
            am.cell(lin, 16, sem)
    # 102-8: os anúncios "Só comparação" (D-069) também aparecem, com Usar? = N (fora da estatística e do valor)
    comparacao = []
    if jid:
        from . import db as _db
        ja = {r.n for r in refs}
        comparacao = [c for c in _db.candidatos(jid) if c.decisao == "comparacao" and c.n not in ja]
    for i, ref in enumerate(comparacao[: max(0, _LINHA_FIM - _LINHA_INI + 1 - len(refs))]):
        lin = _LINHA_INI + len(refs) + i
        am.cell(lin, 1, ref.n)
        am.cell(lin, 2, "N")
        am.cell(lin, 3, "pesquisa de campo" if getattr(ref, "pesquisa_campo", False) else ref.portal)
        am.cell(lin, 4, _link_ou_campo(ref))
        am.cell(lin, 5, ", ".join(x for x in ((getattr(ref, "rua", "") or "").strip(), (ref.bairro or "").strip()) if x) or None)
        am.cell(lin, 6, ref.lote_m2)
        am.cell(lin, 7, ref.area_m2)
        am.cell(lin, 9, ref.preco)
        quando = _data_acesso(ref.acessado_em)
        if quando:
            am.cell(lin, 11, quando)
            am.cell(lin, 11).number_format = "DD/MM/YYYY"
        am.cell(lin, 12, "Só comparação (D-069): fora da amostra e do cálculo")
    for lin in range(_LINHA_INI + len(refs) + len(comparacao), _LINHA_FIM + 1):
        am.cell(lin, 2, "N")  # linhas não usadas ficam fora da estatística

    # 088-4: a aba Pendencias mostra só o que está ABERTO neste trabalho (os itens do modelo já resolvidos saem)
    pe = wb["Pendencias"]
    linhas = [[pe.cell(i, c).value for c in range(2, 6)] for i in range(2, pe.max_row + 1) if pe.cell(i, 2).value]
    if jid:
        feito = _pendencias_abertas(jid, trabalho)
        regra = (("matr", r"(?i)matr[ií]cula"), ("pin", r"(?i)\bpin\b|google maps"), ("capa", r"(?i)capa"),
                 ("solicitante", r"(?i)solicitante"), ("areas", r"(?i)diverg[êe]ncias? de [áa]rea"))
        linhas = [x for x in linhas if not any(feito.get(k) and re.search(rx, str(x[0])) for k, rx in regra)]
    if sem_data:                              # 080-1: vira pendência na própria planilha
        linhas.append(["Data de acesso não registrada: referenciais nº " + ", ".join(map(str, sem_data))
                       + " (abrir o anúncio e enviar pela extensão)", "alto", "Alan", "Aberta"])
    for i in range(2, max(pe.max_row, len(linhas) + 1) + 1):
        x = linhas[i - 2] if i - 2 < len(linhas) else [None] * 4
        pe.cell(i, 1).value = i - 1 if x[0] else None       # cell(.., None) não apaga: .value apaga
        for c, v in enumerate(x, 2):
            pe.cell(i, c).value = v

    calc = wb["Calculo"]
    if r.unitario_adotado != r.media:
        calc["B10"] = _num(r.unitario_adotado)  # entrada manual (senão fica =B6)
    calc["B14"] = 1000
    calc["B17"] = _num(r.faixa_pct / Decimal(100))

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return destino
