/** ORDEM 059 — Detalhes do trabalho (L13 da v2): seções que abrem e fecham, na ordem do desenho.
 * Só mostra e reaproveita o que já existe (dados, divergências, dossiê de pesquisa, cálculo, eventos,
 * entrega e proposta/contrato do cliente). Nada de nome de arquivo nem código na tela (D-101). */
import FotosAnuncio from './FotosAnuncio'
import { baixarArquivo } from './Downloads'
import { useEffect, useState, type ReactNode } from 'react'
import { Camera, FileText } from 'lucide-react'
import { ApiError, baixar, baixarRaw, get, post, postForm } from './api'
import { EditorCampo } from './Acoes'
import { salvarBlob } from './Entrega'
import { AdicionarReferencial } from './Referenciais'
import { dataBR, dataHoraBR, etapaRotulo, moeda, msgSegura, numero2, plural } from './rotulos'
import type { Campo, Detalhe, Evento, ResultadoCalculo, ResultadoEntrega, ResultadoExtracao } from './tipos'
import { nomeCampo, semRepetidos } from './nomesCampos'

// ---------------------------------------------------------------- seção que abre e fecha
export function Secao({ id, titulo, aberta, alternar, children }: {
  id: string; titulo: string; aberta: boolean; alternar: () => void; children: ReactNode
}) {
  return (
    <section id={`l13-${id}`} className="secao-l13">
      <h2 className="secao-l13-h">
        <button type="button" className="secao-l13-topo" aria-expanded={aberta} aria-controls={`l13-${id}-corpo`} onClick={alternar}>
          <span aria-hidden="true" className="seta-l13">{aberta ? '▼' : '▶'}</span>{titulo}
        </button>
      </h2>
      {aberta && <div id={`l13-${id}-corpo`} className="secao-l13-corpo">{children}</div>}
    </section>
  )
}

/** Bloco dentro de uma seção (ex.: "Mudar a escolha dos anúncios"), fechado por padrão. */
export function Mais({ titulo, children, aberto }: { titulo: string; children: ReactNode; aberto?: boolean }) {
  return (
    <details className="mais-l13" open={aberto}>
      <summary>{titulo}</summary>
      <div className="mais-l13-corpo">{children}</div>
    </details>
  )
}

const Vazio = ({ children }: { children: ReactNode }) => <p className="small-jdb">{children}</p>

/** D-101: sem código de regra nem nome de arquivo na tela (mesma regra do pendencias_simples). */
export function limpo(msg: string | null | undefined): string {
  return msgSegura(msg)
    .replace(/\s*\((?:D|F-S|K|P)-?\d+(?:\.\d+)?(?:\s*\/\s*(?:D|F-S|K|P)-?\d+)*\)/g, '')
    .replace(/\b(?:D|F-S)-\d{3}\b/g, 'regra')
    .replace(/\b[\w\-.]+\.(?:jpe?g|png|pdf|docx?|xlsx|heic|md)\b/gi, 'um arquivo')
    .replace(/\s{2,}/g, ' ').trim()
}

const ETAPA_TXT: Record<string, string> = { orquestrador: 'Sistema', revisao: 'Revisão' }
const etapaTxt = (id: string) => ETAPA_TXT[id] ?? etapaRotulo(id)

// ---------------------------------------------------------------- dados que a tela busca
export interface DocL13 { nome: string; tipo: string; caminho: string; rotulo: string; descartado: string; recebido: string }
export interface AnuncioL13 {
  n: number; link: string; portal: string; preco: number | null; area_m2: number | null; unitario: number | null
  acessado_em: string; escolhido: boolean; motivos: string[]; tem_prova: boolean
  foto?: string; fotos_url?: string[]; foto_url_escolhida?: string; foto_avaliador?: boolean; foto_arte?: boolean   // 173
}

/** GET simples que recarrega quando `versao` muda (o trabalho foi atualizado). */
export function useBusca<T>(caminho: string | null, versao: string): T | null {
  const [v, setV] = useState<T | null>(null)
  useEffect(() => {
    if (!caminho) { setV(null); return }
    let vivo = true
    get<T>(caminho).then((r) => { if (vivo) setV(r) }).catch(() => { if (vivo) setV(null) })
    return () => { vivo = false }
  }, [caminho, versao])
  return v
}

// ---------------------------------------------------------------- 1. documentos
const TIPO_ARQ: Record<string, string> = { documento: 'Documento do imóvel', solicitante: 'Documento do solicitante',
  mapa_digital: 'Mapa Digital Fácil (Prefeitura de Goiânia)' }

function periodo(datas: string[]): string {
  const d = [...new Set(datas.filter(Boolean))].sort()
  if (!d.length) return ''
  const f = (x: string) => dataBR(x).slice(0, 5)
  return d.length === 1 ? f(d[0]) : `${f(d[0])} a ${f(d[d.length - 1])}`
}

