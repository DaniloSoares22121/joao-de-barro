/* Executa todos os *.test.ts do João de Barro: `npm.cmd run test:joaodebarro`. */
import type { Falha } from './testar'
import { testes as campo } from './campo.test'
import { testes as controle } from './controle.test'
import { testes as logica } from './logica.test'
import { testes as validacao } from './validacao.test'

declare const process: { exit(codigo: number): never }

const suites: Record<string, () => Falha[] | Promise<Falha[]>> = {
  validacao,
  logica,
  campo,
  controle,
}

let total = 0
for (const [nome, fn] of Object.entries(suites)) {
  const falhas = await fn()
  total += falhas.length
  console.log(`${falhas.length === 0 ? 'OK   ' : 'FALHA'} ${nome}`)
  for (const m of falhas) console.log(`   - ${m}`)
}
process.exit(total === 0 ? 0 : 1)
