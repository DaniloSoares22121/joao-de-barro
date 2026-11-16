"""D-085 (ORDEM 039-4): dossiê dos descartados.

Todo anúncio analisado fica registrado com link, portal, data e hora de acesso e o motivo da
exclusão, tirado da lista fechada do K0.6 (mais "outro: texto"). O sistema gera o PDF
"Dossiê de pesquisa — Nº" com os critérios, os escolhidos e os descartados com o motivo,
apontando o arquivo de prova de cada um (D-082). Fica junto das provas, na pasta de dados do
trabalho (fora dos anexos do laudo e fora do git). No laudo vai só uma frase (`frase_laudo`)."""
from __future__ import annotations

import html
import json
import re
import unicodedata
from pathlib import Path

from . import db, provas
from .plural import pl

# Lista fechada (K0.6 + F-S003/D-067 + D-066). Qualquer outro motivo: "outro: <texto>".
MOTIVOS = (
    "área de terreno no cartão",
    "anúncio contraditório",
    "duplicado (mesmo imóvel)",
    "padrão superior",
    "condomínio fechado",
    "imóvel novo ou em acabamento (avaliando antigo)",
    "imóvel de renda com várias unidades",
    "lote com duas casas",
    "sem fotos suficientes",
    "sem área construída informada",
    "tipologia diferente",
    "fora da região",
)
_PALAVRAS = (
    ("área de terreno no cartão", ("terreno (f-s003)", "era a do terreno", "cartao = terreno", "area do cartao")),
    ("anúncio contraditório", ("contraditori",)),
    ("duplicado (mesmo imóvel)", ("mesmo imovel", "duplic", "e o mesmo", "repetid")),
    ("padrão superior", ("padrao superior", "alto padrao", "planejad", "piscina", "sauna")),
    ("condomínio fechado", ("condominio fechado",)),
    ("imóvel novo ou em acabamento (avaliando antigo)", ("em acabamento", "imovel novo", "lancamento")),
    ("imóvel de renda com várias unidades", ("renda", "varias unidades", "kitnets", "kitnet")),
    ("lote com duas casas", ("duas casas", "2 casas")),
    ("sem fotos suficientes", ("sem fotos", "poucas fotos", "fotos insuficientes")),
    ("tipologia diferente", ("tipologia diferente", "outra tipologia")),
    ("fora da região", ("fora da regiao", "outra cidade", "outro bairro distante")),
)


def _n(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.casefold().split())


def motivos(r, escolhido: bool) -> list[str]:
    """Motivos da exclusão (lista fechada + "outro: texto"). Escolhido: []."""
    if escolhido:
        return []
    t = _n(" ".join((r.motivo_descarte or "", r.motivo if r.nao_recomendado else "", r.observacao or "")))
    out = [m for m, ps in _PALAVRAS if any(p in t for p in ps)]
    if not r.area_m2:
        out.append("sem área construída informada")
    if not out:
        fora = re.search(r"pre[cç]o fora da curva[^;]*", " ".join((r.motivo or "", r.motivo_descarte or "")), re.I)
        nao = re.search(r"não usado:\s*([^;]+)", r.observacao or "", re.I)
        if r.motivo_descarte:
            out.append(f"outro: {r.motivo_descarte.strip()[:160]}")
        elif nao:
            out.append(f"outro: {nao.group(1).strip()[:160]}")
        elif fora and r.nao_recomendado:
            out.append(f"outro: {fora.group(0).strip()[:160]}")
        else:
            out.append("outro: não escolhido pelo avaliador (fora do critério adotado)")
    return list(dict.fromkeys(out))


