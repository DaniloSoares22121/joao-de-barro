/* ORDEM 041 (D-089 a D-093): o cliente é uma conversa, da proposta ao laudo assinado.
 * No centro, a conversa escrita; ao lado, a linha de etapas Proposta → Contrato → Visita →
 * Laudo → Assinatura, cada uma com status, o que falta e o botão. Pendências numa lista única.
 * Nada é enviado ao cliente: o sistema deixa a mensagem pronta para o avaliador mandar. */
import Confirmar from './Confirmar'
import Espera from './Espera'
import { FalarAqui } from './Falar'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { FileEdit, Paperclip, SendHorizontal, X } from 'lucide-react'
import { createPortal } from 'react-dom'
import { ApiError, get, post, postForm } from './api'
import { ativar, registrar, testar } from './avisos'
import { ACEITOS, ConversaCompleta, SolteAqui, ehImportacao, importar, separar, useSoltar } from './Importar'
import { Miniatura, PainelDocumento, useRascunho } from './Rascunho'
import { CartaoPortao, usePortao } from './Portao'
import { useStore } from './store'
import { token } from './token'

interface Etapa { etapa: string; status: string; falta: string[] }
interface Msg { id: number; autor: string; tipo: string; texto: string; dados: { job_id?: string; mensagem_pronta?: string; arquivos?: string[]; proposta_id?: string; arquivo?: string; importacao?: string; mensagens?: number
  opcoes?: { valor: string; rotulo: string; recomendada: boolean }[]; outro?: boolean; respondida?: string; pergunta?: string }; ts: string }
interface Estado {
  id: string; nome: string; contexto: Record<string, string | boolean>; etapas: Etapa[]; etapa_atual: string
  pendencias: { etapa: string; texto: string }[]; mensagens: Msg[]; job_id: string
  proposta: { id: string; numero: string; status: string; arquivos: string[] } | null
  visita: { quando: string; legivel: string; aviso_min: number } | null
  sugestao: { modalidade: string; tipo: string; valor: string; prazo: string; da_tabela?: boolean } | null
  /** ORDEM 061: andamento da importação do WhatsApp. */
  importacao?: { estado: 'trabalhando' | 'pronto' | 'erro'; texto: string; importacao: string; retomar?: boolean } | null
  contrato_existente?: { arquivo: string; data: string; data_legivel: string; sinal_pago: boolean } | null
}
interface Linha { id: string; nome: string; imovel: string; etapa: string; proximo: string }

const ROTULO: Record<string, string> = { proposta: 'Proposta', contrato: 'Contrato', visita: 'Visita', laudo: 'Laudo', assinatura: 'Assinatura' }
const MOD: Record<string, string> = { OV: 'Opinião de Valor', AM: 'PTAM não judicial', AM_GARANTIA: 'PTAM garantia', AMJ: 'PTAM judicial' }

function erroDe(e: unknown) { return e instanceof ApiError ? e.message : 'Não deu certo. Tente de novo.' }

async function abrirComToken(caminho: string) {
  const r = await fetch('/api/avaliacao' + caminho, { headers: { Authorization: `Bearer ${token.get()}` } })
  const b = await r.blob()
  window.open(URL.createObjectURL(b), '_blank', 'noopener')
}

export function LinhaEtapas({ etapas, atual }: { etapas: { etapa: string; status: string }[]; atual: string }) {
  return (
    <ol className="linha-etapas" aria-label="Etapas">
      {etapas.map((e) => (
        <li key={e.etapa} className={e.status === 'feito' || e.status === 'fora' ? 'etapa-feita' : e.etapa === atual ? 'etapa-atual' : ''}
            aria-current={e.etapa === atual ? 'step' : undefined}>
          {ROTULO[e.etapa]}{e.status === 'feito' ? ' ✓' : e.status === 'fora' ? ' (feita fora do JdB)' : ''}
        </li>
      ))}
    </ol>
  )
}

