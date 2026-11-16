/* ORDEM 040 / D-087: "Planos" e "Meu plano". Só local: a troca de plano é simulada e nada é
 * cobrado (pagamento e publicação são a etapa 5, com o Danilo). Regras de tela (D-101): letra
 * grande, pouco texto, um próximo passo com botão verde; detalhes recolhidos. */
import { useCallback, useEffect, useState } from 'react'
import { get, post } from './api'
import { useStore } from './store'

interface Plano { nome: string; preco: number; incluidos: number; extra: number; destaque?: boolean }
interface Conta { mes: string; plano: string; nome: string; limite: number; laudos: number; gratis: number; incluidos: number; extras: number; preco_plano: number; preco_extra: number; total: number; aviso: { texto: string; para: string; nome: string } | null }
interface Margem {
  laudos_medidos: number; minimo_para_medir: number; provisorio: boolean; custo_medio_ia_usd: number
  custo_servidor_usd: number; cotacao: number; mais_caro: { numero: number; custo_ia_usd: number; modalidade: string } | null
  planos: { plano: string; nome: string; receita_por_laudo: number; custo_por_laudo_brl: number; margem_por_laudo: number; margem_extra: number }[]
}

const rs = (v: number) => v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
const nomeMes = (m: string) => `${MESES[Number(m.slice(5, 7)) - 1]} de ${m.slice(0, 4)}`

export function Bloco({ rotulo, valor, nota }: { rotulo: string; valor: string; nota?: string }) {
  return (
    <div className="bloco-valor">
      <p className="bloco-rotulo">{rotulo}</p>
      <p className="bloco-numero">{valor}</p>
      {nota && <p className="bloco-nota">{nota}</p>}
    </div>
  )
}

export function MeuPlano() {
  const ir = useStore((s) => s.ir)
  const [d, setD] = useState<{ plano: string; mes: Conta; historico: Conta[]; sem_limite?: boolean; regra?: string } | null>(null)
  const [m, setM] = useState<Margem | null>(null)
  const [erro, setErro] = useState('')
  useEffect(() => {
    get<{ plano: string; mes: Conta; historico: Conta[]; sem_limite?: boolean; regra?: string }>('/meu-plano').then(setD).catch(() => setErro('Não consegui abrir o seu plano.'))
    get<Margem>('/planos/margem').then(setM).catch(() => undefined)
  }, [])
  if (erro) return <p className="texto-grande">{erro}</p>
  if (!d) return <p className="texto-grande" role="status">Abrindo…</p>
  const c = d.mes
  return (
    <section className="tela-simples">
      <h1 className="titulo-tela">{d.sem_limite ? 'Conta do dono · sem limite' : 'Meu plano'}</h1>
      <p className="linha-tela">{d.sem_limite ? nomeMes(c.mes) : `Plano ${c.nome} · ${nomeMes(c.mes)}`}</p>

      {/* 160-1: a conta do dono não tem plano, limite nem conta a pagar — fica só a medição */}
      {!d.sem_limite && <div className="proximo-passo">
        <p className="bloco-rotulo">Próximo passo</p>
        {c.aviso ? (
          <>
            <p className="texto-grande">{c.aviso.texto}</p>
            <button type="button" className="btn-verde" onClick={() => ir('planos')}>Ver planos</button>
          </>
        ) : (
          <>
            <p className="texto-grande">Seu plano está certo para este mês.</p>
            <button type="button" className="btn-sec-grande" onClick={() => ir('planos')}>Ver planos</button>
          </>
        )}
      </div>}

      {/* 155-2 / 156-1: a regra da contagem, em português simples; e a conta do dono */}
      {d.sem_limite && <p className="aviso-simples" role="status">A contagem abaixo é só medição: não bloqueia nem cobra.</p>}
      {d.regra && <p className="texto">{d.regra}</p>}
      <div className="grade-blocos">
        <Bloco rotulo="Laudos no mês" valor={String(c.laudos)} nota={c.gratis && !d.sem_limite ? '1 grátis (o primeiro)' : undefined} />
        {!d.sem_limite && <>
          <Bloco rotulo="Incluídos" valor={String(c.incluidos)} nota={`de ${c.limite} no plano`} />
          <Bloco rotulo="Extras" valor={String(c.extras)} nota={c.extras ? `${rs(c.preco_extra)} cada` : undefined} />
          <Bloco rotulo="Total do mês" valor={rs(c.total)} />
        </>}
      </div>

      <details className="detalhes">
        <summary>Ver histórico e custos</summary>
        <div className="detalhes-corpo">
          <h2 className="subtitulo">Meses</h2>
          {d.historico.length === 0 ? <p className="texto">Nenhum laudo ainda.</p> : (
            <ul className="lista-simples">
              {d.historico.map((h) => (
                <li key={h.mes}><span>{nomeMes(h.mes)}</span><span>{h.laudos} {h.laudos === 1 ? 'laudo' : 'laudos'}</span>{!d.sem_limite && <strong>{rs(h.total)}</strong>}</li>
              ))}
            </ul>
          )}
          {m && (
            <>
              <h2 className="subtitulo">Margem</h2>
              {m.provisorio && <p className="aviso-simples">Preços provisórios: medir {m.minimo_para_medir} laudos (temos {m.laudos_medidos}).</p>}
              <ul className="lista-simples">
                <li><span>Custo médio de IA por laudo</span><strong>US$ {m.custo_medio_ia_usd.toFixed(2)}</strong></li>
                {m.mais_caro && <li><span>Laudo mais caro (nº {m.mais_caro.numero})</span><strong>US$ {m.mais_caro.custo_ia_usd.toFixed(2)}</strong></li>}
                <li><span>Servidor (estimado) por laudo</span><strong>US$ {m.custo_servidor_usd.toFixed(2)}</strong></li>
                {m.planos.map((p) => (
                  <li key={p.plano}><span>{p.nome}: sobra por laudo</span><strong>{rs(p.margem_por_laudo)}</strong></li>
                ))}
              </ul>
            </>
          )}
        </div>
      </details>
    </section>
  )
}

