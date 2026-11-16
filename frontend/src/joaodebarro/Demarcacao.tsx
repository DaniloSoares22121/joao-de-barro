/* ORDEM 167-1: [Ajustar a demarcação] — a imagem LIMPA (sem contorno) da fachada da capa ou do mapa, e o avaliador
 * desenha o contorno: no mapa um retângulo (arrastar para desenhar; arrastar as pontas para ajustar; arrastar o meio
 * para mover); na fachada um contorno livre (desenhar com o mouse em volta do imóvel). Linha fina e vermelha, como no
 * laudo (D-129/D-130). Ao salvar, o sistema refaz a imagem demarcada e troca a figura no Word editável. */
import { useEffect, useRef, useState, type PointerEvent as PE } from 'react'
import { ApiError, baixarRaw, get, post } from './api'

interface Info { qual: 'capa' | 'mapa'; largura: number; altura: number; contorno: number[][]; forma: 'retangulo' | 'livre' }
type Pt = [number, number]
const FONTE = '"Manrope", "Inter", "Segoe UI", system-ui, -apple-system, Arial, sans-serif'

function caixaDe(pts: number[][]): [number, number, number, number] | null {
  if (pts.length < 3) return null
  const xs = pts.map((p) => p[0]); const ys = pts.map((p) => p[1])
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
}

