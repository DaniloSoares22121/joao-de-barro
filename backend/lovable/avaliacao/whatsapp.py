"""ORDEM 061: importar a conversa exportada do WhatsApp (o .zip com mídias, ou os arquivos soltos).

Só código, sem IA: abre o zip com segurança, lê o .txt (Android e iPhone, data em português), liga
cada "(arquivo anexado)" / "<anexado: …>" à mídia certa e separa os arquivos por tipo. A transcrição
dos áudios fica em `transcricao.py` (local) e a leitura dos documentos é a que já existia."""
from __future__ import annotations

import re
import stat
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

LIMITE_ENVIO = 500 * 1024 * 1024            # por envio
LIMITE_ARQUIVOS_ZIP = 2000
LIMITE_DESCOMPACTADO = 2 * 1024 * 1024 * 1024   # proteção contra zip-bomba

TIPOS = {
    "texto": {".txt"},
    "audio": {".opus", ".ogg", ".m4a", ".mp3", ".aac", ".wav", ".amr"},
    "foto": {".jpg", ".jpeg", ".png", ".webp", ".heic"},
    "documento": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv"},
    "video": {".mp4", ".3gp", ".mov"},
    "contato": {".vcf"},
    "zip": {".zip"},
}
RECUSADOS = {".exe", ".bat", ".cmd", ".com", ".js", ".jse", ".vbs", ".vbe", ".wsf", ".apk", ".msi", ".ps1", ".psm1",
             ".scr", ".jar", ".sh", ".dll", ".lnk", ".reg", ".hta", ".cpl", ".msc", ".pif", ".py"}
FIGURINHA_MAX = 100 * 1024                  # .webp pequeno = figurinha (ignorada)


def tipo_de(nome: str) -> str:
    """'texto' | 'audio' | 'foto' | 'documento' | 'video' | 'contato' | 'zip' | 'recusado' | 'outro'."""
    ext = Path(nome).suffix.lower()
    if ext in RECUSADOS:
        return "recusado"
    return next((t for t, exts in TIPOS.items() if ext in exts), "outro")


def nome_seguro(nome: str) -> str:
    base = unicodedata.normalize("NFC", PurePosixPath(str(nome).replace("\\", "/")).name).strip(_LRM_TODOS)
    base = "".join(ch for ch in base if ch.isalnum() or ch in "._- ()+")[:100].strip(" .")
    return base or "arquivo"


_LRM_TODOS = "\u200e\u200f\u202a\u202c\ufeff "


def nome_do_zip(info: zipfile.ZipInfo) -> str:
    """ORDEM 070-B1: zip sem a marca UTF-8 (o "Pasta compactada" do Windows) — o Python lê os nomes como cp437.
    Se o nome refeito em UTF-8 for válido, vale ele; senão fica o cp437. Sempre em NFC (o WhatsApp manda NFD)."""
    nome = info.filename
    if not info.flag_bits & 0x800:
        try:
            nome = nome.encode("cp437").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return unicodedata.normalize("NFC", nome)


class ZipInvalido(ValueError):
    pass


def abrir_zip(origem: Path, destino: Path) -> list[Path]:
    """Extrai com segurança: nada fora de `destino` (sem '..' nem caminho absoluto), links ignorados,
    no máximo 2.000 arquivos e 2 GB descompactados. Devolve os arquivos extraídos."""
    destino.mkdir(parents=True, exist_ok=True)
    raiz = destino.resolve()
    try:
        z = zipfile.ZipFile(origem)
    except zipfile.BadZipFile as e:
        raise ZipInvalido("o .zip está corrompido") from e
    with z:
        itens = [i for i in z.infolist() if not i.is_dir()]
        if len(itens) > LIMITE_ARQUIVOS_ZIP:
            raise ZipInvalido(f"o .zip tem mais de {LIMITE_ARQUIVOS_ZIP} arquivos")
        if sum(i.file_size for i in itens) > LIMITE_DESCOMPACTADO:
            raise ZipInvalido("o .zip aberto passaria de 2 GB")
        out = []
        for i in itens:
            nome = nome_do_zip(i).replace("\\", "/")
            modo = i.external_attr >> 16
            if stat.S_ISLNK(modo):
                continue                                         # link: ignorado
            if nome.startswith("/") or re.match(r"^[A-Za-z]:", nome) or ".." in PurePosixPath(nome).parts:
                continue                                         # caminho para fora: ignorado
            if "__MACOSX" in PurePosixPath(nome).parts:
                continue
            alvo = (raiz / nome_seguro(nome)).resolve()
            if not alvo.is_relative_to(raiz):
                continue
            k = 2
            while alvo.exists():
                p = Path(nome_seguro(nome))
                alvo = raiz / f"{p.stem} ({k}){p.suffix}"
                k += 1
            with z.open(i) as src, open(alvo, "wb") as dst:
                while bloco := src.read(1024 * 1024):
                    dst.write(bloco)
            out.append(alvo)
        return out


