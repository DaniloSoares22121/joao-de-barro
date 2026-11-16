/* Rótulos e formatadores pt-BR do JdB (lógica pura, sem React). */

/** Etapas na ordem do backend (orquestrador.ETAPAS). */
export const ETAPAS: ReadonlyArray<{ id: string; rotulo: string }> = [
  { id: 'triagem', rotulo: 'Separar os documentos' },
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
/** Falha técnica do sistema (não é final: "Tentar de novo" reabre a etapa). */
export const STATUS_ERRO_TECNICO = 'ERRO TÉCNICO'
export const TEXTO_ERRO_TECNICO = 'O sistema teve uma falha técnica. Nada foi perdido.'

/** "Cancelar" do avaliador (ORDEM 007): parado; dá para retomar ("Reabrir") ou excluir. */
export const STATUS_CANCELADO = 'CANCELADO'
export const TEXTO_CANCELADO = 'Trabalho cancelado. O custo de IA já gasto não volta. '
  + 'Toque em “Reabrir” para continuar de onde parou (nada já feito é refeito) ou exclua o trabalho.'

/** Pipeline parado (final, erro técnico ou cancelado): não há nada rodando nem na fila. */
export function parado(status: string | null | undefined): boolean {
  return ehFinal(status) || status === STATUS_ERRO_TECNICO || status === STATUS_CANCELADO
}

/** Mensagem segura para a tela comum: nunca mostra texto técnico (exceções, JSON). */
export function msgSegura(msg: string | null | undefined): string {
  const m = (msg || '').trim()
  return /exception|traceback|json|error:|errno/i.test(m) ? TEXTO_ERRO_TECNICO : textoTela(m)
}

/** ORDEM 064 (D-100/D-101): texto que vem do sistema sem código interno à vista do avaliador.
 * Tira "(D-013)", "(F-S003)", "(K0.5)", "(P3 §6)", "(ORDEM 041)", "D-064" solto; "orquestrador: PENDÊNCIA x"
 * vira "Pendência: x"; "triagem: …" vira "Separar os arquivos: …"; "PENDÊNCIA" e "status" saem do texto. */
export function textoTela(s: string | null | undefined): string {
  let t = (s || '')
  t = t.replace(/\s*\((?:[^()]*?\b)?(?:D-\d{2,3}|F-[A-Z]?\d+|K\d(?:\.\d+)?|P\d{1,2}(?:\s*§\s*\d+)?|ORDEM\s+\d+[A-Z-]*)(?:[^()]*)?\)/g, '')
  t = t.replace(/\s*[—–-]?\s*\b(?:D-\d{3}|F-S\d{3})\b/g, '')
  t = t.replace(/^triagem bloqueada:\s*/i, '')               // o motivo já é uma frase clara
  const m = /^([a-z_]+):\s+(.*)$/s.exec(t)
  if (m) {
    const [, etapa, resto] = m
    const limpo = resto.replace(/^PEND[ÊE]NCIA(?: DO AVALIADOR)?\s*[:—–-]?\s*/i, '')
    if (etapa === 'orquestrador') t = `Pendência: ${limpo}`
    else if (ETAPAS.some((e) => e.id === etapa)) t = `${etapaRotulo(etapa)}: ${limpo}`
  }
  t = t.replace(/\bPEND[ÊE]NCIA\b:?\s*/g, '')
  return t.replace(/\s{2,}/g, ' ').replace(/\s+([.,;:])/g, '$1').trim()
}

/** Etapa a reabrir no "Tentar de novo": a do último evento de erro (ou triagem). */
export function etapaDoErro(eventos: ReadonlyArray<{ id: number; etapa: string; nivel: string }>): string {
  const ult = eventos.filter((e) => e.nivel === 'erro').reduce<{ id: number; etapa: string } | null>(
    (m, e) => (m === null || e.id > m.id ? e : m), null)
  const e = ult?.etapa
  return e && e !== 'entrega' && ETAPAS.some((x) => x.id === e) ? e : 'triagem'
}

/** Etapa onde o trabalho bloqueado parou (prefixo "etapa: " da última pendência; senão triagem). */
export function etapaDoBloqueio(pendencias: ReadonlyArray<{ texto: string }>): string {
  for (let i = pendencias.length - 1; i >= 0; i--) {
    const m = /^([a-z_]+): /.exec(pendencias[i].texto)
    if (m && m[1] !== 'entrega' && ETAPAS.some((e) => e.id === m[1])) return m[1]
  }
  return 'triagem'
}
/** Pipeline parado na seleção esperando o avaliador confirmar referenciais, unitário e faixa. */
export const STATUS_AGUARDANDO_AVALIADOR = 'AGUARDANDO_AVALIADOR'
/** Mesmo status na etapa "pesquisa": esperando o avaliador escolher na lista de candidatos. */
export const TEXTO_AGUARDANDO_ESCOLHA = 'Aguardando sua escolha de referenciais'

export function aguardandoEscolha(job: { etapa: string; status: string }): boolean {
  return job.status === STATUS_AGUARDANDO_AVALIADOR && job.etapa === 'pesquisa'
}

/** Trabalho na fila ou rodando: o servidor recusa edições (409). */
export function emExecucao(job: { etapa: string; status: string }): boolean {
  return job.status === 'executando' || (job.status === 'pendente' && job.etapa !== 'nova')
}

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
  return ETAPAS.find((e) => e.id === id)?.rotulo ?? id
}

