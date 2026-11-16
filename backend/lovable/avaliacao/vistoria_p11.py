"""ORDEM 067 / D-054: a página da vistoria de TODO trabalho sai do P11, a vistoria padrão do Alan.

Mesmas etapas, itens, textos, chips (Foto, Medir, ITCD), regras "so" e contas do P11 (copiados fiéis em
`P11_JS` abaixo), com os acréscimos da tabela do P5 por caso (apartamento, lote, galpão, AM garantia, AMJ)
e o item novo do Alan ("Padrão de energia"). Os dados do caso vêm do trabalho e dos documentos lidos; sem
dado, o trecho sai — nunca é inventado. Visual: identidade JdB (D-103), botões de 48 px ou mais.

Comportamento: o item se marca sozinho ao preencher; contas de terreno, construção e prazo do ITCD; o pin
do Google Maps; a etapa "Conversa" é só contexto (D-013); observações gerais; tudo salvo no aparelho.
"Mostrar só o que falta" (067-A). "Concluir vistoria" envia ao trabalho (com internet) ou guarda no
celular e envia sozinho quando a internet voltar; "Copiar o texto" fica como opção pequena."""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime

from .vistoria import _fonte, _n, classe_tipo

MOD_NOME = {"OV": "Opinião de Valor", "AM": "PTAM (AM)", "AM_GARANTIA": "PTAM garantia", "AMJ": "PTAM judicial"}


def _fin(finalidade: str, mod: str) -> tuple[str, str]:
    f = _n(finalidade)
    if any(x in f for x in ("itcd", "itcmd", "heranca", "doacao", "malha")):
        return "itcd", "ITCD, malha fiscal" if "malha" in f else "ITCD"
    if mod == "AM_GARANTIA" or "garantia" in f:
        return "garantia", "Garantia"
    if mod == "AMJ" or "judicial" in f or "processo" in f:
        return "judicial", "Judicial"
    if "venda" in f or "compra" in f:
        return "venda", "Venda"
    return "outra", (finalidade or "")[:40]


def _endereco(end: str) -> dict:
    """'Rua XV 9, Qd. 59, Lt. 02, Jardim X, Goiânia – GO, CEP 74000-000' → partes (o que não achar fica vazio)."""
    e = end or ""
    rua = re.split(r",\s*(?:qd|quadra|lt|lote)\b", e, flags=re.I)[0].strip(" ,") if e else ""
    qd = re.search(r"\b(?:qd|quadra)\.?\s*([\w-]+)", e, re.I)
    lt = re.search(r"\b(?:lt|lote)\.?\s*([\w-]+)", e, re.I)
    cep = re.search(r"\b(\d{5}-?\d{3})\b", e)
    return {"rua": rua[:80], "quadraLote": " · ".join(x for x in (f"Qd. {qd.group(1)}" if qd else "", f"Lt. {lt.group(1)}" if lt else "") if x).replace(" · ", ", "),
            "cep": (cep.group(1) if cep else "")}


def _num(v) -> float | None:
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return None


def caso(numero: str, ctx: dict, campos: dict | None = None, entrega: str = "") -> dict:
    """Os dados do caso para a página (do trabalho e dos documentos lidos; sem dado, fica vazio)."""
    campos = campos or {}
    tipo = classe_tipo(ctx.get("imovel_tipo") or "")
    mod = ctx.get("modalidade") or "OV"
    fin, fin_nome = _fin(ctx.get("finalidade") or "", mod)
    end = _endereco(ctx.get("imovel_endereco") or "")
    visita = ctx.get("visita") or ""
    try:
        visita_nome = datetime.fromisoformat(visita).strftime("%d/%m · %Hh%M") if visita else ""
    except ValueError:
        visita_nome = ""
    docs = [d.get("tipo") for d in ctx.get("docs") or [] if d.get("tipo")]
    contato = (ctx.get("solicitante_nome") or "").split(" ")[0]
    return {
        "numero": str(numero), "tipo": tipo, "tipoNome": {"casa": "Casa", "apartamento": "Apartamento", "lote": "Lote", "galpao": "Galpão"}[tipo],
        "mod": "AMG" if mod == "AM_GARANTIA" else mod, "modNome": MOD_NOME.get(mod, mod), "fin": fin, "finNome": fin_nome,
        **end, "bairro": ctx.get("bairro") or "", "cidade": ctx.get("cidade") or "", "uf": "GO" if ctx.get("cidade") else "",
        "visita": visita_nome, "entrega": entrega, "entregaNome": date.fromisoformat(entrega).strftime("%d/%m") if entrega else "",
        "contato": contato, "terrenoDoc": _num(campos.get("terreno_doc")), "terrenoDocFonte": campos.get("terreno_doc_fonte") or "",
        "terrenoIptu": _num(campos.get("terreno_iptu")), "construidaIptu": _num(campos.get("construida_iptu")), "iptuAno": campos.get("iptu_ano") or "",
        "matricula": ctx.get("matricula") or "", "cartorio": ctx.get("cartorio") or "",
        "docsChat": ", ".join(dict.fromkeys(docs)), "docSolicitante": "", "docSolicitanteObs": "",
        "quesitos": [q for q in (ctx.get("quesitos") or []) if q] if isinstance(ctx.get("quesitos"), list) else [],
        "pin": ctx.get("pin_maps") or "",
    }


