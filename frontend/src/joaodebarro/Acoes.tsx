/* Controle do avaliador sobre um trabalho finalizado: editar campo extraído, escolher
 * referenciais, recalcular/regerar, pendências acionáveis, editar dados do trabalho, aviso de fim. */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ApiError, post, put } from './api'
import Confirmar from './Confirmar'
import { unitario } from './calculo'
import {
  deveNotificar, erroEscolha, erroFonte, formDeDados, payloadEdicao, rotuloAcao,
} from './controle'
import { ZonasArquivos, ehAuth, mensagemErro, useEnvio, type Tipo } from './Envio'
import { plural,
  MODALIDADES, STATUS_CANCELADO, STATUS_FINAIS, TEXTO_CANCELADO, TEXTO_ERRO_TECNICO, moeda, nomeSolicitante,
  textoPendencia,
} from './rotulos'
import { useStore } from './store'
import type { AcaoPendencia, Campo, Detalhe, Pendencia, Referencial } from './tipos'
import {
  AJUDA_CHECKLIST, AJUDA_OBS_VISTORIA, dataISOValida, hojeISO, normalizarPin, pinValido, type FormTrabalho,
} from './validacao'

const erroTxt = (e: unknown) => (e instanceof ApiError && e.status === 409
  ? 'O trabalho está em execução; aguarde terminar.' : mensagemErro(e))

function Erro({ msg }: { msg: string }) {
  return msg ? <p className="erro-txt" role="alert">{msg}</p> : null
}

const dataBRHoje = () => hojeISO().split('-').reverse().join('/')

