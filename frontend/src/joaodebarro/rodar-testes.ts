/* Executa todos os *.test.ts do JdB: `npm.cmd run test:joaodebarro`. */
import type { Falha } from './testar'
import { testes as campo } from './campo.test'
import { testes as controle } from './controle.test'
import { testes as logica } from './logica.test'
import { testes as validacao } from './validacao.test'
import { testes as nomesCampos, testesAindaNaoSei } from './nomesCampos.test'

declare const process: { exit(codigo: number): never }

const suites: Record<string, () => Falha[] | Promise<Falha[]>> = {
  validacao,
  logica,
  campo,
  controle,
  nomesCampos,
  testesAindaNaoSei,
}

let total = 0
for (const [nome, fn] of Object.entries(suites)) {
  const falhas = await fn()
  total += falhas.length
  console.log(`${falhas.length === 0 ? 'OK   ' : 'FALHA'} ${nome}`)
  for (const m of falhas) console.log(`   - ${m}`)
}
process.exit(total === 0 ? 0 : 1)
