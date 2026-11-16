/* ORDEM 172-3: as imagens do laudo.
 * - ImagensAprovar: na escolha dos referenciais (antes de montar), o mapa da localização e a capa (fachada demarcada)
 *   como vão entrar no laudo, com [Ajustar a demarcação], [Refazer o mapa] e [Aprovar a imagem]. O contorno ajustado
 *   aqui é o que a montagem usa.
 * - ImagensDoLaudo: a seção "Imagens do laudo" dos Detalhes, com a orientação para editar no programa preferido e
 *   [Baixar a imagem] em cada uma. */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Download } from 'lucide-react'
import { ApiError, baixarRaw, get, post } from './api'
import Demarcacao from './Demarcacao'

type Qual = 'mapa' | 'capa'
interface Uma { existe: boolean; motivo?: string; do_avaliador?: boolean; sem_contorno?: boolean; aprovada_em?: string | null; v?: string }
type Estado = Record<Qual, Uma>
const NOME: Record<Qual, string> = { mapa: 'Mapa da localização', capa: 'Capa — foto da fachada' }

function Previa({ jobId, qual, v }: { jobId: string; qual: Qual; v?: string }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let vivo = true; let u = ''
    baixarRaw(`/jobs/${encodeURIComponent(jobId)}/imagens-laudo/${qual}/imagem?demarcada=1&v=${v ?? ''}`)
      .then((r) => { if (vivo) { u = URL.createObjectURL(r.blob); setUrl(u) } }).catch(() => undefined)
    return () => { vivo = false; if (u) URL.revokeObjectURL(u) }
  }, [jobId, qual, v])
  return url ? <img src={url} alt={`${NOME[qual]}, como vai entrar no laudo`} style={{ display: 'block', width: '100%', maxWidth: 520, borderRadius: 8, border: '1px solid #d5dbe3' }} />
    : <div style={{ width: '100%', maxWidth: 520, aspectRatio: '3 / 2', background: '#eef1f5', borderRadius: 8 }} />
}

export function ImagensAprovar({ jobId }: { jobId: string }) {
  const j = encodeURIComponent(jobId)
  const [st, setSt] = useState<Estado | null>(null)
  const [msg, setMsg] = useState('')
  const [ocupado, setOcupado] = useState<string>('')
  const [desenhar, setDesenhar] = useState<Qual | null>(null)
  const ler = useCallback(async () => {
    try { setSt(await get<Estado>(`/jobs/${j}/imagens-laudo`)) } catch (e) { setMsg(e instanceof ApiError ? e.message : 'Não consegui preparar as imagens.') }
  }, [j])
  useEffect(() => { void ler() }, [ler])
  async function agir(chave: string, f: () => Promise<string>) {
    setOcupado(chave); setMsg('')
    try { setMsg(await f()); await ler() } catch (e) { setMsg(e instanceof ApiError ? e.message : 'Não deu certo. Tente de novo.') }
    finally { setOcupado('') }
  }
  if (!st) {
    return (
      <div className="cartao-pad grid gap-2">
        <p className="texto" role="status">{msg || 'Preparando o mapa e a capa para você aprovar…'}</p>
        {msg && <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} onClick={() => { setMsg(''); void ler() }}>
          Tentar de novo</button>}
      </div>
    )
  }
  return (
    <section className="cartao-pad grid gap-3" aria-labelledby="img-aprovar" style={{ border: '2px solid #18283B', borderRadius: 12 }}>
      <div>
        <h2 id="img-aprovar" className="titulo-cartao">Imagens do laudo: aprove antes de montar</h2>
        <p className="small-jdb">É a hora certa de mexer na demarcação: o que você ajustar aqui é o que entra no laudo.</p>
      </div>
      {(['mapa', 'capa'] as Qual[]).map((q) => {
        const u = st[q]
        return (
          <div key={q} className="grid gap-2">
            <p className="texto" style={{ fontWeight: 700, margin: 0 }}>{NOME[q]}
              {u.aprovada_em && <span style={{ color: '#1f7a3a', marginLeft: 8 }}>✓ Aprovada às {u.aprovada_em}</span>}</p>
            {u.existe ? <>
              <Previa jobId={jobId} qual={q} v={u.v} />
              {u.do_avaliador && <p className="small-jdb" style={{ margin: 0 }}>Contorno desenhado por você.</p>}
              {u.sem_contorno && <p className="small-jdb" style={{ margin: 0 }}>Sem contorno automático: desenhe em [Ajustar a demarcação].</p>}
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} disabled={!!ocupado} onClick={() => setDesenhar(q)}>
                  Ajustar a demarcação</button>
                {q === 'mapa' && (
                  <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} disabled={!!ocupado}
                          onClick={() => void agir('refazer', async () => {
                            const r = await post<{ ok: boolean; motivo: string }>(`/jobs/${j}/imagens-laudo/mapa/refazer`, {})
                            return r.ok ? `Mapa refeito: ${r.motivo}. Confira e aprove.` : r.motivo
                          })}>{ocupado === 'refazer' ? 'Refazendo o mapa… (até 1 minuto)' : 'Refazer o mapa'}</button>)}
                <button type="button" className="btn-verde" style={{ width: 'auto' }} disabled={!!ocupado || !!u.aprovada_em}
                        onClick={() => void agir('aprovar' + q, async () => { await post(`/jobs/${j}/imagens-laudo/${q}/aprovar`, {}); return `${NOME[q]} aprovada.` })}>
                  {u.aprovada_em ? '✓ Aprovada' : 'Aprovar a imagem'}</button>
              </div>
            </> : <>
              <p className="aviso-simples" style={{ margin: 0 }}>{u.motivo}</p>
              {q === 'mapa' && (
                <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} disabled={!!ocupado}
                        onClick={() => void agir('refazer', async () => {
                          const r = await post<{ ok: boolean; motivo: string }>(`/jobs/${j}/imagens-laudo/mapa/refazer`, {})
                          return r.ok ? `Mapa refeito: ${r.motivo}. Confira e aprove.` : r.motivo
                        })}>{ocupado === 'refazer' ? 'Refazendo o mapa… (até 1 minuto)' : 'Refazer o mapa'}</button>)}
            </>}
          </div>
        )
      })}
      {msg && <p className="texto" role="status" style={{ margin: 0 }}>{msg}</p>}
      {desenhar && <Demarcacao jobId={jobId} qual={desenhar} base="imagens-laudo" aoFechar={() => setDesenhar(null)}
                               aoSalvar={() => { const q = desenhar; setDesenhar(null); setMsg(`Demarcação ${q === 'mapa' ? 'do mapa' : 'da capa'} salva. Confira e aprove.`); void ler() }} />}
    </section>
  )
}

