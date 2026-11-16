import { create } from 'zustand'
import { hashDe, lerHash, type Prefill } from './campo'
import { token } from './token'

export type Tela = 'login' | 'lista' | 'novo' | 'job' | 'config' | 'propostas' | 'plano' | 'planos' | 'clientes' | 'cliente' | 'alinhamento' | 'cadastro' | 'avaliadores' | 'regras' | 'avisos' | 'laudo' | 'assinar' | 'sistema' | 'pagamento' | 'guia' | 'compartilhar' | 'detalhes' | 'lixeira' | 'precos' | 'marca'

interface Estado {
  token: string
  tela: Tela
  jobId: string | null
  /** Campos pré-preenchidos do "Novo a partir deste" (consumidos pela tela Novo). */
  prefill: Prefill | null
  /** true quando a API respondeu 403 (conta sem acesso ao avaliador). */
  negado: boolean
  ir: (tela: Tela, jobId?: string) => void
  novoAPartir: (p: Prefill) => void
  entrar: (token: string) => void
  sair: () => void
  negar: () => void
}

const temJanela = typeof window !== 'undefined'

/** Rotas só por hash ("#/", "#/novo", "#/job/<id>", "#/config"). Um caminho ".../configuracoes"
 * (link direto) vira caminho base + "#/config"; hashes fora do padrão são reescritos sem nova entrada. */
function normalizarUrl() {
  if (!temJanela) return
  const { pathname, search, hash } = window.location
  const m = /^(.*\/)configuracoes\/?$/.exec(pathname)
  if (m) {
    window.history.replaceState(window.history.state, '', `${m[1]}${search}#/config`)
    return
  }
  const r = lerHash(hash)
  const canon = hashDe(r.tela, r.jobId)
  if (hash && hash !== canon && !(canon === '#/' && hash === '#')) {
    window.history.replaceState(window.history.state, '', `${pathname}${search}${canon}`)
  }
}
normalizarUrl()

const t0 = token.get()
const r0 = lerHash(temJanela ? window.location.hash : '')

/** Leva a tela para location.hash (nova entrada no histórico: o voltar do celular funciona). */
function sincronizarHash(tela: Tela, jobId: string | null) {
  if (!temJanela || tela === 'login') return
  const h = hashDe(tela, jobId)
  if (window.location.hash !== h && !(h === '#/' && window.location.hash === '')) window.location.hash = h
}

export const useStore = create<Estado>((set, get) => ({
  token: t0,
  tela: t0 ? r0.tela : 'login',
  jobId: r0.jobId,
  prefill: null,
  negado: false,
  ir: (tela, jobId) => {
    const id = jobId ?? (['job', 'detalhes', 'cliente', 'alinhamento'].includes(tela) ? get().jobId : null)
    set({ tela, jobId: id, prefill: null })
    sincronizarHash(tela, id)
  },
  novoAPartir: (p) => {
    set({ tela: 'novo', jobId: null, prefill: p })
    sincronizarHash('novo', null)
  },
  entrar: (token) => {
    const r = lerHash(temJanela ? window.location.hash : '')
    set({ token, tela: r.tela, jobId: r.jobId, negado: false })
  },
  sair: () => set({ token: '', tela: 'login', jobId: null, negado: false }),
  negar: () => set({ negado: true }),
}))

// Voltar/avançar do navegador e links com hash: o hash manda na tela.
if (temJanela) {
  window.addEventListener('hashchange', () => {
    normalizarUrl()
    const s = useStore.getState()
    if (!s.token) return
    const r = lerHash(window.location.hash)
    if (r.tela !== s.tela || r.jobId !== s.jobId) {
      useStore.setState({ tela: r.tela, jobId: r.jobId, ...(r.tela === 'novo' ? {} : { prefill: null }) })
    }
  })
}
