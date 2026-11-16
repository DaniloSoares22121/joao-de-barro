import { useEffect, useState } from 'react'
import { Download, ExternalLink, FileSpreadsheet, FileText, FileType2, Loader2 } from 'lucide-react'
import { ApiError, baixar, baixarRaw, get, post, postForm } from './api'
import { parseMarkdown, type Bloco, type Trecho } from './markdown'
import { PendenciasAcionaveis } from './Acoes'
import PendenciasSimples from './PendenciasSimples'
import { STATUS_BLOQUEADO, STATUS_PARCIAL, STATUS_PRONTO, textoTela } from './rotulos'
import type { AcaoPendencia, Pendencia, PontoContestacao, ResultadoEntrega } from './tipos'

const FRASE_STATUS: Record<string, { texto: string; classe: string }> = {
  [STATUS_PRONTO]: {
    texto: 'Laudo montado e pronto para a sua revisão.',
    classe: 'border-emerald-200 bg-emerald-50 text-emerald-900',
  },
  [STATUS_PARCIAL]: {
    texto: 'Laudo gerado com pendências. Resolva as pendências impeditivas antes de baixar para a revisão humana.',
    classe: 'border-amber-200 bg-amber-50 text-amber-900',
  },
  [STATUS_BLOQUEADO]: {
    texto: 'Bloqueado — pendência do avaliador. O laudo não foi montado: resolva as pendências abaixo e refaça.',
    classe: 'border-amber-300 bg-amber-50 text-red-900',
  },
}
/** Sem arquivos gerados não há "laudo montado", qualquer que seja o status. */
const SEM_ARQUIVOS = {
  texto: 'O laudo ainda não foi montado. Veja as pendências abaixo.',
  classe: 'border-amber-200 bg-amber-50 text-amber-900',
}

type Tipo = 'docx' | 'pdf' | 'xlsx'
const TIPOS: ReadonlyArray<{ ext: Tipo; rotulo: string; icone: typeof FileText; cor: string }> = [
  { ext: 'docx', rotulo: 'Word', icone: FileType2, cor: 'bg-sky-50 text-sky-700' },
  { ext: 'pdf', rotulo: 'PDF', icone: FileText, cor: 'bg-red-50 text-red-700' },
  { ext: 'xlsx', rotulo: 'Planilha', icone: FileSpreadsheet, cor: 'bg-emerald-50 text-emerald-700' },
]

const extensao = (nome: string) => (nome.split('.').pop() || '').toLowerCase()

