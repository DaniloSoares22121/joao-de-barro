import { useEffect, useRef, useState, type DragEvent } from 'react'
import { Camera, CheckCircle2, FileText, Loader2, UploadCloud, X } from 'lucide-react'
import { tamanhoLegivel } from './validacao'

export interface ItemUpload {
  id: string
  file: File
  /** 0..1 */
  progresso: number
  estado: 'fila' | 'enviando' | 'ok' | 'erro'
  erro?: string
  /** Texto curto de andamento (ex.: "Comprimindo…", "Sem rede; nova tentativa em 3 s"). */
  nota?: string
}

interface Props {
  id: string
  titulo: string
  descricao: string
  itens: ItemUpload[]
  accept?: string
  desabilitado?: boolean
  onAdicionar: (files: File[]) => void
  onRemover: (itemId: string) => void
  /** Mostra o botão "Tirar foto" (câmera traseira do celular). */
  camera?: boolean
  /** Item marcado como "Fachada (capa)"; com `onFachada`, cada imagem ganha a opção. */
  fachadaId?: string | null
  onFachada?: (itemId: string | null) => void
}

/** Miniatura da imagem por object URL (revogado ao desmontar/trocar o arquivo). */
function Miniatura({ file }: { file: File }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    const u = URL.createObjectURL(file)
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [file])
  if (!url) return <span className="h-12 w-12 shrink-0 rounded bg-stone-100" aria-hidden="true" />
  return <img src={url} alt="" className="h-12 w-12 shrink-0 rounded object-cover" />
}

function Linha({ it, desabilitado, onRemover, fachada, onFachada }: {
  it: ItemUpload; desabilitado?: boolean; onRemover: () => void
  fachada?: boolean; onFachada?: (marcar: boolean) => void
}) {
  const pct = Math.round(it.progresso * 100)
  const imagem = it.file.type.startsWith('image/')
  return (
    <li className="flex items-start gap-2 rounded-lg border border-stone-200 bg-white px-3 py-2">
      {imagem ? <Miniatura file={it.file} />
              : <FileText size={16} className="mt-0.5 shrink-0 text-stone-400" aria-hidden="true" />}
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-sm text-stone-800" title={it.file.name}>{it.file.name}</span>
          <span className="shrink-0 text-xs text-stone-500">{tamanhoLegivel(it.file.size)}</span>
        </div>
        {it.estado === 'enviando' && (
          <div className="mt-1.5 flex items-center gap-2" role="progressbar" aria-valuenow={pct} aria-valuemin={0}
               aria-valuemax={100} aria-label={`Enviando ${it.file.name}`}>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-stone-100">
              <div className="h-full rounded-full bg-barro transition-[width]" style={{ width: `${pct}%` }} />
            </div>
            <span className="w-9 text-right text-xs tabular-nums text-stone-500">{pct}%</span>
          </div>
        )}
        {it.nota && it.estado !== 'erro' && it.estado !== 'ok' && <p className="mt-0.5 text-xs text-stone-500">{it.nota}</p>}
        {it.estado === 'erro' && <p className="mt-0.5 text-xs text-red-700">{it.erro || 'Falha no envio.'}</p>}
        {imagem && onFachada && (
          <label className="mt-1 inline-flex min-h-[44px] cursor-pointer items-center gap-2 text-sm text-stone-700 sm:min-h-0">
            <input type="checkbox" className="h-5 w-5 accent-[var(--barro)]" checked={!!fachada}
                   disabled={desabilitado || it.estado === 'ok'}
                   onChange={(e) => onFachada(e.target.checked)} />
            Fachada (capa)
          </label>
        )}
      </div>
      <span className="mt-0.5 shrink-0">
        {it.estado === 'ok' && <CheckCircle2 size={16} className="text-emerald-600" aria-label="Enviado" />}
        {it.estado === 'enviando' && <Loader2 size={16} className="animate-spin text-barro" aria-hidden="true" />}
        {(it.estado === 'fila' || it.estado === 'erro') && !desabilitado && (
          <button type="button" onClick={onRemover} aria-label={`Remover ${it.file.name}`}
                  className="toque -m-2 rounded p-2 text-stone-400 hover:bg-stone-100 hover:text-stone-700">
            <X size={16} />
          </button>
        )}
      </span>
    </li>
  )
}

export default function Dropzone({ id, titulo, descricao, itens, accept, desabilitado, onAdicionar, onRemover,
                                  camera, fachadaId, onFachada }: Props) {
  const entrada = useRef<HTMLInputElement>(null)
  const cam = useRef<HTMLInputElement>(null)
  const [sobre, setSobre] = useState(false)

  function soltar(e: DragEvent) {
    e.preventDefault()
    setSobre(false)
    if (desabilitado) return
    const arquivos = Array.from(e.dataTransfer.files)
    if (arquivos.length) onAdicionar(arquivos)
  }

  return (
    <div>
      <p className="rotulo" id={`${id}-t`}>{titulo}</p>
      <div
        onDragOver={(e) => { e.preventDefault(); if (!desabilitado) setSobre(true) }}
        onDragLeave={() => setSobre(false)}
        onDrop={soltar}
        className={`rounded-xl border-2 border-dashed px-4 py-5 text-center transition-colors ${
          sobre ? 'border-barro bg-orange-50' : 'border-stone-300 bg-stone-50/60'} ${desabilitado ? 'opacity-60' : ''}`}
      >
        <UploadCloud size={22} className="mx-auto text-stone-400" aria-hidden="true" />
        <p className="mt-1 text-sm text-stone-600">{descricao}</p>
        <div className="mt-2 flex flex-wrap justify-center gap-2">
          {camera && (
            <button type="button" disabled={desabilitado} onClick={() => cam.current?.click()}
                    aria-describedby={`${id}-t`} className="btn btn-peq">
              <Camera size={16} aria-hidden="true" /> Tirar foto
            </button>
          )}
          <button type="button" disabled={desabilitado} onClick={() => entrada.current?.click()}
                  aria-describedby={`${id}-t`} className="btn-sec btn-peq">
            Escolher arquivos
          </button>
        </div>
        {camera && (
          <input ref={cam} type="file" accept="image/*" capture="environment" className="sr-only" tabIndex={-1}
                 aria-label={`Tirar foto — ${titulo}`}
                 onChange={(e) => {
                   const arquivos = Array.from(e.target.files ?? [])
                   e.target.value = ''
                   if (arquivos.length) onAdicionar(arquivos)
                 }} />
        )}
        <input ref={entrada} type="file" multiple accept={accept} className="sr-only" tabIndex={-1}
               aria-labelledby={`${id}-t`}
               onChange={(e) => {
                 const arquivos = Array.from(e.target.files ?? [])
                 e.target.value = ''
                 if (arquivos.length) onAdicionar(arquivos)
               }} />
      </div>
      {itens.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {itens.map((it) => (
            <Linha key={it.id} it={it} desabilitado={desabilitado} onRemover={() => onRemover(it.id)}
                   fachada={fachadaId === it.id}
                   onFachada={onFachada ? (m) => onFachada(m ? it.id : null) : undefined} />
          ))}
        </ul>
      )}
    </div>
  )
}
