import { AlertTriangle, Check, Circle, Loader2, OctagonX, UserCheck } from 'lucide-react'
import type { EstadoEtapa, LinhaEtapa } from './etapas'
import { TEXTO_AGUARDANDO_ESCOLHA } from './rotulos'

const ROTULO_ESTADO: Record<EstadoEtapa, string> = {
  pendente: 'Pendente',
  rodando: 'Em andamento',
  concluida: 'Concluída',
  erro: 'Erro',
  aguardando_avaliador: 'Aguardando sua confirmação',
  bloqueado: 'Bloqueado — pendência do avaliador',
}

function Marcador({ estado }: { estado: EstadoEtapa }) {
  const base = 'flex h-7 w-7 shrink-0 items-center justify-center rounded-full'
  switch (estado) {
    case 'concluida':
      return <span className={`${base} bg-emerald-100 text-emerald-700`}><Check size={16} aria-hidden="true" /></span>
    case 'rodando':
      return <span className={`${base} bg-sky-100 text-sky-700`}><Loader2 size={16} className="animate-spin" aria-hidden="true" /></span>
    case 'erro':
      return <span className={`${base} bg-red-100 text-red-700`}><AlertTriangle size={15} aria-hidden="true" /></span>
    case 'bloqueado':
      return <span className={`${base} bg-amber-100 text-red-700`}><OctagonX size={15} aria-hidden="true" /></span>
    case 'aguardando_avaliador':
      return <span className={`${base} bg-amber-100 text-amber-700`}><UserCheck size={15} aria-hidden="true" /></span>
    default:
      return <span className={`${base} bg-stone-100 text-stone-400`}><Circle size={12} aria-hidden="true" /></span>
  }
}

export default function LinhaDoTempo({ etapas }: { etapas: LinhaEtapa[] }) {
  return (
    <ol className="relative">
      {etapas.map((e, i) => (
        <li key={e.id} className="relative flex gap-3 pb-5 last:pb-0" aria-current={e.estado === 'rodando' ? 'step' : undefined}>
          {i < etapas.length - 1 && (
            <span className={`absolute left-[13px] top-7 h-[calc(100%-1.75rem)] w-px ${
              e.estado === 'concluida' ? 'bg-emerald-300' : 'bg-stone-200'}`} aria-hidden="true" />
          )}
          <Marcador estado={e.estado} />
          <div className="min-w-0 flex-1 pt-0.5">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className={`text-sm font-medium ${e.estado === 'pendente' ? 'text-stone-500' : 'text-stone-900'}`}>
                {e.rotulo}
              </span>
              <span className="text-xs text-stone-500">
                {e.estado === 'aguardando_avaliador' && e.id === 'pesquisa' ? TEXTO_AGUARDANDO_ESCOLHA : ROTULO_ESTADO[e.estado]}
              </span>
            </div>
            {e.estado === 'aguardando_avaliador' && (
              <p className="mt-1 rounded-md bg-amber-50 px-2.5 py-1.5 text-xs text-amber-900 ring-1 ring-inset ring-amber-600/20">
                {e.id === 'pesquisa'
                  ? 'Marque pelo menos 5 anúncios no quadro “Candidatos a referencial” e toque em “Continuar com os escolhidos”.'
                  : 'Confirme os referenciais e o valor unitário no quadro “Confirmar valor”.'}
              </p>
            )}
            {e.estado === 'bloqueado' && (
              <p className="mt-1 rounded-md bg-amber-50 px-2.5 py-1.5 text-xs text-amber-900 ring-1 ring-inset ring-amber-600/20">
                O trabalho parou aqui. Veja as pendências, corrija e toque em “Conferir os documentos de novo”.
              </p>
            )}
            {e.estado === 'erro' && e.mensagem && <p className="mt-0.5 break-words text-xs text-red-700">{e.mensagem}</p>}
            {e.estado === 'pendente' && e.mensagem && <p className="mt-0.5 text-xs text-stone-500">{e.mensagem}</p>}
            {e.avisos.map((a) => <p key={a} className="mt-0.5 break-words text-xs text-amber-800">Aviso: {a}</p>)}
          </div>
        </li>
      ))}
    </ol>
  )
}
