import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, CalendarDays, ChevronDown, FileStack, MapPin } from 'lucide-react'
import { ApiError, get, post } from './api'
import { ZonasArquivos, ehAuth, mensagemErro, useEnvio } from './Envio'
import Corrigir, { textoCorrecao, type RespostaCorrecao } from './Corrigir'
import { BotoesReabrir, EditarTrabalho, EnviarTipo, useAvisoFim } from './Acoes'
import type { Tipo } from './Envio'
import Entrega from './Entrega'
import { estadoDasEtapas } from './etapas'
import LinhaDoTempo from './LinhaDoTempo'
import Paineis from './Paineis'
import StatusBadge from './StatusBadge'
import { Esqueleto } from './Marca'
import { dataBR, ehFinal, modalidade, moeda, numero2, textoResumoIA } from './rotulos'
import { useStore } from './store'
import type { AcaoPendencia, Detalhe, ResultadoCalculo, ResultadoEntrega } from './tipos'
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
    if (falhou) { setErro(`${falhou} arquivo(s) não foram enviados. Remova-os ou tente novamente.`); return false }
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
    <section className="cartao-pad space-y-4" aria-labelledby="sec-nao-iniciado">
      <div>
        <h2 className="titulo-sec" id="sec-nao-iniciado">Trabalho ainda não iniciado</h2>
        <p className="text-sm text-stone-500">
          {enviados} arquivo(s) já no servidor. Envie o que faltou e toque em Iniciar.
        </p>
      </div>
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

