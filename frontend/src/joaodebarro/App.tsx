import { useEffect, useState, type ReactNode } from 'react'
import { Bell, ChevronsLeft, ChevronsRight, ClipboardList, LogOut, Plus, Settings, UserRound, Wallet } from 'lucide-react'
import Avisos from './TelaAvisos'
import Config from './Config'
import Conta, { Pagamento } from './Conta'
import Lista, { ehVez } from './Lista'
import Lixeira from './Lixeira'
import Login from './Login'
import NovoSimples from './NovoSimples'
import Propostas from './Propostas'
import { MeuPlano, Planos } from './Planos'
import { ConversaCliente, ListaClientes } from './Clientes'
import Escolha from './Escolha'
import Laudo from './Laudo'
import Assinar from './Assinar'
import Guia from './Guia'
import Compartilhar from './Compartilhar'
import { CadastrarAvaliador, MeuCadastro, MinhasRegras } from './Avaliador'
import Trabalho from './Trabalho'
import TabelaPrecos from './TabelaPrecos'
import { ApiError, get } from './api'
import { Logo, Marca } from './Marca'
import { plural } from './rotulos'
import { useStore, type Tela } from './store'
import type { JobResumo } from './tipos'
import { token } from './token'

function sairDaConta() {
  token.limpar()
  useStore.getState().sair()
}

function AcessoRestrito() {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="cartao-pad w-full max-w-sm space-y-4 text-center">
        <div className="flex justify-center"><Logo size={56} /></div>
        <div>
          <h1 className="text-lg font-semibold text-stone-900">Acesso restrito ao avaliador</h1>
          <p className="mt-1 text-sm text-stone-500">Esta conta não tem permissão para usar o JdB.</p>
        </div>
        <button className="btn w-full" onClick={sairDaConta}>Entrar com outra conta</button>
      </div>
    </div>
  )
}

function Carregando() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 p-4" role="status" aria-live="polite">
      <span className="animate-pulse"><Logo size={56} /></span>
      <p className="text-sm text-stone-500">Carregando…</p>
    </div>
  )
}

/** Sondagem leve enquanto a aba está visível. */
function useSondagem<T>(url: string, ms: number): T | null {
  const [v, setV] = useState<T | null>(null)
  useEffect(() => {
    let vivo = true
    const consultar = () => {
      if (document.visibilityState === 'hidden') return
      get<T>(url)
        .then((r) => { if (vivo) setV(r) })
        .catch((e) => { if (vivo && !(e instanceof ApiError && (e.status === 401 || e.status === 403))) setV(null) })
    }
    consultar()
    const t = setInterval(consultar, ms)
    document.addEventListener('visibilitychange', consultar)
    return () => { vivo = false; clearInterval(t); document.removeEventListener('visibilitychange', consultar) }
  }, [url, ms])
  return v
}


/** 112: o programa do PC (Coletor) hoje só faz o mapa da localização; o menu diz isso em palavras do avaliador. */
function PilulaColetor({ aoIr, recolhido }: { aoIr: () => void; recolhido?: boolean }) {
  const st = useSondagem<{ online: boolean }>('/coletor/status', 20_000)
  if (st === null) return null
  const online = !!st.online
  return (
    <button type="button" onClick={aoIr} data-dica={recolhido ? `Mapa ${online ? 'pronto' : 'desligado'}` : undefined}
            title={online ? 'O programa do PC que faz o mapa da localização está ligado'
              : 'O programa do PC que faz o mapa da localização está desligado: o mapa não é refeito até ligar'}
            className="lateral-item foco w-full">
      <span className={`ml-1 h-2 w-2 shrink-0 rounded-full ${online ? 'bg-emerald-400 ring-4 ring-emerald-400/20' : 'bg-amber-400 ring-4 ring-amber-400/20'}`} aria-hidden="true" />
      <span className="flex-1 text-left rotulo-menu">Mapa</span>
      <span className={`text-xs ${online ? 'text-emerald-300' : 'text-amber-300'}`}>{online ? 'pronto' : 'desligado'}</span>
    </button>
  )
}