export function linhasDocumentos(docs: DocL13[]): { chave: string; foto: boolean; texto: string; obs: string }[] {
  // 080-5: as fotos e páginas capturadas dos anúncios não são documentos do imóvel: uma linha só (estão em Anúncios)
  const GRUPOS: Record<string, string> = { foto: 'Fotos da vistoria', foto_cliente: 'Fotos enviadas pelo cliente', video_cliente: 'Vídeos enviados pelo cliente',
    mercado: 'Fotos e páginas dos anúncios' }
  const out = docs.filter((d) => !GRUPOS[d.tipo]).map((d) => ({
    chave: d.caminho, foto: false,
    texto: `${d.rotulo || TIPO_ARQ[d.tipo] || 'Documento'}${d.recebido ? ` · ${dataBR(d.recebido).slice(0, 5)}` : ''}`,
    obs: d.descartado ? `Não usado no laudo: ${limpo(d.descartado)}` : '',
  }))
  for (const [tipo, rotulo] of Object.entries(GRUPOS)) {
    const grupo = docs.filter((d) => d.tipo === tipo)
    if (!grupo.length) continue
    const p = periodo(grupo.map((f) => f.recebido))
    out.push({ chave: tipo, foto: true, texto: `${rotulo} (${grupo.length})${p ? ` · ${p}` : ''}`,
               obs: tipo === 'foto' ? '' : tipo === 'mercado' ? 'Ficam com cada anúncio, na parte Anúncios.'
                 : 'Não são fotos de vistoria: o laudo só usa as fotos que você tirou.' })
  }
  return out
}

export interface ConversaImportada { importacao: string; contato: string; mensagens: number; transcritos: number }

export function Documentos({ docs, extra, conversas, aoVerConversa }: {
  docs: DocL13[] | null; extra?: ReactNode; conversas?: ConversaImportada[]; aoVerConversa?: (imp: string) => void
}) {
  if (!docs) return <Vazio>Carregando os documentos…</Vazio>
  const linhas = linhasDocumentos(docs)
  return (
    <div className="grid gap-3">
      {(conversas ?? []).filter((c) => c.mensagens > 0).map((c) => (
        <p key={c.importacao} className="flex flex-wrap items-center justify-between gap-2">
          <span>Conversa do WhatsApp{c.contato ? ` com ${c.contato}` : ''} · {c.mensagens} mensagens{c.transcritos ? ` · ${c.transcritos} áudios em texto` : ''}</span>
          {aoVerConversa && <button type="button" className="det-l13" onClick={() => aoVerConversa(c.importacao)}>Ver</button>}
        </p>
      ))}
      {linhas.length ? (
        <ul className="lista-l13">
          {linhas.map((l) => (
            <li key={l.chave}>
              <span className="flex items-center gap-2">
                {l.foto ? <Camera size={20} aria-hidden="true" /> : <FileText size={20} aria-hidden="true" />}{l.texto}
              </span>
              {l.obs && <span className="small-jdb block">{l.obs}</span>}
            </li>
          ))}
        </ul>
      ) : <Vazio>Nenhum documento enviado ainda.</Vazio>}
      <p className="small-jdb">O tipo é o que o JdB leu em cada documento; a data é a do envio.</p>
      {extra}
    </div>
  )
}

// ---------------------------------------------------------------- 2. dados do imóvel
const ORIGEM_TXT: Record<string, string> = { vistoria: 'Vistoria', pesquisa: 'Pesquisa', inferido: 'Deduzido pelo JdB' }

/** "De onde veio" em palavras: o documento lido (pelo tipo detectado), a vistoria, a pesquisa… */
export function deOndeVeio(c: Campo, docs: DocL13[] | null): string {
  const fonte = c.fonte || ''
  if (c.origem === 'documento' || /^(documento|solicitante)\//.test(fonte)) {
    const nomes = (docs ?? []).filter((d) => d.rotulo && fonte.includes(d.caminho)).map((d) => d.rotulo)
    if (nomes.length) return [...new Set(nomes)].join(' e ')
    return fonte.startsWith('solicitante/') ? 'Documento do solicitante' : 'Documento do imóvel'
  }
  if (c.origem === 'pendente') {
    if (c.valor !== null && c.valor !== undefined && c.valor !== '') return 'Dados do trabalho'
    return 'Falta'
  }
  return ORIGEM_TXT[c.origem] ?? 'Vistoria'
}

function valorTxt(c: Campo): string {
  if (c.valor === null || c.valor === undefined || c.valor === '') return '—'
  return `${c.valor}${c.unidade ? ` ${c.unidade}` : ''}`
}

const LIMITE_LINHAS = 12