export function ListaClientes() {
  const ir = useStore((s) => s.ir)
  const [lista, setLista] = useState<Linha[] | null>(null)
  const [nome, setNome] = useState('')
  const [aviso, setAviso] = useState('')
  useEffect(() => { get<{ clientes: Linha[] }>('/clientes').then((r) => setLista(r.clientes)).catch(() => setLista([])) }, [])
  useEffect(() => { void registrar() }, [])
  async function novo() {
    const r = await post<Estado>('/clientes', { nome })
    ir('cliente', r.id)
  }
  return (
    <section className="tela-simples">
      <h1 className="titulo-tela">Clientes</h1>
      <div className="proximo-passo">
        <p className="bloco-rotulo">Próximo passo</p>
        <label className="texto-grande" htmlFor="novo-cliente">Nome do cliente novo</label>
        <input id="novo-cliente" className="campo-grande" value={nome} onChange={(e) => setNome(e.target.value)} placeholder="Ex.: Maria Souza" />
        <button type="button" className="btn-verde" onClick={() => void novo()}>Começar conversa</button>
      </div>
      {lista && lista.length > 0 && (
        <ul className="lista-cartoes">
          {lista.map((c) => (
            <li key={c.id}>
              <button type="button" className="cartao-linha" onClick={() => ir('cliente', c.id)}>
                <span className="cartao-titulo">{c.nome}</span>
                <span className="cartao-sub">{c.imovel || 'Imóvel ainda não informado'}</span>
                <span className="cartao-etapa">{ROTULO[c.etapa]} · {c.proximo}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <details className="detalhes">
        <summary>Avisos neste aparelho</summary>
        <div className="detalhes-corpo">
          <div className="botoes">
            <button type="button" className="btn-sec-grande" onClick={() => void ativar().then(setAviso)}>Ligar avisos</button>
            <button type="button" className="btn-sec-grande" onClick={() => void testar().then(setAviso)}>Testar aviso</button>
          </div>
          {aviso && <p className="aviso-simples" role="status">{aviso}</p>}
        </div>
      </details>
    </section>
  )
}

/** ORDEM 053 (L3): a conversa do cliente no desenho do designer — bolhas e, embaixo, a barra
 * "Escreva o que aconteceu…" com clipe e enviar. Usada na tela do trabalho e na do cliente. */
export function ConversaFeed({ clienteId, aoMudar, painel = false }: {
  clienteId: string; aoMudar?: () => void
  /** ORDEM 063: a conversa rola só por dentro, abre na última mensagem e a caixa de escrever fica embaixo. */
  painel?: boolean
}) {
  const [d, setD] = useState<Estado | null>(null)
  const rolagem = useRef<HTMLDivElement>(null)
  const forcarFim = useRef(false)
  const [novas, setNovas] = useState(false)
  const vistas = useRef(0)
  const [texto, setTexto] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const campo = useRef<HTMLTextAreaElement>(null)
  const [explicando, setExplicando] = useState(false)
  const [erro, setErro] = useState('')
  const carregar = useCallback(() => { get<Estado>(`/clientes/${clienteId}`).then((e) => { setD(e); setErro('') }).catch((e) => setErro(e instanceof ApiError && e.status === 404 ? 'Cliente não encontrado.' : 'O JdB está reiniciando. Tento de novo em instantes.')) }, [clienteId])
  useEffect(carregar, [carregar])
  async function agir(f: () => Promise<Estado>) {
    setErro(''); setOcupado(true)
    try { setD(await f()); aoMudar?.() } catch (e) { setErro(erroDe(e)) } finally { setOcupado(false) }
  }
  async function enviar() {
    const t = texto.trim()
    if (!t) return
    setTexto('')
    if (campo.current) campo.current.style.height = 'auto'   // 105-1: volta ao tamanho de uma linha
    setExplicando(false)
    forcarFim.current = true
    await agir(() => post<Estado>(`/clientes/${clienteId}/mensagem`, { texto: t, tipo: 'texto' }))
  }
  // ORDEM 061: vários arquivos de uma vez, o .zip do WhatsApp, áudio, vídeo e contato → leitura em segundo plano
  const [aviso, setAviso] = useState('')
  const [verConversa, setVerConversa] = useState('')
  async function receber(lista: File[]) {
    const { aceitos, aviso: recusa } = separar(lista)
    setAviso(recusa)
    if (!aceitos.length) return
    if (ehImportacao(aceitos)) {
      await agir(async () => {
        const r = await importar<Estado>(clienteId, aceitos)
        if (r.recusados?.length) setAviso(`Deixei de fora ${r.recusados.length === 1 ? `“${r.recusados[0]}”` : `${r.recusados.length} arquivos`}: programa ou formato que eu não abro.`)
        return r
      })
      return
    }
    const f = aceitos[0]
    const fd = new FormData(); fd.append('arquivo', f); fd.append('tipo', f.type.startsWith('image/') ? 'foto' : 'documento')
    await agir(() => postForm<Estado>(`/clientes/${clienteId}/arquivo`, fd))
  }
  async function anexar(fs: FileList | null) { await receber(Array.from(fs ?? [])) }
  const [colado, setColado] = useState<{ arq: File; url: string } | null>(null)
  function colar(e: React.ClipboardEvent) {
    const img = Array.from(e.clipboardData?.files ?? []).find((f) => f.type.startsWith('image/'))
    if (!img) return                       // texto colado segue normal
    e.preventDefault()
    const agora = new Date()
    const nome = `print-${agora.toISOString().slice(0, 16).replace(/[-:T]/g, '')}.${(img.type.split('/')[1] || 'png').replace('jpeg', 'jpg')}`
    if (colado) URL.revokeObjectURL(colado.url)
    const arq = new File([img], nome, { type: img.type })
    setColado({ arq, url: URL.createObjectURL(arq) })
  }
  async function enviarColado() {
    if (!colado) return
    const a = colado.arq
    URL.revokeObjectURL(colado.url); setColado(null)
    await receber([a])
  }
  const soltar = useSoltar((fs) => void receber(fs))
  const lendo = d?.importacao?.estado === 'trabalhando'
  const lia = useRef(false)
  useEffect(() => {                       // enquanto lê a importação, a conversa (e a tela em volta) se atualiza sozinha
    if (!lendo) { if (lia.current) { lia.current = false; aoMudar?.() } return }
    lia.current = true
    const t = setInterval(() => { carregar(); aoMudar?.() }, 3000)
    return () => clearInterval(t)
  }, [lendo, carregar, aoMudar])
  // ORDEM 063: abre no fim; se o avaliador subiu para ler e chega mensagem nova, avisa em vez de pular
  const nMsgs = d?.mensagens.length ?? 0
  useEffect(() => {
    const el = rolagem.current
    if (!painel || !el || !nMsgs) return
    const perto = el.scrollHeight - el.scrollTop - el.clientHeight < 160
    if (vistas.current === 0 || perto || forcarFim.current) { el.scrollTop = el.scrollHeight; setNovas(false); if (!ocupado) forcarFim.current = false }
    else if (nMsgs > vistas.current) setNovas(true)
    vistas.current = nMsgs
  }, [nMsgs, painel, lendo, ocupado])
  const irAoFim = () => { const el = rolagem.current; if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }); setNovas(false) }
  const [textoAberto, setTextoAberto] = useState<Msg | null>(null)
  if (!d) return erro ? <p className="texto">{erro}</p> : null
  // ORDEM 062: só o último resumo leva os botões, enquanto espera a confirmação
  const ultimoResumo = [...d.mensagens].reverse().find((m) => m.tipo === 'entendimento')?.id
  return (
    <section className={`conversa-jdb relative${painel ? ' conversa-painel' : ''}`} aria-label="Conversa do cliente" {...soltar.props}>
      {soltar.arrastando && <SolteAqui />}
      <div className="rolagem-conversa" ref={rolagem}
           onScroll={(e) => { const el = e.currentTarget; if (el.scrollHeight - el.scrollTop - el.clientHeight < 80) setNovas(false) }}>
      <ul className="bolhas">
        {d.mensagens.map((m) => (
          <Mensagem key={m.id} m={m} aoVer={setVerConversa} aoVerTexto={setTextoAberto} ocupado={ocupado}
                    aoEscolher={(valor, pergunta) => void agir(() => post<Estado>(`/clientes/${clienteId}/escolha`, { pergunta: pergunta || 'solicitante', valor }))}
                    acoes={m.id === ultimoResumo && d.contexto.entendimento_status === 'aguardando' ? (
                      <div className="botoes">
                        <button type="button" className="btn-verde" disabled={ocupado}
                                onClick={() => void agir(() => post<Estado>(`/clientes/${clienteId}/entendimento/confirmar`))}>
                          É isso, pode começar
                        </button>
                        <button type="button" className="btn-sec-grande" disabled={ocupado}
                                onClick={() => { setExplicando(true); campo.current?.focus() }}>
                          Quero explicar mais
                        </button>
                      </div>
                    ) : undefined} />
        ))}
      </ul>
      {(ocupado || lendo) && <p className="lendo" role="status"><span className="pontos" aria-hidden="true" />{lendo ? d.importacao?.texto || 'Estou lendo…' : 'Estou lendo…'}</p>}
      {aviso && <p className="aviso-simples" role="status">{aviso}</p>}
      {d.importacao?.estado === 'erro' && (
        <div className="aviso-impede flex flex-wrap items-center justify-between gap-2" role="alert">
          <span>{d.importacao.texto || 'Não consegui terminar a leitura.'}</span>
          {d.importacao.retomar && <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} disabled={ocupado}
                                           onClick={() => void agir(() => post<Estado>(`/clientes/${clienteId}/importar/retomar`))}>Tentar de novo</button>}
        </div>
      )}
      {erro && <p className="aviso-impede" role="alert">{erro}</p>}
      </div>
      {painel && novas && <button type="button" className="novas-l63" onClick={irAoFim}>↓ novas mensagens</button>}
      {verConversa && <ConversaCompleta clienteId={clienteId} importacao={verConversa} aoFechar={() => setVerConversa('')} />}
      {textoAberto && <TextoCompleto m={textoAberto} aoFechar={() => setTextoAberto(null)} />}
      {colado && (                                                    // 167-2: prévia do print colado
        <div className="cartao-pad flex flex-wrap items-center gap-3" role="group" aria-label="Imagem colada">
          <img src={colado.url} alt="Imagem colada (prévia)" style={{ maxHeight: 140, maxWidth: 260, borderRadius: 8, border: '1px solid #ddd' }} />
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-verde" style={{ width: 'auto' }} disabled={ocupado} onClick={() => void enviarColado()}>
              Enviar imagem</button>
            <button type="button" className="btn-sec-grande" style={{ width: 'auto' }}
                    onClick={() => { URL.revokeObjectURL(colado.url); setColado(null) }}>Cancelar</button>
          </div>
        </div>
      )}
      <form className="escrever" onSubmit={(e) => { e.preventDefault(); void enviar() }} onPaste={colar}>
        <label className="clipe" title="Anexar documento ou foto">
          <Paperclip size={22} aria-hidden="true" /><span className="sr-only">Anexar documento ou foto</span>
          <input type="file" hidden multiple accept={ACEITOS} onChange={(e) => { void anexar(e.target.files); e.target.value = '' }} />
        </label>
        <label htmlFor={`escrever-${clienteId}`} className="sr-only">Escreva o que aconteceu</label>
        {/* 105-1: Enter pula linha; envia pelo botão ou Ctrl+Enter; o campo cresce até ~8 linhas e depois rola */}
        <textarea id={`escrever-${clienteId}`} ref={campo} className="escrever-campo" value={texto} rows={1}
                  onChange={(e) => {
                    setTexto(e.target.value)
                    const el = e.target; el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 8 * 28)}px`
                  }}
                  onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void enviar() } }}
                  style={{ resize: 'none', overflowY: 'auto', maxHeight: 8 * 28, lineHeight: '28px' }}
                  placeholder={explicando ? 'Conte o que falta ou o que não está certo… (Ctrl+Enter envia)' : 'Escreva o que aconteceu… (Enter pula linha; Ctrl+Enter envia)'}
                  autoComplete="off" />
        <FalarAqui alvo={`escrever-${clienteId}`} valor={texto} aoMudar={setTexto} rotulo={false} />
        <button type="submit" className="enviar" disabled={ocupado || !texto.trim()} aria-label="Enviar"><SendHorizontal size={22} aria-hidden="true" /></button>
      </form>
    </section>
  )
}

/** ORDEM 063: conversa colada ou texto com mais de ~15 linhas vira um cartão de uma linha com [Ver]. */
export function resumoLongo(m: { texto: string; tipo: string; autor: string }): string | null {
  const linhas = m.texto.split('\n')
  if (m.autor !== 'avaliador' || (linhas.length <= 15 && m.texto.length <= 1500)) return null
  const msgsWpp = linhas.filter((l) => /^\[?\d{1,2}\/\d{1,2}\/\d{2,4}/.test(l.trim())).length
  if (msgsWpp >= 3) return `Conversa do WhatsApp colada · ${msgsWpp.toLocaleString('pt-BR')} mensagens`
  const palavras = m.texto.split(/\s+/).filter(Boolean).length
  return `Texto colado · ${palavras.toLocaleString('pt-BR')} palavras`
}

function TextoCompleto({ m, aoFechar }: { m: Msg; aoFechar: () => void }) {
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Escape') aoFechar() }
    document.addEventListener('keydown', tecla)
    return () => document.removeEventListener('keydown', tecla)
  }, [aoFechar])
  return createPortal(
    <div className="painel-l13-fundo" onMouseDown={(e) => { if (e.target === e.currentTarget) aoFechar() }}>
      <section className="painel-conversa" role="dialog" aria-modal="true" aria-labelledby="titulo-texto">
        <div className="painel-conversa-topo">
          <h2 id="titulo-texto" className="titulo-sub-l13">{resumoLongo(m) ?? 'Texto'}</h2>
          <button type="button" className="btn-opcoes" onClick={aoFechar} autoFocus><X size={20} aria-hidden="true" /> Fechar</button>
        </div>
        <p className="msg-texto texto-completo-l63">{m.texto}</p>
      </section>
    </div>,
    document.body,
  )
}

/** ORDEM 066: card de escolha "Quem está contratando o laudo?" (a recomendada primeiro, e "Outro"). */
function Escolha({ m, ocupado, aoEscolher }: { m: Msg; ocupado?: boolean; aoEscolher?: (v: string, pergunta?: string) => void }) {
  const [outro, setOutro] = useState(false)
  const [nome, setNome] = useState('')
  if (m.dados.respondida) return <p className="small-jdb">✓ {m.dados.respondida}</p>
  if (!aoEscolher) return null
  return (
    <div className="grid gap-2">
      <div className="botoes">
        {(m.dados.opcoes ?? []).map((o) => (
          <button key={o.valor} type="button" className={o.recomendada ? 'btn-verde' : 'btn-sec-grande'} disabled={ocupado}
                  onClick={() => aoEscolher(o.valor, m.dados.pergunta)}>{o.rotulo}</button>
        ))}
        {m.dados.outro && !outro && <button type="button" className="btn-sec-grande" onClick={() => setOutro(true)}>Outro: escrever</button>}
      </div>
      {outro && (
        <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (nome.trim().length > 1) aoEscolher(nome.trim(), m.dados.pergunta) }}>
          <label className="sr-only" htmlFor={`outro-${m.id}`}>{m.dados.pergunta === 'cpf' ? 'CPF certo' : 'Nome de quem contrata'}</label>
          <input id={`outro-${m.id}`} className="campo-grande flex-1" value={nome} onChange={(e) => setNome(e.target.value)}
                 placeholder={m.dados.pergunta === 'cpf' ? 'CPF certo' : 'Nome de quem contrata'} autoFocus />
          <button type="submit" className="btn-verde" style={{ width: 'auto' }} disabled={ocupado || nome.trim().length < 2}>Confirmar</button>
        </form>
      )}
    </div>
  )
}

function Mensagem({ m, aoVer, aoVerTexto, acoes, ocupado, aoEscolher }: {
  m: Msg; aoVer?: (importacao: string) => void; aoVerTexto?: (m: Msg) => void; acoes?: ReactNode
  ocupado?: boolean; aoEscolher?: (v: string, pergunta?: string) => void
}) {
  const [copiado, setCopiado] = useState(false)
  const meu = m.autor === 'avaliador'
  const longo = resumoLongo(m)
  return (
    <li className={meu ? 'bolha bolha-eu' : m.tipo === 'pergunta' ? 'bolha bolha-pergunta' : 'bolha bolha-jdb'}>
      {longo ? (
        <p className="cartao-fechado-l63">
          <span>{longo}</span>
          {aoVerTexto && <button type="button" className="det-l13" onClick={() => aoVerTexto(m)}>Ver</button>}
        </p>
      ) : (
        <>
          {m.tipo === 'whatsapp' && <p className="bloco-rotulo">WhatsApp colado</p>}
          <p className="msg-texto">{m.texto}</p>
        </>
      )}
      {acoes}
      {m.tipo === 'escolha' && <Escolha m={m} ocupado={ocupado} aoEscolher={aoEscolher} />}
      {m.tipo === 'editavel' && m.dados.job_id && (     // 167-3: o chat aponta onde se faz a mudança no laudo pronto
        <button type="button" className="btn-verde" style={{ width: 'auto', justifySelf: 'start' }}
                onClick={() => { useStore.getState().ir('job', String(m.dados.job_id)) }}>
          <FileEdit size={20} aria-hidden="true" /> Abrir o trabalho</button>
      )}
      {m.tipo === 'importacao' && m.dados.importacao && !!m.dados.mensagens && aoVer && (
        <button type="button" className="btn-sec-grande" style={{ width: 'auto', justifySelf: 'start' }} onClick={() => aoVer(m.dados.importacao!)}>
          Ver a conversa completa
        </button>
      )}
      {m.dados.mensagem_pronta && (
        <div className="msg-pronta cartao-msg cartao-msg-verde">
          <p className="cartao-msg-rotulo">Mensagem pronta</p>
          <p>{m.dados.mensagem_pronta}</p>
          <button type="button" className="btn-sec-grande" onClick={() => { void navigator.clipboard.writeText(m.dados.mensagem_pronta!); setCopiado(true) }}>
            {copiado ? 'Copiada' : 'Copiar mensagem'}
          </button>
        </div>
      )}
      {m.dados.arquivos && m.dados.proposta_id && (
        <div className="botoes">
          {m.dados.arquivos.filter((a) => a.endsWith('.pdf')).map((a) => (
            <button key={a} type="button" className="btn-sec-grande" onClick={() => void abrirComToken(`/propostas/${m.dados.proposta_id}/arquivo/${encodeURIComponent(a)}`)}>
              Abrir {a.toLowerCase().includes('contrato') ? 'contrato' : 'proposta'} (PDF)
            </button>
          ))}
        </div>
      )}
    </li>
  )
}

function PainelEtapa({ e, d, agir }: { e: Etapa; d: Estado; agir: (f: () => Promise<unknown>) => Promise<void> }) {
  const ir = useStore((s) => s.ir)
  const [quando, setQuando] = useState('')
  const status = { feito: 'Feito', revisar: 'Revisar', falta: 'Falta', espera: 'Espera', agendada: 'Agendada', decidir: 'Decidir', andando: 'Andando', pronto: 'Pronto' }[e.status] ?? e.status
  return (
    <li className={`painel-etapa ${e.etapa === d.etapa_atual ? 'painel-atual' : ''}`}>
      <p className="painel-titulo">{ROTULO[e.etapa]} <span className="painel-status">{status}</span></p>
      {e.falta.length > 0 && <p className="texto">Falta: {e.falta.join('; ')}</p>}
      {/* ORDEM 065: aprovar a proposta e o contrato fica num lugar só, no PRÓXIMO PASSO */}
      {e.etapa === 'proposta' && e.status === 'revisar' && d.sugestao && (
        <p className="texto">{MOD[d.sugestao.modalidade] ?? d.sugestao.modalidade} · R$ {d.sugestao.valor} · {d.sugestao.prazo}{d.sugestao.da_tabela ? ' · da sua tabela de preços' : ''}</p>
      )}
      {e.etapa === 'visita' && e.status === 'falta' && (
        <>
          <label className="texto" htmlFor="quando">Data e hora</label>
          <input id="quando" type="datetime-local" className="campo-grande" value={quando} onChange={(x) => setQuando(x.target.value)} />
          <button type="button" className="btn-verde" disabled={!quando} onClick={() => void agir(() => post(`/clientes/${d.id}/visita`, { quando }))}>Marcar visita</button>
        </>
      )}
      {e.etapa === 'visita' && e.status !== 'falta' && (
        <div className="botoes">
          {d.visita && <p className="texto">{d.visita.legivel}</p>}
          <button type="button" className="btn-sec-grande" onClick={() => void abrirComToken(`/clientes/${d.id}/vistoria?app=${encodeURIComponent(location.origin + location.pathname)}`)}>Abrir página da vistoria</button>
          {!d.job_id && <button type="button" className="btn-verde" onClick={() => void agir(() => post(`/clientes/${d.id}/trabalho`))}>Seguir para o laudo</button>}
        </div>
      )}
      {e.etapa === 'laudo' && d.job_id && (
        <button type="button" className="btn-verde" onClick={() => ir(e.status === 'decidir' ? 'alinhamento' : 'job', d.job_id)}>
          {e.status === 'decidir' ? 'Referenciais e alinhamento' : 'Abrir o laudo'}
        </button>
      )}
    </li>
  )
}

// ---------------------------------------------------------------- ORDEM 063: tela do cliente
const CHAVE_COLUNA = 'jdb-coluna-cliente'
type Painel = 'proposta' | 'contrato' | 'visita' | 'etapas' | 'dados' | 'portao' | null
interface Botao { rotulo: string; acao: () => void; principal?: boolean }
interface Passo { titulo: string; linha?: string; botoes: Botao[]; portao?: 'proposta' | 'contrato' | 'visita' }

const txt = (v: unknown) => (typeof v === 'string' ? v.trim() : '')

/** Resumo do caso: dados do "Entendimento do caso" (062) e do trabalho. Sem dado: "—", nunca inventado. */
interface LinhaDado { campo: string; rotulo: string; valor: string; editavel: boolean; corrigido: boolean; bruto: string }

/** ORDEM 066: todos os dados guardados do cliente, em português, cada um com [Corrigir]. */
function DadosCliente({ cid, versao, ocupado, corrigir }: {
  cid: string; versao: number; ocupado: boolean; corrigir: (campo: string, valor: string) => Promise<void>
}) {
  const [linhas, setLinhas] = useState<LinhaDado[] | null>(null)
  const [editando, setEditando] = useState<string | null>(null)
  const [valor, setValor] = useState('')
  useEffect(() => { get<{ linhas: LinhaDado[] }>(`/clientes/${cid}/dados`).then((r) => setLinhas(r.linhas)).catch(() => setLinhas([])) }, [cid, versao])
  if (!linhas) return <p className="small-jdb">Carregando…</p>
  return (
    <ul className="lista-l13">
      {linhas.map((l, i) => (
        <li key={`${l.campo}-${i}`} className="grid gap-1">
          <span className="small-jdb">{l.rotulo}{l.corrigido ? ' · corrigido por você' : ''}</span>
          {editando === l.campo ? (
            <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); void corrigir(l.campo, valor).then(() => setEditando(null)) }}>
              <label className="sr-only" htmlFor={`dado-${l.campo}`}>{l.rotulo}</label>
              {l.campo === 'modalidade' ? (
                <select id={`dado-${l.campo}`} className="campo-grande flex-1" value={valor} onChange={(e) => setValor(e.target.value)}>
                  {Object.entries(MOD).map(([k, r]) => <option key={k} value={k}>{r}</option>)}
                </select>
              ) : (
                <input id={`dado-${l.campo}`} className="campo-grande flex-1" value={valor} onChange={(e) => setValor(e.target.value)} autoFocus />
              )}
              <button type="submit" className="btn-verde" style={{ width: 'auto' }} disabled={ocupado}>Salvar</button>
              <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} onClick={() => setEditando(null)}>Cancelar</button>
            </form>
          ) : (
            <span className="flex flex-wrap items-center justify-between gap-2">
              <b className="break-words">{l.valor}</b>
              {l.editavel && <button type="button" className="det-l13" onClick={() => { setEditando(l.campo); setValor(l.bruto) }}>Corrigir</button>}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

function ResumoCaso({ d, aoCorrigir }: { d: Estado; aoCorrigir?: () => void }) {
  const c = d.contexto
  const mod = MOD[txt(c.modalidade)] || (txt(c.modalidade_sugerida) ? `${MOD[txt(c.modalidade_sugerida)] ?? txt(c.modalidade_sugerida)} (sugerida)` : '')
  const fin = txt(c.finalidade) || (txt(c.finalidade_sugerida) ? `${txt(c.finalidade_sugerida)} (sugerida)` : '')
  const valor = d.sugestao?.valor || txt(c.valor_combinado)
  const linhas: [string, string][] = [
    ['Cliente', d.nome || txt(c.solicitante_nome)],
    ['Imóvel', [txt(c.imovel_tipo), txt(c.bairro)].filter(Boolean).join(' · ')],
    ['Modalidade', mod], ['Finalidade', fin],
    ['Valor · prazo', [valor ? `R$ ${valor}` : '', txt(c.prazo) || d.sugestao?.prazo || ''].filter(Boolean).join(' · ')],
  ]
  if (txt(c.prazo_malha)) linhas.push(['Prazo da malha', txt(c.prazo_malha)])     // 072-C3: não é o prazo de entrega
  const falta = d.pendencias.slice(0, 3).map((p) => p.texto.charAt(0).toLowerCase() + p.texto.slice(1))
  return (
    <section className="resumo-l63" aria-labelledby="titulo-resumo-caso">
      <h2 id="titulo-resumo-caso" className="rotulo-l63">Resumo do caso</h2>
      <dl>
        {linhas.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v || '—'}</dd></div>)}
      </dl>
      {falta.length > 0 && <p className="falta-l63">Falta: {falta.join('; ')}</p>}
      {aoCorrigir && <button type="button" className="det-l13 justify-self-start" onClick={aoCorrigir}>Ver e corrigir os dados</button>}
    </section>
  )
}

function proximoPasso(d: Estado, abrir: (p: Painel) => void, agir: (f: () => Promise<unknown>, ok?: string) => Promise<void>, ir: (t: 'job' | 'laudo', id: string) => void): Passo | null {
  const c = d.contexto
  const atual = d.etapas.find((e) => e.etapa === d.etapa_atual)
  const post_ = (url: string, corpo?: unknown, ok?: string) => () => void agir(() => post(url, corpo), ok)
  if (d.importacao?.estado === 'trabalhando') {           // 070-B3: durante a leitura, sem botão; diz o que falta
    return { titulo: 'O JdB está lendo a conversa', linha: d.importacao.texto, botoes: [] }
  }
  if (c.entendimento_status === 'aguardando') {
    return { titulo: 'Confirme o que eu entendi', linha: 'O resumo está na conversa.',
      botoes: [{ rotulo: 'É isso, pode começar', principal: true, acao: post_(`/clientes/${d.id}/entendimento/confirmar`, undefined, '✓ Combinado. Comecei.') }] }
  }
  if (atual?.etapa === 'proposta' && d.contrato_existente) {    // 072-C5: o contrato já foi assinado antes da proposta
    const ce = d.contrato_existente
    const quem = txt(c.solicitante_nome).split(' ')[0] || 'o cliente'
    return { titulo: 'A proposta não precisa ir',
      linha: `Você já mandou o contrato${ce.data_legivel ? ` em ${ce.data_legivel}` : ''}${ce.sinal_pago ? ` e ${quem} pagou o sinal` : ''}.`,
      botoes: [{ rotulo: 'Pular a proposta', principal: true, acao: post_(`/clientes/${d.id}/proposta/pular`, undefined, '✓ Proposta pulada: vale o contrato que você mandou.') },
               { rotulo: 'Fazer a proposta assim mesmo', acao: post_(`/clientes/${d.id}/proposta/mesmo-assim`) }] }
  }
  if (atual?.etapa === 'proposta' && atual.status === 'revisar' && d.sugestao) {
    return { titulo: 'Revisar a proposta', portao: 'proposta',
      linha: `${MOD[d.sugestao.modalidade] ?? d.sugestao.modalidade} · ${d.sugestao.valor ? `R$ ${d.sugestao.valor}` : 'falta o valor'}`
        + (d.sugestao.da_tabela ? ' (da sua tabela de preços; para mudar só nesta proposta: Dados do cliente › Valor combinado)' : ''),   // 184
      botoes: [{ rotulo: 'Aprovar e gerar mensagem', principal: true, acao: post_(`/clientes/${d.id}/proposta/aprovar`, undefined, '✓ Proposta aprovada.') },
               { rotulo: 'Ver a proposta', acao: () => abrir('proposta') }] }
  }
  if (atual?.etapa === 'contrato' && atual.status !== 'espera') {
    const falta = atual.status === 'falta' ? atual.falta : []
    return { titulo: falta.length ? 'Pedir os dados do contrato' : 'Revisar o contrato', portao: 'contrato',
      linha: falta.length ? `Falta: ${falta.join(', ')}` : undefined,
      botoes: [{ rotulo: falta.length ? 'Gerar mensagem para pedir' : 'Aprovar e gerar mensagem', principal: true,
                 acao: post_(`/clientes/${d.id}/contrato/aprovar`, { pagamento: 'pix' }, falta.length ? '✓ Mensagem para pedir os dados pronta.' : '✓ Contrato pronto.') },
               { rotulo: 'Ver o contrato', acao: () => abrir('contrato') }] }
  }
  if (c.visita_feita && !d.job_id) {                       // 069-A7: visita feita → o próximo passo é o laudo, no card de cima
    return { titulo: 'Montar o laudo', linha: d.visita?.legivel ? `Visita feita: ${d.visita.legivel}` : 'Visita feita.', portao: 'visita',
      // 096-5: abre o trabalho e já leva para a tela dele (sem o toque a mais em "Abrir o trabalho")
      botoes: [{ rotulo: 'Montar o laudo', principal: true, acao: () => void agir(async () => {
        const e = await post<{ job_id?: string | null }>(`/clientes/${d.id}/trabalho`)
        if (e?.job_id) ir('job', e.job_id)
      }, '✓ Trabalho aberto.') }] }
  }
  if (atual?.etapa === 'visita' && atual.status === 'falta') {
    return { titulo: 'Marcar a visita', botoes: [{ rotulo: 'Marcar a visita', principal: true, acao: () => abrir('visita') }] }
  }
  if (d.job_id) {
    return { titulo: 'O trabalho já está aberto', linha: 'O laudo segue na tela do trabalho.',
      botoes: [{ rotulo: 'Abrir o trabalho', principal: true, acao: () => ir('job', d.job_id) }] }
  }
  if (atual?.etapa === 'visita' && atual.status !== 'falta') {
    return { titulo: 'Seguir para o laudo', linha: d.visita?.legivel,
      botoes: [{ rotulo: 'Seguir para o laudo', principal: true, acao: post_(`/clientes/${d.id}/trabalho`, undefined, '✓ Trabalho aberto.') },
               { rotulo: 'Página da vistoria', acao: () => void abrirComToken(`/clientes/${d.id}/vistoria?app=${encodeURIComponent(location.origin + location.pathname)}`) }] }
  }
  if (d.pendencias.length) {
    const p0 = d.pendencias[0].texto
    return { titulo: p0.charAt(0).toUpperCase() + p0.slice(1), linha: 'Escreva na conversa: o JdB anota.',
      botoes: [{ rotulo: 'Ver o que falta', acao: () => abrir('etapas') }] }
  }
  return null
}

function BotoesPasso({ passo, ocupado, so, travado, aoTravado }: { passo: Passo; ocupado: boolean; so?: 'principal'; travado?: boolean; aoTravado?: () => void }) {
  // faixa (celular / coluna fechada): a ação principal e o "Ver a proposta/contrato" — ver antes de aprovar (ORDEM 065)
  const bs = so === 'principal' ? passo.botoes.filter((b) => b.principal || b.rotulo.startsWith('Ver a') || b.rotulo.startsWith('Ver o')).slice(0, 2) : passo.botoes
  return (
    <div className="botoes">
      {bs.map((b) => (
        <button key={b.rotulo} type="button" className={b.principal ? 'btn-verde' : 'btn-sec-grande'} disabled={ocupado}
                onClick={b.principal && travado && aoTravado ? aoTravado : b.acao}>{b.rotulo}</button>   // 102-2: nunca mudo
      ))}
    </div>
  )
}

/** Painel por cima da conversa: lateral no computador, tela cheia no celular. */
function PainelSobre({ titulo, aoFechar, children }: { titulo: string; aoFechar: () => void; children: ReactNode }) {
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Escape') aoFechar() }
    document.addEventListener('keydown', tecla)
    return () => document.removeEventListener('keydown', tecla)
  }, [aoFechar])
  return createPortal(
    <div className="painel-l13-fundo" onMouseDown={(e) => { if (e.target === e.currentTarget) aoFechar() }}>
      <section className="painel-conversa painel-sobre-l63" role="dialog" aria-modal="true" aria-label={titulo}>
        <div className="painel-conversa-topo">
          <h2 className="titulo-sub-l13">{titulo}</h2>
          <button type="button" className="btn-opcoes" onClick={aoFechar} autoFocus><X size={20} aria-hidden="true" /> Fechar</button>
        </div>
        <div className="painel-sobre-corpo">{children}</div>
      </section>
    </div>,
    document.body,
  )
}

export function ConversaCliente() {
  const id = useStore((s) => s.jobId)
  const ir = useStore((s) => s.ir)
  const [d, setD] = useState<Estado | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState('')
  const [painel, setPainel] = useState<Painel>(null)
  const [resumoAberto, setResumoAberto] = useState(false)
  const [coluna, setColuna] = useState(() => { try { return localStorage.getItem(CHAVE_COLUNA) !== 'fechada' } catch { return true } })
  const alternarColuna = () => setColuna((c) => {
    try { localStorage.setItem(CHAVE_COLUNA, c ? 'fechada' : 'aberta') } catch { /* sem armazenamento: só nesta visita */ }
    return !c
  })
  const [tentar, setTentar] = useState(0)
  const carregar = useCallback(() => { if (id) get<Estado>(`/clientes/${id}`).then((e) => { setD(e); setErro('') }).catch((e) => {
    if (e instanceof ApiError && e.status === 404) { setErro('Cliente não encontrado.'); return }
    setErro('O JdB está reiniciando. Tento de novo em instantes.')     // 081-1: tenta de novo sozinho
    setTimeout(() => setTentar((n) => n + 1), 4000)
  }) }, [id, tentar])
  useEffect(carregar, [carregar])
  const [versao, setVersao] = useState(0)          // a conversa recarrega quando um botão daqui muda algo
  // ORDEM 065: rascunho real da proposta e do contrato, refeito quando os dados mudam
  const etapaAgora = d?.etapas.find((e) => e.etapa === d.etapa_atual)
  // 083-C4: contrato já mandado → a proposta não precisa ir: não monta rascunho
  const emProposta = !!(d?.sugestao && etapaAgora?.etapa === 'proposta' && etapaAgora.status === 'revisar' && !d?.contrato_existente)
  const emContrato = !!(etapaAgora?.etapa === 'contrato' && etapaAgora.status === 'revisar')
  const dadosVersao = d ? JSON.stringify(d.contexto) : ''
  const rp = useRascunho(d?.id ?? null, 'proposta', emProposta, dadosVersao)
  const rc = useRascunho(d?.id ?? null, 'contrato', emContrato, dadosVersao)
  // ORDEM 071: os portões — perguntas obrigatórias antes da proposta e do contrato
  const etapaContrato = !!(etapaAgora?.etapa === 'contrato' && etapaAgora.status !== 'espera' && etapaAgora.status !== 'feito')
  const [gp, setGp] = usePortao(d?.id ?? null, 'proposta', emProposta, dadosVersao)
  const [gc, setGc] = usePortao(d?.id ?? null, 'contrato', etapaContrato, dadosVersao)
  // 072-C10 / 074: o portão da visita — fotos da vistoria, pin, data-base e as perguntas da análise do relato
  const [gv, setGv] = usePortao(d?.id ?? null, 'visita', !!(d?.contexto.visita_feita && !d?.job_id), dadosVersao)   // 074: fotos, pin, data-base
  // ORDEM 065-A: clique nunca fica sem resposta — "✓ feito" (com a mensagem pronta) ou o que falta
  const [feito, setFeito] = useState<{ titulo: string; mensagem?: string } | null>(null)
  const [apagandoCli, setApagandoCli] = useState(false)       // 183
  const [apagandoErro, setApagandoErro] = useState('')
  const [copiado, setCopiado] = useState(false)
  async function agir(f: () => Promise<unknown>, ok?: string) {
    setErro(''); setFeito(null); setCopiado(false); setOcupado(true)
    const antes = Math.max(0, ...(d?.mensagens.map((m) => m.id) ?? []))
    const pronta = (e: Estado) => [...e.mensagens].reverse().find((m) => m.id > antes && m.dados.mensagem_pronta)?.dados.mensagem_pronta
    try {
      await f(); setPainel(null)
      const novo = await get<Estado>(`/clientes/${id}`)
      setD(novo)
      setFeito({ titulo: ok ?? '✓ Feito.', mensagem: pronta(novo) })
    } catch (e) {
      const novo = await get<Estado>(`/clientes/${id}`).catch(() => null)
      if (novo) setD(novo)
      const msg = novo ? pronta(novo) : undefined
      if (e instanceof ApiError && e.status === 409 && msg) setFeito({ titulo: `Faltam dados do cliente: ${e.message.replace(/^falta: /, '')}. Mensagem para pedir:`, mensagem: msg })
      else setErro(erroDe(e).replace(/^falta: /, 'Falta: '))
    } finally { setOcupado(false); setVersao((v) => v + 1) }
  }
  if (erro && !d) return <p className="texto-grande">{erro}</p>
  if (!d) return <p className="texto-grande" role="status">Abrindo…</p>
  const ctx = d.contexto
  const tipoImovel = txt(ctx.imovel_tipo)
  async function apagarCliente() {         // 183: vai para a Lixeira (restaurável), nunca apaga de vez com um toque
    if (!d) return
    setApagandoErro('')
    try { await post(`/clientes/${d.id}/lixeira`); setApagandoCli(false); ir('lista') }
    catch (e) { setApagandoErro(e instanceof ApiError ? e.message : 'Não deu para apagar. Tente de novo.') }
  }
  const imovel = [tipoImovel.charAt(0).toUpperCase() + tipoImovel.slice(1), txt(ctx.bairro)].filter(Boolean).join(' · ')
  const sub = [d.nome, MOD[txt(ctx.modalidade)] ?? ''].filter(Boolean).join(' · ')
  const passo = proximoPasso(d, setPainel, agir, (t, jid) => ir(t, jid))
  const portao = passo?.portao === 'proposta' ? gp : passo?.portao === 'contrato' ? gc : passo?.portao === 'visita' ? gv : null
  const travado = !!portao && !portao.completo && !portao.usou_existente
  const aoPortao = (p: typeof gp) => { if (p?.etapa === 'contrato') setGc(p); else if (p?.etapa === 'visita') setGv(p); else setGp(p); carregar() }
  const usarExistente = () => void agir(() => post(`/clientes/${d.id}/contrato/existente`), '✓ Contrato marcado como feito, com o arquivo que você mandou.')
  const cartaoPortao = portao && (
    <CartaoPortao cid={d.id} p={portao} aoMudar={aoPortao} usarExistente={usarExistente} />
  )
  const atual = d.etapas.find((e) => e.etapa === d.etapa_atual)
  const cartaoPasso = passo && (
    <div className="proximo-passo passo-l63">
      <span className="tag-jdb">Próximo passo</span>
      {passo.titulo === 'O JdB está lendo a conversa' && <Espera voar={false} />}{/* 123-3 */}
      <h2 className="titulo-cartao">{passo.titulo}</h2>
      {passo.linha && <p className="small-jdb">{passo.linha}</p>}
      <div id="portao-do-passo">{cartaoPortao}</div>
      {emProposta && <Miniatura cid={d.id} qual="proposta" {...rp} aoAbrir={() => setPainel('proposta')} />}
      {emContrato && <Miniatura cid={d.id} qual="contrato" {...rc} aoAbrir={() => setPainel('contrato')} />}
      <BotoesPasso passo={passo} ocupado={ocupado} travado={travado} aoTravado={() => {
        // 102-2: diz o que falta e leva até a pergunta
        const abertas = (portao?.perguntas ?? []).filter((q) => !q.confirmado).map((q) => q.pergunta)
        setErro(abertas.length ? `Antes de seguir, responda: ${abertas.join('; ')}` : 'Antes de seguir, confirme os pontos acima.')
        document.getElementById('portao-do-passo')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }} />
      {erro && <p className="aviso-impede" role="alert">{erro}</p>}
    </div>
  )
  const telefone = String(ctx.solicitante_telefone || '').replace(/\D/g, '')
  const cartaoFeito = feito && (
    <div className="feito-065" role="status">
      <div className="flex items-start justify-between gap-2">
        <p className="titulo-sub-l13">{feito.titulo}</p>
        <button type="button" className="link-discreto" onClick={() => setFeito(null)}>Fechar</button>
      </div>
      {feito.mensagem && (
        <>
          <p className="small-jdb">Mensagem pronta para você mandar:</p>
          <p className="msg-texto">{feito.mensagem}</p>
          <div className="botoes">
            <button type="button" className="btn-sec-grande" onClick={() => { void navigator.clipboard.writeText(feito.mensagem!); setCopiado(true) }}>
              {copiado ? '✓ Copiada' : 'Copiar'}
            </button>
            <a className="btn-sec-grande" target="_blank" rel="noopener"
               href={`https://wa.me/${telefone.length >= 10 ? telefone : ''}?text=${encodeURIComponent(feito.mensagem)}`}>Abrir no WhatsApp</a>
          </div>
        </>
      )}
    </div>
  )
  return (
    <section className={`cliente-l63${coluna ? '' : ' fechada'}`}>
      {coluna && (
        <aside className="coluna-l63" aria-label="Próximo passo e resumo do caso">
          <div className="flex items-center justify-between gap-2">
            <button type="button" className="voltar-jdb" onClick={() => ir('lista')}>← Trabalhos</button>
            <button type="button" className="btn-opcoes" onClick={alternarColuna} aria-label="Fechar a coluna do resumo" title="Fechar a coluna">«</button>
          </div>
          <div>
            <h1 className="titulo-l63">{imovel || d.nome || 'Cliente novo'}</h1>
            <p className="sub-jdb">{sub || 'Imóvel ainda não informado'}</p>
          </div>
          <ol className="etapas-l63" aria-label="Etapas">
            {d.etapas.map((e) => (
              <li key={e.etapa} aria-current={e.etapa === d.etapa_atual ? 'step' : undefined}
                  className={e.status === 'feito' ? 'ok' : e.etapa === d.etapa_atual ? 'now' : ''}>
                {e.status === 'feito' ? '✓ ' : e.status === 'fora' ? '– ' : ''}{ROTULO[e.etapa]}
              </li>
            ))}
          </ol>
          {cartaoPasso}
          <ResumoCaso d={d} aoCorrigir={() => setPainel('dados')} />
          <details className="detalhes detalhes-jdb">
            <summary>Mais</summary>
            <div className="detalhes-corpo">
              <button type="button" className="btn-sec-grande" style={{ width: 'auto', justifySelf: 'start' }} onClick={() => setPainel('etapas')}>Ver todas as etapas</button>
              <button type="button" className="btn-sec-grande" style={{ width: 'auto', justifySelf: 'start' }}
                      onClick={() => { setApagandoErro(''); setApagandoCli(true) }}>Apagar este cliente</button>
              {apagandoCli && (
                <Confirmar titulo={`Apagar o cliente ${d.nome || ''}?`.replace(' ?', '?')}
                           texto="Ele sai da lista e vai para a Lixeira (Configurações › Lixeira), com a conversa e os arquivos. De lá dá para restaurar."
                           rotuloConfirmar="Apagar" perigo erro={apagandoErro}
                           aoConfirmar={() => void apagarCliente()} aoCancelar={() => setApagandoCli(false)} />
              )}
            </div>
          </details>
        </aside>
      )}
      <div className="direita-l63">
        {/* celular: faixa fixa no topo; computador com a coluna fechada: faixa fina no topo da conversa */}
        <div className="faixa-l63">
          <button type="button" className="btn-opcoes so-coluna-fechada" onClick={alternarColuna} aria-label="Abrir a coluna do resumo" title="Abrir a coluna">»</button>
          <div className="min-w-0 flex-1">
            <p className="faixa-titulo">{passo ? passo.titulo : imovel || d.nome}</p>
            <button type="button" className="faixa-resumo so-celular-l63" aria-expanded={resumoAberto} onClick={() => setResumoAberto(!resumoAberto)}>
              {resumoAberto ? '▾' : '▸'} Resumo do caso
            </button>
          </div>
          {passo && travado ? (
            <div className="botoes"><button type="button" className="btn-verde" onClick={() => setPainel('portao')}>
              Confirmar os pontos ({portao!.abertas.length})</button></div>
          ) : passo && <BotoesPasso passo={passo} ocupado={ocupado} so="principal" />}
        </div>
        {resumoAberto && (
          <div className="resumo-sobre-l63 so-celular-l63">
            <ResumoCaso d={d} aoCorrigir={() => { setResumoAberto(false); setPainel('dados') }} />
            <button type="button" className="btn-sec-grande" onClick={() => setResumoAberto(false)}>Fechar o resumo</button>
          </div>
        )}
        {cartaoFeito}
        {erro && !coluna && <p className="aviso-impede" role="alert">{erro}</p>}
        <ConversaFeed key={versao} painel clienteId={d.id} aoMudar={carregar} />
      </div>
      {painel === 'proposta' && d.sugestao && (
        <PainelDocumento cid={d.id} qual="proposta" meta={rp.meta} ocupado={ocupado} erro={rp.erro || erro} aoFechar={() => setPainel(null)}
                         aprovar={emProposta && !(gp && !gp.completo) ? { rotulo: 'Aprovar e gerar mensagem', acao: () => void agir(() => post(`/clientes/${d.id}/proposta/aprovar`), '✓ Proposta aprovada.') } : undefined} />
      )}
      {painel === 'contrato' && emContrato && (
        <PainelDocumento cid={d.id} qual="contrato" meta={rc.meta} ocupado={ocupado} erro={rc.erro || erro} aoFechar={() => setPainel(null)}
                         aprovar={{ rotulo: 'Aprovar e gerar mensagem', acao: () => void agir(() => post(`/clientes/${d.id}/contrato/aprovar`, { pagamento: 'pix' }), '✓ Contrato pronto.') }} />
      )}
      {painel === 'contrato' && !emContrato && atual && (
        <PainelSobre titulo="O contrato" aoFechar={() => setPainel(null)}><RevisarContrato d={d} e={atual} ocupado={ocupado} agir={agir} /></PainelSobre>
      )}
      {painel === 'visita' && (
        <PainelSobre titulo="Marcar a visita" aoFechar={() => setPainel(null)}><MarcarVisita d={d} ocupado={ocupado} agir={agir} /></PainelSobre>
      )}
      {painel === 'portao' && portao && (
        <PainelSobre titulo="Antes de seguir, confirme" aoFechar={() => setPainel(null)}>
          <CartaoPortao cid={d.id} p={portao} aoMudar={aoPortao} usarExistente={usarExistente} />
        </PainelSobre>
      )}
      {painel === 'dados' && (
        <PainelSobre titulo="Dados do cliente" aoFechar={() => setPainel(null)}>
          <DadosCliente cid={d.id} versao={versao} ocupado={ocupado}
                        corrigir={(campo, valor) => agir(() => post(`/clientes/${d.id}/dado`, { campo, valor }), '✓ Dado corrigido. O rascunho da proposta já usa o dado novo.')} />
        </PainelSobre>
      )}
      {painel === 'etapas' && (
        <PainelSobre titulo="Etapas" aoFechar={() => setPainel(null)}>
          <ol className="painel-etapas">{d.etapas.map((e) => <PainelEtapa key={e.etapa} e={e} d={d} agir={agir} />)}</ol>
        </PainelSobre>
      )}
    </section>
  )
}