/** 079-2: a extensão do Chrome é outra peça, com o seu estado (o "Coletor ligado" não diz nada sobre ela). */
function PilulaExtensao({ aoIr, recolhido }: { aoIr: () => void; recolhido?: boolean }) {
  const st = useSondagem<{ instalada: boolean; atualizar: boolean; portais: boolean | null; vista?: string; atual?: string }>('/extensao/estado', 30_000)
  if (st === null) return null
  const ok = st.instalada && !st.atualizar && st.portais !== false
  // 103-1: mostra a versão — "1.2.2 — há a 1.2.3: toque em ↻" (o Capitão achou que já tinha atualizado)
  const txt = !st.instalada ? 'falta ligar'
    : st.atualizar ? (st.vista && st.atual ? `${st.vista} — há a ${st.atual}: toque em ↻` : 'atualizar: toque em ↻')
    : st.portais === false ? 'permitir portais' : (st.vista ? `ligada (${st.vista})` : 'ligada')
  return (
    <button type="button" onClick={aoIr} data-dica={recolhido ? `Extensão: ${txt}` : undefined}
            title={ok ? 'A extensão do JdB está ligada neste Chrome' : 'A extensão do JdB precisa de atenção: toque para ver'}
            className="lateral-item foco w-full">
      <span className={`ml-1 h-2 w-2 shrink-0 rounded-full ${ok ? 'bg-emerald-400 ring-4 ring-emerald-400/20' : 'bg-amber-400 ring-4 ring-amber-400/20'}`} aria-hidden="true" />
      <span className="flex-1 text-left rotulo-menu">Extensão</span>
      <span className={`text-xs ${ok ? 'text-emerald-300' : 'text-amber-300'}`}>{txt}</span>
    </button>
  )
}


