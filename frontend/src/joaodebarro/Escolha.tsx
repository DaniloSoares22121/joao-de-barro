/* ORDEM 053 (L9): "Escolha os anúncios" em 3 partes — anúncios (1 de 3) → perguntas (2 de 3) →
 * fim (3 de 3) → o JdB monta o laudo (L8). Funções que o app já tem (041/003): Usar = o anúncio
 * entra; Trocar = sai e o próximo candidato aparece; "Decide você" (D-063); perguntas do
 * alinhamento; "Montar laudo" = seguir com a pesquisa. Números como no PDF (R$/m² com 2 casas). */
import FotosAnuncio from './FotosAnuncio'
import { FalarAqui } from './Falar'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, Check, Clock, ExternalLink } from 'lucide-react'
import { ApiError, baixarRaw, get, post, postForm, put } from './api'
import { MIN_ESCOLHIDOS, ordenarCandidatos } from './listaCandidatos'
import LinksBusca from './LinksBusca'
import { AdicionarReferencial, ColarDuasFilas } from './Referenciais'
import { ImagensAprovar } from './ImagensLaudo'
import { moeda, numero2 } from './rotulos'
import { useStore } from './store'
import type { Detalhe, Referencial } from './tipos'

interface Ponto { id: string; pergunta: string; opcoes: string[]; recomendada: string }
interface Situacao {
  motivo: string
  extensao: { vista: string; atual: string; atualizar: boolean }
}
interface Estado { pontos: Ponto[]; candidatos: Referencial[]; decidido?: string; situacao?: Situacao; respondidos?: number; referencia_fisco?: number | null }

/** ORDEM 070-C: os caminhos que a L9 antiga tinha, sempre à vista (com lista cheia ou vazia). */
function Caminhos({ jobId, s, aoMudar }: { jobId: string; s?: Situacao; aoMudar: (m: string) => void }) {
  return (
    <div className="caminhos-l9">
      {s?.motivo && <p className="aviso-simples" role="status">{s.motivo}</p>}
      <div className="caminhos-botoes">
        <LinksBusca jobId={jobId} colar={false} />
        <AdicionarReferencial jobId={jobId} aoMudar={aoMudar} />
      </div>
      <p className="small-jdb">Ou abra o anúncio no seu Chrome e toque na extensão › <b>Enviar ao JdB</b>.</p>
      {s?.extensao.atualizar && (
        <p className="small-jdb">
          {s.extensao.vista
            ? `A extensão do JdB no seu Chrome está na versão ${s.extensao.vista}; a atual é ${s.extensao.atual}.`
            : 'Confira se a extensão do JdB no seu Chrome está atualizada.'}
          {' '}Para atualizar: abra <b>chrome://extensions</b> e toque em ↻ na extensão do JdB.
        </p>
      )}
    </div>
  )
}

const erroDe = (e: unknown) => (e instanceof ApiError ? e.message : 'Não deu certo. Tente de novo.')

/** Ilustração de casinha (do desenho) quando o anúncio não tem foto guardada. */
function Casinha() {
  return (
    <svg viewBox="0 0 200 120" preserveAspectRatio="xMidYMid slice" className="foto-anuncio" role="img" aria-label="Anúncio sem foto guardada">
      <rect x="0" y="0" width="200" height="120" fill="#E9E1D3" /><rect x="0" y="92" width="200" height="28" fill="#CFC3AE" />
      <rect x="55" y="48" width="90" height="48" fill="#D9C3A5" /><path d="M45 52 L100 18 L155 52Z" fill="#8C6A4F" />
      <rect x="92" y="66" width="18" height="30" fill="#16283A" /><rect x="64" y="60" width="18" height="14" fill="#fff" /><rect x="120" y="60" width="18" height="14" fill="#fff" />
    </svg>
  )
}

function Foto({ jobId, c }: { jobId: string; c: Referencial }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    if (!c.foto || /^https?:/.test(c.foto)) return
    let vivo = true
    let u = ''
    baixarRaw(`/jobs/${encodeURIComponent(jobId)}/candidatos/${c.n}/foto`).then(({ blob }) => {
      if (!vivo) return
      u = URL.createObjectURL(blob); setUrl(u)
    }).catch(() => undefined)
    return () => { vivo = false; if (u) URL.revokeObjectURL(u) }
  }, [jobId, c.n, c.foto])
  return url ? <img src={url} alt={`Foto do anúncio ${c.n}`} className="foto-anuncio" /> : <Casinha />
}

