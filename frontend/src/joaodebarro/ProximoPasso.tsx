/* ORDEM 047 / D-101: o PRÓXIMO PASSO da tela do trabalho. Um cartão só, com a faixa à esquerda e
 * botões grandes; várias decisões → uma de cada vez ("1 de 3"). Erro do sistema não aparece aqui
 * (D-100). Downloads só depois do "Aprovar". */
import Espera from './Espera'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Check } from 'lucide-react'
import { ApiError, baixarRaw, get, post } from './api'
import { useStore } from './store'
import { CartaoPendencia, usePendencias } from './PendenciasSimples'
import { canalEditor } from './EditorLaudo'
import { BaixarRevisao } from './Downloads'
import TelaFinal from './TelaFinal'
import type { Detalhe, ResultadoEntrega } from './tipos'


function Cartao({ titulo, linha, children }: { titulo: string; linha?: string; children?: React.ReactNode }) {
  return (
    <section className="proximo-passo" aria-labelledby="proximo-titulo">
      <span className="tag-jdb">Próximo passo</span>
      <h2 id="proximo-titulo" className="titulo-cartao">{titulo}</h2>
      {linha && <p className="texto">{linha}</p>}
      {children}
    </section>
  )
}

/** Nomes dos passos na L8 (linguagem de gente; sem nome de etapa interna). */
const PASSO_L8: Record<string, string> = {
  triagem: 'Lendo os documentos', extracao: 'Conferindo os dados e as áreas', pesquisa: 'Mapa e anúncios que você trouxe',   // 075-A: sem pesquisa automática
  selecao: 'Escolhendo os anúncios', calculo: 'Calculando', redacao: 'Escrevendo', montagem: 'Montando o PDF',
  revisao: 'Revisão do sistema',     // 125-1: o JdB confere sozinho; depois vem a "Revisão humana — sua vez"
}

