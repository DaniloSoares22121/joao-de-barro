/* 119-1 / 120: os erros que dependem do avaliador, um embaixo do outro, numerados, na ordem das páginas.
 * Cada um: onde e o que está errado, o que está no laudo, [Mostrar no PDF] (com "1 de 2 ›"), o campo
 * "Me diga como corrigir" já aberto (com [🎤 Falar] e [Aplicar]), e a sugestão de um toque quando houver.
 * No fim: "N de M respondidos" e [Aplicar tudo e refazer o laudo] — uma montagem só. */
import { useEffect, useRef, useState } from 'react'
import { Check, ChevronLeft, ChevronRight, FileSearch, X } from 'lucide-react'
import { ApiError, baixarRaw, post } from './api'
import { BaixarRevisao } from './Downloads'
import { canalEditor } from './EditorLaudo'
import { abrirOuAvisar } from './GoogleDocs'

export interface Erro {
  n: number; pagina: number | null; item: string; titulo: string; no_laudo: string
  lugares: { pagina: number | null; trecho: string }[]; sugestao: string; valor_sugerido: string
  campo: string; tipo: string
  explicacao?: string            // 144: o que está errado e por quê, inteiro
  frase?: string                 // 171-1: a frase exata do Word (5 a 12 palavras, única) para o Ctrl+F
  frase_vezes?: number           // quando só há o número sozinho (célula de tabela): quantas vezes aparece no Word
}

/** 126-1: erro de IMAGEM não pede texto — o cartão traz o botão da ação. */
export function acaoDeImagem(e: Erro): { rotulo: string; pedido: string; aviso: string } | null {
  const t = `${e.titulo} ${e.no_laudo}`.toLowerCase()
  if (!/imagem|mapa|foto|localiza/.test(t) || !/branco|vazi|errad|troc|contorno|demarca|cinza|n[ãa]o mostra/.test(t)) return null
  if (/mapa|localiza/.test(t)) return { rotulo: 'Refazer o mapa', aviso: 'Vou refazer o mapa quando você tocar em Aplicar tudo.',
    pedido: 'refazer o mapa da localização: o lote do avaliando demarcado com contorno fino, imagem com conteúdo' }
  return { rotulo: 'Trocar a foto', aviso: 'Vou trocar a foto quando você tocar em Aplicar tudo.', pedido: `trocar a foto: ${e.titulo}` }
}

/** 132-6: pedido vago ("refaça", "refaz até ficar certo", "arruma") — o sistema pergunta "refazer o quê?" antes. */
export function pedidoVago(texto: string): boolean {
  const t = texto.toLowerCase().replace(/[.,;!]/g, ' ').replace(/\s+/g, ' ').trim()
  const vagas = /^(refa[çc]a|refaz|refazer|arruma|arrumar|corrige|corrigir|conserta|consertar)( isso| de novo| tudo| at[ée] (sair|ficar) (do jeito )?certo| do jeito certo)*$/
  return vagas.test(t)
}

/** O par "Onde fica / O que mudar" que vai para o mecanismo dos pedidos (117). */
export function pedidoDoErro(e: Erro, resposta: string): string {
  const onde = [e.pagina ? `página ${e.pagina}` : '', e.item ? `item ${e.item}` : ''].filter(Boolean).join(', ')
  return `Onde fica: ${onde}\nO que mudar: ${resposta.trim()}`
}

/** 141-3: no modo estreito anda um cartão por vez; o índice dá a volta nas pontas. */
export function andar(i: number, total: number, passo: number): number {
  if (total <= 0) return 0
  return ((i + passo) % total + total) % total
}

