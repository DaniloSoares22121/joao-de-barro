/* ORDEM 045 / D-100: pendências simples. Erro do sistema não aparece (uma linha discreta:
 * "Corrigindo sozinho: N ajustes de montagem"); pendência do avaliador vira um cartão curto, com
 * botões e a recomendação marcada; o texto técnico fica em "Ver detalhes". Vermelho só no que
 * impede de seguir. */
import Espera from './Espera'
import { useCallback, useEffect, useState } from 'react'
import { ApiError, baixarRaw, get, post, postForm, put } from './api'
import { useStore } from './store'
import { AdicionarReferencial } from './Referenciais'
import ListaErros, { type Erro } from './ListaErros'

export interface Opcao { rotulo: string; acao: string; recomendada?: boolean; id?: string; resposta?: string; texto?: string; campo?: string; etapa?: string; tipo?: string; refazer?: string; linha?: string; n?: number; url?: string; manter?: boolean; sugerida?: boolean }
export interface Cartao { chave: string; titulo: string; opcoes: Opcao[]; detalhe: string; impede: boolean; pagina: string; links?: string[]; total?: number; recebidos?: number; imagem?: string; galeria?: { n: number; fotos: string[] }; pontos?: { texto: string; trecho: string }[]; erros?: Erro[] }
export interface Simples { cards: Cartao[]; resumo: string; linha_sozinho: string; sozinho: string[]; descartadas: string[]; avisos?: string[] }

export function usePendencias(jobId: string, versao: string) {
  const [d, setD] = useState<Simples | null>(null)
  const carregar = useCallback(() => { get<Simples>(`/jobs/${encodeURIComponent(jobId)}/pendencias-simples`).then(setD).catch(() => setD(null)) }, [jobId])
  useEffect(carregar, [carregar, versao])
  return { d, setD, carregar }
}

interface EstadoExt { instalada: boolean; atualizar: boolean; fixada: boolean | null; portais: boolean | null; atual: string }

/** 079-1: o card da extensão mostra UM caminho pelo estado real dela: ligar → "Abrir os N anúncios" (a extensão
 *  abre e envia sozinha) → "N de M recebidos"; no último, o servidor remonta o laudo sozinho. */
