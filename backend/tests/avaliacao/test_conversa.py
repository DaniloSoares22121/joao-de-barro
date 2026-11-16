"""ORDEM 041 (D-089 a D-093): conversa por cliente, etapas, avisos, Web Push e vistoria."""
import asyncio
import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from lovable.avaliacao import conversa as C
from lovable.avaliacao import ia, rotas_conversa as R, vistoria, webpush


def test_contexto_nao_apaga_dado_ja_recebido():
    cid = C.criar("Cliente Teste")
    C.juntar_contexto(cid, {"solicitante_nome": "Maria Teste", "cidade": "Goiânia"})
    ctx, mudou = C.juntar_contexto(cid, {"solicitante_nome": "", "bairro": "Centro", "cidade": None})
    assert ctx["solicitante_nome"] == "Maria Teste" and ctx["cidade"] == "Goiânia" and mudou == ["bairro"]


def test_etapas_e_pendencia_unica():
    cid = C.criar("X")
    cli = C.obter(cid)
    e = {x["etapa"]: x for x in C.etapas(cli)}
    assert e["proposta"]["status"] == "falta" and "tipo de imóvel" in e["proposta"]["falta"]
    assert e["contrato"]["status"] == "espera" and C.etapa_atual(cli) == "proposta"
    C.juntar_contexto(cid, {"solicitante_nome": "A", "imovel_tipo": "Casa", "modalidade": "OV", "finalidade": "Venda",
                            "cidade": "Goiânia", "proposta_status": "aprovada"})
    cli = C.obter(cid)
    assert C.etapa_atual(cli) == "contrato"
    textos = [p["texto"] for p in C.pendencias(cli)]
    assert textos[0].startswith("CPF ou CNPJ") and len(textos) == len(set(textos))


def test_mensagem_da_ia_vira_contexto_e_proposta_para_revisar(monkeypatch):
    cid = C.criar("")
    # ORDEM 062: este fluxo vale depois do "É isso, pode começar" (o antes está em test_entendimento.py)
    C.juntar_contexto(cid, {"entendimento_status": "confirmado"})

    async def fake(sistema, prompt, esquema, **k):
        assert "não peça de novo" in prompt.lower() or "NÃO PEÇA DE NOVO" in prompt.upper()
        return esquema.model_validate({"campos": {"solicitante_nome": "Joana Teste", "imovel_tipo": "Galpão",
                                                  "modalidade": "AM", "finalidade": "Venda", "cidade": "Aparecida de Goiânia",
                                                  "visita": "2026-11-19T09:00"},
                                       "intencao": ["proposta", "agendar"], "resposta": "Anotei."})
    monkeypatch.setattr(ia, "perguntar", fake)
    st = asyncio.run(R.nova_mensagem(cid, R.Entrada(texto="[TESTE] …", tipo="whatsapp"), _u={}))
    e = {x["etapa"]: x["status"] for x in st["etapas"]}
    assert e["proposta"] == "revisar" and e["visita"] == "agendada"
    assert st["sugestao"]["valor"] == ""      # ORDEM 069-A1/071: nunca o piso da tabela sozinho (o portão pergunta)
    assert st["visita"]["legivel"] == "quinta, 19/11 às 09:00"


def test_aviso_vence_2h_antes():
    cid = C.criar("Y")
    br = timezone(timedelta(hours=-3))
    quando = (datetime.now(br) + timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M")
    C.agendar(cid, quando, "Visita", 120)
    assert any(r["cliente"] == cid for r in C.avisos_vencidos())
    longe = (datetime.now(br) + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M")
    C.agendar(cid, longe, "Visita", 120)
    assert not any(r["cliente"] == cid for r in C.avisos_vencidos())


def test_mascara_cpf():
    assert C.mascarar("123.456.789-00") == "•••.•••.•••-00"


def _hkdf(salt, ikm, info, n):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:n]


def test_webpush_cifra_e_o_navegador_decifra():
    """Faz o papel do navegador (RFC 8291): decifra o que o servidor cifrou."""
    ua = ec.generate_private_key(ec.SECP256R1())
    ua_pub = ua.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()   # noqa: E731
    corpo = webpush.cifrar(json.dumps({"titulo": "TESTE"}).encode(), b64(ua_pub), b64(auth))
    salt, n = corpo[:16], corpo[20]
    as_pub, ct = corpo[21:21 + n], corpo[21 + n:]
    shared = ua.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = _hkdf(auth, shared, b"WebPush: info\x00" + ua_pub + as_pub, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    claro = AESGCM(cek).decrypt(nonce, ct, None)
    assert claro.rstrip(b"\x02") == b'{"titulo": "TESTE"}'
    assert len(webpush.chave_publica()) > 80


def test_vistoria_sob_medida():
    gal = vistoria.secoes("Galpão", "OV", "Venda")
    nomes = [s for s, _, _ in gal]
    assert "Objeto da avaliação" in nomes and "Conversa com o proprietário" in nomes
    ap = [s for s, _, _ in vistoria.secoes("Apartamento", "AMJ", "Inventário")]
    assert "Condomínio" in ap and "Processo" in ap
    itcmd = [s for s, _, _ in vistoria.secoes("Casa", "AM", "ITCMD – doação")]
    assert "Fisco" in itcmd
    html = vistoria.pagina({"imovel_tipo": "Galpão", "modalidade": "OV", "finalidade": "Venda"})
    assert "VISTORIA – OV – Galpão" in html and "Concluir vistoria" in html
    assert "NBR" not in html and "prazo" not in html.lower()     # nada de exigência legal não conferida