/** Menu lateral (computador); no celular vira o menu inferior (ORDEM 023-B). */
function MenuLateral({ tela, aoNavegar, recolhido = false, alternar }: {
  tela: Tela; aoNavegar: () => void; recolhido?: boolean; alternar?: () => void
}) {
  const ir = useStore((s) => s.ir)
  const jobs = useSondagem<JobResumo[]>('/jobs', 30_000)
  // ORDEM 070-B4: o mesmo número do título da lista (trabalhos que esperam você + clientes ainda sem trabalho)
  const clis = useSondagem<{ clientes: { job_id: string }[] }>('/clientes', 30_000)
  const pedem = (jobs?.filter((j) => ehVez(j.proximo)).length ?? 0) + (clis?.clientes.filter((c) => !c.job_id).length ?? 0)
  const vai = (t: Tela) => { ir(t); aoNavegar() }
  const eu = useSondagem<{ id: string; dados?: Record<string, unknown> }>('/avaliadores/eu', 300_000)   // ORDEM 042: menu do curador só para o Alan
  const item = (alvo: Tela, rotulo: string, ativo: boolean, icone: ReactNode, extra?: ReactNode) => (
    <button type="button" onClick={() => vai(alvo)} aria-current={ativo ? 'page' : undefined}
            aria-label={recolhido ? rotulo : undefined} data-dica={recolhido ? rotulo : undefined}
            className={`lateral-item foco w-full ${ativo ? 'lateral-ativo' : ''}`}>
      <span className="nav-icone">{icone}</span><span className="flex-1 text-left rotulo-menu">{rotulo}</span>{extra}
    </button>
  )
  const nome = String((eu?.dados?.nome as string) || '')
  const iniciais = nome.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join('')
  return (
    <div className={`flex h-full flex-col overflow-y-auto${recolhido ? ' menu-recolhido' : ''}`}>
      <div className="lateral-marca px-4 pb-3 pt-4">
        <button type="button" className="foco rounded-xl text-left" onClick={() => vai('lista')} aria-label="JdB Laudo — início"
                data-dica={recolhido ? 'Início' : undefined}>
          {recolhido ? <Logo size={52} escuro /> : <Marca claro />}
        </button>
      </div>
      <div className="px-4 pt-6">
        <button type="button" className="btn w-full" onClick={() => vai('novo')} aria-label={recolhido ? 'Novo trabalho' : undefined}
                data-dica={recolhido ? 'Novo trabalho' : undefined}>
          <Plus size={recolhido ? 20 : 16} aria-hidden="true" /><span className="rotulo-menu"> Novo trabalho</span>
        </button>
      </div>
      <nav className="mt-6 space-y-1 px-3" aria-label="Principal">
        {/* ORDEM 053 (desenho): Trabalhos · Avisos · Meu plano · Configurações */}
        {item('lista', 'Trabalhos', tela === 'lista' || tela === 'job' || tela === 'detalhes', <ClipboardList size={18} aria-hidden="true" />,
          pedem > 0 ? (
            <span className="contador-menu rounded-full bg-white px-2 py-0.5 text-[16px] font-bold tabular-nums text-[var(--navy)]"
                  title={`${plural(pedem, 'trabalho esperando', 'trabalhos esperando')} você`}>{pedem}</span>
          ) : undefined)}
        {item('avisos', 'Avisos', tela === 'avisos', <Bell size={18} aria-hidden="true" />)}
        {item('plano', 'Meu plano', tela === 'plano' || tela === 'planos', <Wallet size={18} aria-hidden="true" />)}
        {item('config', 'Configurações', ['config', 'sistema', 'pagamento', 'cadastro', 'regras', 'avaliadores', 'marca', 'precos', 'lixeira'].includes(tela), <Settings size={18} aria-hidden="true" />)}
        {/* ORDEM 053 (L20): Minhas regras, Meu cadastro e Avaliadores ficam dentro de Configurações */}
      </nav>
      <div className="mt-auto space-y-1 border-t border-white/10 px-3 py-4">
        <PilulaColetor aoIr={() => vai('sistema')} recolhido={recolhido} />
        <PilulaExtensao aoIr={() => vai('sistema')} recolhido={recolhido} />
        {nome && (
          <div className="lateral-item" aria-label={`Conectado como ${nome}`} data-dica={recolhido ? nome : undefined} tabIndex={recolhido ? 0 : undefined}>
            <span className="avatar-jdb" aria-hidden="true">{iniciais}</span><span className="flex-1 text-left rotulo-menu">{nome}</span>
          </div>
        )}
        {/* ORDEM 070-A: recolher e expandir com um clique (lembra neste aparelho) */}
        {alternar && (
          <button type="button" className="lateral-item foco w-full" onClick={alternar} aria-expanded={!recolhido}
                  aria-label={recolhido ? 'Abrir menu' : 'Recolher menu'} data-dica={recolhido ? 'Abrir menu' : undefined}>
            {recolhido ? <ChevronsRight size={18} aria-hidden="true" /> : <ChevronsLeft size={18} aria-hidden="true" />}
            <span className="flex-1 text-left rotulo-menu">Recolher</span>
          </button>
        )}
        <button type="button" className="lateral-item foco w-full" onClick={sairDaConta} aria-label={recolhido ? 'Sair' : undefined}
                data-dica={recolhido ? 'Sair' : undefined}>
          <LogOut size={18} aria-hidden="true" /><span className="flex-1 text-left rotulo-menu">Sair</span>
        </button>
      </div>
    </div>
  )
}

/** Celular: menu inferior do desenho (Trabalhos · Novo · Avisos · Conta). Sair fica em Conta. */
function MenuInferior({ tela }: { tela: Tela }) {
  const ir = useStore((s) => s.ir)
  const jobs = useSondagem<JobResumo[]>('/jobs', 30_000)
  // o mesmo número do menu lateral e do título da lista (070-B4): trabalhos que esperam você + clientes sem trabalho
  const clis = useSondagem<{ clientes: { job_id: string }[] }>('/clientes', 30_000)
  const pedem = (jobs?.filter((j) => ehVez(j.proximo)).length ?? 0) + (clis?.clientes.filter((c) => !c.job_id).length ?? 0)
  const item = (rotulo: string, icone: ReactNode, ativo: boolean, acao: () => void, extra?: ReactNode, mais = false) => (
    <button type="button" onClick={acao} aria-current={ativo ? 'page' : undefined}
            className={`foco relative flex min-h-[56px] min-w-0 flex-1 flex-col items-center justify-center gap-1 px-1 text-center text-[16px] font-bold leading-tight ${mais ? 'tab-mais' : ''}`}>
      <span className="tab-icone">{icone}</span>{rotulo}{extra}
    </button>
  )
  return (
    <nav className="menu-inferior fixed inset-x-0 bottom-0 z-30 flex lg:hidden" aria-label="Menu">
      {item('Trabalhos', <ClipboardList size={20} aria-hidden="true" />, tela === 'lista' || tela === 'job' || tela === 'detalhes', () => ir('lista'),
        pedem > 0 ? <span className="absolute right-[calc(50%-26px)] top-0 rounded-full bg-[var(--amarelo)] px-1.5 text-[16px] font-bold text-[var(--navy)]">{pedem}</span> : undefined)}
      {item('Novo', <Plus size={22} aria-hidden="true" />, tela === 'novo', () => ir('novo'), undefined, true)}
      {item('Avisos', <Bell size={20} aria-hidden="true" />, tela === 'avisos', () => ir('avisos'))}
      {item('Conta', <UserRound size={20} aria-hidden="true" />, ['config', 'sistema', 'pagamento', 'cadastro', 'regras', 'avaliadores', 'plano', 'planos', 'marca', 'precos', 'lixeira'].includes(tela), () => ir('config'))}
    </nav>
  )
}