export type Tom = 'ok' | 'aviso' | 'erro' | 'andamento' | 'neutro'

/** Texto e tom do status do job (rótulos para o avaliador, não o texto cru do backend). */
export function statusInfo(status: string | null | undefined, etapa?: string | null): { texto: string; tom: Tom } {
  if (status === STATUS_AGUARDANDO_AVALIADOR && etapa === 'pesquisa') return { texto: TEXTO_AGUARDANDO_ESCOLHA, tom: 'aviso' }
  switch (status) {
    case STATUS_PRONTO: return { texto: 'Esperando a sua revisão', tom: 'ok' }   // 125-1f
    case STATUS_PARCIAL: return { texto: 'Laudo gerado com pendências', tom: 'aviso' }
    case STATUS_BLOQUEADO: return { texto: 'Bloqueado — pendência do avaliador', tom: 'erro' }
    case STATUS_ERRO_TECNICO: return { texto: 'Erro técnico', tom: 'erro' }
    case STATUS_CANCELADO: return { texto: 'Cancelado', tom: 'neutro' }
    case 'executando': return { texto: 'Em andamento', tom: 'andamento' }
    case STATUS_AGUARDANDO_AVALIADOR: return { texto: 'Aguardando sua confirmação', tom: 'aviso' }
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
  return textoTela(texto)                                   // 064: sem prefixo técnico nem código de regra
}


/** ORDEM 013 g: só o nome/razão social do solicitante (tela, listas, avisos). O avaliador às
 *  vezes cola a qualificação inteira (CNPJ, sede, representante e CPF) no campo. */
const FIM_NOME = /\s*(?:,|;|\(|\s[-–]\s|\binscrit[ao]\b|\bCNPJ\b|\bCPF\b|\bpessoa jur[ií]dica\b|\bcom sede\b|\bsediad[ao]\b|\bneste ato\b|\brepresentad[ao]\b|\bportador[a]?\b|\bbrasileir[ao]\b)/i
const CPF = /\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b/g
export function nomeSolicitante(cliente: string | null | undefined): string {
  const c = (cliente ?? '').replace(/\s+/g, ' ').trim()
  const nome = c.split(FIM_NOME)[0].replace(CPF, '').replace(/^[\s.,;–-]+|[\s.,;–-]+$/g, '')
  return nome || c.replace(CPF, '').slice(0, 120).trim()
}


/** ORDEM 022: resumo da caixa "Alterar dados extraídos dos documentos". */
export function resumoDadosExtraidos(nCampos: number, nPendentes: number, nImpedem: number): string {
  if (!nCampos) return 'ainda sem dados extraídos'
  const p = nPendentes ? ` · ${nPendentes} pendente${nPendentes === 1 ? '' : 's'}` : ''
  const imp = nImpedem ? ` — ${nImpedem} ${nImpedem === 1 ? 'impede' : 'impedem'} o laudo` : ''
  return `${nCampos} campo${nCampos === 1 ? '' : 's'}${p}${imp}`
}

/** Aberto/fechado lembrado por trabalho (localStorage pode falhar: modo anônimo). */
export const memoria = {
  ler(chave: string): boolean | null {
    try { const v = localStorage.getItem(chave); return v === null ? null : v === '1' } catch { return null }
  },
  gravar(chave: string, aberto: boolean) {
    try { localStorage.setItem(chave, aberto ? '1' : '0') } catch { /* sem armazenamento */ }
  },
  lerTexto(chave: string): string | null {
    try { return localStorage.getItem(chave) } catch { return null }
  },
  gravarTexto(chave: string, v: string | null) {
    try { if (v === null) localStorage.removeItem(chave); else localStorage.setItem(chave, v) } catch { /* idem */ }
  },
}


/** ORDEM 028-2: "1 aviso" / "32 avisos" (nada de "aviso(s)"). */
export function plural(n: number, singular: string, pluralForma: string): string {
  return `${n.toLocaleString('pt-BR')} ${n === 1 ? singular : pluralForma}`
}
