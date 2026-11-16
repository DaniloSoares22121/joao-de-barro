/* Editor do laudo DENTRO do João de Barro (pedido do avaliador): o laudo editável abre no navegador, como um
 * documento on-line, e salva sozinho a cada mudança. O texto troca só o pedaço da frase que mudou; a formatação que o
 * avaliador muda na barra (151-3: fonte, tamanho, negrito, cor, realce, alinhamento, lista, recuo, quebra de página)
 * vai para o Word editável e sai igual no PDF. Cabeçalho, rodapé, numeração e sumário são do sistema. */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react'
import {
  AlignCenter, AlignJustify, AlignLeft, AlignRight, Baseline, Bold, Highlighter, IndentDecrease, IndentIncrease,
  Italic, List, ListOrdered, Redo2, SeparatorHorizontal, Underline, Undo2,
} from 'lucide-react'
import { ApiError, baixarRaw, get, post, put } from './api'
import Demarcacao from './Demarcacao'

interface Run { x: string; b?: number; i?: number; u?: number; sz?: number; cor?: string; fonte?: string; realce?: string }
interface Par {
  t: 'p'; id: number; runs: Run[]; ed: boolean; al?: string; antes?: number; depois?: number; recuo?: number
  fundo?: string; quebra?: number; lista?: number; sumario?: number; linha?: string; imgs?: { w: number; h: number }[]
}
interface Cel { ps: Par[]; span?: number; fundo?: string; junta?: number }
interface Tab { t: 'tab'; larguras: number[]; linhas: Cel[][] }
type Bloco = Par | Tab
interface Doc {
  arquivo: string; blocos: Bloco[]; aviso?: string; paginas?: Record<string, number>; total_paginas?: number; folhas_de?: 'laudo' | 'previa'
  demarcaveis?: Record<string, 'capa' | 'mapa'>
  pagina: { largura: number; esq: number; dir: number; topo: number; altura?: number; baixo?: number; corpo?: number | null }
}
/** 157: um pedaço do documento numa folha — um parágrafo, ou as linhas de..ate de uma tabela */
type Peca = { t: 'p'; p: Par } | { t: 'tab'; tab: Tab; de: number; ate: number; k: number }
interface Folha { n: number | null; pecas: Peca[] }     // n: a página do PDF (null: folha nova, ainda sem número)
interface Salvo { salvo_em: string; removido: boolean; bloco: Par | null }
interface Formato { al?: string; recuo?: number; lista?: number; quebra?: number }
interface Passo { pid: number; antes: Par; depois: Par }       // uma volta do desfazer / refazer

const MM = 3.7795                       // pixels por milímetro (96 dpi)
const FONTE_JDB = '"Manrope", "Inter", "Segoe UI", system-ui, -apple-system, Arial, sans-serif'
export const FONTES = ['Arial', 'Calibri', 'Cambria', 'Georgia', 'Times New Roman', 'Verdana', 'Tahoma', 'Courier New']
const TAMANHOS = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36]
const CORES: [string, string][] = [['000000', 'Preto'], ['18283B', 'Azul do laudo'], ['5B6470', 'Cinza'], ['C00000', 'Vermelho'],
  ['A0522D', 'Barro'], ['1F7A3A', 'Verde'], ['1F4E9A', 'Azul']]
const REALCES: [string, string][] = [['FFFF00', 'Amarelo'], ['00FF00', 'Verde'], ['00FFFF', 'Azul-claro'], ['FF00FF', 'Rosa'],
  ['C0C0C0', 'Cinza'], ['', 'Sem realce']]
const ZOOMS = [50, 75, 90, 100, 110, 125, 150, 200]
const PASSO_RECUO = 36                  // 1,27 cm, como o "aumentar recuo" do Google Docs

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const textoDe = (p: Par) => p.runs.map((r) => r.x).join('')
function html(p: Par): string {
  return p.runs.map((r) => {
    const st = [r.b ? 'font-weight:700' : '', r.i ? 'font-style:italic' : '', r.u ? 'text-decoration:underline' : '',
      r.sz ? `font-size:${r.sz}pt` : '', r.cor ? `color:#${r.cor}` : '', r.fonte ? `font-family:'${r.fonte}'` : '',
      r.realce ? `background-color:#${r.realce}` : ''].filter(Boolean).join(';')
    return `<span style="${st}">${esc(r.x)}</span>`
  }).join('')
}
const lido = (el: HTMLElement) => (el.innerText || '').replace(/ /g, ' ').replace(/[\r\n]+/g, ' ')

/* ---- 151-3: a tela lê de volta a formatação de cada trecho (só o estilo escrito no trecho, como o Word guarda) ---- */
function hexDe(c: string): string | undefined {
  const m = c.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)$/)
  if (m) return m[4] !== undefined && Number(m[4]) === 0 ? '' : [m[1], m[2], m[3]].map((n) => Number(n).toString(16).padStart(2, '0')).join('').toUpperCase()
  if (/^#[0-9a-f]{6}$/i.test(c)) return c.slice(1).toUpperCase()
  if (c === 'transparent') return ''
  return undefined
}
function formatoDe(no: HTMLElement | null, raiz: HTMLElement): Omit<Run, 'x'> {
  const f: Omit<Run, 'x'> = {}
  for (let el = no; el && el !== raiz; el = el.parentElement) {
    const s = el.style
    const tag = el.tagName
    if (f.b === undefined) {
      if (tag === 'B' || tag === 'STRONG') f.b = 1
      else if (s.fontWeight) f.b = s.fontWeight === 'bold' || s.fontWeight === 'bolder' || Number(s.fontWeight) >= 600 ? 1 : 0
    }
    if (f.i === undefined) {
      if (tag === 'I' || tag === 'EM') f.i = 1
      else if (s.fontStyle) f.i = s.fontStyle === 'italic' || s.fontStyle === 'oblique' ? 1 : 0
    }
    const deco = s.textDecorationLine || s.textDecoration
    if (f.u === undefined) {
      if (tag === 'U') f.u = 1
      else if (deco) f.u = deco.includes('underline') ? 1 : deco.includes('none') ? 0 : undefined
    }
    if (f.sz === undefined && s.fontSize) {
      const n = parseFloat(s.fontSize)
      if (s.fontSize.endsWith('pt')) f.sz = n
      else if (s.fontSize.endsWith('px')) f.sz = Math.round(n * 1.5) / 2
    }
    if (f.cor === undefined) {
      const c = s.color || (tag === 'FONT' ? el.getAttribute('color') || '' : '')
      if (c) { const h = hexDe(c); if (h !== undefined) f.cor = h }
    }
    if (f.fonte === undefined) {
      const fa = s.fontFamily || (tag === 'FONT' ? el.getAttribute('face') || '' : '')
      if (fa) {
        const nome = fa.split(',')[0].replace(/["']/g, '').trim()
        f.fonte = FONTES.find((x) => x.toLowerCase() === nome.toLowerCase()) ?? undefined
      }
    }
    if (f.realce === undefined && s.backgroundColor) { const h = hexDe(s.backgroundColor); if (h !== undefined) f.realce = h }
  }
  return { b: f.b ?? 0, i: f.i ?? 0, u: f.u ?? 0, ...(f.sz ? { sz: f.sz } : {}), ...(f.cor !== undefined ? { cor: f.cor } : {}),
    ...(f.fonte ? { fonte: f.fonte } : {}), ...(f.realce !== undefined ? { realce: f.realce } : {}) }
}
function trechosDe(raiz: HTMLElement): Run[] {
  const out: Run[] = []
  const anda = (n: Node) => {
    if (n.nodeType === Node.TEXT_NODE) {
      const x = (n.textContent || '').replace(/ /g, ' ').replace(/[\r\n]+/g, ' ')
      if (!x) return
      const f = formatoDe(n.parentElement, raiz)
      const ult = out[out.length - 1]
      const { x: _x, ...fu } = ult ?? { x: '' }
      if (ult && JSON.stringify(fu) === JSON.stringify(f)) ult.x += x
      else out.push({ x, ...f })
      return
    }
    n.childNodes.forEach(anda)
  }
  raiz.childNodes.forEach(anda)
  return out
}
/** o trecho "cheio" (todo atributo dito, vazio = o do estilo do Word): é o que o desfazer manda de volta */
const cheio = (rs: Run[]): Run[] => rs.map((r) => ({ x: r.x, b: r.b ? 1 : 0, i: r.i ? 1 : 0, u: r.u ? 1 : 0, sz: r.sz ?? 0,
  cor: r.cor ?? '', fonte: r.fonte ?? '', realce: r.realce ?? '' }))
const formatoPar = (p: Par): Formato => ({ al: p.al ?? 'left', recuo: p.recuo ?? 0, lista: p.lista ?? 0, quebra: p.quebra ?? 0 })

function Imagem({ jobId, pid, k, w, h, marcada, aoClicar, v = 0 }: {
  jobId: string; pid: number; k: number; w: number; h: number; marcada?: boolean; aoClicar?: () => void; v?: number
}) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let vivo = true; let u = ''
    baixarRaw(`/jobs/${encodeURIComponent(jobId)}/editavel/imagem/${pid}?k=${k}&v=${v}`)
      .then((r) => { if (vivo) { u = URL.createObjectURL(r.blob); setUrl(u) } }).catch(() => undefined)
    return () => { vivo = false; if (u) URL.revokeObjectURL(u) }
  }, [jobId, pid, k, v])
  const contorno: CSSProperties = { outline: marcada ? '3px solid #1a73e8' : undefined, outlineOffset: 2, cursor: aoClicar ? 'pointer' : undefined }
  return url ? <img src={url} alt="Imagem do laudo" data-img-pid={pid} title="Clique para escolher a imagem e alinhar" onMouseDown={(e) => { e.preventDefault(); aoClicar?.() }}
                    style={{ display: 'inline-block', verticalAlign: 'top', width: w, maxWidth: '100%', height: 'auto', ...contorno }} />
    : <span style={{ display: 'inline-block', width: Math.min(w, 600), maxWidth: '100%', height: Math.min(h, 400), background: '#eee' }} />
}

