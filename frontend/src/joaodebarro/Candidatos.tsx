/* "Candidatos a referencial": a lista montada pela pesquisa. O avaliador marca "Entra no laudo" /
 * "Descartar", pede mais anúncios (com orientação) e continua com os escolhidos (≥ 5). */
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { Download, Loader2, Search, Star } from 'lucide-react'
import { ApiError, baixarRaw, post, put } from './api'
import { unitario } from './calculo'
import { ehAuth, mensagemErro } from './Envio'
import {
  MIN_ESCOLHIDOS, decisaoDe, dominio, entraNoLaudo, ordenarCandidatos, rotuloBuscar, totalEntra,
} from './listaCandidatos'
import { AdicionarReferencial, RemoverReferencial, ehManual } from './Referenciais'
import { aguardandoEscolha, emExecucao, moeda, msgSegura, numero2, textoTela } from './rotulos'
import type { DecisaoCandidato, Detalhe, Evento, Referencial, RespostaDecisao } from './tipos'

const POLL_BUSCA_MS = 5000
const LIMITE_BUSCA_MS = 3 * 60 * 1000

/** Busca em andamento por trabalho (sobrevive à troca de lugar do painel na tela). */
const buscas = new Map<string, { desde: number; qtd: number; evId: number }>()

function erroTxt(e: unknown): string {
  if (e instanceof ApiError && e.status === 409) return 'O trabalho está em execução; aguarde terminar.'
  const m = e instanceof ApiError ? e.detail : mensagemErro(e)
  return m.charAt(0).toUpperCase() + m.slice(1)
}