export function DadosImovel({ campos, docs, podeCorrigir, jobId, arquivos, campoAberto, setCampo, aoSalvo, alterados }: {
  campos: Campo[]; docs: DocL13[] | null; podeCorrigir: boolean; jobId: string; arquivos: Detalhe['arquivos']
  campoAberto: string | null; setCampo: (n: string | null) => void
  aoSalvo: (nome: string, antes: string, depois: string) => void; alterados: boolean
}) {
  const [todos, setTodos] = useState(false)
  if (!campos.length) return <Vazio>Os dados aparecem aqui quando o JdB terminar de ler os documentos.</Vazio>
  // o que falta primeiro; o campo em correção sempre aparece; o mesmo dado repetido com nome interno some (080-5)
  const unicos = semRepetidos(campos)
  const faltam = unicos.filter((c) => deOndeVeio(c, docs) === 'Falta')
  const ordem = [...faltam, ...unicos.filter((c) => !faltam.includes(c))]
  const visiveis = todos ? ordem : ordem.filter((c, i) => i < LIMITE_LINHAS || c.nome === campoAberto)
  return (
    <div className="grid gap-3">
      {alterados && <p className="aviso-simples">Você corrigiu dados depois do último laudo. Atualize o laudo para eles entrarem no PDF.</p>}
      <div className="tabela-l13" role="table" aria-label="Dados do imóvel">
        <div className="linha-l13 cab-l13" role="row">
          <span role="columnheader">Campo</span><span role="columnheader">Valor</span>
          <span role="columnheader">De onde veio</span><span role="columnheader"><span className="sr-only">Ação</span></span>
        </div>
        {visiveis.map((c) => (
          <div key={c.nome} role="row" className="linha-l13">
            <b role="cell">{nomeCampo(c.nome)}</b>
            <span role="cell" className="break-words">{valorTxt(c)}</span>
            <span role="cell" className="small-jdb">{deOndeVeio(c, docs)}</span>
            <span role="cell">
              {podeCorrigir && campoAberto !== c.nome && (
                <button type="button" className="det-l13" onClick={() => setCampo(c.nome)} aria-label={`Corrigir ${nomeCampo(c.nome)}`}>Corrigir</button>
              )}
            </span>
            {campoAberto === c.nome && (
              <div className="editor-l13">
                <EditorCampo jobId={jobId} campo={c} nome={c.nome} arquivos={arquivos} aoCancelar={() => setCampo(null)}
                             aoSalvar={(novo) => { setCampo(null); aoSalvo(c.nome, c.valor == null ? '' : String(c.valor), novo ?? '') }} />
              </div>
            )}
          </div>
        ))}
      </div>
      {ordem.length > LIMITE_LINHAS && (
        <button type="button" className="det-l13 justify-self-start" onClick={() => setTodos(!todos)}>
          {todos ? 'Mostrar menos' : `Mostrar todos os ${ordem.length} dados`}
        </button>
      )}
      {!podeCorrigir && <p className="small-jdb">Dá para corrigir quando o JdB terminar de montar.</p>}
    </div>
  )
}

// ---------------------------------------------------------------- 3. divergências
export function nDivergencias(ext: ResultadoExtracao | null): number {
  return (ext?.divergencias?.length ?? 0) + (ext?.documentos_descartados?.length ?? 0)
}

interface EscolhaArea { base: 'construida' | 'terreno'; campo: string; valor: number; origem: string }

export function DivergenciasL13({ ext, area, dataConfirmada }: {
  ext: ResultadoExtracao | null; area: EscolhaArea | null; dataConfirmada: string
}) {
  const div = ext?.divergencias ?? []
  const desc = ext?.documentos_descartados ?? []
  if (!div.length && !desc.length && !area && !dataConfirmada) return <Vazio>Nenhuma divergência entre os documentos.</Vazio>
  return (
    <ul className="lista-l13">
      {div.map((d) => <li key={d} className="break-words">{limpo(d)}</li>)}
      {desc.map((d) => (
        <li key={d.arquivo} className="break-words">Documento não usado no laudo. <b>Motivo:</b> {limpo(d.motivo)}</li>
      ))}
      {area && (
        <li>Área do cálculo → escolhida: <b>{area.campo}</b>, {numero2(area.valor)} m²{area.base === 'terreno' ? ' (terreno)' : ''}.</li>
      )}
      {dataConfirmada && <li className="break-words">Data da vistoria → {dataConfirmada}</li>}
    </ul>
  )
}

