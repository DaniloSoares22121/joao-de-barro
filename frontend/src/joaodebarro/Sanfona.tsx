/* ORDEM 023-A: caixa sanfona da tela do trabalho (1 linha fechada; 1 aberta por vez). */
import { useEffect, useRef, type ReactNode } from 'react'
import { ArrowRight, ChevronDown } from 'lucide-react'
import { TEXTO_SELO, type Selo } from './caixas'

const COR_SELO: Record<Exclude<Selo, null>, string> = {
  vez: 'bg-[#FFF4CC] text-[#8A6100] ring-[#F5B800]/50',
  pendencias: 'bg-red-50 text-red-800 ring-red-600/20',
  ok: 'bg-emerald-50 text-emerald-800 ring-emerald-600/20',
  aguardando: 'bg-stone-100 text-stone-600 ring-stone-500/20',
}

export function SeloCaixa({ selo }: { selo: Selo }) {
  if (!selo) return null
  return <span className={`chip ${COR_SELO[selo]}`}>{TEXTO_SELO[selo]}</span>
}

export function Caixa({ id, titulo, resumo, selo, aberta, aoAbrir, aoFechar, aoProxima, children }: {
  id: string; titulo: string; resumo?: string; selo: Selo; aberta: boolean
  aoAbrir: () => void; aoFechar: () => void; aoProxima?: () => void; children: ReactNode
}) {
  const ref = useRef<HTMLElement>(null)
  const antes = useRef(aberta)
  useEffect(() => {
    if (aberta && !antes.current) {
      // espera o fechamento da anterior para a posição final estar certa
      requestAnimationFrame(() => ref.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }))
    }
    antes.current = aberta
  }, [aberta])
  const corpo = `caixa-${id}-corpo`
  return (
    <section ref={ref} id={`caixa-${id}`} className={`cartao caixa scroll-mt-32 overflow-hidden ${
      selo === 'vez' && !aberta ? 'ring-1 ring-[#F5B800]' : ''}`}>
      <button type="button" aria-expanded={aberta} aria-controls={corpo}
              onClick={aberta ? aoFechar : aoAbrir}
              className={`foco flex min-h-[52px] w-full items-center gap-3 px-4 py-2.5 text-left sm:px-5 ${
                aberta ? 'border-b border-stone-100' : 'hover:bg-stone-50/80'}`}>
        <span className="min-w-0 flex-1">
          <span className="titulo-caixa block">{titulo}</span>
          {resumo && <span className="block truncate text-sm text-stone-500">{resumo}</span>}
        </span>
        <SeloCaixa selo={selo} />
        <ChevronDown size={18} className={`shrink-0 text-stone-400 transition-transform ${aberta ? 'rotate-180' : ''}`}
                     aria-hidden="true" />
      </button>
      {aberta && (
        <div id={corpo} className="caixa-corpo">
          <div className="space-y-4 px-4 py-4 sm:px-5">{children}</div>
          <div className="flex justify-end gap-2 border-t border-stone-100 px-4 py-2.5 sm:px-5">
            <button type="button" className="btn-sec btn-peq" onClick={aoFechar}>Fechar</button>
            {aoProxima && (
              <button type="button" className="btn btn-peq" onClick={aoProxima}>
                Próxima <ArrowRight size={14} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

/** Faixa fina e fixa no topo: nº/cliente e um chip por caixa (com o selo). */
export function AtalhosCaixas({ titulo, caixas, aberta, aoAbrir }: {
  titulo: string; caixas: { id: string; titulo: string; selo: Selo }[]; aberta: string | null
  aoAbrir: (id: string) => void
}) {
  return (
    <nav aria-label="Caixas do trabalho"
         className="atalhos sticky top-[59px] z-10 -mx-4 border-b border-stone-200 bg-[var(--fundo)]/95 px-4 py-2 backdrop-blur sm:-mx-6 sm:px-6 lg:top-0 lg:-mx-10 lg:px-10">
      <div className="flex items-center gap-2 overflow-x-auto">
        <span className="shrink-0 pr-1 text-sm font-semibold text-stone-900">{titulo}</span>
        {caixas.map((c) => (
          <button key={c.id} type="button" onClick={() => aoAbrir(c.id)} aria-current={aberta === c.id ? 'true' : undefined}
                  className={`foco inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
                    aberta === c.id ? 'border-[#18283B] bg-[#18283B] text-white'
                      : c.selo === 'vez' ? 'border-[#F5B800] bg-[#FFF4CC] text-[#18283B]'
                      : c.selo === 'pendencias' ? 'border-red-200 bg-red-50 text-red-800'
                      : 'border-stone-300 bg-white text-stone-700 hover:border-stone-400'}`}>
            {c.titulo}
          </button>
        ))}
      </div>
    </nav>
  )
}
