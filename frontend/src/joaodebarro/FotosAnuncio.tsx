/* ORDEM 173: a foto da tabela de amostras, sempre à mostra para escolher.
 * - As fotos coletadas do anúncio em miniaturas, abertas, com a escolhida marcada ("Esta vai na tabela"); um toque troca.
 * - [Colar print ou enviar foto]: Ctrl+V de uma imagem ou escolher um arquivo, com prévia e [Usar esta foto] / [Cancelar].
 *   A foto enviada vira a da tabela e fica marcada "foto enviada pelo avaliador". */
import { useEffect, useRef, useState } from 'react'
import { ImagePlus } from 'lucide-react'
import { ApiError, baixarRaw, post, postForm } from './api'

export interface FotoRef {
  n: number; foto?: string; fotos_url?: string[]; foto_url_escolhida?: string; foto_avaliador?: boolean; foto_arte?: boolean
}

export default function FotosAnuncio({ jobId, c, aoMudar, ocupado = false }: {
  jobId: string; c: FotoRef; aoMudar: (m: string) => void; ocupado?: boolean
}) {
  const j = encodeURIComponent(jobId)
  const [prev, setPrev] = useState<{ arq: File; url: string } | null>(null)
  const [minha, setMinha] = useState('')               // a foto enviada pelo avaliador (vem do servidor)
  const [msg, setMsg] = useState('')
  const [trab, setTrab] = useState(false)
  const arquivo = useRef<HTMLInputElement>(null)
  const urls = c.fotos_url ?? []
  const escolhida = c.foto_avaliador ? '' : (c.foto_url_escolhida || urls[0] || '')
  useEffect(() => {
    if (!c.foto_avaliador) { setMinha(''); return undefined }
    let u = ''
    baixarRaw(`/jobs/${j}/candidatos/${c.n}/foto`).then(({ blob }) => { u = URL.createObjectURL(blob); setMinha(u) }).catch(() => undefined)
    return () => { if (u) URL.revokeObjectURL(u) }
  }, [j, c.n, c.foto_avaliador, c.foto])
  useEffect(() => () => { if (prev) URL.revokeObjectURL(prev.url) }, [prev])

  async function trocar(u: string) {
    setMsg(''); setTrab(true)
    try { await post(`/jobs/${j}/candidatos/${c.n}/trocar-foto`, { url: u }); aoMudar(`Foto do anúncio ${c.n} trocada.`) }
    catch (e) { setMsg(e instanceof ApiError ? e.message : 'Não deu para trocar a foto.') } finally { setTrab(false) }
  }
  function preparar(f: File | undefined | null) {
    if (!f || !f.type.startsWith('image/')) { setMsg('Escolha ou cole uma imagem (JPG ou PNG).'); return }
    const nome = f.name && f.name !== 'image.png' ? f.name
      : `print-${new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '')}.${(f.type.split('/')[1] || 'png').replace('jpeg', 'jpg')}`
    const arq = new File([f], nome, { type: f.type })
    setMsg(''); setPrev({ arq, url: URL.createObjectURL(arq) })
  }
  async function usar() {
    if (!prev) return
    setTrab(true); setMsg('')
    try {
      const fd = new FormData(); fd.append('foto', prev.arq, prev.arq.name)
      await postForm(`/jobs/${j}/candidatos/${c.n}/foto-enviada`, fd)
      setPrev(null); aoMudar(`Foto enviada por você no anúncio ${c.n}: ela vai na tabela de amostras.`)
    } catch (e) { setMsg(e instanceof ApiError ? e.message : 'Não deu para usar a foto.') } finally { setTrab(false) }
  }
  const des = ocupado || trab
  return (
    <div className="grid gap-2" onPaste={(e) => {                 // Ctrl+V com o quadro em foco
      const img = Array.from(e.clipboardData?.files ?? []).find((f) => f.type.startsWith('image/'))
      if (img) { e.preventDefault(); preparar(img) }
    }}>
      <div className="flex flex-wrap gap-2" role="group" aria-label={`Fotos do anúncio ${c.n}`}>
        {urls.map((u, i) => {
          const sel = u === escolhida
          return (
            <button key={u} type="button" disabled={des || sel} className="foco grid justify-items-center gap-1"
                    aria-pressed={sel} aria-label={sel ? `Foto ${i + 1}: esta vai na tabela` : `Usar a foto ${i + 1} do anúncio`}
                    onClick={() => void trocar(u)}
                    style={{ border: sel ? '3px solid #14803F' : '1px solid #ddd', borderRadius: 10, padding: 2, background: '#fff' }}>
              <img src={u} alt={`Foto ${i + 1} do anúncio`} referrerPolicy="no-referrer"
                   style={{ width: 120, height: 90, objectFit: 'cover', borderRadius: 8 }} />
              {sel && <span className="small-jdb" style={{ color: '#14803F', fontWeight: 600 }}>Esta vai na tabela</span>}
            </button>
          )
        })}
        {c.foto_avaliador && (
          <div className="grid justify-items-center gap-1" style={{ border: '3px solid #14803F', borderRadius: 10, padding: 2 }}>
            {minha ? <img src={minha} alt="Foto enviada por você" style={{ width: 120, height: 90, objectFit: 'cover', borderRadius: 8 }} />
              : <span className="small-jdb" style={{ width: 120, height: 90, display: 'grid', placeItems: 'center' }}>Foto enviada</span>}
            <span className="small-jdb" style={{ color: '#14803F', fontWeight: 600 }}>Enviada por você · vai na tabela</span>
          </div>
        )}
      </div>
      {prev ? (
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Prévia da foto">
          <img src={prev.url} alt="Prévia da foto" style={{ maxHeight: 120, maxWidth: 200, borderRadius: 8, border: '1px solid #ddd' }} />
          <button type="button" className="btn-verde" style={{ width: 'auto' }} disabled={des} onClick={() => void usar()}>Usar esta foto</button>
          <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} disabled={des} onClick={() => setPrev(null)}>Cancelar</button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} disabled={des}
                  onClick={() => arquivo.current?.click()}>
            <ImagePlus size={20} aria-hidden="true" /> Colar print ou enviar foto</button>
          <span className="small-jdb">Copie um print (Ctrl+C) e cole aqui com Ctrl+V, ou escolha um arquivo.</span>
          <input ref={arquivo} type="file" accept="image/*" hidden onChange={(e) => { preparar(e.target.files?.[0]); e.target.value = '' }} />
        </div>
      )}
      {msg && <p className="aviso-impede" role="alert">{msg}</p>}
    </div>
  )
}
