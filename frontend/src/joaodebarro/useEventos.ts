import { useEffect, useRef, useState } from 'react'
import { wsUrl } from './api'
import { atrasoReconexao } from './reconexao'
import type { Evento } from './tipos'

const AGRUPA_MS = 250

/**
 * Eventos ao vivo do trabalho (WS /ws/avaliacao/{id}).
 * - reconecta com backoff 1 → 2 → 5 → 10 s (zera ao conectar), exceto se o servidor fechar com
 *   4403 (sem acesso) ou 4404 (trabalho não encontrado);
 * - o servidor reenvia o histórico a cada conexão: eventos já vistos (id) são descartados;
 * - `aoAtualizar` (refazer o GET do trabalho) é chamado a cada reconexão e a cada evento
 *   `nivel="resultado"` novo, agrupado em ~250 ms para não gerar rajada de requisições.
 */
export function useEventos(jobId: string | null, aoAtualizar?: () => void) {
  const [eventos, setEventos] = useState<Evento[]>([])
  const [conectado, setConectado] = useState(false)
  const callback = useRef(aoAtualizar)
  callback.current = aoAtualizar

  useEffect(() => {
    setEventos([])
    setConectado(false)
    if (!jobId) return

    let ativo = true
    let ws: WebSocket | null = null
    let timerReconecta: ReturnType<typeof setTimeout> | undefined
    let timerAtualiza: ReturnType<typeof setTimeout> | undefined
    let tentativa = 0
    let jaConectou = false
    let maiorId = 0

    const atualizar = () => {
      if (timerAtualiza) return
      timerAtualiza = setTimeout(() => { timerAtualiza = undefined; if (ativo) callback.current?.() }, AGRUPA_MS)
    }

    const conectar = () => {
      if (!ativo) return
      const s = new WebSocket(wsUrl(jobId))
      ws = s
      s.onopen = () => {
        tentativa = 0
        setConectado(true)
        if (jaConectou) atualizar() // reconexão: ressincroniza o estado
        jaConectou = true
      }
      s.onmessage = (m) => {
        let ev: Evento
        try { ev = JSON.parse(String(m.data)) as Evento } catch { return }
        if (typeof ev?.id !== 'number' || ev.id <= maiorId) return
        maiorId = ev.id
        setEventos((es) => [...es, ev])
        if (ev.nivel === 'resultado') atualizar()
      }
      s.onerror = () => { try { s.close() } catch { /* já fechado */ } }
      s.onclose = (e) => {
        if (ws === s) ws = null
        setConectado(false)
        if (!ativo) return
        if (e.code === 4403 || e.code === 4404) return // sem acesso / trabalho inexistente: reconectar não adianta
        timerReconecta = setTimeout(conectar, atrasoReconexao(tentativa))
        tentativa += 1
      }
    }
    conectar()

    return () => {
      ativo = false
      clearTimeout(timerReconecta)
      clearTimeout(timerAtualiza)
      if (ws) { ws.onclose = null; ws.onerror = null; ws.close() }
    }
  }, [jobId])

  return { eventos, conectado }
}