// ---------------------------------------------------------------- 4. anúncios analisados
async function verProva(jobId: string, n: number, setErro: (m: string) => void) {
  // abre a aba antes do download (o navegador bloqueia janela aberta depois de esperar)
  const aba = window.open('', '_blank')
  try {
    const { blob } = await baixarRaw(`/jobs/${encodeURIComponent(jobId)}/anuncios/${n}/prova`)
    const url = URL.createObjectURL(blob)
    if (aba) aba.location.href = url
    else salvarBlob(blob, `prova-anuncio-${n}.${blob.type.includes('pdf') ? 'pdf' : 'jpg'}`)
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (e) {
    aba?.close()
    setErro(e instanceof ApiError && e.status === 404 ? 'Este anúncio não tem prova guardada.' : 'Não deu para abrir a prova.')
  }
}

const msgErro = (e: unknown, padrao: string) => (e instanceof ApiError ? msgSegura(e.message) || padrao : padrao)

// ORDEM 076-A: o estado da amostra (valor do laudo × valor com a amostra de agora)
interface EstadoAmostra {
  laudo: { valor: string | null; escolhidos: number[] }
  agora: { escolhidos: number[]; n: number; valor: string | null; media: string | null; cv: number | null }
  mudou: boolean; minimo: number; abaixo_do_minimo: boolean; revisao: number
  // 082-A1/4: o essencial de cada anúncio (para o avaliador reconhecer qual é qual) e o que acabou de ser salvo
  refs?: Record<string, CartaoRef>
  salvo?: CartaoRef & { n: number }
  ultimo_envio?: { n: number | null; quando: string } | null    // 086-5
}
interface CartaoRef { rua: string; bairro: string; lote_m2: number | null; area_m2: number | null; preco: number | null
  unitario: number | null; foto: boolean; divergencia?: Record<string, number | string> }

const ROTULO_DIV: Record<string, string> = { area_m2: 'área construída', lote_m2: 'lote', preco: 'preço', quartos: 'quartos',
  suites: 'suítes', bairro: 'bairro', rua: 'rua' }
const fmtDiv = (campo: string, v: unknown) => (campo === 'preco' && typeof v === 'number' ? moeda(v)
  : /_m2$/.test(campo) && typeof v === 'number' ? `${numero2(v)} m²` : String(v ?? '—'))

/** Miniatura da foto principal do anúncio (082-A1). Sem foto: um aviso curto no lugar. */
function FotoAnuncio({ jobId, n, tem }: { jobId: string; n: number; tem: boolean }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    if (!tem) return
    let vivo = true, u = ''
    baixarRaw(`/jobs/${encodeURIComponent(jobId)}/candidatos/${n}/foto`)
      .then(({ blob }) => { u = URL.createObjectURL(blob); if (vivo) setUrl(u) }).catch(() => { /* sem foto */ })
    return () => { vivo = false; if (u) URL.revokeObjectURL(u) }
  }, [jobId, n, tem])
  if (!tem || !url) return <span className="foto-anuncio-l13 small-jdb grid place-items-center text-center">sem foto</span>
  return <img className="foto-anuncio-l13" src={url} alt={`Foto principal do anúncio ${n}`} />
}

function Corrigir({ a, ref, jobId, aoSalvar, aoFechar }: { a: AnuncioL13; ref?: CartaoRef; jobId: string
  aoSalvar: (e: EstadoAmostra) => void; aoFechar: () => void }) {
  const br = (v: number | null | undefined) => (v != null ? String(v).replace('.', ',') : '')
  const [preco, setPreco] = useState(br(ref?.preco ?? a.preco))
  const [area, setArea] = useState(br(ref?.area_m2 ?? a.area_m2))
  const [lote, setLote] = useState(br(ref?.lote_m2))          // 082-A2: o lote guardado aparece (não "se mudar" vazio)
  const [rua, setRua] = useState(ref?.rua ?? '')
  const [foto, setFoto] = useState<File | null>(null)
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)
  async function salvar() {
    setSalvando(true); setErro('')
    const fd = new FormData()
    fd.append('preco', preco); fd.append('area_m2', area); fd.append('lote_m2', lote); fd.append('rua', rua)
    if (foto) fd.append('foto', foto, foto.name)
    try { aoSalvar(await postForm<EstadoAmostra>(`/jobs/${encodeURIComponent(jobId)}/amostra/${a.n}/corrigir`, fd)); aoFechar() }
    catch (e) { setErro(msgErro(e, 'Não deu para corrigir.')) } finally { setSalvando(false) }
  }
  return (
    <div className="grid gap-2 rounded-lg border border-[var(--borda)] bg-white p-3" data-testid={`corrigir-${a.n}`}>
      <div className="grid gap-2 sm:grid-cols-3">
        <label className="grid gap-1 text-[16px]">Preço (R$)<input className="input" inputMode="decimal" value={preco} onChange={(e) => setPreco(e.target.value)} /></label>
        <label className="grid gap-1 text-[16px]">Área construída (m²)<input className="input" inputMode="decimal" value={area} onChange={(e) => setArea(e.target.value)} /></label>
        <label className="grid gap-1 text-[16px]">Lote (m²)<input className="input" inputMode="decimal" value={lote} onChange={(e) => setLote(e.target.value)} /></label>
      </div>
      <label className="grid gap-1 text-[16px]">Rua (localização)<input className="input" value={rua} placeholder="ex.: Rua VF-21" onChange={(e) => setRua(e.target.value)} /></label>
      <label className="grid gap-1 text-[16px]">Foto ou print do anúncio
        <input type="file" accept="image/*" onChange={(e) => setFoto(e.target.files?.[0] ?? null)} /></label>
      {erro && <p className="aviso-impede" role="alert">{erro}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn btn-peq" disabled={salvando} onClick={() => void salvar()}>{salvando ? 'Salvando…' : 'Salvar'}</button>
        <button type="button" className="btn-sec btn-peq" disabled={salvando} onClick={aoFechar}>Cancelar</button>
      </div>
    </div>
  )
}

