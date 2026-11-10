/* Testes da lógica de campo: compressão, rotas por hash, retry, busca/filtro, prefill. */
import {
  ATRASOS_UPLOAD_MS, atrasoRetry, comRetry, dimensoesAlvo, ehImagemComprimivel, filtrarJobs, hashDe, lerHash,
  nomeJpeg, prefillDe, statusPresentes,
} from './campo'
import { igual, verifica, type Falha } from './testar'

const MB = 1024 * 1024

export async function testes(): Promise<Falha[]> {
  const f: Falha[] = []

  // compressão
  igual(f, 'pequena e leve: intacta', dimensoesAlvo(1600, 1200, 1 * MB), null)
  igual(f, 'lado > 2000: reduz', dimensoesAlvo(4000, 3000, 1 * MB), { w: 2000, h: 1500 })
  igual(f, 'retrato > 2000', dimensoesAlvo(3024, 4032, 3 * MB), { w: 1500, h: 2000 })
  igual(f, 'pesada mas pequena: recomprime sem ampliar', dimensoesAlvo(1800, 1000, 2 * MB), { w: 1800, h: 1000 })
  igual(f, 'exatamente 2000 e 1,5 MB: intacta', dimensoesAlvo(2000, 1000, 1.5 * MB), null)
  igual(f, 'dimensão inválida', dimensoesAlvo(0, 100, 5 * MB), null)
  verifica(f, 'pdf não comprime', !ehImagemComprimivel('application/pdf'))
  verifica(f, 'jpeg comprime', ehImagemComprimivel('image/jpeg') && ehImagemComprimivel('image/PNG'))
  verifica(f, 'gif/svg não comprimem', !ehImagemComprimivel('image/gif') && !ehImagemComprimivel('image/svg+xml'))
  igual(f, 'nomeJpeg', [nomeJpeg('IMG_1.HEIC'), nomeJpeg('a.b.png'), nomeJpeg('semext')], ['IMG_1.jpg', 'a.b.jpg', 'semext.jpg'])

  // rotas
  igual(f, 'hash vazio', lerHash(''), { tela: 'lista', jobId: null })
  igual(f, '#/', lerHash('#/'), { tela: 'lista', jobId: null })
  igual(f, '#/novo', lerHash('#/novo'), { tela: 'novo', jobId: null })
  igual(f, '#/config', lerHash('#/config'), { tela: 'config', jobId: null })
  igual(f, '#/job/id', lerHash('#/job/ab%2Fc'), { tela: 'job', jobId: 'ab/c' })
  igual(f, '#/job sem id', lerHash('#/job/'), { tela: 'lista', jobId: null })
  igual(f, 'lixo', lerHash('#/xyz'), { tela: 'lista', jobId: null })
  for (const [t, id] of [['lista', null], ['novo', null], ['config', null], ['job', 'x y']] as const) {
    igual(f, `ida e volta ${t}`, lerHash(hashDe(t, id)), { tela: t, jobId: id })
  }

  // retry
  igual(f, 'backoff 1/3/9 s', ATRASOS_UPLOAD_MS, [1000, 3000, 9000])
  igual(f, 'rede: retenta 3x', [1, 2, 3, 4].map((n) => atrasoRetry(0, n)), [1000, 3000, 9000, null])
  igual(f, 'http: não retenta', [atrasoRetry(500, 1), atrasoRetry(413, 1)], [null, null])
  {
    let chamadas = 0
    const esperas: number[] = []
    const r = await comRetry(async () => {
      chamadas += 1
      if (chamadas < 3) throw { status: 0 }
      return 'ok'
    }, async (ms) => { esperas.push(ms) })
    igual(f, 'comRetry recupera', [r, chamadas, esperas], ['ok', 3, [1000, 3000]])
  }
  {
    let chamadas = 0
    const esperas: number[] = []
    let erro: unknown = null
    try {
      await comRetry(async () => { chamadas += 1; throw { status: 0 } }, async (ms) => { esperas.push(ms) })
    } catch (e) { erro = e }
    igual(f, 'comRetry desiste após 4 tentativas', [chamadas, esperas, erro], [4, [1000, 3000, 9000], { status: 0 }])
  }
  {
    let chamadas = 0
    try { await comRetry(async () => { chamadas += 1; throw { status: 409 } }, async () => undefined) } catch { /* esperado */ }
    igual(f, 'comRetry não retenta 409', chamadas, 1)
  }

  // lista
  const jobs = [
    { numero: 121, status: 'BLOQUEADO', cliente: 'José Antônio', bairro: 'Setor Bueno' },
    { numero: 122, status: 'executando', cliente: 'Maria', bairro: 'Jardim Goiás' },
    { numero: 210, status: 'BLOQUEADO', cliente: null, bairro: 'Centro' },
  ]
  igual(f, 'busca por nº', filtrarJobs(jobs, '12', '').map((j) => j.numero), [121, 122])
  igual(f, 'busca sem acento', filtrarJobs(jobs, 'jose antonio', '').map((j) => j.numero), [121])
  igual(f, 'busca bairro', filtrarJobs(jobs, 'GOIAS', '').map((j) => j.numero), [122])
  igual(f, 'filtro status', filtrarJobs(jobs, '', 'BLOQUEADO').map((j) => j.numero), [121, 210])
  igual(f, 'busca + status', filtrarJobs(jobs, 'centro', 'executando'), [])
  igual(f, 'status presentes', statusPresentes(jobs), ['BLOQUEADO', 'executando'])
  igual(f, 'prefill', prefillDe({ numero: 5, cliente: 'A', tipo: 'Casa', bairro: '', cidade: 'Goiânia',
                                  modalidade: 'OV', finalidade: 'Venda', pin_maps: 'x' }),
        { cliente: 'A', tipo: 'Casa', cidade: 'Goiânia', modalidade: 'OV', finalidade: 'Venda' })
  return f
}