# ------------------------------------------------------------------ o P11 (copiado fiel) + acréscimos do P5 e do Alan
P11_JS = r"""
function montarSecoes(C){
  var itcd = C.fin === 'itcd';
  var tagItcd = itcd ? ['itcd'] : [];
  var EDIF = ['casa','apartamento','galpao'];
  var COM_TERRENO = ['casa','lote','galpao'];
  var S = [
    {id:'s1', t:'Antes de sair', itens:[
      {id:'a1', t:'Celular carregado e com espaço para fotos'},
      {id:'a2', t:'Trena na bolsa (laser ou de 30 m)'},
      {id:'a3', t:'Medidas e confrontações da ' + (C.terrenoDocFonte || 'matrícula') + ' à mão', d:areasTexto() ? 'Para comparar na hora: ' + areasTexto() + '.' : '', so:{tipo:COM_TERRENO}},
      {id:'a4', t:'Localização do celular ligada', d:'As fotos saem georreferenciadas.' + (itcd ? ' A declaração do ITCD pede foto com coordenadas.' : ''), tags:tagItcd}
    ]},
    {id:'s2', t:'Chegada e identificação', itens:[
      {id:'b1', t:'Pin do Google Maps em frente ao imóvel', d:'Marque o pin, toque em Compartilhar, copie o link e cole aqui.', campo:{tipo:'texto', ph:'Cole o link do pin'}, link:{href:'https://www.google.com/maps', t:'Abrir o Google Maps'}},
      {id:'b2', t:'Número do imóvel na fachada', tags:['foto']},
      {id:'b3', t:'Placa da ' + (C.rua || 'rua') + ' ou esquina de referência', tags:['foto']},
      {id:'b4', t:'Endereço confere com o IPTU e a conta de água', d:((C.quadraLote ? C.quadraLote + ' · ' : '') + (C.cep ? 'CEP ' + C.cep + '. ' : '') + 'Se algo não bater, anote.'), campo:{tipo:'texto', ph:'Divergência, se houver'}},
      {id:'b5', t:'Hidrômetro com o número legível', d:'Liga a conta de água a este imóvel.', tags:['foto'], so:{tipo:['casa','galpao']}},
      {id:'b5e', t:'Padrão de energia (medidor) com o número legível', tags:['foto'], so:{tipo:['casa','galpao']}},
      {id:'b6', t:'Capa: só o imóvel, limpo, tirado da rua', d:'Com a localização ligada.', tags:['foto'].concat(tagItcd)},
      {id:'b7', t:'Fachada em ângulo, mostrando a lateral', tags:['foto']}
    ]},
    {id:'s3', t:'Conversa com ' + (C.contato || 'o proprietário'), ctx:true, nota:'Só contexto: o que for dito não entra no laudo (D-013).', itens:[
      {id:'c1', t:'Data da declaração do ITCD (DITCD)', d:'Vira a data-base do laudo.', tags:['itcd'], campo:{tipo:'data'}, so:{fin:['itcd']}},
      {id:'c2', t:'Data da ciência do comunicado da malha', d:'Começa a contar o prazo de 30 dias para justificar.', tags:['itcd'], campo:{tipo:'data'}, calc:'prazo', so:{fin:['itcd']}},
      {id:'c3', t:'Justificativa ainda não enviada', d:'Só pode ser feita uma vez. Esperar o laudo.', tags:['itcd'], so:{fin:['itcd']}},
      {id:'c4', t:'Valor declarado × valor de referência (FIPE)', tags:['itcd'], campo:{tipo:'texto', ph:'Ex.: R$ 150.000 × R$ 210.000'}, so:{fin:['itcd']}},
      {id:'c5', t:'Áreas declaradas na DITCD', campo:{tipo:'texto', ph:'Terreno e construída'}, so:{fin:['itcd']}},
      {id:'c6', t:'Ano da construção, reformas e ampliações', campo:{tipo:'texto', ph:'O que for contado'}, so:{tipo:EDIF}},
      {id:'c7', t:'Combinado: o laudo dá o valor de mercado, que pode ficar acima do declarado', so:{fin:['itcd']}},
      {id:'c8', t:'Taxa de condomínio', d:'Só contexto.', campo:{tipo:'texto', ph:'Valor por mês'}, so:{tipo:['apartamento']}},
      {id:'c9', t:'Quem acompanhou a vistoria', campo:{tipo:'texto', ph:'Nome e relação com o processo'}, so:{mod:['AMJ']}}
    ]},
    {id:'s4', t:'Documentos', itens:[
      {id:'d1', t:'Comunicado da malha e print do ITCD Web', d:'Valor declarado, valor de referência e áreas.', tags:['itcd'], so:{fin:['itcd']}},
      {id:'d2', t:'Certidão atualizada da matrícula' + (C.matricula ? ' ' + C.matricula : ''), d:(C.cartorio ? C.cartorio + '. ' : '') + 'Confirma área, proprietários e averbação.'},
      {id:'d3', t:'PDFs no chat do ' + C.numero, d:C.docsChat ? C.docsChat + '.' : ''},
      {id:'d4', t:C.docSolicitante || 'Documento do solicitante', d:C.docSolicitanteObs || 'Se não for o proprietário, algo que comprove o vínculo.'},
      {id:'d5', t:'Exigências da instituição (habite-se, averbação etc.)', campo:{tipo:'texto', ph:'O que a instituição pede'}, so:{mod:['AMG']}}
    ]},
    {id:'s5', t:'Terreno', so:{tipo:COM_TERRENO}, nota:(areasTexto() ? areasTexto() + '. ' : '') + 'Meça pelo muro.', itens:[
      {id:'e1', t:'Frente', tags:['medir'], campo:{tipo:'num', suf:'m'}},
      {id:'e2', t:'Fundo', tags:['medir'], campo:{tipo:'num', suf:'m'}},
      {id:'e3', t:'Lateral direita (olhando da rua)', tags:['medir'], campo:{tipo:'num', suf:'m'}},
      {id:'e4', t:'Lateral esquerda (olhando da rua)', tags:['medir'], campo:{tipo:'num', suf:'m'}, calc:'terreno'},
      {id:'e5', t:'Formato do lote', campo:{tipo:'opcoes', op:['Regular','Irregular']}},
      {id:'e6', t:'Topografia', campo:{tipo:'opcoes', op:['Plano','Aclive','Declive']}},
      {id:'e7', t:'Posição na quadra', campo:{tipo:'opcoes', op:['Meio de quadra','Esquina']}},
      {id:'e8', t:'Muro alinhado com os vizinhos', d:'Se avança ou recua, anote.', campo:{tipo:'texto', ph:'Observação'}}
    ]},
    {id:'s5l', t:'Lote vago', so:{tipo:['lote']}, itens:[
      {id:'l1', t:'Limpeza', tags:['foto'], campo:{tipo:'opcoes', op:['Limpo','Com mato','Com entulho']}},
      {id:'l2', t:'Cercamento', tags:['foto'], campo:{tipo:'texto', ph:'Muro, cerca ou aberto'}},
      {id:'l3', t:'Drenagem', campo:{tipo:'texto', ph:'Escoamento da água, alagamento'}},
      {id:'l4', t:'Vegetação', tags:['foto'], campo:{tipo:'texto', ph:'Árvores, área de preservação'}},
      {id:'l5', t:'Acesso', campo:{tipo:'texto', ph:'Por onde se chega, rua pavimentada?'}},
      {id:'l6', t:'Marcos', d:'Piquetes ou marcos de divisa.', tags:['foto']}
    ]},
    {id:'s6', t:'Construção', so:{tipo:['casa','galpao']}, nota:C.construidaIptu ? 'IPTU: ' + fmt(C.construidaIptu) + ' m² construídos.' : '', itens:[
      {id:'f1', t:'Tipologia', campo:{tipo:'opcoes', op:['Térrea','Sobrado','Outra']}, so:{tipo:['casa']}},
      {id:'f2', t:'Contorno externo da ' + (C.tipo === 'casa' ? 'casa' : 'construção'), tags:['medir'], campo:{tipo:'grade', itens:[['comp','Comprimento','m'],['larg','Largura','m']]}},
      {id:'f3', t:'Partes fora do IPTU', d:'Varanda, garagem coberta, área de serviço, edícula, puxadinho.', tags:['foto','medir'], campo:{tipo:'texto', ph:'O que é e medidas (ex.: garagem 3 × 5)'}},
      {id:'f4', t:'Área somada das partes fora do IPTU', tags:['medir'], campo:{tipo:'num', suf:'m²'}, calc:'casa'},
      {id:'f5', t:'Cômodos', campo:{tipo:'grade', itens:[['qua','Quartos',''],['sui','Suítes',''],['ban','Banheiros',''],['sal','Salas',''],['vag','Vagas','']]}, so:{tipo:['casa']}}
    ]},
    {id:'s6g', t:'Galpão', so:{tipo:['galpao']}, itens:[
      {id:'gp1', t:'Pé-direito medido', d:'Só entra no laudo se for medido (D-037).', tags:['medir'], campo:{tipo:'num', suf:'m'}},
      {id:'gp2', t:'Vão livre', tags:['medir'], campo:{tipo:'num', suf:'m'}},
      {id:'gp3', t:'Estrutura', tags:['foto'], campo:{tipo:'opcoes', op:['Metálica','Concreto','Mista']}},
      {id:'gp4', t:'Cobertura', tags:['foto'], campo:{tipo:'texto', ph:'Tipo de telha'}},
      {id:'gp5', t:'Piso', tags:['foto'], campo:{tipo:'texto', ph:'Tipo e estado'}},
      {id:'gp6', t:'Docas e portões', tags:['foto'], campo:{tipo:'texto', ph:'Quantos e de que tamanho'}},
      {id:'gp7', t:'Escritório e mezanino', tags:['foto']},
      {id:'gp8', t:'Energia (padrão, trifásica, cabine)', tags:['foto'], campo:{tipo:'texto', ph:'O que tem'}},
      {id:'gp9', t:'Pátio e acesso de carretas', tags:['foto']},
      {id:'gp10', t:'AVCB (Corpo de Bombeiros)', campo:{tipo:'opcoes', op:['Tem, válido','Vencido','Não tem']}}
    ]},
    {id:'s6a', t:'Apartamento', so:{tipo:['apartamento']}, itens:[
      {id:'ap1', t:'Andar, posição e vista', tags:['foto'], campo:{tipo:'texto', ph:'Ex.: 12º andar, frente, vista livre'}},
      {id:'ap2', t:'Vagas', campo:{tipo:'texto', ph:'Quantas, coberta, livre ou presa'}},
      {id:'ap3', t:'Área privativa da matrícula conferida', tags:['medir']},
      {id:'ap4', t:'Portaria, elevador e lazer do condomínio', tags:['foto']}
    ]},
    {id:'s7', t:'Padrão e acabamento', so:{tipo:EDIF}, nota:itcd ? 'É o que diferencia este imóvel da média FIPE da rua.' : 'Fotos que mostram o padrão construtivo.', itens:[
      {id:'g1', t:'Piso da sala, dos quartos e da cozinha', tags:['foto']},
      {id:'g2', t:'Revestimento do banheiro e da cozinha', tags:['foto']},
      {id:'g3', t:'Forro ou laje', tags:['foto']},
      {id:'g4', t:'Telhado e tipo de telha', tags:['foto']},
      {id:'g5', t:'Portas e janelas (material)', tags:['foto']},
      {id:'g6', t:'Portão e muro', tags:['foto']},
      {id:'g7', t:'Padrão construtivo', campo:{tipo:'opcoes', op:['Simples','Normal','Alto']}}
    ]},
    {id:'s8', t:'Conservação', so:{tipo:EDIF}, nota:'Cada defeito: uma foto de perto e outra mostrando onde fica.', itens:[
      {id:'h1', t:'Trincas ou rachaduras', tags:['foto']},
      {id:'h2', t:'Infiltração, umidade ou mofo', tags:['foto']},
      {id:'h3', t:'Telhado, calhas e forro (goteiras)', tags:['foto']},
      {id:'h4', t:'Reboco e pintura', tags:['foto']},
      {id:'h5', t:'Piso quebrado ou solto', tags:['foto']},
      {id:'h6', t:'Estado geral (Ross-Heidecke)', campo:{tipo:'lista', op:['a · Novo','b · Entre novo e regular','c · Regular','d · Entre regular e reparos simples','e · Reparos simples','f · Entre reparos simples e importantes','g · Reparos importantes','h · Entre reparos importantes e sem valor']}}
    ]},
    {id:'s9', t:'Entorno', nota:itcd ? 'A FIPE é a média da rua: mostre o padrão dela.' : 'Mostre o padrão da rua e o que valoriza ou desvaloriza.', itens:[
      {id:'i1', t:'Rua nos dois sentidos', tags:['foto']},
      {id:'i2', t:'Asfalto, calçada, meio-fio e iluminação', tags:['foto']},
      {id:'i3', t:'Três ou quatro imóveis da mesma rua', tags:['foto']},
      {id:'i4', t:'Comércio, ponto de ônibus e escola por perto', campo:{tipo:'texto', ph:'O que tem e a que distância'}},
      {id:'i5', t:'Pontos negativos', d:'Córrego, lote baldio, via barulhenta, área de risco.', campo:{tipo:'texto', ph:'Se houver'}}
    ]},
    {id:'s10', t:'Fotos dos ambientes', so:{tipo:['casa','apartamento']}, itens:[
      {id:'j1', t:'Sala', tags:['foto']},
      {id:'j2', t:'Cozinha', tags:['foto']},
      {id:'j3', t:'Quartos', tags:['foto']},
      {id:'j4', t:'Banheiros', tags:['foto']},
      {id:'j5', t:'Área de serviço', tags:['foto']},
      {id:'j6', t:'Quintal da frente e dos fundos', tags:['foto'], so:{tipo:['casa']}}
    ]},
    {id:'s11', t:'Antes de ir embora', itens:[
      {id:'k1', t:'Fotos conferidas: nítidas e nada faltando'},
      {id:'k2', t:'Combinado o envio dos documentos que faltam'},
      {id:'k3', t:'Vistoria enviada ao trabalho ' + C.numero + ', junto com as fotos', d:'Use o botão verde lá embaixo.'}
    ]}
  ];
  if (C.mod === 'AMJ' && C.quesitos && C.quesitos.length) {
    S.splice(S.length - 1, 0, {id:'s12', t:'Quesitos do processo', itens:C.quesitos.map(function(q, i){
      return {id:'q' + (i + 1), t:'Quesito ' + (i + 1) + ': ' + q, campo:{tipo:'texto', ph:'O que foi observado'}};
    })});
  }
  return S;
}
"""


