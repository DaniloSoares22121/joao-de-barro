/* 138: o avaliador corrige direto no documento editável (cópia do Word do laudo, aberta no editor do PC) e depois usa
 * o documento como laudo: o JdB gera o PDF no padrão e roda só a conferência por regra (sem IA, sem remontar). */
import { useEffect, useState } from 'react'
import { FileEdit, FileCheck2 } from 'lucide-react'
import { ApiError, get, post } from './api'
import EditorLaudo, { abrirEditavel, canalEditor } from './EditorLaudo'

interface Estado { existe: boolean; arquivo?: string; alterado?: boolean; modificado_em?: string }
interface Diferenca { dado: string; pagina: string; encontrado: string; esperado: string; texto: string; do_avaliador?: boolean; sugestao?: string }
interface Uso { ok: boolean; pdf?: string; diferencas?: Diferenca[]; aviso?: string; bloqueia?: number; bloqueia_texto?: string }

export default function Editavel({ jobId, aoMudar, comBotaoUsar = false }: {
  jobId: string; aoMudar?: (m: string) => void
  comBotaoUsar?: boolean         // 143: na lista de erros o botão principal é o do rodapé (manda {tipo:'usar'} para cá)
}) {
  const j = encodeURIComponent(jobId)
  const [st, setSt] = useState<Estado | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [msg, setMsg] = useState('')
  const [uso, setUso] = useState<Uso | null>(null)
  const [editor, setEditor] = useState(false)          // o editor do próprio sistema (salva sozinho)

  async function ler() {
    try { setSt(await get<Estado>(`/jobs/${j}/editavel`)) } catch { /* sem o editável: botão continua */ }
  }
  useEffect(() => {
    void ler()
    const t = window.setInterval(() => { if (document.visibilityState === 'visible') void ler() }, 8000)
    return () => window.clearInterval(t)
  }, [j])            // eslint-disable-line react-hooks/exhaustive-deps

  // ORDEM 142: o editável abre numa ABA NOVA (a mesma aba no 2º toque); os cartões ficam aqui, no JdB
  function abrir() {
    setMsg('')
    const r = abrirEditavel(jobId)
    if (r === 'bloqueada') {               // o navegador barrou a aba: abre aqui mesmo, por cima
      setEditor(true)
      setMsg('O navegador não deixou abrir a aba nova. Abri o editor aqui; para liberar, permita janelas (pop-ups) deste endereço.')
      return
    }
    window.dispatchEvent(new CustomEvent('jdb-editavel-aberto'))
  }
  useEffect(() => {                        // a janela do editor pede "usar este documento": o PDF é gerado por aqui
    if (typeof BroadcastChannel === 'undefined') return undefined
    const c = new BroadcastChannel(canalEditor(jobId))
    c.onmessage = (ev) => {
      if ((ev.data as { tipo?: string } | null)?.tipo !== 'usar') return
      // 150: com duas abas do JdB abertas, só UMA gera o PDF (a mesma trava do SuaVez); as outras ficam quietas
      const travas = (navigator as Navigator & { locks?: { request: (n: string, o: { ifAvailable: boolean }, f: (l: unknown) => Promise<void>) => Promise<void> } }).locks
      if (!travas) { void usar(); return }
      void travas.request(`jdb-usar-${jobId}`, { ifAvailable: true }, async (trava) => { if (trava) await usar() })
    }
    return () => c.close()
  }, [jobId])        // eslint-disable-line react-hooks/exhaustive-deps
  async function usar() {
    setOcupado(true); setMsg(''); setUso(null)
    try {
      const r = await post<Uso>(`/jobs/${j}/editavel/usar`, {})
      setUso(r)
      const n = (r.diferencas ?? []).length
      const m = n ? `PDF novo pronto. A conferência achou ${n} ${n === 1 ? 'ponto' : 'pontos'} para você ver abaixo.`
        : 'PDF novo pronto, no padrão do laudo. A conferência não achou nada diferente.'
      setMsg(m); aoMudar?.(m); void ler()
      avisarAba({ ok: true, texto: r.bloqueia_texto || m, diferencas: n, bloqueia: r.bloqueia ?? 0, sem_mudanca: false })
    } catch (e) {
      const t = e instanceof ApiError ? e.message : 'Não consegui usar o documento.'
      setMsg(t)
      avisarAba({ ok: false, texto: t, diferencas: 0, bloqueia: 0, sem_mudanca: e instanceof ApiError && e.status === 409 && /não mudou nada/.test(t) })
    } finally { setOcupado(false) }
  }
  function avisarAba(r: { ok: boolean; texto: string; diferencas: number; bloqueia: number; sem_mudanca: boolean }) {
    // 150: só a aba que gerou o PDF recebe este evento local (é ela que passa à revisão humana)
    window.dispatchEvent(new CustomEvent('jdb-editavel-usado', { detail: { jobId, ...r } }))
    if (typeof BroadcastChannel === 'undefined') return       // a aba do editor e a lista de erros recebem o resultado
    const c = new BroadcastChannel(canalEditor(jobId)); c.postMessage({ tipo: 'usado', ...r }); c.close()
  }

  return (
    <div className="cartao-pad grid gap-2" style={{ border: '2px solid var(--barro, #a0522d)', borderRadius: 12 }}>
      <p className="titulo-cartao">Corrigir direto no documento</p>
      <p className="texto">Abra o laudo editável e corrija o que quiser: salva sozinho. Os cartões abaixo mostram onde está cada ponto.</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-verde" style={{ width: 'auto' }} disabled={ocupado} onClick={abrir}>
          <FileEdit size={20} aria-hidden="true" /> Abrir o laudo editável</button>
        {comBotaoUsar && <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} disabled={ocupado || !st?.existe}
                onClick={() => void usar()}>
          <FileCheck2 size={20} aria-hidden="true" /> Usar este documento como laudo</button>}
      </div>
      {st?.existe && <p className="small-jdb">{st.alterado ? 'O documento já tem mudanças suas, salvas.' : 'Documento ainda sem mudanças.'}</p>}
      {editor && <EditorLaudo jobId={jobId} aoFechar={() => { setEditor(false); void ler() }}
                              aoUsar={() => { setEditor(false); void usar() }} />}
      {msg && <p className="texto" role="status">{msg}</p>}
      {uso?.aviso && <p className="aviso-simples">{uso.aviso}</p>}
      {(uso?.diferencas ?? []).length > 0 && (
        <ol className="lista-simples">
          {uso!.diferencas!.map((d, i) => (
            <li key={i}><span><b>{d.pagina}</b> — {d.dado}: está «{d.encontrado}», o esperado é «{d.esperado}»{d.sugestao ? `. ${d.sugestao}` : ''}</span></li>
          ))}
        </ol>
      )}
    </div>
  )
}
