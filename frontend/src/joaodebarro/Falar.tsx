/* 119-2: [🎤 Falar] em todo campo aberto para digitação. A fala é escrita no próprio PC (custo zero; o áudio não
 * sai do computador) e entra onde está o cursor — nada é enviado sozinho. Um componente só para todas as telas. */
import { useEffect, useRef, useState, type ReactNode, type TextareaHTMLAttributes } from 'react'
import { Mic, Pencil, Square } from 'lucide-react'
import { ApiError, postForm } from './api'

/** Grava pelo microfone e devolve o texto falado (POST /falar). */
export function useFalar(aoTexto: (texto: string) => void, rota = '/falar') {
  const [gravando, setGravando] = useState(false)
  const [segundos, setSegundos] = useState(0)
  const [ouvindo, setOuvindo] = useState(false)
  const [erro, setErro] = useState('')
  const rec = useRef<MediaRecorder | null>(null)
  const pedacos = useRef<Blob[]>([])
  const inicio = useRef(0)

  useEffect(() => {                              // o tempo continua com a aba em segundo plano (conta pelo relógio)
    if (!gravando) return
    const t = window.setInterval(() => setSegundos(Math.floor((Date.now() - inicio.current) / 1000)), 500)
    return () => window.clearInterval(t)
  }, [gravando])
  useEffect(() => () => rec.current?.stream.getTracks().forEach((x) => x.stop()), [])

  async function ouvir(blob: Blob) {
    const fd = new FormData(); fd.append('audio', blob, 'fala.webm')
    setOuvindo(true); setErro('')
    try {
      const r = await postForm<{ texto: string }>(rota, fd)
      if (!r.texto.trim()) setErro('Não ouvi fala. Tente de novo, mais perto do microfone.')
      else aoTexto(r.texto.trim())
    } catch (e) {
      setErro(e instanceof ApiError ? e.detail || 'Não consegui escrever o que você falou.' : 'Não consegui escrever o que você falou.')
    } finally { setOuvindo(false) }
  }

  async function alternar() {
    if (gravando) { rec.current?.stop(); return }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const r = new MediaRecorder(stream)
      pedacos.current = []
      r.ondataavailable = (e) => { if (e.data.size) pedacos.current.push(e.data) }
      r.onstop = () => {
        stream.getTracks().forEach((x) => x.stop())
        setGravando(false)
        void ouvir(new Blob(pedacos.current, { type: r.mimeType || 'audio/webm' }))
      }
      r.start(1000)
      rec.current = r
      inicio.current = Date.now(); setSegundos(0); setGravando(true); setErro('')
    } catch {
      setErro('O navegador não liberou o microfone. Libere o microfone para este site e tente de novo.')
    }
  }
  return { gravando, segundos, ouvindo, erro, alternar, ouvir }
}

export function tempo(s: number): string {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** O botão [🎤 Falar] / [■ Parar]. */
export function BotaoFalar({ f, rotulo = true, desligado = false }: {
  f: ReturnType<typeof useFalar>; rotulo?: boolean; desligado?: boolean
}) {
  return (
    <button type="button" className={f.gravando ? 'btn-verde' : 'btn-sec-grande'} style={{ width: 'auto' }}
            disabled={desligado || f.ouvindo} onClick={() => void f.alternar()} aria-pressed={f.gravando}
            aria-label={f.gravando ? 'Parar de gravar' : 'Falar em vez de digitar'}>
      {f.gravando ? <><Square size={20} aria-hidden="true" />{rotulo && ' Parar'}</> : <><Mic size={20} aria-hidden="true" />{rotulo && ' Falar'}</>}
    </button>
  )
}

/** "● Gravando 0:12" / "Escrevendo o que você falou…" / erro do microfone. */
export function EstadoFalar({ f }: { f: ReturnType<typeof useFalar> }) {
  if (f.gravando) return <p className="aviso-impede" role="status">● Gravando {tempo(f.segundos)} — fale e toque em Parar no fim.</p>
  if (f.ouvindo) return <p className="texto" role="status">Escrevendo o que você falou… (no seu computador, sem custo)</p>
  if (f.erro) return <p className="small-jdb" role="alert">{f.erro}</p>
  return null
}

/** Põe o texto no lugar do cursor (ou no fim). */
export function inserirNoCursor(atual: string, el: HTMLTextAreaElement | HTMLInputElement | null, falado: string): string {
  const pos = el?.selectionStart ?? atual.length
  const antes = atual.slice(0, pos), depois = atual.slice(pos)
  const sep = antes && !/\s$/.test(antes) ? ' ' : ''
  return antes + sep + falado + (depois && !/^\s/.test(depois) ? ' ' : '') + depois
}

/** 119-1/2: campo de texto aberto, grande, com borda, rótulo, ícone de lápis e o [🎤 Falar] (D-101). */
export function CampoTexto({ rotulo, valor, aoMudar, id, linhas = 3, acoes, ...resto }: {
  rotulo: string; valor: string; aoMudar: (v: string) => void; id: string; linhas?: number; acoes?: ReactNode
} & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'value' | 'onChange' | 'id'>) {
  const caixa = useRef<HTMLTextAreaElement>(null)
  const f = useFalar((t) => aoMudar(inserirNoCursor(valor, caixa.current, t)))
  useEffect(() => {                              // cresce com o texto
    const el = caixa.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight + 2}px`
  }, [valor])
  return (
    <div className="grid gap-2" style={{ width: '100%' }}>
      <label htmlFor={id} className="texto inline-flex items-center gap-2" style={{ fontWeight: 600 }}>
        <Pencil size={20} aria-hidden="true" /> {rotulo}
      </label>
      <div className="flex flex-wrap items-start gap-2" style={{ width: '100%' }}>
        <textarea id={id} ref={caixa} className="caixa-l2" rows={linhas} value={valor}
                  onChange={(e) => aoMudar(e.target.value)}
                  style={{ flex: '1 1 320px', minHeight: `${linhas * 1.6}em`, resize: 'none', overflow: 'hidden',
                           border: '2px solid var(--barro, #a0522d)', background: '#fffdf8' }} {...resto} />
        <div className="flex flex-wrap gap-2">
          <BotaoFalar f={f} />
          {acoes}
        </div>
      </div>
      <EstadoFalar f={f} />
    </div>
  )
}

/** 119-2: o [🎤 Falar] ao lado de um campo que já existe (pelo id): o texto falado entra onde está o cursor dele. */
export function FalarAqui({ alvo, valor, aoMudar, rotulo = true }: {
  alvo: string; valor: string; aoMudar: (v: string) => void; rotulo?: boolean
}) {
  const f = useFalar((t) => {
    const el = document.getElementById(alvo) as HTMLTextAreaElement | HTMLInputElement | null
    aoMudar(inserirNoCursor(valor, el, t))
  })
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <BotaoFalar f={f} rotulo={rotulo} />
      <EstadoFalar f={f} />
    </span>
  )
}
