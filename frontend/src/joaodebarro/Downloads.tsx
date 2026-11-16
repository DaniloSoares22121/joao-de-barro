/* ORDEM 166: downloads do laudo.
 * Antes do [✓ Aprovar]: só o PDF (nome com "(REVISÃO N)"). Depois do ✓: a caixa "Entrega" com PDF, Word, planilha e
 * "tudo" (.zip). O servidor decide o nome e barra o que ainda não pode (rota /jobs/{jid}/baixar/{tipo}). */
import { useState } from 'react'
import { Download, X } from 'lucide-react'
import { ApiError, baixarRaw, post } from './api'
import { salvarBlob } from './Entrega'

export type TipoBaixar = 'pdf' | 'docx' | 'xlsx' | 'tudo'

export async function baixarArquivo(jobId: string, tipo: TipoBaixar): Promise<void> {
  const { blob, nome } = await baixarRaw(`/jobs/${encodeURIComponent(jobId)}/baixar/${tipo}`)
  salvarBlob(blob, nome || `laudo.${tipo === 'tudo' ? 'zip' : tipo}`)
}

/** [Baixar PDF] — ao lado de [Abrir o PDF]. */
export function BotaoBaixarPdf({ jobId, className = 'btn-sec-grande' }: { jobId: string; className?: string }) {
  const [erro, setErro] = useState('')
  const [ocupado, setOcupado] = useState(false)
  async function baixar() {
    setErro(''); setOcupado(true)
    try { await baixarArquivo(jobId, 'pdf') } catch (e) { setErro(e instanceof ApiError ? e.message : 'Não deu para baixar o PDF.') }
    finally { setOcupado(false) }
  }
  return (
    <>
      <button type="button" className={className} disabled={ocupado} onClick={() => void baixar()}>
        <Download size={20} aria-hidden="true" /> {ocupado ? 'Baixando…' : 'Baixar PDF'}</button>
      {erro && <span className="aviso-impede" role="alert">{erro}</span>}
    </>
  )
}

const ITENS: { tipo: TipoBaixar; rotulo: string }[] = [
  { tipo: 'pdf', rotulo: 'Baixar PDF' }, { tipo: 'docx', rotulo: 'Baixar Word' },
  { tipo: 'xlsx', rotulo: 'Baixar planilha' }, { tipo: 'tudo', rotulo: 'Baixar tudo' },
]

/** 166-2: a caixa "Entrega" do laudo aprovado. */
export function CaixaEntrega({ jobId }: { jobId: string }) {
  const [erro, setErro] = useState('')
  const [ocupado, setOcupado] = useState<TipoBaixar | null>(null)
  async function baixar(t: TipoBaixar) {
    setErro(''); setOcupado(t)
    try { await baixarArquivo(jobId, t) } catch (e) { setErro(e instanceof ApiError ? e.message : 'Não deu para baixar.') }
    finally { setOcupado(null) }
  }
  return (
    <section className="cartao-pad grid gap-2" aria-labelledby={`entrega-${jobId}`}>
      <h3 id={`entrega-${jobId}`} className="titulo-cartao">Entrega</h3>
      <div className="flex flex-wrap gap-2">
        {ITENS.map((i) => (
          <button key={i.tipo} type="button" className={i.tipo === 'tudo' ? 'btn-verde' : 'btn-sec-grande'}
                  style={{ width: 'auto' }} disabled={!!ocupado} onClick={() => void baixar(i.tipo)}>
            <Download size={20} aria-hidden="true" /> {ocupado === i.tipo ? 'Baixando…' : i.rotulo}</button>
        ))}
      </div>
      <p className="small-jdb">Abra o Word no seu computador ou no seu Google Drive, faça as últimas mudanças e gere o PDF final de lá.
        O "Baixar tudo" junta os três num arquivo .zip.</p>
      {erro && <p className="aviso-impede" role="alert">{erro}</p>}
    </section>
  )
}

/** 166-3: o atalho do cartão do trabalho (lista) — ícone que abre a caixa "Entrega". */
export function AtalhoEntrega({ jobId, titulo }: { jobId: string; titulo: string }) {
  const [aberto, setAberto] = useState(false)
  return (
    <>
      <button type="button" className="btn-sec btn-peq" aria-label={`Baixar os arquivos do laudo: ${titulo}`}
              onClick={(e) => { e.stopPropagation(); setAberto(true) }}>
        <Download size={18} aria-hidden="true" /> Baixar</button>
      {aberto && (
        <div role="dialog" aria-modal="true" aria-label="Entrega do laudo"
             style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.45)', zIndex: 50, display: 'flex',
                      alignItems: 'center', justifyContent: 'center', padding: 16 }}
             onClick={(e) => { e.stopPropagation(); setAberto(false) }}
             onKeyDown={(e) => { if (e.key === 'Escape') setAberto(false) }}>
          <div style={{ background: '#fff', borderRadius: 16, maxWidth: 640, width: '100%', padding: 8 }}
               onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-end">
              <button type="button" className="btn-sec btn-peq" onClick={() => setAberto(false)}>
                <X size={18} aria-hidden="true" /> Fechar</button>
            </div>
            <CaixaEntrega jobId={jobId} />
          </div>
        </div>
      )}
    </>
  )
}

/** 172-2: [Baixar para a revisão humana] — conclui o laudo (✓) e baixa o Word; a revisão final é no Word do avaliador. */
export function BaixarRevisao({ jobId, aoConcluir, compacto = false }: { jobId: string; aoConcluir?: (m: string) => void; compacto?: boolean }) {
  const [erro, setErro] = useState('')
  const [ocupado, setOcupado] = useState(false)
  async function baixar() {
    setErro(''); setOcupado(true)
    try {
      await post(`/jobs/${encodeURIComponent(jobId)}/concluir`, {})
      await baixarArquivo(jobId, 'docx')
      aoConcluir?.('Laudo concluído ✓. O Word foi baixado: faça as últimas mudanças nele e gere o PDF final de lá.')
    } catch (e) { setErro(e instanceof ApiError ? e.message : 'Não deu para baixar agora. Tente de novo.') }
    finally { setOcupado(false) }
  }
  const botao = (
    <button type="button" className="btn-verde" style={{ width: 'auto', fontSize: compacto ? undefined : 20 }} disabled={ocupado}
            onClick={() => void baixar()}>
      <Download size={22} aria-hidden="true" /> {ocupado ? 'Baixando…' : 'Baixar para a revisão humana'}</button>
  )
  if (compacto) return <>{botao}{erro && <span className="aviso-impede" role="alert">{erro}</span>}</>
  return (
    <section className="cartao-pad grid gap-2" aria-label="Baixar para a revisão humana">
      <div className="flex flex-wrap gap-2">{botao}</div>
      <p className="texto">Ao baixar, o laudo fica <b>concluído ✓</b>. Abra o Word no seu computador ou no seu Google Drive,
        faça as últimas mudanças (use os pontos abaixo com Ctrl+F) e gere o PDF final de lá.</p>
      {erro && <p className="aviso-impede" role="alert">{erro}</p>}
    </section>
  )
}
