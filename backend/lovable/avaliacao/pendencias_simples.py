"""ORDEM 045 / D-100: pendências simples.

Separa duas coisas (K0.9):
- ERRO DO SISTEMA (montagem, texto, conta, imagem cortada, código interno no texto, prazo sem
  fonte): não vai para o avaliador. O sistema corrige sozinho (remontagem sem IA) e mostra no
  máximo uma linha discreta: "Corrigindo sozinho: N ajustes de montagem".
- PENDÊNCIA DO AVALIADOR (escolha, documento que falta, divergência que muda o resultado): um
  cartão por pendência, com título curto em linguagem de gente, botões com as opções conhecidas
  (a recomendada marcada) e "Ver detalhes" (texto técnico, página, fonte).
Proibido no título: código interno (D-027, F-S003, IDs), nome de arquivo, nome de etapa interna
("revisor (visual/montagem)") e inglês. Vermelho só no que impede de seguir.
Pendência ERRADA pela regra (ex.: pedir tarja no laudo do cliente, D-062) é descartada."""
from __future__ import annotations

import json
import re
import unicodedata

from . import db

CHAVE_ACEITAS = "pendencias_aceitas:{}"


def _n(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.casefold().split())


_CODIGO = re.compile(r"\s*\(?\b(?:D-\d{3}|F-[SKD]-?\d{3,4}|K0\.\d+|P\d{1,2})\b\)?")
_ARQUIVO = re.compile(r"\b[\w\-.]+\.(?:jpe?g|png|pdf|docx?|heic)\b", re.I)
_PREFIXO = re.compile(r"^(?:[\w ]+:\s*)?revisor\s*\([^)]*\)\s*:\s*", re.I)


_GENERICO = re.compile(r"(?i)^(?:aviso ao avaliador\W*$|(?:diverg[eê]ncia|pend[eê]ncia|ponto|quest[aã]o)\s+(?:para|a)\s+(?:o\s+)?avaliador\s+"
                       r"(?:decidir|resolver|confirmar)\W*$)")


def sem_caminho(t: str) -> str:
    """074-E: "(_revisao/pagina-21.png)", "(_laudo/x.pdf)" e afins saem inteiros do texto da tela."""
    t = re.sub(r"\s*\([^()]*(?:_revisao|_laudo|/|\\)[^()]*\.(?:png|jpe?g|pdf|docx?|xlsx)\)", "", t or "", flags=re.I)
    t = re.sub(r"\s*\([^()]*_revisao[^()]*\)", "", t, flags=re.I)
    return re.sub(r"\b_revisao/\S+", "", t)


def pergunta(titulo: str, bloqueado: bool = False) -> str:
    """074-C (D-100): o título é a pergunta curta do que o avaliador decide; a página e o item ficam no detalhe."""
    t = (titulo or "").rstrip(" .…")
    if not t or t.endswith("?"):
        return t
    return f"{t}. {'Entendido?' if bloqueado else 'Seguir assim?'}"


# 077-A3: assuntos que viram UMA decisão do avaliador (gravada) — depois, só aviso
PERGUNTA_TEMA = {
    "cv": "A amostra tem dispersão alta (CV acima de 15%). Manter assim, com a conta só na planilha?",
    "amostra": "Há referencial de localização diferente na amostra (falta de anúncios compatíveis). Manter assim?",
}
AVISO_DECIDIDO = {
    "cv": "Dispersão alta da amostra: você decidiu manter, com a conta só na planilha.",
    "amostra": "Referencial de localização diferente: você decidiu manter, por falta de anúncios compatíveis.",
}


def _tema(t: str) -> str:
    if re.search(r"coeficiente de variacao|\bcv\b|dispers|desvio padrao", t):
        return "cv"
    if re.search(r"anglo|localizacao (?:diferente|distinta)|outra (?:regiao|localizacao)", t):
        return "amostra"
    return ""


MAX_PASSOS = 5
_MARCAS_AVISO = ("aviso ao avaliador", "nao e reprovacao", "sem reprovacao", "nao reprova", "ressalva",
                 "decisao do avaliador", "decisao dele", "ignorado", "corrigida de", "corrigido sozinho", "padronizad",
                 "area do cartao")
_MARCAS_TEXTO = ("revisor (", "conferencia de coerencia", "quase vazia")


def _trecho(txt: str) -> str:
    """O trecho do laudo que o apontamento cita (entre aspas), para o avaliador ver o que está escrito."""
    m = re.search(r"[\"'“‘]([^\"'”’]{12,400})[\"'”’]", txt or "")
    return m.group(1).strip() if m else ""


def valor_referencia_fisco(job_id: str):
    """Valor de referência do fisco (SEFAZ/ITCD) lido do comunicado, qualquer que seja o nome do campo."""
    for c in db.campos(job_id):
        n = _n(c.nome)
        if c.valor and c.origem == "documento" and "referencia" in n and ("itcd" in n or "sefaz" in n or "malha" in n
                                                                          or "fisco" in n or "secretaria" in n):
            try:
                return float(str(c.valor).replace(".", "").replace(",", ".")) if isinstance(c.valor, str) and "," in c.valor else float(c.valor)
            except (TypeError, ValueError):
                continue
    return None


def _chave_estavel(s: str) -> str:
    import zlib
    return str(zlib.crc32(s.encode("utf-8")) & 0xffffff)


def _assunto(t: str) -> str:
    """087: o mesmo assunto aparece UMA vez (endereço, datas, área do anúncio N…), em qualquer palavra."""
    m = re.search(r"(?:referencial|anuncio|amostra)\s*(?:n[ºo°]?\s*)?0?(\d{1,2})\b", t)
    if "endereco" in t:
        return "endereco"
    if "mapa digital" in t:
        return "mapa_digital"
    if "anexo" in t and "ordem" in t:
        return "anexo_ordem"
    if "quase vazia" in t or "pagina vazia" in t:
        return "pagina_vazia"
    if m:
        return f"ref{int(m.group(1))}"
    if re.search(r"\bdatas?\b", t) and any(k in t for k in ("fecha", "base", "consulta", "vistoria", "ciencia")):
        return "datas"
    if "quarto" in t:
        return "quartos"
    if "festa" in t:
        return "vizinhanca"
    return " ".join(re.sub(r"[\d\W]+", " ", t).split()[:6])


def gravar_decisao(job_id: str, tema: str, origem: str) -> None:
    """077-A3: grava a decisão como se o avaliador tivesse tocado, com a origem (ex.: "D-068 / caso 122")."""
    aceitar(job_id, f"decisao:{tema}")
    k = f"decisoes_origem:{job_id}"
    d = json.loads(db.setting(k) or "{}")
    d[tema] = origem
    db.set_setting(k, json.dumps(d, ensure_ascii=False))


