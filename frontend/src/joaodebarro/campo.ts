/* Lógica pura do uso em campo (celular): compressão de fotos, rotas por hash, retry de envio,
 * busca/filtro da lista e "novo a partir deste". Sem React/DOM — testada em campo.test.ts. */
import type { FormTrabalho } from './validacao'

// ------------------------------------------------------------------ compressão
export const LADO_MAX = 2000
export const BYTES_COMPRIMIR = 1.5 * 1024 * 1024
export const QUALIDADE_JPEG = 0.85

/** Tipos que o navegador decodifica de forma confiável no canvas (PDF e outros ficam intactos). */
export function ehImagemComprimivel(tipo: string): boolean {
  return /^image\/(jpeg|png|webp|bmp|heic|heif|avif)$/i.test(tipo)
}

/** Dimensões finais da foto, ou null quando não precisa recomprimir
 * (maior lado ≤ 2000 px e arquivo ≤ 1,5 MB). Mantém a proporção, nunca amplia. */
export function dimensoesAlvo(w: number, h: number, bytes: number,
                              ladoMax = LADO_MAX, limiteBytes = BYTES_COMPRIMIR): { w: number; h: number } | null {
  if (!(w > 0 && h > 0)) return null
  const maior = Math.max(w, h)
  if (maior <= ladoMax && bytes <= limiteBytes) return null
  const k = Math.min(1, ladoMax / maior)
  return { w: Math.max(1, Math.round(w * k)), h: Math.max(1, Math.round(h * k)) }
}

/** "foto.png" → "foto.jpg" (a saída da compressão é sempre JPEG). */
export function nomeJpeg(nome: string): string {
  const base = nome.replace(/\.[^./\\]+$/, '')
  return `${base || 'foto'}.jpg`
}

// ------------------------------------------------------------------ rotas por hash
export type TelaRota = 'lista' | 'novo' | 'job' | 'config'
export interface Rota { tela: TelaRota; jobId: string | null }

/** `#/`, `#/novo`, `#/job/<id>`, `#/config` → rota; qualquer outra coisa → lista. */
export function lerHash(hash: string): Rota {
  const h = hash.replace(/^#/, '').replace(/^\/+/, '')
  const [a, b] = h.split('/')
  if (a === 'novo') return { tela: 'novo', jobId: null }
  if (a === 'config') return { tela: 'config', jobId: null }
  if (a === 'job' && b) {
    let id = b
    try { id = decodeURIComponent(b) } catch { /* mantém cru */ }
    return { tela: 'job', jobId: id }
  }
  return { tela: 'lista', jobId: null }
}

export function hashDe(tela: string, jobId: string | null): string {
  if (tela === 'novo') return '#/novo'
  if (tela === 'config') return '#/config'
  if (tela === 'job' && jobId) return `#/job/${encodeURIComponent(jobId)}`
  return '#/'
}

// ------------------------------------------------------------------ retry de envio
/** Espera antes da 2ª, 3ª e 4ª tentativa (3 novas tentativas após a primeira falha). */
export const ATRASOS_UPLOAD_MS: readonly number[] = [1000, 3000, 9000]

/** Atraso para a nova tentativa após a falha nº `falhas` (1 = primeira), ou null para desistir.
 * Só erro de rede (status 0) é retentado; 4xx/5xx são respostas definitivas. */
export function atrasoRetry(status: number, falhas: number): number | null {
  if (status !== 0 || falhas < 1 || falhas > ATRASOS_UPLOAD_MS.length) return null
  return ATRASOS_UPLOAD_MS[falhas - 1]
}

/** Executa `fn` com retry (atrasoRetry). `esperar` injetável para teste. */
export async function comRetry<T>(fn: () => Promise<T>,
                                  esperar: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms)),
                                  aoRetentar?: (tentativa: number, ms: number) => void): Promise<T> {
  for (let falhas = 1; ; falhas++) {
    try {
      return await fn()
    } catch (e) {
      const st = typeof (e as { status?: unknown })?.status === 'number' ? (e as { status: number }).status : -1
      const ms = atrasoRetry(st, falhas)
      if (ms === null) throw e
      aoRetentar?.(falhas + 1, ms)
      await esperar(ms)
    }
  }
}

// ------------------------------------------------------------------ lista
export interface JobFiltravel {
  numero: number
  status: string
  cliente?: string | null
  bairro?: string | null
}

const normal = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim()

/** Busca por nº, cliente ou bairro (sem acento/caixa) e filtro por status ('' = todos). */
export function filtrarJobs<T extends JobFiltravel>(jobs: readonly T[], busca: string, status: string): T[] {
  const q = normal(busca)
  return jobs.filter((j) => {
    if (status && j.status !== status) return false
    if (!q) return true
    return String(j.numero).includes(q) || normal(j.cliente || '').includes(q) || normal(j.bairro || '').includes(q)
  })
}

/** Status distintos presentes, na ordem de aparição (chips do filtro). */
export function statusPresentes(jobs: readonly JobFiltravel[]): string[] {
  return [...new Set(jobs.map((j) => j.status).filter(Boolean))]
}

export type Prefill = Partial<Pick<FormTrabalho, 'cliente' | 'tipo' | 'bairro' | 'cidade' | 'modalidade' | 'finalidade'>>

/** Campos copiados por "Novo a partir deste" (nº, pin, datas e contexto ficam de fora). */
export function prefillDe(j: Record<string, unknown>): Prefill {
  const out: Prefill = {}
  for (const k of ['cliente', 'tipo', 'bairro', 'cidade', 'modalidade', 'finalidade'] as const) {
    const v = j[k]
    if (typeof v === 'string' && v) out[k] = v
  }
  return out
}
