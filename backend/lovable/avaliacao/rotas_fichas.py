"""ORDEM 026 v2 — rotas do módulo de aprendizado (F2 aprender no trabalho, F3 curadoria e
proteção, F4 perguntas de regra, exportar/importar). Registradas no mesmo router de routes.py."""
from __future__ import annotations

import difflib
import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from . import aprender, db, fichas, protecao
from .routes import _dono, _job, router

AV = fichas.AVALIADOR_ALAN       # o Alan (curador); ORDEM 042: cada avaliador usa _av()


def _av() -> str:
    from .routes import av_atual
    return av_atual()


def _curador(u: dict = Depends(_dono)) -> dict:
    """Curador: hoje o Alan (dono). Outros curadores: av_settings "curadores" (lista de e-mails)."""
    if (u or {}).get("avaliador_id", AV) != AV:      # ORDEM 042: avaliador novo não é curador
        raise HTTPException(status_code=403, detail="só o curador")
    return u


# ------------------------------------------------------------------ F2: aprender no trabalho
class Correcao(BaseModel):
    tipo: Literal["campo", "texto", "amostra", "area", "pergunta"]
    chave: str = Field(max_length=200)
    antes: str | float | int | None = None
    depois: str | float | int | None = None
    motivo: str = Field(default="", max_length=2000)


@router.post("/jobs/{jid}/aprender/perguntar")
async def aprender_perguntar(jid: str, body: Correcao, _u: dict = Depends(_dono)):
    """Deve aparecer "Vale só para este laudo ou para todos os seus?"? (não em digitação, não
    repetida no mesmo trabalho)."""
    _job(jid)
    return {"perguntar": aprender.deve_perguntar(jid, body.tipo, body.chave, body.antes, body.depois)}


class RespostaAprender(Correcao):
    resposta: Literal["so_este", "todos", "nao_regra"]


@router.post("/jobs/{jid}/aprender/resposta")
async def aprender_resposta(jid: str, body: RespostaAprender, _u: dict = Depends(_dono)):
    """Só este = fica no trabalho; Não é regra = nada; Todos os meus = rascunho da ficha (IA)
    para o avaliador conferir."""
    _job(jid)
    aprender.marcar_perguntada(jid, body.tipo, body.chave)
    db.evento(jid, "orquestrador", "info", f"aprendizado ({body.tipo}: {body.chave}): {body.resposta}")
    if body.resposta != "todos":
        return {"rascunho": None}
    r = await aprender.rascunho(jid, body.tipo, body.chave, body.antes, body.depois, body.motivo)
    return {"rascunho": r.model_dump()}


@router.post("/jobs/{jid}/aprender/confirmar")
async def aprender_confirmar(jid: str, body: aprender.Rascunho, _u: dict = Depends(_dono)):
    _job(jid)
    return aprender.confirmar(jid, body, _av())


@router.get("/fichas/minhas")
async def fichas_minhas(_u: dict = Depends(_dono)):
    return {"fichas": aprender.minhas(_av())}


class EdicaoFicha(BaseModel):
    titulo: str | None = None
    situacao: str | None = None
    decisao: str | None = None
    porque: str | None = None
    ativa: bool | None = None


@router.put("/fichas/{fid}")
async def editar_ficha(fid: str, body: EdicaoFicha, _u: dict = Depends(_dono)):
    """"Minhas regras": editar e desligar (só as do próprio avaliador)."""
    f = fichas.obter(fid)
    if f is None or f["escopo"] != "avaliador" or f["avaliador_id"] != _av():
        raise HTTPException(status_code=404, detail="regra não encontrada")
    mud = {k: v for k, v in body.model_dump().items() if v is not None}
    acao = "desligada" if mud.get("ativa") is False else "religada" if mud.get("ativa") else "editada"
    return fichas.gravar({**f, **mud, "editada": True}, quem=_av(), acao=acao)


# ------------------------------------------------------------------ F3: curadoria
def _parecidas(f: dict, base: list[dict]) -> list[dict]:
    alvo = f"{f['titulo']} {f['decisao']}".casefold()
    out = []
    for g in base:
        if g["id"] == f["id"] or g["nivel"] == "recusado":
            continue
        r = difflib.SequenceMatcher(None, alvo, f"{g['titulo']} {g['decisao']}".casefold()).ratio()
        if r >= 0.55:
            out.append({"id": g["id"], "titulo": g["titulo"], "nivel": g["nivel"], "semelhanca": round(r, 2)})
    return sorted(out, key=lambda x: -x["semelhanca"])[:5]