/** ORDEM 053 (L5): "Revise o contrato". O que falta do cliente vem primeiro ("Falta o CPF do cliente");
 * à direita, os dados do cliente com ✓ ou "falta". Pedir os dados gera a mensagem pronta (041). */
function RevisarContrato({ d, e, ocupado, agir }: { d: Estado; e: Etapa; ocupado: boolean; agir: (f: () => Promise<unknown>) => Promise<void> }) {
  const falta = e.status === 'falta' ? e.falta : []
  const dados: [string, boolean][] = [
    ['Nome', !falta.some((f) => /nome/i.test(f))], ['CPF ou CNPJ', !falta.some((f) => /cpf|cnpj/i.test(f))],
    ['Endereço', !falta.some((f) => /endere/i.test(f))], ['E-mail', !falta.some((f) => /e-?mail/i.test(f))],
    ['Telefone', !falta.some((f) => /telefone|celular|whats/i.test(f))],
  ]
  return (
    <div className="grid gap-4">
      <div><h2 className="titulo-cartao">Revise o contrato</h2><p className="sub-jdb">{[d.nome, d.contexto.imovel_tipo, d.contexto.bairro].filter(Boolean).join(' · ')}</p></div>
      {falta.length > 0 && (
        <div className="proximo-passo">
          <h3 className="titulo-cartao">{falta.length === 1 ? `Falta ${falta[0]} para o contrato.` : `Faltam ${falta.length} dados para o contrato: ${falta.join(', ')}.`}</h3>
          <div className="botoes">
            <button type="button" className="btn-verde" disabled={ocupado}
                    onClick={() => void agir(() => post(`/clientes/${d.id}/contrato/aprovar`, { pagamento: 'pix' }))}>Gerar mensagem para pedir</button>
          </div>
          <p className="small-jdb">Ou escreva os dados na conversa, abaixo: o JdB anota.</p>
        </div>
      )}
      {/* ORDEM 065: sem a "folha" de enfeite; com os dados completos, o rascunho real aparece no próximo passo */}
      <div>
        <dl className="l4-dados">
          <div><dt>Dados do cliente</dt></div>
          {dados.map(([k, ok]) => <div key={k} className="flex justify-between"><dd style={{ fontWeight: 400 }}>{k}</dd><dd className={ok ? 'ok-l5' : 'falta-l5'}>{ok ? '✓' : 'falta'}</dd></div>)}
        </dl>
      </div>
      {falta.length === 0 && (
        <div className="proximo-passo">
          <div className="botoes"><button type="button" className="btn-verde fixm-l4" disabled={ocupado}
                  onClick={() => void agir(() => post(`/clientes/${d.id}/contrato/aprovar`, { pagamento: 'pix' }))}>Aprovar e gerar mensagem</button></div>
        </div>
      )}
    </div>
  )
}

