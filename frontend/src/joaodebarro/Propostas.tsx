/* ORDEM 024 item 6: proposta -> contrato -> trabalho (D-044 a D-053). Numeração ANO-SEQ própria. */
import { useCallback, useEffect, useState } from 'react'
import { Download, FilePlus2 } from 'lucide-react'
import { baixarRaw, get, post, put } from './api'
import { MODALIDADES, moeda } from './rotulos'
import { useStore } from './store'

interface Proposta { id: string; ano: number; numero: number; status: string; arquivos: string[]
  dados: { modalidade: string; valor: string; finalidade: string; data: string; solicitante: { nome: string }
    imovel: { descricao: string; bairro: string; cidade: string } } }

const VAZIA = { modalidade: 'OV', categoria: 'residencial', solicitante_nome: '', solicitante_doc: '', proprietario: '',
  finalidade: '', valor: '', imovel: { descricao: '', endereco: '', matricula: '', cartorio: '', tipo: '', bairro: '', cidade: 'Goiânia' } }

async function baixar(pid: string, nome: string) {
  const { blob } = await baixarRaw(`/propostas/${encodeURIComponent(pid)}/arquivo/${encodeURIComponent(nome)}`)
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob); a.download = nome; a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 2000)
}

function Campo({ id, rotulo, valor, mudar, tipo = 'text', dica }: {
  id: string; rotulo: string; valor: string; mudar: (v: string) => void; tipo?: string; dica?: string
}) {
  return (
    <div>
      <label className="rotulo" htmlFor={id}>{rotulo}</label>
      <input id={id} name={`jdb-${id}`} className="input" type={tipo} value={valor} onChange={(e) => mudar(e.target.value)} autoComplete="off" />{/* 186 */}
      {dica && <p className="ajuda">{dica}</p>}
    </div>
  )
}

function NovaProposta({ aoCriar }: { aoCriar: () => void }) {
  const [f, setF] = useState(VAZIA)
  const [padrao, setPadrao] = useState<{ valor: string; prazo: string } | null>(null)
  const [erro, setErro] = useState('')
  const [ocupado, setOcupado] = useState(false)
  useEffect(() => {
    get<{ valor: string; prazo: string }>(`/propostas/preco-padrao?modalidade=${encodeURIComponent(f.modalidade)}&tipo=${encodeURIComponent(f.imovel.tipo)}`)
      .then(setPadrao).catch(() => setPadrao(null))
  }, [f.modalidade, f.imovel.tipo])
  const im = (k: keyof typeof VAZIA.imovel) => (v: string) => setF({ ...f, imovel: { ...f.imovel, [k]: v } })
  async function criar() {
    setErro('')
    setOcupado(true)
    try {
      await post('/propostas', { ...f, valor: f.valor.trim() || undefined })
      setF(VAZIA)
      aoCriar()
    } catch {
      setErro('Confira solicitante, imóvel e finalidade.')
    } finally {
      setOcupado(false)
    }
  }
  return (
    <section className="cartao-pad space-y-3">
      <h2 className="titulo-sec">Nova proposta</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="rotulo" htmlFor="p-mod">Modalidade</label>
          <select id="p-mod" className="input" value={f.modalidade} onChange={(e) => setF({ ...f, modalidade: e.target.value })}>
            {MODALIDADES.map((m) => <option key={m.id} value={m.id}>{m.rotulo}</option>)}
          </select>
          {padrao && <p className="ajuda">Preço padrão {moeda(padrao.valor)} · entrega {padrao.prazo}</p>}
        </div>
        <Campo id="p-valor" rotulo="Valor (R$)" valor={f.valor} mudar={(v) => setF({ ...f, valor: v })}
               dica="Vazio = preço da sua tabela" />
        <Campo id="p-sol" rotulo="Solicitante" valor={f.solicitante_nome} mudar={(v) => setF({ ...f, solicitante_nome: v })} />
        <Campo id="p-doc" rotulo="CPF/CNPJ do solicitante (opcional)" valor={f.solicitante_doc} mudar={(v) => setF({ ...f, solicitante_doc: v })} />
        <Campo id="p-tipo" rotulo="Tipo do imóvel" valor={f.imovel.tipo} mudar={im('tipo')} />
        <Campo id="p-desc" rotulo="Descrição do imóvel" valor={f.imovel.descricao} mudar={im('descricao')} />
        <Campo id="p-end" rotulo="Endereço" valor={f.imovel.endereco} mudar={im('endereco')} />
        <Campo id="p-bairro" rotulo="Bairro ou condomínio" valor={f.imovel.bairro} mudar={im('bairro')} />
        <Campo id="p-cid" rotulo="Cidade" valor={f.imovel.cidade} mudar={im('cidade')} />
        <Campo id="p-fin" rotulo="Finalidade" valor={f.finalidade} mudar={(v) => setF({ ...f, finalidade: v })} />
      </div>
      {erro && <p className="erro-txt" role="alert">{erro}</p>}
      <div className="flex justify-end">
        <button type="button" className="btn" disabled={ocupado} onClick={() => void criar()}>
          <FilePlus2 size={16} aria-hidden="true" /> {ocupado ? 'Gerando…' : 'Gerar proposta (Word + PDF)'}
        </button>
      </div>
    </section>
  )
}

