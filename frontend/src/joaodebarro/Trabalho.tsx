import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ArrowLeft } from 'lucide-react'
import { ApiError, get, post } from './api'
import { ZonasArquivos, ehAuth, mensagemErro, useEnvio } from './Envio'
import { BotoesReabrir, Cancelado, EditarTrabalho, EnviarTipo, ErroTecnico, GerirTrabalho, useAvisoFim } from './Acoes'
import type { Tipo } from './Envio'
import Entrega from './Entrega'
import { estadoDasEtapas } from './etapas'
import { Avisos, Calculo, CandidatosConteudo } from './Paineis'
import LinksBusca from './LinksBusca'
import PerguntaAprender, { type CorrecaoAprender } from './Aprender'
import ProximoPasso from './ProximoPasso'
import Opcoes, { consumirEdicao } from './Opcoes'
import {
  Anuncios, ArquivosGerados, CalculoL13, DadosImovel, DivergenciasL13, Documentos, Historico, Mais, Secao,
  arquivosGerados, linhasDocumentos, nDivergencias, useBusca, type AnuncioL13, type ConversaImportada, type DocL13, type PropostaCli,
} from './Detalhes'
import { ConversaCompleta } from './Importar'
import { ConversaFeed } from './Clientes'
import { Esqueleto } from './Marca'
import { ConfirmarValor } from './Referenciais'
import { ImagensDoLaudo } from './ImagensLaudo'
import { QuadroCandidatos } from './Candidatos'
import { plural,
  STATUS_AGUARDANDO_AVALIADOR, STATUS_BLOQUEADO, STATUS_CANCELADO, STATUS_ERRO_TECNICO, aguardandoEscolha, dataBR, ehFinal, emExecucao, textoTela,
  etapaDoBloqueio, etapaDoErro, modalidade, nomeSolicitante, moeda, numero2, parado, textoResumoIA,
} from './rotulos'
import { useStore } from './store'
import { semJaSabido } from './nomesCampos'
import type {
  AcaoPendencia, AreasCalculo, Detalhe, EtapaTela, ResultadoCalculo, ResultadoEntrega, ResultadoExtracao, ResultadoSelecao,
} from './tipos'
import { useEventos } from './useEventos'

const POLL_SEM_WS_MS = 8000

/** O número que o avaliador veio buscar, em destaque no topo do trabalho concluído. */
function ValorDestaque({ r }: { r: ResultadoCalculo }) {
  return (
    <section className="cartao overflow-hidden" aria-labelledby="sec-valor">
      <div className="bg-barro-claro px-4 py-4 sm:px-5">
        <h2 id="sec-valor" className="sobre">Valor de mercado adotado</h2>
        <p className="mt-1 text-3xl font-semibold tabular-nums tracking-tight text-stone-900 sm:text-4xl">{moeda(r.valor_adotado)}</p>
      </div>
      <dl className="grid grid-cols-1 divide-y divide-stone-100 text-sm sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <div className="px-4 py-2.5 sm:px-5">
          <dt className="text-xs text-stone-500">Faixa de valor</dt>
          <dd className="font-medium tabular-nums text-stone-900">{moeda(r.valor_min)} a {moeda(r.valor_max)}</dd>
        </div>
        <div className="px-4 py-2.5 sm:px-5">
          <dt className="text-xs text-stone-500">Unitário adotado</dt>
          <dd className="font-medium tabular-nums text-stone-900">{moeda(r.unitario_adotado)}/m²</dd>
        </div>
        <div className="px-4 py-2.5 sm:px-5">
          <dt className="text-xs text-stone-500">Área considerada</dt>
          <dd className="font-medium tabular-nums text-stone-900">{numero2(r.area)} m²</dd>
        </div>
      </dl>
    </section>
  )
}

