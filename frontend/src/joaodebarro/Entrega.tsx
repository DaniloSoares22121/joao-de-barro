import { useEffect, useState } from 'react'
import { Download, ExternalLink, FileSpreadsheet, FileText, FileType2, Loader2 } from 'lucide-react'
import { ApiError, baixar } from './api'
import { parseMarkdown, type Bloco, type Trecho } from './markdown'
import { PendenciasAcionaveis } from './Acoes'
import StatusBadge from './StatusBadge'
import { STATUS_BLOQUEADO, STATUS_PARCIAL, STATUS_PRONTO } from './rotulos'
import type { AcaoPendencia, Pendencia, ResultadoEntrega } from './tipos'

const FRASE_STATUS: Record<string, { texto: string; classe: string }> = {
  [STATUS_PRONTO]: {
    texto: 'Laudo montado e pronto para a sua revisão e assinatura.',
    classe: 'border-emerald-200 bg-emerald-50 text-emerald-900',
  },
  [STATUS_PARCIAL]: {
    texto: 'Laudo montado, mas com pendências. Resolva as pendências impeditivas antes de assinar.',
    classe: 'border-amber-200 bg-amber-50 text-amber-900',
  },
  [STATUS_BLOQUEADO]: {
    texto: 'Trabalho bloqueado: não foi possível montar o laudo. Veja os motivos nas pendências.',
    classe: 'border-red-200 bg-red-50 text-red-900',
  },
}

type Tipo = 'docx' | 'pdf' | 'xlsx'
const TIPOS: ReadonlyArray<{ ext: Tipo; rotulo: string; icone: typeof FileText; cor: string }> = [
  { ext: 'docx', rotulo: 'Word', icone: FileType2, cor: 'bg-sky-50 text-sky-700' },
  { ext: 'pdf', rotulo: 'PDF', icone: FileText, cor: 'bg-red-50 text-red-700' },
  { ext: 'xlsx', rotulo: 'Planilha', icone: FileSpreadsheet, cor: 'bg-emerald-50 text-emerald-700' },
]

const extensao = (nome: string) => (nome.split('.').pop() || '').toLowerCase()

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
            <span className="break-words">{p.texto}</span>
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

export default function Entrega({ jobId, versao, status, entrega, pendencias, aoAgir }: {
  jobId: string
  /** Muda quando o trabalho é atualizado (recarrega pendências e prévia). */
  versao: string
  status: string
  entrega: ResultadoEntrega | null
  pendencias: Pendencia[]
  /** Ação de uma pendência acionável (abre upload, edição de campo, Coletor, dados do trabalho). */
  aoAgir?: (a: AcaoPendencia) => void
}) {
  const arquivos = entrega?.arquivos ?? []
  const porTipo = (ext: Tipo) => arquivos.find((a) => extensao(a) === ext)
  const pdf = porTipo('pdf')

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
      salvarBlob(await baixar(jobId, nome), nome)
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return
      setErro(msgErro(e))
    } finally {
      setBaixando((b) => { const n = new Set(b); n.delete(nome); return n })
    }
  }

  const fr = FRASE_STATUS[status]
  const graves = (entrega?.pendencias ?? pendencias).filter((p) => p.grave).length

  return (
    <section className="space-y-4" aria-labelledby="sec-entrega">
      <div className={`flex flex-wrap items-center justify-between gap-2 rounded-xl border px-4 py-3 ${fr?.classe ?? 'border-stone-200 bg-white'}`}>
        <div>
          <h2 id="sec-entrega" className="text-sm font-semibold">Entrega</h2>
          <p className="text-sm">{fr?.texto ?? 'Trabalho finalizado.'}</p>
        </div>
        <StatusBadge status={status} />
      </div>

      <div className="cartao-pad space-y-3">
        <h3 className="titulo-sec">Arquivos</h3>
        {arquivos.length === 0
          ? <p className="text-sm text-stone-500">Nenhum arquivo foi gerado.</p>
          : (
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
      </div>

      <div className="cartao-pad space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h3 className="titulo-sec">Pendências</h3>
          {graves > 0 && <span className="text-xs font-medium text-red-700">{graves} impeditiva(s)</span>}
        </div>
        {aoAgir && pendencias.length > 0
          ? <PendenciasAcionaveis pendencias={pendencias} aoAgir={aoAgir} />
          : <Pendencias blocos={blocos} fallback={entrega?.pendencias ?? pendencias} />}
      </div>

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