export default function App() {
  const tk = useStore((s) => s.token)
  const tela = useStore((s) => s.tela)
  const jobId = useStore((s) => s.jobId)
  const negado = useStore((s) => s.negado)

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
  const [recolhido, setRecolhido] = useState(() => { try { return localStorage.getItem('jdb-menu-recolhido') === '1' } catch { return false } })
  const alternarMenu = () => setRecolhido((r) => {
    try { localStorage.setItem('jdb-menu-recolhido', r ? '0' : '1') } catch { /* sem armazenamento: vale só nesta visita */ }
    return !r
  })

  if (!tk || tela === 'login') return <Login />
  if (negado) return <AcessoRestrito />
  if (!sondado) return <Carregando />

  return (
    <div className={`min-h-screen ${recolhido ? 'lg:pl-[84px]' : 'lg:pl-64'}`}>
      <a href="#conteudo" className="btn sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50">
        Ir para o conteúdo
      </a>
      {/* Computador: menu fixo à esquerda */}
      <aside className={`lateral fixed inset-y-0 left-0 z-30 hidden lg:block ${recolhido ? 'w-[84px]' : 'w-64'}`}>
        <MenuLateral tela={tela} aoNavegar={() => undefined} recolhido={recolhido} alternar={alternarMenu} />
      </aside>
      {/* Celular/tablet: barra azul-marinho com a linha amarela + menu inferior */}
      <header className="topo-celular sticky top-0 z-20 flex h-16 items-center justify-between gap-3 px-4 lg:hidden">
        <Marca largura={130} />
        <button type="button" onClick={() => useStore.getState().ir('avisos')} aria-label="Avisos"
                className="foco inline-flex h-12 w-12 items-center justify-center text-[var(--aco)]"><Bell size={26} aria-hidden="true" /></button>
      </header>
      <MenuInferior tela={tela} />
      <main id="conteudo" className="mx-auto max-w-6xl px-4 pb-24 pt-6 sm:px-6 sm:pt-8 lg:px-10 lg:pb-8">
        <div key={`${tela === 'detalhes' ? 'job' : tela}:${jobId ?? ''}`} className="entra">
          {tela === 'lista' && <Lista />}
          {tela === 'novo' && <NovoSimples />}
          {(tela === 'job' || tela === 'detalhes') && <Trabalho />}
          {tela === 'config' && <Conta />}
          {tela === 'lixeira' && <Lixeira />}
          {tela === 'sistema' && <Config />}
          {tela === 'pagamento' && <Pagamento />}
          {tela === 'propostas' && <Propostas />}
          {tela === 'plano' && <MeuPlano />}
          {tela === 'planos' && <Planos />}
          {tela === 'clientes' && <ListaClientes />}
          {tela === 'cliente' && <ConversaCliente />}
          {tela === 'alinhamento' && <Escolha />}
          {tela === 'cadastro' && <MeuCadastro />}
          {tela === 'marca' && <MeuCadastro parte="marca" />}
          {tela === 'precos' && <TabelaPrecos />}
          {tela === 'avaliadores' && <CadastrarAvaliador />}
          {tela === 'regras' && <MinhasRegras />}
          {tela === 'avisos' && <Avisos />}
          {tela === 'laudo' && <Laudo />}
          {tela === 'assinar' && <Assinar />}
          {tela === 'guia' && <Guia />}
          {tela === 'compartilhar' && <Compartilhar />}
        </div>
      </main>
    </div>
  )
}