/** Trabalho criado mas não iniciado (envio interrompido): completa os arquivos e inicia. */
function NaoIniciado({ jobId, enviados, aoMudar }: { jobId: string; enviados: number; aoMudar: () => void }) {
  const envio = useEnvio()
  const [ocupado, setOcupado] = useState(false)
  const [passo, setPasso] = useState('')
  const [erro, setErro] = useState('')

  async function enviarMais(): Promise<boolean> {
    const falhou = await envio.enviarPendentes(jobId, setPasso)
    if (falhou === null) return false
    if (falhou) { setErro(`${falhou === 1 ? '1 arquivo não foi enviado' : `${falhou} arquivos não foram enviados`}. Remova-os ou tente novamente.`); return false }
    return true
  }

  async function executar(iniciar: boolean) {
    setErro('')
    if (envio.temGrande) { setErro('Há arquivos acima de 50 MB. Remova-os para continuar.'); return }
    setOcupado(true)
    try {
      if (envio.pendentes && !(await enviarMais())) return
      if (iniciar) {
        setPasso('Iniciando a avaliação…')
        await post(`/jobs/${encodeURIComponent(jobId)}/iniciar`)
      }
      aoMudar()
    } catch (e) {
      if (!ehAuth(e)) setErro(mensagemErro(e))
    } finally {
      setOcupado(false)
      setPasso('')
    }
  }

  return (
    <section className="proximo-passo" aria-labelledby="sec-nao-iniciado">
      <span className="tag-jdb">Próximo passo</span>
      <h2 className="titulo-cartao" id="sec-nao-iniciado">Envie os documentos e as fotos da visita.</h2>
      <p className="texto">{enviados ? `${plural(enviados, 'arquivo', 'arquivos')} já recebidos. ` : ''}Depois toque em Iniciar.</p>
      <ZonasArquivos envio={envio} desabilitado={ocupado} />
      {erro && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">{erro}</div>}
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-end">
        {ocupado && <span className="text-sm text-stone-500 sm:mr-auto" role="status">{passo}</span>}
        <button type="button" className="btn-sec" disabled={ocupado || envio.pendentes === 0}
                onClick={() => void executar(false)}>
          Enviar mais arquivos{envio.pendentes ? ` (${envio.pendentes})` : ''}
        </button>
        <button type="button" className="btn" disabled={ocupado} onClick={() => void executar(true)}>
          {envio.pendentes ? 'Enviar e iniciar' : 'Iniciar'}
        </button>
      </div>
    </section>
  )
}

/** O "Ver …" do próximo passo leva à seção certa dos detalhes. */
const SECAO_DE: Record<string, string> = {
  confirmar: 'calculo', entrega: 'arquivos', dados: 'dados', candidatos: 'anuncios', referenciais: 'anuncios',
  calculo: 'calculo', divergencias: 'divergencias', trabalho: 'mais', refazer: 'mais', avisos: 'historico', atividade: 'historico',
}

// 097-5: o pedido "só o valor" sobrevive à troca de tela (a tela dos Detalhes pode montar o componente de novo)
let pedidoSoValor = false

export default function Trabalho() {
  const jobId = useStore((s) => s.jobId)
  const ir = useStore((s) => s.ir)
  const emDetalhes = useStore((s) => s.tela) === 'detalhes'
  const [detalhe, setDetalhe] = useState<Detalhe | null>(null)
  const [erro, setErro] = useState('')
  const [naoEncontrado, setNaoEncontrado] = useState(false)
  const [aviso, setAviso] = useState('')
  const [campoEd, setCampoEd] = useState<string | null>(null)
  const [editarTrab, setEditarTrab] = useState<{ foco?: string } | null>(null)
  const [enviarTipo, setEnviarTipo] = useState<Tipo | 'todos' | null>(null)
  const ativo = useRef(true)

  const carregar = useCallback(async () => {
    if (!jobId) return
    try {
      const d = await get<Detalhe>(`/jobs/${encodeURIComponent(jobId)}`)
      if (!ativo.current) return
      setDetalhe(d)
      setErro('')
    } catch (e) {
      if (!ativo.current) return
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return
      if (e instanceof ApiError && e.status === 404) setNaoEncontrado(true)
      else setErro('Não foi possível atualizar o trabalho.')
    }
  }, [jobId])

  useEffect(() => {
    ativo.current = true
    setDetalhe(null)
    setNaoEncontrado(false)
    setAviso('')
    setCampoEd(null)
    setEditarTrab(null)
    setEnviarTipo(null)
    void carregar()
    return () => { ativo.current = false }
  }, [carregar])

  const { eventos, conectado } = useEventos(naoEncontrado ? null : jobId, carregar)
  // ORDEM 060: "Editar trabalho" do menu da lista abre a edição aqui
  const carregado = detalhe?.job.id
  useEffect(() => { if (carregado && consumirEdicao(carregado)) setEditarTrab({}) }, [carregado])

  // ORDEM 026-F2: pergunta "vale só para este laudo ou para todos os seus?" depois de corrigir
  const [filaAprender, setFilaAprender] = useState<CorrecaoAprender[]>([])
  const setAprender = useCallback((c: CorrecaoAprender) => setFilaAprender((f) => (
    f.some((x) => x.tipo === c.tipo && x.chave === c.chave) ? f : [...f, c])), [])
  const aprender = filaAprender[0] ?? null

  // ORDEM 059 (L13): detalhes numa tela própria, com seções que abrem e fecham (várias ao mesmo tempo)
  const [abertas, setAbertas] = useState<string[]>(['dados'])
  const [soValor, setSoValorEstado] = useState(() => pedidoSoValor)   // 093-6: "Confirmar o valor" mostra só o quadro do valor
  const setSoValor = useCallback((v: boolean) => { pedidoSoValor = v; setSoValorEstado(v) }, [])
  const alvo = useRef<string | null>(null)
  const alternar = (id: string) => setAbertas((a) => (a.includes(id) ? a.filter((x) => x !== id) : [...a, id]))
  // 097-5: no modo "só o valor", a tela vai direto ao quadro do valor (também quando já estava nos Detalhes)
  const estavaNosDetalhes = useRef(emDetalhes)
  useEffect(() => {                                  // saiu dos Detalhes (só na passagem Detalhes → outra tela)
    if (estavaNosDetalhes.current && !emDetalhes) setSoValor(false)
    estavaNosDetalhes.current = emDetalhes
  }, [emDetalhes, setSoValor])
  useEffect(() => {
    if (!soValor) return
    alvo.current = null
    const t = setTimeout(() => document.getElementById('l13-confirmar')?.scrollIntoView({ block: 'start', behavior: 'smooth' }), 120)
    return () => clearTimeout(t)
  }, [soValor])
  const irDetalhes = useCallback((secao?: string) => {
    setSoValor(false)
    alvo.current = secao ?? null
    if (secao) setAbertas((a) => (a.includes(secao) ? a : [...a, secao]))
    if (jobId) ir('detalhes', jobId)
  }, [ir, jobId, setSoValor])
  // ação que pede uma seção abre a seção certa
  useEffect(() => { if (campoEd) irDetalhes('dados') }, [campoEd, irDetalhes])
  useEffect(() => { if (editarTrab) irDetalhes('mais') }, [editarTrab, irDetalhes])
  useEffect(() => { if (enviarTipo) irDetalhes('documentos') }, [enviarTipo, irDetalhes])
  // trocar entre o trabalho e os detalhes: vai para a seção pedida, ou para o topo
  useEffect(() => {
    const id = emDetalhes ? alvo.current : null
    alvo.current = null
    const t = setTimeout(() => {
      const el = id ? document.getElementById(`l13-${id}`) : null
      if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' })
      else window.scrollTo({ top: 0 })
    }, 60)
    return () => clearTimeout(t)
  }, [emDetalhes])

  // dados que só a tela de detalhes usa (recarregam quando o trabalho muda)
  const versao = detalhe?.job.atualizado ?? ''
  const jid = encodeURIComponent(jobId ?? '')
  const docs = useBusca<DocL13[]>(emDetalhes && jobId ? `/jobs/${jid}/documentos` : null, versao)
  const anuncios = useBusca<{ anuncios: AnuncioL13[]; dossie: boolean }>(emDetalhes && jobId ? `/jobs/${jid}/anuncios` : null, versao)
  const areas = useBusca<AreasCalculo>(emDetalhes && jobId ? `/jobs/${jid}/areas` : null, versao)
  const cliId = detalhe?.tela?.cliente_id
  const cli = useBusca<{ proposta: PropostaCli | null; contexto?: Record<string, unknown> }>(emDetalhes && cliId ? `/clientes/${encodeURIComponent(cliId)}` : null, versao)
  const imps = useBusca<{ importacoes: ConversaImportada[] }>(emDetalhes && cliId ? `/clientes/${encodeURIComponent(cliId)}/importacoes` : null, versao)
  const [verConversa, setVerConversa] = useState('')

  const final = ehFinal(detalhe?.job.status)
  const quieto = parado(detalhe?.job.status)
  useAvisoFim(detalhe)
  // Sem WebSocket, mantém o painel vivo por sondagem enquanto o trabalho não termina.
  useEffect(() => {
    if (!detalhe || quieto || conectado) return
    const t = setInterval(() => { void carregar() }, POLL_SEM_WS_MS)
    return () => clearInterval(t)
  }, [detalhe, quieto, conectado, carregar])

  const linhas = useMemo(
    () => (detalhe ? estadoDasEtapas(detalhe.job, eventos, etapaDoBloqueio(detalhe.pendencias)) : []),
    [detalhe, eventos],
  )

  // 093-A-13: "Valor confirmado… Gerando o laudo…" some quando a montagem termina
  const montando = !!detalhe && emExecucao(detalhe.job)
  const viuMontar = useRef(false)
  useEffect(() => {
    if (montando) { viuMontar.current = true; return }
    if (viuMontar.current && /Gerando o laudo|Atualizando o laudo|montado de novo/.test(aviso)) { setAviso(''); viuMontar.current = false }
  }, [montando, aviso])

  const voltar = emDetalhes && jobId ? (
    <button className="voltar-jdb" onClick={() => ir('job', jobId)}>
      <ArrowLeft size={18} aria-hidden="true" /> Trabalho
    </button>
  ) : (
    <button className="voltar-jdb" onClick={() => ir('lista')}>
      <ArrowLeft size={18} aria-hidden="true" /> Trabalhos
    </button>
  )

  if (naoEncontrado) {
    return (
      <section>
        {voltar}
        <div className="cartao-pad mt-2 text-center">
          <p className="font-medium text-stone-800">Trabalho não encontrado</p>
          <button className="btn mt-3" onClick={() => ir('lista')}>Voltar à lista</button>
        </div>
      </section>
    )
  }

  if (!detalhe) {
    return (
      <section>
        {voltar}
        {erro
          ? (
            <div className="faixa-erro mt-2 flex items-center justify-between gap-3" role="alert">
              <span>{erro}</span>
              <button className="btn-sec btn-peq" onClick={() => void carregar()}>Tentar de novo</button>
            </div>
          )
          : <div className="mt-2"><Esqueleto linhas={5} rotulo="Carregando o trabalho…" /></div>}
      </section>
    )
  }

  const { job } = detalhe
  const d = job.dados
  const sondando = !conectado && !quieto && !erro
  const naoIniciado = job.etapa === 'nova' && job.status === 'pendente'
  const aguardandoAvaliador = job.status === STATUS_AGUARDANDO_AVALIADOR
  const escolhendo = aguardandoEscolha(job)
  const bloqueado = job.status === STATUS_BLOQUEADO
  const erroTecnico = job.status === STATUS_ERRO_TECNICO
  const cancelado = job.status === STATUS_CANCELADO
  const livre = !emExecucao(job)
  // "Cancelar": rodando, na fila ou esperando (Coletor/avaliador) — nunca finalizado/cancelado
  const podeCancelar = !final && !cancelado && !erroTecnico && !naoIniciado
  const mudou = (msg: string) => { setAviso(msg); void carregar() }
  // Só é "Concluído" (100 %) quando o laudo saiu de fato: bloqueado/erro técnico mostram onde parou.
  const etapaAtual = linhas.find((l) => l.estado === 'rodando'
    || l.estado === 'aguardando_avaliador' || l.estado === 'erro' || l.estado === 'bloqueado')
  const agir = (a: AcaoPendencia) => {
    if (a.tipo === 'ligar_coletor') ir('sistema')
    else if (a.tipo === 'enviar_arquivo') setEnviarTipo(a.tipo_arquivo ?? 'todos')
    else if (a.tipo === 'preencher_trabalho') setEditarTrab({ foco: a.campo })
    else setCampoEd(a.campo)
  }

  // ---------------------------------------------------------------- ORDEM 059: seções do L13
  const ext = (detalhe.etapas.extracao ?? null) as ResultadoExtracao | null
  const selR = (detalhe.etapas.selecao ?? null) as ResultadoSelecao | null
  const ent = (detalhe.etapas.entrega ?? null) as ResultadoEntrega | null
  const nAvisos = eventos.filter((e) => e.nivel === 'aviso').length
  const edicao = { ativa: final, livre, editarCampos: aguardandoAvaliador, jobId: job.id, arquivos: detalhe.arquivos,
                   campo: campoEd, setCampo: setCampoEd, aoMudar: mudou, recarregar: carregar, aoAprender: setAprender }
  const pv = detalhe.previa_calculo ?? null
  const calc = (pv && !('pendente' in pv) ? pv : null) ?? detalhe.resultado
  const planilha = ent?.arquivos?.find((a) => /\.xlsx$/i.test(a)) ?? null
  const proposta = cli?.proposta ?? null

  const parte = (d as { objeto_parte?: string }).objeto_parte
  const imovel = [parte || d.tipo, d.bairro].filter(Boolean).join(' – ') || 'Imóvel sem descrição'
  const linhaTopo = [nomeSolicitante(d.cliente), modalidade(d.modalidade), d.cidade].filter(Boolean).join(' · ')
  const abrirDetalhes = (id: string) => {
    irDetalhes(SECAO_DE[id] ?? id)
    if (id === 'confirmar') { alvo.current = 'confirmar'; setSoValor(true) }   // 083-D / 093-6: só o bloco do valor
  }
  const dataConfirmada = detalhe.alerta_datas?.startsWith('CONFIRMADA: ') ? detalhe.alerta_datas.slice('CONFIRMADA: '.length) : ''

  const avisoTopo = (
    <>
      {/* no máximo um aviso curto por vez */}
      {erro ? <p className="aviso-impede" role="alert">{erro}</p>
        : aviso ? (
          <p className="aviso-simples flex items-start justify-between gap-3" role="status">
            <span>{aviso}</span>
            <button className="link-discreto shrink-0" onClick={() => setAviso('')}>Fechar</button>
          </p>
        ) : null}
    </>
  )

  if (emDetalhes) {
    const nDocs = docs ? linhasDocumentos(docs).length : detalhe.arquivos.length
    const nAnuncios = anuncios ? anuncios.anuncios.length : detalhe.candidatos.length
    const laudoConcluido = !!(detalhe.tela?.aprovado || detalhe.tela?.assinado)   // 181: laudo concluído ✓
    const secoes: { id: string; titulo: string; conteudo: ReactNode }[] = [
      { id: 'documentos', titulo: `Documentos (${nDocs})`, conteudo: (
        <Documentos docs={docs} conversas={imps?.importacoes} aoVerConversa={setVerConversa} extra={enviarTipo && (
          <EnviarTipo key={enviarTipo} jobId={job.id} tipo={enviarTipo === 'todos' ? undefined : enviarTipo}
                      refazer={bloqueado && etapaAtual?.id === 'triagem' ? 'triagem' : 'extracao'} aoFechar={() => setEnviarTipo(null)}
                      aoEnviar={(m) => { setEnviarTipo(null); mudou(m) }} />
        )} />
      ) },
      { id: 'imagens', titulo: 'Imagens do laudo', conteudo: <ImagensDoLaudo jobId={job.id} /> },   // 172-3
      { id: 'dados', titulo: 'Dados do imóvel', conteudo: (
        <DadosImovel campos={detalhe.campos} docs={docs} podeCorrigir={final || aguardandoAvaliador} jobId={job.id}
                     arquivos={detalhe.arquivos} campoAberto={campoEd} setCampo={setCampoEd} alterados={!!(final && detalhe.dados_alterados)}
                     aoSalvo={(nome, antes, depois) => {
                       setAprender({ tipo: 'campo', chave: nome, antes, depois })
                       mudou(final ? `“${nome}” corrigido.` : `“${nome}” salvo.`)
                       ir('job', job.id)          // volta ao trabalho: o próximo passo vira "Atualize o laudo"
                     }} />
      ) },
      { id: 'divergencias', titulo: `Divergências (${nDivergencias(ext)})`, conteudo: (
        <DivergenciasL13 ext={ext} area={areas?.escolha ?? null} dataConfirmada={dataConfirmada} />
      ) },
      { id: 'anuncios', titulo: `Imóveis referenciais (${nAnuncios})`, conteudo: escolhendo ? (
        <>
          <LinksBusca jobId={job.id} />
          <QuadroCandidatos detalhe={detalhe} eventos={eventos} recarregar={carregar} aoMudar={mudou} livre={livre} />
        </>
      ) : (
        <Anuncios jobId={job.id} dados={anuncios} extra={detalhe.candidatos.length > 0 && (
          <Mais titulo="Trocar, tirar ou acrescentar referenciais" aberto>
            <LinksBusca jobId={job.id} />
            <CandidatosConteudo detalhe={detalhe} eventos={eventos} edicao={edicao} />
          </Mais>
        )} />
      ) },
      { id: 'calculo', titulo: 'Cálculo', conteudo: (
        <CalculoL13 jobId={job.id} r={calc} previa={!!(pv && !('pendente' in pv))} planilha={final ? planilha : null} extra={(
          <>
            {aguardandoAvaliador && !escolhendo && (
              <div id="l13-confirmar" className="scroll-mt-4">
                <ConfirmarValor key={detalhe.candidatos.map((r) => r.n).join()} detalhe={detalhe} aoMudar={mudou} aoAprender={setAprender} />
              </div>
            )}
            {calc && <Mais titulo="Ver a conta completa"><Calculo d={detalhe} sel={selR} /></Mais>}
          </>
        )} />
      ) },
      { id: 'historico', titulo: 'Histórico', conteudo: (
        <Historico eventos={eventos} extra={nAvisos > 0 && (
          <Mais titulo={`Avisos (${nAvisos})`}><Avisos eventos={eventos} /></Mais>
        )} />
      ) },
      { id: 'arquivos', titulo: `Arquivos gerados (${arquivosGerados(final ? ent : null, proposta)})`, conteudo: (
        <ArquivosGerados jobId={job.id} entrega={final ? ent : null} revisao={detalhe.tela?.revisao ?? 0} proposta={proposta}
                         aprovado={!!detalhe.tela?.aprovado}
                         abrirLaudo={final ? () => ir('laudo', job.id) : undefined} extra={final && (
          <Mais titulo="Prévia do laudo e o que falta" aberto={detalhe.pendencias.length > 0}>
            {detalhe.resultado && !bloqueado && <ValorDestaque r={detalhe.resultado} />}
            <Entrega jobId={job.id} versao={job.atualizado} status={job.status} entrega={ent}
                     revisao={detalhe.tela?.revisao} aprovado={detalhe.tela ? !!detalhe.tela.aprovado : undefined}
                     pendencias={detalhe.pendencias} aoAgir={agir} />
          </Mais>
        )} />
      ) },
      // 181: sai o "Andamento" (as etapas já estão no alto); no trabalho concluído saem o "Refazer e corrigir" e o
      // "Editar, cancelar ou excluir" (o [Excluir o trabalho] fica no "··· Opções" do alto); custo da IA só para o dono.
      ...(!laudoConcluido || (detalhe.resumo_ia && detalhe.resumo_ia.chamadas > 0) || sondando ? [{ id: 'mais', titulo: 'Mais', conteudo: (
        <div className="grid gap-4">
          {final && !laudoConcluido && (
            <Mais titulo="Refazer e corrigir o laudo">
              <BotoesReabrir jobId={job.id} aoReabrir={mudou} aoEditarTrabalho={() => setEditarTrab({})} bloqueado={bloqueado}
                             aoEnviarArquivos={() => setEnviarTipo('todos')} />
            </Mais>
          )}
          {!laudoConcluido && (
            <Mais titulo="Editar, cancelar ou excluir o trabalho" aberto={!!editarTrab}>
              {editarTrab && (
                <EditarTrabalho detalhe={detalhe} foco={editarTrab.foco} aoCancelar={() => setEditarTrab(null)}
                                aoSalvar={(m) => { setEditarTrab(null); mudou(m) }} />
              )}
              <GerirTrabalho jobId={job.id} numero={job.numero} livre={livre} mostrarEditar={!final}
                             aoEditarTrabalho={() => setEditarTrab({})} podeCancelar={podeCancelar} aoCancelar={mudou} />
            </Mais>
          )}
          {detalhe.resumo_ia && detalhe.resumo_ia.chamadas > 0 && (
            <p className="small-jdb" aria-label="Uso de IA">{textoResumoIA(detalhe.resumo_ia)}</p>
          )}
          {sondando && <p className="small-jdb">Sem conexão ao vivo: a tela consulta o servidor a cada 8 segundos.</p>}
        </div>
      ) }] : []),
    ]
    return (
      <section className="tela-simples tela-larga">
        {voltar}
        <div>
          <h1 className="titulo-jdb">Detalhes do trabalho</h1>
          <p className="sub-jdb break-words">{imovel} · nº {job.numero}{d.data_vistoria ? ` · vistoria ${dataBR(d.data_vistoria)}` : ''}</p>
        </div>
        {avisoTopo}
        {!soValor && typeof cli?.contexto?.entendimento === 'string' && cli.contexto.entendimento_status === 'confirmado' && (
          <section className="entendimento-l13" aria-labelledby="titulo-entendimento">
            <h2 id="titulo-entendimento" className="titulo-sub-l13">Entendimento do caso</h2>
            {/* 080-5: o "Ainda não sei" só com o que continua faltando */}
            <p className="msg-texto">{semJaSabido(String(cli.contexto.entendimento).replace(/\n\nQuer me explicar mais[^]*$/, '').replace(/ ?É isso\?/, ''), detalhe.campos ?? [], d.data_base)}</p>
            <p className="small-jdb">Confirmado por você antes de começar. É contexto do caso: não entra no laudo como dado.</p>
          </section>
        )}
        {verConversa && cliId && <ConversaCompleta clienteId={cliId} importacao={verConversa} aoFechar={() => setVerConversa('')} />}
        {soValor && (
          <p className="aviso-simples flex flex-wrap items-center justify-between gap-2" role="status">
            <span>Mostrando só o valor para confirmar.</span>
            <button type="button" className="btn-sec btn-peq" onClick={() => setSoValor(false)}>Ver todos os detalhes</button>
          </p>
        )}
        <div className="grid gap-4">
          {secoes.filter((s) => !soValor || s.id === 'calculo').map((s) => (
            <Secao key={s.id} id={s.id} titulo={s.titulo} aberta={(soValor && s.id === 'calculo') || abertas.includes(s.id)} alternar={() => alternar(s.id)}>
              {s.conteudo}
            </Secao>
          ))}
        </div>
      </section>
    )
  }

  return (
    <section className="tela-simples tela-larga">
      {voltar}
      <div className="titulo-com-opcoes">
        <div className="min-w-0">
          <h1 className="titulo-jdb break-words">{imovel}</h1>
          <p className="sub-jdb">{linhaTopo || `Trabalho nº ${job.numero}`}</p>
        </div>
        <Opcoes job={{ ...d, id: job.id, numero: job.numero }} titulo={imovel} entregue={!!ent?.arquivos?.length}
                aoEditar={() => setEditarTrab({})} aoApagado={() => ir('lista')} />
      </div>

      {detalhe.tela && detalhe.tela.etapas.length > 0 && <Etapas etapas={detalhe.tela.etapas} />}

      {avisoTopo}
      {aprender && (
        <PerguntaAprender key={`${aprender.tipo}:${aprender.chave}`} jobId={job.id} correcao={aprender}
                          aoFechar={(m) => { setFilaAprender((f) => f.slice(1)); if (m) setAviso(m) }} />
      )}

      {naoIniciado ? <NaoIniciado jobId={job.id} enviados={detalhe.arquivos.length} aoMudar={() => void carregar()} />
        : erroTecnico ? <ErroTecnico jobId={job.id} etapa={etapaDoErro(eventos)} aoReabrir={mudou} />
        : cancelado ? <Cancelado jobId={job.id} aoReabrir={mudou} />
        : <ProximoPasso detalhe={detalhe} rodando={emExecucao(job)} etapaRodando={etapaAtual?.rotulo} etapaId={etapaAtual?.id}
                        agora={fazendoAgora(eventos, etapaAtual?.id)}
                        linhas={linhas} imovel={imovel} livre={livre}
                        aoMudar={mudou} abrirDetalhes={abrirDetalhes} corrigirData={() => setEditarTrab({ foco: 'data_vistoria' })} />}

      <div className="flex flex-wrap justify-end gap-x-6">
        {/* 076-A item 5: do laudo pronto direto para a barra Anúncios dos Detalhes, aberta */}
        {/* 153: "Analisar imóveis referenciais" vai direto ao bloco dos referenciais, já aberto para editar.
            Saiu o "Refazer o laudo (mesmos dados)": nenhum botão manda a IA refazer o laudo inteiro. */}
        {!!ent?.arquivos?.length && <button type="button" className="link-detalhes-l13" onClick={() => irDetalhes('anuncios')}>Analisar imóveis referenciais</button>}
        <button type="button" className="link-detalhes-l13" onClick={() => irDetalhes()}>Ver detalhes do trabalho</button>
      </div>
      {/* 194-4: o modelo que este trabalho usa (o da modalidade), numa linha e sem botão */}
      {detalhe.modelo_laudo && (
        <p className="small-jdb" style={{ textAlign: 'right', margin: 0 }}>Modelo: {detalhe.modelo_laudo.modalidade} — {detalhe.modelo_laudo.de === 'seu' ? 'o seu' : 'o do sistema'}</p>
      )}

      {detalhe.tela?.cliente_id && <ConversaFeed clienteId={detalhe.tela.cliente_id} aoMudar={() => void carregar()} />}
    </section>
  )
}

/** 073-2: a última coisa que a etapa em andamento disse ("consultando portais…", "portal bloqueado: ZAP"…),
 *  em uma linha curta, para a busca nunca ficar 10 min muda. */
function fazendoAgora(eventos: ReadonlyArray<{ etapa: string; nivel: string; msg: string }>, etapa?: string): string {
  const e = [...eventos].reverse().find((x) => x.etapa === etapa && (x.nivel === 'info' || x.nivel === 'aviso'))
  if (!e) return ''
  const m = textoTela(e.msg).split(/ \(|\. Para /)[0].replace(/^consultando portais: todos – /i, 'Procurando nos portais: ')
    .replace(/^portal bloqueado: (.+)$/i, '$1 bloqueou a busca.').replace(/^internet: /i, 'Na internet: ')
  return m.charAt(0).toUpperCase() + m.slice(1)
}

/** ORDEM 053 (L3): etapas em caixas no computador; no celular, bolinhas + "Laudo · etapa 4 de 5". */
function Etapas({ etapas }: { etapas: EtapaTela[] }) {
  const i = Math.max(0, etapas.findIndex((e) => e.status === 'atual'))
  return (
    <div>
      <ol className="etapas-jdb so-computador" aria-label="Etapas do trabalho">
        {etapas.map((e) => (
          <li key={e.etapa} aria-current={e.status === 'atual' ? 'step' : undefined}
              title={e.status === 'fora' ? 'Feita fora do JdB' : undefined} tabIndex={e.status === 'fora' ? 0 : undefined}
              aria-label={e.status === 'fora' ? `${e.rotulo}: feita fora do JdB` : undefined}
              className={e.status === 'feito' ? 'st ok' : e.status === 'atual' ? 'st now' : e.status === 'fora' ? 'st fora' : 'st'}>
            {e.status === 'feito' ? '✓ ' : e.status === 'fora' ? '– ' : ''}{e.rotulo}
          </li>
        ))}
      </ol>
      <p className="etapas-celular so-celular" aria-label={`Etapa ${i + 1} de ${etapas.length}: ${etapas[i]?.rotulo}`}>
        {etapas.map((e) => <span key={e.etapa} aria-hidden="true" className={`ponto ${e.status === 'feito' ? 'ponto-ok' : e.status === 'atual' ? 'ponto-now' : e.status === 'fora' ? 'ponto-fora' : ''}`} />)}
        <b>{etapas[i]?.rotulo}</b><span className="small-jdb">· etapa {i + 1} de {etapas.length}</span>
      </p>
    </div>
  )
}