# ------------------------------------------------------------------ o .txt da conversa
@dataclass
class MsgWpp:
    quando: datetime | None
    autor: str
    texto: str
    anexo: str = ""                   # nome do arquivo de mídia citado na mensagem
    transcricao: str = ""
    linhas: list[str] = field(default_factory=list)


_LRM = "‎‏‪‬﻿"
_ANDROID = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}),? (\d{1,2}:\d{2})(?::\d{2})? - (.*)$")
_IOS = re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4}),? (\d{1,2}:\d{2})(?::\d{2})?\] (.*)$")
_AUTOR = re.compile(r"^([^:]{1,80}?): (.*)$", re.S)
_ANEXO = re.compile(r"^\s*(.+?\.[A-Za-z0-9]{2,5}) \((?:arquivo anexado|file attached)\)", re.I)
_ANEXO_IOS = re.compile(r"<(?:anexado|attached): ([^>]+)>", re.I)
_SISTEMA = re.compile(r"protegidas com a criptografia de ponta a ponta|end-to-end encrypted|"
                      r"criou o grupo|mudou o número|alterou o código de segurança", re.I)


def _data(d: str, h: str) -> datetime | None:
    dia, mes, ano = d.split("/")
    ano = int(ano) + (2000 if len(ano) == 2 else 0)
    try:
        return datetime(ano, int(mes), int(dia), int(h.split(":")[0]), int(h.split(":")[1]))
    except ValueError:
        return None


def ler_conversa(texto: str) -> list[MsgWpp]:
    """Conversa em ordem: quem falou, quando e o texto (linhas seguintes da mesma mensagem juntas).
    Aviso do sistema (criptografia etc.) fica com autor ''."""
    texto = unicodedata.normalize("NFC", texto)          # o .txt e os nomes do zip no mesmo formato (070-B1)
    msgs: list[MsgWpp] = []
    for bruta in texto.replace("\r\n", "\n").split("\n"):
        linha = bruta.strip(_LRM)
        m = _IOS.match(linha) or _ANDROID.match(linha)
        if not m:
            if msgs and linha.strip():
                msgs[-1].texto += "\n" + linha.strip(_LRM)
            continue
        resto = m.group(3).strip(_LRM)
        a = _AUTOR.match(resto)
        autor, corpo = (a.group(1).strip(_LRM), a.group(2)) if a else ("", resto)
        if _SISTEMA.search(corpo):          # no iPhone o aviso do sistema vem com o nome do contato
            autor = ""
        msgs.append(MsgWpp(_data(m.group(1), m.group(2)), autor, corpo.strip(_LRM).strip()))
    for msg in msgs:
        x = _ANEXO_IOS.search(msg.texto) or _ANEXO.search(msg.texto.strip(_LRM_TODOS))
        if x:
            msg.anexo = nome_seguro(unicodedata.normalize("NFC", x.group(1).strip(_LRM_TODOS)))
            msg.texto = (msg.texto[:x.start()] + msg.texto[x.end():]).strip(_LRM).strip()
    return msgs


def nome_do_contato(nome_arquivo: str, msgs: list[MsgWpp]) -> str:
    """'Conversa do WhatsApp com Fulano.txt' / 'WhatsApp Chat - Fulano.txt' → 'Fulano'."""
    s = Path(nome_arquivo).stem
    for pref in ("Conversa do WhatsApp com ", "WhatsApp Chat with ", "WhatsApp Chat - ", "Conversa do WhatsApp - "):
        if s.lower().startswith(pref.lower()):
            r = s[len(pref):].strip()
            return ("+" + r) if re.fullmatch(r"\d[\d ()-]{7,}", r) else r     # telefone sem o "+" (071-C6)
    autores = [m.autor for m in msgs if m.autor]
    return max(set(autores), key=autores.count) if autores else ""


def ler_vcf(texto: str) -> tuple[str, str]:
    """(nome, telefone) do contato."""
    nome = re.search(r"^FN[^:]*:(.+)$", texto, re.M)
    tel = re.search(r"^TEL[^:]*:(.+)$", texto, re.M)
    return (nome.group(1).strip() if nome else ""), (re.sub(r"[^\d+]", "", tel.group(1)) if tel else "")
