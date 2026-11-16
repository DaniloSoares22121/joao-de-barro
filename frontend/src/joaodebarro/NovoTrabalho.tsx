import { FalarAqui } from './Falar'
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { ApiError, get, post } from './api'
import { ZonasArquivos, ehAuth, mensagemErro, useEnvio } from './Envio'
import { plural, MODALIDADES } from './rotulos'
import { useStore } from './store'
import {
  AJUDA_CHECKLIST, AJUDA_OBS_VISTORIA, AJUDA_VISITA_POR, formVazio, paraPayload, validar,
  type CampoForm, type Erros, type FormTrabalho,
} from './validacao'

const FINALIDADES =['Venda', 'Locação', 'Venda e locação', 'Garantia', 'Judicial', 'Outra']

const ROTULOS: Record<CampoForm, string> = {
  numero: 'Nº do trabalho', modalidade: 'Modalidade', finalidade: 'Finalidade', cliente: 'Solicitante',
  tipo: 'Tipo do imóvel', bairro: 'Bairro ou condomínio', cidade: 'Cidade', pin_maps: 'Pin no Google Maps',
  data_base: 'Data-base', data_vistoria: 'Data da vistoria', contexto: 'Contexto',
  obs_vistoria: 'Observações da vistoria', checklist_vistoria: 'Checklist de vistoria', data_emissao: 'Data de emissão', visita_por: 'Visita técnica feita por', objeto_parte: 'Parte avaliada',
  processo_numero: 'Nº do processo', vara_juizo: 'Juízo / Vara', acao: 'Ação', autor: 'Autor',
  reu: 'Réu', quesitos: 'Quesitos',
}

/** Erro do campo fica ao lado dele (sem role=alert); o anúncio é feito uma vez pelo resumo. */
function Campo({ id, rotulo, erro, ajuda, children }: {
  id: string; rotulo: string; erro?: string; ajuda?: string; children: ReactNode
}) {
  return (
    <div>
      <label htmlFor={id} className="rotulo">{rotulo}</label>
      {children}
      {erro ? <p className="erro-txt" id={`${id}-erro`}>{erro}</p>
            : ajuda ? <p className="ajuda">{ajuda}</p> : null}
    </div>
  )
}