/** 141-3: modo estreito quando a janela tem meia tela (< 760 px) ou o laudo editável está aberto em outra janela. */
function useEstreito(): boolean {
  const mq = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(max-width: 760px)') : null
  const [pequena, setPequena] = useState(!!mq?.matches)
  const [editavel, setEditavel] = useState(false)
  useEffect(() => {
    const m = () => setPequena(!!mq?.matches)
    const a = () => setEditavel(true), f = () => setEditavel(false)
    mq?.addEventListener('change', m)
    window.addEventListener('jdb-editavel-aberto', a); window.addEventListener('jdb-editavel-fechado', f)
    return () => { mq?.removeEventListener('change', m); window.removeEventListener('jdb-editavel-aberto', a); window.removeEventListener('jdb-editavel-fechado', f) }
  }, [])            // eslint-disable-line react-hooks/exhaustive-deps
  return pequena || editavel
}

function VerNoPdf({ jobId, erro, aoFechar }: { jobId: string; erro: Erro; aoFechar: () => void }) {
  const lugares = erro.lugares.length ? erro.lugares : [{ pagina: erro.pagina, trecho: '' }]
  const [i, setI] = useState(0)
  const [url, setUrl] = useState('')
  const [falha, setFalha] = useState('')
  const fechar = useRef<HTMLButtonElement>(null)
  useEffect(() => { fechar.current?.focus() }, [])
  useEffect(() => {
    let u = ''
    const l = lugares[i]
    setUrl(''); setFalha('')
    if (!l?.pagina) { setFalha('Não sei a página deste erro.'); return }
    const q = new URLSearchParams({ n: String(l.pagina), trecho: l.trecho || '', largura: '900' })
    baixarRaw(`/jobs/${encodeURIComponent(jobId)}/pdf/pagina?${q}`)
      .then(({ blob }) => { u = URL.createObjectURL(blob); setUrl(u) })
      .catch((e) => setFalha(e instanceof ApiError ? e.message : 'Não consegui abrir a página.'))
    return () => { if (u) URL.revokeObjectURL(u) }
  }, [i, jobId])          // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div role="dialog" aria-modal="true" aria-label={`Erro ${erro.n} no PDF`}
         style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)', zIndex: 50, display: 'flex',
                  alignItems: 'center', justifyContent: 'center', padding: 16 }}
         onClick={aoFechar} onKeyDown={(e) => { if (e.key === 'Escape') aoFechar() }}>
      <div className="cartao-pad" style={{ background: '#fff', maxWidth: 960, width: '100%', maxHeight: '92vh', overflow: 'auto' }}
           onClick={(e) => e.stopPropagation()}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="texto"><b>{erro.n}</b> · Pág. {lugares[i]?.pagina ?? '—'} — {erro.titulo}</p>
          <div className="flex items-center gap-2">
            {lugares.length > 1 && (
              <button type="button" className="btn-sec-grande" style={{ width: 'auto' }}
                      onClick={() => setI((i + 1) % lugares.length)}>{i + 1} de {lugares.length} ›</button>
            )}
            <button ref={fechar} type="button" className="btn-sec-grande" style={{ width: 'auto' }} onClick={aoFechar}>
              <X size={20} aria-hidden="true" /> Fechar</button>
          </div>
        </div>
        {falha ? <p className="aviso-simples">{falha}</p>
          : url ? <img src={url} alt={`Página ${lugares[i]?.pagina} do laudo, com o trecho marcado em amarelo`} style={{ width: '100%' }} />
          : <p className="texto" role="status">Abrindo a página…</p>}
      </div>
    </div>
  )
}

/** 142: [Ir para a pág. N] abre (ou volta à) aba do laudo editável já na página — a aba é do editor (abrirEditavel). */
export function irParaPagina(jobId: string, pagina: number | null, trecho = '') {
  // 169: com o Google ligado abre o Google Docs (a âncora exata vem com a parte do outro executor); senão, o editor do JdB
  abrirOuAvisar(jobId, pagina ?? undefined, trecho.slice(0, 80))
  window.dispatchEvent(new CustomEvent('jdb-editavel-aberto'))
  return true
}

/** 142-4: o contador conta o que a conferência por regra já não acha (depois de usar o documento) + "deixar como está". */
export function contarResolvidos(total: number, deixados: number, restamNaConferencia: number | null): number {
  const pela = restamNaConferencia == null ? 0 : Math.max(0, total - restamNaConferencia)
  return Math.min(total, Math.max(pela, deixados))
}