export default function Demarcacao({ jobId, qual, aoFechar, aoSalvar, base = 'editavel/demarcacao' }: {
  jobId: string; qual: 'capa' | 'mapa'; aoFechar: () => void; aoSalvar: (salvoEm: string) => void
  base?: string                         // 172-3: 'imagens-laudo' = antes da montagem (a montagem usa o contorno)
}) {
  const j = encodeURIComponent(jobId)
  const [info, setInfo] = useState<Info | null>(null)
  const [url, setUrl] = useState('')
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)
  const [caixa, setCaixa] = useState<[number, number, number, number] | null>(null)   // mapa: x0, y0, x1, y1
  const [traco, setTraco] = useState<Pt[]>([])                                       // capa: contorno livre
  const svg = useRef<SVGSVGElement>(null)
  const arrasto = useRef<{ modo: string; de: Pt; caixa: [number, number, number, number] | null } | null>(null)

  useEffect(() => {
    let vivo = true; let u = ''
    get<Info>(`/jobs/${j}/${base}/${qual}`).then((i) => {
      if (!vivo) return
      setInfo(i)
      const c = caixaDe(i.contorno)
      if (i.forma === 'retangulo') setCaixa(c ?? [i.largura * 0.3, i.altura * 0.3, i.largura * 0.7, i.altura * 0.7])
    }).catch((e) => setErro(e instanceof ApiError ? e.message : 'Não consegui abrir a imagem limpa.'))
    baixarRaw(`/jobs/${j}/${base}/${qual}/imagem`)
      .then((r) => { if (vivo) { u = URL.createObjectURL(r.blob); setUrl(u) } }).catch(() => undefined)
    return () => { vivo = false; if (u) URL.revokeObjectURL(u) }
  }, [j, qual, base])

  const ponto = (e: PE<SVGSVGElement>): Pt => {
    const r = svg.current!.getBoundingClientRect()
    const x = ((e.clientX - r.left) / r.width) * (info?.largura ?? 1)
    const y = ((e.clientY - r.top) / r.height) * (info?.altura ?? 1)
    return [Math.max(0, Math.min(info?.largura ?? 0, x)), Math.max(0, Math.min(info?.altura ?? 0, y))]
  }
  const perto = (a: number, b: number) => Math.abs(a - b) < (info ? info.largura * 0.025 : 10)
  function descer(e: PE<SVGSVGElement>) {
    if (!info) return
    e.currentTarget.setPointerCapture(e.pointerId)
    const p = ponto(e)
    if (info.forma === 'livre') { setTraco([p]); arrasto.current = { modo: 'livre', de: p, caixa: null }; return }
    const c = caixa
    let modo = 'novo'
    if (c) {
      const [x0, y0, x1, y1] = c
      const px = perto(p[0], x0) ? 'e' : perto(p[0], x1) ? 'd' : ''
      const py = perto(p[1], y0) ? 'c' : perto(p[1], y1) ? 'b' : ''
      if (px && py && (p[1] > y0 - 20 && p[1] < y1 + 20)) modo = py + px
      else if (px && p[1] > y0 && p[1] < y1) modo = px
      else if (py && p[0] > x0 && p[0] < x1) modo = py
      else if (p[0] > x0 && p[0] < x1 && p[1] > y0 && p[1] < y1) modo = 'mover'
    }
    arrasto.current = { modo, de: p, caixa: c }
    if (modo === 'novo') setCaixa([p[0], p[1], p[0], p[1]])
  }
  function mover(e: PE<SVGSVGElement>) {
    const a = arrasto.current
    if (!a || !info) return
    const p = ponto(e)
    if (a.modo === 'livre') {
      setTraco((t) => {
        const u = t[t.length - 1]
        return !u || Math.hypot(p[0] - u[0], p[1] - u[1]) > info.largura / 250 ? [...t, p] : t
      })
      return
    }
    if (a.modo === 'novo') { setCaixa([a.de[0], a.de[1], p[0], p[1]]); return }
    if (!a.caixa) return
    let [x0, y0, x1, y1] = a.caixa
    const dx = p[0] - a.de[0]; const dy = p[1] - a.de[1]
    if (a.modo === 'mover') {
      const w = x1 - x0; const h = y1 - y0
      x0 = Math.max(0, Math.min(info.largura - w, x0 + dx)); y0 = Math.max(0, Math.min(info.altura - h, y0 + dy))
      setCaixa([x0, y0, x0 + w, y0 + h]); return
    }
    if (a.modo.includes('e')) x0 += dx
    if (a.modo.includes('d')) x1 += dx
    if (a.modo.includes('c')) y0 += dy
    if (a.modo.includes('b')) y1 += dy
    setCaixa([x0, y0, x1, y1])
  }
  function subir() { arrasto.current = null }

  const pontos = (): number[][] => {
    if (info?.forma === 'livre') return traco
    if (!caixa) return []
    const x0 = Math.min(caixa[0], caixa[2]); const x1 = Math.max(caixa[0], caixa[2])
    const y0 = Math.min(caixa[1], caixa[3]); const y1 = Math.max(caixa[1], caixa[3])
    return x1 - x0 < 6 || y1 - y0 < 6 ? [] : [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
  }
  async function salvar() {
    const pts = pontos()
    if (pts.length < 3) { setErro(info?.forma === 'livre' ? 'Desenhe o contorno em volta do imóvel com o mouse.' : 'Desenhe o retângulo em volta do lote.'); return }
    setSalvando(true); setErro('')
    try {
      const r = await post<{ salvo_em: string }>(`/jobs/${j}/${base}/${qual}`, { pontos: pts.map(([x, y]) => [Math.round(x), Math.round(y)]) })
      aoSalvar(r.salvo_em)
    } catch (e) { setErro(e instanceof ApiError ? e.message : 'Não consegui salvar a demarcação. Tente de novo.') }
    finally { setSalvando(false) }
  }

  const linha = info ? Math.max(2, info.largura / 400) : 2
  const c = caixa
  const rx = c ? Math.min(c[0], c[2]) : 0; const ry = c ? Math.min(c[1], c[3]) : 0
  const rw = c ? Math.abs(c[2] - c[0]) : 0; const rh = c ? Math.abs(c[3] - c[1]) : 0
  const ponta = info ? info.largura / 90 : 6
  return (
    <div role="dialog" aria-modal="true" aria-label="Ajustar a demarcação"
         style={{ position: 'fixed', inset: 0, zIndex: 120, background: 'rgba(15,23,35,.72)', display: 'grid', placeItems: 'center', padding: 16, fontFamily: FONTE }}>
      <div style={{ background: '#fff', borderRadius: 12, padding: 16, maxWidth: 'min(1100px, 100%)', width: '100%', maxHeight: '100%', overflow: 'auto' }}>
        <p style={{ margin: '0 0 4px', fontSize: 19, fontWeight: 800, color: '#18283B' }}>
          Ajustar a demarcação — {qual === 'mapa' ? 'mapa da localização' : 'foto da fachada'}</p>
        <p style={{ margin: '0 0 10px', fontSize: 15, color: '#333' }}>
          {qual === 'mapa'
            ? 'Arraste para desenhar o retângulo em volta do lote. Para ajustar, arraste as pontas ou os lados; para mudar de lugar, arraste o meio.'
            : 'Com o mouse apertado, desenhe o contorno em volta do imóvel avaliando. Soltou e não ficou bom? Desenhe de novo.'}</p>
        <div style={{ position: 'relative', maxWidth: '100%', margin: '0 auto', width: info ? Math.min(info.largura, 1060) : 600, aspectRatio: info ? `${info.largura} / ${info.altura}` : undefined, background: '#eee' }}>
          {url && <img src={url} alt="Imagem limpa, sem contorno" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', display: 'block' }} />}
          {info && (
            <svg ref={svg} viewBox={`0 0 ${info.largura} ${info.altura}`} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', cursor: 'crosshair', touchAction: 'none' }}
                 onPointerDown={descer} onPointerMove={mover} onPointerUp={subir} onPointerCancel={subir}>
              {info.forma === 'retangulo' && c && rw > 0 && <>
                <rect x={rx} y={ry} width={rw} height={rh} fill="rgba(224,0,0,.06)" stroke="#E00000" strokeWidth={linha} style={{ cursor: 'move' }} />
                {[[rx, ry], [rx + rw, ry], [rx + rw, ry + rh], [rx, ry + rh]].map(([x, y], i) => (
                  <rect key={i} x={x - ponta / 2} y={y - ponta / 2} width={ponta} height={ponta} fill="#fff" stroke="#E00000" strokeWidth={linha / 2} />))}
              </>}
              {info.forma === 'livre' && traco.length > 1 && (
                <polygon points={traco.map((p) => p.join(',')).join(' ')} fill="rgba(224,0,0,.06)" stroke="#E00000" strokeWidth={linha} strokeLinejoin="round" />)}
            </svg>)}
        </div>
        {erro && <p role="alert" style={{ margin: '10px 0 0', color: '#a12', fontSize: 15 }}>{erro}</p>}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 12, flexWrap: 'wrap' }}>
          {info?.forma === 'livre' && <button type="button" onClick={() => setTraco([])}
                  style={{ minHeight: 44, borderRadius: 8, border: '1px solid #18283B', background: '#fff', color: '#18283B', padding: '0 14px', fontSize: 15, fontFamily: 'inherit' }}>Limpar o desenho</button>}
          <button type="button" onClick={aoFechar}
                  style={{ minHeight: 44, borderRadius: 8, border: '1px solid #18283B', background: '#fff', color: '#18283B', padding: '0 14px', fontSize: 15, fontFamily: 'inherit' }}>Cancelar</button>
          <button type="button" disabled={salvando || !info} onClick={() => void salvar()}
                  style={{ minHeight: 44, borderRadius: 8, border: 0, background: '#1f9d55', color: '#fff', padding: '0 16px', fontSize: 16, fontWeight: 700, fontFamily: 'inherit' }}>
            {salvando ? 'Salvando…' : 'Salvar a demarcação'}</button>
        </div>
      </div>
    </div>
  )
}