function Contrato({ p, aoMudar }: { p: Proposta; aoMudar: () => void }) {
  const [k, setK] = useState({ nome: p.dados.solicitante.nome, doc_tipo: 'CPF', doc: '', endereco: '', representante: '', email: '', telefone: '', pj: false })
  const [aberto, setAberto] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  if (!aberto) return <button type="button" className="btn-sec btn-peq" onClick={() => setAberto(true)}>Gerar contrato</button>
  async function gerar() {
    setOcupado(true)
    try { await post(`/propostas/${encodeURIComponent(p.id)}/contrato`, { contratante: k }); setAberto(false); aoMudar() } finally { setOcupado(false) }
  }
  const c = (key: keyof typeof k, rot: string) => (
    <Campo id={`k-${p.id}-${key}`} rotulo={rot} valor={String(k[key])} mudar={(v) => setK({ ...k, [key]: v })} />
  )
  return (
    <div className="mt-2 w-full space-y-2 rounded-xl border border-[var(--borda)] p-3">
      <p className="text-sm font-semibold">Contratante (o que faltar sai [entre colchetes] para conferir)</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {c('nome', 'Nome ou razão social')}{c('doc_tipo', 'Documento (CPF/CNPJ)')}{c('doc', 'Número do documento')}
        {c('endereco', 'Endereço')}{c('representante', 'Representante (PJ)')}{c('email', 'E-mail')}{c('telefone', 'Telefone')}
      </div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={k.pj} onChange={(e) => setK({ ...k, pj: e.target.checked })} /> Pessoa jurídica</label>
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-sec btn-peq" onClick={() => setAberto(false)}>Cancelar</button>
        <button type="button" className="btn btn-peq" disabled={ocupado} onClick={() => void gerar()}>{ocupado ? 'Gerando…' : 'Gerar contrato'}</button>
      </div>
    </div>
  )
}

export function DadosContratado({ aberto = false }: { aberto?: boolean } = {}) {
  const [d, setD] = useState({ cpf: '', endereco: '', email: '', pix: '' })
  const [msg, setMsg] = useState('')
  useEffect(() => { get<typeof d>('/configuracoes/contratado').then(setD).catch(() => undefined) }, [])
  async function salvar() { setD(await put<typeof d>('/configuracoes/contratado', d)); setMsg('Salvo neste computador (não vai para o git).') }
  return (
    <details className="cartao" open={aberto || undefined}>
      <summary className="cursor-pointer px-4 py-3 font-semibold sm:px-5">Seus dados para o contrato (CPF, endereço, e-mail, Pix)</summary>
      <div className="grid gap-2 border-t border-[var(--borda)] px-4 py-3 sm:grid-cols-2 sm:px-5">
        <Campo id="c-cpf" rotulo="CPF" valor={d.cpf} mudar={(v) => setD({ ...d, cpf: v })} />
        <Campo id="c-email" rotulo="E-mail" valor={d.email} mudar={(v) => setD({ ...d, email: v })} />
        <Campo id="c-end" rotulo="Endereço" valor={d.endereco} mudar={(v) => setD({ ...d, endereco: v })} />
        <Campo id="c-pix" rotulo="Chave Pix" valor={d.pix} mudar={(v) => setD({ ...d, pix: v })} />
        <div className="sm:col-span-2 flex items-center justify-end gap-3">
          {msg && <span className="text-xs text-[var(--cinza)]">{msg}</span>}
          <button type="button" className="btn btn-peq" onClick={() => void salvar()}>Salvar</button>
        </div>
      </div>
    </details>
  )
}

export default function Propostas() {
  const novoAPartir = useStore((s) => s.novoAPartir)
  const [lista, setLista] = useState<Proposta[] | null>(null)
  const carregar = useCallback(() => { get<{ propostas: Proposta[] }>('/propostas').then((r) => setLista(r.propostas)).catch(() => setLista([])) }, [])
  useEffect(carregar, [carregar])
  async function abrirTrabalho(p: Proposta) {
    const pre = await post<Record<string, string>>(`/propostas/${encodeURIComponent(p.id)}/trabalho`)
    novoAPartir(pre)
  }
  return (
    <section className="mx-auto max-w-4xl space-y-4">
      <div>
        <p className="sobre">Comercial</p>
        <h1 className="titulo-pag">Propostas e contratos</h1>
        <p className="text-sm text-[var(--cinza)]">Proposta → contrato → trabalho. Numeração própria (ano-sequência), validade de 10 dias.</p>
      </div>
      <NovaProposta aoCriar={carregar} />
      <DadosContratado />
      <section className="space-y-2">
        {lista && !lista.length && <p className="text-sm text-[var(--cinza)]">Nenhuma proposta ainda.</p>}
        {lista?.map((p) => (
          <article key={p.id} className="cartao-pad">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="font-semibold">Proposta {p.ano}-{String(p.numero).padStart(3, '0')} · {p.dados.solicitante.nome}</p>
                <p className="text-sm text-[var(--cinza)]">{p.dados.imovel.descricao} · {p.dados.imovel.bairro} · {p.dados.imovel.cidade} · {moeda(p.dados.valor)} · {p.dados.data}</p>
              </div>
              <span className="chip bg-[#FFF4CC] text-[#5c4400] ring-[#F5B800]/50">{p.status}</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {p.arquivos.map((a) => (
                <button key={a} type="button" className="btn-sec btn-peq" onClick={() => void baixar(p.id, a)}>
                  <Download size={14} aria-hidden="true" /> {a.endsWith('.pdf') ? 'PDF' : 'Word'} · {a.startsWith('Contrato') ? 'contrato' : 'proposta'}
                </button>
              ))}
              <Contrato p={p} aoMudar={carregar} />
              <button type="button" className="btn btn-peq" onClick={() => void abrirTrabalho(p)}>Abrir trabalho</button>
            </div>
          </article>
        ))}
      </section>
    </section>
  )
}