@router.get("/curadoria")
async def curadoria(_u: dict = Depends(_curador)):
    """Fila: fichas "aprendido" de avaliadores que autorizaram compartilhar, JÁ PROTEGIDAS (trava
    das regras; a da IA roda ao aprovar), com "N avaliadores fazem igual" e as parecidas."""
    todas = fichas.todas(incluir_inativas=False)
    fila = []
    for f in todas:
        if f["nivel"] != "aprendido" or not fichas.compartilha(f["avaliador_id"]):
            continue
        if any(h.get("acao", "").startswith(("aprovada", "recusada")) for h in f["historico"]):
            continue
        prot = protecao.proteger_ficha(f, f.get("trabalho_id") or None)
        parecidas = _parecidas(f, todas)
        fila.append({**{k: prot.get(k) for k in ("id", "titulo", "situacao", "decisao", "porque",
                                                    "tipo_imovel", "modalidade", "etapa", "tipo")},
                     "concordam": 1 + sum(1 for p in parecidas if p["nivel"] in ("aprendido", "validado")),
                     "parecidas": parecidas})
    return {"fila": fila}


class DecisaoCuradoria(BaseModel):
    acao: Literal["aprovar", "recusar", "editar_aprovar"]
    motivo: str = Field(default="", max_length=2000)
    titulo: str | None = None
    situacao: str | None = None
    decisao: str | None = None
    porque: str | None = None


@router.post("/curadoria/{fid}")
async def decidir_curadoria(fid: str, body: DecisaoCuradoria, u: dict = Depends(_curador)):
    """Aprovar = cópia PROTEGIDA (regras + IA) entra na base comum como "validado" (escopo
    geral); a ficha do avaliador continua dele. Recusar = fica fora da base comum, com motivo."""
    f = fichas.obter(fid)
    if f is None or f["nivel"] != "aprendido":
        raise HTTPException(status_code=404, detail="ficha não está na fila de curadoria")
    if body.acao == "recusar":
        if len(body.motivo.strip()) < 5:
            raise HTTPException(status_code=400, detail="diga o motivo da recusa")
        fichas.gravar(f, quem=_av(), acao="recusada na curadoria", motivo=body.motivo)
        return fichas.gravar({**f, "id": aprender.proximo_id(), "nivel": "recusado", "escopo": "geral",
                              "avaliador_id": "", "trabalho_id": "", "historico": []},
                             quem=_av(), acao="recusada", motivo=body.motivo)
    edit = {k: v for k, v in body.model_dump().items()
            if k in protecao.CAMPOS_TEXTO and v is not None} if body.acao == "editar_aprovar" else {}
    prot = await protecao.proteger_com_ia({**f, **edit}, f.get("trabalho_id") or None)
    fichas.gravar(f, quem=_av(), acao="aprovada na curadoria", motivo=body.motivo)
    return fichas.gravar({**prot, "id": aprender.proximo_id(), "nivel": "validado", "escopo": "geral",
                          "avaliador_id": "", "trabalho_id": "", "historico": [],
                          "fonte": f"curadoria ({datetime.now(timezone.utc):%d/%m/%Y}); ficha {fid}"},
                         quem=_av(), acao="aprovada", motivo=body.motivo)


TERMO_PADRAO = ("Autorizo o JdB a usar o raciocínio das minhas decisões (sem dados de "
                "clientes: nomes, documentos, endereços, valores exatos) para melhorar a base comum "
                "de conhecimento dos avaliadores. Posso retirar a autorização a qualquer momento.")


@router.get("/configuracoes/compartilhar")
async def ler_compartilhar(_u: dict = Depends(_dono)):
    try:
        d = json.loads(db.setting(f"compartilhar:{_av()}") or "{}")
    except ValueError:
        d = {}
    return {"sim": True if _av() == fichas.AVALIADOR_ALAN else bool(d.get("sim")), "data": d.get("data"),
            "termo": db.setting("termo_compartilhar") or TERMO_PADRAO, "dono": _av() == fichas.AVALIADOR_ALAN}


