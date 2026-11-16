/* "Conferir tarjas": o avaliador confere/ajusta as tarjas pretas dos documentos do solicitante
 * (só os números ficam cobertos). Caixas em pixels da imagem real; na tela, em % do tamanho exibido. */
import Confirmar from './Confirmar'
import { useCallback, useEffect, useRef, useState, type PointerEvent as PEv } from 'react'
import { ChevronDown, X } from 'lucide-react'
import { ApiError, baixarRaw, get, put } from './api'
import { ehAuth, mensagemErro } from './Envio'

export interface DocTarja {
  arquivo: string
  nome: string
  largura: number
  altura: number
  imagem: boolean
  /** Página de PDF: endereço da página já convertida em imagem. */
  url?: string
  /** [x0, y0, x1, y1] em pixels da imagem. */
  caixas: number[][]
  conferido: boolean
}

type Caixa = [number, number, number, number]
interface Arrasto { modo: 'mover' | 'canto' | 'desenhar'; i: number; canto: number; x0: number; y0: number; orig: Caixa }

export const AJUDA_TARJAS = 'Tarje só os NÚMEROS (CPF, RG, registro da CNH, inscrição da OAB, data de nascimento). '
  + 'Nome, filiação e foto ficam visíveis — eles comprovam o vínculo com o proprietário.'

/** Caixa desenhada menor que isso (px da imagem) é descartada (clique sem arrastar). */
const MIN_PX = 4
const clamp = (v: number, a: number, b: number) => Math.min(Math.max(v, a), b)
const pct = (v: number, total: number) => `${(v / total) * 100}%`
const caminho = (arq: string) => arq.split('/').map(encodeURIComponent).join('/')
const copia = (cs: number[][]): Caixa[] => cs.filter((c) => c.length >= 4).map((c) => [c[0], c[1], c[2], c[3]])

function erroTxt(e: unknown): string {
  if (e instanceof ApiError && e.status === 409 && /execu/i.test(e.detail)) return 'O trabalho está em execução; aguarde terminar.'
  return mensagemErro(e)
}

