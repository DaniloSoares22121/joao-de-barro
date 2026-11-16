/* ORDEM 053 (S1/S2): script das páginas públicas. Fontes servidas junto (sem internet) e os planos
 * lidos do próprio JdB (/planos/publico) — os números são os da ORDEM 040, sem copiar à mão. */
import '@fontsource/sora/700.css'
import '@fontsource/manrope/400.css'
import '@fontsource/manrope/700.css'
import './site.css'

interface Plano { nome: string; preco: number; incluidos: number; extra: number; destaque: boolean }
interface Resp { ordem: string[]; planos: Record<string, Plano>; comparacao_avulso_10: number }

const brl = (v: number) => `R$ ${v.toLocaleString('pt-BR', { maximumFractionDigits: 2 })}`
const APP = './joaodebarro.html'

async function planos() {
  const alvo = document.getElementById('planos-lista')
  if (!alvo) return
  try {
    const r: Resp = await (await fetch('/api/avaliacao/planos/publico')).json()
    // na tela, o destaque primeiro (como no desenho)
    const ordem = [...r.ordem].sort((a, b) => Number(r.planos[b].destaque) - Number(r.planos[a].destaque) || r.planos[b].preco - r.planos[a].preco)
    alvo.innerHTML = ordem.map((k) => {
      const p = r.planos[k]
      const avulso = p.preco === 0
      return `<div class="plano ${p.destaque ? 'destaque' : ''}">
        ${p.destaque ? '<span class="tag">Mais escolhido</span>' : ''}
        <h3>${p.nome}</h3>
        <p class="preco">${brl(avulso ? p.extra : p.preco)}</p>
        <p class="pequeno">${avulso ? 'por laudo' : 'por mês'}</p>
        <p>✓ ${avulso ? 'Sem mensalidade' : `${p.incluidos} laudos incluídos`}</p>
        <a class="${p.destaque ? 'btn' : 'btn2'}" href="${APP}">Começar</a>
      </div>`
    }).join('')
    const extra = document.getElementById('nota-extra')
    const comp = document.getElementById('nota-comparacao')
    const prof = Object.values(r.planos).find((p) => p.destaque)
    if (extra && prof) extra.innerHTML = `<b>Laudo extra:</b> ${brl(prof.extra)}`
    if (comp && prof) comp.innerHTML = `${prof.incluidos} laudos avulsos = ${brl(r.comparacao_avulso_10)} · no ${prof.nome}, <b style="color:#0e6b33">${brl(prof.preco)}</b>`
  } catch {
    alvo.innerHTML = '<p class="sub">Não foi possível carregar os planos agora.</p>'
  }
}
void planos()
