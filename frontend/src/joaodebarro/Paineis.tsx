import { useEffect, useRef, type ReactNode } from 'react'
import { ChevronDown, ExternalLink } from 'lucide-react'
import { EditorCampo, EscolhaReferenciais } from './Acoes'
import { estatisticasUnitarias, unitario } from './calculo'
import { dataHoraBR, etapaRotulo, moeda, numero2 } from './rotulos'
import type {
  Campo, Detalhe, Evento, Origem, Referencial, ResultadoExtracao, ResultadoSelecao,
} from './tipos'

function Painel({ titulo, contagem, children, abertoPorPadrao = true, id }: {
  titulo: string; contagem?: string; children: ReactNode; abertoPorPadrao?: boolean; id?: string
}) {
  return (
    <details open={abertoPorPadrao} className="cartao group" id={id}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-xl px-4 py-3 transition-colors hover:bg-stone-50/70 sm:px-5 [&::-webkit-details-marker]:hidden">
        <h3 className="titulo-sec">{titulo}</h3>
        <span className="flex items-center gap-2 text-xs text-stone-500">
          {contagem}
          <ChevronDown size={16} className="transition-transform group-open:rotate-180" aria-hidden="true" />
        </span>
      </summary>
      <div className="border-t border-stone-100 px-4 py-3 sm:px-5 sm:py-4">{children}</div>
    </details>
  )
}

const VazioTxt = ({ children }: { children: ReactNode }) => <p className="text-sm text-stone-500">{children}</p>

// ---------------------------------------------------------------- dados extraídos
const ORIGEM: Record<Origem, { rotulo: string; classe: string }> = {
  documento: { rotulo: 'Documento', classe: 'bg-emerald-50 text-emerald-800 ring-emerald-600/20' },
  vistoria: { rotulo: 'Vistoria', classe: 'bg-sky-50 text-sky-800 ring-sky-600/20' },
  pesquisa: { rotulo: 'Pesquisa', classe: 'bg-violet-50 text-violet-800 ring-violet-600/20' },
  inferido: { rotulo: 'Inferido', classe: 'bg-amber-50 text-amber-800 ring-amber-600/25' },
  pendente: { rotulo: 'Pendente', classe: 'bg-red-50 text-red-800 ring-red-600/20' },
}

function valorCampo(c: Campo): string {
  if (c.valor === null || c.valor === undefined || c.valor === '') return '—'
  return `${c.valor}${c.unidade ? ` ${c.unidade}` : ''}`
}

export interface Edicao {
  /** Pode editar (trabalho parado/finalizado). */
  ativa: boolean
  jobId: string
  arquivos: Detalhe['arquivos']
  /** Nome do campo com o editor aberto (pode não existir ainda: vira campo novo). */
  campo: string | null
  setCampo: (nome: string | null) => void
  aoMudar: (msg: string) => void
}