/** 091-3: o selo diz o que falta, não "foto/dados". */
function falta(c: Referencial) {
  const f = [!c.area_m2 && 'a área construída', !c.preco && 'o preço', !c.foto && 'a foto'].filter(Boolean) as string[]
  return 'Falta ' + (f.length > 1 ? f.slice(0, -1).join(', ') + ' e ' + f[f.length - 1] : f[0])
}

/** 091-3: área (e lote) no próprio cartão, quando o anúncio não trouxe. */
function InformarArea({ j, c, ocupado, agir }: { j: string; c: Referencial; ocupado: boolean; agir: (f: () => Promise<unknown>) => Promise<void> }) {
  const [area, setArea] = useState('')
  const [lote, setLote] = useState(c.lote_m2 ? String(c.lote_m2).replace('.', ',') : '')
  const salvo = useRef('')
  function salvar() {                      // 096-6: salva ao sair do campo (sem o toque em "Salvar")
    const chave = `${area.trim()}|${lote.trim()}`
    if (!area.trim() || chave === salvo.current || ocupado) return
    salvo.current = chave
    const fd = new FormData(); fd.append('area_m2', area.trim()); if (lote.trim()) fd.append('lote_m2', lote.trim())
    void agir(() => postForm(`/jobs/${j}/amostra/${c.n}/corrigir`, fd))
  }
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); salvar() }}>
      <label className="grid gap-1 small-jdb">Área construída (m²)
        <input className="campo-grande" inputMode="decimal" value={area} onChange={(e) => setArea(e.target.value)} onBlur={salvar} style={{ width: 140 }} /></label>
      <label className="grid gap-1 small-jdb">Lote (m²)
        <input className="campo-grande" inputMode="decimal" value={lote} onChange={(e) => setLote(e.target.value)} onBlur={salvar} style={{ width: 140 }} /></label>
      <button type="submit" className="btn-verde" style={{ width: 'auto' }} disabled={ocupado || !area.trim()}>Salvar</button>
    </form>
  )
}

const FONTE_IDADE: Record<string, string> = {
  'anúncio': 'do anúncio', anuncio: 'do anúncio', fotos: 'da foto', avaliador: 'confirmada por você', relato: 'do seu relato',
}

/** 110-2: a idade aparente de cada anúncio, com a origem; a que veio das fotos pede confirmação em 1 toque. */
function IdadeAnuncio({ j, c, ocupado, agir }: { j: string; c: Referencial; ocupado: boolean; agir: (f: () => Promise<unknown>) => Promise<void> }) {
  const [editando, setEditando] = useState(false)
  const [idade, setIdade] = useState('')
  const fonte = c.idade_fonte || ''
  const tem = !!(c.idade_aparente || '').trim()
  const pedir = fonte === 'fotos' && tem
  return (
    <div className={pedir ? 'aviso-simples' : ''}>
      <p className="texto">
        <b>Idade aparente:</b> {tem ? c.idade_aparente : 'o anúncio não diz'}
        {tem && FONTE_IDADE[fonte] ? ` (${FONTE_IDADE[fonte]})` : ''}
        {pedir ? '. Confere?' : ''}
      </p>
      {!editando && (pedir || !tem) && (
        <div className="flex flex-wrap gap-2">
          {pedir && (
            <button type="button" className="btn-verde" style={{ width: 'auto' }} disabled={ocupado}
                    onClick={() => void agir(() => post(`/jobs/${j}/pendencias/aceitar`, { chave: `idade_foto:${c.n}` }))}>
              <Check size={20} aria-hidden="true" /> Confere</button>
          )}
          <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} disabled={ocupado}
                  onClick={() => setEditando(true)}>{pedir ? 'Corrigir' : 'Informar a idade'}</button>
        </div>
      )}
      {editando && (
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => {
          e.preventDefault()
          if (!idade.trim()) return
          void agir(() => put(`/jobs/${j}/candidatos/${c.n}/idade`, { idade: idade.trim() })).then(() => setEditando(false))
        }}>
          <label className="grid gap-1 texto">Idade aparente
            <input id={`idade-${c.n}`} className="campo-grande" value={idade} onChange={(e) => setIdade(e.target.value)} placeholder="Ex.: 30 anos, novo" style={{ width: 200 }} /></label>
          <FalarAqui alvo={`idade-${c.n}`} valor={idade} aoMudar={setIdade} />
          <button type="submit" className="btn-verde" style={{ width: 'auto' }} disabled={ocupado || !idade.trim()}>Salvar</button>
        </form>
      )}
    </div>
  )
}

