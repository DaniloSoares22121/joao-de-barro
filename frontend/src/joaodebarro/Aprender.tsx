/* ORDEM 026 v2 — F2: "Vale só para este laudo ou para todos os seus?" depois de uma correção. */
import { useEffect, useState } from 'react'
import { GraduationCap } from 'lucide-react'
import { post } from './api'

export interface CorrecaoAprender {
  tipo: 'campo' | 'texto' | 'amostra' | 'area' | 'pergunta'
  chave: string
  antes?: string | number | null
  depois?: string | number | null
  motivo?: string
}

interface Rascunho { titulo: string; situacao: string; decisao: string; porque: string
  tipo_imovel: string[]; modalidade: string[]; etapa: string[] }

export default function PerguntaAprender({ jobId, correcao, aoFechar }: {
  jobId: string; correcao: CorrecaoAprender; aoFechar: (msg?: string) => void
}) {
  const [visivel, setVisivel] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const [rasc, setRasc] = useState<Rascunho | null>(null)
  const [erro, setErro] = useState('')
  const url = `/jobs/${encodeURIComponent(jobId)}/aprender`
  const corpo = { ...correcao, antes: correcao.antes ?? null, depois: correcao.depois ?? null }

  useEffect(() => {
    let vivo = true
    post<{ perguntar: boolean }>(`${url}/perguntar`, corpo)
      .then((r) => { if (!vivo) return; if (r.perguntar) setVisivel(true); else aoFechar() })
      .catch(() => { if (vivo) aoFechar() })
    return () => { vivo = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function responder(resposta: 'so_este' | 'todos' | 'nao_regra') {
    setErro('')
    setOcupado(true)
    try {
      const r = await post<{ rascunho: Rascunho | null }>(`${url}/resposta`, { ...corpo, resposta })
      if (resposta === 'todos' && r.rascunho) setRasc(r.rascunho)
      else aoFechar(resposta === 'so_este' ? 'Ok: vale só para este laudo.' : undefined)
    } catch {
      setErro('Não foi possível registrar a resposta.')
    } finally {
      setOcupado(false)
    }
  }

  async function confirmar() {
    if (!rasc) return
    setOcupado(true)
    try {
      await post(`${url}/confirmar`, rasc)
      aoFechar('Regra salva. Ela vale nos seus próximos laudos e aparece em Configurações → Minhas regras.')
    } catch {
      setErro('Não foi possível salvar a regra.')
    } finally {
      setOcupado(false)
    }
  }

  if (!visivel) return null
  const campo = (k: keyof Rascunho, rotulo: string, linhas = 2) => (
    <div>
      <label className="rotulo" htmlFor={`ap-${k}`}>{rotulo}</label>
      <textarea id={`ap-${k}`} className="input" rows={linhas} value={String(rasc?.[k] ?? '')} disabled={ocupado}
                onChange={(e) => setRasc((r) => (r ? { ...r, [k]: e.target.value } : r))} />
    </div>
  )
  return (
    <section className="cartao-pad space-y-3 ring-2 ring-[var(--amarelo)]" aria-labelledby="ap-titulo" role="dialog">
      <h2 id="ap-titulo" className="titulo-sec flex items-center gap-2">
        <GraduationCap size={18} aria-hidden="true" /> Vale só para este laudo ou para todos os seus?
      </h2>
      <p className="text-sm text-[var(--cinza)]">Você corrigiu: <strong>{correcao.chave}</strong>
        {correcao.depois != null && correcao.depois !== '' ? <> → {String(correcao.depois).slice(0, 160)}</> : null}</p>
      {!rasc ? (
        <div className="flex flex-col gap-2 sm:flex-row">
          <button type="button" className="btn-sec flex-1" disabled={ocupado} onClick={() => void responder('so_este')}>Só este</button>
          <button type="button" className="btn flex-1" disabled={ocupado} onClick={() => void responder('todos')}>
            {ocupado ? 'Escrevendo a regra…' : 'Todos os meus'}
          </button>
          <button type="button" className="btn-sec flex-1" disabled={ocupado} onClick={() => void responder('nao_regra')}>Não é regra</button>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-sm">Confira a regra (sem dados de cliente) e confirme:</p>
          {campo('titulo', 'Título', 1)}
          {campo('situacao', 'Situação (quando vale)')}
          {campo('decisao', 'Decisão (o que fazer)')}
          {campo('porque', 'Porquê')}
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-sec" disabled={ocupado} onClick={() => aoFechar()}>Cancelar</button>
            <button type="button" className="btn" disabled={ocupado} onClick={() => void confirmar()}>Confirmar regra</button>
          </div>
        </div>
      )}
      {erro && <p className="erro-txt" role="alert">{erro}</p>}
    </section>
  )
}