function CartaoExtensao({ c, jobId, aoMudar, umDeN }: { c: Cartao; jobId: string; aoMudar: (s?: Simples) => void; umDeN?: string }) {
  const [ext, setExt] = useState<EstadoExt | null>(null)
  const [cont, setCont] = useState<{ total: number; recebidos: number } | null>(null)
  const [abrindo, setAbrindo] = useState(false)
  const [msg, setMsg] = useState('')
  const [falha, setFalha] = useState('')
  const jid = encodeURIComponent(jobId)
  useEffect(() => {
    let vivo = true
    const ver = () => get<EstadoExt>('/extensao/estado').then((e) => { if (vivo) setExt(e) }).catch(() => undefined)
    void ver(); const t = setInterval(ver, 10_000)
    return () => { vivo = false; clearInterval(t) }
  }, [])
  useEffect(() => {
    let vivo = true
    const contar = () => get<{ total: number; recebidos: number }>(`/jobs/${jid}/extensao/anuncios`)
      .then((r) => { if (!vivo) return; setCont(r); if (r.total && r.recebidos >= r.total) aoMudar() }).catch(() => undefined)
    void contar(); const t = setInterval(contar, abrindo ? 3_000 : 15_000)
    return () => { vivo = false; clearInterval(t) }
  }, [jid, abrindo, aoMudar])
  useEffect(() => {
    const ouvir = (ev: MessageEvent) => {
      const d = ev.data as { jdb?: string; trabalho?: string; ok?: boolean; erro?: string }
      if (ev.origin !== location.origin || d?.jdb !== 'abrir-anuncios-resposta' || d.trabalho !== jobId) return
      if (d.ok) { setAbrindo(true); setFalha(''); setMsg('Abrindo os anúncios um de cada vez. A extensão envia cada um sozinha.') }
      else setFalha(d.erro === 'PORTAIS' ? 'permitir o JdB nos portais (toque na extensão)' : d.erro === 'RECARREGAR'
        ? 'recarregar a extensão em chrome://extensions (↻)' : (d.erro || 'ligar a extensão'))
    }
    window.addEventListener('message', ouvir)
    return () => window.removeEventListener('message', ouvir)
  }, [jobId])
  function abrir() {
    setMsg(''); setFalha('')
    window.postMessage({ jdb: 'abrir-anuncios', trabalho: jobId }, location.origin)
    setTimeout(() => setAbrindo((a) => { if (!a) setFalha((f) => f || 'ligar a extensão do JdB neste Chrome'); return a }), 2500)
  }
  const total = cont?.total ?? c.total ?? 0
  const recebidos = cont?.recebidos ?? c.recebidos ?? 0
  const falta: string[] = []
  if (ext && !ext.instalada && !document.documentElement.dataset.jdbExtensao) falta.push('ligar a extensão do JdB neste Chrome')
  if (ext?.atualizar) falta.push(`a versão nova da extensão (${ext.atual}): toque em ↻ no cartão dela em chrome://extensions`)
  if (ext?.portais === false) falta.push('permitir o JdB nos portais')
  if (falha) falta.push(falha)
  return (
    <div className="proximo-passo cartao-impede">
      {umDeN !== undefined && <span className="tag-jdb">Próximo passo{umDeN ? ` · ${umDeN}` : ''}</span>}
      <p className="titulo-cartao">{c.titulo}</p>
      {total > 0 && <p className="texto" role="status">{recebidos} de {total} recebidos.</p>}
      {falta.length > 0 ? (
        <>
          <p className="texto">Para trazer as fotos, falta: {[...new Set(falta)].join('; ')}.</p>
          <div className="botoes">
            <button type="button" className="btn-verde" onClick={() => { setFalha(''); abrir() }}>Ligar e tentar de novo</button>
          </div>
        </>
      ) : (
        <div className="botoes">
          <button type="button" className="btn-verde" disabled={abrindo} onClick={abrir}>
            {cont && cont.total - cont.recebidos > 0 ? `Abrir os ${cont.total - cont.recebidos} anúncios` : 'Abrir os anúncios'}</button>
          <button type="button" className="btn-sec-grande" onClick={() => void post<Simples>(`/jobs/${jid}/pendencias/aceitar`, { chave: c.chave }).then((s) => aoMudar(s))}>Seguir assim</button>
        </div>
      )}
      {msg && <p className="texto" role="status">{msg}</p>}
    </div>
  )
}

const GUARDADO = 'Guardado. O laudo é atualizado uma vez só, quando você terminar os passos.'

export function CartaoPendencia({ c, jobId, aoMudar, umDeN, adiar }: { c: Cartao; jobId: string; aoMudar: (s?: Simples) => void; umDeN?: string; adiar?: boolean }) {
  if (c.chave === 'extensao') return <CartaoExtensao c={c} jobId={jobId} aoMudar={aoMudar} umDeN={umDeN} />
  return <CartaoPadrao c={c} jobId={jobId} aoMudar={aoMudar} umDeN={umDeN} adiar={adiar} />
}

/** 079-4: a miniatura da capa no próprio card (toque amplia). */
function MiniCapa({ jobId }: { jobId: string }) {
  const [url, setUrl] = useState('')
  const [grande, setGrande] = useState(false)
  const [tentativa, setTentativa] = useState(0)
  const [falhou, setFalhou] = useState(false)
  useEffect(() => {
    let vivo = true; let u = ''
    baixarRaw(`/jobs/${encodeURIComponent(jobId)}/capa.png?t=${tentativa}`).then(({ blob }) => { if (!vivo) return; u = URL.createObjectURL(blob); setUrl(u); setFalhou(false) })
      .catch(() => { if (!vivo) return; if (tentativa < 3) setTimeout(() => setTentativa((n) => n + 1), 3000); else setFalhou(true) })   // 093-A-8
    return () => { vivo = false; if (u) URL.revokeObjectURL(u) }
  }, [jobId, tentativa])
  if (!url) return falhou
    ? <button type="button" className="btn-sec-grande" onClick={() => { setFalhou(false); setTentativa(0) }}>Ver a capa</button>
    : <p className="small-jdb" role="status">Abrindo a capa…</p>
  return (
    <button type="button" className="foco block" onClick={() => setGrande((g) => !g)} aria-label={grande ? 'Diminuir a capa' : 'Ampliar a capa'}>
      <img src={url} alt="Capa do laudo com o contorno do imóvel" style={{ maxWidth: grande ? '100%' : 260, borderRadius: 12 }} />
    </button>
  )
}

