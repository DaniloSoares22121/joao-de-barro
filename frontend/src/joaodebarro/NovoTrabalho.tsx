import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { ApiError, get, post } from './api'
import { ZonasArquivos, ehAuth, mensagemErro, useEnvio } from './Envio'
import { MODALIDADES } from './rotulos'
import { useStore } from './store'
import {
  formVazio, paraPayload, validar,
  type CampoForm, type Erros, type FormTrabalho,
} from './validacao'

const FINALIDADES = ['Venda', 'Locação', 'Venda e locação', 'Garantia', 'Judicial', 'Outra']

const ROTULOS: Record<CampoForm, string> = {
  numero: 'Nº do trabalho', modalidade: 'Modalidade', finalidade: 'Finalidade', cliente: 'Solicitante',
  tipo: 'Tipo do imóvel', bairro: 'Bairro ou condomínio', cidade: 'Cidade', pin_maps: 'Pin no Google Maps',
  data_base: 'Data-base', data_vistoria: 'Data da vistoria', contexto: 'Contexto',
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
    const ev = jobId.current ? {} : validar(form)
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
        setErroGeral(`${falhou} arquivo(s) não foram enviados. Remova-os ou tente novamente — o trabalho já foi criado e não será duplicado.`)
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
        <h1 className="mt-1 text-xl font-semibold text-stone-900">Novo trabalho</h1>
        <p className="text-sm text-stone-500">Dados de entrada do imóvel (checklist P5). O laudo é montado depois do envio.</p>
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
        </div>
        <Campo id="f-contexto" rotulo="Contexto (opcional)"
               ajuda="Informação verbal — não entra no laudo (D-013). Serve só para orientar a análise.">
          <textarea {...propsInput('contexto')} rows={3}
                    placeholder="Ex.: proprietário informou reforma recente; priorizar o bairro vizinho na pesquisa." />
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
          <p className="font-medium">Corrija {qtErros} campo(s) para continuar:</p>
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
          {enviando ? 'Enviando…' : jobId.current ? 'Tentar novamente' : total ? `Criar e enviar ${total} arquivo(s)` : 'Criar e iniciar'}
        </button>
      </div>
    </form>
  )
}