function LinhaAnuncio({ a, jobId, setErro, setAviso, amostra, mudarAmostra }: {
  a: AnuncioL13; jobId: string; setErro: (m: string) => void; setAviso?: (m: string) => void
  amostra?: EstadoAmostra | null; mudarAmostra?: (e: EstadoAmostra) => void
}) {
  const ref = amostra?.refs?.[String(a.n)]
  const [corrigindo, setCorrigindo] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const preco = ref?.preco ?? a.preco, areaC = ref?.area_m2 ?? a.area_m2, unit = ref?.unitario ?? a.unitario
  const numeros = [preco != null && moeda(preco), areaC != null && `${numero2(areaC)} m² construídos`,
    ref?.lote_m2 != null && `lote ${numero2(ref.lote_m2)} m²`, unit != null && `${moeda(unit)}/m²`].filter(Boolean).join(' · ')
  const onde = [ref?.rua, ref?.bairro].filter(Boolean).join(', ')
  const naAmostra = amostra ? amostra.agora.escolhidos.includes(a.n) : a.escolhido
  async function responderDiv(campo: string, manter: boolean) {
    if (!mudarAmostra) return
    setOcupado(true)
    try {
      await post(`/jobs/${encodeURIComponent(jobId)}/candidatos/${a.n}/divergencia`, { campo, manter })
      mudarAmostra(await get<EstadoAmostra>(`/jobs/${encodeURIComponent(jobId)}/amostra`))
    } catch (e) { setErro(msgErro(e, 'Não deu para responder.')) } finally { setOcupado(false) }
  }
  async function alternar() {
    if (!amostra || !mudarAmostra) return
    const nova = naAmostra ? amostra.agora.escolhidos.filter((n) => n !== a.n) : [...amostra.agora.escolhidos, a.n]
    if (!nova.length) { setErro('A amostra não pode ficar vazia.'); return }
    setOcupado(true)
    try { mudarAmostra(await post<EstadoAmostra>(`/jobs/${encodeURIComponent(jobId)}/amostra`, { escolhidos: nova })) }
    catch (e) { setErro(msgErro(e, 'Não deu para mudar a amostra.')) } finally { setOcupado(false) }
  }
  return (
    <li className="anuncio-l13">
      <span className="flex items-start gap-3">
        {ref && <FotoAnuncio jobId={jobId} n={a.n} tem={ref.foto} />}
        <span className="grid min-w-0 gap-1">
          <span><b>Anúncio {a.n}</b> · {a.portal}</span>
          {onde ? <span>{onde}</span> : ref && <span className="small-jdb">Rua não informada: use Corrigir.</span>}
          {numeros && <span className="tabular-nums">{numeros}</span>}
        </span>
      </span>
      {Object.entries(ref?.divergencia ?? {}).map(([campo, v]) => (
        <span key={campo} className="grid gap-1 rounded-lg border border-[var(--amarelo)] bg-[#fff8e1] p-2" data-testid={`divergencia-${a.n}-${campo}`}>
          <span>O anúncio hoje mostra {ROTULO_DIV[campo] ?? campo} {fmtDiv(campo, v)}; o laudo usa {fmtDiv(campo, (ref as unknown as Record<string, unknown>)[campo])}.</span>
          <span className="flex flex-wrap gap-2">
            <button type="button" className="btn btn-peq" disabled={ocupado} onClick={() => void responderDiv(campo, true)}>Manter {fmtDiv(campo, (ref as unknown as Record<string, unknown>)[campo])}</button>
            <button type="button" className="btn-sec btn-peq" disabled={ocupado} onClick={() => void responderDiv(campo, false)}>Trocar para {fmtDiv(campo, v)}</button>
          </span>
        </span>
      ))}
      {!a.escolhido && a.motivos.length > 0 && <span><b>Motivo:</b> {limpo(a.motivos.join('; '))}</span>}
      <span className="small-jdb">{/^\d/.test(a.acessado_em) ? `Visto em ${a.acessado_em}` : 'Data de acesso não registrada'}</span>
      {naAmostra && (                     // 173: a foto da tabela de amostras, à mostra para trocar (refaz só a tabela)
        <FotosAnuncio jobId={jobId} c={a} aoMudar={(m) => setAviso?.(m)} />
      )}
      {a.tem_prova
        ? <button type="button" className="det-l13 justify-self-start" onClick={() => void verProva(jobId, a.n, setErro)}>Ver a prova</button>
        : <span className="small-jdb">Sem a captura da página (prova com data, hora e link). Abra o anúncio e toque em Enviar ao JdB: a prova é guardada junto.</span>}
      {amostra && mudarAmostra && (
        <span className="flex flex-wrap gap-2" data-testid={`acoes-anuncio-${a.n}`}>
          <button type="button" className="btn-sec btn-peq" disabled={ocupado} onClick={() => void alternar()}>
            {naAmostra ? 'Tirar da amostra' : 'Pôr na amostra'}
          </button>
          {/^https?:\/\//i.test(a.link) && (
            <a className="btn-sec btn-peq" href={a.link} target="_blank" rel="noopener noreferrer">Abrir anúncio</a>
          )}
          <button type="button" className="btn-sec btn-peq" onClick={() => setCorrigindo((c) => !c)} aria-expanded={corrigindo}>Corrigir</button>
        </span>
      )}
      {corrigindo && mudarAmostra && (
        <Corrigir a={a} ref={ref} jobId={jobId} aoFechar={() => setCorrigindo(false)} aoSalvar={(e) => {
          mudarAmostra(e)
          const sv = e.salvo                                   // 082-A4: confirmação na hora, com a média nova
          if (sv && setAviso) setAviso(`Salvo: anúncio ${sv.n}, ${[sv.area_m2 != null && `${numero2(sv.area_m2)} m²`,
            sv.unitario != null && `${moeda(sv.unitario)}/m²`].filter(Boolean).join(' · ')}.`
            + (e.agora.media ? ` Média agora ${moeda(Number(e.agora.media))}/m²` : '')
            + (e.agora.valor ? `; valor ${moeda(Number(e.agora.valor))}.` : '.'))
        }} />
      )}
    </li>
  )
}

