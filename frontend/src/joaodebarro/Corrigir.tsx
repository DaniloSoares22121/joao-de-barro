import { useState, type FormEvent } from 'react'
import { ApiError, post } from './api'
import { etapaRotulo } from './rotulos'

export interface RespostaCorrecao { etapa: string; instrucao: string; decisao: string | null }

function mensagem(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 409) return 'Aguarde o trabalho terminar para corrigir.'
    if (e.status === 503) return 'A IA está indisponível agora. Tente novamente em instantes.'
    if (e.status === 400) return 'Escreva a correção antes de enviar.'
    if (e.status === 0) return 'Falha de rede. Tente novamente.'
    return e.detail
  }
  return 'Não foi possível enviar a correção.'
}

export default function Corrigir({ jobId, onEnviado }: {
  jobId: string
  onEnviado: (r: RespostaCorrecao) => void
}) {
  const [texto, setTexto] = useState('')
  const [virarRegra, setVirarRegra] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState('')

  async function enviar(e: FormEvent) {
    e.preventDefault()
    if (!texto.trim()) { setErro('Escreva a correção antes de enviar.'); return }
    setErro('')
    setEnviando(true)
    try {
      const r = await post<RespostaCorrecao>(`/jobs/${encodeURIComponent(jobId)}/corrigir`,
        { texto: texto.trim(), virar_regra: virarRegra })
      setTexto('')
      setVirarRegra(false)
      onEnviado(r)
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) return
      setErro(mensagem(err))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <form onSubmit={enviar} className="cartao-pad space-y-3" aria-labelledby="sec-corrigir">
      <div>
        <h3 className="titulo-sec" id="sec-corrigir">Corrigir o laudo</h3>
        <p className="text-sm text-stone-500">
          Descreva o que precisa mudar. O João de Barro identifica a primeira etapa afetada e refaz a partir dela.
        </p>
      </div>
      <div>
        <label htmlFor="corrigir-texto" className="rotulo">Correção</label>
        <textarea id="corrigir-texto" className={`input ${erro ? 'input-erro' : ''}`} rows={4} value={texto}
                  disabled={enviando} onChange={(e) => setTexto(e.target.value)}
                  placeholder="Ex.: a área construída correta é 148 m², conforme a matrícula; descarte o referencial nº 7." />
      </div>
      <label className="flex items-start gap-2 text-sm text-stone-700">
        <input type="checkbox" className="mt-0.5 h-4 w-4 rounded border-stone-300 accent-[var(--barro)]"
               checked={virarRegra} disabled={enviando} onChange={(e) => setVirarRegra(e.target.checked)} />
        <span>
          Registrar como regra (P3)
          <span className="block text-xs text-stone-500">Vale para os próximos laudos, não só para este.</span>
        </span>
      </label>
      {erro && <p className="erro-txt" role="alert">{erro}</p>}
      <div className="flex justify-end">
        <button type="submit" className="btn" disabled={enviando || !texto.trim()}>
          {enviando ? 'Analisando a correção…' : 'Enviar correção'}
        </button>
      </div>
    </form>
  )
}

export function textoCorrecao(r: RespostaCorrecao): string {
  const regra = r.decisao ? ` Registrada como regra ${r.decisao}.` : ''
  return `Correção enviada. O trabalho será refeito a partir de “${etapaRotulo(r.etapa)}”.${regra}`
}