/** 157-2: o cabeçalho ou o rodapé da página N, recortado do PDF (só imagem, travado, em tom claro, como no Word) */
function Faixa({ jobId, n, parte, versao, raiz }: {
  jobId: string; n: number; parte: 'cab' | 'rod'; versao: number; raiz: { current: HTMLElement | null }
}) {
  const [url, setUrl] = useState('')
  const [perto, setPerto] = useState(false)             // só pede a imagem quando a folha chega perto da tela
  const caixa = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = caixa.current
    if (!el || typeof IntersectionObserver === 'undefined') { setPerto(true); return undefined }
    const o = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { setPerto(true); o.disconnect() } },
      { root: raiz.current, rootMargin: '2500px 0px' })      // a área que rola (não a janela): pede antes de chegar
    o.observe(el)
    return () => o.disconnect()
  }, [])
  useEffect(() => {
    if (!perto) return undefined
    let vivo = true; let u = ''
    baixarRaw(`/jobs/${encodeURIComponent(jobId)}/editavel/faixa/${n}?parte=${parte}&v=${versao}`)
      .then((r) => { if (vivo) { u = URL.createObjectURL(r.blob); setUrl(u) } }).catch(() => undefined)
    return () => { vivo = false; if (u) URL.revokeObjectURL(u) }
  }, [jobId, n, parte, versao, perto])
  return (
    <div ref={caixa} aria-hidden="true" title={parte === 'cab' ? 'Cabeçalho: vem do modelo do laudo' : 'Rodapé: vem do modelo do laudo'}
         style={{ position: 'absolute', left: 0, right: 0, [parte === 'cab' ? 'top' : 'bottom']: 0, minHeight: 2, opacity: 0.55,
                  userSelect: 'none', pointerEvents: 'none', overflow: 'hidden' }}>
      {url && <img src={url} alt="" style={{ display: 'block', width: '100%', height: 'auto' }} />}
    </div>
  )
}