def limpar_titulo(t: str, max_palavras: int = 15) -> str:
    """Título curto sem código interno, nome de arquivo nem nome de etapa."""
    t = _PREFIXO.sub("", t or "")
    # 074: "Pág. 3, item 6 (Documentação analisada): …" — o prefixo de página não é título
    t = re.sub(r"^item\s+[\d.]+(?:\s*\([^)]*\))?\s*[:—–-]\s*", "", t, flags=re.I)   # 079: "Item 10 (pág. 10):"
    t = re.sub(r"^p[aá]gs?\.\s*[\d, e]+(?:,\s*item\s*[\w.]+)?(?:\s*\([^)]*\))?\s*[:—–-]\s*", "", t, flags=re.I)
    t = re.sub(r"^(?:triagem bloqueada|orquestrador)\s*:\s*(?:PEND[ÊE]NCIA\s*:?\s*)?", "", t, flags=re.I)   # 064
    t = re.sub(r"^\w+:\s+", "", t) if re.match(r"^(montagem|selecao|pesquisa|revisao|entrega|extracao|triagem|localizacao):", t) else t
    # frase de abertura que só classifica o aviso ("Ressalva sobre a amostra, não reprovação (…).")
    t = re.sub(r"^(?:Ressalva ao avaliador:\s*|Ressalva sobre [^.]*\.\s*|Aviso ao avaliador:\s*)", "", t.strip(), flags=re.I)
    # 077-C1: "A P9 pede…" sem o código vira "O modelo do laudo pede…", nunca o artigo solto ("A pede")
    t = re.sub(r"^(?:[AaOo]s?)\s+(?:D-\d{3}|P\d{1,2}|K\d(?:\.\d+)?|F-[A-Z]?\d+)\s+", "O modelo do laudo ", t)
    t = _CODIGO.sub("", t)
    t = re.sub(r"^(?:[AaOo]s?)\s+(?=(?:pede|exige|determina|manda|prev[eê]|diz|requer|obriga)\b)", "O modelo do laudo ", t)
    t = sem_caminho(t)
    t = _ARQUIVO.sub("um arquivo", t)
    # 087: o título não é cortado em "pág." nem vem com página, item, "Camada A" ou caminho de arquivo
    t = re.sub(r"\s*\((?:[^()]*\b(?:p[aá]gs?\.|camada\s+[a-z]|_revisao/)[^()]*)\)", "", t, flags=re.I)
    t = re.sub(r",?\s*\(?\s*camada\s+[a-z]\s*\)?", "", t, flags=re.I)
    t = re.sub(r"\s*\((?:deztop|zap|olx|viva ?real|imovelweb|chaves na m[aã]o)[^)]*\)", "", t, flags=re.I)
    t = re.sub(r",?\s*\(?p[aá]gs?\.\s*[\d–-]+(?:\s*(?:,|e)\s*\d+)*\)?", "", t, flags=re.I)
    t = re.sub(r"^(?:itens?|o item|os itens)\s+[\d.]+(?:\s*(?:,|e)\s*[\d.]+)*\s*:\s*", "", t, flags=re.I)
    t = re.sub(r"(?i)\b(p[aá]gs?|qd|lt|n[ºo°]|av|dr)\.", lambda m: m.group(1) + "․", t)
    frases = [f.replace("․", ".") for f in re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ'\"‘“])", t.strip()) if f]
    t = frases[0] if frases else ""
    # 074-E: título genérico ("Divergência para o avaliador decidir") não diz nada: vale a frase seguinte
    if _GENERICO.match(t) and len(frases) > 1:
        t = frases[1]
    pal = t.split()
    if len(pal) > max_palavras:
        t = " ".join(pal[:max_palavras]).rstrip(",;:") + "…"
    return (t[:1].upper() + t[1:]) if t else t


def _num_area(job_id: str) -> str:
    try:
        from .agentes.selecao import escolha_area
        e = escolha_area(job_id) or {}
        v = e.get("valor")
        return f"{float(v):,.2f}".replace(",", "§").replace(".", ",").replace("§", ".") if v else ""
    except Exception:
        return ""


def classificar(job_id: str, pendencias: list[dict]) -> dict:
    """{"sozinho": [textos], "descartadas": [textos], "cards": [...]} — só os cartões vão para a tela."""
    j = db.job(job_id)
    dados = j.get("dados") or {}
    parte = dados.get("objeto_parte") or ""
    bloqueado = (j.get("status") or "") == "BLOQUEADO"   # parado: "seguir assim" não serve
    aceitas = set(json.loads(db.setting(CHAVE_ACEITAS.format(job_id)) or "[]"))
    sozinho, descartadas, cards, avisos = [], [], [], []
    texto_jdb: dict[str, str] = {}          # 087: assunto → texto (um por assunto)
    # 120: a conferência de coerência com os itens estruturados (lugares, quem decide, sugestão)
    itens_co = (((db.resultado(job_id, "entrega") or {}).get("coerencia") or {}).get("itens") or [])
    erros_co: list[dict] = []
    nao_feitos: list[str] = []
    numeros_doc: list[str] = []             # 101-3
    sem_foto = []
    sem_data = []
    contest, mapa = [], []
    vistos = set()

    def card(chave, titulo, opcoes, detalhe, impede=False, pagina=""):
        if chave in aceitas or chave in vistos:
            return
        vistos.add(chave)
        detalhe = _CODIGO.sub("", re.sub(r"(?m)^(?:[\w ]+:\s*)?revisor\s*\([^)]*\)\s*:\s*", "", detalhe or ""))
        detalhe = re.sub(r"(?im)^(?:triagem bloqueada|orquestrador)\s*:\s*(?:PEND[ÊE]NCIA\s*:?\s*)?", "", detalhe)   # 064
        detalhe = _ARQUIVO.sub("um arquivo", sem_caminho(detalhe))                                         # 074-E
        cards.append({"chave": chave, "titulo": titulo, "opcoes": opcoes, "detalhe": detalhe,
                      "impede": impede, "pagina": pagina})

    decididos = {k.split(":", 1)[1] for k in aceitas if k.startswith("decisao:")}
    assuntos: set[str] = set()
    try:                                     # 083-B6: decisão/resposta do avaliador é a fonte — não volta como pendência
        from .agentes.revisor import contra_decisao, decisoes_do_trabalho
        _, temas_decididos = decisoes_do_trabalho(job_id)
    except Exception:
        contra_decisao, temas_decididos = (lambda *_a: ""), set()
    AVISO_RESPONDIDO = {"idade": "Idade aparente: vale a sua resposta na vistoria.",
                        "medidas": "Medidas: vale a sua confirmação na vistoria (compatíveis com a escritura).",
                        "vizinhanca": "Pontos negativos do entorno: vale o que você informou no relato.",
                        "estado": "Estado de conservação: vale a sua classificação no relato."}
    for p in pendencias or []:
        txt = str(p.get("texto") or "")
        t = _n(txt)
        if t.startswith("nao consegui fazer"):
            # 117-2 / 120-7: pedido do avaliador que o sistema não conseguiu cumprir — entra na lista numerada
            if txt not in nao_feitos:
                nao_feitos.append(txt)
            continue
        if t.startswith("conferencia de coerencia") and itens_co:
            # 120-6 / D-100: só o que o avaliador decide vai para a lista; conta/número da conferência o JdB resolve
            for it in itens_co:
                if it.get("do_avaliador"):
                    erros_co.append(it)
                else:
                    sozinho.append(str(it.get("texto") or ""))
            continue
        tema_dec = contra_decisao(txt, temas_decididos) if temas_decididos else ""
        if tema_dec and tema_dec not in ("cv", "amostra"):
            aviso = AVISO_RESPONDIDO.get(tema_dec, "")
            if aviso and aviso not in avisos:
                avisos.append(aviso)
            continue
        if tema_dec in ("cv", "amostra"):
            decididos.add(tema_dec)
        pag = (re.search(r"p[aá]gina[s]?\s+(\d+)", txt, re.I) or [None, ""])[1]
        # 077-A3: decisão que o avaliador já tomou (CV alto, amostra mantida) não volta: só aviso, uma vez
        tema = _tema(t)
        if tema and ("confirmad" in t and ("avaliador" in t or "por ele" in t)):
            decididos.add(tema)              # o próprio texto diz que o avaliador já confirmou
        if tema and tema in decididos:
            if f"aviso:{tema}" not in assuntos:
                assuntos.add(f"aviso:{tema}")
                avisos.append(AVISO_DECIDIDO.get(tema, "Decisão que você já tomou. Não reprova o laudo."))
            continue
        if tema and f"pergunta:{tema}" in assuntos:
            continue                         # o mesmo assunto já virou um card
        if tema and "contestacao simulada" not in t:
            assuntos.add(f"pergunta:{tema}")
            card(f"decisao:{tema}", PERGUNTA_TEMA[tema],
                 [{"rotulo": "Manter assim", "acao": "aceitar", "recomendada": True,
                   "linha": "Fica gravado no trabalho; o revisor não pergunta de novo."},
                  {"rotulo": "Rever os referenciais", "acao": "candidatos"}], txt, pagina=pag)
            continue
        pag = (re.search(r"p[aá]gina[s]?\s+(\d+)", txt, re.I) or [None, ""])[1]
        # pendência errada pela regra do Alan
        # textos gerados pelo próprio sistema (prefixo fixo) vêm antes das regras por palavra
        # 074-E4: divergência de documento que NÃO muda o laudo (endereço de cadastro da contribuinte, nº da
        # declaração no corpo × cabeçalho) é aviso, não pendência que trava
        if (("diverg" in t or "difere" in t or "diferente" in t or "nao bate" in t)
                and (("endereco" in t and any(k in t for k in ("contribuinte", "cadastro", "correspondencia", "comunicado")))
                     or ("declaracao" in t and any(k in t for k in ("numero", " n ", "cabecalho"))))):
            avisos.append(limpar_titulo(txt, 30))
            continue
        # 074: ressalva que o avaliador JÁ confirmou (ex.: CV alto) não volta como decisão — fica um aviso só
        if "confirmad" in t and ("avaliador" in t or "por ele" in t) and ("nao reprova" in t or "ressalva" in t or "aviso" in t):
            if not any("confirmou" in a for a in avisos):
                avisos.append("Ressalva sobre a amostra que você já confirmou (dispersão alta). Não reprova o laudo.")
            continue
        if "contestacao simulada" in t:
            # 079-3: cada ponto com o seu botão — o que é da extensão vai para o card da extensão; o que é
            # erro do próprio JdB (datas/fuso) ele corrige; a referência da malha vira pergunta (D-069)
            if any(k in t for k in ("captura", "data de acesso", "sem data", "sem foto")):
                sem_data.append(txt)
                continue
            if "assinatura" in t and any(k in t for k in ("consulta", "mapa", "data")):
                sozinho.append(txt)
                continue
            mref = re.search(r"r\$\s*([\d.]+,\d{2})", txt, re.I)
            if mref and any(k in t for k in ("referencia", "fipe", "sefaz", "malha")):
                continue                       # 090-1: um gerador só (o passo D-069), com o valor do documento
            contest.append(txt)               # um cartão só para os outros pontos (um de cada vez)
            continue
        if "com os dados novos o valor muda" in t:     # 082-5: o valor mudou com dado novo → confere antes
            card("valor_mudou", txt.strip(),
                 [{"rotulo": "Conferir os anúncios", "acao": "candidatos", "recomendada": True},
                  {"rotulo": "Confirmar o valor novo", "acao": "confirmar_valor"}], "", impede=True)
            continue
        if "a amostra mudou depois que voce fixou o unitario" in t:   # 082-4: trava de valor
            card("amostra_mudou", txt.strip(),
                 [{"rotulo": "Usar a média", "acao": "usar_media", "recomendada": True},
                  {"rotulo": "Confirmar de novo", "acao": "confirmar_valor"}], "", impede=True)
            continue
        if "conferencia de coerencia" in t and ("(documento)" in t or "frase vetada" in t):
            # 101-2/3: número de documento trocado ou frase vetada pelo avaliador: impede aprovar, sem "Seguir assim"
            numeros_doc.append(txt)
            continue
        if "conferencia de coerencia" in t:     # 087 tipo 1: erro do próprio JdB (corrige na montagem; se sobrar, um passo)
            texto_jdb.setdefault(_assunto(t), txt)
            continue
        if "tarja" in t and ("anexo" in t or "escritura" in t or "documento" in t):
            descartadas.append(txt)            # D-062: laudo do cliente vai sem tarja
            continue
        if "padrao e idade a conferir" in t or ("padrao" in t and "idade" in t and "conferir" in t):
            card("padrao_idade", "Padrão e idade dos anúncios ainda não foram conferidos.",
                 [{"rotulo": "Conferir os anúncios", "acao": "candidatos", "recomendada": True},
                  {"rotulo": "Seguir assim", "acao": "aceitar"}], txt)
            continue
        if "sem foto principal" in t or "sem a foto principal" in t:
            sem_foto.append(txt)
            continue
        if "foto principal" in t and ("amostra" in t or "anuncio" in t or "referencia" in t):
            continue        # o mesmo assunto do cartão "N anúncios sem foto principal" (não repete)
        if "data de acesso nao registrada" in t:
            sem_data.append(txt)
            continue
        if "nenhum documento do imovel" in t or ("triagem bloqueada" in t and "document" in t):
            card("doc_imovel", "Falta o documento do imóvel: matrícula, escritura ou IPTU.",
                 [{"rotulo": "Enviar o documento", "acao": "enviar_arquivo", "tipo": "documento",
                   "refazer": "triagem", "recomendada": True}], txt, impede=True, pagina=pag)
            continue
        if "print da medicao" in t or ("medicao" in t and "print" in t):
            card("print_medicao", f"Falta o print da medição{(' do ' + parte) if parte else ''}.",
                 [{"rotulo": "Enviar print", "acao": "enviar_foto", "recomendada": True},
                  {"rotulo": "Medir de novo", "acao": "refazer_mapa"}], txt, impede=bool(p.get("grave")), pagina=pag)
            continue
        if "confira a capa" in t:        # 077-2 (D-079)
            card("capa", "Confira a capa: o contorno vermelho acompanha o imóvel?",
                 [{"rotulo": "Está certo", "acao": "aceitar", "recomendada": True},
                  {"rotulo": "Ajustar", "acao": "ver_capa",
                   "linha": "Em Ajustar, abra os Detalhes do trabalho e marque outra foto da capa; o contorno é refeito."}],
                 "A capa usa a foto da fachada com o contorno do imóvel (muro, telhado até a cumeeira, portão e coluna dos medidores).")
            continue
        if "mapa digital" in t and any(a.get("tipo") == "mapa_digital" for a in db.arquivos(job_id)):
            descartadas.append(txt)          # o print já está no laudo
            continue
        if "secoes sem texto" in t or "fato do exemplo" in t or "reescrever" in t:
            sozinho.append(txt)              # 079-3: erro da redação do próprio JdB, não decisão do avaliador
            continue
        if "repetido descartado" in t or "paragrafo repetido" in t:
            sozinho.append(txt)              # 077-A4: o JdB já tirou o repetido
            continue
        if "mapa digital" in t:          # 077-1(a) (D-077): o avaliador anexa o print, ou segue sem
            card("mapa_digital", "Falta a imagem do Mapa Digital Fácil. Enviar o print?",
                 [{"rotulo": "Gerar automático", "acao": "mapa_digital", "recomendada": True},
                  {"rotulo": "Enviar o print", "acao": "enviar_arquivo", "tipo": "mapa_digital", "refazer": "montagem"},
                  {"rotulo": "Seguir sem", "acao": "aceitar", "linha": "O laudo sai sem o anexo do Mapa Digital Fácil."}], txt)
            continue
        if "localizacao" in t and any(k in t for k in ("ausente", "sem imagem", "nao gerad", "falta", "sem localizacao")):
            # 075-B: o JdB gera a imagem pelo pin; sem pin, pede o link do Maps
            tem_pin = bool((dados or {}).get("pin_maps"))
            card("mapa_falta", "Falta a imagem de localização com o lote demarcado.",
                 [{"rotulo": "Gerar pelo pin", "acao": "refazer_mapa", "recomendada": True}] if tem_pin else
                 [{"rotulo": "Colar o link do Google Maps", "acao": "pin", "recomendada": True}], txt, impede=bool(p.get("grave")))
            continue
        if ("mapa" in t and ("cortad" in t or "recorte" in t or "demarcacao" in t)) or "poligono" in t or "contorno" in t:
            mapa.append(txt)
            continue
        if "objeto" in t and ("ambigu" in t or "lote inteiro" in t or "parte" in t):
            area = _num_area(job_id)
            nome = parte or "a parte"
            card("objeto", f"O laudo avalia só {('o ' + nome) if parte else 'uma parte'} ou o lote inteiro?",
                 [{"rotulo": f"Só {('o ' + nome) if parte else 'a parte'}{(' – ' + area + ' m²') if area else ''}",
                   "acao": "alinhamento", "id": "objeto", "resposta": "Só uma parte", "texto": nome, "recomendada": True},
                  {"rotulo": "Lote inteiro", "acao": "alinhamento", "id": "objeto", "resposta": "Imóvel inteiro"},
                  {"rotulo": "Ver no mapa", "acao": "ver_mapa"}], txt, impede=True, pagina=pag)
            continue
        if "campo essencial pendente" in t:
            campo = txt.split(":", 1)[-1].strip()
            card(f"campo:{campo}", f"Falta {campo.lower()}.", [{"rotulo": "Preencher", "acao": "editar_campo",
                                                                 "campo": campo, "recomendada": True}], txt, impede=True)
            continue
        # erros do sistema: corrige sozinho (não vai para o avaliador)
        if (any(x in t for x in ("identificadores internos", "grafia", "rotulo de documento ausente", "anexo v",
                                  "comeca no fim da pagina", "orfa", "validade de",
                                  "prazo", "sem fonte", "nao consta de nenhum dado", "pdf nao gerado"))
                or (("(visual/montagem)" in t or "(redacao/redacao)" in t or "/montagem)" in t)
                    and not (p.get("grave") and "revisor (" in t))):
            # 113-1: apontamento GRAVE do revisor que sobrou depois das voltas não fica escondido em "corrigindo
            # sozinho": vira o passo do texto (Tentar de novo / Escreva como deve ficar); "pronto" só com zero grave
            sozinho.append(txt)
            continue
        if "area do cartao" in t:              # 090-4: texto antigo, desmentido pela 082-3 (o laudo usa a área guardada)
            descartadas.append(txt)
            continue
        # 087 tipo 2: aviso (o próprio texto diz que não é reprovação, decisão já tomada, correção automática)
        if any(k in t for k in _MARCAS_AVISO) and "contestacao simulada" not in t:
            a_ = _assunto(t)
            if f"aviso:{a_}" not in assuntos:
                assuntos.add(f"aviso:{a_}")
                avisos.append(limpar_titulo(txt, 25).rstrip("?"))
            continue
        # 087 tipo 1: erro de texto ou de montagem do próprio JdB (revisor, conferência de coerência)
        if (any(k in t for k in _MARCAS_TEXTO) and "contestacao simulada" not in t and "confira a capa" not in t
                and not ("diverg" in t and any(d in t for d in ("matricula", "iptu", "escritura")))):   # área do documento: decisão
            a_ = _assunto(t)
            if a_ not in texto_jdb:
                texto_jdb[a_] = txt
            continue
        if "ressalva" in t and ("referencia" in t or "amostra" in t):
            card(f"ressalva:{_chave_estavel(txt)}", limpar_titulo(txt),
                 [{"rotulo": "Rever os referenciais", "acao": "candidatos", "recomendada": True},
                  {"rotulo": "Seguir assim", "acao": "aceitar"}], txt, pagina=pag)
            continue
        # 075-B: sem ação possível não há "Resolver" — só [Seguir assim] / [Entendi], com o que acontece
        assunto = re.sub(r"[\d\W]+", " ", _n(limpar_titulo(txt, 8)))[:60]
        if f"outro:{assunto}" in assuntos:
            continue                         # 077-A1: uma pendência por problema
        assuntos.add(f"outro:{assunto}")
        card(f"outro:{_chave_estavel(assunto)}", pergunta(limpar_titulo(txt), bloqueado),
             [{"rotulo": "Entendi" if bloqueado else "Seguir assim", "acao": "aceitar", "recomendada": True,
               "linha": "Fica anotado e o laudo segue assim." if not bloqueado else "Fica anotado; o laudo continua parado pelo item acima."}],
             txt, impede=bool(p.get("grave")), pagina=pag)
    if mapa:
        card("mapa", "O mapa da localização precisa ser refeito.",
             [{"rotulo": "Refazer pelo pin", "acao": "refazer_mapa", "recomendada": True},
              {"rotulo": "Seguir assim", "acao": "aceitar"}], "\n\n".join(mapa))
    if contest:
        n = len(contest)
        pontos = []
        for x in contest:
            corpo = x.split("—", 1)[-1]
            corpo = corpo.split(":", 1)[-1].strip() if ":" in corpo.split("Como reforçar")[0] else corpo.strip()
            ataque, _, reforco = corpo.partition("Como reforçar:")
            pontos.append(f"• {ataque.strip().rstrip('.')}." + (f" Como reforçar: {reforco.strip()}" if reforco else ""))
        card("contestacao", f"A parte contrária atacaria {n} {'ponto' if n == 1 else 'pontos'} do laudo. Quer reforçar?",
             [{"rotulo": "Ver como reforçar", "acao": "detalhe", "recomendada": True},
              {"rotulo": "Seguir assim", "acao": "aceitar"}], "\n\n".join(pontos), impede=True)
    if sem_foto or sem_data:
        # 077-A5: uma pendência por anúncio e por foto viram UM card, com os links dos anúncios
        refs = [r for r in db.candidatos(job_id) if r.escolhido or r.decisao in ("entra", "comparacao")]   # 090-3
        # 153-4: pesquisa de campo não tem anúncio: a data é a da pesquisa e a foto foi confirmada no cadastro
        refs = [r for r in refs if not getattr(r, "pesquisa_campo", False)]
        # 096-10: a foto que é arte tem o passo próprio (com a galeria): não conta aqui
        faltam = [r for r in refs if (not r.foto and not getattr(r, "foto_arte", False)) or not (getattr(r, "acessado_em", "") or "")]
        if refs and not faltam:                # 087: 6 de 6 recebidos → o texto da montagem anterior ficou velho
            sem_foto, sem_data = [], []
        n = len(faltam) or max(len(sem_foto), len(sem_data))
        o_que = " e ".join(x for x in ("sem foto" if sem_foto else "", "sem data de acesso" if sem_data else "") if x)
    if sem_foto or sem_data:
        um = faltam[0] if len(faltam) == 1 else None    # 096-10: um só → diz qual e o que falta
        titulo_ext = (f"Anúncio {um.n} ({um.rua or um.bairro or um.portal}): falta "
                      + " e ".join(x for x in ("a foto" if not um.foto else "", "a data de acesso" if not (um.acessado_em or "") else "") if x)
                      + ". Abrir no seu Chrome e enviar ao JdB?") if um else             f"{n} {'anúncio' if n == 1 else 'anúncios'} {o_que}. Abra cada um no seu Chrome e toque em Enviar ao JdB?"
        card("extensao", titulo_ext,
             [{"rotulo": "Vou abrir", "acao": "extensao", "recomendada": True},
              {"rotulo": "Seguir assim", "acao": "aceitar", "linha": "A tabela de amostras sai sem a foto e sem a data desses anúncios."}],
             "\n".join(f"Anúncio {r.n}: {r.link}" for r in faltam) or "\n".join(sem_foto + sem_data), impede=bool(sem_foto))
        if cards and cards[-1]["chave"] == "extensao":      # 079-1: a tela abre os anúncios e conta "N de M recebidos"
            cards[-1]["links"] = [r.link for r in faltam]
            cards[-1]["total"] = len(refs)
            cards[-1]["recebidos"] = len(refs) - len(faltam)
    # 082-2: a página do anúncio mostrou dado diferente do guardado → pergunta, o guardado vale até decidir
    from .routes import ROTULO_CAMPO, _fmt_campo
    for r in db.candidatos(job_id):
        if not (r.escolhido or r.decisao in ("entra", "comparacao")):
            continue
        for k, v in (getattr(r, "divergencia_pagina", None) or {}).items():
            g = getattr(r, k, None)
            card(f"divergencia:{r.n}:{k}",
                 f"O anúncio {r.n} hoje mostra {ROTULO_CAMPO.get(k, k)} {_fmt_campo(k, v)}; o laudo usa {_fmt_campo(k, g)}.",
                 [{"rotulo": f"Manter {_fmt_campo(k, g)}", "acao": "divergencia", "n": r.n, "campo": k, "manter": True, "recomendada": True},
                  {"rotulo": f"Trocar para {_fmt_campo(k, v)}", "acao": "divergencia", "n": r.n, "campo": k}], r.link)
    # 083-B5 (D-069): laudo para justificar valor perante o fisco, com valor de referência e sem item de comparação:
    # o JdB PERGUNTA (a busca automática está desligada, então ele não acha sozinho)
    ref = valor_referencia_fisco(job_id)       # 093-4: o nome do campo varia ("itcd_valor_referencia_sefaz"…)
    if ref and not any(r.decisao == "comparacao" for r in db.candidatos(job_id)) and not db.setting(f"sem_comparacao:{job_id}"):
        try:
            ref_txt = f"{float(ref):,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
        except (TypeError, ValueError):
            ref_txt = str(ref)
        card("comparacao_d069", f"Laudo para justificar valor perante o fisco: tem anúncios de padrão superior abaixo de "
                                f"R$ {ref_txt} para mostrar como comparação?",
             [{"rotulo": "Adicionar", "acao": "adicionar_comparacao", "recomendada": True},
              {"rotulo": "Não tenho", "acao": "aceitar", "linha": "O laudo segue sem o item de comparação."}],
             "Entram num item próprio, depois do tratamento dos dados, fora da amostra e do cálculo.")
    # 109-5 (105-2b): idade aparente estimada pela foto (o anúncio não dizia) → confirmar em 1 toque
    for r in db.candidatos(job_id):
        if ((r.escolhido or r.decisao in ("entra", "comparacao")) and getattr(r, "idade_fonte", "") == "fotos"
                and (r.idade_aparente or "").strip()):
            card(f"idade_foto:{r.n}", f"Anúncio {r.n}: o anúncio não diz a idade. Pelas fotos, parece "
                                      f"{r.idade_aparente.strip().rstrip('.')}. Confere?",
                 [{"rotulo": "Confere", "acao": "aceitar", "recomendada": True,
                   "linha": "A idade aparente vale como confirmada por você."},
                  {"rotulo": "Corrigir", "acao": "corrigir_idade", "n": r.n}], r.link)
    # 081-5: foto principal que é arte de anúncio (banner "À VENDA…"): sugere a próxima foto da galeria
    for r in db.candidatos(job_id):
        from .routes import _NAO_E_FOTO
        from .leitura_pagina import fotos_unicas
        fotos = fotos_unicas([u for u in (getattr(r, "fotos_url", None) or []) if not _NAO_E_FOTO.search(u)], 12)   # 089-3 / 096-7
        if (r.escolhido or r.decisao in ("entra", "comparacao")) and getattr(r, "foto_arte", False) and len(fotos) >= 2:
            card(f"foto_arte:{r.n}", f"A 1ª foto do anúncio {r.n} é uma arte de anúncio, não a casa. Qual foto mostra a casa?",
                 [{"rotulo": "Usar a sugerida", "acao": "trocar_foto", "n": r.n, "url": fotos[1], "sugerida": True, "recomendada": True},
                  {"rotulo": "Manter", "acao": "trocar_foto", "n": r.n, "manter": True}], r.link)
            if cards and cards[-1]["chave"] == f"foto_arte:{r.n}":
                cards[-1]["imagem"] = fotos[1]
                cards[-1]["galeria"] = {"n": r.n, "fotos": fotos[1:12]}      # 088-1: o avaliador toca na que mostra a casa
        elif (r.escolhido or r.decisao in ("entra", "comparacao")) and getattr(r, "foto_arte", False):
            # 093-A-10: sem galeria para sugerir, pergunta (reenviar pela extensão traz as fotos do anúncio)
            card(f"foto_arte:{r.n}", f"A foto principal do anúncio {r.n} parece arte de propaganda, não a casa. "
                                     "Reenviar o anúncio pela extensão para escolher outra?",
                 [{"rotulo": "Vou reenviar", "acao": "extensao", "recomendada": True},
                  {"rotulo": "Manter", "acao": "trocar_foto", "n": r.n, "manter": True}], r.link)
            if cards and cards[-1]["chave"] == f"foto_arte:{r.n}":
                cards[-1]["links"] = [r.link]
    if numeros_doc:
        card("numero_documento", "O laudo traz número de documento diferente do documento (ou frase que você vetou). "
                                 "Refazer o texto?",
             [{"rotulo": "Refazer o texto", "acao": "reabrir", "etapa": "redacao", "recomendada": True},
              {"rotulo": "Ver o que está errado", "acao": "detalhe"},
              {"rotulo": "Está certo assim", "acao": "aceitar",          # 104-1b: o alarme nunca prende o avaliador
               "linha": "Fica gravado que você conferiu e o laudo está certo nesse ponto."}],
             "\n".join(f"• {limpar_titulo(x, 40)}" for x in numeros_doc), impede=True)
    # 101-1 (d): o reforço automático da contestação aparece com [Desfazer]
    import json as _json
    reforcos = _json.loads(db.setting(f"reforcos:{job_id}") or "[]")
    if reforcos and db.setting(f"reforco_contestacao:{job_id}") and not db.setting(f"reforco_desfeito:{job_id}"):
        card("reforco", f"Reforcei o texto do laudo em {len(reforcos)} {'ponto' if len(reforcos) == 1 else 'pontos'} da "
                        "contestação simulada (só explicação, sem número novo). Manter?",
             [{"rotulo": "Manter", "acao": "aceitar", "recomendada": True},
              {"rotulo": "Desfazer", "acao": "desfazer_reforco"}],
             "\n".join(f"• {x[:200]}" for x in reforcos))
    # 087 tipo 1: o que é do próprio JdB e ficou depois das voltas vira UM passo, com a lista dentro
    erros = _lista_de_erros(texto_jdb, erros_co, nao_feitos)        # 120: numerada, na ordem das páginas
    _trechos_que_existem(job_id, erros)                              # 144: o "procure" só com texto que está no laudo
    _frases_do_word(job_id, erros)                                   # 171-1: a frase exata do Word para o Ctrl+F
    if erros and not texto_jdb:
        texto_jdb = {f"e{e['n']}": e["titulo"] for e in erros}
    if texto_jdb:
        n = len(erros) or len(texto_jdb)
        um_txt = limpar_titulo(next(iter(texto_jdb.values())), 18).rstrip(" .?") if n == 1 else ""   # 097-4: diz qual
        # 139-4: o título diz o que o avaliador faz agora (sem "Tentar de novo?", que não tinha botão à vista)
        card("texto_jdb", (f"Falta 1 ponto no laudo: {um_txt}. Corrija no seu Word, depois de baixar para a revisão humana." if um_txt else
                           f"Faltam {n} pontos no laudo. Corrija no seu Word, depois de baixar para a revisão humana."),
             [{"rotulo": "Tentar de novo", "acao": "reabrir", "etapa": "redacao", "recomendada": True},
              {"rotulo": "Ver a lista", "acao": "detalhe"},
              {"rotulo": "Seguir assim", "acao": "aceitar", "linha": "O laudo segue com esses pontos; você pode corrigir à mão."}],
             "\n".join(f"• {limpar_titulo(x, 30)}" for x in texto_jdb.values()))
        if cards and cards[-1]["chave"] == "texto_jdb":     # 089-4: o trecho e o campo "Me diga como corrigir"
            cards[-1]["pontos"] = [{"texto": limpar_titulo(x, 40), "trecho": _trecho(x)} for x in texto_jdb.values()]
            cards[-1]["erros"] = erros
            cards[-1]["impede"] = cards[-1]["impede"] or bool(nao_feitos)
        sozinho.extend(texto_jdb.values())
    cards.sort(key=lambda c: (not c["impede"], c["chave"] == "texto_jdb"))
    # 087: trava de quantidade — nunca mais que MAX_PASSOS; o excedente vai junto num passo só
    if len(cards) > MAX_PASSOS:
        fica, resto = cards[:MAX_PASSOS - 1], cards[MAX_PASSOS - 1:]
        fica.append({"chave": "mais", "titulo": f"Mais {len(resto)} pontos para conferir. Ver?",
                     "opcoes": [{"rotulo": "Ver a lista", "acao": "detalhe", "recomendada": True},
                                {"rotulo": "Seguir assim", "acao": "aceitar"}],
                     "detalhe": "\n".join(f"• {c['titulo']}" for c in resto), "impede": False, "pagina": ""})
        cards = fica
    return {"sozinho": sozinho, "descartadas": descartadas, "cards": cards, "avisos": avisos,
            # 074-E2: como o João fala — tudo numa frase, só o que depende do avaliador
            "resumo": (f"Revisei o laudo. {'Falta 1 coisa que depende' if len(cards) == 1 else f'Faltam {len(cards)} coisas que dependem'} de você."
                       if cards else "Revisei o laudo. Nada depende de você."),
            "linha_sozinho": (f"Corrigindo sozinho: {len(sozinho)} {'ajuste' if len(sozinho) == 1 else 'ajustes'} de montagem"
                              if sozinho else "")}


_PAG = re.compile(r"(?i)(?:p[áa]g(?:ina)?s?\.?\s*|_revisao/pagina-0*)(\d+)")
_ITEM = re.compile(r"(?i)\bite(?:m|ns)\s+(\d+(?:\.\d+)*)")


def _titulo_erro(txt: str) -> str:
    """126-1: título curto, sem repetir página/item (que já aparecem antes) — a 1ª frase do apontamento."""
    t = re.sub(r"(?i)^\s*revisor\s*\([^)]*\)\s*:\s*", "", txt or "")
    t = re.sub(r"\s*\(_revisao/[^)]*\)", "", t)
    t = re.sub(r"(?i)^\s*(?:(?:na\s+)?p[áa]g(?:ina)?\.?\s*\d+|(?:no\s+)?item\s+\d+(?:\.\d+)*)(?:\s*[,·–-]\s*"
               r"(?:(?:na\s+)?p[áa]g(?:ina)?\.?\s*\d+|(?:no\s+)?item\s+\d+(?:\.\d+)*))*\s*[:,–-]?\s*", "", t)
    t = re.sub(r"\s*\([^()]*\)", "", t)          # 139-2: parênteses saem inteiros (nunca "… (pág.")
    t = re.split(r"(?<=[.!?])\s+", t.strip(), maxsplit=1)[0].strip(" :;,–-")
    if len(t.split()) < 4:                         # sobrou pouco: a frase inteira do apontamento, sem os parênteses
        t = re.sub(r"\s*\([^()]*\)", "", re.sub(r"(?i)^\s*revisor\s*\([^)]*\)\s*:\s*", "", txt or "")).strip()
        t = re.split(r"(?<=[.!?])\s+", t, maxsplit=1)[0].strip(" :;,–-")
    # 139-2: página/item e traço solto no começo saem também na frase inteira (já aparecem antes do título)
    t = re.sub(r"(?i)^[\s·•—–:,-]*(?:(?:na\s+)?p[áa]g(?:ina)?\.?\s*\d+|(?:no\s+)?item\s+\d+(?:\.\d+)*|[·•—–:,-])"
               r"(?:[\s·•—–:,-]*(?:(?:na\s+)?p[áa]g(?:ina)?\.?\s*\d+|(?:no\s+)?item\s+\d+(?:\.\d+)*))*[\s·•—–:,-]*", "", t)
    t = t[:1].upper() + t[1:]
    t = limpar_titulo(t, 999).rstrip(" .…")             # 142-5: frase inteira, nunca cortada por tamanho
    if t.count("(") > t.count(")"):                # nunca parêntese aberto no fim
        t = t[:t.rfind("(")].rstrip(" ,;:–-")
    return (t or "Ponto para conferir no laudo") + "."


def _lista_de_erros(texto_jdb: dict, erros_co: list[dict], nao_feitos: list[str]) -> list[dict]:
    """120: cada erro numa linha — onde (página/item), o que está errado, o que está no laudo, os lugares para o
    [Mostrar no PDF] e a sugestão de um toque, quando houver. Na ordem das páginas."""
    out = []
    for txt in list(texto_jdb.values()):
        if _n(txt).startswith("conferencia de coerencia") and erros_co:
            continue
        m, it = _PAG.search(txt), _ITEM.search(txt)
        trecho = _trecho(txt)
        pag = int(m.group(1)) if m else None
        out.append({"pagina": pag, "item": it.group(1) if it else "", "titulo": _titulo_erro(txt), "no_laudo": trecho,
                    "lugares": [{"pagina": pag, "trecho": trecho}] if pag else [], "sugestao": "", "valor_sugerido": "",
                    "campo": "", "tipo": "texto", "origem": txt})
    for itc in erros_co:
        dado = _n(str(itc.get("dado") or ""))
        titulo = ("As datas de referência do valor não batem." if "data" in dado
                  else "O bairro está escrito de dois jeitos." if "bairro" in dado
                  else limpar_titulo(str(itc.get("texto") or ""), 999).rstrip(" .…") + ".")
        lugares = [x for x in (itc.get("lugares") or []) if isinstance(x, dict)]
        campo = "data_base" if "data" in dado else "bairro" if "bairro" in dado else ""
        out.append({"pagina": (lugares[0].get("pagina") if lugares else None), "item": "", "titulo": titulo,
                    "no_laudo": "  ·  ".join(f"pág. {x.get('pagina')}: «{x.get('trecho')}»" for x in lugares[:2])
                                or str(itc.get("encontrado") or ""),
                    "lugares": lugares, "sugestao": str(itc.get("sugestao") or ""),
                    "valor_sugerido": str(itc.get("valor_sugerido") or ""), "campo": campo, "tipo": "dado" if campo else "texto",
                    "origem": str(itc.get("texto") or "")})
    for txt in nao_feitos:
        corpo = re.sub(r"(?i)^n[ãa]o consegui fazer:\s*", "", txt)
        pedido, _, motivo = corpo.partition(" — porque ")
        m = _PAG.search(pedido)
        out.append({"pagina": int(m.group(1)) if m else None, "item": "", "tipo": "pedido",
                    "titulo": f"Seu pedido não foi feito: {limpar_titulo(pedido, 999).rstrip(' .…')}.",
                    "no_laudo": f"Motivo: {motivo.strip()}" if motivo else "", "lugares": [], "sugestao": "",
                    "valor_sugerido": "", "campo": "", "origem": txt})
    out.sort(key=lambda e: (e["pagina"] is None, e["pagina"] or 0))
    out = _sem_repetidos(out)                  # 134-2: o mesmo ponto apontado duas vezes vira um só
    for i, e in enumerate(out, 1):
        e["n"] = i
        e["explicacao"] = _explicacao_erro(e.get("origem", ""), e["titulo"]) if e["tipo"] != "pedido" else ""
        # 144-3: "No laudo está" só quando o trecho É o erro (texto citado); em quebra de página, imagem etc. não aparece
        if e["tipo"] == "texto" and _SO_LUGAR.search(f"{e['titulo']} {e.get('origem', '')}"):
            e["no_laudo"] = ""
    return out


def _trechos_que_existem(job_id: str, erros: list[dict]) -> None:
    """144: o trecho citado pelo revisor às vezes não está no laudo (é uma frase dele, ou de um documento). O cartão só
    manda procurar o que existe no PDF; o que não existe sai (a página continua)."""
    try:
        import pymupdf
        from .orquestrador import _arquivos_finais
        pdf = _arquivos_finais(job_id)["pdf"]
        if not pdf.is_file():
            return
        with pymupdf.open(pdf) as d:
            todo = _n(" ".join(" ".join(pg.get_text().split()) for pg in d))
    except Exception:
        return
    def existe(t: str) -> bool:
        t = _n(" ".join((t or "").split()))
        return bool(t) and (t in todo or t[:40] in todo)
    for e in erros:
        for lg in e.get("lugares") or []:
            if lg.get("trecho") and not existe(lg["trecho"]):
                lg["trecho"] = ""
        if e.get("tipo") == "texto" and e.get("no_laudo") and not existe(e["no_laudo"]):
            e["no_laudo"] = ""


def _frases_do_word(job_id: str, erros: list[dict]) -> None:
    """171-1: para cada ponto, a frase do laudo EXATAMENTE como está no Word (5 a 12 palavras, que só aparece uma vez),
    para o avaliador copiar e achar com Ctrl+F. Espaços repetidos viram um; aspas e hífens ficam como no Word."""
    try:
        import docx as _docx
        from .orquestrador import _arquivos_finais
        arq = _arquivos_finais(job_id)["docx"]
        if not arq.is_file():
            return
        d = _docx.Document(arq)
        # cada parágrafo conta sozinho (o Ctrl+F do Word não acha texto que atravessa parágrafos, nem dentro da célula)
        pars = [p.text for p in d.paragraphs] + [q.text for t in d.tables for r in t.rows for c in r.cells for q in c.paragraphs]
    except Exception:
        return
    pars = [" ".join(p.split()) for p in pars if p and p.strip()]
    todo = "\n".join(pars)
    for e in erros:
        tr = " ".join((next((lg.get("trecho") for lg in e.get("lugares") or [] if lg.get("trecho")), "") or "").split())
        e["frase"] = (_frase_unica(pars, todo, tr) if tr else "") or _frase_pelo_numero(pars, todo, e)


def _frase_pelo_numero(pars: list[str], todo: str, e: dict) -> str:
    """171-1 (reserva): sem trecho citado, acha no Word a data/número que o título cita (ex.: "28/10/2026") e devolve
    a menor frase de 5 a 12 palavras ao redor dele que só aparece uma vez."""
    for tok in _SINAL.findall(f"{e.get('titulo', '')} {e.get('explicacao', '')}"):
        for p in pars:
            if tok not in p:
                continue
            ws = p.split()
            k = next((i for i, w in enumerate(ws) if tok in w), None)
            if k is None:
                continue
            for n in range(5, 13):
                for ini in range(max(0, k - n + 1), k + 1):
                    f = " ".join(ws[ini:ini + n])
                    if len(f.split()) == n and tok in f and todo.count(f) == 1:
                        return f
    for tok in _SINAL.findall(f"{e.get('titulo', '')} {e.get('explicacao', '')}"):
        if tok in todo:                         # só existe sozinho (ex.: numa célula de tabela): o número, com quantas vezes
            e["frase_vezes"] = todo.count(tok)
            return tok
    return ""


def _frase_unica(pars: list[str], todo: str, trecho: str) -> str:
    """A menor janela de 5 a 12 palavras, começando no trecho, que aparece uma única vez no Word."""
    alvo = _n(trecho)[:60]
    for p in pars:
        i = _n(p).find(alvo[:40])
        if i < 0 or not alvo:
            continue
        palavras = p[i:].split() if len(_n(p)) == len(p.casefold()) else p.split()
        if p[i:].split():
            palavras = p[i:].split()
        for n in range(5, 13):
            if len(palavras) < n:
                break
            f = " ".join(palavras[:n])
            if todo.count(f) == 1:
                return f
        if len(palavras) < 5:                      # trecho no fim do parágrafo: começa antes, até 12 palavras
            antes = p[:i].split()
            for k in range(1, 8):
                f = " ".join(antes[-k:] + palavras)
                if len(f.split()) >= 5 and todo.count(f) == 1:
                    return " ".join(f.split()[:12])
        return " ".join(palavras[:12])
    return ""


_SO_LUGAR = re.compile(r"(?i)quebra|folha em branco|p[áa]gina (?:quase )?vazia|metade da (?:folha|p[áa]gina)|imagem|mapa|foto|"
                       r"figura|margem|espa[çc]o em branco|tabela (?:cortada|partida)|rodap[ée]|cabe[çc]alho")


def _explicacao_erro(txt: str, titulo: str) -> str:
    """144-1/2: o que está errado e por quê, INTEIRO, sem rótulo interno ("revisor (visual):", caminho de arquivo,
    código) e sem repetir o título. Nunca cortado com reticências."""
    t = _PREFIXO.sub("", txt or "")
    t = re.sub(r"(?i)^\s*revisor\s*\([^)]*\)\s*:\s*", "", t)
    t = re.sub(r"\s*\(_revisao/[^)]*\)", "", t)
    t = re.sub(r"\s*\([^()]*(?:#p\d+|/)[^()]*\)", "", t)                    # "(documento/arquivo#p1)": referência interna
    t = re.sub(r"(?i)\s*\(\s*p[áa]gs?\.\s*[\d\s,e–-]+\)\s*,?", " ", t)       # "(pág. 3 e 4)," já aparece no cartão
    t = re.sub(r"(?i),?\s*\(?\s*camada\s+[a-z]\s*\)?", "", t)
    t = _CODIGO.sub("", sem_caminho(t))
    t = _ARQUIVO.sub("um arquivo", t)
    t = re.sub(r"(?i)^[\s·•—–:,-]*(?:(?:na\s+)?p[áa]g(?:ina)?\.?\s*\d+|(?:no\s+)?item\s+\d+(?:\.\d+)*)"
               r"(?:[\s·•—–:,-]*(?:(?:na\s+)?p[áa]g(?:ina)?\.?\s*\d+|(?:no\s+)?item\s+\d+(?:\.\d+)*))*[\s·•—–:,-]*", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    if not t:
        return ""
    t = t[:1].upper() + t[1:]
    prot = re.sub(r"(?i)\b(p[aá]gs?|qd|lt|n[ºo°]|av|dr)\.", lambda m: m.group(1) + "․", t)
    frases = [f.replace("․", ".") for f in re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ'\"‘“«])", prot) if f.strip()]
    tt = _n(titulo).rstrip(". ")
    if frases and (_n(re.sub(r"\s*\([^()]*\)", "", frases[0])).rstrip(". ") == tt or _n(frases[0]).rstrip(". ").startswith(tt)):
        frases = frases[1:]                      # a 1ª frase já é o título
    out = " ".join(frases).strip()
    if out and out[-1] not in ".!?":
        out += "."
    return out


_SINAL = re.compile(r"\d{2}/\d{2}/\d{4}|\d+,\d{2}")


def _sem_repetidos(erros: list[dict]) -> list[dict]:
    """134-2: dois erros com os mesmos números/datas (ex.: 286,09 × 286,10; a data do relatório FIPE) ou com títulos
    quase iguais são o mesmo ponto — fica o primeiro, com os lugares dos dois."""
    import difflib
    fica: list[dict] = []
    for e in erros:
        sinais = set(_SINAL.findall(f"{e['titulo']} {e['no_laudo']} {e.get('origem', '')}"))
        igual = None
        for f in fica:
            fs = f.setdefault("_sinais", set(_SINAL.findall(f"{f['titulo']} {f['no_laudo']} {f.get('origem', '')}")))
            if (len(sinais & fs) >= 2 or (sinais and sinais == fs)
                    or difflib.SequenceMatcher(None, _n(e["titulo"]), _n(f["titulo"])).ratio() >= 0.8):
                igual = f
                break
        if igual is None:
            fica.append(e)
        else:
            for lg in e.get("lugares") or []:
                if lg not in igual["lugares"]:
                    igual["lugares"].append(lg)
    for f in fica:
        f.pop("_sinais", None)
    return fica


def aceitar(job_id: str, chave: str) -> None:
    k = CHAVE_ACEITAS.format(job_id)
    atual = set(json.loads(db.setting(k) or "[]"))
    atual.add(chave)
    db.set_setting(k, json.dumps(sorted(atual)))
    if chave.startswith("idade_foto:"):          # 109-5: "Confirmo" → a idade estimada pela foto vale como do avaliador
        try:
            n = int(chave.split(":", 1)[1])
        except ValueError:
            return
        r = next((x for x in db.candidatos(job_id) if x.n == n), None)
        if r is not None and getattr(r, "idade_fonte", "") == "fotos":
            db.salvar_candidatos(job_id, [r.model_copy(update={"idade_fonte": "avaliador"})])
            db.evento(job_id, "pesquisa", "edicao_manual", f"anúncio {n}: idade aparente confirmada pelo avaliador")
