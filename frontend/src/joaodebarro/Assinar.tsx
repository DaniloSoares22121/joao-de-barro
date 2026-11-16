/* ORDEM 053 (L12): "Assinar e entregar" em 3 passos. 1) assinar no gov.br (o JdB nunca assina
 * pelo avaliador, D-086); 2) enviar o PDF assinado — o sistema confere a assinatura; 3) entregue:
 * baixar PDF (o assinado, quando houver), Word e planilha. */
import { useEffect, useState } from 'react'
import { ArrowLeft, Check, ExternalLink } from 'lucide-react'
import { ApiError, baixar, get, postForm } from './api'
import { salvarBlob } from './Entrega'
import { useStore } from './store'
import type { Detalhe, ResultadoEntrega } from './tipos'

const erroDe = (e: unknown) => (e instanceof ApiError ? e.message : 'Não deu certo. Tente de novo.')
const ext = (n: string) => (n.split('.').pop() || '').toLowerCase()

function Passo({ n, feito, titulo, children }: { n: number; feito: boolean; titulo: string; children: React.ReactNode }) {
  return (
    <section className={`passo-l12 ${feito ? 'feito' : ''}`}>
      <span className="num-l12" aria-hidden="true">{feito ? <Check size={24} /> : n}</span>
      <div className="grid gap-2">
        <h2 className="titulo-cartao">{titulo}{feito ? <span className="sr-only"> (feito)</span> : null}</h2>
        {children}
      </div>
    </section>
  )
}

export default function Assinar() {
  const jid = useStore((s) => s.jobId) ?? ''
  const ir = useStore((s) => s.ir)
  const j = encodeURIComponent(jid)
  const [d, setD] = useState<Detalhe | null>(null)
  const [info, setInfo] = useState<{ assinador: string; instrucao: string[] } | null>(null)
  const [msg, setMsg] = useState('')
  const [erro, setErro] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const carregar = () => get<Detalhe>(`/jobs/${j}`).then(setD).catch((e) => setErro(erroDe(e)))
  useEffect(() => { void carregar(); get<{ assinador: string; instrucao: string[] }>('/assinatura/instrucao').then(setInfo).catch(() => undefined) }, [j])  // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return <p className="texto" role="status">{erro || 'Abrindo…'}</p>

  const ent = (d.etapas.entrega ?? null) as ResultadoEntrega | null
  const arqs = ent?.arquivos ?? []
  const assinado = ent?.assinado || arqs.find((a) => a.toLowerCase().endsWith('_assinado.pdf')) || ''
  const pdf = assinado || arqs.find((a) => ext(a) === 'pdf') || ''
  const word = arqs.find((a) => ext(a) === 'docx')
  const planilha = arqs.find((a) => ext(a) === 'xlsx')
  const dados = d.job.dados
  const imovel = [(dados as { objeto_parte?: string }).objeto_parte || dados.tipo, dados.bairro].filter(Boolean).join(' – ')

  async function enviar(f?: File) {
    if (!f) return
    setErro(''); setMsg(''); setOcupado(true)
    try {
      const fd = new FormData(); fd.append('arquivo', f)
      const r = await postForm<{ arquivo: string }>(`/jobs/${j}/assinado`, fd)
      setMsg(`Assinatura encontrada · ${r.arquivo}`); void carregar()
    } catch (e) { setErro(erroDe(e)) } finally { setOcupado(false) }
  }
  async function baixarArq(nome?: string) {
    if (!nome) return
    try { salvarBlob(await baixar(jid, nome), nome) } catch (e) { setErro(erroDe(e)) }
  }

  return (
    <section className="tela-simples tela-larga">
      <button type="button" className="voltar-jdb" onClick={() => ir('job', jid)}><ArrowLeft size={18} aria-hidden="true" /> Trabalho</button>
      <div>
        <h1 className="titulo-jdb">Assinar e entregar</h1>
        <p className="sub-jdb">{imovel ? `${imovel} · ` : ''}3 passos</p>
      </div>
      {erro && <p className="aviso-impede" role="alert">{erro}</p>}
      <Passo n={1} feito={!!assinado} titulo="Assine no gov.br">
        <p className="sub-jdb">Você assina. O JdB nunca assina por você.</p>
        {info && (
          <a href={info.assinador} target="_blank" rel="noopener noreferrer" className="btn-sec-grande inline-flex">
            Abrir o assinador <ExternalLink size={18} aria-hidden="true" />
          </a>
        )}
      </Passo>
      <Passo n={2} feito={!!assinado} titulo="Envie o PDF assinado">
        {assinado
          ? <p className="assinatura-ok"><Check size={20} aria-hidden="true" /> Assinatura encontrada · {assinado}</p>
          : (
            <label className="envio-l12">
              {ocupado ? 'Conferindo a assinatura…' : 'Escolher o PDF assinado'}
              <input type="file" accept="application/pdf,.pdf" hidden disabled={ocupado} onChange={(e) => void enviar(e.target.files?.[0])} />
            </label>
          )}
        {msg && !assinado && <p className="assinatura-ok" role="status">{msg}</p>}
      </Passo>
      <Passo n={3} feito={false} titulo={assinado ? 'Entregue' : 'Entregar'}>
        <div className="botoes-l12">
          <button type="button" className="btn-sec-grande" disabled={!pdf} onClick={() => void baixarArq(pdf)}>Baixar PDF</button>
          <button type="button" className="btn3-jdb" disabled={!word} onClick={() => void baixarArq(word)}>Baixar Word</button>
          <button type="button" className="btn3-jdb" disabled={!planilha} onClick={() => void baixarArq(planilha)}>Baixar planilha</button>
        </div>
        {!assinado && <p className="small-jdb">O PDF para o cliente é o assinado: assine antes de entregar.</p>}
      </Passo>
    </section>
  )
}