export function Planos() {
  const ir = useStore((s) => s.ir)
  const [d, setD] = useState<{ ordem: string[]; planos: Record<string, Plano>; atual: string; comparacao_avulso_10: number } | null>(null)
  const [msg, setMsg] = useState('')
  const carregar = useCallback(() => { get<typeof d>('/planos').then(setD).catch(() => undefined) }, [])
  useEffect(carregar, [carregar])
  async function escolher(p: string) {
    await post('/planos/trocar', { plano: p })
    setMsg('Plano trocado (simulação: nada foi cobrado).')
    carregar()
  }
  if (!d) return <p className="texto-grande" role="status">Abrindo…</p>
  return (
    <section className="tela-simples">
      <h1 className="titulo-tela">Planos</h1>
      <p className="linha-tela">Escolha quantos laudos por mês.</p>
      <div className="grade-planos">
        {d.ordem.map((k) => {
          const p = d.planos[k]
          const atual = k === d.atual
          return (
            <div key={k} className={`cartao-plano ${p.destaque ? 'cartao-plano-destaque' : ''}`}>
              {p.destaque && <p className="selo-destaque">Mais escolhido</p>}
              <h2 className="subtitulo">{p.nome}</h2>
              <p className="bloco-numero">{p.preco ? rs(p.preco) : 'R$ 0'}<span className="por-mes">/mês</span></p>
              <p className="texto-grande">{p.incluidos ? `${p.incluidos} laudos incluídos` : 'Sem laudos incluídos'}</p>
              <p className="texto">Laudo extra: {rs(p.extra)}</p>
              {k === 'avulso' && <p className="texto">10 laudos = {rs(d.comparacao_avulso_10)}</p>}
              {atual ? <p className="selo-atual">Seu plano</p> : (
                <button type="button" className={p.destaque ? 'btn-verde' : 'btn-sec-grande'} onClick={() => void escolher(k)}>
                  Escolher {p.nome}
                </button>
              )}
            </div>
          )
        })}
      </div>
      <p className="texto">Primeiro laudo grátis. Troca simulada: nada é cobrado.</p>
      {msg && <p className="aviso-simples" role="status">{msg}</p>}
      <button type="button" className="btn-sec-grande" onClick={() => ir('plano')}>Voltar para Meu plano</button>
    </section>
  )
}