function salvarBlob(blob: Blob, nome: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = nome
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

const ni = (v: string | null) => v ?? <span className="text-stone-400">n/i</span>
const m2 = (v: number | null | undefined) => (v != null ? `${numero2(v)} m²` : null)

function Chip({ classe, children }: { classe: string; children: ReactNode }) {
  return <span className={`chip ${classe}`}>{children}</span>
}

interface Props {
  detalhe: Detalhe
  eventos: Evento[]
  recarregar: () => void
  aoMudar: (msg: string) => void
  /** Pode cadastrar/remover referencial manual (trabalho parado). */
  livre: boolean
}

/** Corpo do painel (tabela + ações). `destaque` é o quadro do topo, quando o trabalho espera a escolha. */
export function ListaCandidatos({ detalhe, eventos, recarregar, aoMudar, livre }: Props) {
  const { job, candidatos } = detalhe
  const jobId = job.id
  const esperando = aguardandoEscolha(job)
  const [local, setLocal] = useState<Record<number, { decisao: DecisaoCandidato; motivo: string }>>({})
  const [descartando, setDescartando] = useState<number | null>(null)
  const [motivo, setMotivo] = useState('')
  const [ocupadoN, setOcupadoN] = useState<number | null>(null)
  const [erroLinha, setErroLinha] = useState<{ n: number; msg: string } | null>(null)
  const [mostrarRiscados, setMostrarRiscados] = useState(true)
  const [orientacao, setOrientacao] = useState('')
  const [busca, setBusca] = useState(() => buscas.get(jobId) ?? null)
  const [erroBusca, setErroBusca] = useState('')
  const [continuando, setContinuando] = useState(false)
  const [erroContinuar, setErroContinuar] = useState('')
  const [erroBaixar, setErroBaixar] = useState('')

  // Dados novos do servidor: descarta o estado otimista.
  useEffect(() => { setLocal({}) }, [candidatos])

  const refs: Referencial[] = candidatos.map((r) => (local[r.n]
    ? { ...r, decisao: local[r.n].decisao, motivo_descarte: local[r.n].motivo } : r))
  const qtd = candidatos.length
  const escolhidos = totalEntra(refs)
  const riscados = refs.filter((r) => r.nao_recomendado).length
  const visiveis = ordenarCandidatos(refs, mostrarRiscados)
  const buscando = busca !== null
  const travado = emExecucao(job) || buscando || continuando

  // Busca em segundo plano: recarrega a cada 5 s até a lista mudar, chegar evento da pesquisa ou dar 3 min.
  const encerrar = useRef(() => { buscas.delete(jobId); setBusca(null) })
  encerrar.current = () => { buscas.delete(jobId); setBusca(null) }
  useEffect(() => {
    if (!busca) return
    const fim = eventos.find((e) => e.id > busca.evId && e.etapa === 'pesquisa'
      && (e.nivel === 'lista' || e.nivel === 'aviso' || e.nivel === 'erro'))
    if (qtd !== busca.qtd || fim) {
      if (fim && fim.nivel !== 'lista' && qtd === busca.qtd) { const m = msgSegura(fim.msg); setErroBusca(m.charAt(0).toUpperCase() + m.slice(1)) }
      encerrar.current()
      recarregar()
    }
  }, [busca, eventos, qtd, recarregar])
  useEffect(() => {
    if (!busca) return
    const t = setInterval(() => {
      if (Date.now() - busca.desde > LIMITE_BUSCA_MS) { encerrar.current(); recarregar(); return }
      recarregar()
    }, POLL_BUSCA_MS)
    return () => clearInterval(t)
  }, [busca, recarregar])

  async function decidir(r: Referencial, decisao: DecisaoCandidato, mot = '') {
    setErroLinha(null)
    setLocal((l) => ({ ...l, [r.n]: { decisao, motivo: mot } }))
    setDescartando(null)
    setOcupadoN(r.n)
    try {
      await put<RespostaDecisao>(`/jobs/${encodeURIComponent(jobId)}/candidatos/${r.n}`,
        decisao === 'descarta' ? { decisao, motivo: mot.trim() } : { decisao })
    } catch (e) {
      setLocal((l) => { const x = { ...l }; delete x[r.n]; return x })
      if (!ehAuth(e)) setErroLinha({ n: r.n, msg: erroTxt(e) })
    } finally {
      setOcupadoN(null)
      recarregar()
    }
  }

  async function pedirMais() {
    setErroBusca('')
    const b = { desde: Date.now(), qtd, evId: eventos.reduce((m, e) => Math.max(m, e.id), 0) }
    try {
      await post(`/jobs/${encodeURIComponent(jobId)}/pesquisa/mais`, orientacao.trim() ? { orientacao: orientacao.trim() } : {})
      buscas.set(jobId, b)
      setBusca(b)
    } catch (e) {
      if (!ehAuth(e)) setErroBusca(erroTxt(e))
    }
  }

  async function continuar() {
    setErroContinuar('')
    setContinuando(true)
    try {
      await post(`/jobs/${encodeURIComponent(jobId)}/pesquisa/continuar`)
      aoMudar(`${escolhidos} referenciais escolhidos. O JdB vai abrir os anúncios e seguir com a seleção.`)
    } catch (e) {
      if (!ehAuth(e)) setErroContinuar(erroTxt(e))
    } finally {
      setContinuando(false)
    }
  }

  async function baixarLista(ext: 'xlsx' | 'md') {
    setErroBaixar('')
    try {
      const { blob, nome } = await baixarRaw(`/jobs/${encodeURIComponent(jobId)}/candidatos.${ext}`)
      salvarBlob(blob, nome || `candidatos-trabalho-${job.numero}.${ext}`)
    } catch (e) {
      if (!ehAuth(e)) setErroBaixar(erroTxt(e))
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className={`text-sm font-semibold tabular-nums ${escolhidos >= MIN_ESCOLHIDOS ? 'text-emerald-700' : 'text-stone-800'}`}
           data-testid="contador-escolhidos" aria-live="polite">
          {escolhidos} escolhido{escolhidos === 1 ? '' : 's'} (mínimo {MIN_ESCOLHIDOS})
        </p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {riscados > 0 && (
            <label className="inline-flex items-center gap-1.5 text-xs text-stone-600" htmlFor="mostrar-riscados">
              <input id="mostrar-riscados" type="checkbox" className="h-4 w-4 accent-[var(--barro)]"
                     checked={mostrarRiscados} onChange={(e) => setMostrarRiscados(e.target.checked)} />
              Mostrar riscados ({riscados})
            </label>
          )}
          {qtd > 0 && (
            <span className="inline-flex items-center gap-1 text-xs">
              <Download size={13} className="text-stone-400" aria-hidden="true" />
              <button type="button" className="btn-link !px-1 text-xs" onClick={() => void baixarLista('xlsx')}>Baixar lista (.xlsx)</button>
              <button type="button" className="btn-link !px-1 text-xs" onClick={() => void baixarLista('md')}>(.md)</button>
            </span>
          )}
          {livre && <AdicionarReferencial jobId={jobId} aoMudar={aoMudar} />}
        </div>
      </div>
      {erroBaixar && <p className="erro-txt" role="alert">{erroBaixar}</p>}

      {qtd === 0 ? (
        <p className="text-sm text-stone-500">
          Nenhum candidato ainda. Toque em “Pesquisar referenciais” para montar a lista{livre ? ' — ou cadastre um anúncio em “Adicionar referencial”' : ''}.
        </p>
      ) : (
        <div className="-mx-4 overflow-x-auto border-y border-stone-100 sm:-mx-5">
          <table className="tabela" data-testid="tabela-candidatos">
            <thead>
              <tr>
                <th scope="col">Nº</th>
                <th scope="col">Anúncio</th>
                <th scope="col">Portal</th>
                <th scope="col">Bairro</th>
                <th scope="col">Tipologia</th>
                <th scope="col">Quartos/suítes</th>
                <th scope="col" className="text-right">Lote</th>
                <th scope="col" className="text-right">Área constr.</th>
                <th scope="col" className="text-right">Preço</th>
                <th scope="col" className="text-right">R$/m²</th>
                <th scope="col">Padrão e idade</th>
                <th scope="col">Observação</th>
                <th scope="col">Decisão</th>
              </tr>
            </thead>
            <tbody>
              {visiveis.map((r) => {
                const dec = decisaoDe(r)
                const entra = entraNoLaudo(r)
                const href = dominio(r.link) ? r.link : null
                const u = unitario(r)
                const risc = r.nao_recomendado ? 'line-through text-stone-400' : ''
                const qs = r.quartos == null && r.suites == null ? null : `${r.quartos ?? '–'} / ${r.suites ?? '–'}`
                const padrao = [r.padrao, r.idade_aparente].filter(Boolean).join(' · ') || null
                const linhaCls = entra ? 'bg-emerald-50/70' : dec === 'descarta' ? 'bg-red-50/50' : undefined
                return (
                  <Fragment key={r.n}>
                    <tr className={linhaCls} data-testid={`candidato-${r.n}`} data-decisao={dec || 'nenhuma'}>
                      <td className={`whitespace-nowrap font-semibold text-stone-900 ${risc}`}>
                        <span className="inline-flex items-center gap-1">
                          {r.recomendado && <Star size={14} className="fill-amber-400 text-amber-500" aria-label="Recomendado" />}
                          {r.n}
                        </span>
                      </td>
                      <td className="min-w-[12rem]">
                        {href ? (
                          <a href={href} target="_blank" rel="noopener noreferrer" data-testid={`link-candidato-${r.n}`}
                             className={`btn-link !px-0 text-xs ${r.nao_recomendado ? 'line-through' : ''}`}>
                            {dominio(r.link)} abrir ↗
                          </a>
                        ) : <span className="text-xs text-stone-400">sem link</span>}
                        {r.titulo && <p className={`mt-0.5 line-clamp-2 text-xs text-stone-600 ${risc}`}>{r.titulo}</p>}
                        {!r.nao_recomendado && r.motivo && (
                          <p className={`mt-0.5 text-xs ${r.recomendado ? 'text-amber-800' : 'text-stone-600'}`}>
                            {r.recomendado ? '★ ' : ''}Por que indico: {textoTela(r.motivo)}</p>
                        )}
                        {r.nao_recomendado && (
                          <p className="mt-0.5 text-xs text-stone-600">Não recomendado: {textoTela(r.motivo) || 'sem motivo informado'}</p>
                        )}
                        <span className="mt-1 flex flex-wrap gap-1">
                          {ehManual(r) && <Chip classe="bg-violet-50 text-violet-800 ring-violet-600/20">Cadastrado por você</Chip>}
                    {r.fonte_coleta === 'avaliador' && <Chip classe="bg-violet-50 text-violet-800 ring-violet-600/20">Enviado por você (Chrome)</Chip>}
                          {r.bloqueado && <Chip classe="bg-amber-50 text-amber-800 ring-amber-600/25">abrir no navegador</Chip>}
                          {(r.rodada ?? 0) > 1 && <Chip classe="bg-stone-50 text-stone-500 ring-stone-400/20">rodada {r.rodada}</Chip>}
                          {r.escolhido && <Chip classe="bg-barro text-white ring-transparent">Na amostra</Chip>}
                        </span>
                      </td>
                      <td className={`whitespace-nowrap ${risc}`}>{ni(r.portal || null)}</td>
                      <td className={risc}>{ni(r.bairro || null)}</td>
                      <td className={risc}>{ni(r.tipologia || null)}</td>
                      <td className={`whitespace-nowrap tabular-nums ${risc}`}>{ni(qs)}</td>
                      <td className={`whitespace-nowrap text-right tabular-nums ${risc}`}>{ni(m2(r.lote_m2))}</td>
                      <td className={`whitespace-nowrap text-right tabular-nums ${risc}`}>{ni(m2(r.area_m2))}</td>
                      <td className={`whitespace-nowrap text-right tabular-nums ${risc}`}>{r.preco != null ? moeda(r.preco) : ni(null)}</td>
                      <td className={`whitespace-nowrap text-right font-medium tabular-nums ${risc}`}>{u !== null ? moeda(u) : ni(null)}</td>
                      <td className={risc}>{ni(padrao)}</td>
                      <td className="min-w-[12rem] text-xs text-stone-600">
                        {textoTela(r.observacao) || (r.justificativa ? null : '—')}
                        {r.justificativa && <span className="block text-stone-500">IA: {textoTela(r.justificativa)}</span>}
                        {dec === 'descarta' && (
                          <span className="block text-red-700">Descartado{r.motivo_descarte ? `: ${r.motivo_descarte}` : ''}</span>
                        )}
                      </td>
                      <td>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <button type="button" aria-pressed={entra} aria-label={`Entra no laudo: candidato ${r.n}`}
                                  disabled={travado || ocupadoN === r.n}
                                  onClick={() => void decidir(r, entra ? '' : 'entra')}
                                  className={`btn-peq whitespace-nowrap ${entra
                                    ? 'btn !bg-emerald-600 hover:!bg-emerald-700' : 'btn-sec'}`}>
                            Entra no laudo
                          </button>
                          <button type="button" aria-pressed={dec === 'descarta'} aria-label={`Descartar: candidato ${r.n}`}
                                  disabled={travado || ocupadoN === r.n}
                                  onClick={() => {
                                    if (dec === 'descarta') void decidir(r, '')
                                    else { setMotivo(''); setDescartando(descartando === r.n ? null : r.n) }
                                  }}
                                  className={`btn-sec btn-peq whitespace-nowrap ${dec === 'descarta'
                                    ? '!border-red-300 !bg-red-50 !text-red-800' : ''}`}>
                            Descartar
                          </button>
                          {livre && ehManual(r) && <RemoverReferencial jobId={jobId} n={r.n} aoMudar={aoMudar} />}
                        </div>
                        {erroLinha?.n === r.n && <p className="mt-1 max-w-[16rem] text-xs text-red-700" role="alert">{erroLinha.msg}</p>}
                      </td>
                    </tr>
                    {descartando === r.n && (
                      <tr className="bg-red-50/40">
                        <td colSpan={13}>
                          <form className="flex flex-wrap items-end gap-2"
                                onSubmit={(e) => { e.preventDefault(); void decidir(r, 'descarta', motivo) }}>
                            <div className="min-w-[14rem] flex-1">
                              <label className="rotulo" htmlFor={`motivo-descarte-${r.n}`}>
                                Motivo do descarte do nº {r.n} (opcional)
                              </label>
                              <input id={`motivo-descarte-${r.n}`} className="input" value={motivo} maxLength={200} autoFocus
                                     placeholder="ex.: área muito maior, outro bairro, anúncio repetido"
                                     onChange={(e) => setMotivo(e.target.value)}
                                     onKeyDown={(e) => { if (e.key === 'Escape') setDescartando(null) }} />
                            </div>
                            <button type="submit" className="btn-sec btn-peq !border-red-300 !text-red-800"
                                    aria-label={`Confirmar descarte: candidato ${r.n}`}>Confirmar descarte</button>
                            <button type="button" className="btn-link btn-peq" onClick={() => setDescartando(null)}>Cancelar</button>
                          </form>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid gap-2 rounded-lg bg-stone-50 px-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <div>
          <label className="rotulo" htmlFor="orientacao-pesquisa">Orientação (opcional)</label>
          <input id="orientacao-pesquisa" className="input" value={orientacao} maxLength={300} disabled={travado}
                 placeholder="ex.: bairros limítrofes, sobrados antigos, 200 a 300 m², mesma rua"
                 onChange={(e) => setOrientacao(e.target.value)}
                 onKeyDown={(e) => { if (e.key === 'Enter' && !travado) { e.preventDefault(); void pedirMais() } }} />
        </div>
        <button type="button" className="btn-sec" disabled={travado} onClick={() => void pedirMais()}>
          {buscando ? <Loader2 size={15} className="animate-spin" aria-hidden="true" /> : <Search size={15} aria-hidden="true" />}
          {rotuloBuscar(qtd)}
        </button>
        {buscando && (
          <p className="text-sm text-sky-800 sm:col-span-2" role="status" data-testid="buscando-candidatos">
            Buscando nos portais… (pode levar alguns minutos)
          </p>
        )}
        {erroBusca && <p className="erro-txt sm:col-span-2" role="alert" data-testid="erro-busca">{erroBusca}</p>}
      </div>

      {esperando && (
        <div className="space-y-2 border-t border-stone-100 pt-3">
          <p className="text-xs text-stone-500">
            Se não houver 5 semelhantes, complete com menos semelhantes — o laudo declara e justifica.
          </p>
          {erroContinuar && <div className="faixa-erro" role="alert" data-testid="erro-continuar">{erroContinuar}</div>}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-end">
            <span className="text-sm text-stone-600 sm:mr-auto" aria-hidden="true">
              {escolhidos} escolhido{escolhidos === 1 ? '' : 's'} (mínimo {MIN_ESCOLHIDOS})
            </span>
            <button type="button" className="btn" disabled={travado || escolhidos < MIN_ESCOLHIDOS}
                    onClick={() => void continuar()}>
              {continuando ? 'Enviando…' : 'Continuar com os escolhidos'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/** Quadro em destaque no topo quando o trabalho espera a escolha dos referenciais. */
export function QuadroCandidatos(props: Props) {
  return (
    <section className="cartao overflow-hidden ring-2 ring-amber-300" aria-labelledby="sec-candidatos" id="candidatos-referencial">
      <div className="space-y-3 px-4 py-4 sm:px-5">
        <h2 id="sec-candidatos" className="titulo-sec">Candidatos a referencial</h2>
        <div className="faixa-aviso" role="status">
          Abra os anúncios, marque “Entra no laudo” em pelo menos 5 e toque em “Continuar com os escolhidos”.
          Ordem: do mais parecido para o menos parecido. ★ = recomendado; linha riscada = não recomendado.
        </div>
        <ListaCandidatos {...props} />
      </div>
    </section>
  )
}