export default function ListaErros({ jobId, erros, aoMudar, aoConferir }: {
  jobId: string; erros: Erro[]; aoMudar: (m: string) => void
  aoConferir?: () => Promise<void>        // 143: passa para "Revisão humana — sua vez" (o mesmo "seguir" do cartão)
}) {
  const [feitos, setFeitos] = useState<Record<number, string>>({})        // só as ações de imagem (D-148)
  const [ver, setVer] = useState<Erro | null>(null)
  const [deixados, setDeixados] = useState<Record<number, boolean>>({})
  const [ocupado, setOcupado] = useState(false)
  const [erroEnvio, setErroEnvio] = useState('')
  const [restam, setRestam] = useState<number | null>(null)
  const [, setUsando] = useState(false)
  const [achou, setAchou] = useState('')          // 143-3: o que a conferência por regra achou e impede de seguir
  const espera = useRef<number | undefined>(undefined)
  const conferir = useRef(aoConferir)
  conferir.current = aoConferir
  const aoMudarRef = useRef(aoMudar)
  aoMudarRef.current = aoMudar
  const nDeixados = erros.filter((e) => deixados[e.n]).length
  const n = contarResolvidos(erros.length, nDeixados, restam)
  const estreito = useEstreito()
  const [atual, setAtual] = useState(0)
  const idx = Math.min(atual, Math.max(erros.length - 1, 0))
  const visiveis = estreito ? erros.slice(idx, idx + 1) : erros

  useEffect(() => {                      // a resposta do [Usar este documento como laudo] (feito pelo quadro do editável)
    let c: BroadcastChannel | null = null
    try {
      c = new BroadcastChannel(canalEditor(jobId))
      c.onmessage = (ev) => {
        const m = ev.data as { tipo?: string; texto?: string; diferencas?: number; bloqueia?: number; ok?: boolean; sem_mudanca?: boolean } | null
        if (m?.tipo === 'revisao_humana') {     // 164: outra aba passou o trabalho à revisão humana — esta vai junto, sem F5
          window.clearTimeout(espera.current); setUsando(false); setErroEnvio('')
          aoMudarRef.current('O laudo passou para a revisão humana.')
          return
        }
        if (m?.tipo !== 'usado') return
        window.clearTimeout(espera.current)
        if (typeof m.diferencas === 'number') setRestam(m.diferencas)
        if (m.ok === false && !m.sem_mudanca) { setUsando(false); setErroEnvio(m.texto || 'Não consegui gerar o PDF. Tente de novo.'); return }
        if ((m.bloqueia ?? 0) > 0) {              // 143-3: número diferente da planilha ou imagem faltando — não passa
          setUsando(false); setAchou(m.texto || 'A conferência achou um número diferente da planilha.'); return
        }
        setUsando(false)                  // 162-2: a passagem à revisão é feita só pela aba que gerou o PDF (abaixo)
      }
    } catch { /* sem canal */ }
    return () => { c?.close(); window.clearTimeout(espera.current) }
  }, [jobId])

  useEffect(() => {                      // 162-2: só a aba do JdB que GEROU o PDF passa à revisão humana (duas abas abertas
    const ouvir = (ev: Event) => {       // no mesmo trabalho não fazem a passagem em dobro)
      const m = (ev as CustomEvent).detail as { jobId?: string; ok?: boolean; sem_mudanca?: boolean; bloqueia?: number; texto?: string } | null
      if (!m || m.jobId !== jobId) return
      // 164: trabalho cujo editável nunca foi aberto = nada mudou no documento → vale a palavra do avaliador (143-4)
      const semCopia = m.ok === false && /n[ãa]o h[áa] c[óo]pia edit[áa]vel/i.test(m.texto ?? '')
      if (m.ok === false && !m.sem_mudanca && !semCopia) {
        window.clearTimeout(espera.current); setUsando(false)
        setErroEnvio(m.texto || 'Não consegui gerar o PDF. Tente de novo.')     // nunca um toque sem resposta
        return
      }
      if ((m.bloqueia ?? 0) > 0) return
      // conferido (ou nada mudou no documento: a palavra do avaliador basta, 143-4) → revisão humana
      void (conferir.current ? conferir.current() : Promise.resolve())
        .then(() => {                     // 149-1: a aba do editável mostra "Pronto" e o botão de voltar ao JdB
          try { const k = new BroadcastChannel(canalEditor(jobId)); k.postMessage({ tipo: 'revisao_humana' }); k.close() } catch { /* sem canal */ }
        })
        .finally(() => setUsando(false))
    }
    window.addEventListener('jdb-editavel-usado', ouvir)
    return () => window.removeEventListener('jdb-editavel-usado', ouvir)
  }, [jobId])

  async function aplicarImagem(e: Erro) {   // D-148: mapa e foto não se resolvem colando — o sistema refaz só a imagem
    const a = acaoDeImagem(e)
    if (!a) return
    setOcupado(true); setErroEnvio('')
    try {
      await post(`/jobs/${encodeURIComponent(jobId)}/corrigir`, { texto: pedidoDoErro(e, a.pedido), virar_regra: false })
      setFeitos((f) => ({ ...f, [e.n]: `${a.rotulo}: pedido enviado.` }))
      aoMudar(`${a.rotulo}: pedido enviado.`)
    } catch (x) {
      setErroEnvio(x instanceof ApiError ? (x.status === 409 ? 'Aguarde o laudo terminar de montar.' : x.message) : 'Não deu certo. Tente de novo.')
    } finally { setOcupado(false) }
  }

  return (
    <div className="grid gap-3">
      <BaixarRevisao jobId={jobId} aoConcluir={aoMudar} />{/* 172-2: o download para a revisão humana conclui */}
      {estreito && erros.length > 1 && (
        // 141-3: meia tela — um cartão por vez em destaque, com o contador e [Anterior]/[Próximo] grandes
        <div className="flex items-center justify-between gap-2" role="group" aria-label="Andar entre os pontos">
          <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} onClick={() => setAtual(andar(idx, erros.length, -1))}>
            <ChevronLeft size={22} aria-hidden="true" /> Anterior</button>
          <span className="texto" role="status"><b>{idx + 1} de {erros.length}</b></span>
          <button type="button" className="btn-verde" style={{ width: 'auto' }} onClick={() => setAtual(andar(idx, erros.length, 1))}>
            Próximo <ChevronRight size={22} aria-hidden="true" /></button>
        </div>
      )}
      <ol className="grid gap-3" style={{ listStyle: 'none', padding: 0 }}>
        {visiveis.map((e) => (
          // 139-1: o cartão se destaca do painel. 142-3: o cartão é só âncora — achar o lugar e copiar; a mudança é no documento
          <li key={e.n} className="cartao-pad cartao-erro" style={{ marginBottom: 6 }}>
            <p className="texto">
              <b aria-label={`Ponto ${e.n}`} style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                minWidth: 36, height: 36, borderRadius: 18, background: '#18283B', color: '#F5B800', fontSize: 20, marginRight: 10 }}>{e.n}</b>
              {e.titulo}
            </p>
            {e.explicacao && <p className="texto">{e.explicacao}</p>}
            {(e.pagina || e.item) && (
              <p className="small-jdb">{[e.pagina ? `Página ${e.pagina}` : '', e.item ? `item ${e.item}` : ''].filter(Boolean).join(' · ')}</p>
            )}
            {e.tipo === 'pedido' && e.no_laudo && <p className="small-jdb">{e.no_laudo}</p>}
            <Ancora e={e} />
            {deixados[e.n] ? (
              <p className="small-jdb flex flex-wrap items-center gap-2" role="status">Fica como está.
                <button type="button" className="link-jdb" onClick={() => setDeixados((d) => ({ ...d, [e.n]: false }))}>mudar</button>
              </p>
            ) : feitos[e.n] ? (
              <p className="aviso-simples flex flex-wrap items-center gap-2" role="status"><Check size={20} aria-hidden="true" /> {feitos[e.n]}</p>
            ) : null}
            <div className="flex flex-wrap items-center gap-2" style={{ marginTop: 8 }}>
              {acaoDeImagem(e) && !feitos[e.n] && !deixados[e.n] && (
                <button type="button" className="btn-verde" style={{ width: 'auto' }} disabled={ocupado}
                        onClick={() => void aplicarImagem(e)}>{acaoDeImagem(e)!.rotulo}</button>
              )}
              {(e.lugares.length > 0 || e.pagina) && (
                <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} onClick={() => setVer(e)}>
                  <FileSearch size={20} aria-hidden="true" /> Mostrar no PDF</button>
              )}
              {!feitos[e.n] && !deixados[e.n] && (
                <button type="button" className="link-jdb" onClick={() => setDeixados((d) => ({ ...d, [e.n]: true }))}>deixar como está</button>
              )}
            </div>
          </li>
        ))}
      </ol>
      {/* 142-4: rodapé sempre à vista — sem campos, o botão principal é usar o documento editado como laudo */}
      <div className="flex flex-wrap items-center gap-3"
           style={{ position: 'sticky', bottom: 0, background: '#fff', padding: '12px 0', borderTop: '1px solid #e7e1d8', zIndex: 5 }}>
        {/* 172-2: o botão principal é o [Baixar para a revisão humana] (acima); aqui, só a contagem */}
        <BaixarRevisao jobId={jobId} aoConcluir={aoMudar} compacto />
        <span className="small-jdb" role="status">{n} de {erros.length} resolvidos</span>
      </div>
      {achou && <p className="aviso-impede" role="alert">{achou}</p>}
      {erroEnvio && <p className="aviso-impede" role="alert">{erroEnvio}</p>}
      {ver && <VerNoPdf jobId={jobId} erro={ver} aoFechar={() => setVer(null)} />}
    </div>
  )
}

