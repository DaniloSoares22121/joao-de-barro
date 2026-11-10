import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronRight, Copy, Plus, Search } from 'lucide-react'
import { filtrarJobs, prefillDe, statusPresentes } from './campo'
import { ApiError, get } from './api'
import { Esqueleto, Logo } from './Marca'
import StatusBadge from './StatusBadge'
import {
  STATUS_BLOQUEADO, STATUS_PARCIAL, STATUS_PRONTO, dataHoraBR, ehFinal, etapaRotulo, modalidade, statusInfo,
} from './rotulos'
import { useStore } from './store'
import type { JobResumo } from './tipos'

const ATUALIZA_MS = 10_000

/** Contadores do topo: quantos trabalhos em cada situação. */
function Resumo({ jobs }: { jobs: JobResumo[] }) {
  const conta = (f: (j: JobResumo) => boolean) => jobs.filter(f).length
  const itens = [
    { rotulo: 'Em andamento', n: conta((j) => !ehFinal(j.status)), cor: 'text-sky-700' },
    { rotulo: 'Prontos para revisão', n: conta((j) => j.status === STATUS_PRONTO), cor: 'text-emerald-700' },
    { rotulo: 'Com pendências', n: conta((j) => j.status === STATUS_PARCIAL || j.status === STATUS_BLOQUEADO), cor: 'text-amber-700' },
    { rotulo: 'Total', n: jobs.length, cor: 'text-stone-900' },
  ]
  return (
    <dl className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
      {itens.map((i) => (
        <div key={i.rotulo} className="cartao px-4 py-3">
          <dt className="text-xs text-stone-500">{i.rotulo}</dt>
          <dd className={`mt-0.5 text-2xl font-semibold tabular-nums ${i.cor}`}>{i.n}</dd>
        </div>
      ))}
    </dl>
  )
}

