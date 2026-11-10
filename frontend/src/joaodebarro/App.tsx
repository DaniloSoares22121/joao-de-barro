import { useEffect, useState, type ReactNode } from 'react'
import { ClipboardList, LogOut, Settings } from 'lucide-react'
import Config from './Config'
import Lista from './Lista'
import Login from './Login'
import NovoTrabalho from './NovoTrabalho'
import Trabalho from './Trabalho'
import { ApiError, get } from './api'
import { Logo, Marca } from './Marca'
import { useStore, type Tela } from './store'
import { token } from './token'

function sairDaConta() {
  token.limpar()
  useStore.getState().sair()
}

function AcessoRestrito() {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="cartao-pad w-full max-w-sm space-y-4 text-center">
        <div className="flex justify-center"><Logo size={44} /></div>
        <div>
          <h1 className="text-lg font-semibold text-stone-900">Acesso restrito ao avaliador</h1>
          <p className="mt-1 text-sm text-stone-500">Esta conta não tem permissão para usar o João de Barro.</p>
        </div>
        <button className="btn w-full" onClick={sairDaConta}>Entrar com outra conta</button>
      </div>
    </div>
  )
}

function Carregando() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 p-4" role="status" aria-live="polite">
      <span className="animate-pulse"><Logo size={44} /></span>
      <p className="text-sm text-stone-500">Carregando…</p>
    </div>
  )
}

/** Estado do Coletor no cabeçalho: a pesquisa de referenciais depende dele. */
function PilulaColetor() {
  const ir = useStore((s) => s.ir)
  const [online, setOnline] = useState<boolean | null>(null)
  useEffect(() => {
    let vivo = true
    const consultar = () => {
      if (document.visibilityState === 'hidden') return
      get<{ online: boolean }>('/coletor/status')
        .then((r) => { if (vivo) setOnline(!!r.online) })
        .catch((e) => { if (vivo && !(e instanceof ApiError && (e.status === 401 || e.status === 403))) setOnline(null) })
    }
    consultar()
    const t = setInterval(consultar, 20_000)
    document.addEventListener('visibilitychange', consultar)
    return () => { vivo = false; clearInterval(t); document.removeEventListener('visibilitychange', consultar) }
  }, [])
  if (online === null) return null
  return (
    <button type="button" onClick={() => ir('config')}
            title={online ? 'O Coletor está conectado' : 'O Coletor está desligado: a pesquisa de referenciais fica esperando'}
            className={`foco inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
              online ? 'bg-emerald-50 text-emerald-800 ring-emerald-600/20' : 'bg-amber-50 text-amber-900 ring-amber-600/25'}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${online ? 'bg-emerald-500' : 'bg-amber-500'}`} aria-hidden="true" />
      Coletor {online ? 'online' : 'offline'}
    </button>
  )
}

function Navegacao({ tela }: { tela: Tela }) {
  const ir = useStore((s) => s.ir)
  const item = (alvo: Tela, rotulo: string, ativo: boolean, icone: ReactNode) => (
    <button
      onClick={() => ir(alvo)}
      aria-current={ativo ? 'page' : undefined}
      className={`foco inline-flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors sm:flex-none ${
        ativo ? 'bg-barro-claro text-barro' : 'text-stone-600 hover:bg-stone-100 hover:text-stone-900'}`}
    >
      {icone}{rotulo}
    </button>
  )
  return (
    <nav className="flex items-center gap-1" aria-label="Principal">
      {item('lista', 'Trabalhos', tela === 'lista' || tela === 'novo' || tela === 'job', <ClipboardList size={16} aria-hidden="true" />)}
      {item('config', 'Configurações', tela === 'config', <Settings size={16} aria-hidden="true" />)}
    </nav>
  )
}

export default function App() {
  const tk = useStore((s) => s.token)
  const tela = useStore((s) => s.tela)
  const jobId = useStore((s) => s.jobId)
  const negado = useStore((s) => s.negado)
  const ir = useStore((s) => s.ir)

  // Valida a sessão (e o acesso de avaliador) assim que há token; 401/403 tratados no api.ts.
  // Até a primeira sondagem terminar, mostra um estado neutro (sem piscar a lista antes do 403).
  const [sondado, setSondado] = useState(false)
  useEffect(() => {
    if (!tk) { setSondado(false); return }
    let vivo = true
    get('/proximo-numero').catch(() => undefined).finally(() => { if (vivo) setSondado(true) })
    return () => { vivo = false }
  }, [tk])

  // Cada tela começa no topo (no celular a anterior podia estar rolada até o fim).
  useEffect(() => { window.scrollTo(0, 0) }, [tela, jobId])

  if (!tk || tela === 'login') return <Login />
  if (negado) return <AcessoRestrito />
  if (!sondado) return <Carregando />

  return (
    <div className="min-h-screen">
      <a href="#conteudo" className="btn sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50">
        Ir para o conteúdo
      </a>
      <header className="sticky top-0 z-20 border-b border-stone-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-2.5">
          <button type="button" className="foco shrink-0 rounded-lg" onClick={() => ir('lista')} aria-label="João de Barro — início">
            <Marca />
          </button>
          <div className="order-last w-full sm:order-none sm:w-auto sm:flex-1">
            <Navegacao tela={tela} />
          </div>
          <div className="ml-auto flex items-center gap-1 sm:ml-0">
            <PilulaColetor />
            <button className="btn-link inline-flex shrink-0 items-center gap-1.5 !text-stone-600" onClick={sairDaConta}>
              <LogOut size={15} aria-hidden="true" /> Sair
            </button>
          </div>
        </div>
      </header>
      <main id="conteudo" className="mx-auto max-w-6xl px-4 py-5 sm:py-8">
        <div key={`${tela}:${jobId ?? ''}`} className="entra">
          {tela === 'lista' && <Lista />}
          {tela === 'novo' && <NovoTrabalho />}
          {tela === 'job' && <Trabalho />}
          {tela === 'config' && <Config />}
        </div>
      </main>
    </div>
  )
}