/** ORDEM 053 (L6): "Marcar visita" — dia, hora, endereço e "me avisar" (2 horas antes, 1 dia antes, outro). */
function MarcarVisita({ d, ocupado, agir }: { d: Estado; ocupado: boolean; agir: (f: () => Promise<unknown>) => Promise<void> }) {
  const [dia, setDia] = useState('')
  const [hora, setHora] = useState('09:00')
  const [aviso, setAviso] = useState(120)
  const [outro, setOutro] = useState('')
  const end = [d.contexto.imovel_endereco, d.contexto.bairro, d.contexto.cidade].filter(Boolean).join(' · ')
  const min = aviso >= 0 ? aviso : Math.max(0, Math.min(7 * 24 * 60, Number(outro || 0) * 60))
  return (
    <div className="grid gap-4">
      <div><h2 className="titulo-cartao">Marcar visita</h2><p className="sub-jdb">{[d.contexto.imovel_tipo, d.contexto.bairro].filter(Boolean).join(' – ')}</p></div>
      <div className="grade-l6">
        <label className="grid gap-1"><span className="rotulo-s4">Dia</span><input type="date" className="campo-grande campo-l6" value={dia} onChange={(e) => setDia(e.target.value)} /></label>
        <label className="grid gap-1"><span className="rotulo-s4">Hora</span><input type="time" className="campo-grande campo-l6" value={hora} onChange={(e) => setHora(e.target.value)} /></label>
      </div>
      {end && <div className="cartao-pad"><p className="small-jdb">Endereço</p><p className="texto" style={{ fontWeight: 700 }}>{end}</p></div>}
      <div className="grid gap-2">
        <span className="rotulo-s4">Me avisar</span>
        <div className="chips-l6">
          {[[120, '2 horas antes'], [1440, '1 dia antes'], [-1, 'Outro']].map(([v, r]) => (
            <button key={v} type="button" aria-pressed={aviso === v} onClick={() => setAviso(Number(v))}>{r}</button>
          ))}
        </div>
        {aviso < 0 && <label className="grid gap-1"><span className="small-jdb">Quantas horas antes?</span>
          <input className="campo-grande" inputMode="numeric" value={outro} onChange={(e) => setOutro(e.target.value.replace(/\D/g, ''))} /></label>}
      </div>
      <button type="button" className="btn-verde w-full fixm-l4" disabled={ocupado || !dia}
              onClick={() => void agir(() => post(`/clientes/${d.id}/visita`, { quando: `${dia}T${hora}`, aviso_min: min }))}>Marcar visita</button>
    </div>
  )
}


