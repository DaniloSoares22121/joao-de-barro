/* ORDEM 184: Configurações › Tabela de preços.
 * Os serviços que o avaliador faz (as 4 modalidades da P7 e o que mais quiser, como um tipo de imóvel), com o valor
 * de cada um e, se quiser, o prazo em dias úteis e uma observação. A proposta de um trabalho novo já vem preenchida
 * por aqui; numa proposta dá para mudar só nela (Dados do cliente › Valor combinado). Remover pede confirmação (183). */
import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import Confirmar from './Confirmar'
import { ApiError, get, put } from './api'
import { useStore } from './store'

interface Linha { servico: string; nome: string; tipo: string; valor: string; prazo_dias: number | null; obs: string }
interface Resp { linhas: Linha[]; salva: boolean; servicos: { cod: string; nome: string }[] }

export default function TabelaPrecos() {
  const ir = useStore((s) => s.ir)
  const [r, setR] = useState<Resp | null>(null)
  const [linhas, setLinhas] = useState<Linha[]>([])
  const [mudou, setMudou] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; texto: string } | null>(null)
  const [salvando, setSalvando] = useState(false)
  const [remover, setRemover] = useState<number | null>(null)
  useEffect(() => {
    get<Resp>('/avaliadores/eu/tabela-precos').then((x) => { setR(x); setLinhas(x.linhas) })
      .catch(() => setMsg({ ok: false, texto: 'Não deu para abrir a tabela. Tente de novo.' }))
  }, [])
  const muda = (i: number, campo: keyof Linha, v: string) => {
    setMudou(true); setMsg(null)
    setLinhas((ls) => ls.map((l, k) => (k !== i ? l : {
      ...l, [campo]: campo === 'prazo_dias' ? (v.trim() === '' ? null : Number(v.replace(/\D/g, '')) || null) : v,
      ...(campo === 'servico' && v ? { nome: r?.servicos.find((s) => s.cod === v)?.nome ?? l.nome } : {}),
    })))
  }
  async function salvar() {
    setSalvando(true); setMsg(null)
    try {
      const x = await put<Resp>('/avaliadores/eu/tabela-precos', { linhas })
      setR(x); setLinhas(x.linhas); setMudou(false)
      setMsg({ ok: true, texto: 'Tabela salva. A proposta de um trabalho novo já vem com estes valores.' })
    } catch (e) { setMsg({ ok: false, texto: e instanceof ApiError ? e.message : 'Não deu para salvar. Tente de novo.' }) }
    finally { setSalvando(false) }
  }
  if (!r) return <p className="texto-grande" role="status">{msg?.texto ?? 'Abrindo…'}</p>
  const nomeLinha = (l: Linha, i: number) => l.nome || r.servicos.find((s) => s.cod === l.servico)?.nome || `linha ${i + 1}`
  return (
    <section className="tela-simples">
      <button type="button" className="voltar-jdb" onClick={() => ir('config')}>← Configurações</button>
      <h1 className="titulo-jdb">Tabela de preços</h1>
      <p className="sub-jdb">Os serviços que você faz e quanto cobra em cada um. A proposta de um trabalho novo já vem com o valor e o prazo daqui;
        numa proposta, dá para mudar só nela (Dados do cliente › Valor combinado).</p>
      {!r.salva && (
        <p className="aviso-simples" role="status">Ainda não salva: confira {linhas.some((l) => l.valor) ? 'os valores (são os que o sistema já usava como piso)' : 'e preencha os valores'} e toque em <b>Salvar a tabela</b>.
          Antes disso, a proposta não usa a tabela.</p>
      )}
      <ul className="grid gap-3" aria-label="Serviços e valores">
        {linhas.map((l, i) => (
          <li key={i} className="cartao-pad grid gap-2" aria-label={nomeLinha(l, i)}>
            <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))' }}>
              <label className="campo-bloco"><span className="bloco-rotulo">Serviço</span>
                <select className="campo-grande" value={l.servico} onChange={(e) => muda(i, 'servico', e.target.value)}>
                  {r.servicos.map((s) => <option key={s.cod} value={s.cod}>{s.nome}</option>)}
                  <option value="">Outro (escreva o nome)</option>
                </select></label>
              {!l.servico && (
                <label className="campo-bloco"><span className="bloco-rotulo">Nome do serviço</span>
                  <input className="campo-grande" value={l.nome} onChange={(e) => muda(i, 'nome', e.target.value)} placeholder="Ex.: Galpão" /></label>
              )}
              <label className="campo-bloco"><span className="bloco-rotulo">Tipo de imóvel (opcional)</span>
                <input className="campo-grande" value={l.tipo} onChange={(e) => muda(i, 'tipo', e.target.value)} placeholder="Ex.: galpão" /></label>
              <label className="campo-bloco"><span className="bloco-rotulo">Valor (R$)</span>
                <input className="campo-grande" inputMode="decimal" value={l.valor} onChange={(e) => muda(i, 'valor', e.target.value)} placeholder="Ex.: 600,00" /></label>
              <label className="campo-bloco"><span className="bloco-rotulo">Prazo (dias úteis após a visita)</span>
                <input className="campo-grande" inputMode="numeric" value={l.prazo_dias ?? ''} onChange={(e) => muda(i, 'prazo_dias', e.target.value)} placeholder="Ex.: 3" /></label>
            </div>
            <label className="campo-bloco"><span className="bloco-rotulo">Observação (opcional)</span>
              <input className="campo-grande" value={l.obs} onChange={(e) => muda(i, 'obs', e.target.value)} /></label>
            <button type="button" className="btn-sec btn-peq" style={{ justifySelf: 'start' }} onClick={() => setRemover(i)}>
              <Trash2 size={16} aria-hidden="true" /> Remover</button>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-sec-grande" style={{ width: 'auto' }}
                onClick={() => { setMudou(true); setLinhas((ls) => [...ls, { servico: '', nome: '', tipo: '', valor: '', prazo_dias: null, obs: '' }]) }}>
          <Plus size={20} aria-hidden="true" /> Adicionar serviço</button>
        <button type="button" className="btn-verde" style={{ width: 'auto' }} disabled={salvando || (r.salva && !mudou)} onClick={() => void salvar()}>
          {salvando ? 'Salvando…' : 'Salvar a tabela'}</button>
      </div>
      {msg && <p className={msg.ok ? 'aviso-simples' : 'aviso-impede'} role={msg.ok ? 'status' : 'alert'}>{msg.texto}</p>}
      {remover !== null && linhas[remover] && (
        <Confirmar titulo={`Remover “${nomeLinha(linhas[remover], remover)}” da tabela?`}
                   texto="A linha sai da lista. Só vale depois de tocar em Salvar a tabela; antes disso, é só sair sem salvar."
                   rotuloConfirmar="Remover" perigo
                   aoConfirmar={() => { setLinhas((ls) => ls.filter((_, k) => k !== remover)); setMudou(true); setRemover(null) }}
                   aoCancelar={() => setRemover(null)} />
      )}
    </section>
  )
}
