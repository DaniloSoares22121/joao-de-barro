/** ORDEM 060: Lixeira (Configurações). O trabalho apagado fica aqui com [Restaurar]; só
 * [Esvaziar lixeira], depois de nova confirmação, apaga de vez (banco e arquivos). */
import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, RotateCcw, Trash2 } from 'lucide-react'
import { get, post } from './api'
import Confirmar from './Confirmar'
import { dataBR, nomeSolicitante, plural } from './rotulos'
import { useStore } from './store'

interface ItemLixeira { id: string; numero: number; titulo: string; cliente: string; quando: string; entregue: boolean; tipo?: 'trabalho' | 'cliente' }

export default function Lixeira() {
  const ir = useStore((s) => s.ir)
  const [itens, setItens] = useState<ItemLixeira[] | null>(null)
  const [msg, setMsg] = useState('')
  const [erro, setErro] = useState('')
  const [esvaziando, setEsvaziando] = useState(false)
  const [ocupado, setOcupado] = useState(false)

  const carregar = useCallback(async () => {
    try { setItens(await get<ItemLixeira[]>('/lixeira')) } catch { setErro('Não deu para abrir a Lixeira.') }
  }, [])
  useEffect(() => { void carregar() }, [carregar])

  async function restaurar(i: ItemLixeira) {
    setErro('')
    try {
      if (i.tipo === 'cliente') await post(`/clientes/${encodeURIComponent(i.id)}/restaurar`)   // 183
      else await post(`/jobs/${encodeURIComponent(i.id)}/restaurar`)
      setMsg(`“${i.titulo}” voltou para a lista de ${i.tipo === 'cliente' ? 'clientes' : 'trabalhos'}.`)
      void carregar()
    } catch { setErro('Não deu para restaurar. Tente de novo.') }
  }

  async function esvaziar() {
    setOcupado(true)
    setErro('')
    try {
      const r = await post<{ apagados: number[]; ficaram: number[] }>('/lixeira/esvaziar')
      setEsvaziando(false)
      setMsg(r.ficaram.length
        ? `${plural(r.apagados.length, 'trabalho apagado', 'trabalhos apagados')} de vez. ${plural(r.ficaram.length, 'ficou', 'ficaram')} porque o JdB ainda está trabalhando ${r.ficaram.length === 1 ? 'nele' : 'neles'}.`
        : `Lixeira esvaziada: ${plural(r.apagados.length, 'trabalho apagado', 'trabalhos apagados')} de vez.`)
      void carregar()
    } catch {
      setErro('Não deu para esvaziar a Lixeira. Tente de novo.')
    } finally {
      setOcupado(false)
    }
  }

  return (
    <section className="tela-simples">
      <button type="button" className="voltar-jdb" onClick={() => ir('config')}><ArrowLeft size={18} aria-hidden="true" /> Configurações</button>
      <div>
        <h1 className="titulo-jdb">Lixeira</h1>
        <p className="sub-jdb">Trabalhos e clientes apagados. Daqui dá para restaurar; nada sai de vez sem você esvaziar a Lixeira.</p>
      </div>
      {msg && <p className="aviso-simples" role="status">{msg}</p>}
      {erro && <p className="aviso-impede" role="alert">{erro}</p>}
      {itens === null && !erro && <p className="small-jdb">Carregando…</p>}
      {itens !== null && itens.length === 0 && <p className="texto">A Lixeira está vazia.</p>}
      {itens !== null && itens.length > 0 && (
        <>
          <ul className="lista-cartoes">
            {itens.map((i) => (
              <li key={i.id} className="cartao-pad item-lixeira">
                <div className="grid gap-1">
                  <span className="cartao-titulo">{i.titulo}</span>
                  <span className="cartao-sub">
                    {[i.tipo === 'cliente' ? '' : `nº ${i.numero}`, i.tipo === 'cliente' ? '' : nomeSolicitante(i.cliente),
                      `apagado em ${dataBR(i.quando)}`].filter(Boolean).join(' · ')}
                  </span>
                  {i.entregue && <span className="small-jdb">Este laudo já tinha sido entregue.</span>}
                </div>
                <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} onClick={() => void restaurar(i)}>
                  <RotateCcw size={20} aria-hidden="true" /> Restaurar
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className="btn-perigo" style={{ width: 'auto', justifySelf: 'start' }} onClick={() => setEsvaziando(true)}>
            <Trash2 size={20} aria-hidden="true" /> Esvaziar lixeira
          </button>
        </>
      )}
      {esvaziando && itens && (
        <Confirmar titulo="Esvaziar a Lixeira?"
                   texto={`${plural(itens.length, 'item será apagado', 'itens serão apagados')} de vez, com todos os arquivos. Isso não pode ser desfeito.`}
                   rotuloConfirmar="Esvaziar lixeira" perigo ocupado={ocupado} erro={erro}
                   aoConfirmar={() => void esvaziar()} aoCancelar={() => setEsvaziando(false)} />
      )}
    </section>
  )
}