export function salvarBlob(blob: Blob, nome: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = nome
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

function msgErro(e: unknown): string {
  if (e instanceof ApiError && e.status === 404) return 'Arquivo não encontrado.'
  return 'Não foi possível baixar o arquivo.'
}

const Inline = ({ trechos }: { trechos: Trecho[] }) => (
  <>{trechos.map((t, i) => (t.negrito ? <strong key={i}>{t.texto}</strong> : <span key={i}>{t.texto}</span>))}</>
)

function Pendencias({ blocos, fallback }: { blocos: Bloco[] | null; fallback: Pendencia[] }) {
  if (blocos === null && fallback.length === 0) return <p className="text-sm text-stone-500">Nenhuma pendência.</p>
  if (blocos === null) {
    return (
      <ul className="space-y-1.5">
        {fallback.map((p) => (
          <li key={p.texto} className="flex items-start gap-2 text-sm">
            {p.grave && <span className="chip bg-red-50 text-red-800 ring-red-600/20">impeditiva</span>}
            <span className="break-words">{textoTela(p.texto)}</span>
          </li>
        ))}
      </ul>
    )
  }
  const itens = blocos.filter((b) => b.tipo === 'item')
  return (
    <div className="space-y-1.5">
      {blocos.map((b, i) => {
        if (b.tipo === 'titulo') {
          return i === 0 ? null : <p key={i} className="pt-1 text-sm font-semibold text-stone-800"><Inline trechos={b.trechos} /></p>
        }
        if (b.tipo === 'item') {
          return (
            <div key={i} className="flex items-start gap-2 text-sm text-stone-800">
              {b.impeditiva
                ? <span className="chip shrink-0 bg-red-50 text-red-800 ring-red-600/20">impeditiva</span>
                : <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-stone-400" aria-hidden="true" />}
              <span className="break-words"><Inline trechos={b.trechos} /></span>
            </div>
          )
        }
        return <p key={i} className="text-sm text-stone-700"><Inline trechos={b.trechos} /></p>
      })}
      {itens.length === 0 && <p className="text-sm text-stone-500">Nenhuma pendência.</p>}
    </div>
  )
}

/** D-041: cópia do laudo para mostrar a clientes (endereço/nomes trocados por █, mapa e
 * documentos desfocados). Gerada no servidor, sem IA. */
function ExemploClientes({ jobId }: { jobId: string }) {
  const [gerando, setGerando] = useState(false)
  const [arqs, setArqs] = useState<{ docx: string; pdf: string | null } | null>(null)
  const [erro, setErro] = useState('')
  async function gerar() {
    setErro('')
    setGerando(true)
    try {
      setArqs(await post<{ docx: string; pdf: string | null }>(`/jobs/${encodeURIComponent(jobId)}/exemplo`))
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return
      setErro(e instanceof ApiError && e.status === 409 ? e.detail : 'Não foi possível gerar o exemplo.')
    } finally {
      setGerando(false)
    }
  }
  async function baixarEx(nome: string) {
    try {
      const { blob } = await baixarRaw(`/jobs/${encodeURIComponent(jobId)}/exemplo/${encodeURIComponent(nome)}`)
      salvarBlob(blob, nome)
    } catch (e) {
      setErro(msgErro(e))
    }
  }
  return (
    <div className="space-y-2 border-t border-stone-100 pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-stone-600">Exemplo para clientes: endereço, nomes e documentos ocultos; fotos e valores mantidos.</p>
        <button type="button" className="btn-sec" disabled={gerando} onClick={() => void gerar()}>
          {gerando ? 'Gerando…' : 'Gerar exemplo para clientes'}
        </button>
      </div>
      {arqs && (
        <div className="flex flex-wrap gap-2" role="status">
          <button type="button" className="btn-link" onClick={() => void baixarEx(arqs.docx)}>Baixar exemplo (Word)</button>
          {arqs.pdf && <button type="button" className="btn-link" onClick={() => void baixarEx(arqs.pdf!)}>Baixar exemplo (PDF)</button>}
        </div>
      )}
      {erro && <p className="erro-txt" role="alert">{erro}</p>}
    </div>
  )
}

const GRAV: Record<PontoContestacao['gravidade'], { rotulo: string; classe: string }> = {
  alta: { rotulo: 'alta', classe: 'bg-red-100 text-red-800' },
  media: { rotulo: 'média', classe: 'bg-amber-100 text-amber-800' },
  baixa: { rotulo: 'baixa', classe: 'bg-stone-100 text-stone-700' },
}

/** ORDEM 039: D-084 (conferência de coerência, sem IA) e D-083 (contestação simulada). */
function Conferencias({ entrega }: { entrega: ResultadoEntrega | null }) {
  const co = entrega?.coerencia
  const ct = entrega?.contestacao
  if (!co && !ct) return null
  return (
    <details className="cartao-pad space-y-3 detalhes">
      <summary className="titulo-sec">Ver detalhes das conferências</summary>
      {co && (
        <div className={`rounded-lg border px-3 py-2 text-sm ${co.ok ? 'border-emerald-200 bg-emerald-50' : 'border-red-200 bg-red-50'}`}>
          <p className="font-semibold">Coerência dos números (capa, corpo, resumo, quadro, extenso e planilha)</p>
          {co.ok ? <p>Tudo igual em todo o laudo e na planilha.</p> : (
            <ul className="mt-1 list-disc pl-5">{co.diferencas.map((d) => <li key={d}>{d}</li>)}</ul>
          )}
        </div>
      )}
      {ct && (
        <div className="space-y-2">
          <p className="text-sm"><strong>Contestação simulada</strong> — onde a parte contrária atacaria o laudo. O laudo não foi alterado: você decide o que reforçar.</p>
          {ct.pontos.length === 0 ? <p className="text-sm text-stone-500">Nenhum ponto atacável encontrado.</p> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-xs">
                <thead><tr className="text-stone-500"><th className="p-1">Página</th><th className="p-1">Ponto</th><th className="p-1">Por que é atacável</th><th className="p-1">Gravidade</th><th className="p-1">Como reforçar</th></tr></thead>
                <tbody>{ct.pontos.map((p, i) => (
                  <tr key={i} className="border-t border-stone-100 align-top">
                    <td className="p-1 whitespace-nowrap">{p.pagina}</td><td className="p-1">{p.ponto}</td><td className="p-1">{p.por_que}</td>
                    <td className="p-1"><span className={`rounded px-1.5 py-0.5 ${GRAV[p.gravidade].classe}`}>{GRAV[p.gravidade].rotulo}</span></td>
                    <td className="p-1">{p.como_reforcar}</td>
                  </tr>))}</tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </details>
  )
}

/** ORDEM 039 / D-086: assinar no gov.br e subir o PDF assinado (o sistema só confere). */
export function Assinar({ jobId, assinado, aoEnviar }: { jobId: string; assinado?: string; aoEnviar: () => void }) {
  const [info, setInfo] = useState<{ assinador: string; instrucao: string[] } | null>(null)
  const [msg, setMsg] = useState('')
  const [erro, setErro] = useState('')
  const [ocupado, setOcupado] = useState(false)
  useEffect(() => { get<{ assinador: string; instrucao: string[] }>('/assinatura/instrucao').then(setInfo).catch(() => undefined) }, [])
  async function enviar(f: File | undefined) {
    if (!f) return
    setErro(''); setMsg(''); setOcupado(true)
    try {
      const fd = new FormData()
      fd.append('arquivo', f)
      const r = await postForm<{ arquivo: string }>(`/jobs/${encodeURIComponent(jobId)}/assinado`, fd)
      setMsg(`Assinatura conferida. Versão final guardada: ${r.arquivo}`)
      aoEnviar()
    } catch (e) {
      setErro(msgErro(e))
    } finally {
      setOcupado(false)
    }
  }
  return (
    <div className="cartao-pad space-y-2">
      <h3 className="titulo-sec">Assinar</h3>
      {info && (
        <a href={info.assinador} target="_blank" rel="noopener noreferrer" className="btn btn-peq inline-flex items-center gap-1.5">
          Abrir o assinador do gov.br <ExternalLink size={13} aria-hidden="true" />
        </a>
      )}
      <ol className="space-y-0.5 text-sm text-stone-600">{(info?.instrucao ?? []).map((l) => <li key={l}>{l}</li>)}</ol>
      <label className="block text-sm font-semibold" htmlFor="pdf-assinado">PDF assinado</label>
      <input id="pdf-assinado" type="file" accept="application/pdf,.pdf" disabled={ocupado}
             onChange={(e) => void enviar(e.target.files?.[0])} className="block text-sm" />
      <p className="text-xs text-stone-500">O sistema nunca assina por você e nunca pede a sua senha.</p>
      {ocupado && <p className="text-sm" role="status">Conferindo a assinatura…</p>}
      {(msg || assinado) && <p className="text-sm text-emerald-800">{msg || `Versão final assinada: ${assinado}`}</p>}
      {erro && <p className="erro-txt" role="alert">{erro}</p>}
    </div>
  )
}

export default function Entrega({ jobId, versao, status, entrega, pendencias, aoAgir, revisao, aprovado }: {
  jobId: string
  /** Muda quando o trabalho é atualizado (recarrega pendências e prévia). */
  versao: string
  status: string
  entrega: ResultadoEntrega | null
  pendencias: Pendencia[]
  /** Ação de uma pendência acionável (abre upload, edição de campo, Coletor, dados do trabalho). */
  aoAgir?: (a: AcaoPendencia) => void
  /** 074-E5 (D-073): antes do ok, só o PDF, com "(REVISÃO N)" no nome. */
  revisao?: number
  aprovado?: boolean
}) {
  const antesDoOk = aprovado === false
  const arquivos = (entrega?.arquivos ?? []).filter((a) => !antesDoOk || extensao(a) === 'pdf')
  const porTipo = (ext: Tipo) => arquivos.find((a) => extensao(a) === ext)
  const pdf = arquivos.find((a) => extensao(a) === 'pdf' && !a.toLowerCase().endsWith('_assinado.pdf'))

  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [pdfErro, setPdfErro] = useState('')
  // Downloads independentes: cada botão só trava a si mesmo.
  const [baixando, setBaixando] = useState<ReadonlySet<string>>(() => new Set())
  const [erro, setErro] = useState('')
  const [blocos, setBlocos] = useState<Bloco[] | null>(null)

  // Prévia do PDF.
  useEffect(() => {
    setPdfUrl(null)
    setPdfErro('')
    if (!pdf) return
    let vivo = true
    let url = ''
    baixar(jobId, pdf).then((b) => {
      if (!vivo) return
      url = URL.createObjectURL(new Blob([b], { type: 'application/pdf' }))
      setPdfUrl(url)
    }).catch((e) => { if (vivo) setPdfErro(msgErro(e)) })
    return () => { vivo = false; if (url) URL.revokeObjectURL(url) }
  }, [jobId, pdf, versao])

  // Lista de pendências (pendencias.md).
  useEffect(() => {
    setBlocos(null)
    let vivo = true
    baixar(jobId, 'pendencias.md').then((b) => b.text()).then((t) => { if (vivo) setBlocos(parseMarkdown(t)) })
      .catch(() => undefined)
    return () => { vivo = false }
  }, [jobId, versao])

  async function baixarArquivo(nome: string) {
    setErro('')
    setBaixando((b) => new Set(b).add(nome))
    try {
      const salvar = antesDoOk && extensao(nome) === 'pdf' ? nome.replace(/\.pdf$/i, ` (REVISÃO ${Math.max(1, revisao ?? 1)}).pdf`) : nome
      salvarBlob(await baixar(jobId, nome), salvar.split('/').pop() || salvar)
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return
      setErro(msgErro(e))
    } finally {
      setBaixando((b) => { const n = new Set(b); n.delete(nome); return n })
    }
  }

  const fr = status === STATUS_BLOQUEADO ? FRASE_STATUS[status] : arquivos.length ? FRASE_STATUS[status] : SEM_ARQUIVOS
  const graves = (entrega?.pendencias ?? pendencias).filter((p) => p.grave).length

  return (
    <section className="space-y-4" aria-labelledby="sec-entrega">
      {/* ORDEM 047: o estado aparece na linha de etapas e no próximo passo (sem selo aqui) */}
      <h2 id="sec-entrega" className="sr-only">{fr?.texto ?? 'Entrega'}</h2>
      {arquivos.length > 0 && (
      <div className="cartao-pad space-y-3">
        <h3 className="titulo-sec">Arquivos</h3>
        {antesDoOk && <p className="text-[16px] text-stone-600">Para revisão vai só o PDF. O Word e a planilha saem depois do seu ok.</p>}
        {(
            <div className="grid gap-2 sm:grid-cols-3">
              {TIPOS.map(({ ext, rotulo, icone: Icone, cor }) => {
                const nome = porTipo(ext)
                const ocupado = !!nome && baixando.has(nome)
                return (
                  <button key={ext} type="button" disabled={!nome || ocupado}
                          onClick={() => nome && void baixarArquivo(nome)}
                          className="btn-sec !justify-start !gap-3 !px-3 !py-2.5 text-left"
                          title={nome ?? `${rotulo} não gerado`}>
                    <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${nome ? cor : 'bg-stone-100 text-stone-400'}`}>
                      <Icone size={18} aria-hidden="true" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-semibold">{ocupado ? 'Baixando…' : `Baixar ${rotulo}`}</span>
                      <span className="block truncate text-xs font-normal text-stone-500">{nome ?? 'não gerado'}</span>
                    </span>
                    {nome && (ocupado
                      ? <Loader2 size={16} className="shrink-0 animate-spin text-stone-400" aria-hidden="true" />
                      : <Download size={16} className="shrink-0 text-stone-400" aria-hidden="true" />)}
                  </button>
                )
              })}
            </div>
          )}
        {erro && <p className="erro-txt" role="alert">{erro}</p>}
        {/* ORDEM 008: laudo com pendência não vai para cliente — exemplo só do PRONTO */}
        {status === STATUS_PRONTO && <ExemploClientes jobId={jobId} />}
      </div>
      )}

      {/* 178-2: a assinatura saiu do sistema (o avaliador assina o PDF por fora); o Assinar fica guardado */}

      {/* ORDEM 045 / D-100: só o que depende do avaliador, em cartões; erro do sistema corrige sozinho */}
      <PendenciasSimples jobId={jobId} versao={versao} />
      <Conferencias entrega={entrega} />
      {false && aoAgir && graves > 0 && blocos && <><PendenciasAcionaveis pendencias={pendencias} aoAgir={aoAgir!} /><Pendencias blocos={blocos} fallback={pendencias} /></>}

      {pdf && (
        <div className="cartao overflow-hidden">
          <div className="flex items-center justify-between gap-2 px-4 py-3 sm:px-5">
            <h3 className="titulo-sec">Prévia do PDF</h3>
            {pdfUrl && (
              <a className="btn-link inline-flex items-center gap-1" href={pdfUrl} target="_blank" rel="noopener noreferrer">
                Abrir em nova aba <ExternalLink size={13} aria-hidden="true" />
              </a>
            )}
          </div>
          {pdfErro && <p className="erro-txt px-4 pb-3 sm:px-5">{pdfErro}</p>}
          {!pdfUrl && !pdfErro && <p className="px-4 pb-4 text-sm text-stone-500 sm:px-5" role="status">Carregando prévia…</p>}
          {pdfUrl && (
            <iframe title="Prévia do laudo em PDF" src={pdfUrl} className="hidden h-[80vh] min-h-[420px] w-full border-t border-stone-100 bg-stone-100 sm:block" />
          )}
          {pdfUrl && (
            <p className="border-t border-stone-100 px-4 py-3 text-sm text-stone-500 sm:hidden">
              No celular a prévia abre em outra aba: toque em “Abrir em nova aba”.
            </p>
          )}
        </div>
      )}
      {!pdf && arquivos.length > 0 && (
        <p className="text-sm text-stone-500">O PDF não foi gerado; baixe o Word para revisar.</p>
      )}
    </section>
  )
}
