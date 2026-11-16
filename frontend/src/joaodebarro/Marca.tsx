/* ORDEM 052 / D-103: marca do JdB Laudo aprovada pelo Alan (14/11/2026). Só "JdB", nunca o nome
 * por extenso; os arquivos vêm do pacote do designer (jdb-marca/). Sem esticar, sem sombra nem
 * contorno; logo horizontal com 120 px ou mais; símbolo sempre com o pássaro (D-113). */
const MARCA = `${import.meta.env.BASE_URL}jdb-marca/`

/** Símbolo do JdB Laudo: SEMPRE com o pássaro (D-113, Alan 14/11 20h05: "a logo é com o passarinho").
 *  A versão "só ninho" não é mais usada, nem abaixo de 48 px. */
export function Logo({ size = 48, escuro }: { size?: number; escuro?: boolean }) {
  // 072-B: sobre fundo escuro (Aço), a versão "escuro" (pernas e base brancas): a "cor" some no escuro
  return <img src={MARCA + (escuro ? 'jdb-laudo-simbolo-escuro.svg' : 'jdb-laudo-simbolo-cor.svg')} width={size} height={size}
              alt="" aria-hidden="true" className="shrink-0" />
}

/** Logo horizontal do JdB Laudo: versão "escuro" sobre o Aço, colorida sobre fundo claro. */
export function Marca({ grande, claro, largura }: { grande?: boolean; claro?: boolean; largura?: number }) {
  const w = Math.max(120, largura ?? (grande ? 220 : 168))
  return (
    <img src={MARCA + (claro ? 'jdb-laudo-horizontal-escuro.svg' : 'jdb-laudo-horizontal-cor.svg')}
      width={w} height={Math.round((w * 120) / 335)} alt="JdB Laudo" className="logo-jdb" style={{ width: w }} />
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
