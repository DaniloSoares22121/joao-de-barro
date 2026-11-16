"""ORDEM 024 item 6: proposta -> contrato -> trabalho dentro do sistema (rotas e armazenamento).
Numeração ANO-SEQ própria (separada do nº do laudo); validade de 10 dias."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from lovable import config

from . import db, propostas
from .routes import _dono, router

_DDL = """CREATE TABLE IF NOT EXISTS av_propostas (
  id TEXT PRIMARY KEY, ano INTEGER NOT NULL, numero INTEGER NOT NULL, status TEXT NOT NULL,
  dados TEXT NOT NULL, arquivos TEXT NOT NULL DEFAULT '[]', criado TEXT NOT NULL,
  UNIQUE (ano, numero))"""


def _init() -> None:
    db.init()
    with db._conn() as c:
        c.execute(_DDL)


def _pasta(pid: str) -> Path:
    return Path(config.DATA_DIR) / "avaliacao" / "propostas" / pid


def _ler(pid: str, checar: bool = True) -> dict:
    _init()
    with db._conn() as c:
        r = c.execute("SELECT * FROM av_propostas WHERE id=?", (pid,)).fetchone()
    if r is None:
        raise HTTPException(status_code=404, detail="proposta não encontrada")
    d = dict(r)
    d["dados"] = json.loads(d["dados"])
    d["arquivos"] = json.loads(d["arquivos"])
    from .routes import av_atual
    if checar and (d["dados"].get("avaliador_id") or "AV-0001") != av_atual() and d["dados"]:
        raise HTTPException(status_code=404, detail="proposta não encontrada")
    return d


def _salvar(pid: str, status: str, dados: dict, arquivos: list[str]) -> None:
    with db._conn() as c:
        c.execute("UPDATE av_propostas SET status=?, dados=?, arquivos=? WHERE id=?",
                  (status, json.dumps(dados, ensure_ascii=False), json.dumps(arquivos, ensure_ascii=False), pid))


class Imovel(BaseModel):
    descricao: str = Field(max_length=300)
    endereco: str = Field(default="", max_length=300)
    matricula: str = Field(default="", max_length=60)
    cartorio: str = Field(default="", max_length=200)
    tipo: str = Field(default="", max_length=60)
    bairro: str = Field(default="", max_length=120)
    cidade: str = Field(default="Goiânia", max_length=120)


class NovaProposta(BaseModel):
    modalidade: str = "OV"
    categoria: str = "residencial"
    solicitante_nome: str = Field(min_length=2, max_length=200)
    solicitante_doc: str = Field(default="", max_length=40)
    proprietario: str = Field(default="", max_length=200)
    imovel: Imovel
    finalidade: str = Field(min_length=2, max_length=300)
    valor: str | None = None                 # vazio = preço padrão (D-051)
    cidade_emissao: str = "Goiânia"
    pagamento_texto: str = ""                # ORDEM 071: como foi confirmado no portão
    prazo_texto: str = ""


def _gerar(dados: dict, pasta, qual: str):
    """O Alan usa o gerador dele (P10); os outros avaliadores, os modelos gerais aprovados (ORDEM 043)."""
    av = dados.get("avaliador_id") or "AV-0001"
    if av == "AV-0001":
        return propostas.gerar(dados, pasta, qual)
    from . import modelos_gerais as M
    n = f"{dados.get('ano')}-{int(dados.get('numero') or 0):03d}"
    d = {**dados, "numero": n}
    if qual == "proposta":
        return M.salvar(M.proposta(av, d), pasta / f"Proposta {n} - {dados.get('arquivo', '')}.docx".replace("/", "-"))
    c = json.loads(db.setting(f"contratado:{av}") or "{}")
    return M.salvar(M.contrato(av, d, c), pasta / f"Contrato {n} - {dados.get('arquivo', '')}.docx".replace("/", "-"))


@router.get("/propostas/preco-padrao")
async def preco_padrao(modalidade: str = "OV", tipo: str = "", _u: dict = Depends(_dono)):
    """ORDEM 042 (D-097): preço da tabela do PRÓPRIO avaliador; sem tabela, vazio (sem sugestão)."""
    from . import avaliadores
    av = (_u or {}).get("avaliador_id", "AV-0001")
    linha = avaliadores.linha_da_tabela(av, modalidade, tipo) if avaliadores.tabela_salva(av) else None     # 184
    return {"valor": avaliadores.preco(av, modalidade, tipo),
            "prazo": avaliadores.prazo_da_linha(linha) or propostas.prazo_entrega(modalidade)}


def valor_decimal(v) -> Decimal | None:
    """ORDEM 065: "R$ 600,00", "600", "600.00", "1.200,50" → Decimal. Vazio ou sem número → None."""
    import re
    from decimal import InvalidOperation
    # ORDEM 071-A: só o PRIMEIRO valor em dinheiro do texto ("Honorários de R$ 600, com sinal de R$ 300"
    # é 600, nunca 600.300). Ordem: milhar com ponto, decimal com ponto, inteiro ou decimal com vírgula.
    m = re.search(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?(?!\d)|\d+\.\d{1,2}(?!\d)|\d+(?:,\d{1,2})?(?!\d)", str(v or ""))
    if not m:
        return None
    s = m.group(0)
    if "," in s:                                   # pt-BR: ponto é milhar, vírgula é decimal
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.search(r"\.\d{3}$", s):
        s = s.replace(".", "")                     # "1.200" = mil e duzentos
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def montar_dados(body: NovaProposta, av: str, ano: int, n: int, valor: Decimal) -> dict:
    """Os dados da proposta: os mesmos no rascunho e na aprovada (ORDEM 065)."""
    from .nomes import cliente_curto, local_curto, tipo_curto
    return {"ano": ano, "numero": n, "data": date.today().strftime("%d/%m/%Y"), "modalidade": body.modalidade,
            "categoria": body.categoria, "solicitante": {"nome": body.solicitante_nome, "doc": body.solicitante_doc},
            "proprietario": body.proprietario, "imovel": body.imovel.model_dump(), "finalidade": body.finalidade,
            "valor": str(valor), "cidade_emissao": body.cidade_emissao, "avaliador_id": av,
            "pagamento_texto": body.pagamento_texto, "prazo_texto": body.prazo_texto,
            "arquivo": " - ".join(x for x in (cliente_curto(body.solicitante_nome), tipo_curto(body.imovel.tipo or body.imovel.descricao),
                                             local_curto(body.imovel.bairro), body.imovel.cidade) if x)}


def valor_da_proposta(body: NovaProposta, av: str) -> Decimal:
    from . import avaliadores
    v = valor_decimal(body.valor)
    if v is None:
        # ORDEM 069-A1 / 071: nunca o piso da tabela sozinho — sem valor combinado, o JdB pergunta
        tabela = avaliadores.preco(av, body.modalidade, body.imovel.tipo)
        dica = f" (sua tabela: a partir de R$ {tabela})" if tabela else ""
        raise HTTPException(status_code=409, detail=f"falta: quanto vai cobrar{dica}")
    return v


def proximo_numero(ano: int) -> int:
    _init()
    with db._conn() as c:
        return (c.execute("SELECT MAX(numero) FROM av_propostas WHERE ano=?", (ano,)).fetchone()[0] or 0) + 1


@router.post("/propostas")
async def nova_proposta(body: NovaProposta, _u: dict = Depends(_dono)):
    _init()
    hoje = date.today()
    av = (_u or {}).get("avaliador_id", "AV-0001")
    valor = valor_da_proposta(body, av)            # ORDEM 065-A: o valor é lido ANTES de reservar o número
    with db._conn() as c:
        n = (c.execute("SELECT MAX(numero) FROM av_propostas WHERE ano=?", (hoje.year,)).fetchone()[0] or 0) + 1
        pid = uuid.uuid4().hex[:12]
        c.execute("INSERT INTO av_propostas (id, ano, numero, status, dados, criado) VALUES (?,?,?,?,?,?)",
                  (pid, hoje.year, n, "proposta", "{}", datetime.now(timezone.utc).isoformat()))
    dados = montar_dados(body, av, hoje.year, n, valor)
    try:
        arqs = _gerar(dados, _pasta(pid), "proposta")
    except Exception:
        with db._conn() as c:                      # nada de proposta vazia ocupando número
            c.execute("DELETE FROM av_propostas WHERE id=?", (pid,))
        raise
    _salvar(pid, "proposta", dados, [a.name for a in arqs])
    return _ler(pid)


@router.get("/propostas")
async def listar_propostas(_u: dict = Depends(_dono)):
    _init()
    with db._conn() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM av_propostas ORDER BY ano DESC, numero DESC")]
    todas = [_ler(i, checar=False) for i in ids]
    return {"propostas": [p for p in todas if (p["dados"].get("avaliador_id") or "AV-0001") == (_u or {}).get("avaliador_id", "AV-0001")]}


class Contratante(BaseModel):
    nome: str = Field(default="", max_length=200)
    doc_tipo: str = Field(default="CPF/CNPJ", max_length=20)
    doc: str = Field(default="", max_length=40)
    endereco: str = Field(default="", max_length=300)
    representante: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=200)
    telefone: str = Field(default="", max_length=40)
    pj: bool = False


class NovoContrato(BaseModel):
    contratante: Contratante
    pagamento: str = "pix"                 # pix | link


@router.post("/propostas/{pid}/contrato")
async def gerar_contrato(pid: str, body: NovoContrato, _u: dict = Depends(_dono)):
    p = _ler(pid)
    dados = {**p["dados"], "contratante": body.contratante.model_dump(), "pagamento": body.pagamento,
             "data_contrato": date.today().strftime("%d/%m/%Y")}
    arqs = _gerar(dados, _pasta(pid), "contrato")
    _salvar(pid, "contrato", dados, sorted(set(p["arquivos"]) | {a.name for a in arqs}))
    return _ler(pid)


@router.post("/propostas/{pid}/trabalho")
async def abrir_trabalho(pid: str, _u: dict = Depends(_dono)):
    """Dados para o "Novo trabalho" já preenchido (a tela abre o formulário com eles)."""
    p = _ler(pid)
    d = p["dados"]
    im = d.get("imovel") or {}
    _salvar(pid, "trabalho", d, p["arquivos"])
    return {"modalidade": d.get("modalidade", "OV"), "finalidade": d.get("finalidade", ""),
            "cliente": d.get("solicitante", {}).get("nome", ""), "tipo": im.get("tipo") or im.get("descricao", ""),
            "bairro": im.get("bairro", ""), "cidade": im.get("cidade", "")}


@router.get("/propostas/{pid}/arquivo/{nome}")
async def baixar_arquivo(pid: str, nome: str, _u: dict = Depends(_dono)):
    p = _ler(pid)
    if nome not in p["arquivos"]:
        raise HTTPException(status_code=404)
    f = (_pasta(pid) / nome).resolve()
    if f.parent != _pasta(pid).resolve() or not f.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(f, filename=f.name)


class Contratado(BaseModel):
    cpf: str = Field(default="", max_length=20)
    endereco: str = Field(default="", max_length=300)
    email: str = Field(default="", max_length=200)
    pix: str = Field(default="", max_length=120)


@router.get("/configuracoes/contratado")
async def ler_contratado(_u: dict = Depends(_dono)):
    """Dados do contratado para o contrato (ficam no banco local/config, nunca no git)."""
    av = (_u or {}).get("avaliador_id", "AV-0001")
    if av != "AV-0001":
        c = json.loads(db.setting(f"contratado:{av}") or "{}")
        return {k: c.get(k, "") for k in ("cpf", "endereco", "email", "pix")}
    propostas._AV = "AV-0001"
    c = propostas.contratado()
    return {k: c.get(k, "") for k in ("cpf", "endereco", "email", "pix")}


@router.put("/configuracoes/contratado")
async def gravar_contratado(body: Contratado, _u: dict = Depends(_dono)):
    av = (_u or {}).get("avaliador_id", "AV-0001")
    chave = "contratado" if av == "AV-0001" else f"contratado:{av}"
    db.set_setting(chave, json.dumps({k: v.strip() for k, v in body.model_dump().items()}, ensure_ascii=False))
    return await ler_contratado(_u=_u)
