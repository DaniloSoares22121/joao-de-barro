/* ORDEM 026 v2 — Configurações: Minhas regras (F2), Curadoria e Compartilhar (F3),
 * "Me mostre como se faz" (F4). Visual da ORDEM 023 (caixas sanfona, cores do protótipo). */
import { plural } from './rotulos'
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { get, post, put } from './api'

interface Ficha { id: string; titulo: string; situacao: string; decisao: string; porque: string; ativa: boolean
  nivel: string; trabalho_numero?: number | null; concordam?: number; parecidas?: { id: string; titulo: string; semelhanca: number }[] }

function Bloco({ titulo, resumo, children, abertoInicial = false }: {
  titulo: string; resumo?: string; children: ReactNode; abertoInicial?: boolean
}) {
  const [aberto, setAberto] = useState(abertoInicial)
  return (
    <section className="cartao overflow-hidden">
      <button type="button" aria-expanded={aberto} onClick={() => setAberto(!aberto)}
              className="foco flex min-h-[52px] w-full items-center gap-3 px-4 py-2.5 text-left sm:px-5">
        <span className="min-w-0 flex-1">
          <span className="titulo-caixa block">{titulo}</span>
          {resumo && <span className="block text-sm text-[var(--cinza)]">{resumo}</span>}
        </span>
        <ChevronDown size={18} className={`text-stone-400 transition-transform ${aberto ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
      {aberto && <div className="space-y-3 border-t border-[var(--borda)] px-4 py-4 sm:px-5">{children}</div>}
    </section>
  )
}

const NIVEL: Record<string, string> = {
  oficial: 'bg-[#18283B] text-white ring-[#18283B]', 'regra do avaliador': 'bg-[#FFF4CC] text-[#5c4400] ring-[#F5B800]/50',
  validado: 'bg-emerald-50 text-emerald-800 ring-emerald-600/20', aprendido: 'bg-sky-50 text-sky-800 ring-sky-600/20',
  'sem base': 'bg-stone-100 text-stone-600 ring-stone-500/20',
}

export function MinhasRegras() {
  const [lista, setLista] = useState<Ficha[] | null>(null)
  const [editando, setEditando] = useState<Ficha | null>(null)
  const carregar = useCallback(() => { get<{ fichas: Ficha[] }>('/fichas/minhas').then((r) => setLista(r.fichas)).catch(() => setLista([])) }, [])
  useEffect(carregar, [carregar])
  async function salvar(f: Partial<Ficha> & { id: string }) {
    await put(`/fichas/${encodeURIComponent(f.id)}`, f)
    setEditando(null)
    carregar()
  }
  return (
    <Bloco titulo="Minhas regras" resumo={lista ? `${plural(lista.length, 'regra aprendida', 'regras aprendidas')} nos seus trabalhos` : 'carregando…'}>
      {lista && !lista.length && <p className="text-sm text-[var(--cinza)]">Ainda nenhuma. Ao corrigir um laudo, responda “Todos os meus” para criar uma.</p>}
      <ul className="space-y-2">
        {lista?.map((f) => (
          <li key={f.id} className={`rounded-xl border border-[var(--borda)] p-3 ${f.ativa ? '' : 'opacity-60'}`}>
            {editando?.id === f.id ? (
              <div className="space-y-2">
                {(['titulo', 'situacao', 'decisao', 'porque'] as const).map((k) => (
                  <textarea key={k} className="input" rows={k === 'titulo' ? 1 : 2} value={editando[k]}
                            aria-label={k} onChange={(e) => setEditando({ ...editando, [k]: e.target.value })} />
                ))}
                <div className="flex justify-end gap-2">
                  <button type="button" className="btn-sec btn-peq" onClick={() => setEditando(null)}>Cancelar</button>
                  <button type="button" className="btn btn-peq" onClick={() => void salvar(editando)}>Salvar</button>
                </div>
              </div>
            ) : (
              <>
                <p className="font-semibold">{f.titulo} <span className="text-xs font-normal text-[var(--cinza)]">{f.id}</span></p>
                <p className="text-sm">{f.decisao}</p>
                <p className="text-xs text-[var(--cinza)]">Porquê: {f.porque}{f.trabalho_numero ? ` · veio do trabalho nº ${f.trabalho_numero}` : ''}</p>
                <div className="mt-2 flex gap-2">
                  <button type="button" className="btn-sec btn-peq" onClick={() => setEditando(f)}>Editar</button>
                  <button type="button" className="btn-sec btn-peq" onClick={() => void salvar({ id: f.id, ativa: !f.ativa })}>
                    {f.ativa ? 'Desligar' : 'Religar'}
                  </button>
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
    </Bloco>
  )
}

function Curadoria() {
  const [fila, setFila] = useState<Ficha[] | null>(null)
  const [motivo, setMotivo] = useState<Record<string, string>>({})
  const [edit, setEdit] = useState<Ficha | null>(null)
  const [erro, setErro] = useState('')
  const carregar = useCallback(() => { get<{ fila: Ficha[] }>('/curadoria').then((r) => setFila(r.fila)).catch(() => setFila([])) }, [])
  useEffect(carregar, [carregar])
  async function decidir(f: Ficha, acao: 'aprovar' | 'recusar' | 'editar_aprovar') {
    setErro('')
    try {
      await post(`/curadoria/${encodeURIComponent(f.id)}`, { acao, motivo: motivo[f.id] ?? '',
        ...(acao === 'editar_aprovar' && edit ? { titulo: edit.titulo, situacao: edit.situacao, decisao: edit.decisao, porque: edit.porque } : {}) })
      setEdit(null)
      carregar()
    } catch {
      setErro(acao === 'recusar' ? 'Escreva o motivo da recusa.' : 'Não foi possível salvar a decisão.')
    }
  }
  return (
    <Bloco titulo="Curadoria (base comum)" resumo={fila ? `${plural(fila.length, 'ficha esperando', 'fichas esperando')} aprovação` : 'carregando…'}>
      <p className="text-xs text-[var(--cinza)]">As fichas já vêm protegidas (sem nomes, documentos, endereços nem valores exatos). Nada vira “validado” sem a sua aprovação.</p>
      {erro && <p className="erro-txt" role="alert">{erro}</p>}
      {fila && !fila.length && <p className="text-sm text-[var(--cinza)]">Fila vazia.</p>}
      <ul className="space-y-3">
        {fila?.map((f) => (
          <li key={f.id} className="space-y-2 rounded-xl border border-[var(--borda)] p-3">
            {edit?.id === f.id ? (['titulo', 'situacao', 'decisao', 'porque'] as const).map((k) => (
              <textarea key={k} className="input" rows={k === 'titulo' ? 1 : 2} value={edit[k]} aria-label={k}
                        onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} />
            )) : (
              <>
                <p className="font-semibold">{f.titulo}</p>
                <p className="text-sm"><span className="text-[var(--cinza)]">Situação:</span> {f.situacao}</p>
                <p className="text-sm"><span className="text-[var(--cinza)]">Decisão:</span> {f.decisao}</p>
                <p className="text-sm"><span className="text-[var(--cinza)]">Porquê:</span> {f.porque}</p>
              </>
            )}
            <p className="text-xs"><span className="chip bg-sky-50 text-sky-800 ring-sky-600/20">{plural(f.concordam ?? 1, 'avaliador faz', 'avaliadores fazem')} igual</span>
              {f.parecidas?.length ? <> · parecidas: {f.parecidas.map((p) => `${p.id} (${Math.round(p.semelhanca * 100)}%)`).join(', ')}</> : null}</p>
            <input className="input" placeholder="Motivo (obrigatório para recusar)" value={motivo[f.id] ?? ''}
                   onChange={(e) => setMotivo({ ...motivo, [f.id]: e.target.value })} />
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn btn-peq" onClick={() => void decidir(f, edit?.id === f.id ? 'editar_aprovar' : 'aprovar')}>
                {edit?.id === f.id ? 'Salvar e aprovar' : 'Aprovar'}
              </button>
              {edit?.id !== f.id && <button type="button" className="btn-sec btn-peq" onClick={() => setEdit(f)}>Editar e aprovar</button>}
              <button type="button" className="btn-perigo btn-peq" onClick={() => void decidir(f, 'recusar')}>Recusar</button>
            </div>
          </li>
        ))}
      </ul>
    </Bloco>
  )
}

function Compartilhar() {
  const [d, setD] = useState<{ sim: boolean; data?: string | null; termo: string; dono: boolean } | null>(null)
  const [termo, setTermo] = useState('')
  useEffect(() => { get<typeof d>('/configuracoes/compartilhar').then((r) => { setD(r); setTermo(r?.termo ?? '') }).catch(() => undefined) }, [])
  async function gravar(sim: boolean) {
    const r = await put<typeof d>('/configuracoes/compartilhar', { sim, termo })
    setD(r)
  }
  return (
    <Bloco titulo="Compartilhar meu raciocínio com a base comum" resumo={d ? (d.sim ? `Sim${d.data ? ` (aceite em ${d.data})` : ''}` : 'Não') : ''}>
      <label className="rotulo" htmlFor="termo">Termo (texto editável; o texto final o Danilo revisa)</label>
      <textarea id="termo" className="input" rows={3} value={termo} onChange={(e) => setTermo(e.target.value)} />
      <div className="flex gap-2">
        <button type="button" className="btn btn-peq" onClick={() => void gravar(true)}>Sim, compartilhar (sem dados de clientes)</button>
        {!d?.dono && <button type="button" className="btn-sec btn-peq" onClick={() => void gravar(false)}>Não</button>}
      </div>
      {d?.dono && <p className="text-xs text-[var(--cinza)]">Você é o dono e o curador: suas regras sempre alimentam a base comum (protegidas).</p>}
    </Bloco>
  )
}

function ComoSeFaz() {
  const [pergunta, setPergunta] = useState('')
  const [r, setR] = useState<{ sem_base: boolean; partes: { texto: string; nivel: string; fonte: string }[] } | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState('')
  async function perguntar() {
    setErro('')
    setOcupado(true)
    try {
      setR(await post('/conhecimento/perguntar', { pergunta }))
    } catch {
      setErro('Não foi possível responder agora.')
    } finally {
      setOcupado(false)
    }
  }
  return (
    <Bloco titulo="Me mostre como se faz" resumo="Pergunte uma regra ou peça o modelo de um tipo de laudo">
      <textarea className="input" rows={2} value={pergunta} onChange={(e) => setPergunta(e.target.value)}
                placeholder="Ex.: Qual a regra para a área de um galpão dentro de um lote maior?" aria-label="Pergunta" />
      <div className="flex justify-end">
        <button type="button" className="btn btn-peq" disabled={ocupado || pergunta.trim().length < 3} onClick={() => void perguntar()}>
          {ocupado ? 'Consultando…' : 'Perguntar'}
        </button>
      </div>
      {erro && <p className="erro-txt" role="alert">{erro}</p>}
      {r && (
        <ul className="space-y-2">
          {r.partes.map((p, i) => (
            <li key={i} className="rounded-xl border border-[var(--borda)] p-3 text-sm">
              <span className={`chip mr-2 ${NIVEL[p.nivel] ?? NIVEL['sem base']}`}>{p.nivel}</span>
              {p.texto}
              {p.fonte && <span className="block text-xs text-[var(--cinza)]">Fonte: {p.fonte}</span>}
            </li>
          ))}
        </ul>
      )}
    </Bloco>
  )
}

export default function Conhecimento() {
  // 185: a Curadoria (base comum) é só do dono; para o avaliador comum o servidor recusa e o bloco nem aparece
  const [dono, setDono] = useState(false)
  useEffect(() => { get<{ id: string }>('/avaliadores/eu').then((r) => setDono(r.id === 'AV-0001')).catch(() => undefined) }, [])
  return (
    <div className="space-y-3">
      <h2 className="titulo-sec">Conhecimento e aprendizado</h2>
      {/* 189: "Minhas regras" fica só no cartão das Configurações */}
      {dono && <Curadoria />}
      <Compartilhar />
      <ComoSeFaz />
    </div>
  )
}