def pagina(c: dict, envio: str, app: str = "") -> str:
    """HTML auto-contido (funciona sem internet). `envio` é o endereço que recebe a vistoria (com o código do trabalho)."""
    e = html.escape
    fontes = "".join(
        f"@font-face{{font-family:{fam};font-weight:{peso};src:url(data:font/woff2;base64,{_fonte(arq)}) format('woff2')}}"
        for fam, peso, arq in (("Sora", 700, "sora-latin-700-normal.woff2"), ("M", 400, "manrope-latin-400-normal.woff2"),
                               ("M", 700, "manrope-latin-700-normal.woff2")))
    end = ", ".join(x for x in (c["rua"], c["quadraLote"]) if x)
    sub = " · ".join(x for x in (end, c["bairro"], c["cidade"]) if x)
    meta = " · ".join(x for x in (f"Visita: {c['visita']}" if c["visita"] else "", c["modNome"], c["finNome"]) if x)
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Vistoria{(' ' + e(c['numero'])) if c['numero'].isdigit() else ''}</title>
<style>{fontes}
*{{box-sizing:border-box}}
body{{font:400 18px/1.45 M,system-ui,sans-serif;margin:0;background:#F4EDE4;color:#16283A}}
main{{padding:16px 16px 150px;display:grid;gap:14px;max-width:760px;margin:auto}}
h1{{font:700 28px/1.15 Sora,sans-serif;margin:0}} .sub{{color:#56616B;margin:2px 0 0;font-size:18px}}
.ficha{{background:#fff;border:1px solid #E2DBD0;border-radius:18px;padding:12px 16px;display:grid;gap:4px;font-size:16px}}
.ficha a{{color:#16283A;font-weight:700}}
.topo{{position:sticky;top:0;z-index:5;background:#F4EDE4;padding:10px 0 8px;display:grid;gap:8px;border-bottom:1px solid #E2DBD0}}
.prog{{display:flex;align-items:center;gap:12px;font-weight:700}} .barra{{flex:1;height:12px;border-radius:10px;background:#E2DBD0;overflow:hidden}}
.barra span{{display:block;height:100%;width:0;background:#14803F;border-radius:10px}}
.salvo{{font-size:16px;color:#56616B}}
#so-falta{{min-height:48px;border-radius:14px;border:2px solid #16283A;background:#fff;color:#16283A;font:700 17px M,sans-serif;padding:0 16px}}
#so-falta[aria-pressed=true]{{background:#16283A;color:#fff}}
.sec{{background:#fff;border:1px solid #E2DBD0;border-radius:22px;overflow:hidden}}
.sec>summary{{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:16px 18px;font:700 20px Sora,sans-serif;cursor:pointer;list-style:none;min-height:60px}}
.sec>summary::-webkit-details-marker{{display:none}}
.cont{{font:800 16px M,sans-serif;padding:6px 12px;border-radius:30px;background:#F4EDE4;white-space:nowrap}}
.cont.ok{{background:#E6F2EA;color:#0E6B33}}
.nota{{margin:0;padding:0 18px 10px;color:#56616B;font-size:16px}} .ctx .nota{{color:#b5562b;font-weight:700}}
.it{{border-top:1px solid #E2DBD0;padding:14px 18px;display:grid;gap:8px}}
.it.feito .t{{color:#0E6B33}} .lin{{display:flex;gap:12px;align-items:flex-start}}
.chk{{flex:none;width:32px;height:32px;margin-top:2px;accent-color:#14803F}}
.t{{font-weight:700}} .d{{color:#56616B;font-size:16px;margin:0}}
.chips{{display:flex;gap:6px;flex-wrap:wrap}} .chip{{font:800 16px M,sans-serif;padding:2px 10px;border-radius:20px;background:#F4EDE4}}
.chip.itcd{{background:#FDF3D0}} .chip.medir{{background:#E6F2EA}}
.it input:not(.chk),.it select,textarea{{font:400 18px M,sans-serif;padding:10px 12px;border:2px solid #E2DBD0;border-radius:14px;color:#16283A;min-height:52px;width:100%;background:#fff}}
.grade{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px}} .grade label{{font-size:16px;color:#56616B}}
.ops{{display:flex;flex-wrap:wrap;gap:8px}} .op{{min-height:48px;padding:0 16px;border-radius:14px;border:2px solid #E2DBD0;background:#fff;color:#16283A;font:700 17px M,sans-serif}}
.op.on{{background:#16283A;color:#fff;border-color:#16283A}}
.conta{{background:#E6F2EA;border-radius:12px;padding:8px 12px;font-size:16px;font-weight:700}} .conta.alerta{{background:#FDE8E4;color:#9b2c1d}}
.link{{font-weight:700;color:#16283A}}
.esconde{{display:none!important}}
.fixo{{position:fixed;left:0;right:0;bottom:0;background:#F4EDE4;border-top:1px solid #E2DBD0;padding:10px 16px 14px;display:grid;gap:6px;justify-items:center}}
#concluir{{font:700 19px M,sans-serif;min-height:60px;width:100%;max-width:728px;background:#14803F;color:#fff;border:0;border-radius:16px;box-shadow:0 4px 0 #0e5f2e}}
#copiar{{font:700 16px M,sans-serif;background:none;border:0;color:#56616B;text-decoration:underline;min-height:40px}}
.modal{{position:fixed;inset:0;background:#16283a66;display:flex;align-items:flex-end;justify-content:center;z-index:20;padding:16px}}
.caixa{{background:#fff;border-radius:22px;padding:20px;width:100%;max-width:520px;display:grid;gap:12px}}
.caixa h2{{font:700 22px Sora,sans-serif;margin:0}}
.bt{{min-height:56px;border-radius:16px;font:700 18px M,sans-serif;border:2px solid #16283A;background:#fff;color:#16283A}}
.bt.v{{background:#14803F;color:#fff;border-color:#14803F}}
.fim{{position:fixed;inset:0;background:#F4EDE4;z-index:30;display:grid;place-content:center;gap:16px;padding:24px;text-align:center}}
.fim h2{{font:700 30px Sora,sans-serif;margin:0;color:#0E6B33}}
</style></head><body><main>
<div><h1>Vistoria{(' nº ' + e(c['numero'])) if c['numero'].isdigit() else ''} · {e(c['tipoNome'])}</h1><p class="sub">{e(sub)}</p><p class="sub">{e(meta)}</p></div>
<div class="ficha" id="ficha"></div>
<div class="topo"><div class="prog"><div class="barra"><span id="barra"></span></div><span id="conta">0 de 0</span></div>
<div style="display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap">
<button id="so-falta" type="button" aria-pressed="false">Mostrar só o que falta</button><span class="salvo" id="salvo">Salvo neste aparelho</span></div></div>
<div id="secoes"></div>
<section class="sec" style="padding:14px 18px"><p class="t" style="margin:0 0 8px">Observações gerais</p><textarea id="obs" rows="4" placeholder="Algo que não coube nos itens"></textarea></section>
</main><div class="fixo"><button id="concluir" type="button">Concluir vistoria</button><button id="copiar" type="button">Copiar o texto</button></div>
<script>
var C = {json.dumps(c, ensure_ascii=False)};
var ENVIO = {json.dumps(envio)}; var APP = {json.dumps(app)};
var CHAVE = 'jdb-vistoria-' + C.numero;
function fmt(n){{ return Number(n).toLocaleString('pt-BR', {{minimumFractionDigits: 2, maximumFractionDigits: 2}}); }}
function areasTexto(){{ var p = []; if (C.terrenoDoc) p.push((C.terrenoDocFonte ? C.terrenoDocFonte.charAt(0).toUpperCase() + C.terrenoDocFonte.slice(1) : 'Documento') + ' ' + fmt(C.terrenoDoc) + ' m²');
  if (C.terrenoIptu) p.push('IPTU' + (C.iptuAno ? ' ' + C.iptuAno : '') + ' ' + fmt(C.terrenoIptu) + ' m²'); return p.join(' · '); }}
{P11_JS}
function vale(so){{ if (!so) return true; for (var k in so) {{ if (so[k].indexOf(C[k]) < 0) return false; }} return true; }}
var SECOES = montarSecoes(C).filter(function(s){{ return vale(s.so); }}).map(function(s){{ s.itens = s.itens.filter(function(i){{ return vale(i.so); }}); return s; }}).filter(function(s){{ return s.itens.length; }});
var EST = {{}}; try {{ EST = JSON.parse(localStorage.getItem(CHAVE) || '{{}}'); }} catch (e) {{ EST = {{}}; }}
EST.m = EST.m || {{}}; EST.v = EST.v || {{}};
function salvar(){{ try {{ localStorage.setItem(CHAVE, JSON.stringify(EST)); document.getElementById('salvo').textContent = 'Salvo neste aparelho ' + new Date().toLocaleTimeString('pt-BR', {{hour:'2-digit', minute:'2-digit'}}); }} catch (e) {{ document.getElementById('salvo').textContent = 'Não deu para salvar neste aparelho'; }} }}
function tem(v){{ if (v == null) return false; if (typeof v === 'object') {{ for (var k in v) if (String(v[k]).trim()) return true; return false; }} return String(v).trim() !== ''; }}
function feito(i){{ return !!EST.m[i.id] || tem(EST.v[i.id]); }}
var TOTAL = 0; SECOES.forEach(function(s){{ TOTAL += s.itens.length; }});
// ficha do caso: terreno (documento × IPTU), construída do IPTU, entrega e o Maps
(function(){{ var f = []; if (areasTexto()) f.push('Terreno: ' + areasTexto());
  if (C.construidaIptu) f.push('Construída (IPTU' + (C.iptuAno ? ' ' + C.iptuAno : '') + '): ' + fmt(C.construidaIptu) + ' m²');
  if (C.entregaNome) f.push('Entrega: ' + C.entregaNome);
  var end = [C.rua, C.quadraLote, C.bairro, C.cidade].filter(Boolean).join(', ');
  var h = f.map(function(x){{ return '<span>' + x + '</span>'; }}).join('');
  if (end) h += '<a href="https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(end) + '" target="_blank" rel="noopener">Abrir o endereço no Google Maps</a>';
  var el = document.getElementById('ficha'); if (h) el.innerHTML = h; else el.remove(); }})();
function esc(s){{ return String(s).replace(/[&<>"]/g, function(c){{ return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]; }}); }}
function campoHtml(i){{ var c = i.campo; if (!c) return ''; var v = EST.v[i.id];
  if (c.tipo === 'opcoes') return '<div class="ops">' + c.op.map(function(o){{ return '<button type="button" class="op' + (v === o ? ' on' : '') + '" data-op="' + esc(o) + '">' + esc(o) + '</button>'; }}).join('') + '</div>';
  if (c.tipo === 'lista') return '<select data-c><option value="">Escolha</option>' + c.op.map(function(o){{ return '<option' + (v === o ? ' selected' : '') + '>' + esc(o) + '</option>'; }}).join('') + '</select>';
  if (c.tipo === 'grade') return '<div class="grade">' + c.itens.map(function(g){{ var x = (v || {{}})[g[0]] || ''; return '<label>' + g[1] + (g[2] ? ' (' + g[2] + ')' : '') + '<input inputmode="decimal" data-g="' + g[0] + '" value="' + esc(x) + '"></label>'; }}).join('') + '</div>';
  var tp = c.tipo === 'data' ? 'date' : 'text'; var im = c.tipo === 'num' ? ' inputmode="decimal"' : '';
  return '<input type="' + tp + '"' + im + ' data-c placeholder="' + esc(c.ph || (c.suf ? 'em ' + c.suf : '')) + '" value="' + esc(v || '') + '">';
}}
function desenhar(){{
  var h = '';
  SECOES.forEach(function(s, n){{
    h += '<details class="sec' + (s.ctx ? ' ctx' : '') + '" data-s="' + s.id + '"' + (n < 2 ? ' open' : '') + '><summary><span>' + (n + 1) + '. ' + esc(s.t) + '</span><b class="cont"></b></summary>';
    if (s.nota) h += '<p class="nota">' + esc(s.nota) + '</p>';
    s.itens.forEach(function(i){{
      var chips = (i.tags || []).map(function(t){{ return '<span class="chip ' + t + '">' + ({{foto:'Foto', medir:'Medir', itcd:'ITCD'}}[t] || t) + '</span>'; }}).join('');
      h += '<div class="it" data-i="' + i.id + '"><div class="lin"><input type="checkbox" class="chk" aria-label="' + esc(i.t) + '"><div style="display:grid;gap:4px"><span class="t">' + esc(i.t) + '</span>' + (i.d ? '<p class="d">' + esc(i.d) + '</p>' : '') + (chips ? '<div class="chips">' + chips + '</div>' : '') + '</div></div>' + campoHtml(i) + (i.link ? '<a class="link" href="' + i.link.href + '" target="_blank" rel="noopener">' + esc(i.link.t) + '</a>' : '') + (i.calc ? '<div class="conta esconde" data-calc="' + i.calc + '"></div>' : '') + '</div>';
    }});
    h += '</details>';
  }});
  document.getElementById('secoes').innerHTML = h;
  document.getElementById('obs').value = EST.obs || '';
  ligar(); atualizar();
}}
function achar(id){{ for (var a = 0; a < SECOES.length; a++) for (var b = 0; b < SECOES[a].itens.length; b++) if (SECOES[a].itens[b].id === id) return SECOES[a].itens[b]; }}
function ligar(){{
  document.querySelectorAll('.it').forEach(function(el){{ var i = achar(el.dataset.i);
    el.querySelector('.chk').onchange = function(){{ EST.m[i.id] = this.checked; salvar(); atualizar(); }};
    el.querySelectorAll('[data-c]').forEach(function(x){{ x.oninput = x.onchange = function(){{ EST.v[i.id] = x.value; salvar(); atualizar(); }}; }});
    el.querySelectorAll('[data-g]').forEach(function(x){{ x.oninput = function(){{ EST.v[i.id] = EST.v[i.id] || {{}}; EST.v[i.id][x.dataset.g] = x.value; salvar(); atualizar(); }}; }});
    el.querySelectorAll('.op').forEach(function(b){{ b.onclick = function(){{ EST.v[i.id] = EST.v[i.id] === b.dataset.op ? '' : b.dataset.op; el.querySelectorAll('.op').forEach(function(o){{ o.classList.toggle('on', o.dataset.op === EST.v[i.id]); }}); salvar(); atualizar(); }}; }});
  }});
  document.getElementById('obs').oninput = function(){{ EST.obs = this.value; salvar(); }};
}}
function n(v){{ var x = parseFloat(String(v || '').replace(',', '.')); return isFinite(x) ? x : null; }}
function contas(){{
  var r = {{}};
  var fr = n(EST.v.e1), fu = n(EST.v.e2), ld = n(EST.v.e3), le = n(EST.v.e4);
  if (fr && fu && ld && le) {{ var a = ((fr + fu) / 2) * ((ld + le) / 2); var t = 'Estimativa de campo do terreno: ' + fmt(a) + ' m²';
    var ref = []; if (C.terrenoDoc) ref.push([C.terrenoDocFonte || 'Documento', C.terrenoDoc]); if (C.terrenoIptu) ref.push(['IPTU', C.terrenoIptu]);
    if (ref.length) {{ ref.sort(function(x, y){{ return Math.abs(x[1] - a) - Math.abs(y[1] - a); }});
      t += ' (' + ref.map(function(x){{ return x[0] + ' ' + fmt(x[1]); }}).join(' · ') + '; mais perto ' + (ref[0][0].toLowerCase() === 'iptu' ? 'do IPTU' : 'da ' + ref[0][0].toLowerCase()) + ')'; }}
    r.terreno = [t, false]; }}
  var g = EST.v.f2 || {{}}; var comp = n(g.comp), larg = n(g.larg), fora = n(EST.v.f4) || 0;
  if (comp && larg) {{ var tot = comp * larg + fora; r.casa = ['Construção: ' + fmt(comp * larg) + (fora ? ' + ' + fmt(fora) : '') + ' = ' + fmt(tot) + ' m²' + (C.construidaIptu ? ' × IPTU ' + fmt(C.construidaIptu) + ' m²' : '') + '. Estimativa de campo, só para conferir: medida de trena não entra em número no laudo.', false]; }}
  if (EST.v.c2) {{ var d = new Date(EST.v.c2 + 'T12:00:00'); d.setDate(d.getDate() + 30); var txt = 'Prazo aproximado para justificar: ' + d.toLocaleDateString('pt-BR');
    var alerta = C.entrega && new Date(C.entrega + 'T12:00:00') > d; r.prazo = [txt + (alerta ? '. Atenção: vence antes da entrega do laudo.' : ''), alerta]; }}
  return r;
}}
var SO_FALTA = false;
function atualizar(){{
  var tot = 0, ok = 0, r = contas();
  SECOES.forEach(function(s){{ var x = 0;
    s.itens.forEach(function(i){{ var f = feito(i); var el = document.querySelector('.it[data-i="' + i.id + '"]'); tot++; if (f) {{ ok++; x++; }}
      el.classList.toggle('feito', f); el.querySelector('.chk').checked = f; el.classList.toggle('esconde', SO_FALTA && f);
      var cc = el.querySelector('[data-calc]'); if (cc) {{ var v = r[i.calc]; cc.classList.toggle('esconde', !v); if (v) {{ cc.textContent = v[0]; cc.classList.toggle('alerta', v[1]); }} }}
    }});
    var sec = document.querySelector('.sec[data-s="' + s.id + '"]'); var c = sec.querySelector('.cont'); c.textContent = x + '/' + s.itens.length; c.classList.toggle('ok', x === s.itens.length);
    sec.classList.toggle('esconde', SO_FALTA && x === s.itens.length);
  }});
  document.getElementById('conta').textContent = ok + ' de ' + tot + ' feitos';
  document.getElementById('barra').style.width = (tot ? 100 * ok / tot : 0) + '%';
  return tot - ok;
}}
function soFalta(on){{ SO_FALTA = on; var b = document.getElementById('so-falta'); b.setAttribute('aria-pressed', on); b.textContent = on ? 'Mostrar todos' : 'Mostrar só o que falta';
  if (on) document.querySelectorAll('.sec').forEach(function(s){{ s.open = true; }}); atualizar(); }}
document.getElementById('so-falta').onclick = function(){{ soFalta(!SO_FALTA); }};
function valorTxt(i){{ var v = EST.v[i.id]; if (!tem(v)) return ''; var c = i.campo || {{}};
  if (c.tipo === 'grade') return c.itens.filter(function(g){{ return (v[g[0]] || '').trim(); }}).map(function(g){{ return g[1] + ' ' + v[g[0]] + (g[2] ? ' ' + g[2] : ''); }}).join(', ');
  if (c.tipo === 'data') return new Date(v + 'T12:00:00').toLocaleDateString('pt-BR');
  return v + (c.suf ? ' ' + c.suf : ''); }}
function texto(){{
  var agora = new Date(); var r = contas(); var ok = 0;
  SECOES.forEach(function(s){{ s.itens.forEach(function(i){{ if (feito(i)) ok++; }}); }});
  var end = [C.rua, C.quadraLote].filter(Boolean).join(', ');
  var L = ['VISTORIA Nº ' + C.numero + ' · ' + [C.tipoNome, end, C.bairro, C.cidade].filter(Boolean).join(' · '),
           'Checklist enviado em ' + agora.toLocaleDateString('pt-BR') + ' às ' + agora.getHours() + 'h' + String(agora.getMinutes()).padStart(2, '0') + ' · ' + ok + ' de ' + TOTAL + ' itens feitos', ''];
  SECOES.forEach(function(s, k){{ L.push((k + 1) + '. ' + s.t.toUpperCase() + (s.ctx ? ' (só contexto, não entra no laudo)' : ''));
    s.itens.forEach(function(i){{ var v = valorTxt(i); L.push('[' + (feito(i) ? 'x' : ' ') + '] ' + i.t + (v ? ': ' + v : ''));
      if (i.calc && r[i.calc]) L.push('    ' + r[i.calc][0]); }}); L.push(''); }});
  L.push('OBSERVAÇÕES'); L.push((EST.obs || '').trim() || '(nenhuma)');
  return L.join('\\n');
}}
function modal(h){{ var m = document.createElement('div'); m.className = 'modal'; m.innerHTML = '<div class="caixa">' + h + '</div>'; document.body.appendChild(m); return m; }}
function tela(h){{ var m = document.createElement('div'); m.className = 'fim'; m.innerHTML = h; document.body.appendChild(m); return m; }}
function fila(){{ try {{ return JSON.parse(localStorage.getItem(CHAVE + '-fila') || 'null'); }} catch (e) {{ return null; }} }}
async function mandar(p){{ var r = await fetch(ENVIO, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(p)}}); if (!r.ok) throw new Error('http ' + r.status); }}
async function tentarFila(){{ var p = fila(); if (!p) return; try {{ await mandar(p); try {{ localStorage.removeItem(CHAVE + '-fila'); }} catch (e) {{}}
  tela('<h2>✓ Vistoria enviada ao trabalho</h2><p>A internet voltou e eu enviei.</p>' + (APP ? '<a class="bt v" style="display:grid;place-content:center;text-decoration:none" href="' + APP + '">Abrir o trabalho</a>' : '')); }} catch (e) {{}} }}
window.addEventListener('online', tentarFila); setInterval(tentarFila, 30000);
async function concluir(){{
  var p = {{texto: texto(), marcas: EST, feitos: TOTAL - atualizar(), total: TOTAL}};
  try {{ await mandar(p);
    tela('<h2>✓ Vistoria enviada ao trabalho</h2><p>O texto e as marcações já estão no trabalho' + (/^[0-9]+$/.test(C.numero) ? ' ' + esc(C.numero) : '') + '.</p>' + (APP ? '<a class="bt v" style="display:grid;place-content:center;text-decoration:none" href="' + APP + '">Abrir o trabalho</a>' : ''));
  }} catch (e) {{
    try {{ localStorage.setItem(CHAVE + '-fila', JSON.stringify(p)); }} catch (x) {{}}
    tela('<h2 style="color:#16283A">Salvo no celular</h2><p>Envio sozinho quando a internet voltar.</p><button class="bt" type="button" onclick="this.parentElement.remove()">Voltar à vistoria</button>');
  }}
}}
document.getElementById('concluir').onclick = function(){{
  var falta = atualizar();
  if (!falta) {{ concluir(); return; }}
  var m = modal('<h2>Faltam ' + falta + ' ' + (falta === 1 ? 'item' : 'itens') + '.</h2><button class="bt" type="button" id="m-falta">Mostrar o que falta</button><button class="bt v" type="button" id="m-assim">Concluir assim mesmo</button>');
  m.querySelector('#m-falta').onclick = function(){{ m.remove(); soFalta(true); window.scrollTo({{top:0}}); }};
  m.querySelector('#m-assim').onclick = function(){{ m.remove(); concluir(); }};
}};
document.getElementById('copiar').onclick = async function(){{ var t = texto(); try {{ await navigator.clipboard.writeText(t); this.textContent = '✓ Texto copiado'; }} catch (e) {{ prompt('Copie o texto:', t); }} }};
desenhar(); tentarFila();
</script></body></html>"""