function DadosExtraidos({ campos, ed }: { campos: Campo[]; ed?: Edicao }) {
  const aberto = ed?.ativa ? ed.campo : null
  const novo = aberto && !campos.some((c) => c.nome === aberto) ? aberto : null
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => { if (aberto) ref.current?.scrollIntoView({ block: 'center', behavior: 'smooth' }) }, [aberto])
  const editor = (c: Campo | null, nome: string) => ed && (
    <div ref={ref}>
      <EditorCampo jobId={ed.jobId} campo={c} nome={nome} arquivos={ed.arquivos}
                   aoCancelar={() => ed.setCampo(null)}
                   aoSalvar={() => { ed.setCampo(null); ed.aoMudar(`Campo “${nome}” salvo. Toque em “Recalcular” ou “Regerar documento”.`) }} />
    </div>
  )
  if (!campos.length && !novo) return <VazioTxt>Os dados aparecem aqui quando a extração terminar.</VazioTxt>
  return (
    <ul className="divide-y divide-stone-100">
      {novo && (
        <li className="py-2">
          <span className="text-sm font-medium text-stone-800">Novo campo: {novo}</span>
          {editor(null, novo)}
        </li>
      )}
      {campos.map((c) => {
        const o = ORIGEM[c.origem] ?? ORIGEM.pendente
        return (
          <li key={c.nome} className="grid gap-x-4 gap-y-0.5 py-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_auto]">
            <span className="text-sm text-stone-500">{c.nome}</span>
            <span className={`break-words text-sm font-medium ${c.origem === 'pendente' ? 'text-red-700' : 'text-stone-900'}`}>
              {valorCampo(c)}
              {(c.fonte || c.observacao) && (
                <span className="block text-xs font-normal text-stone-500 break-all">
                  {[c.fonte && `Fonte: ${c.fonte}`, c.observacao].filter(Boolean).join(' · ')}
                </span>
              )}
            </span>
            <span className="flex items-center gap-2 sm:justify-end">
              <span className={`chip ${o.classe}`}>{o.rotulo}</span>
              {ed?.ativa && aberto !== c.nome && (
                <button type="button" className="btn-link btn-peq !px-1" onClick={() => ed.setCampo(c.nome)}
                        aria-label={`Editar ${c.nome}`}>Editar</button>
              )}
            </span>
            {aberto === c.nome && <div className="sm:col-span-3">{editor(c, c.nome)}</div>}
          </li>
        )
      })}
    </ul>
  )
}

