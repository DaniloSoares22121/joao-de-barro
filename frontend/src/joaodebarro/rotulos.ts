/* Rótulos e formatadores pt-BR do João de Barro (lógica pura, sem React). */

/** Etapas na ordem do backend (orquestrador.ETAPAS). */
export const ETAPAS: ReadonlyArray<{ id: string; rotulo: string }> = [
  { id: 'triagem', rotulo: 'Triagem dos documentos' },
  { id: 'extracao', rotulo: 'Extração de dados' },
  { id: 'pesquisa', rotulo: 'Pesquisa de referenciais' },
  { id: 'selecao', rotulo: 'Seleção de referenciais' },
  { id: 'calculo', rotulo: 'Cálculo do valor' },
  { id: 'redacao', rotulo: 'Redação do laudo' },
  { id: 'montagem', rotulo: 'Montagem dos arquivos' },
  { id: 'revisao', rotulo: 'Revisão' },
  { id: 'entrega', rotulo: 'Entrega' },
]

export const STATUS_PRONTO = 'PRONTO PARA REVISÃO'
export const STATUS_PARCIAL = 'PARCIAL — PENDÊNCIAS'
export const STATUS_BLOQUEADO = 'BLOQUEADO'
export const STATUS_FINAIS: readonly string[] = [STATUS_PRONTO, STATUS_PARCIAL, STATUS_BLOQUEADO]

export const MODALIDADES = [
  { id: 'OV', rotulo: 'Opinião de Valor' },
  { id: 'AM', rotulo: 'PTAM' },
  { id: 'AM_GARANTIA', rotulo: 'PTAM — Garantia' },
  { id: 'AMJ', rotulo: 'PTAM Judicial' },
] as const

export function modalidade(m: string | null | undefined): string {
  return MODALIDADES.find((x) => x.id === m)?.rotulo ?? (m || '—')
}

/** Rótulo da etapa atual do job (inclui os estados que não são etapas do pipeline). */
export function etapaRotulo(id: string | null | undefined): string {
  if (!id || id === 'nova') return 'Aguardando início'
  if (id === 'aguardando_coletor') return 'Aguardando o Coletor'
  return ETAPAS.find((e) => e.id === id)?.rotulo ?? id
}

export type Tom = 'ok' | 'aviso' | 'erro' | 'andamento' | 'neutro'

/** Texto e tom do status do job. Os três status finais saem exatamente como o backend grava. */
export function statusInfo(status: string | null | undefined): { texto: string; tom: Tom } {
  switch (status) {
    case STATUS_PRONTO: return { texto: STATUS_PRONTO, tom: 'ok' }
    case STATUS_PARCIAL: return { texto: STATUS_PARCIAL, tom: 'aviso' }
    case STATUS_BLOQUEADO: return { texto: STATUS_BLOQUEADO, tom: 'erro' }
    case 'executando': return { texto: 'Em andamento', tom: 'andamento' }
    case 'aguardando': return { texto: 'Aguardando o Coletor', tom: 'aviso' }
    case 'pendente': return { texto: 'Na fila', tom: 'neutro' }
    default: return { texto: status || '—', tom: 'neutro' }
  }
}

export function ehFinal(status: string | null | undefined): boolean {
  return !!status && STATUS_FINAIS.includes(status)
}

const fmtMoeda = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' })
const fmtNum = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2, minimumFractionDigits: 2 })

/** Valores monetários chegam do backend como string decimal ("123456.00") ou número. */
export function moeda(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? fmtMoeda.format(n) : String(v)
}

export function numero2(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? fmtNum.format(n) : String(v)
}

/** "2026-10-20" ou ISO completo → "20/10/2026". */
export function dataBR(iso: string | null | undefined): string {
  if (!iso) return '—'
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso
}

/** ISO com hora → "20/10/2026 14:05" (horário local). */
export function dataHoraBR(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}

/** Rodapé do trabalho: "12 chamadas de IA · US$ 0,84 · 3 min 20 s". */
export function textoResumoIA(r: { chamadas: number; custo_usd: number; tempo_s: number }): string {
  const s = Math.round(r.tempo_s)
  const tempo = s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`
  const custo = `US$ ${r.custo_usd.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  return `${r.chamadas} chamada${r.chamadas === 1 ? '' : 's'} de IA · ${custo} · ${tempo}`
}

/** "selecao: áreas divergentes…" → "Seleção de referenciais: áreas divergentes…" (as pendências
 * nascem no servidor com o id da etapa na frente). */
export function textoPendencia(texto: string): string {
  const m = /^([a-z_]+): /.exec(texto)
  const etapa = m && ETAPAS.find((e) => e.id === m[1])
  return etapa ? `${etapa.rotulo}: ${texto.slice(m![0].length)}` : texto
}