export function Anuncios({ jobId, dados, extra }: {
  jobId: string; dados: { anuncios: AnuncioL13[]; dossie: boolean } | null; extra?: ReactNode
}) {
  const [erro, setErro] = useState('')
  const [amostra, setAmostra] = useState<EstadoAmostra | null>(null)
  const [aviso, setAviso] = useState('')
  const [gerando, setGerando] = useState(false)
  const [conf, setConf] = useState<string | null>(null)
  useEffect(() => {
    let vivo = true
    get<EstadoAmostra>(`/jobs/${encodeURIComponent(jobId)}/amostra`).then((r) => { if (vivo) setAmostra(r) }).catch(() => { /* sem barra */ })
    return () => { vivo = false }
  }, [jobId, dados])
  if (!dados) return <Vazio>Carregando os anúncios…</Vazio>
  const naAmostra = (a: AnuncioL13) => (amostra ? amostra.agora.escolhidos.includes(a.n) : a.escolhido)
  const esc = dados.anuncios.filter(naAmostra)
  const desc = dados.anuncios.filter((a) => !naAmostra(a))
  async function desfazer() {
    if (!amostra) return
    try { setAmostra(await post<EstadoAmostra>(`/jobs/${encodeURIComponent(jobId)}/amostra`, { escolhidos: amostra.laudo.escolhidos })) }
    catch (e) { setErro(msgErro(e, 'Não deu para desfazer.')) }
  }
  async function gerar() {
    setGerando(true); setErro('')
    try {
      await post(`/jobs/${encodeURIComponent(jobId)}/amostra/gerar`, { confirmacao: conf ?? '' })
      setAviso(`Gerando a REVISÃO ${amostra?.revisao ?? 1} com a amostra nova.`); setConf(null)
    } catch (e) {
      const m = msgErro(e, 'Não deu para gerar.')
      if (/confirme/i.test(m)) setConf('')            // pede o "Confirmo mesmo assim, porque…" ali mesmo
      setErro(m)
    } finally { setGerando(false) }
  }
  const valor = (v: string | null | undefined) => (v ? moeda(Number(v)) : '—')
  async function baixarDossie() {
    try {
      const { blob, nome } = await baixarRaw(`/jobs/${encodeURIComponent(jobId)}/dossie.pdf`)
      salvarBlob(blob, nome || 'dossie-de-pesquisa.pdf')
    } catch { setErro('Não deu para baixar o dossiê.') }
  }
  return (
    <div className="grid gap-4">
      <div className="grid gap-1" data-testid="adicionar-anuncio">
        <AdicionarReferencial jobId={jobId} aoMudar={setAviso} rotulo="+ Adicionar anúncio" perguntarDestino={!!amostra?.laudo.valor} />
        <p className="small-jdb">Ou abra o anúncio no seu Chrome e toque em Enviar ao JdB.</p>
        {amostra?.ultimo_envio && (
          <p className="text-[16px]" role="status" data-testid="ultimo-envio">✓ Último anúncio recebido pela extensão:
            {amostra.ultimo_envio.n != null ? ` nº ${amostra.ultimo_envio.n},` : ''} {dataHoraBR(amostra.ultimo_envio.quando)}.</p>
        )}
        {aviso && <p className="text-[16px]" role="status">{aviso}</p>}
      </div>
      {amostra?.mudou && (
        <div className="grid gap-2 rounded-lg border border-[var(--amarelo)] bg-[#fff8e1] p-3" role="status" data-testid="amostra-mudou">
          <p><b>A amostra mudou:</b> valor passou de {valor(amostra.laudo.valor)} para {valor(amostra.agora.valor)}.
            {amostra.agora.cv != null && <span className="small-jdb"> (média {valor(amostra.agora.media)}/m², CV {String(amostra.agora.cv).replace('.', ',')}%)</span>}</p>
          {amostra.abaixo_do_minimo && (
            <p className="aviso-impede">Ficam só {amostra.agora.n} anúncios. O mínimo é {amostra.minimo}. Adicione outro antes de gerar o laudo.</p>
          )}
          {conf !== null && (
            <label className="grid gap-1 text-[16px]">Confirmo mesmo assim, porque…
              <input className="input" value={conf} onChange={(e) => setConf(e.target.value)} /></label>
          )}
          <p className="texto">{/* 153-3: avisa antes o que vai refazer */}
            Vou refazer só a conta, a planilha, a tabela dos referenciais e os números do texto. O resto do texto do laudo fica igual: a IA não reescreve o laudo.</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn btn-peq" disabled={gerando || amostra.abaixo_do_minimo} onClick={() => void gerar()}>
              {gerando ? 'Mandando…' : `Gerar a REVISÃO ${amostra.revisao} com a amostra nova`}
            </button>
            <button type="button" className="btn-sec btn-peq" disabled={gerando} onClick={() => void desfazer()}>Desfazer</button>
          </div>
        </div>
      )}
      {!amostra?.mudou && amostra?.abaixo_do_minimo && (
        <p className="aviso-impede">Ficam só {amostra.agora.n} anúncios. O mínimo é {amostra.minimo}. Adicione outro antes de gerar o laudo.</p>
      )}
      {dados.anuncios.length ? (
        <>
          <p>{plural(esc.length, 'escolhido', 'escolhidos')} · {plural(desc.length, 'descartado', 'descartados')} com motivo · prova com data e hora</p>
          {erro && <p className="aviso-impede" role="alert">{erro}</p>}
          {esc.length > 0 && (
            <div className="grid gap-2">
              <h3 className="titulo-sub-l13">Escolhidos ({esc.length})</h3>
              <ul className="lista-l13">{esc.map((a) => <LinhaAnuncio key={a.n} a={a} jobId={jobId} setErro={setErro} setAviso={setAviso} amostra={amostra} mudarAmostra={setAmostra} />)}</ul>
            </div>
          )}
          {desc.length > 0 && (
            <div className="grid gap-2">
              <h3 className="titulo-sub-l13">Fora da amostra ({desc.length})</h3>
              <ul className="lista-l13">{desc.map((a) => <LinhaAnuncio key={a.n} a={a} jobId={jobId} setErro={setErro} setAviso={setAviso} amostra={amostra} mudarAmostra={setAmostra} />)}</ul>
            </div>
          )}
          {dados.dossie && (
            <button type="button" className="btn-sec-grande justify-self-start" style={{ width: 'auto' }} onClick={() => void baixarDossie()}>
              Baixar o dossiê de pesquisa
            </button>
          )}
        </>
      ) : <Vazio>Os anúncios aparecem aqui depois da pesquisa.</Vazio>}
      {extra}
    </div>
  )
}