def registros(job_id: str) -> list[dict]:
    """Todos os anúncios analisados do trabalho: link, portal, acesso, prova, situação, motivos."""
    from .agentes.selecao import Selecao
    sel_d = db.resultado(job_id, "selecao") or {}
    escolhidos = {x.n for x in Selecao.model_validate(sel_d).refs if x.escolhido} if sel_d else set()
    out = []
    for r in db.candidatos(job_id):
        quando, origem = provas.acesso(job_id, r)
        if quando is None:
            quando, origem = registro_no_sistema(job_id, r.n)
        esc = r.n in escolhidos
        out.append({
            "n": r.n, "link": r.link, "portal": r.portal or "—", "preco": r.preco, "area_m2": r.area_m2,
            "unitario": round(r.preco / r.area_m2, 2) if r.preco and r.area_m2 else None,
            "acessado_em": provas.fmt(quando) if quando else provas.SEM_DATA,
            "origem_data": origem, "prova": getattr(r, "prova", "") or r.print_ or "",
            "escolhido": esc, "motivos": motivos(r, esc), "justificativa": "",
        })
    return out


def registro_no_sistema(job_id: str, n: int):
    """Hora em que o anúncio nº n entrou na lista do trabalho (evento da pesquisa) — é a hora
    que o banco tem. Sem evento: (None, '')."""
    with db._conn() as c:
        rows = c.execute("SELECT msg, ts FROM av_events WHERE job=? AND etapa='pesquisa' "
                         "ORDER BY id", (job_id,)).fetchall()
    for msg, ts in rows:
        if re.search(rf"nº {n}\b(?![–-])", msg or ""):
            return provas.em_brasilia(ts), "registro do sistema (entrada do anúncio na lista)"
        m = re.search(r"nº (\d+)[–-](\d+)", msg or "")
        if m and int(m.group(1)) <= n <= int(m.group(2)):
            return provas.em_brasilia(ts), "registro do sistema (entrada do anúncio na lista)"
    return None, ""


def frase_laudo(job_id: str, n_escolhidos: int) -> str:
    """Frase do item da pesquisa de mercado (todas as modalidades). O Alan confere na revisão."""
    n = len(db.candidatos(job_id))
    n = max(n, n_escolhidos)
    if n <= n_escolhidos:
        return (f"Foram analisados {pl(n, 'anúncio', 'anúncios')}; todos atenderam aos critérios "
                "adotados, conforme o dossiê de pesquisa, disponível mediante solicitação.")
    return (f"Foram analisados {pl(n, 'anúncio', 'anúncios')}; {n_escolhidos} "
            f"{'atendeu' if n_escolhidos == 1 else 'atenderam'} aos critérios adotados; os demais foram "
            "descartados pelos motivos registrados no dossiê de pesquisa, disponível mediante solicitação.")


def _criterios(job_id: str) -> list[str]:
    from .agentes import _comum
    t = _comum.trabalho(job_id)
    esc = json.loads(db.setting(f"area_escolha:{job_id}") or "{}")
    base = {"construida": "área construída", "terreno": "área total do terreno"}.get(esc.get("base"), "não informada")
    return [
        f"Tipologia do avaliando: {t.tipo}; região: {t.bairro}, {t.cidade}.",
        f"Base do cálculo: {base}.",
        "Prioridade para a mesma tipologia e o mesmo padrão, na mesma faixa de preço (D-010, D-067).",
        "Só entra referencial com área construída informada, conferida no texto do anúncio (D-067, F-S003).",
        "Ficam fora: anúncio contraditório, duplicata, padrão superior, condomínio fechado, imóvel novo "
        "quando o avaliando é antigo, imóvel de renda com várias unidades, lote com duas casas e anúncio "
        "sem fotos suficientes (K0.6).",
        "Mínimo de 5 referenciais (D-021). Primeiro os portais; na escassez, sites de imobiliárias e "
        "outros sites de anúncio (D-064).",
    ]


def _brl(v) -> str:
    if v is None:
        return "n/i"
    return "R$00a0" + f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _m2(v) -> str:
    return "n/i" if not v else f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".") + " m²"