export default function NovoTrabalho() {
  const ir = useStore((s) => s.ir)
  const prefill = useStore((s) => s.prefill)
  const [form, setForm] = useState<FormTrabalho>(() => ({ ...formVazio(), ...(prefill ?? {}) }))
  const [erros, setErros] = useState<Erros>({})
  // ORDEM 032-2: objeto da avaliação — imóvel inteiro ou parte (qual)
  const [parte, setParte] = useState(false)
  const [tentou, setTentou] = useState(false)
  const envio = useEnvio()
  const [enviando, setEnviando] = useState(false)
  const [passo, setPasso] = useState('')
  const [erroGeral, setErroGeral] = useState('')
  const [sugerido, setSugerido] = useState<number | null>(null)
  const jobId = useRef<string | null>(null)
  const montado = useRef(true)
  const resumo = useRef<HTMLDivElement>(null)

  useEffect(() => {
    montado.current = true
    return () => { montado.current = false }
  }, [])

  // Número sugerido pelo servidor (max + 1).
  const sugerir = (forcar = false) =>
    get<{ numero: number }>('/proximo-numero').then(({ numero }) => {
      if (!montado.current) return
      setSugerido(numero)
      setForm((f) => (f.numero && !forcar ? f : { ...f, numero: String(numero) }))
    }).catch(() => undefined)
  useEffect(() => { void sugerir() }, [])

  function alterar(campo: CampoForm, valor: string) {
    setForm((f) => {
      const novo = { ...f, [campo]: valor }
      if (tentou) setErros(validar(novo))
      return novo
    })
  }

  const propsInput = (campo: CampoForm) => ({
    id: `f-${campo}`,
    value: form[campo],
    disabled: enviando || (campo !== 'contexto' && !!jobId.current),
    'aria-invalid': erros[campo] ? true : undefined,
    'aria-describedby': erros[campo] ? `f-${campo}-erro` : undefined,
    className: `input ${erros[campo] ? 'input-erro' : ''}`,
    onChange: (e: { target: { value: string } }) => alterar(campo, e.target.value),
  })

  async function enviar(e: FormEvent) {
    e.preventDefault()
    setErroGeral('')
    setTentou(true)
    const ev: Erros = jobId.current ? {} : validar(form)
    if (!jobId.current && parte && !form.objeto_parte.trim()) ev.objeto_parte = 'Diga qual parte do imóvel é avaliada (ex.: Galpão 01) ou marque “Imóvel inteiro”.'
    setErros(ev)
    if (Object.keys(ev).length) {
      requestAnimationFrame(() => resumo.current?.focus())
      return
    }
    if (envio.temGrande) {
      setErroGeral('Há arquivos acima de 50 MB. Remova-os para continuar.')
      return
    }

    setEnviando(true)
    try {
      if (!jobId.current) {
        setPasso('Criando o trabalho…')
        try {
          jobId.current = (await post<{ id: string }>('/jobs', paraPayload(form))).id
        } catch (err) {
          if (err instanceof ApiError && err.status === 409) {
            setErros({ numero: `O nº ${form.numero} já foi usado. Sugestão: o próximo livre.` })
            void sugerir(true)
            requestAnimationFrame(() => document.getElementById('f-numero')?.focus())
            return
          }
          throw err
        }
      }
      const id = jobId.current
      const falhou = await envio.enviarPendentes(id, setPasso)
      if (falhou === null) return
      if (falhou) {
        setErroGeral(`${falhou === 1 ? '1 arquivo não foi enviado' : `${falhou} arquivos não foram enviados`}. Remova-os ou tente novamente — o trabalho já foi criado e não será duplicado.`)
        return
      }
      setPasso('Iniciando a avaliação…')
      await post(`/jobs/${encodeURIComponent(id)}/iniciar`)
      useStore.getState().ir('job', id)
    } catch (err) {
      if (ehAuth(err)) return
      setErroGeral(mensagemErro(err))
    } finally {
      if (montado.current) { setEnviando(false); setPasso('') }
    }
  }

  const total = envio.total
  const qtErros = Object.keys(erros).length

  return (
    <form onSubmit={enviar} noValidate className="mx-auto max-w-3xl space-y-5">
      <div>
        <button type="button" className="btn-link -ml-2" onClick={() => ir('lista')} disabled={enviando}>← Trabalhos</button>
        <h1 className="titulo-pag mt-1">Novo trabalho</h1>
        <p className="text-sm text-stone-500">Dados de entrada do imóvel. O laudo é montado depois do envio.</p>
        {/* 155-2: a contagem do plano, antes de começar */}
        <p className="texto mt-1">Este trabalho conta 1 laudo do seu plano quando o primeiro rascunho ficar pronto.</p>
      </div>

      <section className="cartao-pad space-y-4" aria-labelledby="sec-dados">
        <h2 className="titulo-sec" id="sec-dados">Dados do trabalho</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Campo id="f-numero" rotulo="Nº do trabalho" erro={erros.numero}>
            <input {...propsInput('numero')} inputMode="numeric" autoComplete="off" />
            {sugerido !== null && !erros.numero && String(sugerido) !== form.numero.trim() && (
              <p className="ajuda">Próximo livre: {sugerido}{' '}
                <button type="button" className="btn-link !p-0" onClick={() => alterar('numero', String(sugerido))}
                        disabled={enviando || !!jobId.current}>usar</button>
              </p>
            )}
          </Campo>
          <Campo id="f-modalidade" rotulo="Modalidade" erro={erros.modalidade}>
            <select {...propsInput('modalidade')}>
              <option value="">Selecione…</option>
              {MODALIDADES.map((m) => <option key={m.id} value={m.id}>{m.rotulo}</option>)}
            </select>
          </Campo>
          <Campo id="f-finalidade" rotulo="Finalidade" erro={erros.finalidade}
                 ajuda="Venda, locação, ambos ou outra. Destinatário com exigência específica, se houver.">
            <input {...propsInput('finalidade')} list="finalidades" autoComplete="off" />
            <datalist id="finalidades">{FINALIDADES.map((x) => <option key={x} value={x} />)}</datalist>
          </Campo>
          <Campo id="f-cliente" rotulo="Solicitante" erro={erros.cliente}
                 ajuda="Nome (PF) ou razão social (PJ).">
            <input {...propsInput('cliente')} autoComplete="off" />
          </Campo>
          <Campo id="f-tipo" rotulo="Tipo do imóvel" erro={erros.tipo}>
            <input {...propsInput('tipo')} placeholder="Casa, apartamento, lote…" autoComplete="off" />
          </Campo>
          <Campo id="f-bairro" rotulo="Bairro ou condomínio" erro={erros.bairro}>
            <input {...propsInput('bairro')} autoComplete="off" />
          </Campo>
          <Campo id="f-cidade" rotulo="Cidade" erro={erros.cidade}>
            <input {...propsInput('cidade')} autoComplete="off" />
          </Campo>
          <Campo id="f-pin_maps" rotulo="Pin no Google Maps" erro={erros.pin_maps}
                 ajuda="Link de maps.app.goo.gl ou google.com/maps.">
            <input {...propsInput('pin_maps')} type="url" inputMode="url" placeholder="https://maps.app.goo.gl/…" autoComplete="off" />
          </Campo>
          <Campo id="f-data_base" rotulo="Data-base" erro={erros.data_base}>
            <input {...propsInput('data_base')} type="date" />
          </Campo>
          <Campo id="f-data_vistoria" rotulo="Data da vistoria" erro={erros.data_vistoria}>
            <input {...propsInput('data_vistoria')} type="date" />
          </Campo>
          <Campo id="f-data_emissao" rotulo="Data de emissão" erro={erros.data_emissao}
                 ajuda="Data que sai no laudo. Padrão: hoje.">
            <input {...propsInput('data_emissao')} type="date" />
          </Campo>
        </div>
        <fieldset className="space-y-2" aria-describedby="objeto-ajuda">
          <legend className="rotulo">Objeto da avaliação</legend>
          <p id="objeto-ajuda" className="text-xs text-[var(--cinza)]">
            Parte do imóvel (ex.: um galpão dentro de um lote maior): o valor é só dessa parte e o lote entra como contexto.
          </p>
          <div className="flex flex-wrap gap-4">
            <label className="flex items-center gap-2 text-sm">
              <input type="radio" name="objeto" checked={!parte} disabled={enviando}
                     onChange={() => { setParte(false); setForm((f) => ({ ...f, objeto_parte: '' })) }} />
              Imóvel inteiro
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="radio" name="objeto" checked={parte} disabled={enviando}
                     onChange={() => setParte(true)} />
              Parte do imóvel
            </label>
          </div>
          {parte && (
            <Campo id="f-objeto_parte" rotulo="Qual parte?" erro={erros.objeto_parte}>
              <input {...propsInput('objeto_parte')} placeholder="Ex.: Galpão 01" autoComplete="off" />
            </Campo>
          )}
        </fieldset>
        <Campo id="f-visita_por" rotulo="Visita técnica feita por (nome, registro)" erro={erros.visita_por}
               ajuda={AJUDA_VISITA_POR}>
          <input {...propsInput('visita_por')} placeholder="Opcional — ex.: João da Silva, CRECI 12345/GO" autoComplete="off" />
        </Campo>
        <Campo id="f-obs_vistoria" rotulo="Observações da vistoria"
               ajuda={AJUDA_OBS_VISTORIA}>
          <textarea {...propsInput('obs_vistoria')} rows={3} />
          <FalarAqui alvo="f-obs_vistoria" valor={form.obs_vistoria} aoMudar={(v) => alterar('obs_vistoria', v)} />
        </Campo>
        <Campo id="f-checklist_vistoria" rotulo="Checklist de vistoria (colar do celular)"
               ajuda={AJUDA_CHECKLIST}>
          <textarea {...propsInput('checklist_vistoria')} rows={10} className={`input min-h-[12rem] font-mono text-xs ${erros.checklist_vistoria ? 'input-erro' : ''}`} />
        </Campo>
        <Campo id="f-contexto" rotulo="Contexto (opcional)"
               ajuda="Informação verbal — não entra no laudo. Serve só para orientar a análise.">
          <textarea {...propsInput('contexto')} rows={3}
                    placeholder="Ex.: proprietário informou reforma recente; priorizar o bairro vizinho na pesquisa." />
          <FalarAqui alvo="f-contexto" valor={form.contexto} aoMudar={(v) => alterar('contexto', v)} />
        </Campo>
      </section>

      {(form.modalidade === 'AMJ' || form.modalidade === 'AM') && (
        <section className="cartao-pad space-y-4" aria-labelledby="sec-processo">
          <div>
            <h2 className="titulo-sec" id="sec-processo">Processo judicial</h2>
            <p className="text-sm text-stone-500">
              {form.modalidade === 'AMJ'
                ? 'Sem nº do processo, vara e partes o laudo judicial sai com pendências.'
                : 'Opcional em AM: preencha se o parecer se refere a um processo.'}
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Campo id="f-processo_numero" rotulo="Nº do processo">
              <input {...propsInput('processo_numero')} placeholder="0000000-00.0000.0.00.0000" autoComplete="off" />
            </Campo>
            <Campo id="f-vara_juizo" rotulo="Juízo / Vara">
              <input {...propsInput('vara_juizo')} placeholder="Ex.: 2ª Vara de Família de Goiânia" autoComplete="off" />
            </Campo>
            <Campo id="f-acao" rotulo="Ação (opcional)">
              <input {...propsInput('acao')} placeholder="Ex.: Partilha de bens" autoComplete="off" />
            </Campo>
          </div>
          {form.modalidade === 'AMJ' && (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <Campo id="f-autor" rotulo="Autor">
                  <input {...propsInput('autor')} autoComplete="off" />
                </Campo>
                <Campo id="f-reu" rotulo="Réu">
                  <input {...propsInput('reu')} autoComplete="off" />
                </Campo>
              </div>
              <Campo id="f-quesitos" rotulo="Quesitos" ajuda="Um quesito por linha; cada um é respondido no laudo.">
                <textarea {...propsInput('quesitos')} rows={4} placeholder={'Qual o valor de mercado do imóvel?\nO imóvel possui benfeitorias?'} />
              </Campo>
            </>
          )}
        </section>
      )}

      <section className="cartao-pad space-y-5" aria-labelledby="sec-arquivos">
        <div>
          <h2 className="titulo-sec" id="sec-arquivos">Arquivos</h2>
          <p className="text-sm text-stone-500">
            Cada arquivo pode ter até 50 MB. Sem fotos ou sem matrícula/IPTU o laudo sai com pendências.
          </p>
        </div>
        <ZonasArquivos envio={envio} desabilitado={enviando} />
      </section>

      {tentou && qtErros > 0 && (
        <div ref={resumo} tabIndex={-1} role="alert"
             className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <p className="font-medium">Corrija {plural(qtErros, 'campo', 'campos')} para continuar:</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {(Object.keys(erros) as CampoForm[]).map((c) => (
              <li key={c}>
                <button type="button" className="toque text-left font-medium underline sm:min-h-0"
                        onClick={() => document.getElementById(`f-${c}`)?.focus()}>
                  {ROTULOS[c]}
                </button>: {erros[c]}
              </li>
            ))}
          </ul>
        </div>
      )}
      {erroGeral && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">{erroGeral}</div>
      )}

      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-end">
        {enviando && <span className="text-sm text-stone-500 sm:mr-auto" role="status">{passo}</span>}
        <button type="button" className="btn-sec" onClick={() => ir('lista')} disabled={enviando}>Cancelar</button>
        <button type="submit" className="btn" disabled={enviando}>
          {enviando ? 'Enviando…' : jobId.current ? 'Tentar novamente' : total ? `Criar e enviar ${plural(total, 'arquivo', 'arquivos')}` : 'Criar e iniciar'}
        </button>
      </div>
    </form>
  )
}
