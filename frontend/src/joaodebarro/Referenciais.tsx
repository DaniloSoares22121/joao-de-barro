/* Referenciais pelo avaliador: cadastro manual de anúncio (modal), remoção do cadastrado à mão
 * e o quadro "Confirmar valor" (pipeline parado em AGUARDANDO_AVALIADOR antes da redação). */
import { FalarAqui } from './Falar'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Plus, X } from 'lucide-react'
import { ApiError, del, get, post, postForm, put } from './api'
import {
  alertasValor, br2, correcoesDaConfirmacao, decimalBR, ehContraditorio, estatisticaAmostra, faltaFotoOuDados, previaValor, unitarioDigitado, unitarioNaBase,
} from './controle'
import { ehAuth, mensagemErro } from './Envio'
import type { CorrecaoAprender } from './Aprender'
import Confirmar from './Confirmar'
import { moeda, numero2, textoTela } from './rotulos'
import { nomeCampo } from './nomesCampos'

const ORIGEM_AREA: Record<string, string> = { documento: 'do documento', vistoria: 'da vistoria', pesquisa: 'da pesquisa',
  inferido: 'deduzida', pendente: 'a confirmar' }
import type {
  AreasCalculo, BaseArea, Detalhe, Referencial, ReferencialSalvo, RespostaEscolha, ResultadoSelecao,
} from './tipos'

function erroTxt(e: unknown): string {
  if (e instanceof ApiError && e.status === 409 && /execu/i.test(e.detail)) return 'O trabalho está em execução; aguarde terminar.'
  const m = mensagemErro(e)
  return m.charAt(0).toUpperCase() + m.slice(1)
}

export const ehManual = (r: Referencial) => r.fonte_coleta === 'manual'

// ---------------------------------------------------------------- cadastro manual
type CampoForm = 'link' | 'portal' | 'localizacao' | 'bairro' | 'tipologia' | 'quartos' | 'suites' | 'lote_m2'
  | 'area_m2' | 'idade_estado' | 'padrao' | 'preco' | 'descricao'

const VAZIO: Record<CampoForm, string> = {
  link: '', portal: '', localizacao: '', bairro: '', tipologia: '', quartos: '', suites: '', lote_m2: '',
  area_m2: '', idade_estado: '', padrao: '', preco: '', descricao: '',
}

const CAMPOS: ReadonlyArray<{ k: CampoForm; rotulo: string; ph?: string; ajuda?: string; num?: boolean; largo?: boolean }> = [
  { k: 'link', rotulo: 'Link do anúncio', ph: 'https://…', largo: true },
  { k: 'portal', rotulo: 'Portal', ph: 'ex.: ZAP Imóveis', ajuda: 'Se ficar vazio, o sistema deduz pelo link.' },
  { k: 'localizacao', rotulo: 'Localização', ph: 'Rua das Flores, 01 – Setor Exemplo' },
  { k: 'bairro', rotulo: 'Bairro' },
  { k: 'tipologia', rotulo: 'Tipologia', ph: 'ex.: Casa térrea' },
  { k: 'quartos', rotulo: 'Quartos', num: true },
  { k: 'suites', rotulo: 'Suítes', num: true },
  { k: 'lote_m2', rotulo: 'Terreno (m²)', num: true, ajuda: 'Deixe vazio se não informado.' },
  { k: 'area_m2', rotulo: 'Área construída (m²)', ph: '198,00', num: true },
  { k: 'idade_estado', rotulo: 'Idade/estado', ph: 'ex.: Antiga' },
  { k: 'padrao', rotulo: 'Padrão', ph: 'ex.: Médio' },
  { k: 'preco', rotulo: 'Preço (R$)', ph: '650.000,00', num: true },
]

const OBRIGATORIOS: ReadonlyArray<CampoForm> = ['link', 'preco', 'area_m2']

