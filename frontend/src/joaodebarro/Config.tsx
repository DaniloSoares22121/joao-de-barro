import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { ApiError, baixarRaw, get, post, put } from './api'
import { hojeBR, proximoCodigoDecisao, proximoCodigoNorma } from './codigos'
import { dataHoraBR } from './rotulos'

// ------------------------------------------------------------------ tipos
interface Decisao {
  codigo: string; data: string; laudo: string; decisao: string; regra: string; tipo: string; escopo: string; status: string
}
interface Norma { codigo: string; titulo: string; itens: Record<string, string>; vigente: boolean }
interface ConfigResp {
  avaliador: Record<string, string>
  dono_email?: string
  aviso_whatsapp?: boolean
  decisoes: Decisao[]
  normas: Norma[]
}

const CAMPOS_AVALIADOR: ReadonlyArray<{ chave: string; rotulo: string; placeholder?: string }> = [
  { chave: 'nome', rotulo: 'Nome completo' },
  { chave: 'creci', rotulo: 'CRECI', placeholder: 'Ex.: CRECI 5ª Região – GO, nº 00000' },
  { chave: 'cnai', rotulo: 'CNAI', placeholder: 'Ex.: nº 00000' },
  { chave: 'telefone', rotulo: 'Telefone', placeholder: '(00) 00000-0000' },
  { chave: 'telefone_avisos', rotulo: 'Telefone para avisos (WhatsApp)', placeholder: 'Vazio = usa o telefone acima' },
  { chave: 'site', rotulo: 'Site', placeholder: 'https://' },
  { chave: 'instagram', rotulo: 'Instagram', placeholder: '@usuario' },
]

/** Textos longos: qualificação do perito (AM/AMJ), sem certificados anexos (D-009). */
const CAMPOS_AVALIADOR_LONGOS: ReadonlyArray<{ chave: string; rotulo: string; placeholder?: string }> = [
  { chave: 'formacao', rotulo: 'Formação', placeholder: 'Ex.: Técnico em Transações Imobiliárias – CEP-SINDMOVEIS/GO.' },
  { chave: 'qualificacao', rotulo: 'Qualificação do perito (currículo resumido)',
    placeholder: 'Cursos, experiência e atuação em avaliações judiciais — obrigatório para AMJ.' },
]

const TIPOS_DECISAO = [
  { id: 'CP', rotulo: 'CP — correção pontual' },
  { id: 'PR', rotulo: 'PR — preferência de redação' },
  { id: 'PM', rotulo: 'PM — padrão de modalidade' },
  { id: 'RG', rotulo: 'RG — regra geral' },
  { id: 'RN', rotulo: 'RN — requisito normativo' },
]

const CHAVES_NORMA = ['Órgão', 'Status verificado', 'Uso no laudo', 'Fonte da verificação', 'Ação']

function Secao({ titulo, descricao, contagem, aberta = true, children }: {
  titulo: string; descricao?: string; contagem?: string; aberta?: boolean; children: ReactNode
}) {
  return (
    <details open={aberta} className="cartao group">
      <summary className="flex cursor-pointer list-none items-start justify-between gap-3 px-4 py-3.5 sm:px-5 [&::-webkit-details-marker]:hidden">
        <div>
          <h2 className="titulo-sec">{titulo}</h2>
          {descricao && <p className="mt-0.5 text-sm text-stone-500">{descricao}</p>}
        </div>
        <span className="flex shrink-0 items-center gap-2 pt-0.5 text-xs text-stone-500">
          {contagem}
          <span className="inline-block transition-transform group-open:rotate-180" aria-hidden="true">▾</span>
        </span>
      </summary>
      <div className="border-t border-stone-100 px-4 py-4 sm:px-5">{children}</div>
    </details>
  )
}

function Rotulado({ id, rotulo, children }: { id: string; rotulo: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="rotulo">{rotulo}</label>
      {children}
    </div>
  )
}

function Status({ msg }: { msg: { ok: boolean; texto: string } | null }) {
  if (!msg) return null
  return <p className={msg.ok ? 'text-sm text-emerald-700' : 'erro-txt'} role={msg.ok ? 'status' : 'alert'}>{msg.texto}</p>
}