// ---------------------------------------------------------------- divergências
function Divergencias({ ext }: { ext: ResultadoExtracao | null }) {
  const div = ext?.divergencias ?? []
  const desc = ext?.documentos_descartados ?? []
  if (!div.length && !desc.length) return <VazioTxt>Nenhuma divergência registrada.</VazioTxt>
  return (
    <div className="space-y-3">
      {div.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm text-stone-800">
          {div.map((d) => <li key={d} className="break-words">{d}</li>)}
        </ul>
      )}
      {desc.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-stone-500">Documentos descartados</p>
          <ul className="space-y-1 text-sm">
            {desc.map((d) => (
              <li key={d.arquivo} className="break-words">
                <span className="font-medium text-stone-800">{d.arquivo}</span>
                <span className="text-stone-600"> — {d.motivo}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- candidatos
function linkSeguro(url: string): string | null {
  try {
    const u = new URL(url)
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.toString() : null
  } catch { return null }
}

function Candidato({ r, marcado, alternar }: { r: Referencial; marcado?: boolean; alternar?: () => void }) {
  const u = unitario(r)
  const href = linkSeguro(r.link)
  const info = [
    r.tipologia, r.quartos != null && `${r.quartos} quarto(s)`, r.area_m2 != null && `${numero2(r.area_m2)} m²`,
    r.lote_m2 != null && `lote ${numero2(r.lote_m2)} m²`, r.padrao && `padrão ${r.padrao}`, r.idade_aparente,
  ].filter(Boolean).join(' · ')
  return (
    <li className={`rounded-lg border px-3 py-2.5 ${r.escolhido ? 'border-barro bg-barro-claro' : 'border-stone-200 bg-white'}`}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {alternar && (
          <label className="-my-2 -ml-1 inline-flex min-h-[44px] cursor-pointer items-center gap-1.5 sm:min-h-0">
            <input type="checkbox" className="h-5 w-5 accent-[var(--barro)]" checked={!!marcado} onChange={alternar}
                   disabled={u === null} aria-label={`Escolher referencial ${r.n}`} />
          </label>
        )}
        <span className="text-sm font-semibold text-stone-900">#{r.n}</span>
        {r.escolhido && <span className="chip bg-barro text-white ring-transparent">Escolhido</span>}
        <span className="text-sm text-stone-600">{[r.portal, r.bairro].filter(Boolean).join(' · ')}</span>
        {href && (
          <a href={href} target="_blank" rel="noopener noreferrer" className="btn-link ml-auto inline-flex items-center gap-1 !px-0 text-xs">
            Ver anúncio <ExternalLink size={12} aria-hidden="true" />
          </a>
        )}
      </div>
      <p className="mt-0.5 text-xs text-stone-600">{info}</p>
      <p className="mt-1 text-sm text-stone-900">
        <span className="font-semibold">{moeda(r.preco)}</span>
        {u !== null && <span className="text-stone-500"> · {moeda(u)}/m²</span>}
      </p>
      {r.justificativa && (
        <p className={`mt-1.5 break-words text-xs ${r.escolhido ? 'text-stone-800' : 'text-stone-500'}`}>
          {r.escolhido ? 'Por que entrou: ' : 'Por que ficou de fora: '}{r.justificativa}
        </p>
      )}
    </li>
  )
}

function Candidatos({ refs, ed, sel }: { refs: Referencial[]; ed?: Edicao; sel: ResultadoSelecao | null }) {
  if (!refs.length) return <VazioTxt>Os referenciais aparecem aqui depois da pesquisa.</VazioTxt>
  if (ed?.ativa) {
    return (
      <EscolhaReferenciais key={refs.map((r) => `${r.n}${r.escolhido ? '+' : ''}`).join()} jobId={ed.jobId} refs={refs}
                           unitarioAtual={sel?.unitario_adotado} aoSalvar={ed.aoMudar}>
        {(r, marcado, alternar) => <Candidato key={r.n} r={r} marcado={marcado} alternar={alternar} />}
      </EscolhaReferenciais>
    )
  }
  const ordenados = [...refs].sort((a, b) => Number(b.escolhido) - Number(a.escolhido) || a.n - b.n)
  return <ul className="space-y-2">{ordenados.map((r) => <Candidato key={r.n} r={r} />)}</ul>
}

// ---------------------------------------------------------------- cálculo
function Medida({ rotulo, valor, destaque }: { rotulo: string; valor: string; destaque?: boolean }) {
  return (
    <div className={`rounded-lg px-3 py-2 ${destaque ? 'bg-orange-50 ring-1 ring-inset ring-orange-200' : 'bg-stone-50'}`}>
      <dt className="text-xs text-stone-500">{rotulo}</dt>
      <dd className={`mt-0.5 font-semibold tabular-nums text-stone-900 ${destaque ? 'text-lg' : 'text-sm'}`}>{valor}</dd>
    </div>
  )
}

function Calculo({ d, sel }: { d: Detalhe; sel: ResultadoSelecao | null }) {
  const r = d.resultado
  if (!r) return <VazioTxt>O cálculo aparece aqui depois da seleção dos referenciais.</VazioTxt>
  const est = estatisticasUnitarias(d.candidatos)
  const faixa = sel?.faixa_pct != null ? `± ${numero2(sel.faixa_pct)}%` : '—'
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Medida rotulo="Unitário mínimo" valor={est ? moeda(est.minimo) : '—'} />
        <Medida rotulo="Unitário médio" valor={est ? moeda(est.media) : '—'} />
        <Medida rotulo="Unitário máximo" valor={est ? moeda(est.maximo) : '—'} />
        <Medida rotulo="Unitário adotado" valor={moeda(r.unitario_adotado)} />
      </dl>
      <dl className="grid gap-2 sm:grid-cols-3">
        <Medida rotulo="Área construída" valor={`${numero2(r.area)} m²`} />
        <Medida rotulo="Valor adotado" valor={moeda(r.valor_adotado)} destaque />
        <Medida rotulo={`Faixa ${faixa}`} valor={`${moeda(r.valor_min)} a ${moeda(r.valor_max)}`} />
      </dl>
      {sel?.justificativa_unitario && (
        <p className="break-words text-xs text-stone-600"><span className="font-medium">Unitário adotado: </span>{sel.justificativa_unitario}</p>
      )}
      {sel?.declaracao_amostra && (
        <p className="break-words text-xs text-stone-600"><span className="font-medium">Amostra: </span>{sel.declaracao_amostra}</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- avisos e atividade
function Avisos({ eventos }: { eventos: Evento[] }) {
  const vistos = new Set<string>()
  const lista = eventos.filter((e) => e.nivel === 'aviso' || e.nivel === 'erro').filter((e) => {
    const k = `${e.etapa}|${e.msg}`
    if (vistos.has(k)) return false
    vistos.add(k)
    return true
  })
  if (!lista.length) return <VazioTxt>Nenhum aviso até agora.</VazioTxt>
  return (
    <ul className="space-y-1.5">
      {lista.map((e) => (
        <li key={e.id} className={`rounded-md px-3 py-2 text-sm ring-1 ring-inset break-words ${
          e.nivel === 'erro' ? 'bg-red-50 text-red-900 ring-red-600/20' : 'bg-amber-50 text-amber-900 ring-amber-600/20'}`}>
          <span className="font-medium">{etapaRotulo(e.etapa)}: </span>{e.msg}
        </li>
      ))}
    </ul>
  )
}

function Atividade({ eventos }: { eventos: Evento[] }) {
  const lista = eventos.filter((e) => e.nivel !== 'resultado').slice(-30).reverse()
  if (!lista.length) return <VazioTxt>Sem atividade registrada.</VazioTxt>
  return (
    <ul className="space-y-1 text-xs text-stone-600">
      {lista.map((e) => (
        <li key={e.id} className="break-words">
          <span className="tabular-nums text-stone-400">{dataHoraBR(e.ts)}</span>{' '}
          <span className="font-medium text-stone-700">{etapaRotulo(e.etapa)}</span> — {e.msg}
        </li>
      ))}
    </ul>
  )
}

export default function Paineis({ detalhe, eventos, edicao }: { detalhe: Detalhe; eventos: Evento[]; edicao?: Edicao }) {
  const ext = (detalhe.etapas.extracao ?? null) as ResultadoExtracao | null
  const sel = (detalhe.etapas.selecao ?? null) as ResultadoSelecao | null
  const escolhidos = detalhe.candidatos.filter((c) => c.escolhido).length
  const pendentes = detalhe.campos.filter((c) => c.origem === 'pendente').length
  return (
    <div className="space-y-4">
      <Painel titulo="Dados extraídos" id="painel-dados"
              contagem={detalhe.campos.length ? `${detalhe.campos.length} campos${pendentes ? ` · ${pendentes} pendentes` : ''}` : undefined}>
        <DadosExtraidos campos={detalhe.campos} ed={edicao} />
      </Painel>
      <Painel titulo="Divergências" abertoPorPadrao={!!(ext?.divergencias?.length || ext?.documentos_descartados?.length)}
              contagem={ext?.divergencias?.length ? String(ext.divergencias.length) : undefined}>
        <Divergencias ext={ext} />
      </Painel>
      <Painel titulo="Referenciais"
              contagem={detalhe.candidatos.length ? `${escolhidos} escolhidos de ${detalhe.candidatos.length}` : undefined}>
        {edicao?.ativa && detalhe.candidatos.length > 0 && (
          <p className="mb-2 text-xs text-stone-500">Marque os referenciais da amostra{sel?.manual ? ' (escolha atual: manual)' : ''}.</p>
        )}
        <Candidatos refs={detalhe.candidatos} ed={edicao} sel={sel} />
      </Painel>
      <Painel titulo="Cálculo do valor"><Calculo d={detalhe} sel={sel} /></Painel>
      <Painel titulo="Avisos"><Avisos eventos={eventos} /></Painel>
      <Painel titulo="Atividade" abertoPorPadrao={false}><Atividade eventos={eventos} /></Painel>
    </div>
  )
}