const BOTAO: CSSProperties = { minWidth: 36, height: 36, borderRadius: 6, border: 0, background: 'transparent', color: '#18283B',
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', padding: '0 6px', fontFamily: 'inherit', fontSize: 14 }
const SELECT: CSSProperties = { height: 34, borderRadius: 6, border: '1px solid #c9d1dc', background: '#fff', color: '#111', fontSize: 14,
  fontFamily: 'inherit', padding: '0 4px' }
function Ferr({ titulo, ativo, onClick, children, desligado }: { titulo: string; ativo?: boolean; onClick: () => void; children: ReactNode; desligado?: boolean }) {
  return (
    <button type="button" title={titulo} aria-label={titulo} aria-pressed={ativo} disabled={desligado}
            onMouseDown={(e) => e.preventDefault()} onClick={onClick}
            style={{ ...BOTAO, background: ativo ? '#dbe6f5' : 'transparent', opacity: desligado ? 0.4 : 1 }}>{children}</button>
  )
}
const Risca = () => <span aria-hidden="true" style={{ width: 1, height: 22, background: '#c9d1dc', margin: '0 4px' }} />

export default function EditorLaudo({ jobId, irPara, pagina, aoFechar, aoUsar, nomeUsar, aoLadoUsar, faixa }: {
  jobId: string; irPara?: string; pagina?: number; aoFechar: () => void; aoUsar?: () => void
  nomeUsar?: string; aoLadoUsar?: string          // 143-5: o mesmo nome do botão da lista
  faixa?: string                                  // 151-1: aviso fixo na barra ("Revisão humana — sua vez")
}) {
  const j = encodeURIComponent(jobId)
  const [doc, setDoc] = useState<Doc | null>(null)
  const [erro, setErro] = useState('')
  const [estado, setEstado] = useState('')              // "Salvando…" | "Salvo às 14:32:10"
  const [busca, setBusca] = useState(irPara ?? '')
  const [achou, setAchou] = useState('')
  const [numPag, setNumPag] = useState(pagina ? String(pagina) : '')
  const [zoom, setZoom] = useState(() => { try { return Number(localStorage.getItem('jdb_editor_zoom')) || 100 } catch { return 100 } })
  const [atual, setAtual] = useState<{ pid: number; f: Omit<Run, 'x'> } | null>(null)   // o parágrafo e o trecho do cursor
  const [voltas, setVoltas] = useState({ desfazer: 0, refazer: 0 })
  const [imgSel, setImgSel] = useState<number | null>(null)       // 158: a linha da imagem escolhida (clique na imagem)
  const [versao, setVersao] = useState(0)                          // 157: muda quando as páginas são refeitas
  const [paginando, setPaginando] = useState(false)
  const [demarcar, setDemarcar] = useState<{ qual: 'capa' | 'mapa'; pid: number } | null>(null)   // 167-1: a janela de ajustar a demarcação
  const [versaoImg, setVersaoImg] = useState<Record<number, number>>({})     // imagem trocada: pede de novo
  const [refazendoMapa, setRefazendoMapa] = useState(false)
  const [baixando, setBaixando] = useState(false)
  const salvo = useRef<Map<number, string>>(new Map())  // o último texto gravado de cada parágrafo
  const blocoDe = useRef<Map<number, Par>>(new Map())   // como o Word está agora (a última resposta do servidor)
  const formatou = useRef<Set<number>>(new Set())       // parágrafos com formatação mudada ainda não gravada
  const relogios = useRef<Map<number, number>>(new Map())
  const pendentes = useRef(0)
  const folha = useRef<HTMLDivElement>(null)
  const rolagem = useRef<HTMLDivElement>(null)
  const focar = useRef<number | null>(null)
  const faixaSel = useRef<Range | null>(null)           // a seleção guardada (a lista de fontes tira o foco do texto)
  const desfazer = useRef<Passo[]>([])
  const refazer = useRef<Passo[]>([])

  const contar = () => setVoltas({ desfazer: desfazer.current.length, refazer: refazer.current.length })
  const carregar = useCallback(async (manterVoltas = false) => {
    try {
      const d = await get<Doc>(`/jobs/${j}/editavel/documento`)
      const m = new Map<number, string>()
      const bs = new Map<number, Par>()
      const ver = (p: Par) => { m.set(p.id, textoDe(p)); bs.set(p.id, p) }
      d.blocos.forEach((b) => (b.t === 'p' ? ver(b) : b.linhas.forEach((l) => l.forEach((c) => c.ps.forEach(ver)))))
      salvo.current = m; blocoDe.current = bs
      if (!manterVoltas) { desfazer.current = []; refazer.current = []; contar() }   // os números dos parágrafos mudam
      setDoc(d); setErro('')
    } catch (e) { setErro(e instanceof ApiError ? e.message : 'Não consegui abrir o laudo editável.') }
  }, [j])
  useEffect(() => { void carregar() }, [carregar])
  function imagemTrocada(pid: number, salvoEm: string) {
    setVersaoImg((v) => ({ ...v, [pid]: (v[pid] ?? 0) + 1 }))
    setEstado(`Salvo às ${salvoEm}`)
  }
  async function refazerMapa(pid: number) {           // 167-1: nova captura no zoom do lote
    if (refazendoMapa) return
    setRefazendoMapa(true); setErro(''); setAchou('Refazendo o mapa no zoom do lote… pode levar até 1 minuto.')
    try {
      const r = await post<{ ok: boolean; motivo: string; salvo_em?: string }>(`/jobs/${j}/editavel/refazer-mapa`, {})
      if (r.ok) { imagemTrocada(pid, r.salvo_em ?? ''); setAchou(`Mapa refeito: ${r.motivo}. Confira o contorno; se precisar, use [Ajustar a demarcação].`) }
      else setAchou(r.motivo)
    } catch (e) { setAchou(''); setErro(e instanceof ApiError ? e.message : 'Não consegui refazer o mapa agora; o mapa atual ficou.') }
    finally { setRefazendoMapa(false) }
  }
  async function baixarPdf() {                         // 166: o PDF atual do laudo, com a revisão no nome
    if (baixando) return
    setBaixando(true)
    try {
      const r = await baixarRaw(`/jobs/${j}/baixar/pdf`)
      const a = document.createElement('a')
      a.href = URL.createObjectURL(r.blob); a.download = r.nome || 'laudo.pdf'
      document.body.appendChild(a); a.click(); a.remove()
      window.setTimeout(() => URL.revokeObjectURL(a.href), 30000)
    } catch (e) {
      setErro(e instanceof ApiError && e.status === 404 ? 'O botão de baixar entra no ar no próximo reinício do sistema.'
        : e instanceof ApiError ? e.message : 'Não consegui baixar o PDF agora.')
    } finally { setBaixando(false) }
  }
  async function atualizarPaginas() {                  // 157-3: refaz a paginação igual à do PDF (o laudo não muda)
    if (paginando) return
    setPaginando(true); setAchou('Refazendo as páginas como no PDF… leva uns 30 segundos. Pode continuar lendo.')
    try {
      await salvarTudo()
      await post(`/jobs/${j}/editavel/paginar`, {})
      await carregar(true)
      setVersao((v) => v + 1)
      setAchou('')
    } catch (e) { setAchou(''); setErro(e instanceof ApiError ? e.message : 'Não consegui refazer as páginas agora.') }
    finally { setPaginando(false) }
  }
  useEffect(() => { try { localStorage.setItem('jdb_editor_zoom', String(zoom)) } catch { /* ok */ } }, [zoom])

  useEffect(() => {                                     // depois de recarregar: põe o cursor no parágrafo novo
    if (doc && focar.current !== null) {
      const el = folha.current?.querySelector<HTMLElement>(`[data-pid="${focar.current}"]`)
      focar.current = null
      el?.focus()
    }
  }, [doc])

  const elDe = (pid: number) => folha.current?.querySelector<HTMLElement>(`[data-pid="${pid}"][contenteditable]`) ?? null
  function trocarBloco(novo: Par) {                     // a tela passa a mostrar o parágrafo como o Word ficou
    blocoDe.current.set(novo.id, novo)
    setDoc((d) => {
      if (!d) return d
      const tr = (p: Par) => (p.id === novo.id ? novo : p)
      return { ...d, blocos: d.blocos.map((b) => (b.t === 'p' ? tr(b) : { ...b, linhas: b.linhas.map((l) => l.map((c) => ({ ...c, ps: c.ps.map(tr) }))) })) }
    })
  }

  async function enviar(pid: number, corpo: { texto: string; base: string; runs?: Run[]; formato?: Formato; manter?: boolean }, el: HTMLElement | null,
    historico: 'novo' | 'nada'): Promise<Salvo | null> {
    pendentes.current += 1; setEstado('Salvando…')
    const antes = blocoDe.current.get(pid)
    try {
      const r = await put<Salvo>(`/jobs/${j}/editavel/paragrafo/${pid}`, corpo)
      if (r.removido) { await carregar() } else if (r.bloco) {
        salvo.current.set(pid, textoDe(r.bloco))
        blocoDe.current.set(pid, r.bloco)
        if (historico === 'novo' && antes) { desfazer.current.push({ pid, antes, depois: r.bloco }); refazer.current = []; contar() }
        if (corpo.formato) trocarBloco(r.bloco)
        else if (el && document.activeElement !== el && corpo.runs) el.innerHTML = html(r.bloco)
      }
      setEstado(`Salvo às ${r.salvo_em}`); setErro('')
      return r
    } catch (e) {
      const semConexao = !(e instanceof ApiError) || e.status >= 500
      if (corpo.runs) formatou.current.add(pid)
      if (semConexao) {
        // automático: sem conexão com o sistema, o texto fica na tela e o editor tenta salvar de novo sozinho
        setErro('Sem conexão com o sistema. Seu texto está na tela; tento salvar de novo sozinho a cada 5 segundos.')
        setEstado('Não salvo')
        if (el && !relogios.current.has(pid)) {
          relogios.current.set(pid, window.setTimeout(() => { relogios.current.delete(pid); if (el.isConnected) void gravar(pid, el) }, 5000))
        }
      } else {
        setErro(e.message); setEstado('Não salvo')
        if (e.status === 409) await carregar()
      }
      return null
    } finally { pendentes.current -= 1 }
  }
  async function gravar(pid: number, el: HTMLElement, formato?: Formato) {
    const comFormato = formatou.current.has(pid)
    const runs = comFormato ? trechosDe(el) : undefined
    const texto = runs ? runs.map((r) => r.x).join('') : lido(el)
    const base = salvo.current.get(pid) ?? ''
    if (texto === base && !comFormato && !formato) return
    formatou.current.delete(pid)
    await enviar(pid, { texto, base, ...(runs ? { runs } : {}), ...(formato ? { formato } : {}) }, el, 'novo')
  }
  async function salvarTudo() {                         // antes de conferir / concluir: nada fica para trás
    const ps = [...relogios.current.keys()]
    relogios.current.forEach((t) => window.clearTimeout(t)); relogios.current.clear()
    await Promise.all(ps.map((pid) => { const el = elDe(pid); return el ? gravar(pid, el) : Promise.resolve() }))
    for (let k = 0; k < 100 && pendentes.current > 0; k++) await new Promise((r) => window.setTimeout(r, 100))
  }
  useEffect(() => {                                     // fechar a aba com texto ainda não salvo: o navegador avisa
    const aviso = (ev: BeforeUnloadEvent) => { if (pendentes.current > 0 || relogios.current.size > 0) { ev.preventDefault(); ev.returnValue = '' } }
    window.addEventListener('beforeunload', aviso)
    return () => window.removeEventListener('beforeunload', aviso)
  }, [])
  function digitou(pid: number, el: HTMLElement) {
    const t = relogios.current.get(pid)
    if (t) window.clearTimeout(t)
    setEstado('Salvando…')
    relogios.current.set(pid, window.setTimeout(() => { relogios.current.delete(pid); void gravar(pid, el) }, 900))
  }
  function saiu(pid: number, el: HTMLElement, para: EventTarget | null) {
    const t = relogios.current.get(pid)
    if (t) { window.clearTimeout(t); relogios.current.delete(pid) }
    if ((para as HTMLElement | null)?.closest?.('.jdb-ferr')) { digitou(pid, el); return }   // foi à barra: volta já
    void gravar(pid, el).then(() => {                   // a formatação volta como o Word ficou
      const b = blocoDe.current.get(pid)
      if (b && document.activeElement !== el && el.isConnected && lido(el) === textoDe(b)) el.innerHTML = html(b)
    })
  }
  async function enter(pid: number, el: HTMLElement) {
    const sel = window.getSelection()
    const noFim = !!sel && sel.rangeCount > 0 && (() => {
      const r = sel.getRangeAt(0).cloneRange(); r.selectNodeContents(el); r.setStart(sel.focusNode ?? el, sel.focusOffset)
      return r.toString().length === 0
    })()
    if (!noFim) return                                  // Enter no meio da frase não parte o parágrafo
    await gravar(pid, el)
    try {
      const r = await post<{ id: number }>(`/jobs/${j}/editavel/paragrafo/${pid}/novo`, {})
      focar.current = r.id
      await carregar()
    } catch (e) { setErro(e instanceof ApiError ? e.message : 'Não consegui abrir um parágrafo novo.') }
  }

  /* ---- 151-3: a barra de ferramentas ---- */
  const paragrafoDaSelecao = (): HTMLElement | null => {
    const sel = window.getSelection()
    const n = sel && sel.rangeCount ? sel.getRangeAt(0).startContainer : null
    const el = n ? (n.nodeType === Node.ELEMENT_NODE ? n as HTMLElement : n.parentElement)?.closest<HTMLElement>('[data-pid][contenteditable]') : null
    return el && folha.current?.contains(el) ? el : null
  }
  useEffect(() => {                                     // guarda a seleção e mostra na barra o que vale no cursor
    const ver = () => {
      const el = paragrafoDaSelecao()
      if (!el) return
      setImgSel(null)
      const sel = window.getSelection()!
      faixaSel.current = sel.getRangeAt(0).cloneRange()
      const n = sel.getRangeAt(0).startContainer
      setAtual({ pid: Number(el.dataset.pid), f: formatoDe(n.nodeType === Node.ELEMENT_NODE ? n as HTMLElement : n.parentElement, el) })
    }
    document.addEventListener('selectionchange', ver)
    return () => document.removeEventListener('selectionchange', ver)
  }, [])
  function paragrafoAlvo(): HTMLElement | null {
    const el = paragrafoDaSelecao() ?? (atual ? elDe(atual.pid) : null)
    if (!el) {
      setAchou(imgSel !== null ? 'Na imagem, só os botões de alinhar, de recuo e de quebra de página agem. Para mudar a letra, clique numa frase.'
        : 'Para mudar a letra, clique numa frase (ou selecione um trecho); para alinhar uma imagem, clique nela. Depois toque no botão.')
      return null
    }
    if (document.activeElement !== el) {                // a lista de fontes/tamanhos tirou o foco: volta a seleção
      const r = faixaSel.current
      el.focus()
      if (r && el.contains(r.startContainer) && el.contains(r.endContainer)) {
        const s = window.getSelection(); s?.removeAllRanges(); s?.addRange(r)
      }
    }
    return el
  }
  function mudouFormato(el: HTMLElement) {
    const pid = Number(el.dataset.pid)
    formatou.current.add(pid)
    digitou(pid, el)
  }
  function marcar(cmd: 'bold' | 'italic' | 'underline') {
    const el = paragrafoAlvo(); if (!el) return
    document.execCommand('styleWithCSS', false, 'true')
    document.execCommand(cmd)
    mudouFormato(el)
  }
  /** fonte, tamanho, cor e realce: o trecho selecionado (ou a frase toda, sem seleção) recebe o estilo */
  function estilo(prop: 'fontSize' | 'fontFamily' | 'color' | 'backgroundColor', valor: string) {
    const el = paragrafoAlvo(); if (!el) return
    const sel = window.getSelection()
    if (!sel || !sel.rangeCount) return
    if (sel.isCollapsed) { const r = document.createRange(); r.selectNodeContents(el); sel.removeAllRanges(); sel.addRange(r) }
    document.execCommand('styleWithCSS', false, 'false')
    document.execCommand('fontSize', false, '7')        // marca o trecho com <font size=7> e troca pelo estilo
    el.querySelectorAll('font[size="7"]').forEach((f) => {
      const s = document.createElement('span')
      s.style[prop] = valor
      while (f.firstChild) s.appendChild(f.firstChild)
      s.querySelectorAll<HTMLElement>('[style]').forEach((x) => { x.style[prop] = '' })
      f.replaceWith(s)
    })
    mudouFormato(el)
  }
  async function noParagrafo(muda: (p: Par) => Formato) {
    if (imgSel !== null) {                               // 158: a imagem escolhida (a linha dela) recebe o formato
      const b = blocoDe.current.get(imgSel)
      if (b) await enviar(imgSel, { texto: textoDe(b), base: textoDe(b), formato: muda(b) }, null, 'novo')
      return
    }
    const el = paragrafoAlvo(); if (!el) return
    const pid = Number(el.dataset.pid)
    const t = relogios.current.get(pid)
    if (t) { window.clearTimeout(t); relogios.current.delete(pid) }
    const b = blocoDe.current.get(pid)
    if (!b) return
    await gravar(pid, el, muda(b))
    window.setTimeout(() => elDe(pid)?.focus(), 50)
  }
  async function voltar(de: typeof desfazer, para: typeof desfazer, lado: 'antes' | 'depois') {
    await salvarTudo()
    const passo = de.current.pop()
    if (!passo) { contar(); return }
    const agora = blocoDe.current.get(passo.pid)
    const quer = passo[lado]
    if (!agora) { contar(); return }
    const fa = formatoPar(agora); const fq = formatoPar(quer)
    const formato: Formato = {}
    ;(Object.keys(fq) as (keyof Formato)[]).forEach((k) => { if (fa[k] !== fq[k]) (formato as Record<string, unknown>)[k] = fq[k] })
    const r = await enviar(passo.pid, { texto: textoDe(quer), base: textoDe(agora), runs: cheio(quer.runs), manter: true,
      ...(Object.keys(formato).length ? { formato } : {}) }, null, 'nada')
    if (r?.bloco) {
      para.current.push(passo); contar()
      trocarBloco(r.bloco)
      const el = elDe(passo.pid)
      if (el) { el.innerHTML = html(r.bloco); el.scrollIntoView({ block: 'center' }) }
    } else { de.current.push(passo); contar() }
  }
  const voltarUm = () => void voltar(desfazer, refazer, 'antes')
  const refazerUm = () => void voltar(refazer, desfazer, 'depois')
  function teclas(e: KeyboardEvent<HTMLDivElement>) {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return
    const k = e.key.toLowerCase()
    if (k === 'b') { e.preventDefault(); marcar('bold') }
    else if (k === 'i') { e.preventDefault(); marcar('italic') }
    else if (k === 'u') { e.preventDefault(); marcar('underline') }
    else if (k === 'z' && !e.shiftKey) { e.preventDefault(); voltarUm() }
    else if (k === 'y' || (k === 'z' && e.shiftKey)) { e.preventDefault(); refazerUm() }
  }

  function procurar(texto: string) {
    const alvo = texto.trim().toLowerCase()
    if (!alvo || !folha.current) { setAchou(''); return }
    const els = [...folha.current.querySelectorAll<HTMLElement>('[data-pid]')]
    const el = els.find((x) => (x.innerText || '').toLowerCase().includes(alvo))
      ?? els.find((x) => (x.innerText || '').toLowerCase().includes(alvo.slice(0, 30)))
    if (!el) { setAchou('Não achei esse trecho no documento.'); return }
    setAchou('')
    el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    el.style.outline = '3px solid #F5B800'
    window.setTimeout(() => { el.style.outline = '' }, 2500)
    if (el.isContentEditable) el.focus()
  }
  const inicioDe = useMemo(() => {                       // nº do parágrafo -> página do PDF que começa nele
    const m = new Map<number, number>()
    Object.entries(doc?.paginas ?? {}).forEach(([n, pid]) => { if (!m.has(pid)) m.set(pid, Number(n)) })
    return m
  }, [doc])
  const numeroDaLista = useMemo(() => {                  // listas numeradas: 1, 2, 3… seguidos
    const m = new Map<number, number>()
    let n = 0
    doc?.blocos.forEach((b) => { if (b.t === 'p' && b.lista === 2) { n += 1; m.set(b.id, n) } else n = 0 })
    return m
  }, [doc])
  const folhas = useMemo<Folha[]>(() => {             // 157: uma folha por página do PDF, cortada onde ela começa
    const fs: Folha[] = [{ n: 1, pecas: [] }]
    // folha só com linhas vazias (ex.: a linha vazia com "quebra de página" logo antes do começo da página) não conta
    const vazia = (f: Folha) => f.pecas.every((pc) => pc.t === 'p' && !textoDe(pc.p).trim() && !pc.p.imgs)
    const nova = (n: number | null) => {
      const cur = fs[fs.length - 1]
      if (vazia(cur) && (fs.length > 1 || !cur.pecas.length)) { if (n !== null) cur.n = n; return }
      fs.push({ n, pecas: [] })
    }
    doc?.blocos.forEach((b, k) => {
      if (b.t === 'p') {
        const pg = inicioDe.get(b.id)
        if (pg && pg > 1) nova(pg)
        else if (b.quebra) nova(null)
        fs[fs.length - 1].pecas.push({ t: 'p', p: b })
        return
      }
      let de = 0
      b.linhas.forEach((l, i) => {
        const pgs = l.flatMap((c) => c.ps.map((p) => inicioDe.get(p.id) ?? 0)).filter((x) => x > 1)
        if (!pgs.length) return
        if (i > de) fs[fs.length - 1].pecas.push({ t: 'tab', tab: b, de, ate: i, k })
        nova(Math.min(...pgs)); de = i
      })
      fs[fs.length - 1].pecas.push({ t: 'tab', tab: b, de, ate: b.linhas.length, k })
    })
    return fs
  }, [doc, inicioDe])
  useEffect(() => {                                     // folha que passou do tamanho da página: avisa (sem recarregar)
    const medir = () => folha.current?.querySelectorAll<HTMLElement>('.jdb-folha').forEach((f) => {
      const alvo = Number(f.dataset.alt || 0)
      f.dataset.passou = alvo && f.scrollHeight > alvo * 1.06 ? '1' : ''
    })
    medir()
    const t = window.setInterval(medir, 3000)
    return () => window.clearInterval(t)
  }, [folhas])
  function irPagina(n: number) {
    if (!folha.current || !Number.isFinite(n) || n < 1) return
    const marcas = Object.keys(doc?.paginas ?? {}).map(Number).filter((x) => x <= n).sort((a, b) => b - a)
    const alvo = marcas[0]
    const el = alvo ? folha.current.querySelector<HTMLElement>(`[data-pag="${alvo}"]`) : null
    if (!el) { setAchou(n === 1 ? '' : 'Não achei essa página no documento.'); folha.current.scrollIntoView({ block: 'start' }); return }
    setAchou(alvo !== n ? `A página ${n} do PDF só tem imagem ou tabela; fui para o começo da pág. ${alvo}.` : '')
    el.scrollIntoView({ block: 'start' })             // instantâneo: chega certo mesmo vindo de longe
    el.style.outline = '4px solid rgba(245,184,0,.8)'
    window.setTimeout(() => { el.style.outline = '' }, 2500)
  }
  useEffect(() => { if (doc && pagina) irPagina(pagina) }, [doc === null, pagina])   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (doc && irPara && !pagina) procurar(irPara) }, [doc === null, irPara])   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {                                     // o cartão do JdB manda "ir para o trecho" para esta janela
    const ir = (ev: Event) => {
      const d = (ev as CustomEvent).detail as { pagina?: number; ir?: string } | string
      const pg = typeof d === 'object' ? Number(d.pagina || 0) : 0
      const t = typeof d === 'object' ? String(d.ir || '') : String(d || '')
      if (pg) { setNumPag(String(pg)); irPagina(pg) }
      if (t) { setBusca(t); window.setTimeout(() => procurar(t), pg ? 700 : 0) }
    }
    window.addEventListener('jdb-editor-ir', ir)
    return () => window.removeEventListener('jdb-editor-ir', ir)
  }, [doc])   // eslint-disable-line react-hooks/exhaustive-deps

  function par(p: Par, naCelula = false) {
    const estilo: CSSProperties = {
      textAlign: (p.al as CSSProperties['textAlign']) ?? 'left', margin: 0,
      paddingTop: p.antes ? `${p.antes}pt` : undefined, paddingBottom: p.depois !== undefined ? `${p.depois}pt` : (naCelula ? 0 : '6pt'),
      marginLeft: p.recuo ? `${p.recuo}pt` : undefined, background: p.fundo ? `#${p.fundo}` : undefined,
      borderBottom: p.linha ? `1.5px solid #${p.linha === 'auto' ? '999999' : p.linha}` : undefined,
      minHeight: '1.2em', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', borderRadius: 2,
      ...(p.lista ? { marginLeft: `${(p.recuo ?? 0) + 18}pt`, position: 'relative' } : {}),
    }
    const marcador = p.lista === 1 ? '•' : p.lista === 2 ? `${numeroDaLista.get(p.id) ?? 1}.` : ''
    return (
      <div key={p.id}>
        {p.imgs && <div style={{ textAlign: estilo.textAlign, marginLeft: estilo.marginLeft, paddingTop: estilo.paddingTop,
                                 paddingBottom: p.runs.length ? 0 : estilo.paddingBottom }}>
          {imgSel === p.id && doc?.demarcaveis?.[String(p.id)] && (
            <div role="toolbar" aria-label="Ferramentas da imagem" onMouseDown={(e) => e.preventDefault()}
                 style={{ display: 'flex', gap: 6, justifyContent: 'center', margin: '0 0 6px', fontFamily: FONTE_JDB }}>
              <button type="button" onClick={() => setDemarcar({ qual: doc.demarcaveis![String(p.id)], pid: p.id })}
                      style={{ minHeight: 36, borderRadius: 8, border: 0, background: '#1a73e8', color: '#fff', padding: '0 12px', fontSize: 14, fontWeight: 700, fontFamily: 'inherit' }}>
                Ajustar a demarcação</button>
              {doc.demarcaveis[String(p.id)] === 'mapa' && (
                <button type="button" disabled={refazendoMapa} onClick={() => void refazerMapa(p.id)}
                        style={{ minHeight: 36, borderRadius: 8, border: '1px solid #1a73e8', background: '#fff', color: '#1a73e8', padding: '0 12px', fontSize: 14, fontWeight: 700, fontFamily: 'inherit' }}>
                  {refazendoMapa ? 'Refazendo o mapa…' : 'Refazer o mapa'}</button>)}
            </div>)}
          {p.imgs.map((im, k) => <Imagem key={k} jobId={jobId} pid={p.id} k={k} w={im.w} h={im.h} marcada={imgSel === p.id} v={versaoImg[p.id] ?? 0}
                                         aoClicar={naCelula ? undefined : () => { (document.activeElement as HTMLElement | null)?.blur(); setImgSel(p.id) }} />)}</div>}
        <div style={{ position: 'relative' }}>
        {marcador && <span aria-hidden="true" style={{ position: 'absolute', left: `${(p.recuo ?? 0) + 4}pt`, top: p.antes ? `${p.antes}pt` : 0, userSelect: 'none' }}>
          {marcador}</span>}
        {(p.runs.length > 0 || !p.imgs) && (p.ed
          ? <div data-pid={p.id} contentEditable suppressContentEditableWarning spellCheck lang="pt-BR" style={estilo} className="jdb-editavel"
                 onInput={(e) => digitou(p.id, e.currentTarget)} onBlur={(e) => saiu(p.id, e.currentTarget, e.relatedTarget)}
                 onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void enter(p.id, e.currentTarget) } }}
                 onPaste={(e) => { e.preventDefault(); document.execCommand('insertText', false, e.clipboardData.getData('text/plain').replace(/[\r\n]+/g, ' ')) }}
                 dangerouslySetInnerHTML={{ __html: html(p) }} />
          : <div data-pid={p.id} style={{ ...estilo, color: p.sumario ? '#5B6470' : undefined }} title="Este trecho é montado pelo sistema"
                 dangerouslySetInnerHTML={{ __html: html(p) }} />)}
        </div>
      </div>
    )
  }
  function tabela(t: Tab, k: number, de = 0, ate = t.linhas.length) {
    const total = t.larguras.reduce((a, b) => a + b, 0) || 1
    return (
      <table key={`t${k}-${de}`} style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed', margin: '4pt 0 8pt' }}>
        <colgroup>{t.larguras.map((w, i) => <col key={i} style={{ width: `${(100 * w) / total}%` }} />)}</colgroup>
        <tbody>{t.linhas.slice(de, ate).map((l, i) => (
          <tr key={i}>{l.map((c, n) => (
            <td key={n} colSpan={c.span} style={{ border: '1px solid #b8c0cc', padding: '3pt 5pt', verticalAlign: 'top', background: c.fundo ? `#${c.fundo}` : undefined }}>
              {c.ps.map((p) => par(p, true))}
            </td>))}</tr>))}</tbody>
      </table>
    )
  }

  const pg = doc?.pagina
  const bAtual = imgSel !== null ? blocoDe.current.get(imgSel) : atual ? blocoDe.current.get(atual.pid) : undefined
  const f = atual?.f
  return (
    <div role="dialog" aria-modal="true" aria-label="Editor do laudo"
         style={{ position: 'fixed', inset: 0, zIndex: 80, background: '#e9edf2', display: 'flex', flexDirection: 'column', fontFamily: FONTE_JDB }}>
      <style>{'.jdb-editavel{outline:none;cursor:text}.jdb-editavel:hover{background-color:rgba(245,184,0,.10)}.jdb-editavel:focus{background-color:rgba(245,184,0,.18);box-shadow:0 0 0 2px #F5B800}'
        + '.jdb-ferr button:hover:not(:disabled){background:#e3e8ef!important}'
        + '.jdb-folha[data-passou="1"]::after{content:"Esta folha passou do tamanho da página: toque em Atualizar páginas";position:absolute;right:8px;bottom:-22px;font:12px Arial;color:#a33}'}</style>
      <div style={{ background: '#18283B', color: '#fff', padding: '8px 12px', display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', fontFamily: FONTE_JDB }}>
        <strong style={{ fontSize: 15, maxWidth: 190, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                title={doc?.arquivo}>{doc ? doc.arquivo.replace(/ - editável\.docx$/i, '') : 'Laudo editável'}</strong>
        {faixa && <span role="note" style={{ background: '#F5B800', color: '#18283B', borderRadius: 999, padding: '4px 10px', fontSize: 14, fontWeight: 700, whiteSpace: 'nowrap' }}>
          {faixa}</span>}
        <form onSubmit={(e) => { e.preventDefault(); irPagina(Number(numPag)) }} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <label htmlFor="jdb-pag" style={{ fontSize: 15, whiteSpace: 'nowrap' }}>Página</label>
          <input id="jdb-pag" inputMode="numeric" value={numPag} onChange={(e) => setNumPag(e.target.value.replace(/\D/g, '').slice(0, 3))}
                 style={{ width: 52, minHeight: 40, borderRadius: 8, border: 0, padding: '0 6px', fontSize: 16, color: '#111', textAlign: 'center', fontFamily: 'inherit' }} />
          <button type="submit" style={{ minHeight: 40, borderRadius: 8, border: 0, background: '#F5B800', color: '#18283B', padding: '0 14px', fontSize: 15, fontWeight: 700, fontFamily: 'inherit' }}>Ir</button>
        </form>
        <span role="status" style={{ fontSize: 14, color: estado === 'Não salvo' ? '#ffb4a8' : '#F5B800', minWidth: 104, whiteSpace: 'nowrap' }}>
          {estado || 'Tudo salvo'}</span>
        <form onSubmit={(e) => { e.preventDefault(); procurar(busca) }} style={{ display: 'flex', gap: 6, flex: '1 1 150px', maxWidth: 260 }}>
          <input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Achar um trecho no documento"
                 aria-label="Achar um trecho no documento" style={{ flex: 1, minWidth: 0, minHeight: 40, borderRadius: 8, border: 0, padding: '0 10px', fontSize: 15, color: '#111', fontFamily: 'inherit' }} />
          <button type="submit" style={{ minHeight: 40, borderRadius: 8, border: '1px solid #fff', background: 'transparent', color: '#fff', padding: '0 10px', fontSize: 15, fontFamily: 'inherit' }}>Achar</button>
        </form>
        <span style={{ flex: 1 }} />
        {aoUsar && <button type="button" onClick={() => { (document.activeElement as HTMLElement | null)?.blur(); void salvarTudo().then(aoUsar) }}
                           style={{ minHeight: 44, borderRadius: 8, border: 0, background: '#1f9d55', color: '#fff', padding: '0 12px', fontSize: 15, fontWeight: 700, whiteSpace: 'nowrap', fontFamily: 'inherit' }}>
          {nomeUsar || 'Usar este documento como laudo'}</button>}
        {aoUsar && aoLadoUsar && <span style={{ fontSize: 14, color: '#cfe8d8', whiteSpace: 'nowrap' }}>{aoLadoUsar}</span>}
        <button type="button" onClick={() => { (document.activeElement as HTMLElement | null)?.blur(); void salvarTudo().then(aoFechar) }}
                style={{ minHeight: 44, borderRadius: 8, border: '1px solid #fff', background: 'transparent', color: '#fff', padding: '0 12px', fontSize: 15, fontFamily: 'inherit' }}>
          Fechar</button>
      </div>
      {/* 151-3: a barra de ferramentas fixa, como a do Google Docs */}
      <div role="toolbar" aria-label="Formatação" className="jdb-ferr"
           style={{ background: '#f4f6f9', borderBottom: '1px solid #d5dbe3', padding: '4px 10px', display: 'flex', flexWrap: 'wrap', gap: 2, alignItems: 'center' }}>
        <Ferr titulo="Desfazer (Ctrl+Z)" onClick={voltarUm} desligado={!voltas.desfazer}><Undo2 size={18} /></Ferr>
        <Ferr titulo="Refazer (Ctrl+Y)" onClick={refazerUm} desligado={!voltas.refazer}><Redo2 size={18} /></Ferr>
        <Risca />
        <select aria-label="Zoom" title="Zoom" value={zoom} onChange={(e) => setZoom(Number(e.target.value))} style={{ ...SELECT, width: 74 }}>
          {ZOOMS.map((z) => <option key={z} value={z}>{z}%</option>)}</select>
        <Risca />
        <select aria-label="Fonte" title="Fonte" value={f?.fonte ?? ''} onChange={(e) => { if (e.target.value) estilo('fontFamily', `'${e.target.value}'`) }}
                style={{ ...SELECT, width: 150 }}>
          <option value="">{f && !f.fonte ? 'Arial (do laudo)' : 'Fonte'}</option>
          {FONTES.map((x) => <option key={x} value={x} style={{ fontFamily: x }}>{x}</option>)}</select>
        <select aria-label="Tamanho da letra" title="Tamanho da letra" value={f?.sz ?? ''} onChange={(e) => { if (e.target.value) estilo('fontSize', `${e.target.value}pt`) }}
                style={{ ...SELECT, width: 64 }}>
          <option value="">{f && !f.sz ? '11' : 'Tam.'}</option>
          {TAMANHOS.map((x) => <option key={x} value={x}>{x}</option>)}
          {f?.sz && !TAMANHOS.includes(f.sz) && <option value={f.sz}>{f.sz}</option>}</select>
        <Risca />
        <Ferr titulo="Negrito (Ctrl+B)" ativo={!!f?.b} onClick={() => marcar('bold')}><Bold size={18} /></Ferr>
        <Ferr titulo="Itálico (Ctrl+I)" ativo={!!f?.i} onClick={() => marcar('italic')}><Italic size={18} /></Ferr>
        <Ferr titulo="Sublinhado (Ctrl+U)" ativo={!!f?.u} onClick={() => marcar('underline')}><Underline size={18} /></Ferr>
        <label title="Cor do texto" style={{ ...BOTAO, gap: 2, position: 'relative' }}>
          <Baseline size={18} color={f?.cor ? `#${f.cor}` : '#18283B'} />
          <select aria-label="Cor do texto" value=""
                  onChange={(e) => { if (e.target.value) estilo('color', `#${e.target.value}`) }}
                  style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }}>
            <option value="">Cor do texto</option>
            {CORES.map(([h, n]) => <option key={h} value={h}>{n}</option>)}</select></label>
        <label title="Realce (marca-texto)" style={{ ...BOTAO, position: 'relative', background: f?.realce ? `#${f.realce}` : 'transparent' }}>
          <Highlighter size={18} />
          <select aria-label="Realce" value="-" onChange={(e) => { if (e.target.value !== '-') estilo('backgroundColor', e.target.value ? `#${e.target.value}` : 'transparent') }}
                  style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }}>
            <option value="-">Realce</option>
            {REALCES.map(([h, n]) => <option key={n} value={h}>{n}</option>)}</select></label>
        <Risca />
        {([['left', 'Alinhar à esquerda', AlignLeft], ['center', 'Centralizar', AlignCenter], ['right', 'Alinhar à direita', AlignRight],
          ['justify', 'Justificar', AlignJustify]] as const).map(([al, t, Ic]) => (
          <Ferr key={al} titulo={t} ativo={!!bAtual && (bAtual.al ?? 'left') === al} onClick={() => void noParagrafo(() => ({ al }))}><Ic size={18} /></Ferr>))}
        <Risca />
        <Ferr titulo="Lista com marcador" ativo={bAtual?.lista === 1} onClick={() => void noParagrafo((p) => ({ lista: p.lista === 1 ? 0 : 1 }))}><List size={18} /></Ferr>
        <Ferr titulo="Lista numerada" ativo={bAtual?.lista === 2} onClick={() => void noParagrafo((p) => ({ lista: p.lista === 2 ? 0 : 2 }))}><ListOrdered size={18} /></Ferr>
        <Ferr titulo="Diminuir recuo" onClick={() => void noParagrafo((p) => ({ recuo: Math.max(0, (p.recuo ?? 0) - PASSO_RECUO) }))}><IndentDecrease size={18} /></Ferr>
        <Ferr titulo="Aumentar recuo" onClick={() => void noParagrafo((p) => ({ recuo: (p.recuo ?? 0) + PASSO_RECUO }))}><IndentIncrease size={18} /></Ferr>
        <Risca />
        <Ferr titulo={bAtual?.quebra ? 'Tirar a quebra de página antes desta frase' : 'Começar página nova nesta frase (quebra de página)'}
              ativo={!!bAtual?.quebra} onClick={() => void noParagrafo((p) => ({ quebra: p.quebra ? 0 : 1 }))}>
          <SeparatorHorizontal size={18} /><span style={{ marginLeft: 4 }}>{bAtual?.quebra ? 'Tirar quebra de página' : 'Quebra de página'}</span></Ferr>
        <Risca />
        <Ferr titulo="Baixar o PDF atual do laudo (as mudanças entram no PDF ao concluir)" onClick={() => void baixarPdf()} desligado={baixando}>
          <span>{baixando ? 'Baixando…' : 'Baixar PDF'}</span></Ferr>
        <Risca />
        <Ferr titulo="Refaz as folhas igual às páginas do PDF (o laudo não muda)" onClick={() => void atualizarPaginas()} desligado={paginando}>
          <span>{paginando ? 'Atualizando páginas…' : 'Atualizar páginas'}</span></Ferr>
        <span style={{ fontSize: 12, color: '#5B6470', marginLeft: 4 }}>
          deixa as páginas iguais às do PDF (uns 30 s; o laudo não muda){doc?.total_paginas ? ` · agora: ${doc.total_paginas} páginas, como no ${doc.folhas_de === 'previa' ? 'PDF de prévia' : 'PDF do laudo'}` : ''}</span>
      </div>
      {demarcar && <Demarcacao jobId={jobId} qual={demarcar.qual} aoFechar={() => setDemarcar(null)}
                               aoSalvar={(em) => { const pid = demarcar.pid; setDemarcar(null); imagemTrocada(pid, em); setAchou('Demarcação salva no laudo editável. Ela sai no PDF ao concluir.') }} />}
      {(erro || achou || doc?.aviso) && <p role="alert" style={{ margin: 0, padding: '8px 14px', background: erro ? '#fde8e4' : '#fff6d6', color: '#111', fontSize: 15 }}>{erro || achou || doc?.aviso}</p>}
      <div ref={rolagem} style={{ flex: 1, overflow: 'auto', padding: '18px 8px 60px' }} onKeyDown={teclas}>
        {!doc && !erro && <p style={{ textAlign: 'center', fontSize: 16 }}>Abrindo o laudo…</p>}
        {doc && pg && (
          <div ref={folha} onMouseDown={(e) => { const t = e.target as HTMLElement; if (!t.closest('img') && !t.closest('[aria-label="Ferramentas da imagem"]')) setImgSel(null) }}
               style={{ zoom: zoom / 100, font: '11pt Arial, Helvetica, sans-serif', color: '#111', lineHeight: 1.25 }}>
            {folhas.map((fo, i) => {
              const alt = (pg.altura ?? 297) * MM
              const n = fo.n
              return (
                <div key={i} className="jdb-folha" data-pag={n ?? undefined} data-alt={Math.round(alt)}
                     style={{ position: 'relative', width: pg.largura * MM, maxWidth: zoom > 100 ? undefined : '100%', minHeight: alt, margin: '0 auto 22px',
                              background: '#fff', boxShadow: '0 1px 6px rgba(0,0,0,.25)', boxSizing: 'border-box',
                              padding: `${(pg.corpo ?? pg.topo) * MM}px ${pg.dir * MM}px ${(pg.baixo ?? pg.topo) * MM}px ${pg.esq * MM}px` }}>
                  {n && n <= (doc.total_paginas ?? 0) && <Faixa jobId={jobId} n={n} parte="cab" versao={versao} raiz={rolagem} />}
                  {n && n <= (doc.total_paginas ?? 0) && <Faixa jobId={jobId} n={n} parte="rod" versao={versao} raiz={rolagem} />}
                  <span aria-hidden="true" style={{ position: 'absolute', left: -52, top: 6, font: '11px Arial', color: '#8a6d00' }}>
                    {n ? `pág. ${n}` : 'folha nova'}</span>
                  {fo.pecas.map((pc) => (pc.t === 'p' ? par(pc.p) : tabela(pc.tab, pc.k, pc.de, pc.ate)))}
                </div>
              )
            })}
          </div>
        )}
        {doc && <p style={{ textAlign: 'center', fontSize: 13, color: '#5B6470', marginTop: 14 }}>
          Clique numa frase e escreva: salva sozinho. Clique numa imagem para alinhar. A barra de cima muda fonte, tamanho,
          alinhamento e o resto, e sai igual no PDF. Cabeçalho, rodapé e sumário vêm do modelo do laudo. Se o texto passar do
          fim de uma folha, ela cresce: [Atualizar páginas] corta as folhas de novo igual ao PDF.</p>}
      </div>
    </div>
  )
}