// ---------------------------------------------------------------- C1: editar campo
export function EditorCampo({ jobId, campo, nome, arquivos, aoSalvar, aoCancelar }: {
  jobId: string; campo: Campo | null; nome: string
  arquivos: Detalhe['arquivos']; aoSalvar: (novo?: string) => void; aoCancelar: () => void
}) {
  const [valor, setValor] = useState(campo?.valor == null ? '' : String(campo.valor))
  const [origem, setOrigem] = useState<'documento' | 'vistoria'>(campo?.origem === 'vistoria' ? 'vistoria' : 'documento')
  const [fonte, setFonte] = useState(campo && (campo.origem === 'documento' || campo.origem === 'vistoria') ? campo.fonte : '')
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)
  const id = `ed-${nome.replace(/\W+/g, '-')}`

  async function salvar() {
    const ef = erroFonte(origem, fonte, arquivos)
    if (ef) { setErro(ef); return }
    setSalvando(true)
    setErro('')
    try {
      await put(`/jobs/${encodeURIComponent(jobId)}/campos/${encodeURIComponent(nome)}`,
        { valor: valor.trim() || null, origem, fonte: fonte.trim() })
      aoSalvar(valor.trim())
    } catch (e) {
      if (!ehAuth(e)) setErro(erroTxt(e))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <div className="mt-2 space-y-2 rounded-lg border border-stone-200 bg-stone-50 p-3" role="group" aria-label={`Editar ${nome}`}>
      <div className="grid gap-2 sm:grid-cols-2">
        <div>
          <label className="rotulo" htmlFor={`${id}-v`}>Valor{campo?.unidade ? ` (${campo.unidade})` : ''}</label>
          <input id={`${id}-v`} className="input" value={valor} onChange={(e) => setValor(e.target.value)} autoFocus />
        </div>
        <div>
          <label className="rotulo" htmlFor={`${id}-o`}>Origem</label>
          <select id={`${id}-o`} className="input" value={origem}
                  onChange={(e) => setOrigem(e.target.value as 'documento' | 'vistoria')}>
            <option value="documento">Documento</option>
            <option value="vistoria">Vistoria</option>
          </select>
        </div>
      </div>
      <div>
        <label className="rotulo" htmlFor={`${id}-f`}>Fonte</label>
        <input id={`${id}-f`} className="input" value={fonte} list={`${id}-l`} onChange={(e) => setFonte(e.target.value)}
               placeholder={origem === 'vistoria' ? `vistoria do avaliador em ${dataBRHoje()}` : 'documento/iptu.pdf p. 1'} />
        <datalist id={`${id}-l`}>
          {origem === 'vistoria' && <option value={`vistoria do avaliador em ${dataBRHoje()}`} />}
          {arquivos.filter((a) => origem === 'documento' || a.tipo === 'foto').map((a) => <option key={a.id} value={a.caminho} />)}
        </datalist>
        <p className="ajuda">Cite um arquivo enviado{origem === 'vistoria' ? ' (foto) ou “vistoria do avaliador em dd/mm/aaaa”' : ''}. Informação verbal não é fonte.</p>
      </div>
      <Erro msg={erro} />
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-sec btn-peq" onClick={aoCancelar} disabled={salvando}>Cancelar</button>
        <button type="button" className="btn btn-peq" onClick={() => void salvar()} disabled={salvando}>
          {salvando ? 'Salvando…' : 'Salvar'}
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- C2: escolher referenciais
export function EscolhaReferenciais({ jobId, refs, unitarioAtual, aoSalvar, children }: {
  jobId: string; refs: Referencial[]; unitarioAtual?: string | number | null
  aoSalvar: (msg: string) => void; children: (r: Referencial, marcado: boolean, alternar: () => void) => ReactNode
}) {
  const [marcados, setMarcados] = useState<Set<number>>(() => new Set(refs.filter((r) => r.escolhido).map((r) => r.n)))
  const [unit, setUnit] = useState('')
  const [just, setJust] = useState('')
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)
  const original = refs.filter((r) => r.escolhido).map((r) => r.n).sort().join(',')
  const mudou = [...marcados].sort().join(',') !== original || unit.trim() !== ''
  const alternar = (n: number) => setMarcados((m) => {
    const x = new Set(m)
    if (x.has(n)) x.delete(n)
    else x.add(n)
    return x
  })
  const us = refs.filter((r) => marcados.has(r.n)).map(unitario).filter((u): u is number => u !== null)

  async function salvar() {
    const e = erroEscolha(marcados, refs, unit)
    if (e) { setErro(e); return }
    setSalvando(true)
    setErro('')
    try {
      await put(`/jobs/${encodeURIComponent(jobId)}/referenciais`, {
        escolhidos: [...marcados], unitario_adotado: unit.trim() || null, justificativa: just.trim() || null })
      setUnit('')
      aoSalvar('Escolha salva. Toque em “Recalcular” para refazer o cálculo e o laudo.')
    } catch (err) {
      if (!ehAuth(err)) setErro(erroTxt(err))
    } finally {
      setSalvando(false)
    }
  }

  const ordenados = [...refs].sort((a, b) => Number(b.escolhido) - Number(a.escolhido) || a.n - b.n)
  return (
    <div className="space-y-3">
      <ul className="space-y-2">{ordenados.map((r) => children(r, marcados.has(r.n), () => alternar(r.n)))}</ul>
      <div className="space-y-2 rounded-lg border border-stone-200 bg-stone-50 p-3">
        <p className="text-sm text-stone-700">
          {plural(marcados.size, 'marcado', 'marcados')}{us.length ? ` · unitário de ${moeda(Math.min(...us))} a ${moeda(Math.max(...us))}/m²` : ''}
          {unitarioAtual != null && unitarioAtual !== '' ? ` · adotado hoje ${moeda(unitarioAtual)}/m²` : ''}
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          <div>
            <label className="rotulo" htmlFor="esc-unit">Unitário adotado (opcional, R$/m²)</label>
            <input id="esc-unit" className="input" inputMode="decimal" value={unit} placeholder="média dos escolhidos"
                   onChange={(e) => setUnit(e.target.value)} />
          </div>
          <div>
            <label className="rotulo" htmlFor="esc-just">Justificativa (opcional)</label>
            <input id="esc-just" className="input" value={just} onChange={(e) => setJust(e.target.value)} />
          </div>
        </div>
        <Erro msg={erro} />
        <div className="flex justify-end">
          <button type="button" className="btn btn-peq" disabled={salvando || !mudou} onClick={() => void salvar()}>
            {salvando ? 'Salvando…' : 'Salvar escolha'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- C3: recalcular / regerar
const MSG_REABRIR: Record<string, string> = {
  triagem: 'Refazendo a triagem: os documentos serão conferidos de novo e o trabalho continua.',
  calculo: 'Recalculando: o cálculo e o laudo serão refeitos.',
  redacao: 'Regerando o documento a partir da redação.',
}

export function BotoesReabrir({ jobId, aoReabrir, aoEditarTrabalho, aoEnviarArquivos, bloqueado = false }: {
  jobId: string; aoReabrir: (msg: string) => void; aoEditarTrabalho: () => void
  /** Abre as caixas de envio (documento esquecido etc.). */
  aoEnviarArquivos: () => void
  /** Triagem bloqueada: "Refazer triagem" vira a ação principal. */
  bloqueado?: boolean
}) {
  const [ocupado, setOcupado] = useState<string | null>(null)
  const [erro, setErro] = useState('')
  async function reabrir(etapa: 'triagem' | 'calculo' | 'redacao') {
    setErro('')
    setOcupado(etapa)
    try {
      await post(`/jobs/${encodeURIComponent(jobId)}/reabrir`, { etapa })
      aoReabrir(MSG_REABRIR[etapa])
    } catch (e) {
      if (!ehAuth(e)) setErro(erroTxt(e))
    } finally {
      setOcupado(null)
    }
  }
  const triagem = (
    <button type="button" className={bloqueado ? 'btn w-full sm:w-auto' : 'btn-sec'} disabled={!!ocupado}
            onClick={() => void reabrir('triagem')}>
      {ocupado === 'triagem' ? 'Enviando…' : 'Conferir os documentos de novo'}
    </button>
  )
  return (
    <section className="cartao-pad space-y-2" aria-labelledby="sec-reabrir">
      <h3 className="titulo-sec" id="sec-reabrir">Refazer</h3>
      {bloqueado
        ? (
          <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
            <p className="text-sm text-amber-900">
              Resolva as pendências (envie o documento que falta ou corrija os dados) e toque em “Conferir os documentos de novo”.
            </p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <button type="button" className="btn-sec w-full sm:w-auto" disabled={!!ocupado} onClick={aoEnviarArquivos}>
                Enviar arquivos
              </button>
              {triagem}
            </div>
          </div>
        )
        : <p className="text-sm text-stone-500">O texto do laudo se corrige no Word, depois de [Baixar para a revisão humana].</p>}
      {/* 153-1: saíram "Recalcular", "Regerar documento" e o "Conferir os documentos de novo" fora do bloqueio —
          nenhum botão manda a IA refazer o laudo inteiro. */}
      <div className={`grid gap-2 ${bloqueado ? 'sm:grid-cols-3' : 'sm:grid-cols-2 lg:grid-cols-3'}`}>
        <button type="button" className="btn-sec" disabled={!!ocupado} onClick={aoEditarTrabalho}>Editar dados do trabalho</button>
        {!bloqueado && (
          <button type="button" className="btn-sec" disabled={!!ocupado} onClick={aoEnviarArquivos}>Enviar arquivos</button>
        )}
      </div>
      <Erro msg={erro} />
    </section>
  )
}

// ---------------------------------------------------------------- erro técnico: tentar de novo
export function ErroTecnico({ jobId, etapa, aoReabrir }: { jobId: string; etapa: string; aoReabrir: (msg: string) => void }) {
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState('')
  async function tentar() {
    setErro('')
    setOcupado(true)
    try {
      await post(`/jobs/${encodeURIComponent(jobId)}/reabrir`, { etapa })
      aoReabrir('Tentando de novo: o trabalho continua de onde parou.')
    } catch (e) {
      if (!ehAuth(e)) setErro(erroTxt(e))
    } finally {
      setOcupado(false)
    }
  }
  return (
    <section className="faixa-erro space-y-2" aria-labelledby="sec-erro-tecnico" role="alert">
      <h2 id="sec-erro-tecnico" className="text-sm font-semibold">Erro técnico</h2>
      <p>{TEXTO_ERRO_TECNICO} Toque em “Tentar de novo” para continuar de onde parou.</p>
      <button type="button" className="btn" disabled={ocupado} onClick={() => void tentar()}>
        {ocupado ? 'Enviando…' : 'Tentar de novo'}
      </button>
      <Erro msg={erro} />
    </section>
  )
}

// ---------------------------------------------------------------- cancelado: reabrir
export function Cancelado({ jobId, aoReabrir }: { jobId: string; aoReabrir: (msg: string) => void }) {
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState('')
  async function reabrir() {
    setErro('')
    setOcupado(true)
    try {
      await post(`/jobs/${encodeURIComponent(jobId)}/retomar`)
      aoReabrir('Reaberto: o trabalho continua de onde parou.')
    } catch (e) {
      if (!ehAuth(e)) setErro(erroTxt(e))
    } finally {
      setOcupado(false)
    }
  }
  return (
    <section className="faixa-aviso space-y-2" aria-labelledby="sec-cancelado" role="status">
      <h2 id="sec-cancelado" className="text-sm font-semibold">Trabalho cancelado</h2>
      <p>{TEXTO_CANCELADO}</p>
      <button type="button" className="btn" disabled={ocupado} onClick={() => void reabrir()}>
        {ocupado ? 'Enviando…' : 'Reabrir'}
      </button>
      <Erro msg={erro} />
    </section>
  )
}

// ---------------------------------------------------------------- gerir: editar dados / excluir
/** ORDEM 028-5: "Duplicar trabalho" (cópia com nº novo; o original não muda). */
function Duplicar({ jobId, numero, livre }: { jobId: string; numero: number; livre: boolean }) {
  const ir = useStore((s) => s.ir)
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState('')
  async function duplicar() {
    setErro('')
    setOcupado(true)
    try {
      const r = await post<{ id: string; numero: number }>(`/jobs/${encodeURIComponent(jobId)}/duplicar`)
      ir('job', r.id)
    } catch (e) {
      if (!ehAuth(e)) setErro(erroTxt(e))
    } finally {
      setOcupado(false)
    }
  }
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <button type="button" className="btn-sec btn-peq" disabled={!livre || ocupado} onClick={() => void duplicar()}
              title={`Cria uma cópia do nº ${numero} para testar; o original não muda`}>
        {ocupado ? 'Duplicando…' : 'Duplicar trabalho'}
      </button>
      <span className="text-xs text-[var(--cinza)]">Cópia de teste com número novo; o original não muda.</span>
      <Erro msg={erro} />
    </div>
  )
}

export function GerirTrabalho({ jobId, numero, livre, mostrarEditar, aoEditarTrabalho, podeCancelar = false, aoCancelar }: {
  jobId: string; numero: number; livre: boolean; mostrarEditar: boolean; aoEditarTrabalho: () => void
  /** Rodando, na fila ou esperando (Coletor/avaliador): mostra "Cancelar". */
  podeCancelar?: boolean; aoCancelar?: (msg: string) => void
}) {
  const ir = useStore((s) => s.ir)
  const [perguntando, setPerguntando] = useState(false)
  const [cancelando, setCancelando] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const [erro, setErro] = useState('')
  async function cancelar() {
    setErro('')
    setOcupado(true)
    try {
      const r = await post<{ status: string }>(`/jobs/${encodeURIComponent(jobId)}/cancelar`)
      setCancelando(false)
      aoCancelar?.(r.status === STATUS_CANCELADO ? 'Trabalho cancelado.'
        : 'Cancelamento pedido: o trabalho para assim que terminar a etapa em andamento.')
    } catch (e) {
      if (!ehAuth(e)) setErro(mensagemErro(e))
    } finally {
      setOcupado(false)
    }
  }
  async function excluir() {
    setErro('')
    setOcupado(true)
    try {
      await post(`/jobs/${encodeURIComponent(jobId)}/lixeira`)    // ORDEM 060: vai para a Lixeira
      setPerguntando(false)
      ir('lista')
    } catch (e) {
      if (!ehAuth(e)) setErro(erroTxt(e))
      setOcupado(false)
    }
  }
  return (
    <section className="cartao-pad space-y-2" aria-labelledby="sec-gerir">
      <Duplicar jobId={jobId} numero={numero} livre={livre} />
      <h3 className="titulo-sec" id="sec-gerir">Trabalho</h3>
      {!livre && <p className="text-sm text-stone-500">O trabalho está em execução; aguarde terminar para editar ou excluir.</p>}
      <div className="flex flex-col gap-2 sm:flex-row">
        {podeCancelar && (
          <button type="button" className="btn-sec" onClick={() => { setErro(''); setCancelando(true) }}>Cancelar</button>
        )}
        {mostrarEditar && (
          <button type="button" className="btn-sec" disabled={!livre} onClick={aoEditarTrabalho}>Editar dados do trabalho</button>
        )}
        <button type="button" className="btn-sec !text-red-700 hover:!border-red-300 hover:!bg-red-50" disabled={!livre}
                onClick={() => { setErro(''); setPerguntando(true) }}>
          Apagar trabalho
        </button>
      </div>
      {perguntando && (
        <Confirmar titulo={`Apagar o trabalho nº ${numero}?`}
                   texto="Ele sai da lista e vai para a Lixeira (Configurações › Lixeira), de onde dá para restaurar."
                   rotuloConfirmar="Apagar" perigo ocupado={ocupado} erro={erro}
                   aoConfirmar={() => void excluir()} aoCancelar={() => setPerguntando(false)} />
      )}
      {cancelando && (
        <Confirmar titulo={`Cancelar o trabalho nº ${numero}?`}
                   texto="O trabalho para assim que terminar a etapa em andamento. O custo de IA já gasto não volta. Depois você pode reabrir (continua de onde parou) ou excluir."
                   rotuloConfirmar="Cancelar trabalho" perigo ocupado={ocupado} erro={erro}
                   aoConfirmar={() => void cancelar()} aoCancelar={() => setCancelando(false)} />
      )}
    </section>
  )
}

// ---------------------------------------------------------------- C5: editar trabalho
const CAMPOS_TRAB: ReadonlyArray<{ k: keyof FormTrabalho; rotulo: string; tipo?: string; so?: string[] }> = [
  { k: 'finalidade', rotulo: 'Finalidade' }, { k: 'cliente', rotulo: 'Solicitante' },
  { k: 'tipo', rotulo: 'Tipo do imóvel' }, { k: 'bairro', rotulo: 'Bairro ou condomínio' },
  { k: 'cidade', rotulo: 'Cidade' }, { k: 'pin_maps', rotulo: 'Pin no Google Maps' },
  { k: 'data_base', rotulo: 'Data-base', tipo: 'date' }, { k: 'data_vistoria', rotulo: 'Data da vistoria', tipo: 'date' },
  { k: 'data_emissao', rotulo: 'Data de emissão', tipo: 'date' },
  { k: 'visita_por', rotulo: 'Visita técnica feita por (nome, registro) — opcional' },
  { k: 'objeto_parte', rotulo: 'Objeto: parte do imóvel avaliada (ex.: Galpão 01) — vazio = imóvel inteiro' },
  { k: 'processo_numero', rotulo: 'Nº do processo', so: ['AM', 'AMJ'] },
  { k: 'vara_juizo', rotulo: 'Juízo / Vara', so: ['AM', 'AMJ'] }, { k: 'acao', rotulo: 'Ação', so: ['AM', 'AMJ'] },
  { k: 'autor', rotulo: 'Autor', so: ['AMJ'] }, { k: 'reu', rotulo: 'Réu', so: ['AMJ'] },
]

export function EditarTrabalho({ detalhe, foco, aoSalvar, aoCancelar }: {
  detalhe: Detalhe; foco?: string; aoSalvar: (msg: string) => void; aoCancelar: () => void
}) {
  const [form, setForm] = useState<FormTrabalho>(() => formDeDados(detalhe.job.dados))
  // O número só muda enquanto o laudo não foi gerado (entrega sem arquivos).
  const entregaArqs = (detalhe.etapas.entrega as { arquivos?: unknown[] } | undefined)?.arquivos
  const numeroEditavel = !entregaArqs || entregaArqs.length === 0
  const [numero, setNumero] = useState(String(detalhe.job.numero))
  const [erro, setErro] = useState('')
  const [salvando, setSalvando] = useState(false)
  const caixa = useRef<HTMLElement>(null)
  useEffect(() => {
    caixa.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    const alvo = document.getElementById(`et-${foco || 'finalidade'}`) as HTMLElement | null
    alvo?.focus()
  }, [foco])
  const alt = (k: keyof FormTrabalho, v: string) => setForm((f) => ({ ...f, [k]: v }))

  async function salvar() {
    for (const k of ['finalidade', 'cliente', 'tipo', 'bairro', 'cidade'] as const) {
      if (!form[k].trim()) { setErro('Preencha finalidade, solicitante, tipo, bairro e cidade.'); return }
    }
    if (!pinValido(form.pin_maps)) { setErro('Link do Google Maps inválido.'); return }
    if (!dataISOValida(form.data_base) || !dataISOValida(form.data_vistoria)
        || (form.data_emissao && !dataISOValida(form.data_emissao))) { setErro('Datas inválidas.'); return }
    const novoNumero = Number(numero.trim())
    const mudouNumero = numeroEditavel && novoNumero !== detalhe.job.numero
    if (mudouNumero && (!Number.isInteger(novoNumero) || novoNumero < 1)) { setErro('Número inválido: use um número inteiro maior que zero.'); return }
    setSalvando(true)
    setErro('')
    try {
      if (mudouNumero) {
        try {
          await put(`/jobs/${encodeURIComponent(detalhe.job.id)}/numero`, { numero: novoNumero })
        } catch (e) {
          if (!ehAuth(e)) setErro(e instanceof ApiError && e.status === 409 ? e.detail : erroTxt(e))
          return
        }
      }
      await put(`/jobs/${encodeURIComponent(detalhe.job.id)}`, payloadEdicao({ ...form, pin_maps: normalizarPin(form.pin_maps) }))
      aoSalvar(mudouNumero
        ? `Dados salvos e número alterado para ${novoNumero}.`
        : 'Dados do trabalho salvos. Toque em “Regerar documento” para refazer o laudo com eles.')
    } catch (e) {
      if (!ehAuth(e)) setErro(erroTxt(e))
    } finally {
      setSalvando(false)
    }
  }

  return (
    <section ref={caixa} className="cartao-pad space-y-3" aria-labelledby="sec-editar-trab">
      <div>
        <h3 className="titulo-sec" id="sec-editar-trab">Dados do trabalho Nº {detalhe.job.numero}</h3>
        <p className="text-sm text-stone-500">
          {numeroEditavel ? 'Salve e depois regere o documento.' : 'O número não muda depois que o laudo foi gerado. Salve e depois regere o documento.'}
        </p>
      </div>
      {numeroEditavel && (
        <div className="max-w-[12rem]">
          <label className="rotulo" htmlFor="et-numero">Número</label>
          <input id="et-numero" className="input" inputMode="numeric" value={numero}
                 onChange={(e) => setNumero(e.target.value.replace(/\D/g, ''))} />
          <p className="ajuda">Pode mudar enquanto o laudo não foi gerado.</p>
        </div>
      )}
      <div>
        <label className="rotulo" htmlFor="et-modalidade">Modalidade</label>
        <select id="et-modalidade" className="input" value={form.modalidade} onChange={(e) => alt('modalidade', e.target.value)}>
          {MODALIDADES.map((m) => <option key={m.id} value={m.id}>{m.rotulo}</option>)}
        </select>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {CAMPOS_TRAB.filter((c) => !c.so || c.so.includes(form.modalidade)).map((c) => (
          <div key={c.k}>
            <label className="rotulo" htmlFor={`et-${c.k}`}>{c.rotulo}</label>
            <input id={`et-${c.k}`} className="input" type={c.tipo ?? 'text'} value={form[c.k]}
                   onChange={(e) => alt(c.k, e.target.value)} />
          </div>
        ))}
      </div>
      {form.modalidade === 'AMJ' && (
        <div>
          <label className="rotulo" htmlFor="et-quesitos">Quesitos (um por linha)</label>
          <textarea id="et-quesitos" className="input min-h-[96px]" value={form.quesitos} onChange={(e) => alt('quesitos', e.target.value)} />
        </div>
      )}
      <div>
        <label className="rotulo" htmlFor="et-contexto">Contexto</label>
        <textarea id="et-contexto" className="input min-h-[72px]" value={form.contexto} onChange={(e) => alt('contexto', e.target.value)} />
      </div>
      <div>
        <label className="rotulo" htmlFor="et-obs_vistoria">Observações da vistoria</label>
        <textarea id="et-obs_vistoria" className="input min-h-[72px]" value={form.obs_vistoria}
                  onChange={(e) => alt('obs_vistoria', e.target.value)} />
        <p className="ajuda">{AJUDA_OBS_VISTORIA}</p>
      </div>
      <div>
        <label className="rotulo" htmlFor="et-checklist_vistoria">Checklist de vistoria (colar do celular)</label>
        <textarea id="et-checklist_vistoria" className="input min-h-[12rem] font-mono text-xs" value={form.checklist_vistoria}
                  onChange={(e) => alt('checklist_vistoria', e.target.value)} />
        <p className="ajuda">{AJUDA_CHECKLIST}</p>
      </div>
      <Erro msg={erro} />
      <div className="flex justify-end gap-2">
        <button type="button" className="btn-sec" onClick={aoCancelar} disabled={salvando}>Cancelar</button>
        <button type="button" className="btn" onClick={() => void salvar()} disabled={salvando}>{salvando ? 'Salvando…' : 'Salvar'}</button>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- envio de um tipo (ação de pendência)
export function EnviarTipo({ jobId, tipo, refazer = 'extracao', aoEnviar, aoFechar }: {
  /** Sem `tipo`: as três caixas (documentos, fotos, solicitante). */
  jobId: string; tipo?: Tipo; aoEnviar: (msg: string) => void; aoFechar: () => void
  /** De onde refazer depois do envio: triagem (trabalho bloqueado na triagem) ou extração. */
  refazer?: 'triagem' | 'extracao'
}) {
  const envio = useEnvio()
  const [ocupado, setOcupado] = useState(false)
  const [passo, setPasso] = useState('')
  const [erro, setErro] = useState('')
  const [enviado, setEnviado] = useState(false)
  const caixa = useRef<HTMLElement>(null)
  useEffect(() => { caixa.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }) }, [tipo])

  async function enviar() {
    setErro('')
    if (envio.temGrande) { setErro('Há arquivos acima de 50 MB. Remova-os.'); return }
    setOcupado(true)
    try {
      const falhou = await envio.enviarPendentes(jobId, setPasso)
      if (falhou === null) return
      if (falhou) { setErro(falhou === 1 ? '1 arquivo não foi enviado.' : `${falhou} arquivos não foram enviados.`); return }
      setEnviado(true)
    } finally {
      setOcupado(false)
      setPasso('')
    }
  }

  /** C1: os arquivos novos só entram no laudo se a extração for refeita. */
  async function reprocessar() {
    setErro('')
    setOcupado(true)
    try {
      await post(`/jobs/${encodeURIComponent(jobId)}/reabrir`, { etapa: refazer })
      aoEnviar(refazer === 'triagem' ? MSG_REABRIR.triagem
        : 'Reprocessando: os documentos serão relidos e o laudo refeito a partir da extração.')
    } catch (e) {
      if (!ehAuth(e)) setErro(erroTxt(e))
    } finally {
      setOcupado(false)
    }
  }

  if (enviado) {
    return (
      <section ref={caixa} className="cartao-pad space-y-3" aria-label="Reprocessar">
        <p className="text-sm text-stone-700" role="status">
          {refazer === 'triagem'
            ? 'Arquivos enviados. Toque em “Conferir os documentos de novo” para o JdB conferir os documentos de novo e seguir com o laudo.'
            : 'Arquivos enviados. Reprocesse para o JdB reler os documentos e refazer o laudo.'}
        </p>
        <Erro msg={erro} />
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" className="btn-sec" disabled={ocupado}
                  onClick={() => aoEnviar('Arquivos enviados. Use “Reprocessar” quando quiser que sejam lidos.')}>
            Agora não
          </button>
          <button type="button" className="btn" disabled={ocupado} onClick={() => void reprocessar()}>
            {ocupado ? 'Enviando…' : refazer === 'triagem' ? 'Conferir os documentos de novo' : 'Reprocessar'}
          </button>
        </div>
      </section>
    )
  }

  return (
    <section ref={caixa} className="cartao-pad space-y-3" aria-label="Enviar arquivos">
      <div>
        <h3 className="titulo-sec">Enviar arquivos</h3>
        <p className="text-sm text-stone-500">Arraste ou escolha os arquivos e toque em “Enviar”. Os que já estão no trabalho continuam lá.</p>
      </div>
      <ZonasArquivos envio={envio} desabilitado={ocupado} apenas={tipo} />
      <Erro msg={erro} />
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-end">
        {ocupado && <span className="text-sm text-stone-500 sm:mr-auto" role="status">{passo}</span>}
        <button type="button" className="btn-sec" onClick={aoFechar} disabled={ocupado}>Fechar</button>
        <button type="button" className="btn" onClick={() => void enviar()} disabled={ocupado || envio.pendentes === 0}>
          Enviar{envio.pendentes ? ` (${envio.pendentes})` : ''}
        </button>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- C4: pendências acionáveis
export function PendenciasAcionaveis({ pendencias, aoAgir }: {
  pendencias: Pendencia[]; aoAgir: (a: AcaoPendencia) => void
}) {
  if (!pendencias.length) return <p className="text-sm text-stone-500">Nenhuma pendência.</p>
  return (
    <ul className="space-y-2">
      {pendencias.map((p) => (
        <li key={p.texto} className="flex flex-col gap-1.5 text-sm sm:flex-row sm:items-start sm:gap-2">
          <span className="flex min-w-0 flex-1 items-start gap-2">
            {p.grave
              ? <span className="chip shrink-0 bg-red-50 text-red-800 ring-red-600/20">impeditiva</span>
              : <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-stone-400" aria-hidden="true" />}
            <span className="break-words text-stone-800">{textoPendencia(p.texto)}</span>
          </span>
          {p.acao && (
            <button type="button" className="btn-sec btn-peq shrink-0 self-start" onClick={() => aoAgir(p.acao!)}>
              {rotuloAcao(p.acao)}
            </button>
          )}
        </li>
      ))}
    </ul>
  )
}

// ---------------------------------------------------------------- C6: notificação do navegador
type NotificacaoAPI = { permission: string; requestPermission: () => Promise<string> }
type NotificacaoCtor = NotificacaoAPI & (new (titulo: string, op?: { body?: string; tag?: string }) => unknown)

/** Notification do navegador quando o trabalho termina com a aba aberta. */
export function useAvisoFim(detalhe: Detalhe | null) {
  const anterior = useRef<string | null>(null)
  const jobId = detalhe?.job.id
  const status = detalhe?.job.status
  useEffect(() => { anterior.current = null }, [jobId])
  useEffect(() => {
    const N = (globalThis as { Notification?: NotificacaoCtor }).Notification
    if (!detalhe || !status) return
    if (N && N.permission === 'default' && !anterior.current && !STATUS_FINAIS.includes(status)) {
      void N.requestPermission().catch(() => undefined)
    }
    if (deveNotificar(anterior.current, status) && N && N.permission === 'granted') {
      try {
        const n = detalhe.pendencias.length
        new N(`Laudo nº ${detalhe.job.numero}: ${status}`, {
          body: `${nomeSolicitante(detalhe.job.dados.cliente)} · ${plural(n, 'pendência', 'pendências')}`, tag: `jdb-${detalhe.job.id}` })
      } catch { /* navegador sem suporte (ex.: Android exige service worker) */ }
    }
    anterior.current = status
  }, [detalhe, status])
}

/** Navega para a configuração (seção do Coletor). */
export function irParaColetor() {
  useStore.getState().ir('sistema')
}