interface Item { id: string; rotulo: string; arquivo: string; nova?: boolean }

/** 182: miniatura leve (o servidor manda reduzida); carrega só quando aparece na tela */
function Miniatura({ jobId, id, rotulo, aoAbrir }: { jobId: string; id: string; rotulo: string; aoAbrir: () => void }) {
  const [url, setUrl] = useState('')
  const caixa = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    let vivo = true; let u = ''
    const pedir = () => baixarRaw(`/jobs/${encodeURIComponent(jobId)}/imagens-laudo/miniatura/${encodeURIComponent(id)}?lado=160`)
      .then((r) => { if (vivo) { u = URL.createObjectURL(r.blob); setUrl(u) } }).catch(() => undefined)
    const el = caixa.current
    if (!el || typeof IntersectionObserver === 'undefined') void pedir()
    else {
      const o = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { o.disconnect(); void pedir() } }, { rootMargin: '400px' })
      o.observe(el)
      return () => { vivo = false; o.disconnect(); if (u) URL.revokeObjectURL(u) }
    }
    return () => { vivo = false; if (u) URL.revokeObjectURL(u) }
  }, [jobId, id])
  return (
    <button ref={caixa} type="button" onClick={aoAbrir} title={`Abrir “${rotulo}” numa aba nova`} aria-label={`Abrir ${rotulo} numa aba nova`}
            style={{ width: 96, height: 72, flex: '0 0 96px', borderRadius: 8, border: '1px solid #d5dbe3', background: '#eef1f5', padding: 0,
                     overflow: 'hidden', cursor: 'zoom-in' }}>
      {url && <img src={url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />}
    </button>
  )
}

export function ImagensDoLaudo({ jobId }: { jobId: string }) {
  const j = encodeURIComponent(jobId)
  const [lista, setLista] = useState<Item[] | null>(null)
  const [msg, setMsg] = useState('')
  useEffect(() => { get<Item[]>(`/jobs/${j}/imagens-laudo/lista`).then(setLista).catch(() => setLista([])) }, [j])
  async function pegar(it: Item) {
    return baixarRaw(`/jobs/${j}/imagens-laudo/baixar/${encodeURIComponent(it.id)}`)
  }
  async function baixar(it: Item) {
    setMsg('')
    try {
      const r = await pegar(it)
      const a = document.createElement('a')
      a.href = URL.createObjectURL(r.blob); a.download = r.nome || it.arquivo
      document.body.appendChild(a); a.click(); a.remove()
      window.setTimeout(() => URL.revokeObjectURL(a.href), 30000)
    } catch (e) { setMsg(e instanceof ApiError ? e.message : 'Não consegui baixar a imagem.') }
  }
  /** 182-1: a imagem grande numa aba nova (a mesma do laudo); a aba abre já no toque, o navegador não bloqueia */
  async function abrir(it: Item) {
    setMsg('')
    const aba = window.open('', '_blank')
    try {
      const r = await pegar(it)
      const u = URL.createObjectURL(r.blob)
      if (aba) aba.location.href = u
      else window.open(u, '_blank')
      window.setTimeout(() => URL.revokeObjectURL(u), 120000)
    } catch (e) {
      aba?.close()
      setMsg(e instanceof ApiError ? e.message : 'Não consegui abrir a imagem.')
    }
  }
  return (
    <div className="grid gap-2">
      <p className="texto" style={{ margin: 0 }}>Se quiser editar alguma imagem, edite no seu programa de preferência e troque no Word quando baixar para a revisão humana.</p>
      {lista === null ? <p className="small-jdb">Carregando…</p> : lista.length === 0 ? <p className="small-jdb">Ainda não há imagens do laudo.</p> : (
        <ul className="lista-simples">
          {lista.map((it) => (
            <li key={it.id} style={{ display: 'flex', alignItems: 'center', gap: 12, justifyContent: 'space-between', flexWrap: 'wrap' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0, flex: '1 1 260px' }}>
                <Miniatura jobId={jobId} id={it.id} rotulo={it.rotulo} aoAbrir={() => void abrir(it)} />
                <button type="button" className="texto" onClick={() => void abrir(it)}
                        style={{ background: 'none', border: 0, padding: 0, textAlign: 'left', cursor: 'pointer', textDecoration: 'underline',
                                 textUnderlineOffset: 3, color: it.nova ? '#8a5a00' : 'inherit', fontFamily: 'inherit' }}>
                  {it.rotulo}</button>
              </span>
              <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} onClick={() => void baixar(it)}>
                <Download size={18} aria-hidden="true" /> Baixar a imagem</button>
            </li>))}
        </ul>)}
      {msg && <p className="aviso-simples" role="status">{msg}</p>}
    </div>
  )
}
