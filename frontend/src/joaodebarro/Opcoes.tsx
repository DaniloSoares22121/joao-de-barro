/** ORDEM 060: botão "⋯ Opções" de cada trabalho (L1 e L3): Editar trabalho, Exportar (.zip),
 * Novo a partir deste e Apagar (vai para a Lixeira; só "Esvaziar lixeira" apaga de vez). */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Copy, Download, MoreHorizontal, Pencil, Trash2 } from 'lucide-react'
import { ApiError, baixarRaw, post } from './api'
import Confirmar from './Confirmar'
import { salvarBlob } from './Entrega'
import { prefillDe } from './campo'
import { useStore } from './store'

// "Editar trabalho" pedido na lista: a tela do trabalho abre a edição assim que carregar.
let edicaoPedida: string | null = null
export function pedirEdicao(jobId: string) { edicaoPedida = jobId }
export function consumirEdicao(jobId: string): boolean {
  if (edicaoPedida !== jobId) return false
  edicaoPedida = null
  return true
}

export interface JobOpcoes {
  id: string; numero: number
  cliente?: string | null; tipo?: string | null; bairro?: string | null; cidade?: string | null
  modalidade?: string | null; finalidade?: string | null
}

export default function Opcoes({ job, titulo, entregue, aoEditar, aoApagado }: {
  job: JobOpcoes; titulo: string; entregue: boolean
  aoEditar: () => void; aoApagado: (msg: string) => void
}) {
  const novoAPartir = useStore((s) => s.novoAPartir)
  const [aberto, setAberto] = useState(false)
  const [apagando, setApagando] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState('')
  const [msg, setMsg] = useState('')
  const caixa = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!aberto) return
    const fora = (e: MouseEvent) => { if (!caixa.current?.contains(e.target as Node)) setAberto(false) }
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Escape') setAberto(false) }
    document.addEventListener('mousedown', fora)
    document.addEventListener('keydown', tecla)
    caixa.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus()
    return () => { document.removeEventListener('mousedown', fora); document.removeEventListener('keydown', tecla) }
  }, [aberto])

  async function exportar() {
    setAberto(false)
    setMsg('Preparando o arquivo…')
    try {
      const { blob, nome } = await baixarRaw(`/jobs/${encodeURIComponent(job.id)}/exportar.zip`)
      salvarBlob(blob, nome || `trabalho-${job.numero}.zip`)
      setMsg('')
    } catch {
      setMsg('Não deu para exportar. Tente de novo.')
    }
  }

  async function apagar() {
    setErro('')
    setOcupado(true)
    try {
      await post(`/jobs/${encodeURIComponent(job.id)}/lixeira`)
      setApagando(false)
      aoApagado(`“${titulo}” foi para a Lixeira. Para trazer de volta: Configurações › Lixeira.`)
    } catch (e) {
      setErro(e instanceof ApiError && e.status === 409
        ? 'O JdB está trabalhando neste trabalho agora. Espere terminar para apagar.' : 'Não deu para apagar. Tente de novo.')
    } finally {
      setOcupado(false)
    }
  }

  const item = (rotulo: string, icone: ReactNode, acao: () => void, perigo = false) => (
    <button type="button" role="menuitem" className={`item-opcoes${perigo ? ' item-perigo' : ''}`} onClick={acao}>
      <span aria-hidden="true">{icone}</span>{rotulo}
    </button>
  )

  return (
    // o card inteiro abre o trabalho: o clique no menu não pode chegar nele
    <div className="opcoes-jdb" ref={caixa} onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
      <button type="button" className="btn-opcoes" aria-haspopup="menu" aria-expanded={aberto}
              aria-label={`Opções do trabalho nº ${job.numero}`} onClick={() => setAberto(!aberto)}>
        <MoreHorizontal size={22} aria-hidden="true" /> Opções
      </button>
      {aberto && (
        <div className="menu-opcoes" role="menu" aria-label={`Opções do trabalho nº ${job.numero}`}>
          {item('Editar trabalho', <Pencil size={20} />, () => { setAberto(false); aoEditar() })}
          {item('Exportar', <Download size={20} />, () => void exportar())}
          {item('Novo a partir deste', <Copy size={20} />, () => { setAberto(false); novoAPartir(prefillDe(job as unknown as Record<string, unknown>)) })}
          {item('Apagar', <Trash2 size={20} />, () => { setAberto(false); setErro(''); setApagando(true) }, true)}
        </div>
      )}
      {msg && <p className="small-jdb msg-opcoes" role="status">{msg}</p>}
      {apagando && (
        <Confirmar titulo={`Apagar o trabalho “${titulo}”?`}
                   texto={`Ele sai da lista e vai para a Lixeira.${entregue ? ' Este laudo já foi entregue.' : ''}`}
                   rotuloConfirmar="Apagar" perigo ocupado={ocupado} erro={erro}
                   aoConfirmar={() => void apagar()} aoCancelar={() => setApagando(false)} />
      )}
    </div>
  )
}