export default function Trabalho() {
  const jobId = useStore((s) => s.jobId)
  const ir = useStore((s) => s.ir)
  const [detalhe, setDetalhe] = useState<Detalhe | null>(null)
  const [erro, setErro] = useState('')
  const [naoEncontrado, setNaoEncontrado] = useState(false)
  const [aviso, setAviso] = useState('')
  const [campoEd, setCampoEd] = useState<string | null>(null)
  const [editarTrab, setEditarTrab] = useState<{ foco?: string } | null>(null)
  const [enviarTipo, setEnviarTipo] = useState<Tipo | null>(null)
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

  const final = ehFinal(detalhe?.job.status)
  useAvisoFim(detalhe)
  // Sem WebSocket, mantém o painel vivo por sondagem enquanto o trabalho não termina.
  useEffect(() => {
    if (!detalhe || final || conectado) return
    const t = setInterval(() => { void carregar() }, POLL_SEM_WS_MS)
    return () => clearInterval(t)
  }, [detalhe, final, conectado, carregar])

  const linhas = useMemo(
    () => (detalhe ? estadoDasEtapas(detalhe.job, eventos) : []),
    [detalhe, eventos],
  )

  const voltar = (
    <button className="btn-link -ml-2 inline-flex items-center gap-1" onClick={() => ir('lista')}>
      <ArrowLeft size={15} aria-hidden="true" /> Trabalhos
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
  const sondando = !conectado && !final && !erro
  const naoIniciado = job.etapa === 'nova' && job.status === 'pendente'
  const mudou = (msg: string) => { setAviso(msg); void carregar() }
  const feitas = linhas.filter((l) => l.estado === 'concluida').length
  const pct = final ? 100 : Math.round((feitas / Math.max(1, linhas.length)) * 100)
  const etapaAtual = linhas.find((l) => l.estado === 'rodando' || l.estado === 'aguardando_coletor' || l.estado === 'erro')
  const largo = typeof window !== 'undefined' && window.matchMedia('(min-width: 1024px)').matches
  const agir = (a: AcaoPendencia) => {
    if (a.tipo === 'ligar_coletor') ir('config')
    else if (a.tipo === 'enviar_arquivo') setEnviarTipo(a.tipo_arquivo)
    else if (a.tipo === 'preencher_trabalho') setEditarTrab({ foco: a.campo })
    else setCampoEd(a.campo)
  }

  return (
    <section className="space-y-4">
      <div>
        {voltar}
        <div className="mt-1 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            <p className="sobre">Trabalho Nº {job.numero} · {modalidade(d.modalidade)}</p>
            <h1 className="titulo-pag break-words">{d.cliente || 'Sem solicitante'}</h1>
            <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-stone-600">
              <span className="inline-flex items-center gap-1.5">
                <MapPin size={14} className="text-stone-400" aria-hidden="true" />
                {[d.tipo, d.bairro, d.cidade].filter(Boolean).join(' · ') || '—'}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <CalendarDays size={14} className="text-stone-400" aria-hidden="true" />
                Vistoria em {dataBR(d.data_vistoria)}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <FileStack size={14} className="text-stone-400" aria-hidden="true" />
                {detalhe.arquivos.length} arquivo{detalhe.arquivos.length === 1 ? '' : 's'}
              </span>
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-xs text-stone-500" role="status"
                  title={conectado ? 'Atualizando ao vivo' : sondando ? 'Sem conexão ao vivo; consultando o servidor periodicamente' : 'Sem conexão com o servidor'}>
              <span className={`h-2 w-2 rounded-full ${conectado ? 'bg-emerald-500' : sondando ? 'bg-sky-500' : final ? 'bg-stone-300' : 'bg-amber-500 animate-pulse'}`} aria-hidden="true" />
              {conectado ? 'Ao vivo' : sondando ? 'Atualizando a cada 8 s' : final ? 'Atualizado' : 'Reconectando…'}
            </span>
            <StatusBadge status={job.status} />
          </div>
        </div>
        {erro && <p className="erro-txt" role="alert">{erro}</p>}
      </div>

      <div className="grid gap-4 lg:grid-cols-[17rem_minmax(0,1fr)] lg:items-start">
        <aside className="cartao lg:sticky lg:top-20">
          {/* No celular o andamento de um trabalho concluído fica recolhido: a entrega vem primeiro. */}
          <details open={largo || !final} className="group">
            <summary className="flex cursor-pointer list-none flex-col gap-2 rounded-xl px-4 py-3 sm:px-5 [&::-webkit-details-marker]:hidden">
              <span className="flex items-center justify-between gap-2">
                <span className="titulo-sec">Andamento</span>
                <span className="flex items-center gap-1.5 text-xs tabular-nums text-stone-500">
                  {final ? 'Concluído' : `${feitas} de ${linhas.length}`}
                  <ChevronDown size={16} className="transition-transform group-open:rotate-180" aria-hidden="true" />
                </span>
              </span>
              <span className="block h-1.5 overflow-hidden rounded-full bg-stone-100" role="progressbar"
                    aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Andamento do trabalho">
                <span className={`block h-full rounded-full transition-[width] duration-500 ${final ? 'bg-emerald-500' : 'bg-barro'}`}
                      style={{ width: `${Math.max(pct, 3)}%` }} />
              </span>
              {!final && etapaAtual && (
                <span className="text-xs text-stone-600 group-open:hidden">Agora: {etapaAtual.rotulo}</span>
              )}
            </summary>
            <div className="border-t border-stone-100 px-4 py-4 sm:px-5">
              <LinhaDoTempo etapas={linhas} />
            </div>
          </details>
        </aside>
        <div className="min-w-0 space-y-4">
          {aviso && (
            <div className="faixa-info flex items-start justify-between gap-3" role="status">
              <span>{aviso}</span>
              <button className="btn-link shrink-0 !p-0" onClick={() => setAviso('')} aria-label="Fechar aviso">Fechar</button>
            </div>
          )}
          {final && detalhe.dados_alterados && (
            <div className="faixa-aviso" role="status">
              <strong className="font-semibold">Dados alterados.</strong> O laudo abaixo ainda é o anterior — use “Recalcular” para atualizar.
            </div>
          )}
          {naoIniciado && (
            <NaoIniciado jobId={job.id} enviados={detalhe.arquivos.length} aoMudar={() => void carregar()} />
          )}
          {final && detalhe.resultado && <ValorDestaque r={detalhe.resultado} />}
          {final && (
            <>
              <Entrega jobId={job.id} versao={job.atualizado} status={job.status}
                       entrega={(detalhe.etapas.entrega ?? null) as ResultadoEntrega | null}
                       pendencias={detalhe.pendencias} aoAgir={agir} />
              {enviarTipo && (
                <EnviarTipo key={enviarTipo} jobId={job.id} tipo={enviarTipo} aoFechar={() => setEnviarTipo(null)}
                            aoEnviar={(m) => { setEnviarTipo(null); mudou(m) }} />
              )}
              {editarTrab && (
                <EditarTrabalho detalhe={detalhe} foco={editarTrab.foco} aoCancelar={() => setEditarTrab(null)}
                                aoSalvar={(m) => { setEditarTrab(null); mudou(m) }} />
              )}
              <BotoesReabrir jobId={job.id} aoReabrir={mudou} aoEditarTrabalho={() => setEditarTrab({})} />
              <Corrigir jobId={job.id} onEnviado={(r: RespostaCorrecao) => { setAviso(textoCorrecao(r)); void carregar() }} />
            </>
          )}
          <Paineis detalhe={detalhe} eventos={eventos}
                   edicao={{ ativa: final, jobId: job.id, arquivos: detalhe.arquivos, campo: campoEd,
                             setCampo: setCampoEd, aoMudar: mudou }} />
        </div>
      </div>
      {detalhe.resumo_ia && detalhe.resumo_ia.chamadas > 0 && (
        <footer className="border-t border-stone-200 pt-3 text-xs text-stone-500" aria-label="Uso de IA">
          {textoResumoIA(detalhe.resumo_ia)}
        </footer>
      )}
    </section>
  )
}