/* ORDEM 142: o laudo editável numa ABA NOVA do navegador (nome fixo: o 2º toque volta à mesma aba). A aba conversa
 * com o JdB pelo canal 'jdb-editavel-<trabalho>': {tipo:'ir', pagina, ir} leva à página; "usar" pede ao JdB o PDF;
 * 151: {tipo:'revisao'} (ou &modo=revisao) põe a aba na revisão humana; no fim ela manda {tipo:'concluido'}. */
export const canalEditor = (jobId: string) => `jdb-editavel-${jobId}`
export const nomeAba = (jobId: string) => `jdb-editavel-${jobId}`
const NOME_USAR = '✓ Todos os pontos conferidos'
const AO_LADO_USAR = 'Seguir para a revisão humana →'
const NOME_CONCLUIR = 'Concluir a revisão humana'
const NINHO = `${import.meta.env.BASE_URL}jdb-marca/jdb-animacao-claro-etapa7.svg`

/** Abre o editável numa aba nova, ou volta à mesma aba e manda ir à página. 'bloqueada': o navegador não deixou. */
export function abrirEditavel(jobId: string, pagina?: number, trecho?: string, modo?: 'revisao'): 'nova' | 'existente' | 'bloqueada' {
  const url = `${window.location.pathname}?editor=${encodeURIComponent(jobId)}${pagina ? `&pagina=${pagina}` : ''}${modo ? `&modo=${modo}` : ''}`
  const w = window.open('', nomeAba(jobId))
  if (!w) return 'bloqueada'
  let nova = true
  try { nova = !w.location.href || w.location.href === 'about:blank' } catch { nova = false }
  if (nova) { w.location.href = url } else if (typeof BroadcastChannel !== 'undefined') {
    const c = new BroadcastChannel(canalEditor(jobId))
    if (modo === 'revisao') c.postMessage({ tipo: 'revisao', pagina: pagina ?? 1 })
    else if (pagina || trecho) c.postMessage({ tipo: 'ir', pagina, ir: trecho })
    c.close()
  }
  try { w.focus() } catch { /* o navegador decide se troca de aba */ }
  return nova ? 'nova' : 'existente'
}

