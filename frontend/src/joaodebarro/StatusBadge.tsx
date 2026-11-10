import { AlertTriangle, CheckCircle2, Clock, Loader2, OctagonX, PlugZap } from 'lucide-react'
import { STATUS_BLOQUEADO, statusInfo, type Tom } from './rotulos'

const CLASSES: Record<Tom, string> = {
  ok: 'bg-emerald-50 text-emerald-800 ring-emerald-600/20',
  aviso: 'bg-amber-50 text-amber-800 ring-amber-600/25',
  erro: 'bg-red-50 text-red-800 ring-red-600/20',
  andamento: 'bg-sky-50 text-sky-800 ring-sky-600/20',
  neutro: 'bg-stone-100 text-stone-700 ring-stone-500/20',
}

function Icone({ status, tom }: { status: string | null | undefined; tom: Tom }) {
  const p = { size: 12, 'aria-hidden': true } as const
  if (tom === 'ok') return <CheckCircle2 {...p} />
  if (tom === 'andamento') return <Loader2 {...p} className="animate-spin" />
  if (status === STATUS_BLOQUEADO) return <OctagonX {...p} />
  if (status === 'aguardando') return <PlugZap {...p} />
  if (tom === 'aviso' || tom === 'erro') return <AlertTriangle {...p} />
  return <Clock {...p} />
}

export default function StatusBadge({ status }: { status: string | null | undefined }) {
  const { texto, tom } = statusInfo(status)
  return <span className={`chip ${CLASSES[tom]}`}><Icone status={status} tom={tom} />{texto}</span>
}