export default function ProximoPasso({ detalhe, rodando, etapaRodando, etapaId, linhas, imovel, livre, aoMudar, abrirDetalhes, corrigirData, agora: fazendo }: {
  detalhe: Detalhe
  rodando: boolean
  etapaRodando?: string
  etapaId?: string
  linhas?: { id: string; rotulo: string; estado: string }[]
  imovel?: string
  livre: boolean
  aoMudar: (msg: string) => void
  abrirDetalhes: (caixa: string) => void
  corrigirData: () => void
  agora?: string            // 073-2: o que a etapa está fazendo agora ("Procurando no ZAP… bloqueado")
}) {
  const { job } = detalhe
  const jid = encodeURIComponent(job.id)
  const tela = detalhe.tela
  const entrega = (detalhe.etapas.entrega ?? null) as ResultadoEntrega | null
  const final = !!entrega && !rodando && job.status !== 'AGUARDANDO_AVALIADOR'
  const { d: pend, setD, carregar } = usePendencias(job.id, job.atualizado)
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState('')
  const [nPontos, setNPontos] = useState(0)          // 178: pontos da revisão do sistema (para a tela final)
  // "1 de 3": o total do começo desta visita à tela; a posição avança a cada resposta
  const total = useRef(0)
  const vistos = useRef<Set<string>>(new Set())        // 111-3c: passos já mostrados e os já resolvidos
  const resolvidos = useRef<Set<string>>(new Set())
  const [qual, setQual] = useState('')        // 084-4: o avaliador escolhe qual responder
  // 086-2: respostas guardadas esperando o "Respondi tudo: atualizar o laudo"
  const [guardadas, setGuardadas] = useState<string[]>([])
  useEffect(() => {
    let vivo = true
    get<{ pendente: { esperar?: boolean; motivos?: string[] } | null }>(`/jobs/${encodeURIComponent(job.id)}/remontar`)
      .then((r) => { if (vivo) setGuardadas(r.pendente?.esperar ? (r.pendente.motivos ?? ['resposta']) : []) }).catch(() => undefined)
    return () => { vivo = false }
  }, [job.id, job.atualizado, pend])
  // 089-1: dado corrigido (anúncio, foto, área) também é resposta guardada — conta e entra no mesmo "Respondi tudo"
  const nGuardadas = guardadas.length + (detalhe.dados_alterados ? 1 : 0)
  const botaoAtualizar = nGuardadas > 0 && (
    <div className="botoes">
      <button type="button" className="btn-verde" disabled={ocupado}
              onClick={() => void agir(() => detalhe.dados_alterados
                ? post(`/jobs/${encodeURIComponent(job.id)}/remontar`, { etapa: 'calculo', adiar: false, motivo: 'dados novos do avaliador', so_numeros: true })
                : post(`/jobs/${encodeURIComponent(job.id)}/atualizar`, {}), 'Atualizando o laudo com as suas respostas.').then(() => setGuardadas([]))}>
        Respondi tudo: atualizar o laudo</button>
      <span className="small-jdb">{nGuardadas === 1 ? '1 resposta guardada' : `${nGuardadas} respostas guardadas`}</span>
      {detalhe.dados_alterados && (       // 159-1: avisa antes o que vai refazer
        <p className="small-jdb">Com o dado corrigido, refaço só a conta, a planilha, a tabela e os números do texto (área, valor e
          unitário, também por extenso). A IA não reescreve o laudo.</p>
      )}
    </div>
  )
  // 111-3c: "N de T" = resolvidos + 1 de (resolvidos + os que faltam, contando os escondidos em "Mais N pontos")
  const cardsAgora = final ? pend?.cards ?? [] : []
  if (final && pend) {
    const agora = new Set(cardsAgora.map((c) => c.chave))
    vistos.current.forEach((k) => { if (!agora.has(k)) resolvidos.current.add(k) })
    agora.forEach((k) => { vistos.current.add(k); resolvidos.current.delete(k) })
  }
  const mais = cardsAgora.find((c) => c.chave === 'mais')
  const escondidos = mais ? Number(/Mais (\d+)/.exec(mais.titulo)?.[1] ?? 0) : 0
  const feitos = [...resolvidos.current].filter((k) => k !== 'mais').length
  total.current = feitos + cardsAgora.filter((c) => c.chave !== 'mais').length + escondidos
  useEffect(() => { total.current = 0; vistos.current = new Set(); resolvidos.current = new Set() }, [job.id])

  async function agir(fn: () => Promise<unknown>, msg: string) {
    setErro(''); setOcupado(true)
    try { await fn(); aoMudar(msg) } catch (e) { setErro(e instanceof ApiError ? e.message : 'Não deu certo. Tente de novo.') } finally { setOcupado(false) }
  }
  const erroTxt = erro && <p className="aviso-impede" role="alert">{erro}</p>
  async function abrirPrevia() {
    try {
      const { blob } = await baixarRaw(`/jobs/${jid}/pdf-previa`)
      window.open(URL.createObjectURL(blob), '_blank', 'noopener')
    } catch (e) { setErro(e instanceof ApiError ? e.message : 'Ainda não deu para abrir o PDF.') }
  }

  // 1. data das fotos × vistoria ainda sem confirmação
  if (detalhe.alerta_datas && !detalhe.alerta_datas.startsWith('CONFIRMADA: ') && livre) {
    return (
      <Cartao titulo="A data das fotos não bate com a vistoria." linha="Confira a data antes de seguir.">
        <div className="botoes">
          <button type="button" className="btn-verde" disabled={ocupado}
                  onClick={() => void agir(() => post(`/jobs/${jid}/datas/confirmar`, {}), 'Data da vistoria confirmada.')}>A data está certa</button>
          <button type="button" className="btn-sec-grande" onClick={corrigirData}>Corrigir a data</button>
        </div>
        <details className="detalhes"><summary>Ver detalhes</summary><p className="texto detalhes-corpo">{detalhe.alerta_datas}</p></details>
        {erroTxt}
      </Cartao>
    )
  }
  // 2. o sistema está trabalhando
  if (rodando) {
    // ORDEM 053 (L8): "Estou montando o seu laudo" com a lista dos passos
    const todas = (linhas ?? []).filter((l) => PASSO_L8[l.id])
    // 129-3: numa correção (laudo já entregue antes), mostra só as etapas que vão rodar — as de antes não são refeitas
    const correcao = (tela?.revisao ?? 0) > 0
    const ini = correcao ? Math.max(0, todas.findIndex((l) => l.estado !== 'concluida')) : 0
    const visiveis = correcao ? todas.slice(ini) : todas
    return (
      <section className="proximo-passo montando" aria-labelledby="montando-titulo">
        <div className="montando-topo">
          {/* 118-3 / ORDEM 123: a animação do designer, o arquivo da etapa atual (ninho crescendo) */}
          <Espera etapa={etapaRodando || etapaId} desde={job.atualizado} />
          <div><h2 id="montando-titulo" className="titulo-cartao">{correcao ? 'Corrigindo os seus pontos' : 'Estou montando o seu laudo'}</h2>
            {correcao && <p className="texto">Só refaço o que você pediu.</p>}{/* 131: sem previsão de tempo */}
            {imovel && <p className="sub-jdb">{imovel}</p>}</div>
        </div>
        {tela?.por_que && <p className="aviso-simples" role="status">{tela.por_que}</p>}   {/* 111-3d */}
        {(etapaId === 'revisao' || etapaRodando === 'revisao') && (    // 093-7: o PDF já existe; a revisão continua
          <div className="botoes">
            {/* 125-1: o sistema ainda confere — nada de "PDF pronto"; a prévia é só um link discreto */}
            <span className="texto font-semibold">Laudo montado. Estou conferindo antes de te mostrar.</span>
            <button type="button" className="link-jdb" onClick={() => void abrirPrevia()}>ver a prévia — ainda pode mudar</button>
          </div>
        )}
        {visiveis.length > 0 ? (
          <ol className="passos-l8">
            {visiveis.map((l) => {
              const feito = l.estado === 'concluida'
              const agora = !feito && (l.estado === 'rodando' || l.id === etapaId)
              return (
                <li key={l.id} className={feito ? 'feito' : agora ? 'agora' : ''} aria-current={agora ? 'step' : undefined}>
                  <span className="marca-passo" aria-hidden="true">{feito ? <Check size={18} /> : agora ? '…' : ''}</span>
                  {PASSO_L8[l.id]}
                  {agora && fazendo && <span className="small-jdb block">{fazendo}</span>}
                </li>
              )
            })}
          </ol>
        ) : <p className="texto">{etapaRodando ? `Agora: ${etapaRodando}.` : ''}</p>}
        {visiveis.length > 0 && (
          <p className="small-jdb">Depois: <b>Revisão humana — sua vez</b> (você abre o PDF e aprova).</p>
        )}
        <p className="pode-fechar"><b>Pode fechar o app.</b> Eu aviso quando precisar de você.</p>
      </section>
    )
  }
  // 3. decisões da pesquisa e do valor
  if (job.status === 'AGUARDANDO_AVALIADOR' && job.etapa === 'pesquisa') {
    return (
      <Cartao titulo="Escolha os referenciais do laudo." linha="Marque os anúncios parecidos com o imóvel.">
        <div className="botoes"><button type="button" className="btn-verde" onClick={() => useStore.getState().ir('alinhamento', job.id)}>Escolher os anúncios</button></div>
      </Cartao>
    )
  }
  if (job.status === 'AGUARDANDO_AVALIADOR') {
    return (
      <Cartao titulo="Confirme o valor do laudo." linha="Referenciais, unitário, faixa e área.">
        <div className="botoes"><button type="button" className="btn-verde" onClick={() => abrirDetalhes('confirmar')}>Confirmar o valor</button></div>
      </Cartao>
    )
  }
  if (!final) return null
  // 4. concluído ✓ (178: a tela final; a assinatura saiu do sistema — o avaliador assina o PDF por fora)
  if (tela?.assinado || tela?.aprovado) {
    return (
      <div className="grid gap-3">
        <TelaFinal job={job} temPontos={nPontos > 0} fotosNovas={tela?.fotos_novas ?? 0} verFotos={() => abrirDetalhes('imagens')} verPontos={() => {
          const el = document.getElementById('jdb-pontos')
          if (el) { (el as HTMLDetailsElement).open = true; el.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
        }} />
        <PontosDepoisDoDownload jobId={job.id} aoContar={setNPontos} />
      </div>
    )
  }
  // 5. dados mudaram depois da entrega: atualizar chama a IA de novo → vira o próximo passo
  if (detalhe.dados_alterados && !(final && pend && pend.cards.length)) {    // 089-1: com passo aberto, os passos continuam
    return (
      <Cartao titulo="Atualize o laudo com os dados novos." linha="O PDF ainda é o anterior. Leva alguns minutos.">
        <div className="botoes">
          <button type="button" className="btn-verde" disabled={ocupado}
                  onClick={() => void agir(() => post(`/jobs/${jid}/reabrir`, { etapa: 'calculo' }), 'Atualizando o laudo.')}>Atualizar</button>
        </div>
        {erroTxt}
      </Cartao>
    )
  }
  // 187: fotos que chegaram depois do laudo pronto — nenhum botão manda a IA refazer o laudo; elas vão para o Word
  // (o antigo [Refazer o laudo com as fotos] — reabrir na extração — ficou guardado no servidor, sem botão)
  if (final && (tela?.fotos_novas ?? 0) > 0 && !(tela?.aprovado || tela?.assinado)) {
    return (
      <Cartao titulo="Chegaram fotos novas.">
        <p className="texto">Coloque no Word quando baixar para a revisão humana; elas ficam em Detalhes › Imagens do laudo.</p>
        <BaixarRevisao jobId={job.id} aoConcluir={() => { window.location.reload() }} />
        <div className="botoes">
          <button type="button" className="btn-sec-grande" onClick={() => abrirDetalhes('imagens')}>Ver as fotos novas</button>
        </div>
      </Cartao>
    )
  }
  // 6. decisões do avaliador, uma de cada vez
  if (pend && pend.cards.length) {
    const pos = Math.min(feitos + 1, Math.max(1, total.current))
    const atual = pend.cards.find((c) => c.chave === qual) ?? pend.cards[0]
    return (
      <>
        {/* 074-E2: como o João fala — "Revisei o laudo. Faltam 3 coisas que dependem de você." */}
        {pend.resumo && <p className="texto font-semibold" role="status">{pend.resumo}</p>}
        {botaoAtualizar}
        <CartaoPendencia key={atual.chave} c={atual} jobId={job.id} adiar={pend.cards.length > 1}
                         umDeN={total.current > 1 ? `${pos} de ${total.current}` : ''}
                         aoMudar={(s) => { setQual(''); if (s) setD(s); else carregar(); aoMudar('') }} />   {/* 096-9: recarrega o trabalho */}
        {pend.cards.length > 1 && (
          <details className="detalhes detalhes-jdb detalhes-esq" open>
            <summary>Todas as {pend.cards.length} coisas que dependem de você</summary>
            <ol className="lista-simples">
              {pend.cards.map((c) => (
                <li key={c.chave}>
                  <button type="button" className="link-jdb text-left" aria-current={c.chave === atual.chave}
                          onClick={() => setQual(c.chave)}>{c.chave === atual.chave ? <b>{c.titulo}</b> : c.titulo}</button>
                </li>
              ))}
            </ol>
          </details>
        )}
        {pend.avisos && pend.avisos.length > 0 && (
          <details className="detalhes detalhes-jdb detalhes-esq">
            <summary>Avisos que não mudam o laudo ({pend.avisos.length})</summary>
            <ul className="lista-simples">{pend.avisos.map((x) => <li key={x}>{x}</li>)}</ul>
          </details>
        )}
      </>
    )
  }
  if (botaoAtualizar) {                      // 086-2: tudo respondido; falta aplicar de uma vez
    return <Cartao titulo="Você respondeu os passos." linha="O JdB aplica tudo de uma vez, numa montagem só.">{botaoAtualizar}{erroTxt}</Cartao>
  }
  if (!pend) return null
  if (job.status === 'BLOQUEADO') {
    return (
      <Cartao titulo="O laudo parou: falta uma informação.">
        <div className="botoes"><button type="button" className="btn-verde" onClick={() => abrirDetalhes('entrega')}>Ver o que falta</button></div>
      </Cartao>
    )
  }
  // 7. nada pendente: revisar e aprovar (L3 do desenho: Abrir o PDF → L10; Aprovar laudo)
  return (
    <SuaVez jobId={job.id} ocupado={ocupado} erroTxt={erroTxt}
            aprovar={() => void agir(() => post(`/jobs/${jid}/aprovar`, {}), 'Laudo aprovado.')} />
  )
}

/** 125-1: o sistema terminou — "Agora é com você." Um título, uma linha, um botão (teste dos 2 segundos, D-101).
 *  152: três botões — [Começar a revisão humana] · [Abrir o PDF] · [✓ Aprovar]. O pássaro fica pousado (sem movimento). */
function SuaVez({ jobId, erroTxt }: { jobId: string; ocupado?: boolean; erroTxt: ReactNode; aprovar?: () => void }) {
  const [abriu, setAbriu] = useState(() => { try { return sessionStorage.getItem(`pdf-aberto:${jobId}`) === '1' } catch { return false } })
  function abrir() {
    try { sessionStorage.setItem(`pdf-aberto:${jobId}`, '1') } catch { /* sem armazenamento: segue */ }
    setAbriu(true)
    useStore.getState().ir('laudo', jobId)
  }
  // 150-2 (143-6): na revisão humana o avaliador também corrige no editável. O [✓ Todos os pontos conferidos] da aba
  // manda {tipo:'usar'}: aqui o PDF é gerado do documento editado, confere por regra (sem IA) e a tela volta para a
  // revisão com o PDF novo (o "Abrir o PDF e revisar" reaparece). Só uma aba do JdB faz isso (trava do navegador).
  const [msgEd, setMsgEd] = useState('')
  const [ocupadoEd, setOcupadoEd] = useState(false)
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return undefined
    const c = new BroadcastChannel(canalEditor(jobId))
    const avisar = (m: object) => { try { const k = new BroadcastChannel(canalEditor(jobId)); k.postMessage(m); k.close() } catch { /* sem canal */ } }
    async function usarAqui() {
      setOcupadoEd(true); setMsgEd('')
      try {
        const r = await post<{ diferencas?: unknown[]; bloqueia?: number; bloqueia_texto?: string }>(`/jobs/${encodeURIComponent(jobId)}/editavel/usar`, {})
        const n = (r.diferencas ?? []).length
        avisar({ tipo: 'usado', ok: true, texto: r.bloqueia_texto || 'PDF novo pronto.', diferencas: n, bloqueia: r.bloqueia ?? 0, sem_mudanca: false })
        if ((r.bloqueia ?? 0) > 0) { setMsgEd(r.bloqueia_texto || 'A conferência achou um número diferente da planilha.'); return }
        try { sessionStorage.removeItem(`pdf-aberto:${jobId}`) } catch { /* sem armazenamento */ }
        setAbriu(false)
        setMsgEd(n ? `PDF novo pronto. A conferência achou ${n} ${n === 1 ? 'ponto' : 'pontos'} para você ver no PDF.` : 'PDF novo pronto, com as suas mudanças. Abra e revise.')
        avisar({ tipo: 'revisao_humana' })
      } catch (e) {
        const t = e instanceof ApiError ? e.message : 'Não consegui gerar o PDF do documento.'
        const sem = e instanceof ApiError && e.status === 409 && /não mudou nada/.test(t)
        avisar({ tipo: 'usado', ok: false, texto: t, diferencas: 0, bloqueia: 0, sem_mudanca: sem })
        if (sem) avisar({ tipo: 'revisao_humana' })
        setMsgEd(sem ? 'O documento não mudou: o PDF continua o mesmo.' : t)
      } finally { setOcupadoEd(false) }
    }
    c.onmessage = (ev) => {
      const m0 = ev.data as { tipo?: string; texto?: string } | null
      if (m0?.tipo === 'concluido') {       // 151-5: a revisão humana foi concluída na aba — o PDF final está pronto
        try { sessionStorage.removeItem(`pdf-aberto:${jobId}`) } catch { /* sem armazenamento */ }
        setAbriu(false); setMsgEd(m0.texto || 'Revisão humana concluída: PDF final pronto. Abra o PDF e aprove.')
        return
      }
      if (m0?.tipo !== 'usar') return
      const nav = navigator as Navigator & { locks?: { request: (n: string, o: object, f: (l: unknown) => Promise<void>) => Promise<void> } }
      if (nav.locks) void nav.locks.request(`jdb-usar-${jobId}`, { ifAvailable: true }, async (l) => { if (l) await usarAqui() })
      else void usarAqui()
    }
    return () => c.close()
  }, [jobId])
  return (
    <section className="proximo-passo sua-vez" aria-labelledby="sua-vez-titulo" style={{ borderLeftColor: '#14803F' }}>
      <div className="flex flex-wrap items-center gap-4">
        <img src={`${import.meta.env.BASE_URL}jdb-marca/jdb-parado-claro.svg`} alt="" aria-hidden="true" style={{ width: 96, height: 96 }} />
        <div>
          <h2 id="sua-vez-titulo" className="titulo-cartao" style={{ fontSize: 32 }}>Agora é com você.</h2>
          <p className="texto">Estou esperando a sua revisão para aprovar e enviar para assinatura.</p>
        </div>
      </div>
      <ol className="passos-l8" aria-label="Etapas">
        <li className="feito"><span className="marca-passo" aria-hidden="true">✓</span>Revisão do sistema</li>
        <li className="agora" aria-current="step"><span className="marca-passo" aria-hidden="true">→</span><b>Revisão humana — sua vez</b></li>
      </ol>
      {/* 172-2: o download para a revisão humana conclui; a revisão final é no Word do avaliador */}
      <div className="botoes">
        <BaixarRevisao jobId={jobId} compacto aoConcluir={() => { window.location.reload() }} />
        <button type="button" className="btn-sec-grande" onClick={abrir}>{abriu ? 'Abrir o PDF de novo' : 'Abrir o PDF'}</button>
      </div>
      <p className="small-jdb">Ao baixar, o laudo fica concluído ✓: abra o Word no seu computador ou no Google Drive, faça as últimas
        mudanças e gere o PDF final de lá.</p>
      {ocupadoEd && <p className="texto" role="status">Gerando o PDF do documento editado e conferindo…</p>}
      {msgEd && <p className="aviso-simples" role="status">{msgEd}</p>}
      {erroTxt}
    </section>
  )
}

