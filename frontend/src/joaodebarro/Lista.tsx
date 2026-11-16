import { AtalhoEntrega, BaixarRevisao } from './Downloads'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Plus, Search } from 'lucide-react'
import { filtrarJobs } from './campo'
import { ApiError, get } from './api'
import { Esqueleto, Logo } from './Marca'
import { nomeSolicitante, parado, modalidade } from './rotulos'
import { useStore } from './store'
import type { JobResumo } from './tipos'
import Opcoes, { pedirEdicao } from './Opcoes'

const ATUALIZA_MS = 10_000

/** Próximo passo que depende do avaliador (o resto é o sistema trabalhando ou já acabou). */
const QUIETOS = ['O JdB está montando', 'Concluído', 'Laudo concluído ✓', 'Cancelado', '']
export const ehVez = (p?: string) => !QUIETOS.includes(p ?? '') && !(p ?? '').startsWith('Aguardando')
const ETAPAS_L1 = ['Proposta', 'Contrato', 'Visita', 'Laudo']      // 178: a assinatura saiu do sistema
interface Cli { id: string; nome: string; imovel: string; etapa: string; proximo: string; job_id: string; modalidade: string }
const ROT_CLI: Record<string, string> = { proposta: 'Proposta', contrato: 'Contrato', visita: 'Visita', laudo: 'Laudo', assinatura: 'Laudo' }
const MOD_CLI: Record<string, string> = { OV: 'Opinião de Valor', AM: 'PTAM', AM_GARANTIA: 'PTAM garantia', AMJ: 'PTAM judicial' }
const primeiraMaiuscula = (t: string) => t.charAt(0).toUpperCase() + t.slice(1)

