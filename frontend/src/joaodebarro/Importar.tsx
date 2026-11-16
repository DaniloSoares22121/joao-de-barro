/** ORDEM 061: arrastar e soltar, formatos aceitos e a conversa do WhatsApp importada (com o texto
 * dos áudios no lugar de cada áudio). Mesma lista de formatos do servidor (whatsapp.py). */
import { useEffect, useState, type DragEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Camera, FileText, Mic, Video, X } from 'lucide-react'
import { ApiError, get, postForm } from './api'
import { dataHoraBR } from './rotulos'

const EXT: Record<string, string[]> = {
  texto: ['.txt'], audio: ['.opus', '.ogg', '.m4a', '.mp3', '.aac', '.wav', '.amr'],
  foto: ['.jpg', '.jpeg', '.png', '.webp', '.heic'], documento: ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv'],
  video: ['.mp4', '.3gp', '.mov'], contato: ['.vcf'], zip: ['.zip'],
}
/** Para o atributo accept do clipe (o seletor de arquivos já mostra só o que é aceito). */
export const ACEITOS = Object.values(EXT).flat().join(',')

export function tipoArquivo(nome: string): string {
  const ext = '.' + (nome.split('.').pop() || '').toLowerCase()
  return Object.entries(EXT).find(([, l]) => l.includes(ext))?.[0] ?? 'recusado'
}

/** Separa o que o JdB aceita; o resto vira um aviso de uma linha. */
export function separar(fs: File[]): { aceitos: File[]; aviso: string } {
  const recusados = fs.filter((f) => tipoArquivo(f.name) === 'recusado')
  const aceitos = fs.filter((f) => tipoArquivo(f.name) !== 'recusado')
  const aviso = recusados.length
    ? `Deixei de fora ${recusados.length === 1 ? `“${recusados[0].name}”` : `${recusados.length} arquivos`}: programa ou formato que eu não abro.`
    : ''
  return { aceitos, aviso }
}

/** Precisa da importação (zip, conversa, áudio, vídeo ou contato, ou vários de uma vez)? */
export function ehImportacao(fs: File[]): boolean {
  return fs.length > 1 || fs.some((f) => ['zip', 'texto', 'audio', 'video', 'contato'].includes(tipoArquivo(f.name)))
}

export const LIMITE_ENVIO = 500 * 1024 * 1024

/** Envia tudo de uma vez para a leitura em segundo plano do servidor. */
export async function importar<T>(clienteId: string, fs: File[]): Promise<T & { recusados?: string[] }> {
  const total = fs.reduce((s, f) => s + f.size, 0)
  if (total > LIMITE_ENVIO) throw new ApiError(413, 'Passou de 500 MB. Envie em partes.')
  const fd = new FormData()
  for (const f of fs) fd.append('arquivos', f, f.name)
  return postForm(`/clientes/${encodeURIComponent(clienteId)}/importar`, fd)
}

/** Área que aceita arrastar e soltar: mostra "Solte aqui" enquanto o arquivo está por cima. */
export function useSoltar(aoSoltar: (fs: File[]) => void) {
  const [arrastando, setArrastando] = useState(false)
  const temArquivo = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes('Files')
  return {
    arrastando,
    props: {
      onDragEnter: (e: DragEvent) => { if (temArquivo(e)) { e.preventDefault(); setArrastando(true) } },
      onDragOver: (e: DragEvent) => { if (temArquivo(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy' } },
      onDragLeave: (e: DragEvent) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setArrastando(false) },
      onDrop: (e: DragEvent) => {
        if (!temArquivo(e)) return
        e.preventDefault(); setArrastando(false)
        const fs = Array.from(e.dataTransfer.files ?? [])
        if (fs.length) aoSoltar(fs)
      },
    },
  }
}

export function SolteAqui() {
  return <div className="solte-aqui" aria-hidden="true"><span>Solte aqui</span></div>
}

// ---------------------------------------------------------------- a conversa completa
interface MsgImportada { quando: string; autor: string; texto: string; anexo: string; tipo_anexo: string; transcricao: string }
interface Importada { meta: { contato: string; mensagens: number }; mensagens: MsgImportada[] }

const ICONE: Record<string, ReactNode> = {
  audio: <Mic size={18} aria-hidden="true" />, video: <Video size={18} aria-hidden="true" />,
  foto: <Camera size={18} aria-hidden="true" />, documento: <FileText size={18} aria-hidden="true" />,
}
const ROTULO: Record<string, string> = { audio: 'Áudio', video: 'Vídeo', foto: 'Foto', documento: 'Documento', contato: 'Contato' }

export function ConversaCompleta({ clienteId, importacao, aoFechar }: { clienteId: string; importacao: string; aoFechar: () => void }) {
  const [c, setC] = useState<Importada | null>(null)
  const [erro, setErro] = useState('')
  useEffect(() => {
    get<Importada>(`/clientes/${encodeURIComponent(clienteId)}/importacoes/${encodeURIComponent(importacao)}`)
      .then(setC).catch(() => setErro('Não deu para abrir a conversa.'))
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Escape') aoFechar() }
    document.addEventListener('keydown', tecla)
    return () => document.removeEventListener('keydown', tecla)
  }, [clienteId, importacao, aoFechar])
  return createPortal(
    <div className="painel-l13-fundo" onMouseDown={(e) => { if (e.target === e.currentTarget) aoFechar() }}>
      <section className="painel-conversa" role="dialog" aria-modal="true" aria-labelledby="titulo-conversa">
        <div className="painel-conversa-topo">
          <h2 id="titulo-conversa" className="titulo-sub-l13">
            {c ? `Conversa do WhatsApp${c.meta.contato ? ` com ${c.meta.contato}` : ''} · ${c.meta.mensagens} mensagens` : 'Conversa do WhatsApp'}
          </h2>
          <button type="button" className="btn-opcoes" onClick={aoFechar} autoFocus><X size={20} aria-hidden="true" /> Fechar</button>
        </div>
        {erro && <p className="aviso-impede">{erro}</p>}
        {!c && !erro && <p className="small-jdb">Carregando…</p>}
        {c && (
          <ol className="lista-conversa">
            {c.mensagens.map((m, i) => (
              <li key={i} className={m.autor ? '' : 'msg-sistema-wpp'}>
                <span className="small-jdb tabular-nums">{m.quando ? dataHoraBR(m.quando) : '—'}{m.autor ? ` · ${m.autor}` : ''}</span>
                {m.texto && <p className="break-words whitespace-pre-wrap">{m.texto}</p>}
                {m.anexo && (
                  <p className="anexo-wpp">
                    {ICONE[m.tipo_anexo]}<b>{ROTULO[m.tipo_anexo] ?? 'Arquivo'}</b>
                    {(m.tipo_anexo === 'audio' || m.tipo_anexo === 'video')
                      && (m.transcricao ? <span className="break-words">“{m.transcricao}”</span> : <span className="small-jdb">sem fala reconhecida</span>)}
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>,
    document.body,
  )
}