class Compartilhar(BaseModel):
    sim: bool
    termo: str | None = Field(default=None, max_length=5000)


@router.put("/configuracoes/compartilhar")
async def gravar_compartilhar(body: Compartilhar, _u: dict = Depends(_dono)):
    """Autorização "Compartilhar meu raciocínio com a base comum", com a data do aceite. O texto
    do termo é editável (o texto final o Danilo revisa)."""
    if body.termo is not None:
        db.set_setting("termo_compartilhar", body.termo.strip() or TERMO_PADRAO)
    db.set_setting(f"compartilhar:{_av()}", json.dumps(
        {"sim": body.sim, "data": datetime.now(timezone.utc).date().isoformat()}))
    return await ler_compartilhar()


# ------------------------------------------------------------------ F4: perguntas de regra
class Pergunta(BaseModel):
    pergunta: str = Field(min_length=3, max_length=2000)
    tipo_imovel: str = ""
    modalidade: str = ""


class _ParteResposta(BaseModel):
    texto: str
    nivel: Literal["oficial", "regra do avaliador", "validado", "aprendido", "sem base"]
    fonte: str = ""


class _Resposta(BaseModel):
    sem_base: bool = False
    partes: list[_ParteResposta] = []


INSTRUCAO_PERGUNTA = """\
Você responde perguntas de regra e "me mostre como se faz" do avaliador, usando SÓ a fonte
oficial (normas) e as fichas listadas abaixo — nunca o seu conhecimento geral. Cada parte da
resposta diz o nível de onde veio (oficial, regra do avaliador, validado, aprendido) e a fonte
(o id da ficha ou a norma). Se pedirem um MODELO de laudo de um tipo, entregue a estrutura e o
raciocínio de cada item, sem cliente, montados com as fichas daquela etiqueta. Se as fichas não
bastarem, sem_base = true: diga "ainda não tenho base para isso", mostre só o que vem da fonte
oficial e sugira aprender com o primeiro trabalho desse tipo (ficha F-S007). NUNCA INVENTE."""


# palavras de toda pergunta (não ajudam a achar a ficha certa)
_COMUNS = {"como", "faco", "fazer", "laudo", "laudos", "qual", "quais", "regra", "regras", "para", "sobre",
           "imovel", "imoveis", "avaliacao", "avaliar", "modelo", "mostre", "quando", "onde", "esse", "essa",
           "este", "esta", "isso", "fica", "deve", "devo", "dentro", "valor", "tipo"}


def _relevantes(p: Pergunta) -> list[dict]:
    fs = fichas.buscar(_av(), p.tipo_imovel, p.modalidade, ())
    palavras = {w for w in fichas._n(p.pergunta).split() if len(w) >= 4 and w not in _COMUNS}
    def nota(f):
        t = fichas._n(f"{f['titulo']} {f['situacao']} {f['decisao']} {' '.join(f['tipo_imovel'])}")
        return sum(1 for w in palavras if w in t)
    rel = [f for f in fs if nota(f) > 0]
    return sorted(rel, key=lambda f: (f["camada"], -nota(f)))[:25]


def tipo_da_pergunta(p: Pergunta) -> str:
    """Tipo de imóvel pedido (campo ou texto da pergunta): "galpão", "rural"... ou ''."""
    if p.tipo_imovel:
        return fichas._classe_imovel(p.tipo_imovel)
    palavras = set(fichas._n(p.pergunta).replace("?", " ").replace(",", " ").split())
    for k, ps in fichas._TIPO_PALAVRAS.items():
        if any(w in palavras for w in ps):
            return k
    return ""


def tem_base_do_tipo(tipo: str) -> bool:
    """ORDEM 038: há ficha (oficial, do avaliador ou validada) com esse tipo na etiqueta?"""
    alvo = fichas._n(tipo)
    return any(alvo in {fichas._n(x) for x in f["tipo_imovel"]}
               for f in fichas.buscar(_av(), "", "", ()) if f["camada"] < 4)


