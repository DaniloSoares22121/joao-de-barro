/* ORDEM 053 (L14): "Avisos — Toque para abrir o trabalho." Os avisos que o JdB já registra (041:
 * visita, proposta, teste), o mais novo em cima, com um ponto nos que ainda não foram lidos. Tocar
 * abre a conversa do cliente, quando o aviso tem cliente. */
import { useEffect, useState } from 'react'
import { Bell, CalendarDays, FileText } from 'lucide-react'
import { get } from './api'
import { ativar, testar } from './avisos'
import { useStore } from './store'

interface Aviso { id: number; titulo: string; corpo: string; cliente: string; lido: number; ts: string }

function quando(ts: string) {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  const hoje = new Date()
  const ontem = new Date(hoje.getTime() - 86_400_000)
  const hora = d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
  if (d.toDateString() === hoje.toDateString()) return hora
  if (d.toDateString() === ontem.toDateString()) return 'ontem'
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
}

export default function Avisos() {
  const ir = useStore((s) => s.ir)
  const [lista, setLista] = useState<Aviso[] | null>(null)
  const [msg, setMsg] = useState('')
  useEffect(() => { get<{ avisos: Aviso[] }>('/avisos').then((r) => setLista(r.avisos)).catch(() => setLista([])) }, [])
  return (
    <section className="tela-simples">
      <div>
        <h1 className="titulo-jdb">Avisos</h1>
        <p className="sub-jdb">Toque para abrir o trabalho.</p>
      </div>
      <button type="button" className="btn-sec-grande w-full" onClick={() => void ativar().then(setMsg)}>
        <Bell size={20} aria-hidden="true" /> Ligar avisos neste celular</button>
      {msg && <p className="aviso-simples" role="status">{msg} <button type="button" className="link-discreto" onClick={() => void testar().then(setMsg)}>Testar aviso</button></p>}
      {lista && lista.length === 0 && <p className="texto">Nenhum aviso por enquanto.</p>}
      {lista && lista.length > 0 && (
        <ul className="lista-l20">
          {lista.map((a) => {
            const Icone = /visita/i.test(a.titulo) ? CalendarDays : FileText
            const conteudo = (
              <>
                <span className="icone-l20" aria-hidden="true"><Icone size={22} /></span>
                <span className="grid flex-1 text-left">
                  <span>{a.titulo}</span>
                  <span className="small-jdb" style={{ fontWeight: 400 }}>{[a.corpo, quando(a.ts)].filter(Boolean).join(' · ')}</span>
                </span>
                {!a.lido && <span className="ponto-novo" aria-label="não lido" />}
              </>
            )
            return (
              <li key={a.id}>
                {a.cliente
                  ? <button type="button" className="linha-l20" onClick={() => ir('cliente', a.cliente)}>{conteudo}</button>
                  : <div className="linha-l20">{conteudo}</div>}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
