/* Estado de cada etapa da linha do tempo, derivado do job (etapa/status) e dos eventos do WS.
 * Lógica pura — testada em logica.test.ts. */
import { ETAPAS, STATUS_AGUARDANDO_AVALIADOR, STATUS_BLOQUEADO, STATUS_ERRO_TECNICO, ehFinal, msgSegura } from './rotulos'

export type EstadoEtapa = 'pendente' | 'rodando' | 'concluida' | 'erro' | 'aguardando_avaliador'
  | 'bloqueado'

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
  /** BLOQUEADO: etapa onde o trabalho parou (pendência do avaliador). Padrão: triagem. */
  paradaEm = 'triagem',
): LinhaEtapa[] {
  const voltas = eventos.filter((e) => e.nivel === 'volta').map((e) => ({ id: e.id, i: etapaDaVolta(e) }))
  const atual = idx(job.etapa)
  const final = ehFinal(job.status)
  const bloqueado = job.status === STATUS_BLOQUEADO
  const iParada = Math.max(0, idx(paradaEm))

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
    } else if (bloqueado) {
      // Bloqueado não é "concluído": até a parada valeu, a parada espera o avaliador, o resto não rodou.
      estado = i < iParada ? (erroAberto ? 'erro' : resultado ? 'concluida' : 'pendente')
        : i === iParada ? 'bloqueado' : 'pendente'
    } else if (final) {
      estado = erroAberto ? 'erro' : (resultado || def.id === 'entrega') ? 'concluida' : 'pendente'
    } else if (i < atual) {
      estado = 'concluida'
    } else if (i === atual) {
      if (erroAberto || job.status === STATUS_ERRO_TECNICO) estado = 'erro'
      else if (job.status === 'executando') estado = 'rodando'
      else if (job.status === STATUS_AGUARDANDO_AVALIADOR) estado = 'aguardando_avaliador'
      else { estado = 'pendente'; mensagem = 'Na fila' }
    }
    if (estado === 'erro' && erro) mensagem = msgSegura(erro.msg)
    return { id: def.id, rotulo: def.rotulo, estado, mensagem, avisos: avisos.map(msgSegura) }
  })
}