function EditorTarja({ jobId, doc, livre, aoSalvo }: {
  jobId: string; doc: DocTarja; livre: boolean; aoSalvo: () => void
}) {
  const [caixas, setCaixas] = useState<Caixa[]>(() => copia(doc.caixas))
  const [url, setUrl] = useState<string | null>(null)
  const [erroImg, setErroImg] = useState('')
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null)
  const [desenhar, setDesenhar] = useState(false)
  const [alterado, setAlterado] = useState(false)
  const [salvando, setSalvando] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; texto: string } | null>(null)
  const [apagarIdx, setApagarIdx] = useState<number | null>(null)     // 183: apagar tarja pede confirmação
  const area = useRef<HTMLDivElement>(null)
  const arrasto = useRef<Arrasto | null>(null)
  const L = doc.largura || nat?.w || 0
  const A = doc.altura || nat?.h || 0
  const editavel = livre && !salvando && L > 0 && A > 0

  useEffect(() => {
    if (!doc.imagem) return
    let vivo = true
    let u = ''
    setUrl(null)
    setErroImg('')
    baixarRaw(doc.url || `/jobs/${encodeURIComponent(jobId)}/arquivo/${caminho(doc.arquivo)}`).then(({ blob }) => {
      if (!vivo) return
      u = URL.createObjectURL(blob)
      setUrl(u)
    }).catch((e) => { if (vivo && !ehAuth(e)) setErroImg('Não foi possível carregar a imagem do documento.') })
    return () => { vivo = false; if (u) URL.revokeObjectURL(u) }
  }, [jobId, doc.arquivo, doc.imagem, doc.url])

  /** Ponto da tela → pixels da imagem real. */
  function paraImagem(e: { clientX: number; clientY: number }) {
    const r = area.current!.getBoundingClientRect()
    return {
      x: clamp(((e.clientX - r.left) / Math.max(1, r.width)) * L, 0, L),
      y: clamp(((e.clientY - r.top) / Math.max(1, r.height)) * A, 0, A),
    }
  }

  function iniciar(e: PEv<HTMLElement>, modo: Arrasto['modo'], i: number, canto = -1) {
    if (!editavel || !area.current) return
    if (e.pointerType === 'mouse' && e.button !== 0) return
    e.preventDefault()
    e.stopPropagation()
    const p = paraImagem(e)
    let idx = i
    let orig: Caixa = caixas[i]
    if (modo === 'desenhar') {
      idx = caixas.length
      orig = [p.x, p.y, p.x, p.y]
      setCaixas((cs) => [...cs, orig])
    }
    arrasto.current = { modo, i: idx, canto, x0: p.x, y0: p.y, orig }
    try { area.current.setPointerCapture(e.pointerId) } catch { /* sem captura: segue sem */ }
  }

  function mover(e: PEv<HTMLDivElement>) {
    const a = arrasto.current
    if (!a) return
    const p = paraImagem(e)
    const [x0, y0, x1, y1] = a.orig
    let nova: Caixa
    if (a.modo === 'mover') {
      const dx = clamp(p.x - a.x0, -x0, L - x1)
      const dy = clamp(p.y - a.y0, -y0, A - y1)
      nova = [x0 + dx, y0 + dy, x1 + dx, y1 + dy]
    } else {
      // Desenhar: o ponto inicial fica fixo. Canto (0 ↖, 1 ↗, 2 ↙, 3 ↘): fixo é o canto oposto.
      const fx = a.modo === 'desenhar' ? a.x0 : (a.canto === 0 || a.canto === 2 ? x1 : x0)
      const fy = a.modo === 'desenhar' ? a.y0 : (a.canto === 0 || a.canto === 1 ? y1 : y0)
      nova = [Math.min(fx, p.x), Math.min(fy, p.y), Math.max(fx, p.x), Math.max(fy, p.y)]
    }
    setCaixas((cs) => cs.map((c, j) => (j === a.i ? nova : c)))
    setAlterado(true)
  }

  function soltar(e: PEv<HTMLDivElement>) {
    const a = arrasto.current
    if (!a) return
    arrasto.current = null
    try { area.current?.releasePointerCapture(e.pointerId) } catch { /* já liberado */ }
    if (a.modo === 'desenhar') {
      setCaixas((cs) => cs.filter((c, j) => j !== a.i || (c[2] - c[0] >= MIN_PX && c[3] - c[1] >= MIN_PX)))
      setDesenhar(false)
    }
  }

  function apagar(i: number) {
    setCaixas((cs) => cs.filter((_, j) => j !== i))
    setAlterado(true)
    setMsg(null)
  }

  function desfazer() {
    setCaixas(copia(doc.caixas))
    setAlterado(false)
    setDesenhar(false)
    setMsg(null)
  }

  async function salvar() {
    setSalvando(true)
    setMsg(null)
    try {
      await put(`/jobs/${encodeURIComponent(jobId)}/tarjas`, {
        arquivo: doc.arquivo,
        caixas: caixas.map((c) => c.map((v) => Math.round(v))),
      })
      setAlterado(false)
      setMsg({ ok: true, texto: 'Tarjas salvas.' })
      aoSalvo()
    } catch (e) {
      if (!ehAuth(e)) setMsg({ ok: false, texto: erroTxt(e) })
    } finally {
      setSalvando(false)
    }
  }

  return (
    <div className="space-y-2" data-arquivo={doc.arquivo}>
      {apagarIdx !== null && (
        <Confirmar titulo={`Apagar a tarja ${apagarIdx + 1}?`}
                   texto="O que ela cobre volta a aparecer neste documento. Antes de salvar, dá para desfazer."
                   rotuloConfirmar="Apagar" perigo
                   aoConfirmar={() => { apagar(apagarIdx); setApagarIdx(null) }} aoCancelar={() => setApagarIdx(null)} />
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="min-w-0 break-words text-sm font-medium text-stone-800">{doc.nome || doc.arquivo}</p>
        {doc.conferido && !alterado
          ? <span className="chip bg-emerald-50 text-emerald-800 ring-emerald-600/20">Conferido ✓</span>
          : doc.imagem && <span className="chip bg-amber-50 text-amber-800 ring-amber-600/25">A conferir</span>}
      </div>
      {!doc.imagem && <p className="text-sm text-stone-500">Prévia disponível só para imagens.</p>}
      {doc.imagem && (
        <>
          {erroImg && <p className="erro-txt" role="alert">{erroImg}</p>}
          {!url && !erroImg && <p className="text-sm text-stone-500" role="status">Carregando a imagem…</p>}
          {url && (
            <div ref={area} data-testid="tarjas-imagem"
                 className={`relative select-none overflow-visible rounded border border-stone-200 ${desenhar ? 'ring-2 ring-amber-300' : ''}`}
                 style={{ touchAction: desenhar ? 'none' : 'auto', cursor: desenhar ? 'crosshair' : 'default' }}
                 onPointerDown={(e) => { if (desenhar) iniciar(e, 'desenhar', -1) }}
                 onPointerMove={mover} onPointerUp={soltar} onPointerCancel={soltar}>
              <img src={url} alt={`Documento ${doc.nome || doc.arquivo}`} draggable={false}
                   className="pointer-events-none block h-auto w-full"
                   onLoad={(e) => setNat({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />
              {L > 0 && A > 0 && caixas.map((c, i) => (
                <div key={i} role="group" aria-label={`Tarja ${i + 1}`} data-tarja={i}
                     className="absolute border-2 border-stone-900 bg-black/60"
                     style={{
                       left: pct(c[0], L), top: pct(c[1], A), width: pct(c[2] - c[0], L), height: pct(c[3] - c[1], A),
                       touchAction: 'none', cursor: editavel && !desenhar ? 'move' : undefined,
                     }}
                     onPointerDown={(e) => { if (!desenhar) iniciar(e, 'mover', i) }}>
                  {editavel && !desenhar && (
                    <>
                      {[0, 1, 2, 3].map((k) => (
                        <span key={k} aria-hidden="true" onPointerDown={(e) => iniciar(e, 'canto', i, k)}
                              className="absolute h-3 w-3 rounded-sm border border-white bg-stone-900"
                              style={{
                                left: k % 2 ? undefined : -7, right: k % 2 ? -7 : undefined,
                                top: k < 2 ? -7 : undefined, bottom: k < 2 ? undefined : -7,
                                cursor: k === 0 || k === 3 ? 'nwse-resize' : 'nesw-resize', touchAction: 'none',
                              }} />
                      ))}
                      <button type="button" aria-label={`Apagar tarja ${i + 1}`} title="Apagar tarja"
                              className="absolute -top-7 right-0 flex h-6 w-6 items-center justify-center rounded-full bg-red-600 text-white shadow ring-2 ring-white"
                              onPointerDown={(e) => e.stopPropagation()} onClick={() => setApagarIdx(i)}>
                        <X size={14} aria-hidden="true" />
                      </button>
                    </>
                  )}
                </div>
              ))}
            </div>
          )}
          {desenhar && <p className="text-xs text-stone-600" role="status">Arraste na imagem para criar a tarja.</p>}
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={`btn-sec btn-peq ${desenhar ? '!border-barro !bg-barro-claro' : ''}`}
                    aria-pressed={desenhar} disabled={!editavel || !url} onClick={() => setDesenhar((d) => !d)}>
              Desenhar caixa
            </button>
            <button type="button" className="btn-sec btn-peq" disabled={!alterado || salvando} onClick={desfazer}>
              Desfazer alterações
            </button>
            <button type="button" className="btn btn-peq sm:ml-auto" disabled={!livre || salvando || !url}
                    onClick={() => void salvar()}>
              {salvando ? 'Salvando…' : 'Salvar tarjas'}
            </button>
          </div>
          {msg && <p className={msg.ok ? 'text-sm text-emerald-700' : 'erro-txt'} role={msg.ok ? 'status' : 'alert'}>{msg.texto}</p>}
        </>
      )}
    </div>
  )
}

/** Painel "Conferir tarjas". `destaque`: aberto e em evidência (antes de confirmar o valor). */
export default function ConferirTarjas({ jobId, livre, destaque = false }: {
  jobId: string; livre: boolean; destaque?: boolean
}) {
  const [docs, setDocs] = useState<DocTarja[] | null>(null)
  const [erro, setErro] = useState('')

  const carregar = useCallback(async () => {
    try {
      setDocs(await get<DocTarja[]>(`/jobs/${encodeURIComponent(jobId)}/tarjas`))
      setErro('')
    } catch (e) {
      if (ehAuth(e)) return
      if (e instanceof ApiError && e.status === 404) { setDocs([]); return }
      setErro('Não foi possível carregar os documentos do solicitante.')
    }
  }, [jobId])

  useEffect(() => { void carregar() }, [carregar])

  if (docs !== null && docs.length === 0) return null
  const conferidos = docs?.filter((d) => d.conferido).length ?? 0

  return (
    <details open={destaque || undefined} id="painel-tarjas"
             className={`cartao group ${destaque ? '!border-amber-300 ring-2 ring-amber-200' : ''}`}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-xl px-4 py-3 transition-colors hover:bg-stone-50/70 sm:px-5 [&::-webkit-details-marker]:hidden">
        <h3 className="titulo-sec">Conferir tarjas</h3>
        <span className="flex items-center gap-2 text-xs text-stone-500">
          {docs ? `${conferidos} de ${docs.length} conferido${docs.length === 1 ? '' : 's'}` : ''}
          <ChevronDown size={16} className="transition-transform group-open:rotate-180" aria-hidden="true" />
        </span>
      </summary>
      <div className="space-y-4 border-t border-stone-100 px-4 py-3 sm:px-5 sm:py-4">
        {destaque && (
          <p className="text-sm font-medium text-amber-900">
            Antes de confirmar o valor, confira as tarjas dos documentos do solicitante.
          </p>
        )}
        <p className="rounded-lg bg-stone-50 px-3 py-2 text-sm text-stone-700">{AJUDA_TARJAS}</p>
        {!livre && <p className="text-sm text-stone-500">O trabalho está em execução; aguarde terminar para editar as tarjas.</p>}
        {erro && (
          <div className="flex items-center justify-between gap-3">
            <p className="erro-txt" role="alert">{erro}</p>
            <button type="button" className="btn-sec btn-peq" onClick={() => void carregar()}>Recarregar</button>
          </div>
        )}
        {!docs && !erro && <p className="text-sm text-stone-500" role="status">Carregando…</p>}
        {docs?.map((d) => (
          <div key={d.arquivo} className="border-t border-stone-100 pt-4 first-of-type:border-t-0 first-of-type:pt-0">
            <EditorTarja jobId={jobId} doc={d} livre={livre} aoSalvo={() => void carregar()} />
          </div>
        ))}
      </div>
    </details>
  )
}