function quando(iso: string) {
  const d = new Date(iso)
  if (!iso || Number.isNaN(d.getTime())) return ''
  return `${d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })} às ${d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`
}

function Cabeca({ titulo, sub, parte, voltar }: { titulo: string; sub?: string; parte: 1 | 2 | 3; voltar: () => void }) {
  return (
    <>
      <div className="flex flex-wrap gap-x-5">
        <button type="button" className="voltar-jdb" onClick={voltar}><ArrowLeft size={18} aria-hidden="true" /> Trabalho</button>
        <button type="button" className="voltar-jdb" onClick={() => useStore.getState().ir('lista')}>Voltar para a lista</button>
      </div>
      <div className="flex items-start justify-between gap-3">
        <div><h1 className="titulo-jdb">{titulo}</h1>{sub && <p className="sub-jdb">{sub}</p>}</div>
        <span className={`selo-parte ${parte === 3 ? 'selo-parte-fim' : ''}`}>{parte} de 3</span>
      </div>
      <div className="barra-partes" aria-hidden="true"><span style={{ width: `${(parte / 3) * 100}%` }} /></div>
    </>
  )
}

export default function Escolha() {
  const jid = useStore((s) => s.jobId) ?? ''
  const ir = useStore((s) => s.ir)
  const [d, setD] = useState<Estado | null>(null)
  const [det, setDet] = useState<Detalhe | null>(null)
  const [parte, setParte] = useState<1 | 2 | 3>(1)
  const [respostas, setRespostas] = useState(0)
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState('')
  const [confirmar, setConfirmar] = useState<number | null>(null)   // L201-3: nº do anúncio que destoa, à espera do "Usar"
  const [parteTexto, setParteTexto] = useState('')
  const [soParte, setSoParte] = useState(false)       // 073-1: o campo só aparece depois de "Só uma parte"
  const [aviso, setAviso] = useState('')
  const j = encodeURIComponent(jid)
  const carregar = useCallback(() => {
    get<Estado>(`/jobs/${j}/alinhamento`).then(setD).catch((e) => setErro(erroDe(e)))
    get<Detalhe>(`/jobs/${j}`).then(setDet).catch(() => undefined)
  }, [j])
  useEffect(carregar, [carregar])
  // 103-3c: enquanto os anúncios chegam pela extensão, a lista se atualiza sozinha (sem recarregar a página)
  useEffect(() => {
    if (parte !== 1) return
    const t = setInterval(() => { if (!document.hidden) carregar() }, 6000)
    return () => clearInterval(t)
  }, [parte, carregar])
  const voltar = () => ir('job', jid)

  async function montar() {                // 102-5: um botão só — monta o laudo e abre o trabalho
    await agir(async () => { await post(`/jobs/${j}/pesquisa/continuar`); ir('job', jid) })
  }
  async function agir(f: () => Promise<unknown>) {
    setErro(''); setOcupado(true)
    try { await f() } catch (e) { setErro(erroDe(e)) } finally { setOcupado(false); carregar() }
  }
  if (!d) return <p className="texto" role="status">{erro || 'Abrindo…'}</p>

  const dados = det?.job.dados
  const imovel = dados ? [(dados as { objeto_parte?: string }).objeto_parte || dados.tipo, dados.bairro].filter(Boolean).join(' – ') : ''
  // 091-6: o que o avaliador trouxe aparece na ordem dele (1…6); o que o JdB achou, na ordem de semelhança
  const seus = (c: { fonte_coleta?: string }) => c.fonte_coleta === 'avaliador' || c.fonte_coleta === 'manual'
  const todos = [...d.candidatos.filter(seus).sort((a, b) => a.n - b.n), ...ordenarCandidatos(d.candidatos.filter((c) => !seus(c)), false)]
  const usados = d.candidatos.filter((c) => c.decisao === 'entra')
  // 091-1/2: uma conta só — "entra" está em uso mesmo com aviso; descartado é o "descarta" ou o riscado que não entrou
  const ehDescartado = (c: Referencial) => c.decisao === 'descarta' || (!!c.nao_recomendado && c.decisao !== 'entra' && c.decisao !== 'comparacao')   // 092-9
  const descartados = d.candidatos.filter(ehDescartado)
  const aMostrar = todos.filter((c) => !ehDescartado(c))
  const errTxt = erro && <p className="aviso-impede" role="alert">{erro}</p>

  // ---------------------------------------------------------------- 3 de 3
  if (parte === 3) {
    return (
      <section className="tela-simples tela-larga">
        <Cabeca titulo="Tudo certo" parte={3} voltar={voltar} />
        <div className="cartao-pad grid justify-items-center gap-3 py-10 text-center">
          <span className="circulo-ok" aria-hidden="true"><Check size={48} /></span>
          <h2 className="titulo-cartao">Pronto. Vou montar o laudo.</h2>
          <p className="sub-jdb">{usados.length} {usados.length === 1 ? 'anúncio' : 'anúncios'} e {d.respondidos ?? respostas} {(d.respondidos ?? respostas) === 1 ? 'resposta guardada' : 'respostas guardadas'}.</p>
          <button type="button" className="btn-verde" style={{ minWidth: 320 }} disabled={ocupado}
                  onClick={() => void agir(async () => { await post(`/jobs/${j}/pesquisa/continuar`); ir('job', jid) })}>Montar laudo</button>
          {errTxt}
        </div>
      </section>
    )
  }
  // ---------------------------------------------------------------- 2 de 3
  if (parte === 2) {
    if (!d.pontos.length) { if (!ocupado) void montar(); return <p className="texto" role="status">Montando o laudo…</p> }   // 102-5
    return (
      <section className="tela-simples tela-larga">
        <Cabeca titulo={d.pontos.length === 1 ? 'Só 1 pergunta' : `Só ${d.pontos.length} perguntas`} sub="Respondo o resto sozinho." parte={2} voltar={voltar} />
        {errTxt}
        {d.pontos.map((p) => (
          <div key={p.id} className="proximo-passo">
            <h2 className="titulo-cartao">{p.pergunta}</h2>
            <div className="botoes">
              {p.opcoes.map((o) => (
                <button key={o} type="button" disabled={ocupado} className={o === p.recomendada ? 'btn-verde' : 'btn-sec-grande'}
                        onClick={() => {
                          if (p.id === 'objeto' && /parte/i.test(o)) { setSoParte(true); return }
                          void agir(async () => { await post(`/jobs/${j}/alinhamento`, { id: p.id, resposta: o, texto: '' }); setRespostas((n) => n + 1) })
                        }}>
                  {o}{o === p.recomendada ? ' ★' : ''}
                </button>
              ))}
            </div>
            {p.id === 'objeto' && soParte && (
              <form className="flex flex-wrap gap-2" onSubmit={(e) => {
                e.preventDefault()
                if (parteTexto.trim()) void agir(async () => { await post(`/jobs/${j}/alinhamento`, { id: 'objeto', resposta: 'Só uma parte', texto: parteTexto.trim() }); setRespostas((n) => n + 1) })
              }}>
                <label className="sr-only" htmlFor="parte-l9">Qual parte?</label>
                <input id="parte-l9" className="campo-grande flex-1" placeholder="Qual parte? Ex.: Galpão 01" value={parteTexto}
                       onChange={(e) => setParteTexto(e.target.value)} autoFocus />
                <button type="submit" className="btn-verde" style={{ width: 'auto' }} disabled={ocupado || !parteTexto.trim()}>Confirmar</button>
              </form>
            )}
          </div>
        ))}
      </section>
    )
  }
  // ---------------------------------------------------------------- 1 de 3
  const k = new Map(todos.filter((c) => c.recomendado).map((c, i) => [c.n, i + 1]))
  return (
    <section className="tela-simples tela-larga">
      <Cabeca titulo="Escolha os anúncios" parte={1} voltar={voltar}
              sub={`${imovel ? imovel + ' · ' : ''}${usados.length} ${usados.length === 1 ? 'escolhido' : 'escolhidos'} de ${d.candidatos.length} analisados.`} />
      {/* 102-3: as duas filas (amostra e só comparação) numa caixa só, com um botão para as duas */}
      <ColarDuasFilas jobId={jid} referenciaFisco={d.referencia_fisco} aoMudar={(m) => { setAviso(m); carregar() }} />
      <Caminhos jobId={jid} s={d.situacao} aoMudar={(m) => { setAviso(m); carregar() }} />
      {aviso && <p className="aviso-simples" role="status">{aviso}</p>}
      <div className="flex justify-end">
        <button type="button" className="btn3-jdb" disabled={ocupado || aMostrar.length === 0}
                onClick={() => void agir(() => post(`/jobs/${j}/alinhamento`, { id: 'decide', resposta: '' }))}>Decide você</button>
      </div>
      {d.decidido && <p className="aviso-simples" role="status">Decidido: {d.decidido}</p>}
      {d.referencia_fisco ? (                  // 097-1: a comparação (D-069) é perguntada aqui, antes de montar
        <div className="proximo-passo">
          <h2 className="titulo-cartao">Laudo para o fisco: tem anúncios de padrão superior abaixo de {moeda(d.referencia_fisco)}?</h2>
          <p className="small-jdb">Cole os links na caixa “Padrão superior — só comparação”, no alto: entram fora da amostra e do cálculo.</p>
          <div className="botoes">
            <button type="button" className="btn-sec-grande" disabled={ocupado}
                    onClick={() => void agir(() => post(`/jobs/${j}/comparacao/nao-tenho`, {}))}>Não tenho</button>
          </div>
        </div>
      ) : null}
      {errTxt}
      <ul className="lista-cartoes">
        {aMostrar.map((c) => {
          const rm2 = c.preco && c.area_m2 ? c.preco / c.area_m2 : null
          const visto = quando(c.acessado_em || c.visto_em || '')
          const usado = c.decisao === 'entra'
          return (
            <li key={c.n} className={`cartao-anuncio ${usado ? 'usado' : ''}`}>
              <Foto jobId={jid} c={c} />
              <div className="grid gap-2">
                <div className="flex flex-wrap gap-2">
                  <span className="tag-cinza">{k.has(c.n) ? `#${k.get(c.n)} mais parecido` : `Anúncio ${c.n}`}</span>
                  {c.fonte_coleta === 'avaliador' && <span className="tag-cinza">Enviado por você (Chrome)</span>}
                  {(c.destoa ?? []).map((e) => <span key={e} className="tag-amarela">{e}</span>)}
                </div>
                <h2 className="titulo-anuncio">{c.titulo || [c.tipologia, c.bairro].filter(Boolean).join(' – ')}</h2>
                <dl className="numeros-anuncio">
                  <div><dt>Preço</dt><dd>{c.preco ? moeda(c.preco) : 'não informado'}</dd></div>
                  <div><dt>Área</dt><dd>{c.area_m2 ? `${numero2(c.area_m2)} m²` : 'não informada'}</dd></div>
                  {rm2 && <div><dt>R$/m²</dt><dd className="barro">{moeda(rm2)}</dd></div>}
                </dl>
                <IdadeAnuncio j={j} c={c} ocupado={ocupado} agir={agir} />
                {c.motivo && <p className="por-que"><b>{c.recomendado ? 'Por que indico:' : 'Atenção:'}</b> {c.motivo}</p>}
                {visto && <p className="small-jdb inline-flex items-center gap-1"><Clock size={16} aria-hidden="true" /> Visto em {visto}</p>}
                {(!c.foto || !c.preco || !c.area_m2 || c.link) && (
                  <p className="small-jdb flex flex-wrap items-center gap-x-3">
                    {(!c.foto || !c.preco || !c.area_m2) && <span className="tag-cinza">{falta(c)}</span>}
                    {c.link && <a href={c.link} target="_blank" rel="noopener noreferrer" className="link-jdb inline-flex items-center gap-1">Abrir anúncio <ExternalLink size={16} aria-hidden="true" /></a>}
                  </p>
                )}
                {!c.area_m2 && <InformarArea j={j} c={c} ocupado={ocupado} agir={agir} />}
                {c.foto_arte && <p className="aviso-impede">A foto principal é uma arte de anúncio, não a casa. Escolha outra abaixo
                  ou use [Colar print ou enviar foto].</p>}
                {/* 173: fotos sempre à mostra (a escolhida marcada) + colar print ou enviar foto */}
                <FotosAnuncio jobId={jid} c={c} ocupado={ocupado} aoMudar={() => void agir(async () => undefined)} />
              </div>
              <div className="botoes-anuncio">
                {confirmar === c.n && !usado ? (
                  <p className="aviso-impede" role="alert">
                    Este anúncio é {(c.destoa ?? []).join(' e ')} que o avaliando (regra 6). Usar mesmo assim?{' '}
                    <button type="button" disabled={ocupado} className="btn-verde"
                            onClick={() => { setConfirmar(null); void agir(() => put(`/jobs/${j}/candidatos/${c.n}`, { decisao: 'entra' })) }}>Usar</button>{' '}
                    <button type="button" className="btn-sec-grande" onClick={() => setConfirmar(null)}>Cancelar</button>
                  </p>
                ) : (
                <button type="button" disabled={ocupado} className={usado ? 'btn-sec-grande' : 'btn-verde'}
                        onClick={() => (!usado && (c.destoa ?? []).length ? setConfirmar(c.n)
                          : void agir(() => put(`/jobs/${j}/candidatos/${c.n}`, { decisao: usado ? '' : 'entra' })))}>
                  {usado ? '✓ Em uso' : 'Usar'}
                </button>
                )}
                <button type="button" disabled={ocupado} className="btn-sec-grande"
                        onClick={() => void agir(() => put(`/jobs/${j}/candidatos/${c.n}`, { decisao: 'descarta', motivo: 'trocado pelo avaliador' }))}>Trocar</button>
                {/* 080-4 (D-069): padrão superior abaixo da referência do fisco — item próprio, fora do cálculo */}
                <button type="button" disabled={ocupado} className="btn-sec-grande"
                        onClick={() => void agir(() => put(`/jobs/${j}/candidatos/${c.n}`, { decisao: c.decisao === 'comparacao' ? '' : 'comparacao' }))}>
                  {c.decisao === 'comparacao' ? '✓ Só comparação' : 'Só comparação'}</button>
              </div>
            </li>
          )
        })}
      </ul>
      {descartados.length > 0 && (
        <details className="detalhes detalhes-jdb detalhes-esq">
          <summary>Ver os descartados e o motivo ({descartados.length})</summary>
          <ul className="lista-simples">
            {descartados.map((c) => (
              <li key={c.n}><span>{c.titulo || `Anúncio ${c.n}`}</span><span className="small-jdb">{c.motivo_descarte || c.motivo || 'fora do padrão'}</span>
                <button type="button" className="btn-sec-grande" disabled={ocupado}
                        onClick={() => void agir(() => put(`/jobs/${j}/candidatos/${c.n}`, { decisao: 'entra' }))}>Usar mesmo assim</button></li>
            ))}
          </ul>
        </details>
      )}
      <ImagensAprovar jobId={jid} />{/* 172-3: mapa e capa aprovados antes de montar */}
      <div className="fixm-jdb">
        <button type="button" className="btn-verde" disabled={usados.length < MIN_ESCOLHIDOS || ocupado}
                onClick={() => (d.pontos.length ? setParte(2) : void montar())}>
          {usados.length < MIN_ESCOLHIDOS ? `Escolha pelo menos ${MIN_ESCOLHIDOS} (faltam ${MIN_ESCOLHIDOS - usados.length})` : 'Montar o laudo'}
        </button>
      </div>
    </section>
  )
}