interface Ponto { id: string; pergunta: string; opcoes: string[]; recomendada: string }
interface Cand { n: number; portal: string; bairro: string; area_m2: number | null; preco: number | null; recomendado: boolean; nao_recomendado: boolean; motivo: string; decisao: string; link: string }

export function Alinhamento() {
  const jid = useStore((s) => s.jobId)
  const ir = useStore((s) => s.ir)
  const [d, setD] = useState<{ pontos: Ponto[]; candidatos: Cand[]; decidido?: string } | null>(null)
  const [parte, setParte] = useState('')
  const [erro, setErro] = useState('')
  const carregar = useCallback(() => { if (jid) get<typeof d>(`/jobs/${jid}/alinhamento`).then(setD).catch(() => setErro('Não consegui abrir.')) }, [jid])
  useEffect(carregar, [carregar])
  async function responder(id: string, resposta: string) {
    setErro('')
    try { setD(await post(`/jobs/${jid}/alinhamento`, { id, resposta, texto: parte })) } catch (e) { setErro(erroDe(e)) }
  }
  if (!d) return <p className="texto-grande" role="status">{erro || 'Abrindo…'}</p>
  const ponto = d.pontos[0]
  const brl = (v: number | null) => (v == null ? 'n/i' : v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', maximumFractionDigits: 0 }))
  return (
    <section className="tela-simples">
      <button type="button" className="voltar" onClick={() => ir('job', jid!)}>← Trabalho</button>
      <h1 className="titulo-tela">Referenciais e alinhamento</h1>
      <p className="linha-tela">Resolva tudo de uma vez ou deixe comigo.</p>
      {d.decidido && <p className="aviso-simples" role="status">Decidido: {d.decidido}</p>}
      {erro && <p className="aviso-impede" role="alert">{erro}</p>}
      {ponto ? (
        <div className="proximo-passo">
          <p className="bloco-rotulo">Próximo passo · {d.pontos.length === 1 ? '1 de 1' : `1 de ${d.pontos.length}`}</p>
          <p className="texto-grande">{ponto.pergunta}</p>
          {ponto.id === 'objeto' && <input className="campo-grande" placeholder="Qual parte? Ex.: Galpão 01" value={parte} onChange={(e) => setParte(e.target.value)} />}
          <div className="botoes">
            {ponto.opcoes.map((o) => (
              <button key={o} type="button" className={o === ponto.recomendada ? 'btn-verde' : 'btn-sec-grande'} onClick={() => void responder(ponto.id, o)}>
                {o}{o === ponto.recomendada ? ' (recomendado)' : ''}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="proximo-passo">
          <p className="bloco-rotulo">Próximo passo</p>
          <p className="texto-grande">Escolha os referenciais e confirme o valor.</p>
          <button type="button" className="btn-verde" onClick={() => ir('job', jid!)}>Confirmar valor</button>
        </div>
      )}
      <button type="button" className="btn-sec-grande" onClick={() => void responder('decide', '')}>Decide você</button>
      <h2 className="subtitulo">Candidatos ({d.candidatos.length})</h2>
      <ul className="lista-simples">
        {d.candidatos.slice(0, 20).map((c) => (
          <li key={c.n} className={c.nao_recomendado ? 'riscado' : ''}>
            <span>{c.recomendado ? '★ ' : ''}nº {c.n} · {c.bairro || c.portal}</span>
            <span>{c.area_m2 ? `${c.area_m2.toLocaleString('pt-BR')} m²` : 'área n/i'} · {brl(c.preco)}</span>
            <strong>{c.decisao === 'entra' ? 'Entra' : c.decisao === 'descarta' ? 'Fora' : ''}</strong>
          </li>
        ))}
      </ul>
    </section>
  )
}