export function FormReferencialManual({ jobId, aoFechar, aoSalvar, inicial, aviso, titulo, destino, campo = false }: {
  jobId: string; aoFechar: () => void; aoSalvar: (msg: string) => void
  inicial?: Partial<Record<CampoForm, string>>; aviso?: string; titulo?: string
  destino?: 'entra' | 'comparacao'        // 084-3: "Só comparação" nunca passa pela amostra nem mexe na média
  campo?: boolean                         // 153-4: pesquisa de campo — sem link; data da pesquisa obrigatória
}) {
  const [extra, setExtra] = useState({ cidade: '', data_pesquisa: '', informante: '', negocio: 'oferta' })
  const altX = (k: keyof typeof extra, v: string) => setExtra((x) => ({ ...x, [k]: v }))
  const [f, setF] = useState<Record<CampoForm, string>>({ ...VAZIO, ...(inicial ?? {}) })
  const [foto, setFoto] = useState<File | null>(null)
  const [erro, setErro] = useState('')
  const [campoErro, setCampoErro] = useState<CampoForm | null>(null)   // 073-4: o erro fica junto do campo
  const [salvando, setSalvando] = useState(false)
  const primeiro = useRef<HTMLInputElement>(null)
  const alt = (k: CampoForm, v: string) => setF((x) => ({ ...x, [k]: v }))
  const u = unitarioDigitado(f.preco, f.area_m2)

  const fechar = useRef(aoFechar)
  fechar.current = () => { if (!salvando) aoFechar() }
  useEffect(() => {
    primeiro.current?.focus()
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') fechar.current() }
    document.addEventListener('keydown', esc)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.removeEventListener('keydown', esc); document.body.style.overflow = overflow }
  }, [])

  async function salvar(e: FormEvent) {
    e.preventDefault()
    setErro(''); setCampoErro(null)
    const falha = (k: CampoForm, msg: string) => {
      setCampoErro(k); setErro(msg)
      const el = document.getElementById(`rm-${k}`)
      el?.scrollIntoView({ block: 'center', behavior: 'smooth' }); el?.focus()
    }
    if (!campo && !/^https?:\/\/\S+$/i.test(f.link.trim())) { falha('link', 'Informe o link do anúncio (começando com http:// ou https://).'); return }
    if (decimalBR(f.area_m2) === null || (decimalBR(f.area_m2) ?? 0) <= 0) { falha('area_m2', 'Informe a área construída (m²).'); return }
    if (decimalBR(f.preco) === null || (decimalBR(f.preco) ?? 0) <= 0) { falha('preco', 'Informe o preço (R$).'); return }
    if (campo && !/^\s*\d{1,2}\/\d{1,2}\/\d{4}\s*$/.test(extra.data_pesquisa)) {
      setErro('Informe a data da pesquisa de campo (dd/mm/aaaa).'); document.getElementById('rm-data_pesquisa')?.focus(); return
    }
    if (campo && !foto && !window.confirm('Sem foto: este referencial sai sem foto na tabela do laudo. Salvar assim mesmo?')) return
    const fd = new FormData()
    for (const [k, v] of Object.entries(f)) if (v.trim()) fd.append(k, v.trim())
    if (destino) fd.append('decisao', destino)
    if (campo) {                           // 153-4: pesquisa de campo
      fd.append('pesquisa_campo', '1')
      for (const [k, v] of Object.entries(extra)) if (v.trim()) fd.append(k, v.trim())
    }
    if (foto) fd.append('foto', foto, foto.name)
    setSalvando(true)
    try {
      const r = await postForm<ReferencialSalvo>(`/jobs/${encodeURIComponent(jobId)}/referenciais/manual`, fd)
      if (destino === 'comparacao') {      // garante a decisão mesmo se o servidor criou como "entra"
        await put(`/jobs/${encodeURIComponent(jobId)}/candidatos/${r.n}`, { decisao: 'comparacao' })
        aoSalvar(`Anúncio nº ${r.n} guardado só como comparação: fora da amostra e do cálculo.`)
      } else {
        aoSalvar(`Referencial nº ${r.n} cadastrado${campo ? ' (pesquisa de campo)' : ''} (${moeda(r.unitario)}/m²). Ele entra marcado na amostra.`)
      }
    } catch (err) {
      if (!ehAuth(err)) setErro(erroTxt(err))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 sm:items-center sm:p-4"
         onMouseDown={(e) => { if (e.target === e.currentTarget && !salvando) aoFechar() }}>
      <form role="dialog" aria-modal="true" aria-labelledby="ref-manual-titulo" onSubmit={(e) => void salvar(e)}
            className="entra flex max-h-[92vh] w-full max-w-2xl flex-col rounded-t-2xl bg-white shadow-xl sm:rounded-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-stone-100 px-4 py-3 sm:px-5">
          <div>
            <h2 id="ref-manual-titulo" className="titulo-sec">{titulo ?? (campo ? 'Referencial de pesquisa de campo' : 'Adicionar referencial')}</h2>
            {campo ? <p className="text-[16px] text-stone-500">Imóvel que você pesquisou em campo, sem anúncio na internet. Obrigatórios: área construída, preço e data da pesquisa.</p>
            : <p className="text-[16px] text-stone-500">{destino === 'comparacao'
              ? 'Só comparação: aparece no item de comparação do laudo, fora da amostra e do cálculo.'
              : 'Anúncio que você encontrou. Ele entra marcado na amostra.'} Só link, área construída e preço são obrigatórios.</p>}
            {aviso && <p className="aviso-simples mt-2 text-[16px]" role="status">{aviso}</p>}
          </div>
          <button type="button" className="btn-link !px-1" onClick={aoFechar} disabled={salvando} aria-label="Fechar">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="space-y-3 overflow-y-auto px-4 py-4 sm:px-5">
          <div className="grid gap-3 sm:grid-cols-2">
            {CAMPOS.filter((c) => OBRIGATORIOS.includes(c.k) && !(campo && c.k === 'link')).map((c, i) => (
              <div key={c.k} className={c.largo ? 'sm:col-span-2' : undefined}>
                <label className="rotulo" htmlFor={`rm-${c.k}`}>
                  {c.rotulo} *
                </label>
                <input id={`rm-${c.k}`} ref={i === 0 ? primeiro : undefined} className="input" value={f[c.k]}
                       type={c.k === 'link' ? 'url' : 'text'} inputMode={c.num ? 'decimal' : undefined}
                       placeholder={c.ph} onChange={(e) => alt(c.k, e.target.value)} disabled={salvando} />
                {campoErro === c.k ? <p className="faixa-erro mt-1" role="alert">{erro}</p> : c.ajuda && <p className="ajuda">{c.ajuda}</p>}
              </div>
            ))}
            {campo && (                        // 153-4: os dados da pesquisa de campo
              <>
                <div>
                  <label className="rotulo" htmlFor="rm-data_pesquisa">Data da pesquisa *</label>
                  <input id="rm-data_pesquisa" className="input" value={extra.data_pesquisa} placeholder="dd/mm/aaaa" inputMode="numeric"
                         onChange={(e) => altX('data_pesquisa', e.target.value)} disabled={salvando} />
                </div>
                <div>
                  <span className="rotulo">O preço é</span>
                  <div className="flex gap-2" role="radiogroup" aria-label="O preço é">
                    {(['oferta', 'venda'] as const).map((v) => (
                      <button key={v} type="button" role="radio" aria-checked={extra.negocio === v} disabled={salvando}
                              className={extra.negocio === v ? 'btn' : 'btn-sec'} onClick={() => altX('negocio', v)}>
                        {v === 'oferta' ? 'Oferta' : 'Venda realizada'}</button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="rotulo" htmlFor="rm-cidade">Cidade</label>
                  <input id="rm-cidade" className="input" value={extra.cidade} onChange={(e) => altX('cidade', e.target.value)} disabled={salvando} />
                </div>
                <div>
                  <label className="rotulo" htmlFor="rm-informante">Fonte / informante</label>
                  <input id="rm-informante" className="input" value={extra.informante} placeholder="ex.: corretor, imobiliária, morador"
                         onChange={(e) => altX('informante', e.target.value)} disabled={salvando} />
                  <p className="ajuda">Opcional.</p>
                </div>
              </>
            )}
            <details className="sm:col-span-2" open={campo || CAMPOS.some((c) => !OBRIGATORIOS.includes(c.k) && !!(inicial ?? {})[c.k])}>
              <summary className="cursor-pointer text-[16px] font-semibold text-stone-700">{campo ? 'Dados do imóvel' : 'Mais dados (opcional: o JdB completa depois)'}</summary>
              <div className="mt-2 grid gap-3 sm:grid-cols-2">
                {CAMPOS.filter((c) => !OBRIGATORIOS.includes(c.k) && !(campo && c.k === 'portal')).map((c) => (
                  <div key={c.k}>
                    <label className="rotulo" htmlFor={`rm-${c.k}`}>{c.rotulo}</label>
                    <input id={`rm-${c.k}`} className="input" value={f[c.k]} type="text" inputMode={c.num ? 'decimal' : undefined}
                           placeholder={c.ph} onChange={(e) => alt(c.k, e.target.value)} disabled={salvando} />
                    {campoErro === c.k ? <p className="faixa-erro mt-1" role="alert">{erro}</p> : c.ajuda && <p className="ajuda">{c.ajuda}</p>}
                  </div>
                ))}
              </div>
            </details>
            <div className="flex flex-col justify-end">
              <span className="rotulo">R$/m² calculado</span>
              <p className="rounded-lg bg-barro-claro px-3 py-2.5 text-sm font-semibold tabular-nums text-stone-900"
                 aria-live="polite" data-testid="ref-manual-unitario">
                {u !== null ? `${moeda(u)}/m²` : '— (informe preço e área)'}
              </p>
            </div>
          </div>
          <div>
            <label className="rotulo" htmlFor="rm-descricao">{campo ? 'Observação' : 'Descrição'}</label>
            <textarea id="rm-descricao" className="input min-h-[72px]" value={f.descricao}
                      onChange={(e) => alt('descricao', e.target.value)} disabled={salvando} />
            <FalarAqui alvo="rm-descricao" valor={f.descricao} aoMudar={(v) => alt('descricao', v)} />
          </div>
          <div>
            <label className="rotulo" htmlFor="rm-foto">{campo ? 'Foto do imóvel (tirada em campo)' : 'Foto/print do anúncio'}</label>
            <input id="rm-foto" type="file" accept="image/jpeg,image/png,image/webp,image/*" disabled={salvando}
                   className="block w-full text-sm text-stone-700 file:mr-3 file:rounded-lg file:border file:border-stone-300 file:bg-white file:px-3 file:py-2 file:text-sm file:font-semibold file:text-stone-700"
                   onChange={(e) => setFoto(e.target.files?.[0] ?? null)} />
            <p className="ajuda">{campo ? 'JPG ou PNG. Sem foto, o referencial sai sem foto na tabela do laudo.' : 'Opcional. JPG ou PNG.'}</p>
          </div>
          {erro && !campoErro && <div className="faixa-erro" role="alert">{erro}</div>}
        </div>
        <div className="flex flex-col-reverse gap-2 border-t border-stone-100 px-4 py-3 sm:flex-row sm:justify-end sm:px-5">
          <button type="button" className="btn-sec" onClick={aoFechar} disabled={salvando}>Cancelar</button>
          <button type="submit" className="btn" disabled={salvando}>{salvando ? 'Salvando…' : 'Salvar referencial'}</button>
        </div>
      </form>
    </div>
  )
}

/** Botão "Adicionar referencial" + modal. 073-3: primeiro "Cole aqui um ou vários links" — o avaliador abre cada um
 *  no Chrome dele e a extensão envia (112: o "Tentar ler pelo Coletor" saiu com a busca automática); ou preenche à mão. */
interface LidoLink { link: string; erro?: string; campos?: Partial<Record<CampoForm, string>>; faltam?: string[] }

export function AdicionarReferencial({ jobId, aoMudar, rotulo = 'Adicionar referencial', perguntarDestino = false, comparacao = false }: {
  jobId: string; aoMudar: (msg: string) => void; rotulo?: string   // 076-2: "+ Colar o link de um anúncio" nos Detalhes
  perguntarDestino?: boolean    // 084-3: valor já confirmado -> pergunta [Entra na amostra] [Só comparação] antes
  comparacao?: boolean          // 084-3: aberto pelo card da comparação (D-069): já marcado "Só comparação"
}) {
  const [aberto, setAberto] = useState(false)
  const [deCampo, setDeCampo] = useState(false)        // 153-4: cadastro de pesquisa de campo (sem link)
  const [destino, setDestino] = useState<'entra' | 'comparacao' | null>(comparacao ? 'comparacao' : perguntarDestino ? null : 'entra')
  const [abertos, setAbertos] = useState<string[] | null>(null)
  const [texto, setTexto] = useState('')
  const [erro, setErro] = useState('')
  const [fila, setFila] = useState<LidoLink[] | null>(null)
  const [i, setI] = useState(0)
  const [salvos, setSalvos] = useState(0)
  const fechar = () => { setAberto(false); setFila(null); setI(0); setTexto(''); setErro(''); setSalvos(0); setAbertos(null)
    setDestino(comparacao ? 'comparacao' : perguntarDestino ? null : 'entra') }
  const fecharRef = useRef(fechar); fecharRef.current = fechar
  useEffect(() => {                       // 185: a caixa "Adicionar referencial" fecha com Esc (antes ficava por cima de tudo)
    if (!aberto) return undefined
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') fecharRef.current() }
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  }, [aberto])
  const links = () => texto.split(/\s+/).map((x) => x.trim()).filter((x) => /^https?:\/\//i.test(x)).slice(0, 10)
  function abrirNoChrome() {             // 084-1: a extensão lê a página aberta no Chrome do avaliador
    const l = links()
    if (!l.length) { setErro('Cole pelo menos um link (começando com http:// ou https://).'); return }
    setErro(''); setAbertos(l)
    // 091-5: o JdB guarda os links: ao abrir cada um, a extensão já sabe o trabalho e envia sem perguntar
    void post(`/jobs/${encodeURIComponent(jobId)}/extensao/colados`, { links: l, decisao: destino === 'comparacao' ? 'comparacao' : 'entra' }).catch(() => { /* segue sem a fila */ })
  }
  const [abrindo, setAbrindo] = useState('')
  function abrirTodos() {                // 091-5: "Abrir os N" — a extensão abre um a um e envia sozinha
    setAbrindo('Pedindo à extensão…')
    let respondeu = false
    const ouvir = (ev: MessageEvent) => {
      const m = ev.data as { jdb?: string; ok?: boolean; erro?: string; total?: number } | null
      if (ev.source !== window || !m || m.jdb !== 'abrir-anuncios-resposta') return
      respondeu = true
      window.removeEventListener('message', ouvir)
      if (m.ok && !m.total) setAbrindo('Nada para abrir: estes anúncios já chegaram com foto e data de acesso. Para mandar de novo, use “Abrir no Chrome” e o botão Enviar ao JdB.')
      else if (m.ok) setAbrindo(m.total === 1
        ? 'A extensão está abrindo o anúncio e enviando sozinha. Pode acompanhar em Detalhes › Anúncios.'
        : `A extensão está abrindo ${m.total} anúncios, um de cada vez, e enviando sozinha. Pode acompanhar em Detalhes › Anúncios.`)
      else if (m.erro === 'PORTAIS') setAbrindo('Falta permitir o JdB nos portais: toque no ícone do JdB, no alto do Chrome, e em “Permitir”.')
      else setAbrindo('A extensão não conseguiu abrir agora. Use os botões “Abrir no Chrome” abaixo.')
    }
    window.addEventListener('message', ouvir)
    setTimeout(() => {
      window.postMessage({ jdb: 'abrir-anuncios', trabalho: jobId }, window.location.origin)
      setTimeout(() => {
        if (!respondeu) {
          window.removeEventListener('message', ouvir)
          setAbrindo('A extensão não respondeu (não está ligada neste Chrome?). Use os botões “Abrir no Chrome” abaixo.')
        }
      }, 2500)
    }, 600)                              // dá tempo de o JdB guardar os links
  }
  const atual = fila?.[i]
  const proximo = (msg?: string) => {
    const total = salvos + (msg ? 1 : 0)
    if (msg) setSalvos(total)
    if (fila && i + 1 < fila.length) { setI(i + 1); return }
    if (total) aoMudar(`${total} ${total === 1 ? 'anúncio adicionado' : 'anúncios adicionados'}.`)
    fechar()
  }
  return (
    <>
      <button type="button" className="btn-sec btn-peq" onClick={() => setAberto(true)}>
        {rotulo.startsWith('+') ? rotulo : <><Plus size={16} aria-hidden="true" /> {rotulo}</>}
      </button>
      {!comparacao && (
        <span className="inline-flex flex-wrap items-center gap-2">
          <button type="button" className="btn-sec btn-peq" onClick={() => setDeCampo(true)}>
            <Plus size={16} aria-hidden="true" /> Adicionar referencial manualmente</button>
          <span className="small-jdb">para referencial de pesquisa de campo, sem anúncio na internet</span>
        </span>
      )}
      {deCampo && (
        <FormReferencialManual jobId={jobId} campo destino={destino ?? 'entra'}
          aoFechar={() => setDeCampo(false)} aoSalvar={(m) => { setDeCampo(false); aoMudar(m) }} />
      )}
      {aberto && !fila && !destino && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 sm:items-center sm:p-4"
             onMouseDown={(e) => { if (e.target === e.currentTarget) fechar() }}>
          <div role="dialog" aria-modal="true" aria-labelledby="destino-titulo" className="entra grid w-full max-w-lg gap-3 rounded-t-2xl bg-white p-5 shadow-xl sm:rounded-2xl">
            <h2 id="destino-titulo" className="titulo-sec">O valor deste laudo já está confirmado</h2>
            <p className="text-[16px]">O anúncio novo entra na amostra (e o valor é refeito pela conta) ou fica só como comparação, fora do cálculo?</p>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" className="btn-sec min-h-[48px]" onClick={fechar}>Cancelar</button>
              <button type="button" className="btn-sec min-h-[48px]" onClick={() => setDestino('entra')}>Entra na amostra</button>
              <button type="button" className="btn min-h-[48px]" onClick={() => setDestino('comparacao')}>Só comparação</button>
            </div>
          </div>
        </div>
      )}
      {aberto && !fila && destino && abertos && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 sm:items-center sm:p-4"
             onMouseDown={(e) => { if (e.target === e.currentTarget) fechar() }}>
          <div role="dialog" aria-modal="true" aria-labelledby="abrir-titulo" className="entra grid w-full max-w-2xl gap-3 rounded-t-2xl bg-white p-5 shadow-xl sm:rounded-2xl">
            <h2 id="abrir-titulo" className="titulo-sec">Abra cada anúncio no seu Chrome</h2>
            <p className="text-[16px]">Em cada página, toque em <b>Enviar ao JdB</b> (no canto): a extensão traz foto, preço, rua, bairro, quartos e a data do acesso.
              Se a área não vier confirmada, o JdB pede só a área.{destino === 'comparacao' ? ' Depois, marque cada um como “Só comparação” na lista de anúncios.' : ''}</p>
            <button type="button" className="btn min-h-[48px] justify-self-start" onClick={abrirTodos}>
              {abertos.length === 1 ? 'Abrir e enviar sozinho' : `Abrir os ${abertos.length} e enviar sozinho`}
            </button>
            {abrindo && <p className="text-[16px]" role="status">{abrindo}</p>}
            <ul className="grid gap-2">
              {abertos.map((l, k) => (
                <li key={l} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-stone-200 p-2">
                  <span className="min-w-0 break-all text-[14px]">{k + 1}. {l}</span>
                  <a className="btn-sec btn-peq" href={l} target="_blank" rel="noopener noreferrer">Abrir no Chrome</a>
                </li>
              ))}
            </ul>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" className="btn-sec min-h-[48px]" onClick={() => { setAbertos(null); setFila(abertos.map((l) => ({ link: l }))) }}>Preencher à mão</button>
              <button type="button" className="btn min-h-[48px]" onClick={() => { aoMudar('Anúncios abertos no Chrome: toque em Enviar ao JdB em cada um.'); fechar() }}>Pronto</button>
            </div>
          </div>
        </div>
      )}
      {aberto && !fila && destino && !abertos && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 sm:items-center sm:p-4"
             onMouseDown={(e) => { if (e.target === e.currentTarget) fechar() }}>
          <form role="dialog" aria-modal="true" aria-labelledby="links-titulo" onSubmit={(e) => { e.preventDefault(); abrirNoChrome() }}
                className="entra grid w-full max-w-2xl gap-3 rounded-t-2xl bg-white p-5 shadow-xl sm:rounded-2xl">
            <h2 id="links-titulo" className="titulo-sec">Adicionar referencial</h2>
            <label htmlFor="links-ref" className="text-[16px] font-semibold">Cole aqui um ou vários links (um por linha)</label>
            <textarea id="links-ref" className="input min-h-[140px] text-[16px]" value={texto} onChange={(e) => setTexto(e.target.value)}
                      placeholder={'https://www.zapimoveis.com.br/imovel/…\nhttps://www.vivareal.com.br/imovel/…'} autoFocus />
            <p className="text-[16px] text-stone-500">Depois, abra cada um no seu Chrome e toque em <b>Enviar ao JdB</b>: a extensão traz foto, preço, rua, bairro, quartos e a data do acesso.</p>
            {erro && <p className="faixa-erro" role="alert">{erro}</p>}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" className="btn-sec min-h-[48px]" onClick={fechar}>Cancelar</button>
              <button type="button" className="btn-sec min-h-[48px]" onClick={() => { const ls = links(); setFila(ls.length ? ls.map((l) => ({ link: l })) : [{ link: '' }]) }}>Preencher à mão</button>
              <button type="submit" className="btn min-h-[48px]">Abrir no meu Chrome</button>
            </div>
          </form>
        </div>
      )}
      {aberto && atual && (
        <FormReferencialManual key={`${i}-${atual.link}`} jobId={jobId}
          titulo={fila && fila.length > 1 ? `Anúncio ${i + 1} de ${fila.length}` : 'Adicionar referencial'}
          inicial={{ link: atual.link, ...(atual.campos ?? {}) }}
          aviso={atual.erro ?? (atual.faltam?.length ? `Não consegui ler: ${atual.faltam.join(' e ')}. Preencha antes de salvar.`
                 : atual.campos ? 'Preenchi pelo anúncio. Confira e salve.' : undefined)}
          destino={destino ?? 'entra'} aoFechar={() => proximo()} aoSalvar={(m) => proximo(m)} />
      )}
    </>
  )
}

/** Remove um referencial cadastrado à mão (com confirmação). */
export function RemoverReferencial({ jobId, n, aoMudar }: { jobId: string; n: number; aoMudar: (msg: string) => void }) {
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState('')
  const [perguntando, setPerguntando] = useState(false)
  async function remover() {
    setErro('')
    setOcupado(true)
    try {
      await del(`/jobs/${encodeURIComponent(jobId)}/referenciais/${n}`)
      setPerguntando(false)
      aoMudar(`Referencial nº ${n} removido.`)
    } catch (e) {
      if (!ehAuth(e)) setErro(erroTxt(e))
    } finally {
      setOcupado(false)
    }
  }
  return (
    <>
      <button type="button" className="btn-link btn-peq !px-1 text-red-700" disabled={ocupado}
              onClick={() => { setErro(''); setPerguntando(true) }} aria-label={`Remover referencial ${n}`}>
        {ocupado ? 'Removendo…' : 'Remover'}
      </button>
      {erro && !perguntando && <span className="basis-full text-xs text-red-700" role="alert">{erro}</span>}
      {perguntando && (
        <Confirmar titulo={`Remover o referencial nº ${n}?`} texto="Ele foi cadastrado por você e sairá da lista de referenciais."
                   rotuloConfirmar="Remover referencial" perigo ocupado={ocupado} erro={erro}
                   aoConfirmar={() => void remover()} aoCancelar={() => setPerguntando(false)} />
      )}
    </>
  )
}

// ---------------------------------------------------------------- confirmar valor
const txtNum = (v: string | number | null | undefined): string => {
  if (v === null || v === undefined || v === '') return ''
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? br2(n) : String(v)
}

export function ConfirmarValor({ detalhe, aoMudar, aoAprender }: {
  detalhe: Detalhe; aoMudar: (msg: string) => void
  aoAprender?: (c: CorrecaoAprender) => void
}) {
  const { job } = detalhe
  // 094-1: "Só comparação" (D-069) nunca entra na tabela do cálculo — nem marcado, nem desmarcado
  const refs = detalhe.candidatos.filter((r) => r.decisao !== 'comparacao')
  const soComparacao = detalhe.candidatos.filter((r) => r.decisao === 'comparacao').sort((a, b) => a.n - b.n)
  const sel = (detalhe.etapas.selecao ?? null) as ResultadoSelecao | null
  const proposta = sel?.proposta_ia ?? null
  // ORDEM 021: o avaliador escolhe SEMPRE a base do cálculo e qual área (nada pré-marcado na
  // base; na lista de áreas, a do imóvel avaliado vem marcada)
  const [areas, setAreas] = useState<AreasCalculo | null>(null)
  const [erroAreas, setErroAreas] = useState('')
  const [base, setBase] = useState<BaseArea | null>(null)
  const [campoArea, setCampoArea] = useState<string | null>(null)
  useEffect(() => {
    let vivo = true
    get<AreasCalculo>(`/jobs/${encodeURIComponent(job.id)}/areas`)
      .then((a) => {
        if (!vivo) return
        setAreas(a)
        if (a.escolha) { setBase(a.escolha.base); setCampoArea(a.escolha.campo) }
      })
      .catch((e) => { if (vivo && !ehAuth(e)) setErroAreas('Não foi possível carregar as áreas do imóvel.') })
    return () => { vivo = false }
  }, [job.id])
  const opcoesBase = base && areas ? areas[base] : []
  const escolherBase = (b: BaseArea) => {
    setBase(b)
    const lista = areas ? areas[b] : []
    const salva = areas?.escolha?.base === b ? lista.find((o) => o.campo === areas.escolha?.campo) : undefined
    setCampoArea((salva ?? lista.find((o) => o.sugerida) ?? lista[0])?.campo ?? null)
  }
  const area = opcoesBase.find((o) => o.campo === campoArea)?.valor ?? null
  const unitarioRef = (r: Referencial) => unitarioNaBase(r, base ?? 'construida')
  const nomeBase = base === 'terreno' ? 'área do terreno' : 'área construída'

  const [marcados, setMarcados] = useState<Set<number>>(
    () => new Set(refs.filter((r) => r.escolhido || ehManual(r)).map((r) => r.n)))
  // ORDEM 028-1: o que estava escolhido ao abrir (para perguntar se a troca vale para todos)
  const [inicial] = useState<number[]>(() => refs.filter((r) => r.escolhido || ehManual(r)).map((r) => r.n))
  const escolhidos = refs.filter((r) => marcados.has(r.n))
  const semFoto = escolhidos.filter(faltaFotoOuDados).sort((a, b) => a.n - b.n)
  const us = escolhidos.map(unitarioRef).filter((x): x is number => x !== null)
  const est = estatisticaAmostra(us)

  const unitIA = proposta ? proposta.unitario_adotado : sel?.unitario_adotado ?? null
  const justIA = textoTela(proposta?.justificativa_unitario || sel?.justificativa_unitario || '')   // 074-F1: sem códigos
  // ORDEM 010: a proposta da IA nunca se aplica sozinha — o avaliador decide (P0 item 5)
  const salvo = !!(sel?.confirmado || sel?.manual)   // ORDEM 034: 'Só salvar' grava sem confirmar
  // 084-7: o padrão é "= média" (já vem preenchido); número diferente só por decisão do avaliador, com o motivo dele
  const [unit, setUnit] = useState(() => (salvo ? txtNum(sel?.unitario_adotado ?? null) : (est?.media != null ? br2(est.media) : '')))
  const [faixa, setFaixa] = useState(() => (salvo ? txtNum(sel?.faixa_pct ?? null).replace(/,00$/, '') : '') || '10')
  // 083-D: o rótulo padrão ("escolha manual do avaliador") não é texto do avaliador: não volta no campo nem se repete
  const [just, setJust] = useState(() => (salvo ? semPadrao(sel?.justificativa_unitario || '') : ''))
  const [conf, setConf] = useState('')
  const [erro, setErro] = useState('')
  const [ocupado, setOcupado] = useState<'salvar' | 'continuar' | 'voltar' | null>(null)

  const u = decimalBR(unit)
  const f = decimalBR(faixa)
  const alertas = alertasValor(escolhidos, u, est, base ?? 'construida')
  const difereMedia = u !== null && est !== null && Math.abs(u - est.media) >= 0.005
  const fora = u !== null && est !== null && (u < est.min || u > est.max)
  const previa = area !== null && u !== null && u > 0 ? previaValor(area, u, f ?? 10) : null

  const alternar = (n: number) => setMarcados((m) => {
    const x = new Set(m)
    if (x.has(n)) x.delete(n)
    else x.add(n)
    return x
  })

  async function enviar(continuar: boolean) {
    setErro('')
    if (!marcados.size) { setErro('Marque ao menos 1 referencial.'); return }
    if (continuar && (!base || !campoArea)) { setErro('Escolha a base do cálculo e a área do imóvel.'); return }
    if (!est) { setErro('Nenhum dos marcados tem preço e área.'); return }
    if (unit.trim() && u === null) { setErro('Valor unitário inválido.'); return }
    if (fora) { setErro(`O unitário deve ficar entre ${moeda(est.min)} e ${moeda(est.max)} por m².`); return }
    if (faixa.trim() && (f === null || f <= 0 || f > 30)) { setErro('A faixa deve ficar entre 0 e 30%.'); return }
    if (difereMedia && !just.trim()) { setErro(`Justifique o unitário: ele é diferente da média (${moeda(est.media)}/m²).`); return }
    if (continuar && alertas.length && conf.trim().length < 10) {
      setErro('Há alertas na amostra ou no unitário: escreva “Confirmo mesmo assim, porque…” ou volte para a lista.')
      return
    }
    setOcupado(continuar ? 'continuar' : 'salvar')
    try {
      const r = await put<RespostaEscolha>(`/jobs/${encodeURIComponent(job.id)}/referenciais`, {
        escolhidos: [...marcados], unitario_adotado: unit.trim() || undefined,
        justificativa: just.trim() || undefined, faixa_pct: faixa.trim() || undefined, continuar,
        base_area: base ?? undefined, area_campo: base && campoArea ? campoArea : undefined,
        confirmacao_alertas: alertas.length ? conf.trim() || undefined : undefined })
      const doc = areas && base ? areas[base].find((o) => o.origem === 'documento') : undefined
      const escolhida = opcoesBase.find((o) => o.campo === campoArea)
      for (const c of correcoesDaConfirmacao({
        inicial, marcados: [...marcados], baseAntes: areas?.escolha?.base ?? null, baseDepois: base,
        areaDoc: continuar && doc ? doc : null, areaEscolhida: escolhida ?? null })) aoAprender?.(c)
      aoMudar(continuar
        ? `Valor confirmado (${moeda(r.valor_adotado)}). Gerando o laudo…`
        : r.valor_adotado === null
          ? `Escolha salva. ${r.mensagem ? r.mensagem.charAt(0).toUpperCase() + r.mensagem.slice(1) : ''}.`
          : `Escolha salva — prévia ${moeda(r.valor_adotado)}. Quando quiser, toque em “Confirmar e gerar o laudo”.`)
    } catch (e) {
      if (!ehAuth(e)) setErro(erroTxt(e))
    } finally {
      setOcupado(null)
    }
  }

  async function voltarLista() {
    setErro('')
    setOcupado('voltar')
    try {
      await post(`/jobs/${encodeURIComponent(job.id)}/voltar-lista`)
      aoMudar('De volta à lista de candidatos: o que você marcou continua marcado. Busque ou escolha outros e toque em “Continuar com os escolhidos”.')
    } catch (e) {
      if (!ehAuth(e)) setErro(erroTxt(e))
    } finally {
      setOcupado(null)
    }
  }

  return (
    <section className="cartao overflow-hidden ring-2 ring-amber-300" aria-labelledby="sec-confirmar" id="confirmar-valor">
      <div className="space-y-3 px-4 py-4 sm:px-5">
        <h2 id="sec-confirmar" className="titulo-sec">Confirmar valor</h2>
        <div className="faixa-aviso" role="status">
          Você decide o valor unitário. A proposta da IA aparece abaixo, com a justificativa, e só entra se você tocar em “Usar a proposta da IA”.
        </div>
        <p className="text-xs text-stone-500">
          Para incluir um anúncio que você achou, use “Adicionar referencial” no quadro “Candidatos a referencial”.
        </p>

        <fieldset className="space-y-2 rounded-xl border border-stone-200 p-3" aria-describedby="base-ajuda">
          <legend className="px-1 text-sm font-semibold text-stone-900">Base do cálculo *</legend>
          <p id="base-ajuda" className="text-xs text-stone-500">
            O valor unitário dos referenciais e a área do imóvel seguem a base escolhida.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            {(['construida', 'terreno'] as const).map((b) => (
              <label key={b} className={`flex flex-1 cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-sm ${
                base === b ? 'border-barro bg-barro-claro' : 'border-stone-200 hover:border-stone-300'}`}>
                <input type="radio" name="base-calculo" className="mt-0.5 h-4 w-4 accent-[var(--barro)]"
                       checked={base === b} disabled={!areas || !!ocupado} onChange={() => escolherBase(b)} />
                <span>
                  <span className="block font-medium text-stone-900">{b === 'construida' ? 'Só área construída' : 'Área total do terreno'}</span>
                  <span className="block text-xs text-stone-500">
                    {b === 'construida' ? 'R$/m² = preço ÷ área construída de cada referencial'
                      : 'R$/m² = preço ÷ área do terreno de cada referencial'}
                  </span>
                </span>
              </label>
            ))}
          </div>
          {erroAreas && <p className="erro-txt" role="alert">{erroAreas}</p>}
          {base && (
            <div className="space-y-1.5 pt-1" role="radiogroup" aria-label={`Qual ${nomeBase} do imóvel`}>
              <p className="text-sm font-medium text-stone-800">Qual {nomeBase} do imóvel? *</p>
              {opcoesBase.length === 0 && (
                <p className="text-sm text-amber-800">Nenhuma {nomeBase} nos dados extraídos — edite os campos do imóvel.</p>
              )}
              {opcoesBase.map((o) => (
                <label key={o.campo} className={`flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-sm ${
                  campoArea === o.campo ? 'border-barro bg-barro-claro' : 'border-stone-200 hover:border-stone-300'}`}>
                  <input type="radio" name="area-imovel" className="mt-0.5 h-4 w-4 accent-[var(--barro)]"
                         checked={campoArea === o.campo} disabled={!!ocupado} onChange={() => setCampoArea(o.campo)} />
                  <span className="min-w-0">
                    <span className="font-semibold tabular-nums text-stone-900">{numero2(o.valor)} m²</span>
                    <span className="text-stone-700"> · {nomeCampo(o.campo)}</span>{' '}
                    <span className="chip ml-1.5 bg-stone-100 text-stone-700 ring-stone-500/20">{ORIGEM_AREA[o.origem] ?? o.origem}</span>{' '}
                    {o.sugerida && <span className="chip ml-1 bg-emerald-50 text-emerald-800 ring-emerald-600/20">imóvel avaliado (sugerida)</span>}
                    {o.fonte && <span className="block break-words text-xs text-stone-500">Fonte: {o.fonte}</span>}
                  </span>
                </label>
              ))}
              {opcoesBase.length > 1 && (
                <p className="text-xs text-amber-800">Há {opcoesBase.length} valores diferentes: confira qual é o do imóvel avaliado.</p>
              )}
            </div>
          )}
        </fieldset>
      </div>

      <div className="overflow-x-auto border-y border-stone-100">
        <table className="tabela">
          <thead>
            <tr>
              <th scope="col">Usar</th>
              <th scope="col">Nº</th>
              <th scope="col">Portal</th>
              <th scope="col">Bairro</th>
              <th scope="col" className="text-right">Área (m²)</th>
              <th scope="col" className="text-right">Terreno (m²)</th>
              <th scope="col" className="text-right">Preço</th>
              <th scope="col" className="text-right">R$/m²{base === 'terreno' ? ' (terreno)' : ''}</th>
              <th scope="col">Justificativa da IA</th>
            </tr>
          </thead>
          <tbody>
            {[...refs].sort((a, b) => a.n - b.n).map((r) => {
              const ur = unitarioRef(r)
              return (
                <tr key={r.n} className={marcados.has(r.n) ? 'bg-barro-claro' : undefined}>
                  <td>
                    <input type="checkbox" className="h-5 w-5 accent-[var(--barro)]" checked={marcados.has(r.n)}
                           onChange={() => alternar(r.n)} disabled={ur === null || !!ocupado}
                           aria-label={`Usar referencial ${r.n}`} />
                  </td>
                  <td className="whitespace-nowrap font-semibold text-stone-900">
                    #{r.n}
                    {ehManual(r) && <span className="chip ml-1.5 bg-violet-50 font-medium text-violet-800 ring-violet-600/20">Cadastrado por você</span>}
                    {ehContraditorio(r) && (
                      <span className="chip ml-1.5 bg-red-50 font-medium text-red-800 ring-red-600/20" title={r.observacao}>
                        Anúncio contraditório
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap">{r.portal || '—'}</td>
                  <td>{r.bairro || '—'}</td>
                  <td className="whitespace-nowrap text-right tabular-nums">{numero2(r.area_m2)}</td>
                  <td className="whitespace-nowrap text-right tabular-nums">{r.lote_m2 ? numero2(r.lote_m2) : '—'}</td>
                  <td className="whitespace-nowrap text-right tabular-nums">{moeda(r.preco)}</td>
                  <td className="whitespace-nowrap text-right font-medium tabular-nums">{ur !== null ? moeda(ur) : '—'}</td>
                  <td className="min-w-[14rem] text-xs text-stone-600">{textoTela(semRepeticao(r.justificativa)) || '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {soComparacao.length > 0 && (
        <div className="mx-4 mt-4 space-y-1 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2.5 sm:mx-5" data-testid="so-comparacao">
          <p className="text-[16px] font-semibold">Só comparação (fora do cálculo)</p>
          <ul className="space-y-0.5 text-sm text-stone-700">
            {soComparacao.map((r) => (
              <li key={r.n}>✓ Nº {r.n} · {[r.rua, r.bairro].filter(Boolean).join(', ') || r.portal}
                {r.preco ? ` · ${moeda(r.preco)}` : ''}{r.area_m2 ? ` · ${numero2(r.area_m2)} m²` : ''}</li>
            ))}
          </ul>
          <p className="small-jdb">Aparecem no item de comparação do laudo. Não entram na média nem no valor.</p>
        </div>
      )}

      {semFoto.length > 0 && (
        // ORDEM 029-5: o Coletor não abre o anúncio (Cloudflare); o avaliador abre e envia pela extensão
        <div className="mx-4 mt-4 space-y-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2.5 sm:mx-5"
             role="note" data-testid="faltam-foto">
          <p className="text-sm text-amber-900">
            Abra o anúncio. Vai aparecer o botão <strong>Enviar ao JdB</strong> no canto da página. A foto e os dados
            vão direto para o referencial e para o laudo.
          </p>
          <ul className="space-y-1.5">
            {semFoto.map((r) => (
              <li key={r.n} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-semibold text-stone-900">#{r.n}</span>
                <span className="chip bg-amber-100 font-medium text-amber-900 ring-amber-600/30">Faltam foto/dados</span>
                <span className="text-stone-600">{r.portal || 'anúncio'}{r.bairro ? ` · ${r.bairro}` : ''}</span>
                {/^https?:\/\//i.test(r.link) && (
                  <a href={r.link} target="_blank" rel="noopener noreferrer" className="btn-sec btn-peq"
                     data-testid={`abrir-anuncio-${r.n}`}>Abrir anúncio</a>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="space-y-4 px-4 py-4 sm:px-5">
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5" aria-label="Estatística dos escolhidos">
          {[
            ['Escolhidos', est ? String(est.n) : String(marcados.size)],
            ['Mínimo R$/m²', est ? moeda(est.min) : '—'],
            ['Média R$/m²', est ? moeda(est.media) : '—'],
            ['Máximo R$/m²', est ? moeda(est.max) : '—'],
            ['CV (dispersão)', est && est.cv !== null ? `${(est.cv * 100).toFixed(1).replace('.', ',')}%` : '—'],
          ].map(([r, v]) => (
            <div key={r} className="rounded-lg bg-stone-50 px-3 py-2">
              <dt className="text-xs text-stone-500">{r}</dt>
              <dd className="mt-0.5 text-sm font-semibold tabular-nums text-stone-900">{v}</dd>
            </div>
          ))}
        </dl>

        {(proposta || sel?.unitario_adotado != null) && (
          <div className="rounded-lg border border-stone-200 bg-stone-50 px-3 py-2.5 text-sm">
            <p className="font-medium text-stone-800">
              Proposta da IA: {unitIA != null && unitIA !== '' ? `${moeda(unitIA)}/m²` : 'média da amostra'}
              {' · '}faixa ± {numero2(proposta?.faixa_pct ?? sel?.faixa_pct ?? 10)}%
            </p>
            {justIA && <p className="mt-0.5 break-words text-xs text-stone-600">{justIA}</p>}
            {unitIA != null && unitIA !== '' && (
              <button type="button" className="btn-link !p-0 mt-1 text-xs" disabled={!!ocupado}
                      onClick={() => { setUnit(txtNum(unitIA)); if (!just.trim()) setJust(justIA) }}>
                Usar a proposta da IA
              </button>
            )}
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="rotulo" htmlFor="cv-unit">Valor unitário adotado (R$/m²)</label>
            <input id="cv-unit" className="input" inputMode="decimal" value={unit} disabled={!!ocupado}
                   placeholder={est ? br2(est.media) : ''} onChange={(e) => setUnit(e.target.value)} />
            {est && (
              <p className="ajuda">
                Média {moeda(est.media)}{' '}
                <button type="button" className="btn-link !p-0 text-xs" onClick={() => setUnit(br2(est.media))}>usar a média</button>
              </p>
            )}
          </div>
          <div>
            <label className="rotulo" htmlFor="cv-faixa">Faixa ± (%)</label>
            <input id="cv-faixa" className="input" inputMode="decimal" value={faixa} disabled={!!ocupado}
                   onChange={(e) => setFaixa(e.target.value)} />
          </div>
        </div>
        {fora && est && (
          <div className="faixa-aviso" role="alert">
            O unitário está fora do intervalo dos escolhidos ({moeda(est.min)} a {moeda(est.max)}/m²).
          </div>
        )}
        <div>
          <label className="rotulo" htmlFor="cv-just">Justificativa do unitário{difereMedia ? ' *' : ''}</label>
          <textarea id="cv-just" className="input min-h-[72px]" value={just} disabled={!!ocupado}
                    onChange={(e) => setJust(e.target.value)} />
          <FalarAqui alvo="cv-just" valor={just} aoMudar={setJust} />
          <p className="ajuda">Obrigatória quando o unitário é diferente da média.</p>
        </div>

        <div className="rounded-lg bg-barro-claro px-3 py-2.5 text-sm" aria-live="polite">
          {!base || area === null ? (
            <p className="text-stone-700">Escolha a base do cálculo e a área do imóvel para ver a prévia do valor.</p>
          ) : previa ? (
            <>
              <p className="text-stone-700">
                {numero2(area)} m² ({nomeBase}) × {moeda(u)}/m² = <span className="tabular-nums">{moeda(previa.calculado)}</span>
              </p>
              <p className="mt-0.5 text-base font-semibold tabular-nums text-stone-900">
                Valor adotado (arredondado ao milhar): {moeda(previa.adotado)}
              </p>
              <p className="text-xs text-stone-600">Faixa: {moeda(previa.min)} a {moeda(previa.max)}</p>
            </>
          ) : (
            <p className="text-stone-700">Informe o valor unitário para ver a prévia do valor.</p>
          )}
        </div>

        {alertas.length > 0 && (
          <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2.5" role="alert" data-testid="alertas-valor">
            <p className="text-sm font-semibold text-amber-900">Atenção antes de confirmar</p>
            <ul className="list-disc space-y-0.5 pl-5 text-sm text-amber-900">
              {alertas.map((a) => <li key={a}>{a}</li>)}
            </ul>
            {!difereMedia && !conf.trim() && (
              // 102-6: unitário = média e dispersão alta — a decisão padrão do avaliador (D-068) num toque
              <button type="button" className="btn-sec btn-peq w-full sm:w-auto" disabled={!!ocupado} data-testid="motivo-padrao"
                      onClick={() => setConf(MOTIVO_PADRAO_DISPERSAO)}>
                Manter a amostra (mercado raso; conta da dispersão só na planilha)
              </button>
            )}
            <label className="rotulo" htmlFor="cv-conf">Confirmo mesmo assim, porque…</label>
            <textarea id="cv-conf" className="input min-h-[56px]" value={conf} disabled={!!ocupado}
                      onChange={(e) => setConf(e.target.value)}
                      placeholder="Explique por que esta amostra e este unitário estão certos — ou volte para a lista." />
          </div>
        )}

        {erro && <div className="faixa-erro" role="alert">{erro}</div>}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" className="btn-sec sm:mr-auto" disabled={!!ocupado} onClick={() => void voltarLista()}>
            {ocupado === 'voltar' ? 'Voltando…' : 'Voltar para a lista'}
          </button>
          <button type="button" className="btn-sec" disabled={!!ocupado} onClick={() => void enviar(false)}>
            {ocupado === 'salvar' ? 'Salvando…' : 'Só salvar'}
          </button>
          <button type="button" className="btn" disabled={!!ocupado || !base || !campoArea}
                  title={!base || !campoArea ? 'Escolha a base do cálculo e a área do imóvel' : undefined}
                  onClick={() => void enviar(true)}>
            {ocupado === 'continuar' ? 'Enviando…' : 'Confirmar e gerar o laudo'}
          </button>
        </div>
      </div>
    </section>
  )
}

// 102-6: a decisão padrão do Alan quando a dispersão passa de 15% num mercado raso (D-068)
const MOTIVO_PADRAO_DISPERSAO = 'Manter a amostra: mercado raso, são as ofertas do segmento encontradas na região. Conta da dispersão só na planilha.'

const PADRAO_ESCOLHA = 'escolha manual do avaliador'
/** "escolha manual do avaliador: escolha manual do avaliador: X" -> "escolha manual do avaliador: X" (083-D). */
export function semRepeticao(t: string | null | undefined): string {
  return String(t ?? '').replace(new RegExp(`^(${PADRAO_ESCOLHA})(?:\\s*:\\s*${PADRAO_ESCOLHA})+`, 'i'), '$1')
}
/** Só o que o avaliador escreveu, sem o rótulo padrão. */
export function semPadrao(t: string): string {
  return semRepeticao(t).replace(new RegExp(`^${PADRAO_ESCOLHA}\\s*:?\\s*`, 'i'), '')
}

/** 102-3: colar os anúncios numa tela só — duas caixas abertas (amostra e "só comparação") e UM botão que guarda as
 *  duas filas e pede à extensão para abrir e enviar tudo sozinha. De 8 toques para 3. */
export function ColarDuasFilas({ jobId, referenciaFisco, aoMudar }: {
  jobId: string; referenciaFisco?: number | null; aoMudar: (msg: string) => void
}) {
  const [amostra, setAmostra] = useState('')
  const [comparacao, setComparacao] = useState('')
  const [estado, setEstado] = useState('')
  const [ocupado, setOcupado] = useState(false)
  // 103-3a: a fila é do servidor — depois do ↻ da extensão ou de recarregar a página, os links que faltam continuam aqui
  const [fila, setFila] = useState<{ links: string[]; faltam: number; recebidos: number; total: number } | null>(null)
  const [acompanhando, setAcompanhando] = useState(false)
  const [usou, setUsou] = useState(false)
  const ultimos = useRef(-1)
  const avisar = useRef(aoMudar)
  avisar.current = aoMudar
  // 110-1: a fila anda sozinha — se nada chega em 20 s, a própria tela pede de novo à extensão (até 3 vezes seguidas
  // sem nada chegar; aí avisa e deixa o "Continuar")
  const andou = useRef(Date.now())
  const tentativas = useRef(0)
  const pedir = useRef<(auto: boolean) => void>(() => undefined)
  useEffect(() => {
    let vivo = true
    const ler = () => get<{ faltam: { n: number | null; link: string }[]; recebidos: number; total: number }>(
      `/jobs/${encodeURIComponent(jobId)}/extensao/anuncios`).then((r) => {
      if (!vivo) return
      setFila({ links: r.faltam.filter((f) => f.n === null).map((f) => f.link), faltam: r.faltam.length,
                recebidos: r.recebidos, total: r.total })
      if (ultimos.current >= 0 && r.recebidos > ultimos.current) {   // o envio andou: some o aviso de erro
        andou.current = Date.now(); tentativas.current = 0
        setEstado(r.faltam.length ? `${r.recebidos} de ${r.total} recebidos. A extensão está abrindo o próximo…`
          : `${r.recebidos} de ${r.total} recebidos.`)
        avisar.current(`${r.recebidos} de ${r.total} anúncios recebidos.`)
      }
      ultimos.current = r.recebidos
      if (!r.faltam.length) { if (acompanhando) setAcompanhando(false); return }
      if (acompanhando && Date.now() - andou.current > 20000) {
        andou.current = Date.now()
        tentativas.current += 1
        if (tentativas.current <= 3) {
          setEstado(`${r.recebidos} de ${r.total} recebidos. A extensão parou; pedi para continuar sozinha (${tentativas.current}ª vez)…`)
          pedir.current(true)
        } else {
          setAcompanhando(false)
          setEstado(`${r.recebidos} de ${r.total} recebidos. A extensão não está andando (o anúncio que falta pode estar pedindo ` +
            'verificação numa aba aberta). Resolva a aba e toque em Continuar, ou use o botão Enviar ao JdB no anúncio.')
        }
      }
    }).catch(() => { /* sem a fila: a tela segue */ })
    ler()
    const t = acompanhando ? setInterval(ler, 5000) : undefined
    return () => { vivo = false; if (t) clearInterval(t) }
  }, [jobId, acompanhando])
  const links = (t: string) => [...new Set(t.split(/\s+/).map((x) => x.trim()).filter((x) => /^https?:\/\//i.test(x)))].slice(0, 15)
  function continuar() {                 // 103-3a: os que ficaram na fila, sem colar de novo
    andou.current = Date.now(); tentativas.current = 0
    setOcupado(true); setAcompanhando(true); setEstado('Pedindo à extensão…')
    pedirExtensao()
  }
  pedir.current = (auto) => pedirExtensao(auto)
  async function enviar() {
    const la = links(amostra), lc = links(comparacao)
    if (!la.length && !lc.length) { setEstado('Cole pelo menos um link (começando com http:// ou https://).'); return }
    setOcupado(true); setEstado('Guardando os links…')
    try {
      const j = encodeURIComponent(jobId)
      if (la.length) await post(`/jobs/${j}/extensao/colados`, { links: la, decisao: 'entra' })
      if (lc.length) await post(`/jobs/${j}/extensao/colados`, { links: lc, decisao: 'comparacao' })
    } catch (e) {
      setOcupado(false)
      setEstado(ehAuth(e) ? '' : erroTxt(e))
      return
    }
    andou.current = Date.now(); tentativas.current = 0
    setAcompanhando(true); setUsou(true)
    pedirExtensao()
  }
  function pedirExtensao(auto = false) {
    let respondeu = false
    const ouvir = (ev: MessageEvent) => {
      const m = ev.data as { jdb?: string; ok?: boolean; erro?: string; total?: number } | null
      if (ev.source !== window || !m || m.jdb !== 'abrir-anuncios-resposta') return
      respondeu = true
      window.removeEventListener('message', ouvir)
      setOcupado(false)
      if (auto) {                          // 110-1: o pedido automático só fala se der erro de permissão
        if (!m.ok && m.erro === 'PORTAIS') setEstado('Falta permitir o JdB nos portais: toque no ícone do JdB, no alto do Chrome, e em “Permitir”.')
        return
      }
      if (!m.ok && /^J[áa] estou abrindo/.test(m.erro || '')) {
        setEstado('A extensão continua abrindo os anúncios, um de cada vez.')
      } else if (m.ok && m.total) {
        setEstado(m.total === 1 ? 'A extensão está abrindo o anúncio e enviando sozinha.'
          : `A extensão está abrindo ${m.total} anúncios, um de cada vez, e enviando sozinha.`)
        setAmostra(''); setComparacao('')
        aoMudar('Anúncios a caminho: eles aparecem aqui conforme chegam.')
      } else if (m.ok) setEstado('Nada para abrir: estes anúncios já chegaram com foto e data de acesso.')
      else if (m.erro === 'PORTAIS') setEstado('Falta permitir o JdB nos portais: toque no ícone do JdB, no alto do Chrome, e em “Permitir”.')
      else setEstado('A extensão não conseguiu abrir agora. Abra cada anúncio no Chrome e toque em Enviar ao JdB.')
    }
    window.addEventListener('message', ouvir)
    window.postMessage({ jdb: 'abrir-anuncios', trabalho: jobId }, window.location.origin)
    setTimeout(() => {
      if (!respondeu) {
        window.removeEventListener('message', ouvir)
        setOcupado(false)
        if (auto) return                   // a próxima volta (20 s) tenta de novo
        setEstado('Links guardados, mas a extensão não respondeu (não está ligada neste Chrome?). Abra cada anúncio e toque em Enviar ao JdB: ele vai direto para este trabalho.')
      }
    }, 3000)
  }
  return (
    <div className="grid gap-3 rounded-xl border border-stone-200 bg-white p-4" data-testid="colar-duas-filas">
      <div className={`grid gap-3 ${referenciaFisco ? 'sm:grid-cols-2' : ''}`}>
        <label className="grid gap-1 text-[16px] font-semibold">Anúncios da amostra
          <textarea className="input min-h-[110px] text-[15px] font-normal" value={amostra} disabled={ocupado}
                    onChange={(e) => setAmostra(e.target.value)} placeholder={'Cole os links, um por linha'} />
        </label>
        {!!referenciaFisco && (
          <label className="grid gap-1 text-[16px] font-semibold">Padrão superior abaixo de {moeda(referenciaFisco)} — só comparação
            <textarea className="input min-h-[110px] text-[15px] font-normal" value={comparacao} disabled={ocupado}
                      onChange={(e) => setComparacao(e.target.value)} placeholder={'Cole os links (fora da amostra e do cálculo)'} />
          </label>
        )}
      </div>
      <button type="button" className="btn min-h-[48px] justify-self-start" disabled={ocupado} onClick={() => void enviar()}>
        {ocupado ? 'Mandando…' : 'Abrir e enviar sozinho'}
      </button>
      {!ocupado && !acompanhando && fila && fila.faltam > 0 && (fila.links.length > 0 || usou) && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-300 bg-amber-50 p-2" data-testid="fila-colados">
          <span className="text-[16px]">Faltam {fila.faltam} {fila.faltam === 1 ? 'anúncio' : 'anúncios'} que ainda não chegaram ({fila.recebidos} de {fila.total} recebidos).</span>
          <button type="button" className="btn btn-peq" onClick={continuar}>Continuar</button>
        </div>
      )}
      {estado && <p className="text-[16px]" role="status">{estado}</p>}
    </div>
  )
}