// ---------------------------------------------------------------- 5. cálculo
const num = (v: string | number | null | undefined) => (v === null || v === undefined || v === '' ? NaN : Number(v))

/** "R$ 2.844,44/m² × 180,00 m² = R$ 511.999,20" (+ o valor adotado, se foi arredondado). */
export function contaResumida(r: ResultadoCalculo): { conta: string; adotado: string } | null {
  const u = num(r.unitario_adotado)
  const a = num(r.area)
  if (!Number.isFinite(u) || !Number.isFinite(a)) return null
  const bruto = Math.round(u * a * 100) / 100
  const v = num(r.valor_adotado)
  const arred = Number.isFinite(v) && Math.abs(v - bruto) >= 0.01
  return {
    conta: `${moeda(u)}/m² × ${numero2(a)} m² = ${moeda(bruto)}`,
    adotado: `Valor adotado: ${moeda(r.valor_adotado)}${arred ? ' (arredondado)' : ''} · faixa ${moeda(r.valor_min)} a ${moeda(r.valor_max)}`,
  }
}

export function CalculoL13({ jobId, r, previa, planilha, extra }: {
  jobId: string; r: ResultadoCalculo | null; previa: boolean; planilha: string | null; extra?: ReactNode
}) {
  const [erro, setErro] = useState('')
  const conta = r ? contaResumida(r) : null
  async function baixarPlanilha() {
    if (!planilha) return
    try { salvarBlob(await baixar(jobId, planilha), planilha.split('/').pop() || 'planilha.xlsx') } catch { setErro('Não deu para baixar a planilha.') }
  }
  return (
    <div className="grid gap-3">
      {conta ? (
        <>
          {previa && <p className="small-jdb">Prévia: ainda não está no laudo.</p>}
          <p className="conta-l13 tabular-nums">{conta.conta}</p>
          <p className="tabular-nums">{conta.adotado}</p>
        </>
      ) : <Vazio>A conta aparece aqui depois da escolha dos anúncios.</Vazio>}
      {erro && <p className="aviso-impede" role="alert">{erro}</p>}
      {planilha
        ? <button type="button" className="btn-sec-grande justify-self-start" style={{ width: 'auto' }} onClick={() => void baixarPlanilha()}>Baixar planilha</button>
        : <p className="small-jdb">A planilha sai junto com o laudo.</p>}
      {extra}
    </div>
  )
}

// ---------------------------------------------------------------- 6. histórico
const LIMITE_HIST = 15