export default function Lista() {
  const ir = useStore((s) => s.ir)
  const novoAPartir = useStore((s) => s.novoAPartir)
  const [busca, setBusca] = useState('')
  const [filtro, setFiltro] = useState('')
  const [jobs, setJobs] = useState<JobResumo[] | null>(null)
  const [erro, setErro] = useState('')

  const carregar = useCallback(async () => {
    try {
      const r = await get<JobResumo[]>('/jobs')
      setJobs([...r].sort((a, b) => b.numero - a.numero))
      setErro('')
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return
      setErro('Não foi possível carregar os trabalhos.')
    }
  }, [])

  useEffect(() => { void carregar() }, [carregar])

  // Atualiza sozinho enquanto houver trabalho em andamento (e ao voltar para a aba).
  const emAndamento = !!jobs?.some((j) => !ehFinal(j.status))
  useEffect(() => {
    if (!emAndamento) return
    const t = setInterval(() => { if (document.visibilityState !== 'hidden') void carregar() }, ATUALIZA_MS)
    return () => clearInterval(t)
  }, [emAndamento, carregar])
  useEffect(() => {
    const aoVoltar = () => { if (document.visibilityState === 'visible') void carregar() }
    document.addEventListener('visibilitychange', aoVoltar)
    return () => document.removeEventListener('visibilitychange', aoVoltar)
  }, [carregar])

  const visiveis = useMemo(() => (jobs ? filtrarJobs(jobs, busca, filtro) : []), [jobs, busca, filtro])
  const chips = useMemo(() => (jobs ? statusPresentes(jobs) : []), [jobs])
  // O filtro escolhido pode deixar de existir quando o trabalho muda de status.
  useEffect(() => { if (filtro && !chips.includes(filtro)) setFiltro('') }, [filtro, chips])
  const copiar = (j: JobResumo) => novoAPartir(prefillDe(j as unknown as Record<string, unknown>))

  return (
    <section>
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h1 className="titulo-pag">Trabalhos</h1>
          <p className="text-sm text-stone-500">Avaliações em andamento e concluídas.</p>
        </div>
        <button className="btn shrink-0" onClick={() => ir('novo')}>
          <Plus size={16} aria-hidden="true" /> Novo trabalho
        </button>
      </div>

      {erro && (
        <div className="faixa-erro mb-4 flex items-center justify-between gap-3" role="alert">
          <span>{erro}</span>
          <button className="btn-sec btn-peq" onClick={() => void carregar()}>Tentar de novo</button>
        </div>
      )}

      {jobs === null && !erro && <Esqueleto linhas={4} rotulo="Carregando os trabalhos…" />}

      {jobs !== null && jobs.length === 0 && (
        <div className="cartao-pad py-12 text-center">
          <div className="mb-3 flex justify-center"><Logo size={48} /></div>
          <p className="text-base font-semibold text-stone-900">Nenhum trabalho ainda</p>
          <p className="mx-auto mt-1 max-w-sm text-sm text-stone-500">
            Crie o primeiro trabalho: informe os dados do imóvel, envie os documentos e o João de Barro monta o laudo.
          </p>
          <button className="btn mt-4" onClick={() => ir('novo')}><Plus size={16} aria-hidden="true" /> Novo trabalho</button>
        </div>
      )}

      {jobs !== null && jobs.length > 0 && (
        <>
          <Resumo jobs={jobs} />
          <div className="mb-3 space-y-2">
            <label htmlFor="busca" className="sr-only">Buscar trabalhos</label>
            <div className="relative">
              <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400" aria-hidden="true" />
              <input id="busca" type="search" className="input pl-9" placeholder="Buscar por nº, cliente ou bairro"
                     value={busca} onChange={(e) => setBusca(e.target.value)} autoComplete="off" />
            </div>
            {chips.length > 1 && (
              <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrar por status">
                {['', ...chips].map((st) => (
                  <button key={st || 'todos'} type="button" aria-pressed={filtro === st}
                          onClick={() => setFiltro(st)}
                          className={`toque foco rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                            filtro === st ? 'border-barro bg-barro-claro text-barro' : 'border-stone-300 bg-white text-stone-600 hover:border-stone-400'}`}>
                    {st ? statusInfo(st).texto : 'Todos'}
                    <span className="ml-1.5 tabular-nums opacity-70">
                      {st ? jobs.filter((j) => j.status === st).length : jobs.length}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
          {visiveis.length === 0 && (
            <div className="cartao-pad py-8 text-center text-sm text-stone-500" role="status">
              Nenhum trabalho encontrado.{' '}
              <button type="button" className="btn-link" onClick={() => { setBusca(''); setFiltro('') }}>Limpar a busca</button>
            </div>
          )}
          {/* Telas largas: tabela */}
          {visiveis.length > 0 && (
            <div className="cartao hidden overflow-hidden md:block">
              <table className="tabela">
                <thead>
                  <tr>
                    <th>Nº</th><th>Solicitante</th><th>Imóvel</th><th>Modalidade</th><th>Status</th><th>Etapa atual</th><th>Atualizado</th><th><span className="sr-only">Ações</span></th>
                  </tr>
                </thead>
                <tbody>
                  {visiveis.map((j) => (
                    <tr key={j.id} tabIndex={0} role="link"
                        aria-label={`Abrir trabalho ${j.numero}`}
                        onClick={() => ir('job', j.id)}
                        onKeyDown={(e) => { if (e.key === 'Enter') ir('job', j.id) }}
                        className="cursor-pointer transition-colors hover:bg-stone-50 focus-visible:bg-barro-claro focus-visible:outline-none">
                      <td className="font-semibold tabular-nums text-stone-900">{j.numero}</td>
                      <td className="font-medium text-stone-900">{j.cliente || '—'}</td>
                      <td>
                        <div>{j.tipo || '—'}</div>
                        <div className="text-xs text-stone-500">{[j.bairro, j.cidade].filter(Boolean).join(' · ')}</div>
                      </td>
                      <td className="whitespace-nowrap text-stone-600">{modalidade(j.modalidade)}</td>
                      <td><StatusBadge status={j.status} /></td>
                      <td className="text-stone-600">{ehFinal(j.status) ? '—' : etapaRotulo(j.etapa)}</td>
                      <td className="whitespace-nowrap text-xs text-stone-500">{dataHoraBR(j.atualizado)}</td>
                      <td>
                        <button type="button" className="btn-link inline-flex items-center gap-1 whitespace-nowrap text-xs"
                                onClick={(e) => { e.stopPropagation(); copiar(j) }}
                                onKeyDown={(e) => e.stopPropagation()}
                                aria-label={`Novo trabalho a partir do nº ${j.numero}`}
                                title="Cria um trabalho novo já com solicitante, tipo, bairro e modalidade deste">
                          <Copy size={13} aria-hidden="true" /> Novo a partir deste
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Celular: cartões */}
          <ul className="space-y-3 md:hidden">
            {visiveis.map((j) => (
              <li key={j.id}>
                <button onClick={() => ir('job', j.id)}
                        className="cartao-pad foco relative block w-full pr-9 text-left transition-colors hover:bg-stone-50">
                  <ChevronRight size={18} className="absolute right-3 top-1/2 -translate-y-1/2 text-stone-300" aria-hidden="true" />
                  <span className="block text-base font-semibold text-stone-900">
                    Nº {j.numero} <span className="font-normal text-stone-600">· {j.cliente || '—'}</span>
                  </span>
                  <span className="mt-0.5 block text-sm text-stone-600">
                    {j.tipo || '—'}{j.bairro ? ` · ${j.bairro}` : ''}{j.cidade ? ` · ${j.cidade}` : ''}
                  </span>
                  <span className="mt-2 flex flex-wrap items-center gap-2">
                    <StatusBadge status={j.status} />
                    <span className="text-xs text-stone-500">{modalidade(j.modalidade)}</span>
                  </span>
                  <span className="mt-2 block text-xs text-stone-500">
                    {ehFinal(j.status) ? `Atualizado em ${dataHoraBR(j.atualizado)}` : `Etapa: ${etapaRotulo(j.etapa)}`}
                  </span>
                </button>
                <button type="button" className="btn-link toque mt-1 inline-flex items-center gap-1 text-sm"
                        onClick={() => copiar(j)} aria-label={`Novo trabalho a partir do nº ${j.numero}`}>
                  <Copy size={14} aria-hidden="true" /> Novo a partir deste
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