def k0_da_pergunta(p: Pergunta, n: int = 2) -> str:
    """As partes do K0 mais ligadas à pergunta (palavras em comum), no máx. `n`."""
    from . import conhecimento
    palavras = {w.strip("?.,") for w in fichas._n(p.pergunta).split()}
    palavras = {w for w in palavras if len(w) >= 4 and w not in _COMUNS}
    secs = {k: v for k, v in conhecimento.k0_secoes().items() if k.startswith("K0.")}
    nota = {k: sum(fichas._n(v).count(w) for w in palavras) for k, v in secs.items()}
    melhores = [k for k, x in sorted(nota.items(), key=lambda kv: -kv[1]) if x > 0][:n]
    return "\n\n".join(secs[k] for k in melhores)


@router.post("/conhecimento/perguntar")
async def perguntar_regra(body: Pergunta, _u: dict = Depends(_dono)):
    """"Me mostre como se faz": responde só com fonte oficial + fichas (+ as partes do K0 da
    pergunta), com o nível de cada parte. ORDEM 038: tipo de imóvel sem nenhuma ficha daquele
    tipo (ex.: rural) = sem base, sem gastar IA."""
    from . import conhecimento, ia
    tipo = tipo_da_pergunta(body)
    rel = _relevantes(body)
    oficiais = [f for f in rel if f["camada"] == 1]
    if (tipo and not tem_base_do_tipo(tipo)) or (not [f for f in rel if f["camada"] > 1] and not oficiais):
        return {"sem_base": True, "partes": [{"texto": "Ainda não tenho base para isso. Não há fonte "
                 "oficial nem ficha sobre esse assunto. Sugestão: aprender com o primeiro trabalho desse "
                 "tipo (o sistema pergunta, ao corrigir, se vale para todos os seus laudos).",
                 "nivel": "sem base", "fonte": "F-S007"}], "fichas": []}
    bloco = "\n".join(f"- [{fichas.ROTULO_CAMADA[f['camada']]}] {f['id']} — {f['titulo']}: {f['decisao']}"
                      f" — fonte: {f['fonte']}" for f in rel)
    normas = "\n".join(f"- {n['codigo']}: {n.get('titulo', '')}" for n in conhecimento.normas_vigentes())
    try:
        r: _Resposta = await ia.perguntar(INSTRUCAO_PERGUNTA, f"Pergunta: {body.pergunta}\n\nNormas vigentes "
                                          f"(fonte oficial):\n{normas}\n\nFichas:\n{bloco}"
                                          f"\n\nBase geral K0 (validada; cite como \"K0.x\"):\n"
                                          f"{k0_da_pergunta(body)}", _Resposta)
    except ia.IAFalhou as e:
        raise HTTPException(status_code=502, detail=f"a IA não respondeu: {e}")
    return {**r.model_dump(), "fichas": [f["id"] for f in rel]}


# ------------------------------------------------------------------ exportar / importar (servidor futuro)
@router.get("/fichas/exportar")
async def exportar_fichas(_u: dict = Depends(_curador)):
    """JSON da base comum (oficial + validado + aprendido de quem autorizou), sem trabalho_id e
    sem nada da camada do avaliador além das fichas; textos protegidos."""
    out = []
    for f in fichas.todas(incluir_inativas=False):
        if f["nivel"] == "recusado":
            continue
        if f["escopo"] == "avaliador" and not fichas.compartilha(f["avaliador_id"]):
            continue
        p = protecao.proteger_ficha(f, f.get("trabalho_id") or None)
        out.append({k: p.get(k) for k in ("id", "titulo", "situacao", "decisao", "porque", "tipo",
                                           "tipo_imovel", "modalidade", "etapa", "nivel", "escopo",
                                           "avaliador_id", "fonte", "concordam")})
    return {"versao": 1, "fichas": out}


class Importacao(BaseModel):
    fichas: list[dict] = Field(default_factory=list, max_length=5000)


@router.post("/fichas/importar")
async def importar_fichas(body: Importacao, _u: dict = Depends(_curador)):
    n = 0
    for f in body.fichas:
        if not f.get("id") or fichas.obter(f["id"]):
            continue      # não sobrescreve o que já existe (editado aqui prevalece)
        fichas.gravar({**protecao.proteger_ficha(f), "trabalho_id": ""}, quem="importação", acao="importada")
        n += 1
    return {"importadas": n}
