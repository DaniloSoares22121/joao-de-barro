/* Estado de cada etapa da linha do tempo, derivado do job (etapa/status) e dos eventos do WS.
 * Lógica pura — testada em logica.test.ts. */
import { ETAPAS, ehFinal } from './rotulos'

export type EstadoEtapa = 'pendente' | 'rodando' | 'concluida' | 'erro' | 'aguardando_coletor'

export interface EventoMin { id: number; etapa: string; nivel: string; msg: string; dados?: unknown }

export interface LinhaEtapa {
  id: string
  rotulo: string
  estado: EstadoEtapa
  /** Texto de apoio: motivo do erro, "na fila"… */
  mensagem?: string
  /** Avisos emitidos nesta execução da etapa. */
  avisos: string[]
}

const idx = (etapa: string) => ETAPAS.findIndex((e) => e.id === etapa)

function etapaDaVolta(e: EventoMin): number {
  const d = e.dados as { etapa?: unknown } | null | undefined
  return d && typeof d.etapa === 'string' ? idx(d.etapa) : -1
}

export function estadoDasEtapas(
  job: { etapa: string; status: string },
  eventos: EventoMin[],
): LinhaEtapa[] {
  const voltas = eventos.filter((e) => e.nivel === 'volta').map((e) => ({ id: e.id, i: etapaDaVolta(e) }))
  const atual = job.etapa === 'aguardando_coletor' ? idx('pesquisa') : idx(job.etapa)
  const final = ehFinal(job.status)

  return ETAPAS.map((def, i) => {
    // Eventos desta etapa anteriores à última "volta" que a invalidou não valem mais.
    const barreira = voltas.reduce((m, v) => (v.i >= 0 && v.i <= i ? Math.max(m, v.id) : m), 0)
    const meus = eventos.filter((e) => e.etapa === def.id && e.id > barreira)
    const ult = (nivel: string) => meus.filter((e) => e.nivel === nivel).reduce<EventoMin | null>(
      (m, e) => (m === null || e.id > m.id ? e : m), null)
    const inicio = ult('inicio')
    const resultado = ult('resultado')
    const erro = ult('erro')
    const erroAberto = !!erro && erro.id > Math.max(inicio?.id ?? 0, resultado?.id ?? 0)
    const avisos = meus.filter((e) => e.nivel === 'aviso' && e.id > (inicio?.id ?? 0)).map((e) => e.msg)

    let estado: EstadoEtapa = 'pendente'
    let mensagem: string | undefined

    if (job.etapa === 'nova' || atual < 0) {
      estado = 'pendente'
    } else if (final) {
      estado = erroAberto ? 'erro' : (resultado || def.id === 'entrega') ? 'concluida' : 'pendente'
    } else if (i < atual) {
      estado = 'concluida'
    } else if (i === atual) {
      if (erroAberto) estado = 'erro'
      else if (job.status === 'executando') estado = 'rodando'
      else if (job.status === 'aguardando' || job.etapa === 'aguardando_coletor') estado = 'aguardando_coletor'
      else { estado = 'pendente'; mensagem = 'Na fila' }
    }
    if (estado === 'erro' && erro) mensagem = erro.msg
    return { id: def.id, rotulo: def.rotulo, estado, mensagem, avisos }
  })
}