/** 138: o cartão como âncora — o trecho a procurar no documento (Ctrl+F) e a sugestão, cada um com [Copiar]. */
function Ancora({ e }: { e: Erro }) {
  const [copiado, setCopiado] = useState('')
  const trecho = (e.frase || e.lugares.find((l) => l.trecho)?.trecho || e.no_laudo.replace(/^.*?«|».*$/g, '') || '')
    .replace(/\s*\(_revisao\/[^)]*\)/g, '').replace(/^[\s.,;:–—-]+/, '').trim()   // 141: nunca nome de arquivo interno no trecho
  async function copiar(txt: string, qual: string) {
    try { await navigator.clipboard.writeText(txt); setCopiado(qual) } catch { setCopiado('erro') }
  }
  if (!trecho && !e.sugestao) return null
  return (
    <div className="grid gap-1" style={{ background: '#faf6ef', borderRadius: 8, padding: '8px 12px' }}>
      {trecho && (
        <p className="texto flex flex-wrap items-center gap-2">
          <span>No Word, procure (Ctrl+F): <b>«{trecho.slice(0, 100)}»</b>{e.pagina ? ` — pág. ${e.pagina}` : ''}{e.item ? `, item ${e.item}` : ''}{(e.frase_vezes ?? 1) > 1 ? ` (aparece ${e.frase_vezes} vezes no Word)` : ''}</span>
          <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} onClick={() => void copiar(trecho.slice(0, 100), 'trecho')}>Copiar a frase</button>
        </p>
      )}
      {e.sugestao && (
        <p className="texto flex flex-wrap items-center gap-2">
          <span>Sugestão para colar: <b>{e.sugestao}</b></span>
          <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} onClick={() => void copiar(e.valor_sugerido || e.sugestao, 'sugestao')}>Copiar a sugestão</button>
        </p>
      )}
      {copiado && <p className="small-jdb" role="status">{copiado === 'erro' ? 'Não consegui copiar: selecione o texto e use Ctrl+C.'
        : copiado === 'trecho' ? 'Copiado. No Word, aperte Ctrl+F e cole (Ctrl+V).' : 'Copiado. Cole no Word com Ctrl+V.'}</p>}
    </div>
  )
}