interface Fim { ok: boolean; texto: string; pdf?: string; diferencas: number }
export function JanelaEditor({ jobId }: { jobId: string }) {
  const busca = new URLSearchParams(window.location.search)
  const [aviso, setAviso] = useState('')
  const [chave, setChave] = useState(0)
  const [pronto, setPronto] = useState(false)          // 151-1: a revisão do sistema terminou (tela com o João)
  const [modo, setModo] = useState<'conferir' | 'revisao'>(busca.get('modo') === 'revisao' ? 'revisao' : 'conferir')
  const [pagIni, setPagIni] = useState<number | undefined>(Number(busca.get('pagina') || 0) || undefined)
  const [concluindo, setConcluindo] = useState(false)
  const [fim, setFim] = useState<Fim | null>(null)     // 151-5: revisão humana concluída
  const pronto_ = useRef(false)
  pronto_.current = pronto || !!fim

  function entrarNaRevisao(pagina = 1) {
    setModo('revisao'); setPronto(false); setFim(null); setAviso('')
    try {
      const u = new URL(window.location.href); u.searchParams.set('modo', 'revisao'); u.searchParams.set('pagina', String(pagina))
      window.history.replaceState(null, '', u.toString())
    } catch { /* ok */ }
    if (pronto_.current) { setPagIni(pagina); setChave((k) => k + 1) }      // volta da tela "Pronto": abre na página
    else window.dispatchEvent(new CustomEvent('jdb-editor-ir', { detail: { pagina } }))
  }
  useEffect(() => {
    document.title = 'Laudo editável — João de Barro'
    try { window.name = nomeAba(jobId) } catch { /* ok */ }
    if (typeof BroadcastChannel === 'undefined') return undefined
    const c = new BroadcastChannel(canalEditor(jobId))
    c.onmessage = (ev) => {
      const m = ev.data as { tipo?: string; texto?: string; ir?: string; pagina?: number; ok?: boolean; pdf?: string; diferencas?: number } | null
      if (m?.tipo === 'usado') { setAviso(m.texto || 'PDF novo pronto.'); if (m.ok !== false) setChave((k) => k + 1) }
      // 164: outra aba do editor concluiu (esta pode ter levado "Já estou gerando…"): vai à mesma tela que ela
      if (m?.tipo === 'concluido') {
        if (m.ok) { setAviso(''); setFim({ ok: true, texto: m.texto || 'PDF final pronto.', pdf: m.pdf, diferencas: Number(m.diferencas || 0) }) }
        else { setAviso(m.texto || 'A conferência achou um número diferente da conta.'); setChave((k) => k + 1) }
      }
      if (m?.tipo === 'revisao_humana') { setPronto(true); setAviso('') }
      if (m?.tipo === 'revisao') entrarNaRevisao(Number(m.pagina || 1))
      if (m?.tipo === 'ir') window.dispatchEvent(new CustomEvent('jdb-editor-ir', { detail: { pagina: m.pagina, ir: m.ir } }))
    }
    return () => c.close()
  }, [jobId])        // eslint-disable-line react-hooks/exhaustive-deps
  function irAoJdB() {
    try { if (window.opener && !window.opener.closed) { window.opener.focus(); return } } catch { /* outra origem */ }
    window.location.href = `${window.location.pathname}#/job/${encodeURIComponent(jobId)}`   // sem a aba do JdB: abre aqui
  }
  function avisar(m: Record<string, unknown>) {
    if (typeof BroadcastChannel === 'undefined') return
    const c = new BroadcastChannel(canalEditor(jobId)); c.postMessage(m); c.close()
  }
  function usar() {
    if (typeof BroadcastChannel === 'undefined') { setAviso('Volte à aba do João de Barro e toque em “' + NOME_USAR + '”.'); return }
    avisar({ tipo: 'usar' })
    setAviso('Gerando o PDF com este documento e conferindo… o resultado aparece aqui e na aba do João de Barro.')
  }
  async function concluir() {                          // 151-5: salva, gera o PDF final, confere só por regra
    if (concluindo) return
    setConcluindo(true)
    setAviso('Gerando o PDF final no padrão do laudo e conferindo… leva menos de 1 minuto.')
    try {
      const r = await post<{ ok: boolean; pdf?: string; diferencas?: unknown[]; bloqueia?: number; bloqueia_texto?: string;
        concluida_em?: string | null; mudou?: boolean }>(`/jobs/${encodeURIComponent(jobId)}/editavel/usar`, { concluir: true })
      const n = (r.diferencas ?? []).length
      if (!r.concluida_em) {
        const t = r.bloqueia_texto || 'A conferência achou um número diferente da conta. Corrija e toque de novo.'
        setAviso(t)
        avisar({ tipo: 'concluido', ok: false, texto: t, pdf: r.pdf, diferencas: n, bloqueia: r.bloqueia ?? 0 })
        setChave((k) => k + 1)
        return
      }
      const t = n ? `PDF final pronto. A conferência deixou ${n} ${n === 1 ? 'aviso' : 'avisos'} para você ver no João de Barro.`
        : 'PDF final pronto, no padrão do laudo. A conferência não achou nada diferente.'
      avisar({ tipo: 'concluido', ok: true, texto: t, pdf: r.pdf, diferencas: n, bloqueia: 0 })
      setAviso(''); setFim({ ok: true, texto: t, pdf: r.pdf, diferencas: n })
    } catch (e) {
      setAviso(e instanceof ApiError ? e.message : 'Não consegui concluir agora. Seu texto está salvo; toque de novo.')
    } finally { setConcluindo(false) }
  }

  const cartao = (filhos: ReactNode) => (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#e9edf2', padding: 16, fontFamily: FONTE_JDB }}>
      <div style={{ background: '#fff', borderRadius: 14, padding: '24px 24px 26px', maxWidth: 560, width: '100%', textAlign: 'center',
                    boxShadow: '0 2px 10px rgba(0,0,0,.18)', border: '2px solid #18283B' }}>
        <img src={NINHO} alt="" aria-hidden="true" width={160} height={160} style={{ display: 'block', margin: '0 auto 6px' }} />
        {filhos}
      </div>
    </div>
  )
  const BOTAO_GRANDE: CSSProperties = { minHeight: 52, width: '100%', borderRadius: 10, border: 0, background: '#1f9d55', color: '#fff',
    fontSize: 18, fontWeight: 700, fontFamily: 'inherit', cursor: 'pointer' }
  if (fim) {
    return cartao(<>
      <p style={{ fontSize: 24, fontWeight: 800, color: '#18283B', margin: '0 0 8px' }}>Revisão humana concluída</p>
      <p style={{ fontSize: 17, color: '#111', margin: '0 0 22px' }}>{fim.texto} Agora é só abrir o PDF final no João de Barro e aprovar.</p>
      <button type="button" onClick={irAoJdB} style={BOTAO_GRANDE}>Ir ao João de Barro para aprovar</button>
    </>)
  }
  if (pronto) {
    return cartao(<>
      <p style={{ fontSize: 24, fontWeight: 800, color: '#18283B', margin: '0 0 8px' }}>Pronto! A revisão do sistema terminou.</p>
      <p style={{ fontSize: 17, color: '#111', margin: '0 0 22px' }}>Agora é a revisão humana: você volta ao documento para ler o laudo inteiro e ajustar o que quiser.</p>
      <button type="button" onClick={() => entrarNaRevisao(1)} style={BOTAO_GRANDE}>Começar a revisão humana</button>
    </>)
  }
  const revisao = modo === 'revisao'
  return (
    <>
      <EditorLaudo key={chave} jobId={jobId} pagina={pagIni} aoFechar={() => window.close()}
                   aoUsar={revisao ? () => void concluir() : usar}
                   nomeUsar={revisao ? (concluindo ? 'Concluindo…' : NOME_CONCLUIR) : NOME_USAR}
                   aoLadoUsar={revisao ? undefined : AO_LADO_USAR} faixa={revisao ? 'Revisão humana — sua vez' : undefined} />
      {aviso && <p role="status" style={{ position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: 90, margin: 0, padding: '10px 14px',
                                            background: '#18283B', color: '#fff', fontSize: 15, fontFamily: FONTE_JDB }}>{aviso}</p>}
    </>
  )
}
