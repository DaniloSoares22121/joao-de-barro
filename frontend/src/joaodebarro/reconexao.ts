/* Política de reconexão do WebSocket de acompanhamento: espera 1 → 2 → 5 → 10 s e fica em 10 s. */

export const ATRASOS_MS: readonly number[] = [1000, 2000, 5000, 10000]

/** Espera (ms) antes da tentativa de reconexão nº `tentativa` (0 = primeira falha seguida). */
export function atrasoReconexao(tentativa: number): number {
  const i = Math.min(Math.max(Math.floor(tentativa) || 0, 0), ATRASOS_MS.length - 1)
  return ATRASOS_MS[i]
}