function PontoTexto({ pt }: { pt: { texto: string; trecho: string }; jid?: string; adiar?: boolean; aoMudar?: (m: string) => void }) {
  // 152: a correção é manual, no editável — o ponto mostra o que está errado, o trecho e o caminho até ele
  const [fechado, setFechado] = useState(false)
  return (
    <li>
      <p className="texto">{pt.texto}</p>
      {pt.trecho && <p className="small-jdb">No laudo está: «{pt.trecho}»</p>}
      {fechado ? <p className="small-jdb">Fica como está.</p> : (
        <p className="flex flex-wrap items-center gap-2">
          <span className="small-jdb">Corrija no Word, depois de baixar para a revisão humana (ache com Ctrl+F).</span>
          <button type="button" className="link-jdb" onClick={() => setFechado(true)}>deixar como está</button>
        </p>
      )}
    </li>
  )
}

function CartaoPadrao({ c, jobId, aoMudar, umDeN, adiar }: { c: Cartao; jobId: string; aoMudar: (s?: Simples) => void; umDeN?: string; adiar?: boolean }) {
  const ir = useStore((s) => s.ir)
  const [comparar, setComparar] = useState(false)
  const [aberto, setAberto] = useState(false)
  const [msg, setMsg] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const [pin, setPin] = useState(false)
  const [link, setLink] = useState('')
  const [idadeN, setIdadeN] = useState<number | null>(null)   // 111-3a: "Corrigir" a idade abre o campo aqui mesmo
  const [idade, setIdade] = useState('')
  const jid = encodeURIComponent(jobId)
  const comLista = !!c.erros?.length        // 128: o passo do texto com a lista numerada aberta
  async function salvarIdade() {
    if (idadeN === null || !idade.trim()) return
    setMsg(''); setOcupado(true)
    try {
      await put(`/jobs/${jid}/candidatos/${idadeN}/idade`, { idade: idade.trim() })
      setMsg('Idade corrigida.'); setIdadeN(null); aoMudar()
    } catch (e) { setMsg(e instanceof ApiError ? e.message : 'Não deu certo.') } finally { setOcupado(false) }
  }
  async function colarPin() {
    setMsg(''); setOcupado(true)
    try {
      await post(`/jobs/${jid}/pin`, { link: link.trim() })
      await post(`/jobs/${jid}/reabrir`, { etapa: 'montagem' })
      setMsg('Gerei a imagem pelo link. O laudo está sendo montado de novo com ela.'); setPin(false); aoMudar()
    } catch (e) { setMsg(e instanceof ApiError ? e.message : 'Não deu certo.') } finally { setOcupado(false) }
  }
  async function agir(o: Opcao) {
    setMsg(''); setOcupado(true)
    try {
      if (o.acao === 'aceitar') aoMudar(await post<Simples>(`/jobs/${jid}/pendencias/aceitar`, { chave: c.chave }))
      else if (o.acao === 'alinhamento') { await post(`/jobs/${jid}/alinhamento`, { id: o.id, resposta: o.resposta, texto: o.texto ?? '' }); aoMudar(await post<Simples>(`/jobs/${jid}/pendencias/aceitar`, { chave: c.chave })) }
      else if (o.acao === 'refazer_mapa') {               // 075-B / 088-2: responde na hora e diz o que aconteceu
        setMsg('Refazendo o mapa pelo pin… (leva até 1 minuto)')
        await post(`/jobs/${jid}/mapa/refazer`)
        await post(`/jobs/${jid}/remontar`, { etapa: 'montagem', adiar: !!adiar, motivo: 'mapa refeito pelo pin' })
        setMsg(adiar ? 'Mapa refeito. ' + GUARDADO : 'Mapa refeito pelo pin. O laudo está sendo montado de novo com ele.')
        aoMudar(await post<Simples>(`/jobs/${jid}/pendencias/aceitar`, { chave: c.chave }))
      }
      else if (o.acao === 'adicionar_comparacao') setComparar(true)   // 083-B5: o formulário já marcado "Só comparação"
      else if (o.acao === 'desfazer_reforco') {         // 101-1 (d)
        await post(`/jobs/${jid}/reforco/desfazer`, {}); setMsg('Desfeito: o texto volta sem o reforço. O laudo está sendo refeito.'); aoMudar()
      }
      else if (o.acao === 'usar_media') {               // 082-4: o valor volta a sair da média
        await post(`/jobs/${jid}/unitario/media`, {}); setMsg('Combinado: o valor sai da média da amostra. O laudo está sendo recalculado.'); aoMudar()
      }
      else if (o.acao === 'confirmar_valor') ir('detalhes', jobId)
      else if (o.acao === 'divergencia') {              // 082-2: dado da página × o guardado
        await post(`/jobs/${jid}/candidatos/${o.n}/divergencia`, { campo: o.campo ?? '', manter: !!o.manter })
        setMsg(o.manter ? 'Combinado: fica o que o laudo já usa.' : 'Trocado. Confira o valor novo antes de remontar.'); aoMudar()
      }
      else if (o.acao === 'trocar_foto') {              // 081-5: a foto principal era arte de anúncio
        await post(`/jobs/${jid}/candidatos/${o.n}/trocar-foto`, { url: o.url ?? '', manter: !!o.manter, adiar: !!adiar, sugerida: !!o.sugerida })
        setMsg(o.manter ? 'Combinado: fica a foto que estava.' : 'Foto trocada. O laudo está sendo montado de novo com ela.'); aoMudar()
      }
      else if (o.acao === 'pin') setPin(true)
      else if (o.acao === 'corrigir_idade' && o.n !== undefined) { setIdade(''); setIdadeN(o.n) }
      else if (o.acao === 'mapa_digital') {             // 077-1: print do Mapa Digital Fácil gerado sozinho, e o laudo remontado
        await post(`/jobs/${jid}/mapa-digital`)
        await post(`/jobs/${jid}/reabrir`, { etapa: 'montagem' })
        setMsg('Gerei o print do Mapa Digital Fácil. O laudo está sendo montado de novo com ele.'); aoMudar()
      }
      else if (o.acao === 'reabrir') {                  // 086-2: com outros passos abertos, guarda e segue para o próximo
        await post(`/jobs/${jid}/remontar`, { etapa: o.etapa ?? 'calculo', adiar: !!adiar, motivo: c.titulo.slice(0, 190) })
        if (adiar) { setMsg(GUARDADO); aoMudar(await post<Simples>(`/jobs/${jid}/pendencias/aceitar`, { chave: c.chave })) }
        else setMsg('Recalculando. O laudo novo aparece aqui quando ficar pronto.')
      }
      else if (o.acao === 'candidatos' || o.acao === 'ver_mapa' || o.acao === 'editar_campo') ir('job', jobId)
      else if (o.acao === 'ver_capa') ir('detalhes', jobId)          // 077-2: marcar outra foto da capa
      else if (o.acao === 'extensao') setMsg('Abra o anúncio no seu Chrome. Vai aparecer o botão Enviar ao JdB no canto da página.')
      else if (o.acao === 'detalhe' && c.erros?.length)          // 120: "Ver a lista" leva à lista numerada
        document.getElementById(`lista-${c.chave}`)?.scrollIntoView({ block: 'start', behavior: 'smooth' })
      else setAberto(true)
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : 'Não deu certo.')
    } finally { setOcupado(false) }
  }
  async function enviarFoto(f?: File) {
    if (!f) return
    const fd = new FormData(); fd.append('tipo', 'foto'); fd.append('arquivos', f)
    try { await postForm(`/jobs/${jid}/arquivos`, fd); setMsg('Print enviado. Atualize o laudo.') } catch (e) { setMsg(e instanceof ApiError ? e.message : 'Não deu certo.') }
  }
  /** ORDEM 047: envia o documento que falta e refaz o laudo a partir da etapa certa. */
  async function enviarArquivos(o: Opcao, fs?: FileList | null) {
    if (!fs || !fs.length) return
    setOcupado(true); setMsg('')
    try {
      const fd = new FormData(); fd.append('tipo', o.tipo ?? 'documento')
      for (const f of Array.from(fs)) fd.append('arquivos', f)
      await postForm(`/jobs/${jid}/arquivos`, fd)
      await post(`/jobs/${jid}/remontar`, { etapa: o.refazer ?? 'extracao', adiar: !!adiar, motivo: 'documento enviado pelo avaliador' })
      if (adiar) { setMsg(GUARDADO); aoMudar(await post<Simples>(`/jobs/${jid}/pendencias/aceitar`, { chave: c.chave })) }
      else { setMsg('Documento recebido. O JdB está refazendo o laudo.'); aoMudar() }
    } catch (e) { setMsg(e instanceof ApiError ? e.message : 'Não deu certo.') } finally { setOcupado(false) }
  }
  return (
    <div className={`proximo-passo ${c.impede ? 'cartao-impede' : ''}`}>
      {umDeN !== undefined && <span className="tag-jdb">Próximo passo{umDeN ? ` · ${umDeN}` : ''}</span>}
      <p className="titulo-cartao">{c.titulo}</p>
      {c.chave === 'capa' && <MiniCapa jobId={jobId} />}
      {c.erros && c.erros.length > 0 && (                    // 119-1 / 120: lista numerada, o campo já aberto em cada erro
        <div id={`lista-${c.chave}`}>
          <ListaErros jobId={jobId} erros={c.erros} aoMudar={(m) => { setMsg(m); aoMudar() }}
                      aoConferir={async () => {            // 143: conferido → o mesmo "seguir" do cartão → revisão humana
                        const o = c.opcoes.find((x) => x.acao === 'aceitar')
                        if (o) await agir(o)
                      }} />
        </div>
      )}
      {!c.erros?.length && c.pontos && c.pontos.length > 0 && (   // 089-4: o trecho exato e "Me diga como corrigir"
        <ol className="lista-simples">
          {c.pontos.map((pt) => <PontoTexto key={pt.texto} pt={pt} jid={jid} adiar={!!adiar} aoMudar={(m) => { setMsg(m); aoMudar() }} />)}
        </ol>
      )}
      {(comparar || c.chave === 'comparacao_d069') && (   // 097-1: o formulário já aberto no passo; ao incluir, remonta
        <AdicionarReferencial jobId={jobId} comparacao rotulo="Colar o link do anúncio de comparação" aoMudar={(m) => {
          setMsg(m)
          void post(`/jobs/${jid}/remontar`, { etapa: 'montagem', adiar: !!adiar, motivo: 'anúncio de comparação incluído' })
            .then(() => aoMudar()).catch(() => aoMudar())
        }} />
      )}
      {c.galeria ? (                                  // 088-1: a galeria inteira; a sugerida vem marcada, a escolha é do avaliador
        <div className="flex flex-wrap gap-2">
          {c.galeria.fotos.map((u, i) => (
            <button key={u} type="button" disabled={ocupado} className="foco" aria-label={`Usar a foto ${i + 2} do anúncio`}
                    style={{ outline: i === 0 ? '3px solid var(--verde, #2e7d32)' : undefined, borderRadius: 8 }}
                    onClick={() => void agir({ rotulo: 'Usar', acao: 'trocar_foto', n: c.galeria!.n, url: u })}>
              <img src={u} alt={`Foto ${i + 2} do anúncio${i === 0 ? ' (sugerida)' : ''}`} referrerPolicy="no-referrer"
                   style={{ width: 150, height: 112, objectFit: 'cover', borderRadius: 8 }} />
            </button>
          ))}
        </div>
      ) : c.imagem && <img src={c.imagem} alt="A outra foto do anúncio" referrerPolicy="no-referrer" style={{ maxWidth: 260, borderRadius: 12 }} />}
      {comLista ? null   // 147: com a lista, o único caminho é o [✓ Todos os pontos conferidos] do rodapé (saíram os dois links)
        : <div className="botoes">
        {c.opcoes.filter((o) => o.acao !== 'adicionar_comparacao').map((o) => o.acao === 'enviar_arquivo' ? (
          <label key={o.rotulo} className={o.recomendada ? 'btn-verde' : 'btn-sec-grande'}>{o.rotulo}
            <input type="file" multiple accept="application/pdf,image/*,.doc,.docx" hidden onChange={(e) => void enviarArquivos(o, e.target.files)} /></label>
        ) : o.acao === 'enviar_foto' ? (
          <label key={o.rotulo} className={o.recomendada ? 'btn-verde' : 'btn-sec-grande'}>{o.rotulo}
            <input type="file" accept="image/*" hidden onChange={(e) => void enviarFoto(e.target.files?.[0])} /></label>
        ) : (
          <button key={o.rotulo} type="button" disabled={ocupado} className={o.recomendada ? 'btn-verde' : 'btn-sec-grande'} onClick={() => void agir(o)}>{o.rotulo}</button>
        ))}
      </div>}
      {!comLista && c.opcoes.map((o) => o.linha && <p key={`l-${o.rotulo}`} className="small-jdb">{o.linha}</p>)}
      {pin && (
        <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (link.trim()) void colarPin() }}>
          <label className="sr-only" htmlFor={`pin-${c.chave}`}>Link do Google Maps do imóvel</label>
          <input id={`pin-${c.chave}`} className="campo-grande flex-1" placeholder="Cole o link do Google Maps do imóvel" value={link}
                 onChange={(e) => setLink(e.target.value)} autoFocus />
          <button type="submit" className="btn-verde" style={{ width: 'auto' }} disabled={ocupado || !link.trim()}>Gerar</button>
        </form>
      )}
      {idadeN !== null && (
        <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); void salvarIdade() }}>
          <label className="sr-only" htmlFor={`idade-${c.chave}`}>Idade aparente do anúncio</label>
          <input id={`idade-${c.chave}`} className="campo-grande flex-1" placeholder="Ex.: 30 anos, novo" value={idade}
                 onChange={(e) => setIdade(e.target.value)} autoFocus />
          <button type="submit" className="btn-verde" style={{ width: 'auto' }} disabled={ocupado || !idade.trim()}>Salvar</button>
        </form>
      )}
      {ocupado && msg.startsWith('Refazendo o mapa') && <Espera voar={false} />}{/* 123-3 */}
      {msg && <p className="texto" role="status">{msg}</p>}
      {!comLista && <details className="detalhes" open={aberto}>{/* 128: com a lista aberta, o "Ver detalhes" só repetiria */}
        <summary>Ver detalhes{c.pagina ? ` · página ${c.pagina}` : ''}</summary>
        <p className="texto detalhes-corpo">{c.detalhe.split(/(https?:\/\/\S+)/).map((x, i) => /^https?:\/\//.test(x)
          ? <a key={i} href={x} target="_blank" rel="noopener noreferrer" className="link-jdb">{x}</a> : x)}</p>
      </details>}
    </div>
  )
}

export default function PendenciasSimples({ jobId, versao }: { jobId: string; versao: string }) {
  const { d, setD, carregar } = usePendencias(jobId, versao)
  const [corrigindo, setCorrigindo] = useState(false)
  async function corrigir() {
    setCorrigindo(true)
    try { setD(await post<Simples>(`/jobs/${encodeURIComponent(jobId)}/corrigir-sozinho`)) } catch { carregar() } finally { setCorrigindo(false) }
  }
  if (!d) return null
  return (
    <section className="tela-simples" aria-labelledby="pend-titulo">
      <h2 id="pend-titulo" className={d.cards.some((c) => c.impede) ? 'contador-impede' : 'contador'}>{d.resumo}</h2>
      {d.linha_sozinho && (
        <p className="linha-discreta">{corrigindo ? 'Corrigindo sozinho…' : d.linha_sozinho}
          {!corrigindo && <button type="button" className="link-discreto" onClick={() => void corrigir()}>Corrigir agora</button>}</p>
      )}
      {d.cards.map((c) => <CartaoPendencia key={c.chave} c={c} jobId={jobId} aoMudar={(s) => (s ? setD(s) : carregar())} />)}
    </section>
  )
}