export function Historico({ eventos, extra }: { eventos: Evento[]; extra?: ReactNode }) {
  const [todos, setTodos] = useState(false)
  const lista = eventos.filter((e) => e.nivel !== 'resultado' && e.msg).slice().reverse()
  const vis = todos ? lista : lista.slice(0, LIMITE_HIST)
  return (
    <div className="grid gap-3">
      {extra}
      {vis.length ? (
        <ul className="lista-l13">
          {vis.map((e) => (
            <li key={e.id} className="break-words">
              <span className="tabular-nums small-jdb">{dataHoraBR(e.ts)}</span> · <b>{etapaTxt(e.etapa)}</b> — {limpo(e.msg)}
            </li>
          ))}
        </ul>
      ) : <Vazio>Nada registrado ainda.</Vazio>}
      {lista.length > LIMITE_HIST && (
        <button type="button" className="det-l13 justify-self-start" onClick={() => setTodos(!todos)}>
          {todos ? 'Mostrar menos' : `Mostrar tudo (${lista.length})`}
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- 7. arquivos gerados
export interface PropostaCli { id: string; numero: string; status: string; arquivos: string[] }

export function arquivosGerados(entrega: ResultadoEntrega | null, proposta: PropostaCli | null): number {
  return (entrega?.arquivos ?? []).filter((a) => !/\.md$/i.test(a)).length + (proposta?.arquivos?.length ?? 0)
}

const rotuloArquivo = (nome: string, revisao: number) => {
  const ext = (nome.split('.').pop() || '').toLowerCase()
  const rev = revisao > 0 ? ` · revisão ${revisao}` : ''        // mesma contagem do L10
  if (/^contrato/i.test(nome)) return 'Contrato (Word)'
  if (/^proposta/i.test(nome)) return 'Proposta (Word)'
  if (/_assinado/i.test(nome)) return `Laudo assinado (PDF)${rev}`
  return ext === 'pdf' ? `Laudo (PDF)${rev}` : ext === 'docx' ? `Laudo (Word)${rev}` : ext === 'xlsx' ? `Planilha de cálculo${rev}` : 'Arquivo'
}

export function ArquivosGerados({ jobId, entrega, revisao, proposta, abrirLaudo, extra, aprovado = false }: {
  jobId: string; entrega: ResultadoEntrega | null; revisao: number; proposta: PropostaCli | null
  abrirLaudo?: () => void; extra?: ReactNode
  aprovado?: boolean                 // 166: antes do ✓ só o PDF; Word e planilha só depois
}) {
  const [erro, setErro] = useState('')
  const laudo = (entrega?.arquivos ?? []).filter((a) => !/\.md$/i.test(a))
  async function baixarLaudo(a: string) {
    try { salvarBlob(await baixar(jobId, a), a.split('/').pop() || a) } catch { setErro('Não deu para baixar o arquivo.') }
  }
  async function baixarProposta(nome: string) {
    if (!proposta) return
    try {
      const { blob } = await baixarRaw(`/propostas/${encodeURIComponent(proposta.id)}/arquivo/${encodeURIComponent(nome)}`)
      salvarBlob(blob, nome)
    } catch { setErro('Não deu para baixar o arquivo.') }
  }
  const linhas: { chave: string; texto: string; acao: () => void }[] = [
    ...(proposta?.arquivos ?? []).map((n) => ({ chave: `p:${n}`, texto: `${rotuloArquivo(n, 0)} nº ${proposta!.numero}`, acao: () => void baixarProposta(n) })),
    // 166: o laudo sai da versão ATUAL (rota /baixar) — antes do ✓ só o PDF; depois PDF, Word, planilha e tudo (.zip)
    ...(laudo.length ? (aprovado ? (['pdf', 'docx', 'xlsx', 'tudo'] as const) : (['pdf'] as const)) : []).map((t) => ({
      chave: `b:${t}`,
      texto: t === 'pdf' ? `Laudo (PDF)${aprovado ? '' : ` · revisão ${Math.max(1, revisao)}`}` : t === 'docx' ? 'Laudo (Word)'
        : t === 'xlsx' ? 'Planilha de cálculo' : 'Tudo (.zip com os três)',
      acao: () => void baixarArquivo(jobId, t).catch(() => setErro('Não deu para baixar o arquivo.')) })),
    ...laudo.filter((a) => /_assinado/i.test(a)).map((a) => ({ chave: `l:${a}`, texto: rotuloArquivo(a.split('/').pop() || a, revisao),
      acao: () => void baixarLaudo(a) })),
  ]
  return (
    <div className="grid gap-3">
      {linhas.length ? (
        <ul className="lista-l13">
          {linhas.map((l) => (
            <li key={l.chave} className="flex flex-wrap items-center justify-between gap-2">
              <span>{l.texto}</span>
              <button type="button" className="det-l13" onClick={l.acao}>Baixar</button>
            </li>
          ))}
        </ul>
      ) : <Vazio>Nenhum arquivo gerado ainda.</Vazio>}
      {erro && <p className="aviso-impede" role="alert">{erro}</p>}
      {abrirLaudo && laudo.length > 0 && (
        <button type="button" className="btn-sec-grande justify-self-start" style={{ width: 'auto' }} onClick={abrirLaudo}>Abrir o laudo</button>
      )}
      {extra}
    </div>
  )
}