def gerar(job_id: str) -> dict:
    """Gera `provas/dossie_pesquisa_<nº>.pdf` (+ .json) na pasta do trabalho."""
    import pymupdf
    from .agentes import _comum
    t = _comum.trabalho(job_id)
    regs = registros(job_id)
    pasta = db.pasta(job_id) / "provas"
    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"dossie_pesquisa_{t.numero}"
    (pasta / f"{nome}.json").write_text(json.dumps(regs, ensure_ascii=False, indent=1, default=str),
                                        encoding="utf-8")
    e = html.escape
    esc = [r for r in regs if r["escolhido"]]
    desc = [r for r in regs if not r["escolhido"]]

    def linha(r, com_motivo):
        prova = e(r["prova"]) if r["prova"] else "<i>sem captura guardada</i>"
        cel = [str(r["n"]), f'<a href="{e(r["link"])}">{e(r["link"][:90])}</a><br/>{e(r["portal"])}',
               e(_brl(r["preco"])), e(_m2(r["area_m2"])), e(_brl(r["unitario"])),
               e(r["acessado_em"]) + (f'<br/><small>{e(r["origem_data"])}</small>' if r["origem_data"] else "")]
        cel.append(e("; ".join(r["motivos"])) if com_motivo else prova)
        if com_motivo:
            cel.append(prova)
        return "<tr>" + "".join(f"<td>{c}</td>" for c in cel) + "</tr>"
    cab1 = "<tr><th>Nº</th><th>Anúncio</th><th>Preço</th><th>Área constr.</th><th>R$/m²</th><th>Acesso</th><th>Prova</th></tr>"
    cab2 = "<tr><th>Nº</th><th>Anúncio</th><th>Preço</th><th>Área constr.</th><th>R$/m²</th><th>Acesso</th><th>Motivo da exclusão</th><th>Prova</th></tr>"
    corpo = f"""
<h1>Dossiê de pesquisa — Nº {e(str(t.numero))}</h1>
<p class="sub">{e(t.tipo)} · {e(t.bairro)}, {e(t.cidade)} · data-base {t.data_base.strftime('%d/%m/%Y')}<br/>
Gerado em {e(provas.fmt(provas.agora()))} (horário de Brasília). Documento de guarda do avaliador:
não faz parte dos anexos do laudo (D-015, D-085).</p>
<h2>Resumo</h2>
<p>Foram analisados {len(regs)} anúncios; {len(esc)} atenderam aos critérios adotados e {len(desc)}
foram descartados pelos motivos abaixo.</p>
<h2>Critérios adotados</h2><ul>{''.join(f'<li>{e(c)}</li>' for c in _criterios(job_id))}</ul>
<h2>Escolhidos ({len(esc)})</h2><table>{cab1}{''.join(linha(r, False) for r in esc)}</table>
<h2>Descartados ({len(desc)})</h2><table>{cab2}{''.join(linha(r, True) for r in desc)}</table>
<p class="nota">Acesso: data e hora em que o anúncio foi visto. "{provas.SEM_DATA}" = o anúncio entrou
sem hora registrada (nunca se inventa data). Prova: captura da página inteira com data, hora e link,
guardada em provas/anuncios/ (D-082).</p>"""
    css = """
body{font-family:sans-serif;font-size:8.5pt;color:#18283B}
h1{font-size:15pt;margin:0 0 2pt 0} h2{font-size:11pt;margin:10pt 0 3pt 0;border-left:4pt solid #F5B800;padding-left:4pt}
.sub{color:#5B6470;font-size:8pt} .nota{color:#5B6470;font-size:7.5pt}
table{border-collapse:collapse;width:100%} th{background:#18283B;color:white;font-size:7.5pt;padding:2pt}
td{border:0.5pt solid #C9CED6;padding:2pt;font-size:7.5pt;vertical-align:top} a{color:#18283B}"""
    destino = pasta / f"{nome}.pdf"
    story = pymupdf.Story(html=corpo, user_css=css)
    w = pymupdf.DocumentWriter(str(destino))
    rect = pymupdf.paper_rect("a4")
    area = rect + (36, 40, -36, -40)
    mais = True
    while mais:
        dev = w.begin_page(rect)
        mais, _ = story.place(area)
        story.draw(dev)
        w.end_page()
    w.close()
    db.evento(job_id, "entrega", "info", f"dossiê de pesquisa gerado: {len(regs)} anúncios analisados, "
              f"{len(esc)} escolhidos, {len(desc)} descartados (D-085)")
    return {"pdf": str(destino), "json": str(pasta / f"{nome}.json"), "analisados": len(regs),
            "escolhidos": len(esc), "descartados": len(desc)}