export default function Lista() {
  const ir = useStore((s) => s.ir)
  const [busca, setBusca] = useState('')
  const [jobs, setJobs] = useState<JobResumo[] | null>(null)
  const [erro, setErro] = useState('')
  const [aviso, setAviso] = useState('')

  const carregar = useCallback(async () => {
    try {
      const r = await get<JobResumo[]>('/jobs')
      setJobs([...r].sort((a, b) => b.numero - a.numero))
      setErro('')
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) return
      setErro('Não foi possível carregar os trabalhos.')
    }
  }, [])

  useEffect(() => { void carregar() }, [carregar])

  // Atualiza sozinho enquanto houver trabalho em andamento (e ao voltar para a aba).
  const emAndamento = !!jobs?.some((j) => !parado(j.status))
  useEffect(() => {
    if (!emAndamento) return
    const t = setInterval(() => { if (document.visibilityState !== 'hidden') void carregar() }, ATUALIZA_MS)
    return () => clearInterval(t)
  }, [emAndamento, carregar])
  useEffect(() => {
    const aoVoltar = () => { if (document.visibilityState === 'visible') void carregar() }
    document.addEventListener('visibilitychange', aoVoltar)
    return () => document.removeEventListener('visibilitychange', aoVoltar)
  }, [carregar])

  const [aba, setAba] = useState<'andamento' | 'concluidos'>('andamento')
  // ORDEM 053 / 054 item 5: cliente ainda sem trabalho (Proposta, Contrato, Visita) vira card da L1
  const [clientes, setClientes] = useState<Cli[]>([])
  useEffect(() => { get<{ clientes: Cli[] }>('/clientes').then((r) => setClientes(r.clientes.filter((c) => !c.job_id))).catch(() => undefined) }, [])
  const cliVis = aba === 'andamento' ? clientes.filter((c) => !busca || `${c.nome} ${c.imovel}`.toLowerCase().includes(busca.toLowerCase())) : []
  const eu = useEu()
  const concluido = (j: JobResumo) => j.proximo === 'Concluído' || j.proximo === 'Cancelado'
  const daAba = useMemo(() => (jobs ?? []).filter((j) => (aba === 'concluidos') === concluido(j)), [jobs, aba])
  const visiveis = useMemo(() => filtrarJobs(daAba, busca, ''), [daAba, busca])
  const precisam = (jobs ?? []).filter((j) => ehVez(j.proximo)).length + clientes.length
  const abrir = (j: JobResumo) => ir(j.proximo === 'Escolher referenciais' ? 'alinhamento' : 'job', j.id)
  const h = new Date().getHours()
  const saudacao = (h < 12 ? 'Bom dia' : h < 18 ? 'Boa tarde' : 'Boa noite') + (eu ? ', ' + eu : '')

  return (
    <section className="tela-simples tela-larga">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="titulo-jdb">{saudacao}</h1>
          <p className="sub-jdb">{precisam ? `${precisam} ${precisam === 1 ? 'trabalho precisa' : 'trabalhos precisam'} de você.` : 'Nenhum trabalho esperando você.'}</p>
        </div>
        <button className="btn-verde so-computador" style={{ width: 'auto' }} onClick={() => ir('novo')}>
          <Plus size={20} aria-hidden="true" /> Novo trabalho
        </button>
      </div>

      {erro && (
        <p className="aviso-impede flex items-center justify-between gap-3" role="alert">
          <span>{erro}</span>
          <button className="btn-sec-grande" style={{ width: 'auto' }} onClick={() => void carregar()}>Tentar de novo</button>
        </p>
      )}
      {aviso && (
        <p className="aviso-simples flex items-start justify-between gap-3" role="status">
          <span>{aviso}</span>
          <button className="link-discreto shrink-0" onClick={() => setAviso('')}>Fechar</button>
        </p>
      )}
      {jobs === null && !erro && <Esqueleto linhas={4} rotulo="Carregando os trabalhos…" />}

      {/* 072-B: "Nenhum trabalho ainda" só sem trabalho E sem cliente (cliente sem trabalho é card, 053-C) */}
      {jobs !== null && jobs.length === 0 && clientes.length === 0 && (
        <div className="cartao-pad grid justify-items-center gap-3 py-10 text-center">
          <Logo size={72} />
          <p className="cartao-titulo">Nenhum trabalho ainda</p>
          <p className="texto">Crie o primeiro: informe o imóvel e envie os documentos.</p>
          <button className="btn-verde" style={{ width: 'auto' }} onClick={() => ir('novo')}><Plus size={20} aria-hidden="true" /> Novo trabalho</button>
        </div>
      )}

      {jobs !== null && (jobs.length > 0 || clientes.length > 0) && (
        <>
          <div className="filtros-l1">
            <div className="abas-l1" role="tablist" aria-label="Trabalhos">
              <button type="button" role="tab" aria-selected={aba === 'andamento'} onClick={() => setAba('andamento')}>Em andamento</button>
              <button type="button" role="tab" aria-selected={aba === 'concluidos'} onClick={() => setAba('concluidos')}>Concluídos</button>
              <button type="button" role="tab" aria-selected={false} onClick={() => ir('propostas')}>Propostas</button>
            </div>
            <div className="busca-l1">
              <Search size={20} aria-hidden="true" />
              <label htmlFor="busca" className="sr-only">Buscar endereço ou cliente</label>
              <input id="busca" type="search" placeholder="Buscar endereço ou cliente" value={busca}
                     onChange={(e) => setBusca(e.target.value)} autoComplete="off" />
            </div>
          </div>
          {visiveis.length === 0 && cliVis.length === 0 && (
            <p className="texto" role="status">
              {busca ? 'Nenhum trabalho encontrado. ' : aba === 'concluidos' ? 'Nenhum trabalho concluído ainda.' : 'Nada em andamento.'}
              {busca && <button type="button" className="link-discreto" onClick={() => setBusca('')}>Limpar a busca</button>}
            </p>
          )}
          <ul className="lista-cartoes">
            {cliVis.map((c) => {
              const k = Math.max(0, ETAPAS_L1.indexOf(ROT_CLI[c.etapa] ?? 'Proposta'))
              return (
                <li key={`c-${c.id}`}>
                  <div className="cartao-l1 vez" role="link" tabIndex={0} aria-label={`Abrir conversa: ${c.nome}`}
                       onClick={() => ir('cliente', c.id)} onKeyDown={(e) => { if (e.key === 'Enter') ir('cliente', c.id) }}>
                    <span className="cartao-titulo">{c.imovel ? c.imovel.charAt(0).toUpperCase() + c.imovel.slice(1) : 'Imóvel ainda não informado'}</span>
                    <span className="cartao-sub">{[c.nome, MOD_CLI[c.modalidade] ?? ''].filter(Boolean).join(' · ')}</span>
                    <span className="pontos-l1" aria-label={`Etapa: ${ETAPAS_L1[k]}`}>
                      {ETAPAS_L1.map((e, x) => <span key={e} aria-hidden="true" className={`ponto ${x < k ? 'ponto-ok' : x === k ? 'ponto-now' : ''}`} />)}
                      <span className="etapa-l1">{ETAPAS_L1[k]}</span>
                    </span>
                    <button type="button" className="btn-verde" style={{ width: 'auto' }} onClick={(e) => { e.stopPropagation(); ir('cliente', c.id) }}>
                      {c.proximo && c.proximo !== 'Nada pendente' ? primeiraMaiuscula(c.proximo) : 'Abrir a conversa'}</button>
                  </div>
                </li>
              )
            })}
            {visiveis.map((j) => {
              const tipo = j.objeto_parte || j.tipo || ''                                   // 071-C7: um formato só, "Casa · Jardim Curitiba"
              const imovel = [tipo.charAt(0).toUpperCase() + tipo.slice(1), j.bairro].filter(Boolean).join(' · ') || 'Imóvel sem descrição'
              const vez = ehVez(j.proximo)
              const etapa = j.etapa_tela || 'Laudo'
              const k = Math.max(0, ETAPAS_L1.indexOf(etapa))
              return (
                <li key={j.id}>
                  <div className={`cartao-l1 ${vez ? 'vez' : ''}`} role="link" tabIndex={0} aria-label={`Abrir trabalho ${j.numero}: ${imovel}`}
                       onClick={() => abrir(j)} onKeyDown={(e) => { if (e.key === 'Enter') abrir(j) }}>
                    <span className="titulo-com-opcoes">
                      <span className="cartao-titulo">{imovel}</span>
                      <Opcoes job={j} titulo={imovel} entregue={!!j.entregue}
                              aoEditar={() => { pedirEdicao(j.id); ir('job', j.id) }}
                              aoApagado={(m) => { setAviso(m); void carregar() }} />
                    </span>
                    <span className="cartao-sub">{[nomeSolicitante(j.cliente), modalidade(j.modalidade)].filter(Boolean).join(' · ')}</span>
                    <span className="pontos-l1" aria-label={`Etapa: ${etapa}`}>
                      {ETAPAS_L1.map((e, x) => {
                        const st = j.etapas_st?.[x] ?? (x < k ? 'feito' : x === k ? 'atual' : '')
                        return <span key={e} aria-hidden="true" className={`ponto ${st === 'feito' ? 'ponto-ok' : st === 'atual' ? 'ponto-now' : st === 'fora' ? 'ponto-fora' : ''}`} />
                      })}
                      <span className="etapa-l1">{etapa}</span>
                      {j.etapas_st?.[3] === 'feito' && (   // 152-3: o laudo aprovado ganha o ✓ no cartão do trabalho
                        <span className="tag-contorno" style={{ color: '#14803F', borderColor: '#14803F', marginLeft: 8 }}>✓ Concluído</span>
                      )}
                      {j.etapas_st?.[3] === 'feito' && (   // 166-3: atalho da entrega (só depois do ✓)
                        <span style={{ marginLeft: 8 }}><AtalhoEntrega jobId={j.id} titulo={imovel} /></span>
                      )}
                      {j.etapa === 'entrega' && j.etapas_st?.[3] !== 'feito' && /PRONTO|PARCIAL/.test(j.status || '') && (
                        // 172-2: o mesmo [Baixar para a revisão humana] no cartão (conclui e baixa o Word)
                        <span style={{ marginLeft: 8 }} onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                          <BaixarRevisao jobId={j.id} compacto aoConcluir={() => void carregar()} /></span>
                      )}
                    </span>
                    {vez
                      ? <button type="button" className="btn-verde" style={{ width: 'auto' }} onClick={(e) => { e.stopPropagation(); abrir(j) }}>{j.proximo}</button>
                      : j.proximo ? <span className="espera-l1">{j.proximo}</span> : null}
                  </div>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </section>
  )
}

/** Primeiro nome do avaliador para o "Bom dia" (L1). */
function useEu(): string {
  const [n, setN] = useState('')
  useEffect(() => {
    get<{ dados?: { nome?: string } }>('/avaliadores/eu').then((r) => setN(String(r.dados?.nome || '').split(/\s+/)[0] || '')).catch(() => undefined)
  }, [])
  return n
}
