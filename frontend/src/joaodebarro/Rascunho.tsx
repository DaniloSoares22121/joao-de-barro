/** ORDEM 065: a proposta e o contrato de verdade ANTES de aprovar (D-091). O rascunho é o mesmo
 * documento que sai depois de aprovar; a miniatura é a 1ª página real e [Ver a proposta] abre o
 * documento inteiro por cima da tela, com o Aprovar fixo embaixo. */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Download, ExternalLink, X } from 'lucide-react'
import { ApiError, baixarRaw, post } from './api'
import { salvarBlob } from './Entrega'

export interface MetaRascunho { numero: string; valor: string; pdf: string; docx: string; capa: string }
type Qual = 'proposta' | 'contrato'

/** Gera (ou reaproveita) o rascunho quando `ativo`; refaz quando `versao` muda (dados do cliente mudaram). */
export function useRascunho(cid: string | null, qual: Qual, ativo: boolean, versao: string) {
  const [meta, setMeta] = useState<MetaRascunho | null>(null)
  const [erro, setErro] = useState('')
  const [carregando, setCarregando] = useState(false)
  useEffect(() => {
    if (!cid || !ativo) { setMeta(null); setErro(''); return }
    let vivo = true
    setCarregando(true); setErro('')
    post<MetaRascunho>(`/clientes/${encodeURIComponent(cid)}/rascunho/${qual}`)
      .then((m) => { if (vivo) setMeta(m) })
      .catch((e) => { if (vivo) setErro(e instanceof ApiError ? textoErro(e.message) : 'Não consegui montar o rascunho.') })
      .finally(() => { if (vivo) setCarregando(false) })
    return () => { vivo = false }
  }, [cid, qual, ativo, versao])
  return { meta, erro, carregando }
}

const textoErro = (m: string) => (m.startsWith('falta: ') ? `Falta ${m.slice(7)}.` : m.charAt(0).toUpperCase() + m.slice(1))

function useArquivo(cid: string, qual: Qual, nome: string | undefined) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    if (!nome) { setUrl(''); return }
    let u = ''
    let vivo = true
    baixarRaw(`/clientes/${encodeURIComponent(cid)}/rascunho/${qual}/${encodeURIComponent(nome)}`)
      .then(({ blob }) => { if (vivo) { u = URL.createObjectURL(blob); setUrl(u) } }).catch(() => undefined)
    return () => { vivo = false; if (u) URL.revokeObjectURL(u) }
  }, [cid, qual, nome])
  return url
}

export function Miniatura({ cid, qual, meta, carregando, erro, aoAbrir }: {
  cid: string; qual: Qual; meta: MetaRascunho | null; carregando: boolean; erro: string; aoAbrir: () => void
}) {
  const url = useArquivo(cid, qual, meta?.capa)
  if (erro) return <p className="aviso-impede">{erro}</p>
  if (carregando && !meta) return <p className="small-jdb" role="status">Montando o rascunho da {qual}…</p>
  if (!meta) return null
  return (
    <button type="button" className="miniatura-065" onClick={aoAbrir} aria-label={`Ver a ${qual} inteira`}>
      {url ? <img src={url} alt={`1ª página da ${qual} nº ${meta.numero}`} /> : <span className="small-jdb">1ª página</span>}
      <span className="small-jdb">{qual === 'proposta' ? 'Proposta' : 'Contrato'} nº {meta.numero} · rascunho</span>
    </button>
  )
}

export function PainelDocumento({ cid, qual, meta, aprovar, ocupado, erro, aoFechar }: {
  cid: string; qual: Qual; meta: MetaRascunho | null
  aprovar?: { rotulo: string; acao: () => void }; ocupado: boolean; erro?: string; aoFechar: () => void
}) {
  const pdf = useArquivo(cid, qual, meta?.pdf)
  const [aviso, setAviso] = useState('')
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Escape') aoFechar() }
    document.addEventListener('keydown', tecla)
    return () => document.removeEventListener('keydown', tecla)
  }, [aoFechar])
  async function baixar(nome: string) {
    try {
      const { blob } = await baixarRaw(`/clientes/${encodeURIComponent(cid)}/rascunho/${qual}/${encodeURIComponent(nome)}`)
      salvarBlob(blob, `Rascunho - ${nome}`)
      setAviso('✓ Rascunho baixado.')
    } catch { setAviso('Não deu para baixar. Tente de novo.') }
  }
  const titulo = `${qual === 'proposta' ? 'A proposta' : 'O contrato'}${meta ? ` nº ${meta.numero}` : ''} · rascunho`
  return createPortal(
    <div className="painel-l13-fundo" onMouseDown={(e) => { if (e.target === e.currentTarget) aoFechar() }}>
      <section className="painel-conversa painel-doc-065" role="dialog" aria-modal="true" aria-label={titulo}>
        <div className="painel-conversa-topo">
          <h2 className="titulo-sub-l13">{titulo}</h2>
          <button type="button" className="btn-opcoes" onClick={aoFechar} autoFocus><X size={20} aria-hidden="true" /> Fechar</button>
        </div>
        <div className="doc-065">
          {!meta ? <p className="small-jdb" role="status">Montando o rascunho…</p>
            : pdf ? <iframe title={titulo} src={pdf} className="pdf-065" />
            : meta.pdf ? <p className="small-jdb" role="status">Abrindo o documento…</p>
            : <p className="texto">O PDF não ficou pronto neste computador. Baixe o Word para ver.</p>}
        </div>
        <div className="rodape-065">
          <div className="botoes">
            {meta?.pdf && <button type="button" className="btn-sec-grande" onClick={() => void baixar(meta.pdf)}><Download size={20} aria-hidden="true" /> Baixar rascunho em PDF</button>}
            {!meta?.pdf && meta?.docx && <button type="button" className="btn-sec-grande" onClick={() => void baixar(meta.docx)}><Download size={20} aria-hidden="true" /> Baixar rascunho em Word</button>}
            {pdf && <a className="btn-sec-grande" href={pdf} target="_blank" rel="noopener"><ExternalLink size={20} aria-hidden="true" /> Abrir em tela cheia</a>}
          </div>
          {(aviso || erro) && <p className={erro ? 'aviso-impede' : 'small-jdb'} role="status">{erro || aviso}</p>}
          {aprovar && <button type="button" className="btn-verde w-full" disabled={ocupado || !meta} onClick={aprovar.acao}>{ocupado ? 'Aguarde…' : aprovar.rotulo}</button>}
        </div>
      </section>
    </div>,
    document.body,
  )
}
