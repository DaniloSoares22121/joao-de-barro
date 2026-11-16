"""ORDEM 041 / D-092 / D-054: página de vistoria sob medida, gerada para cada trabalho.

Parte do checklist por ambiente (D-054) no formato que o sistema já lê ("VISTORIA – OV – Casa",
"## Seção", "- rótulo: valor", "Não feito: …") e se ajusta ao tipo de imóvel, à modalidade e à
finalidade. Só entra item que o K0 sustenta (cada grupo cita a fonte). Nenhuma exigência legal,
prazo ou norma que não esteja conferida na P4. A página funciona no celular sem internet: o botão
"Copiar para o JdB" gera o texto para colar na conversa do cliente."""
from __future__ import annotations

import base64
import html
import json
import unicodedata
from pathlib import Path

# (seção, [itens], fonte)
BASE = [
    ("Fachada e entorno", ["Fachada frontal fotografada (capa)", "Rua e acesso", "Vizinhança"], "K0.5"),
    ("Estado e idade", ["Estado de conservação", "Idade aparente (estimada)"], "K0.5 / D-071"),
    ("Áreas", ["As medidas conferidas batem com o documento? (sim/não)", "Construção que não está no documento"],
     "K0.4 / D-055 / D-027"),
    ("Benfeitorias fixas", ["Benfeitorias fixas (ex.: fotovoltaico, ar-condicionado, planejados)"], "K0.7"),
]
POR_TIPO = {
    "casa": [("Ambientes (uma foto por ambiente, de fora para dentro)",
              ["Sala", "Cozinha", "Quartos (quantos)", "Banheiros (quantos)", "Área de serviço", "Garagem (vagas)",
               "Quintal / área externa"], "K0.5 / D-022"),
             ("Construção", ["Telhado", "Piso", "Esquadrias", "Umidade ou trincas"], "K0.5")],
    "apartamento": [("Unidade", ["Andar e posição", "Ambientes (uma foto por ambiente)", "Vaga(s) de garagem"], "K0.5"),
                    ("Condomínio", ["Fachada do condomínio (capa sem demarcação se não der para ver a torre)",
                                    "Áreas comuns e lazer"], "K0.5 / regra do Alan")],
    "galpao": [("Objeto da avaliação", ["Galpão inteiro ou só uma parte do lote? (qual)",
                                        "Outras construções no mesmo lote"], "K0.4 / D-059"),
               ("Construção", ["Estrutura (metálica / concreto)", "Cobertura (tipo de telha)", "Piso",
                               "Docas", "Escritórios / mezanino", "Pátio e manobra",
                               "Pé-direito (só se medido; não medido fica fora)"], "K0.4 / D-037"),
               ("Medição", ["Contorno para medir por satélite (o que não está em documento)"], "D-027")],
    "lote": [("Lote", ["Topografia", "Frente e fundos (sem medida de trena no laudo)", "Cercamento",
                       "Infraestrutura (água, energia, asfalto)"], "K0.4 / D-055")],
}
POR_MODALIDADE = {
    "AMJ": [("Processo", ["Dados do processo conferidos com os autos", "O que observar para cada quesito"],
             "K0.2 (AMJ responde os quesitos)")],
    "AM_GARANTIA": [("Instituição", ["Exigências do formato da instituição, se houver"], "K0.2")],
}
POR_FINALIDADE = {
    "itcmd": [("Fisco", ["Comunicado do Fisco recebido (anexar)", "Valor de referência informado no comunicado"],
               "F-K016 (contestação de valor)")],
}
CONVERSA = ("Conversa com o proprietário", ["Contexto (não entra no laudo)"], "D-013")


