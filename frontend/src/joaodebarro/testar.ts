/* Micro-harness de testes (o repo não tem vitest). Cada *.test.ts exporta `testes(): Falha[]`;
 * rode com `npm.cmd run test:joaodebarro` (esbuild empacota e o Node executa). */

export type Falha = string

export function verifica(falhas: Falha[], nome: string, ok: boolean, detalhe?: unknown): void {
  if (!ok) falhas.push(detalhe === undefined ? nome : `${nome} — obtido: ${JSON.stringify(detalhe)}`)
}

export function igual<T>(falhas: Falha[], nome: string, obtido: T, esperado: T): void {
  const a = JSON.stringify(obtido)
  const b = JSON.stringify(esperado)
  if (a !== b) falhas.push(`${nome} — esperado ${b}, obtido ${a}`)
}
