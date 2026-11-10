/* Identidade do João de Barro: o ninho de barro (casa do pássaro) e os estados de carregamento. */

/** Marca: ninho de barro em forma de forno, com a entrada lateral. */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
      <rect width="32" height="32" rx="8" fill="var(--barro)" />
      <path d="M6.5 23.5c0-8.2 4.1-14.5 9.5-14.5s9.5 6.3 9.5 14.5z" fill="#fbf1e9" />
      <ellipse cx="16" cy="19.2" rx="3.4" ry="4.3" fill="var(--barro-esc)" />
      <path d="M5 24h22" stroke="#fbf1e9" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  )
}

export function Marca({ grande }: { grande?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <Logo size={grande ? 40 : 28} />
      <span className="leading-tight">
        <span className={`block font-semibold tracking-tight text-stone-900 ${grande ? 'text-2xl' : 'text-base'}`}>João de Barro</span>
        {grande && <span className="block text-sm text-stone-500">Avaliação de imóveis</span>}
      </span>
    </span>
  )
}

/** Linhas de esqueleto enquanto os dados chegam. */
export function Esqueleto({ linhas = 3, rotulo = 'Carregando…' }: { linhas?: number; rotulo?: string }) {
  return (
    <div className="cartao-pad space-y-3" role="status" aria-live="polite">
      <span className="sr-only">{rotulo}</span>
      {Array.from({ length: linhas }, (_, i) => (
        <div key={i} className="flex items-center gap-3" aria-hidden="true">
          <span className="osso h-9 w-9 rounded-full" />
          <span className="flex-1 space-y-2">
            <span className="osso block h-3" style={{ width: `${70 - i * 12}%` }} />
            <span className="osso block h-2.5" style={{ width: `${45 - i * 6}%` }} />
          </span>
        </div>
      ))}
    </div>
  )
}