def _n(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def classe_tipo(tipo: str) -> str:
    t = _n(tipo)
    if any(x in t for x in ("galpao", "barracao", "deposito", "armazem")):
        return "galpao"
    if any(x in t for x in ("apart", "apto", "flat", "kitnet")):
        return "apartamento"
    if any(x in t for x in ("lote", "terreno")):
        return "lote"
    return "casa"


def secoes(tipo: str, modalidade: str, finalidade: str) -> list[tuple[str, list[str], str]]:
    out = list(BASE[:1]) + POR_TIPO[classe_tipo(tipo)] + list(BASE[1:])
    out += POR_MODALIDADE.get(modalidade, [])
    f = _n(finalidade)
    if "itcd" in f or "itcmd" in f or "heranca" in f or "doacao" in f:
        out += POR_FINALIDADE["itcmd"]
    out.append(CONVERSA)
    return out


ROTULO_TIPO = {"casa": "Casa / Sobrado", "apartamento": "Apartamento", "galpao": "Galpão", "lote": "Lote"}


_FONTES = Path(__file__).parent / "assets" / "fontes"


def _fonte(nome: str) -> str:
    """Fonte embutida em base64: a página funciona no celular sem internet (ORDEM 053, L7)."""
    try:
        return base64.b64encode((_FONTES / nome).read_bytes()).decode()
    except OSError:
        return ""


# itens de estado (Bom / Regular / Ruim com um toque); os demais são anotação livre
_ESTADO = ("telhado", "piso", "esquadrias", "estrutura", "cobertura", "estado de conservacao", "paredes",
           "sala", "cozinha", "banheiros", "area de servico", "fachada", "docas")


def _eh_estado(item: str) -> bool:
    t = _n(item)
    return "?" not in item and "quantos" not in t and any(t.startswith(x) for x in _ESTADO)


def pagina(dados: dict) -> str:
    """HTML auto-contido (sem internet) com o checklist do trabalho — desenho L7 do designer."""
    tipo = dados.get("imovel_tipo") or ""
    mod = dados.get("modalidade") or "OV"
    fin = dados.get("finalidade") or ""
    cab = f"VISTORIA – {mod} – {ROTULO_TIPO[classe_tipo(tipo)]}"
    e = html.escape
    blocos = []
    for i, (sec, itens, fonte) in enumerate(secoes(tipo, mod, fin)):
        linhas = []
        for it in itens:
            botoes = ""
            if _eh_estado(it):
                botoes = '<div class="est">' + "".join(
                    f'<button type="button" class="op" data-v="{v}">{v}</button>' for v in ("Bom", "Regular", "Ruim")) + "</div>"
            linhas.append(f'<div class="it"><p class="nome">{e(it)}</p>{botoes}'
                          f'<input data-r="{e(it)}" placeholder="{"Observação curta…" if botoes else "Anotar…"}" aria-label="{e(it)}"></div>')
        aberto = " open" if i == 0 else ""
        blocos.append(f'<details class="sec" data-sec="{e(sec)}"{aberto}><summary><span>{e(sec)}</span>'
                      f'<b class="cont">0/{len(itens)}</b></summary>{"".join(linhas)}</details>')   # fonte fica no código, não na tela
    endereco = " · ".join(x for x in (dados.get("imovel_endereco"), dados.get("bairro"), dados.get("cidade")) if x)
    sub = " · ".join(x for x in (endereco, fin) if x)
    fontes = "".join(
        f"@font-face{{font-family:{fam};font-weight:{peso};src:url(data:font/woff2;base64,{_fonte(arq)}) format('woff2')}}"
        for fam, peso, arq in (("Sora", 700, "sora-latin-700-normal.woff2"), ("M", 400, "manrope-latin-400-normal.woff2"),
                               ("M", 700, "manrope-latin-700-normal.woff2")))
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Vistoria</title>
<style>{fontes}
*{{box-sizing:border-box}}
body{{font:400 18px/1.45 M,system-ui,sans-serif;margin:0;background:#F4EDE4;color:#16283A}}
main{{padding:18px 18px 130px;display:grid;gap:14px;max-width:720px;margin:auto}}
h1{{font:700 30px/1.15 Sora,sans-serif;margin:0}} .sub{{color:#56616B;margin:4px 0 0}}
.prog{{display:flex;align-items:center;gap:14px;font-weight:700}} .barra{{flex:1;height:12px;border-radius:10px;background:#E2DBD0;overflow:hidden}}
.barra span{{display:block;height:100%;width:0;background:#14803F;border-radius:10px}}
.sec{{background:#fff;border:1px solid #E2DBD0;border-radius:22px;overflow:hidden}}
.sec summary{{display:flex;justify-content:space-between;align-items:center;padding:20px 22px;font:700 22px Sora,sans-serif;cursor:pointer;list-style:none;min-height:64px}}
.sec summary::-webkit-details-marker{{display:none}}
.cont{{font:800 16px M,sans-serif;letter-spacing:1px;padding:6px 12px;border-radius:30px;background:#F4EDE4;color:#16283A}}
.cont.ok{{background:#E6F2EA;color:#0E6B33}}
.it{{border-top:1px solid #E2DBD0;padding:16px 22px;display:grid;gap:10px}} .nome{{margin:0;font-weight:700}}
.est{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}
.op{{min-height:52px;border-radius:14px;border:2px solid #E2DBD0;background:#fff;color:#16283A;font:700 18px M,sans-serif}}
.op.on{{background:#16283A;color:#fff;border-color:#16283A}}
.it input{{font:400 18px M,sans-serif;padding:12px 14px;border:2px solid #E2DBD0;border-radius:14px;color:#16283A;min-height:52px}}
.it input::placeholder{{color:#56616B}}
.f{{font-size:16px;color:#56616B;margin:0;padding:0 22px 16px}}
.fixo{{position:fixed;left:0;right:0;bottom:0;background:#F4EDE4;border-top:1px solid #E2DBD0;padding:12px 18px 18px}}
#copiar{{font:700 19px M,sans-serif;min-height:60px;width:100%;max-width:684px;display:block;margin:auto;background:#14803F;color:#fff;border:0;border-radius:16px;box-shadow:0 4px 0 #0e5f2e}}
#ok{{text-align:center;margin:6px 0 0}}
</style></head><body><main>
<h1>Vistoria</h1><p class="sub">{e(sub or cab)}</p>
<p class="sub">{e(dados.get('solicitante_nome') or '')}{' · Visita: ' + e(dados.get('visita_legivel')) if dados.get('visita_legivel') else ''}</p>
<div class="prog"><div class="barra"><span id="barra"></span></div><span id="conta">0 itens</span></div>
{''.join(blocos)}
</main><div class="fixo"><button id="copiar" type="button">Concluir vistoria</button><p id="ok" role="status"></p></div>
<script>
const CAB = {json.dumps(cab, ensure_ascii=False)};
const its = [...document.querySelectorAll('.it')];
function valor(it) {{
  const on = it.querySelector('.op.on'); const obs = it.querySelector('input').value.trim();
  return [on ? on.dataset.v : '', obs].filter(Boolean).join(' – ');
}}
function contar() {{
  let feitos = 0;
  for (const s of document.querySelectorAll('.sec')) {{
    const lst = [...s.querySelectorAll('.it')]; const n = lst.filter((i) => valor(i)).length; feitos += n;
    const c = s.querySelector('.cont'); c.textContent = n + '/' + lst.length; c.classList.toggle('ok', n === lst.length);
  }}
  document.getElementById('conta').textContent = feitos + ' de ' + its.length + ' itens';
  document.getElementById('barra').style.width = (100 * feitos / its.length) + '%';
}}
for (const b of document.querySelectorAll('.op')) b.onclick = () => {{
  const irmaos = b.parentElement.querySelectorAll('.op'); const ja = b.classList.contains('on');
  irmaos.forEach((x) => x.classList.remove('on')); if (!ja) b.classList.add('on'); contar();
}};
for (const i of document.querySelectorAll('.it input')) i.oninput = contar;
contar();
document.getElementById('copiar').onclick = async () => {{
  const linhas = [CAB];
  for (const s of document.querySelectorAll('.sec')) {{
    linhas.push('## ' + s.dataset.sec);
    const nao = [];
    for (const it of s.querySelectorAll('.it')) {{
      const r = it.querySelector('input').dataset.r; const v = valor(it);
      if (v) linhas.push('- ' + r + ': ' + v); else nao.push(r);
    }}
    if (nao.length) linhas.push('Não feito: ' + nao.join('; '));
  }}
  const txt = linhas.join('\\n');
  try {{ await navigator.clipboard.writeText(txt); document.getElementById('ok').textContent = 'Copiado. Cole na conversa do cliente no JdB.'; }}
  catch (e) {{ prompt('Copie o texto:', txt); }}
}};
</script></body></html>"""
