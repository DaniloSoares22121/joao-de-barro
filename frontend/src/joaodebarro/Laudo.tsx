/* ORDEM 053 (L10): "Seu laudo está pronto". Miniatura da 1ª página e, logo abaixo do título, 152: [Abrir o PDF] ·
 * [Abrir o laudo editável] · [✓ Aprovar] por último — a correção agora é manual, no editável (saiu o "pedir ajuste" e o
 * ciclo "O que mudou na Revisão N / Desfazer"). Os 3 números escritos como no PDF (054 item 4). Pontos de
 * atenção = os cartões da 045 que ainda estão abertos; "Conferido sozinho" = ajustes do sistema. */
import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowLeft, Check } from 'lucide-react'
import { ApiError, baixar, baixarRaw, get } from './api'
import { canalEditor } from './EditorLaudo'
import { BaixarRevisao, CaixaEntrega } from './Downloads'
import type { Simples } from './PendenciasSimples'
import { modalidade, moeda } from './rotulos'
import { useStore } from './store'
import type { Detalhe, ResultadoEntrega } from './tipos'

const erroDe = (e: unknown) => (e instanceof ApiError ? e.message : 'Não deu certo. Tente de novo.')

export default function Laudo() {
  const jid = useStore((s) => s.jobId) ?? ''
  const ir = useStore((s) => s.ir)
  const j = encodeURIComponent(jid)
  const [d, setD] = useState<Detalhe | null>(null)
  const [p, setP] = useState<Simples | null>(null)
  const [capa, setCapa] = useState('')
  const [msg, setMsg] = useState('')
  const [erro, setErro] = useState('')
  useEffect(() => {
    get<Detalhe>(`/jobs/${j}`).then(setD).catch((e) => setErro(erroDe(e)))
    get<Simples>(`/jobs/${j}/pendencias-simples`).then(setP).catch(() => undefined)
    let u = ''
    baixarRaw(`/jobs/${j}/capa-pdf.png`).then(({ blob }) => { u = URL.createObjectURL(blob); setCapa(u) }).catch(() => undefined)
    return () => { if (u) URL.revokeObjectURL(u) }
  }, [j])
  useEffect(() => {                      // 151-5: [Concluir a revisão humana] na aba do editável → PDF final aqui
    if (typeof BroadcastChannel === 'undefined') return undefined
    const c = new BroadcastChannel(canalEditor(jid))
    c.onmessage = (ev) => {
      const m = ev.data as { tipo?: string; texto?: string } | null
      if (m?.tipo !== 'concluido') return
      setMsg(m.texto || 'Revisão humana concluída: PDF final pronto. Abra e aprove.')
      get<Detalhe>(`/jobs/${j}`).then(setD).catch(() => undefined)
      let u = ''
      baixarRaw(`/jobs/${j}/capa-pdf.png`).then(({ blob }) => { u = URL.createObjectURL(blob); setCapa(u) }).catch(() => undefined)
    }
    return () => c.close()
  }, [j, jid])
  if (!d) return <p className="texto" role="status">{erro || 'Abrindo…'}</p>

  const ent = (d.etapas.entrega ?? null) as ResultadoEntrega | null
  const pdf = (ent?.arquivos ?? []).find((a) => a.toLowerCase().endsWith('.pdf') && !a.toLowerCase().endsWith('_assinado.pdf'))
  const r = d.resultado
  const dados = d.job.dados
  const imovel = [(dados as { objeto_parte?: string }).objeto_parte || dados.tipo, dados.bairro].filter(Boolean).join(' – ')
  const nRefs = d.candidatos.filter((c) => c.escolhido).length || d.candidatos.filter((c) => c.decisao === 'entra').length
  const aprovado = !!d.tela?.aprovado

  async function abrirPdf() {
    if (!pdf) return
    try { window.open(URL.createObjectURL(new Blob([await baixar(jid, pdf)], { type: 'application/pdf' })), '_blank', 'noopener') } catch (e) { setErro(erroDe(e)) }
  }

  return (
    <section className="tela-simples tela-larga">
      <button type="button" className="voltar-jdb" onClick={() => ir('job', jid)}><ArrowLeft size={18} aria-hidden="true" /> Trabalho</button>
      <div>
        <h1 className="titulo-jdb inline-flex flex-wrap items-center gap-3">{aprovado ? 'Laudo concluído ✓' : 'Seu laudo está pronto'}
          {(d.tela?.revisao ?? 0) > 0 && <span className="tag-contorno">Revisão {d.tela?.revisao}</span>}</h1>
        <p className="sub-jdb">{[imovel, modalidade(dados.modalidade)].filter(Boolean).join(' · ')}</p>
      </div>
      {erro && <p className="aviso-impede" role="alert">{erro}</p>}
      {msg && <p className="aviso-simples" role="status">{msg}</p>}
      <div className="proximo-passo l10">
        <div className="l10-capa">
          {capa ? <img src={capa} alt="Primeira página do laudo" /> : <div className="l10-capa-vazia">Prévia do PDF</div>}
        </div>
        <div className="l10-lado">
          <div className="l10-botoes">
            <button type="button" className="btn-sec-grande" disabled={!pdf} onClick={() => void abrirPdf()}>Abrir o PDF</button>
            {/* 172-2: o download para a revisão humana conclui (saíram o editável e o Aprovar) */}
            {!aprovado && pdf && <BaixarRevisao jobId={jid} compacto aoConcluir={(m) => { setMsg(m); ir('job', jid) }} />}
          </div>
          {r && (
            <dl className="l10-numeros">
              <div><dt>Valor de mercado</dt><dd className="barro">{moeda(r.valor_adotado)}</dd></div>
              <div><dt>Faixa</dt><dd>{moeda(r.valor_min)} a {moeda(r.valor_max)}</dd></div>
              <div><dt>Referenciais</dt><dd>{nRefs}</dd></div>
            </dl>
          )}
        </div>
      </div>
      {aprovado && <CaixaEntrega jobId={jid} />}{/* 166-2: depois do ✓, a entrega */}
      {p && p.cards.length > 0 && (
        <details className="cartao-pad pontos-atencao">
          <summary><AlertTriangle size={20} aria-hidden="true" /> Pontos de atenção ({p.cards.length})</summary>
          <ul className="lista-simples">
            {p.cards.map((c) => <li key={c.chave}><span>{c.titulo}</span></li>)}
          </ul>
          <button type="button" className="btn-sec-grande" onClick={() => ir('job', jid)}>Resolver no trabalho</button>
        </details>
      )}
      {p?.linha_sozinho && <p className="small-jdb inline-flex items-center gap-1"><Check size={18} aria-hidden="true" /> {p.linha_sozinho.replace('Corrigindo sozinho', 'Conferido sozinho')}</p>}
    </section>
  )
}
