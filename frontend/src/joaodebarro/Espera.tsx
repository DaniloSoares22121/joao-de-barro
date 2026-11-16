/* 118-3 / ORDEM 123: a animação da espera é a do designer (aprovada pelo Capitão em 15/11) — SVG animado, sem
 * biblioteca, 160 px no computador e 96 no celular; versão clara em fundo claro e escura no Aço (D-114). Nas esperas do
 * laudo, o arquivo da etapa (ninho crescendo, 1 a 7); nas outras esperas, a animação genérica. O próprio SVG respeita
 * "reduzir movimento" (mostra o pássaro parado). Não desenhamos animação nenhuma: só trocamos o arquivo. */
import { useEffect, useRef, useState } from 'react'

const MARCA = `${import.meta.env.BASE_URL}jdb-marca/`

/** Etapa do pipeline → arquivo do designer (1 Ler documentos … 7 Revisar). */
const ETAPA_ARQUIVO: Record<string, number> = {
  triagem: 1, extracao: 2, pesquisa: 3, selecao: 4, calculo: 4, redacao: 5, montagem: 6, revisao: 7, entrega: 7,
}

export function arquivoDaEspera(etapa: string | null | undefined, escuro = false): string {
  const tema = escuro ? 'escuro' : 'claro'
  const n = etapa ? ETAPA_ARQUIVO[etapa] : undefined
  return MARCA + (n ? `jdb-animacao-${tema}-etapa${n}.svg` : `jdb-animacao-${tema}.svg`)
}

/** Quanto tempo desde `desde` (ISO), em palavras: "há 3 min". */
export function haQuanto(desde: string | undefined, agora: number): string {
  const t = desde ? new Date(desde).getTime() : NaN
  if (!Number.isFinite(t)) return ''
  const min = Math.max(0, Math.floor((agora - t) / 60000))
  return min < 1 ? 'agora há pouco' : `há ${min} min`
}

const CSS = `.jdb-espera-img { width: 160px; height: 160px; flex-shrink: 0; }
@media (max-width: 640px) { .jdb-espera-img { width: 96px; height: 96px; } }`

/** ORDEM 124: 1 voo por minuto (o exemplo do designer usa 15 s só para demonstrar). */
export const INTERVALO_VOO = 60_000

export default function Espera({ etapa, escuro = false, desde, voar = true }: {
  etapa?: string | null; escuro?: boolean; desde?: string; voar?: boolean
}) {
  const [agora, setAgora] = useState(() => Date.now())
  const ninho = useRef<HTMLImageElement>(null)
  const passaro = useRef<HTMLImageElement>(null)
  const tema = escuro ? 'escuro' : 'claro'
  const arquivo = arquivoDaEspera(etapa, escuro)
  useEffect(() => {                                   // o "há N min" anda só com a aba visível
    const t = window.setInterval(() => { if (document.visibilityState === 'visible') setAgora(Date.now()) }, 20_000)
    return () => window.clearInterval(t)
  }, [])
  // ORDEM 124: o voo pela tela, como no exemplo-L8-voo.html do designer — o ninho vira o "ninho vazio", o pássaro sai
  // do mesmo ponto do ninho, voa pelo alto da tela (acima do cartão, sem cruzar a lista de etapas nem botões), some pela
  // direita, volta pela esquerda com barro e pousa no mesmo ponto; então o ninho animado volta. Sem voo com "reduzir
  // movimento" e com a aba escondida.
  useEffect(() => {
    if (!voar || typeof window.matchMedia !== 'function' || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let vivo = true
    const voo = () => {
      const n = ninho.current, v = passaro.current
      if (!vivo || !n || !v || document.visibilityState !== 'visible' || typeof v.animate !== 'function') return
      const r = n.getBoundingClientRect()
      const sx = r.left + r.width * 0.45, sy = r.top + r.height * 0.05, W = window.innerWidth
      const alto = Math.max(8, Math.min(30, r.top - 60))    // no celular, o voo fica acima do título
      n.src = `${MARCA}ninho-vazio-${tema}.svg`
      const a = v.animate([{ left: `${sx}px`, top: `${sy}px` }, { left: `${sx + W * 0.25}px`, top: `${alto + 8}px` },
                           { left: `${W * 0.75}px`, top: `${alto}px` }, { left: `${W + 80}px`, top: `${alto + 20}px` }],
                          { duration: 2600, easing: 'ease-in-out' })
      a.onfinish = () => {
        const b = v.animate([{ left: '-120px', top: `${alto + 20}px` }, { left: `${W * 0.3}px`, top: `${alto + 4}px` },
                             { left: `${sx}px`, top: `${sy}px` }], { duration: 2400, easing: 'ease-in-out' })
        b.onfinish = () => { v.style.left = '-120px'; if (ninho.current) ninho.current.src = `${arquivo}?${Date.now()}` }
      }
    }
    const t0 = window.setTimeout(voo, 3000)
    const t = window.setInterval(voo, INTERVALO_VOO)
    return () => { vivo = false; window.clearTimeout(t0); window.clearInterval(t) }
  }, [voar, tema, arquivo])
  return (
    <div className="grid justify-items-center gap-1">
      <style>{CSS}</style>
      <img ref={ninho} className="jdb-espera-img" src={arquivo} alt="" aria-hidden="true" />
      {voar && <img ref={passaro} src={`${MARCA}joao-voando-${tema}.svg`} alt="" aria-hidden="true"
                    style={{ position: 'fixed', width: 50, left: -120, top: 20, zIndex: 50, pointerEvents: 'none' }} />}
      {desde && <span className="small-jdb">{haQuanto(desde, agora)}</span>}
    </div>
  )
}