/** 172-2: depois do download, os pontos da revisão do sistema continuam à vista, com a frase para o Ctrl+F no Word. */
function PontosDepoisDoDownload({ jobId, aoContar }: { jobId: string; aoContar?: (n: number) => void }) {
  const [erros, setErros] = useState<{ n: number; titulo: string; frase?: string; pagina: number | null }[]>([])
  const [copiado, setCopiado] = useState(0)
  useEffect(() => {
    get<{ cards: { erros?: { n: number; titulo: string; frase?: string; pagina: number | null }[] }[] }>(
      `/jobs/${encodeURIComponent(jobId)}/pendencias-simples`)
      .then((r) => { const e = r.cards.flatMap((c) => c.erros ?? []); setErros(e); aoContar?.(e.length) }).catch(() => undefined)
  }, [jobId])   // eslint-disable-line react-hooks/exhaustive-deps
  if (!erros.length) return null
  return (
    <details id="jdb-pontos" className="detalhes detalhes-jdb detalhes-esq" open>
      <summary>Pontos da revisão do sistema ({erros.length}) — para achar no Word com Ctrl+F</summary>
      <ol className="lista-simples">
        {erros.map((e) => (
          <li key={e.n} className="grid gap-1">
            <span><b>{e.n}.</b> {e.titulo}{e.pagina ? ` (pág. ${e.pagina})` : ''}</span>
            {e.frase && (
              <span className="flex flex-wrap items-center gap-2">
                <span>Procure: <b>«{e.frase}»</b></span>
                <button type="button" className="btn-sec btn-peq" onClick={() => {
                  void navigator.clipboard.writeText(e.frase!).then(() => setCopiado(e.n)).catch(() => setCopiado(-1)) }}>Copiar a frase</button>
                {copiado === e.n && <span className="small-jdb">Copiado.</span>}
              </span>
            )}
          </li>
        ))}
      </ol>
    </details>
  )
}