function erroTexto(e: unknown): string {
  if (e instanceof ApiError) return e.status === 0 ? 'Falha de rede. Tente novamente.' : e.detail
  return 'Não foi possível salvar.'
}

// ------------------------------------------------------------------ avaliador
function Avaliador({ inicial, recarregar }: { inicial: Record<string, string>; recarregar: () => Promise<void> }) {
  const [form, setForm] = useState<Record<string, string>>(inicial)
  const [salvando, setSalvando] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; texto: string } | null>(null)
  useEffect(() => setForm(inicial), [inicial])

  async function salvar() {
    setSalvando(true)
    setMsg(null)
    try {
      const corpo: Record<string, string> = { ...inicial }
      for (const c of [...CAMPOS_AVALIADOR, ...CAMPOS_AVALIADOR_LONGOS]) corpo[c.chave] = (form[c.chave] ?? '').trim()
      await put('/config', { avaliador: corpo })
      await recarregar()
      setMsg({ ok: true, texto: 'Dados do avaliador salvos.' })
    } catch (e) {
      setMsg({ ok: false, texto: erroTexto(e) })
    } finally {
      setSalvando(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        {CAMPOS_AVALIADOR.map((c) => (
          <Rotulado key={c.chave} id={`av-${c.chave}`} rotulo={c.rotulo}>
            <input id={`av-${c.chave}`} className="input" value={form[c.chave] ?? ''} placeholder={c.placeholder}
                   disabled={salvando} onChange={(e) => setForm({ ...form, [c.chave]: e.target.value })} />
          </Rotulado>
        ))}
      </div>
      {CAMPOS_AVALIADOR_LONGOS.map((c) => (
        <Rotulado key={c.chave} id={`av-${c.chave}`} rotulo={c.rotulo}>
          <textarea id={`av-${c.chave}`} className="input" rows={3} value={form[c.chave] ?? ''} placeholder={c.placeholder}
                    disabled={salvando} onChange={(e) => setForm({ ...form, [c.chave]: e.target.value })} />
        </Rotulado>
      ))}
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn" onClick={() => void salvar()} disabled={salvando}>{salvando ? 'Salvando…' : 'Salvar'}</button>
        <Status msg={msg} />
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ aviso de fim
interface StatusAviso { ok: boolean; motivo: string; mensagem: string; telefone: string }

function AvisoWhatsapp({ ligado, recarregar }: { ligado: boolean; recarregar: () => Promise<void> }) {
  const [salvando, setSalvando] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; texto: string } | null>(null)
  const [st, setSt] = useState<StatusAviso | null>(null)
  useEffect(() => {
    get<StatusAviso>('/aviso/status').then(setSt).catch(() => setSt(null))
  }, [ligado])
  async function alternar(v: boolean) {
    setSalvando(true)
    setMsg(null)
    try {
      await put('/config', { aviso_whatsapp: v })
      await recarregar()
    } catch (e) {
      setMsg({ ok: false, texto: erroTexto(e) })
    } finally {
      setSalvando(false)
    }
  }
  return (
    <div className="space-y-1">
      <label className="inline-flex min-h-[44px] cursor-pointer items-center gap-2 text-sm text-stone-800">
        <input type="checkbox" className="h-5 w-5 accent-[var(--barro)]" checked={ligado} disabled={salvando}
               onChange={(e) => void alternar(e.target.checked)} />
        Avisar por WhatsApp quando um laudo terminar
      </label>
      <p className="ajuda">Vai para o telefone para avisos (ou o telefone do avaliador), pelo WhatsApp da Brixly. Com a aba aberta, o navegador também avisa.</p>
      {ligado && st?.motivo === 'proprio_numero' && (
        <p className="erro-txt" role="alert">{st.mensagem}</p>
      )}
      <Status msg={msg} />
    </div>
  )
}

// ------------------------------------------------------------------ P3
function EditorDecisao({ valor, novo, onSalvar, onCancelar }: {
  valor: Decisao; novo: boolean; onSalvar: (d: Decisao) => Promise<void>; onCancelar: () => void
}) {
  const [d, setD] = useState<Decisao>(valor)
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState('')
  const set = (k: keyof Decisao, v: string) => setD((x) => ({ ...x, [k]: v }))
  const id = (k: string) => `dec-${valor.codigo}-${k}`

  async function salvar() {
    if (!d.decisao.trim()) { setErro('Descreva a decisão.'); return }
    setSalvando(true)
    setErro('')
    try { await onSalvar({ ...d, decisao: d.decisao.trim(), regra: d.regra.trim() }) }
    catch (e) { setErro(erroTexto(e)) }
    finally { setSalvando(false) }
  }

  return (
    <div className="space-y-3 rounded-lg border border-stone-200 bg-stone-50/60 p-3 sm:p-4">
      <p className="text-sm font-semibold text-stone-800">{novo ? 'Nova decisão' : `Editar ${valor.codigo}`}</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Rotulado id={id('cod')} rotulo="Código">
          <input id={id('cod')} className="input" value={d.codigo} disabled readOnly />
        </Rotulado>
        <Rotulado id={id('data')} rotulo="Data">
          <input id={id('data')} className="input" value={d.data} disabled={salvando} onChange={(e) => set('data', e.target.value)} />
        </Rotulado>
        <Rotulado id={id('laudo')} rotulo="Laudo / origem">
          <input id={id('laudo')} className="input" value={d.laudo} disabled={salvando} onChange={(e) => set('laudo', e.target.value)} />
        </Rotulado>
      </div>
      <Rotulado id={id('decisao')} rotulo="Decisão do avaliador">
        <textarea id={id('decisao')} className="input" rows={3} value={d.decisao} disabled={salvando}
                  onChange={(e) => set('decisao', e.target.value)} />
      </Rotulado>
      <Rotulado id={id('regra')} rotulo="Regra resultante">
        <textarea id={id('regra')} className="input" rows={3} value={d.regra} disabled={salvando}
                  onChange={(e) => set('regra', e.target.value)} />
      </Rotulado>
      <div className="grid gap-3 sm:grid-cols-3">
        <Rotulado id={id('tipo')} rotulo="Tipo">
          <select id={id('tipo')} className="input" value={d.tipo} disabled={salvando} onChange={(e) => set('tipo', e.target.value)}>
            <option value="">—</option>
            {TIPOS_DECISAO.map((t) => <option key={t.id} value={t.id}>{t.rotulo}</option>)}
            {d.tipo && !TIPOS_DECISAO.some((t) => t.id === d.tipo) && <option value={d.tipo}>{d.tipo}</option>}
          </select>
        </Rotulado>
        <Rotulado id={id('escopo')} rotulo="Escopo">
          <input id={id('escopo')} className="input" value={d.escopo} disabled={salvando} onChange={(e) => set('escopo', e.target.value)} />
        </Rotulado>
        <Rotulado id={id('status')} rotulo="Status">
          <input id={id('status')} className="input" list="status-decisao" value={d.status} disabled={salvando}
                 onChange={(e) => set('status', e.target.value)} />
          <datalist id="status-decisao">
            <option value="Aprovada" /><option value="Pendente" /><option value="Substituída" />
          </datalist>
        </Rotulado>
      </div>
      {erro && <p className="erro-txt" role="alert">{erro}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        <button className="btn-sec" onClick={onCancelar} disabled={salvando}>Cancelar</button>
        <button className="btn" onClick={() => void salvar()} disabled={salvando}>{salvando ? 'Salvando…' : 'Salvar decisão'}</button>
      </div>
    </div>
  )
}

function Decisoes({ lista, recarregar }: { lista: Decisao[]; recarregar: () => Promise<void> }) {
  const [editando, setEditando] = useState<string | null>(null) // código; '' = nova
  const [novaBase, setNovaBase] = useState<Decisao | null>(null)

  async function salvar(d: Decisao) {
    await put('/config', { decisoes: [d] })
    await recarregar()
    setEditando(null)
    setNovaBase(null)
  }

  function nova() {
    setNovaBase({
      codigo: proximoCodigoDecisao(lista.map((x) => x.codigo)), data: hojeBR(), laudo: '', decisao: '',
      regra: '', tipo: 'RG', escopo: 'Todos os laudos', status: 'Aprovada',
    })
    setEditando('')
  }

  const ordenadas = [...lista].sort((a, b) => b.codigo.localeCompare(a.codigo))
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button className="btn-sec btn-peq" onClick={nova} disabled={editando !== null}>+ Adicionar decisão</button>
      </div>
      {editando === '' && novaBase && (
        <EditorDecisao valor={novaBase} novo onSalvar={salvar} onCancelar={() => { setEditando(null); setNovaBase(null) }} />
      )}
      {lista.length === 0 && editando !== '' && <p className="text-sm text-stone-500">Nenhuma decisão registrada.</p>}
      <ul className="divide-y divide-stone-100">
        {ordenadas.map((d) => (
          <li key={d.codigo} className="py-2.5">
            {editando === d.codigo
              ? <EditorDecisao valor={d} novo={false} onSalvar={salvar} onCancelar={() => setEditando(null)} />
              : (
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm">
                      <span className="font-semibold text-stone-900">{d.codigo}</span>
                      <span className="text-stone-500"> · {d.data}{d.tipo ? ` · ${d.tipo}` : ''} · {d.status}</span>
                    </p>
                    <p className="mt-0.5 line-clamp-3 break-words text-sm text-stone-700">{d.regra || d.decisao}</p>
                  </div>
                  <button className="btn-link shrink-0" onClick={() => setEditando(d.codigo)} disabled={editando !== null}>Editar</button>
                </div>
              )}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ------------------------------------------------------------------ P4
function EditorNorma({ valor, novo, onSalvar, onCancelar }: {
  valor: Norma; novo: boolean; onSalvar: (n: Norma) => Promise<void>; onCancelar: () => void
}) {
  const [n, setN] = useState<Norma>(valor)
  const [salvando, setSalvando] = useState(false)
  const [erro, setErro] = useState('')
  const chaves = Array.from(new Set([...CHAVES_NORMA, ...Object.keys(valor.itens)]))
  const id = (k: string) => `nor-${valor.codigo}-${k}`

  async function salvar() {
    if (!n.titulo.trim()) { setErro('Informe o título da norma.'); return }
    setSalvando(true)
    setErro('')
    try { await onSalvar({ ...n, titulo: n.titulo.trim() }) }
    catch (e) { setErro(erroTexto(e)) }
    finally { setSalvando(false) }
  }

  return (
    <div className="space-y-3 rounded-lg border border-stone-200 bg-stone-50/60 p-3 sm:p-4">
      <p className="text-sm font-semibold text-stone-800">{novo ? 'Nova norma' : `Editar ${valor.codigo}`}</p>
      <div className="grid gap-3 sm:grid-cols-[8rem_1fr]">
        <Rotulado id={id('cod')} rotulo="Código">
          <input id={id('cod')} className="input" value={n.codigo} readOnly disabled />
        </Rotulado>
        <Rotulado id={id('titulo')} rotulo="Norma / lei">
          <input id={id('titulo')} className="input" value={n.titulo} disabled={salvando}
                 onChange={(e) => setN({ ...n, titulo: e.target.value })} />
        </Rotulado>
      </div>
      {chaves.map((k) => (
        <Rotulado key={k} id={id(k)} rotulo={k}>
          <textarea id={id(k)} className="input" rows={2} value={n.itens[k] ?? ''} disabled={salvando}
                    onChange={(e) => setN({ ...n, itens: { ...n.itens, [k]: e.target.value } })} />
        </Rotulado>
      ))}
      <label className="flex items-center gap-2 text-sm text-stone-700">
        <input type="checkbox" className="h-4 w-4 rounded border-stone-300 accent-[var(--barro)]" checked={n.vigente}
               disabled={salvando} onChange={(e) => setN({ ...n, vigente: e.target.checked })} />
        Vigente (desmarcada, a norma deixa de ser usada nos laudos, mas continua nesta lista para reativar)
      </label>
      {erro && <p className="erro-txt" role="alert">{erro}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        <button className="btn-sec" onClick={onCancelar} disabled={salvando}>Cancelar</button>
        <button className="btn" onClick={() => void salvar()} disabled={salvando}>{salvando ? 'Salvando…' : 'Salvar norma'}</button>
      </div>
    </div>
  )
}

function Normas({ lista, recarregar }: { lista: Norma[]; recarregar: () => Promise<void> }) {
  const [editando, setEditando] = useState<string | null>(null)
  const [novaBase, setNovaBase] = useState<Norma | null>(null)

  async function salvar(n: Norma) {
    await put('/config', { normas: [n] })
    await recarregar()
    setEditando(null)
    setNovaBase(null)
  }

  function nova() {
    setNovaBase({ codigo: proximoCodigoNorma(lista.map((x) => x.codigo)), titulo: '', itens: {}, vigente: true })
    setEditando('')
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button className="btn-sec btn-peq" onClick={nova} disabled={editando !== null}>+ Adicionar norma</button>
      </div>
      {editando === '' && novaBase && (
        <EditorNorma valor={novaBase} novo onSalvar={salvar} onCancelar={() => { setEditando(null); setNovaBase(null) }} />
      )}
      {lista.length === 0 && editando !== '' && <p className="text-sm text-stone-500">Nenhuma norma cadastrada.</p>}
      <ul className="divide-y divide-stone-100">
        {lista.map((n) => (
          <li key={n.codigo} className="py-2.5">
            {editando === n.codigo
              ? <EditorNorma valor={n} novo={false} onSalvar={salvar} onCancelar={() => setEditando(null)} />
              : (
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="break-words text-sm"><span className="font-semibold text-stone-900">{n.codigo}</span> · {n.titulo}
                      {!n.vigente && <span className="ml-2 rounded bg-stone-100 px-1.5 py-0.5 text-xs font-medium text-stone-600">Não vigente</span>}
                    </p>
                    {n.itens['Status verificado'] && (
                      <p className="mt-0.5 line-clamp-2 break-words text-xs text-stone-500">{n.itens['Status verificado']}</p>
                    )}
                  </div>
                  <button className="btn-link shrink-0" onClick={() => setEditando(n.codigo)} disabled={editando !== null}>Editar</button>
                </div>
              )}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ------------------------------------------------------------------ Coletor
interface ColetorStatus { online: boolean; visto_em?: string | null }

function Coletor() {
  // 'indisponivel' = rotas do Plano 3 ainda não existem no servidor (404).
  const [estado, setEstado] = useState<'carregando' | 'indisponivel' | 'erro' | 'ok'>('carregando')
  const [status, setStatus] = useState<ColetorStatus | null>(null)
  const [codigo, setCodigo] = useState('')
  const [gerando, setGerando] = useState(false)
  const [baixando, setBaixando] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; texto: string } | null>(null)

  const consultar = useCallback(async () => {
    try {
      setStatus(await get<ColetorStatus>('/coletor/status'))
      setEstado('ok')
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setEstado('indisponivel')
      else if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return
      else setEstado((s) => (s === 'ok' ? s : 'erro'))
    }
  }, [])

  useEffect(() => {
    void consultar()
    const t = setInterval(() => { void consultar() }, 15_000)
    return () => clearInterval(t)
  }, [consultar])

  async function gerar() {
    setGerando(true)
    setMsg(null)
    try {
      const r = await post<{ codigo: string }>('/coletor/codigo')
      setCodigo(r.codigo)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setEstado('indisponivel')
      else setMsg({ ok: false, texto: 'Não foi possível gerar o código.' })
    } finally {
      setGerando(false)
    }
  }

  async function baixar() {
    setBaixando(true)
    setMsg(null)
    try {
      const { blob, nome } = await baixarRaw('/coletor/download')
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = nome || 'Coletor-JoaoDeBarro'
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 10_000)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setEstado('indisponivel')
      else setMsg({ ok: false, texto: 'Não foi possível baixar o Coletor.' })
    } finally {
      setBaixando(false)
    }
  }

  if (estado === 'carregando') return <p className="text-sm text-stone-500" role="status">Verificando o Coletor…</p>
  if (estado === 'indisponivel') {
    return (
      <div className="rounded-lg bg-stone-50 px-4 py-3 text-sm text-stone-600">
        <p className="font-medium text-stone-800">Coletor disponível em breve</p>
        <p className="mt-0.5">O programa que coleta os anúncios no seu PC ainda não foi liberado nesta conta.</p>
      </div>
    )
  }
  if (estado === 'erro') {
    return (
      <div className="flex items-center justify-between gap-3 text-sm text-red-800" role="alert">
        <span>Não foi possível consultar o Coletor.</span>
        <button className="btn-sec btn-peq" onClick={() => void consultar()}>Tentar de novo</button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className={`chip ${status?.online ? 'bg-emerald-50 text-emerald-800 ring-emerald-600/20' : 'bg-stone-100 text-stone-700 ring-stone-500/20'}`}>
          {status?.online ? 'Online' : 'Offline'}
        </span>
        <span className="text-stone-500">
          {status?.visto_em ? `Visto pela última vez em ${dataHoraBR(status.visto_em)}` : 'Nunca conectado'}
        </span>
      </div>
      <ol className="list-decimal space-y-1 pl-5 text-sm text-stone-700">
        <li>Baixe e instale o Coletor no PC que fica ligado durante as pesquisas.</li>
        <li>Gere um código de pareamento e informe-o no programa.</li>
        <li>Mantenha o PC ligado: a pesquisa de referenciais espera o Coletor ficar online.</li>
      </ol>
      <div className="flex flex-wrap gap-2">
        <button className="btn" onClick={() => void baixar()} disabled={baixando}>{baixando ? 'Baixando…' : 'Baixar o Coletor'}</button>
        <button className="btn-sec" onClick={() => void gerar()} disabled={gerando}>{gerando ? 'Gerando…' : 'Gerar código de pareamento'}</button>
      </div>
      {codigo && (
        <div className="rounded-lg border border-stone-200 bg-stone-50 px-4 py-3">
          <p className="text-xs text-stone-500">Código de pareamento</p>
          <p className="mt-0.5 select-all break-all font-mono text-xl font-semibold tracking-wider text-stone-900">{codigo}</p>
        </div>
      )}
      <Status msg={msg} />
    </div>
  )
}

// ------------------------------------------------------------------ tela
export default function Config() {
  const [cfg, setCfg] = useState<ConfigResp | null>(null)
  const [erro, setErro] = useState('')

  const carregar = useCallback(async () => {
    try {
      const c = await get<ConfigResp>('/config')
      setCfg({ ...c, avaliador: c.avaliador ?? {}, decisoes: c.decisoes ?? [], normas: c.normas ?? [] })
      setErro('')
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return
      setErro('Não foi possível carregar as configurações.')
    }
  }, [])

  useEffect(() => { void carregar() }, [carregar])

  return (
    <section className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-stone-900">Configurações</h1>
        <p className="text-sm text-stone-500">Dados do avaliador, regras aprendidas, normas e Coletor.</p>
      </div>

      {erro && (
        <div className="cartao-pad flex items-center justify-between gap-3 border-red-200 bg-red-50 text-sm text-red-800" role="alert">
          <span>{erro}</span>
          <button className="btn-sec btn-peq" onClick={() => void carregar()}>Tentar de novo</button>
        </div>
      )}

      {!cfg && !erro && <p className="py-8 text-center text-sm text-stone-500" role="status">Carregando…</p>}

      {cfg && (
        <>
          <Secao titulo="Avaliador" descricao="Identificação que sai no laudo.">
            <Avaliador inicial={cfg.avaliador} recarregar={carregar} />
            <div className="mt-4 border-t border-stone-100 pt-3">
              <AvisoWhatsapp ligado={cfg.aviso_whatsapp !== false} recarregar={carregar} />
            </div>
          </Secao>
          <Secao titulo="Decisões e regras (P3)" descricao="Cada decisão vira regra para os próximos laudos."
                 contagem={`${cfg.decisoes.length}`} aberta={false}>
            <Decisoes lista={cfg.decisoes} recarregar={carregar} />
          </Secao>
          <Secao titulo="Normas e legislação (P4)" descricao="Normas que o laudo pode citar (só as vigentes são usadas)."
                 contagem={`${cfg.normas.length}`} aberta={false}>
            <Normas lista={cfg.normas} recarregar={carregar} />
          </Secao>
        </>
      )}

      <Secao titulo="Coletor" descricao="Programa do seu PC que coleta anúncios para a pesquisa de referenciais.">
        <Coletor />
      </Secao>
    </section>
  )
}
