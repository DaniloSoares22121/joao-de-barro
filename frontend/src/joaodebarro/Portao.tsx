/** ORDEM 071: "Antes de seguir, confirme:" — as perguntas obrigatórias da etapa (os portões do João). Cada uma
 * já vem com a resposta sugerida e a fonte; o avaliador confirma com um toque, troca de opção ou escreve. O que
 * foi confirmado fica ✓ e não é perguntado de novo. Sem tudo confirmado, o Aprovar não anda. */
import { useEffect, useState } from 'react'
import { ApiError, get, post } from './api'
import { textoTela } from './rotulos'

export interface Opcao { valor: string; rotulo: string }
export interface PerguntaPortao {
  id: string; pergunta: string; opcoes: Opcao[]; livre: boolean; sugestao: Opcao | null; fonte: string
  aviso: string; dica: string; confirmado: Opcao | null
}
export interface Portao {
  etapa: 'proposta' | 'contrato' | 'visita'; perguntas: PerguntaPortao[]; completo: boolean; abertas: string[]
  existente: { arquivo: string; data: string; valor: string; pagamento: string; sinal_pago: boolean } | null
  usou_existente: boolean
}

export function usePortao(cid: string | null, etapa: 'proposta' | 'contrato' | 'visita', ativo: boolean, versao: string) {
  const [p, setP] = useState<Portao | null>(null)
  useEffect(() => {
    if (!cid || !ativo) { setP(null); return }
    let vivo = true
    get<Portao>(`/clientes/${encodeURIComponent(cid)}/portao/${etapa}`).then((r) => { if (vivo) setP(r) }).catch(() => undefined)
    return () => { vivo = false }
  }, [cid, etapa, ativo, versao])
  return [p, setP] as const
}

function Pergunta({ q, cid, etapa, aoMudar }: { q: PerguntaPortao; cid: string; etapa: string; aoMudar: (p: Portao) => void }) {
  const [editando, setEditando] = useState(!q.confirmado)
  const [texto, setTexto] = useState('')
  const [erro, setErro] = useState('')
  const [ocupado, setOcupado] = useState(false)
  useEffect(() => { setEditando(!q.confirmado) }, [q.confirmado])
  async function responder(valor: string, rotulo?: string) {
    setErro(''); setOcupado(true)
    try {
      aoMudar(await post<Portao>(`/clientes/${encodeURIComponent(cid)}/portao/${etapa}`, { id: q.id, valor, rotulo: rotulo ?? valor }))
      setTexto('')
    } catch (e) { setErro(e instanceof ApiError ? 'Não entendi esse valor. Confira e tente de novo.' : 'Não deu certo. Tente de novo.') }
    finally { setOcupado(false) }
  }
  if (q.confirmado && !editando) {
    return (
      <li className="portao-ok">
        <span><b>✓ {q.pergunta}</b> {q.confirmado.rotulo}</span>
        <button type="button" className="det-l13" onClick={() => setEditando(true)}>Mudar</button>
      </li>
    )
  }
  const outras = q.opcoes.filter((o) => o.valor !== q.sugestao?.valor)
  return (
    <li className="portao-aberta">
      <p className="portao-pergunta">{q.pergunta}</p>
      {q.sugestao && (
        <div className="portao-sugestao">
          <p><b>{q.sugestao.rotulo}</b></p>
          {q.fonte && <p className="small-jdb">Fonte: {textoTela(q.fonte)}</p>}
        </div>
      )}
      {q.dica && <p className="small-jdb">{textoTela(q.dica)}</p>}
      {q.aviso && <p className="aviso-impede">{q.aviso}</p>}
      <div className="botoes">
        {q.sugestao && (
          <button type="button" className="btn-verde" disabled={ocupado} onClick={() => void responder(q.sugestao!.valor, q.sugestao!.rotulo)}>
            ✓ Confirmar
          </button>
        )}
        {outras.map((o) => (
          <button key={o.valor} type="button" className="btn-sec-grande" disabled={ocupado} onClick={() => void responder(o.valor, o.rotulo)}>{o.rotulo}</button>
        ))}
      </div>
      {q.livre && (
        <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (texto.trim()) void responder(texto.trim()) }}>
          <label className="sr-only" htmlFor={`portao-${q.id}`}>{q.pergunta}</label>
          <input id={`portao-${q.id}`} className="campo-grande flex-1" value={texto} onChange={(e) => setTexto(e.target.value)}
                 placeholder={q.sugestao ? 'Ou escreva outro' : 'Escreva aqui'} />
          <button type="submit" className="btn-sec-grande" style={{ width: 'auto' }} disabled={ocupado || !texto.trim()}>Usar este</button>
        </form>
      )}
      {erro && <p className="aviso-impede" role="alert">{erro}</p>}
    </li>
  )
}

export function CartaoPortao({ cid, p, aoMudar, usarExistente }: {
  cid: string; p: Portao; aoMudar: (p: Portao) => void; usarExistente?: () => void
}) {
  const feitos = p.perguntas.filter((q) => q.confirmado).length
  return (
    <section className="portao-071" aria-label="Antes de seguir, confirme">
      <p className="rotulo-l63">Antes de seguir, confirme · {feitos} de {p.perguntas.length}</p>
      {p.etapa === 'contrato' && p.existente && !p.usou_existente && usarExistente && (
        <div className="portao-existente">
          <p>Você já mandou um contrato nesta conversa{p.existente.data ? ` (${p.existente.data.split('-').reverse().join('/')})` : ''}
            {p.existente.sinal_pago ? ' e o cliente já pagou o sinal' : ''}.</p>
          <button type="button" className="btn-verde" style={{ width: 'auto' }} onClick={usarExistente}>Usar esse contrato</button>
        </div>
      )}
      <ul className="portao-lista">
        {p.perguntas.map((q) => <Pergunta key={q.id} q={q} cid={cid} etapa={p.etapa} aoMudar={aoMudar} />)}
      </ul>
    </section>
  )
}
