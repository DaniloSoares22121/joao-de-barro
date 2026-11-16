/* ORDEM 049 / D-102 (L15): "Para qual trabalho?" — chega aqui pelo menu Compartilhar do celular
 * (Web Share Target). Os arquivos ficam neste aparelho até o avaliador escolher o trabalho; só então
 * são enviados, com o login dele, pelos mesmos caminhos do envio pela tela (tipos e limite de tamanho
 * conferidos aqui e no servidor). Texto compartilhado (mensagem do WhatsApp) entra na conversa do
 * cliente (D-089). */
import { useEffect, useState } from 'react'
import { ChevronRight, FileText, Plus } from 'lucide-react'
import { ApiError, get, post, postForm } from './api'
import { comecarCom, comecarComArquivos } from './NovoSimples'
import { modalidade, nomeSolicitante } from './rotulos'
import { useStore } from './store'
import type { Detalhe, JobResumo } from './tipos'
import { ehImportacao, importar, tipoArquivo } from './Importar'

const CACHE = 'jdb-compartilhar'
// ORDEM 061: os mesmos formatos da caixa da L2 e da conversa (zip do WhatsApp, texto, áudio, foto,
// documento, vídeo e contato); executáveis ficam de fora. Documento ou foto solto: até 50 MB cada.
const MAX_SOLTO = 50 * 1024 * 1024

interface Item { chave: string; nome: string; tipo: string; tamanho: number }
interface Indice { arquivos: Item[]; texto: string; quando: number }
interface Cli { id: string; nome: string; imovel: string; job_id: string; atualizado: string; modalidade: string }
type Destino = { tipo: 'job'; id: string; numero: number; titulo: string; sub: string; quando: string }
  | { tipo: 'cliente'; id: string; titulo: string; sub: string; quando: string }

const base = () => window.location.href.split('#')[0].replace(/[^/]*$/, '')
const erroDe = (e: unknown) => (e instanceof ApiError ? e.message : 'Não deu certo. Tente de novo.')

/** O que é cada arquivo, pelo nome (a triagem do JdB confere depois, como no envio pela tela). */
export function rotuloArquivo(nome: string, tipo: string): string {
  const n = nome.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
  if (tipo.startsWith('image/') && !/matricula|iptu|escritura|rg|cnh|cpf|documento/.test(n)) return 'foto'
  if (/matricula/.test(n)) return 'matrícula'
  if (/iptu/.test(n)) return 'IPTU'
  if (/escritura/.test(n)) return 'escritura'
  if (/\b(rg|cnh|cpf|identidade)\b/.test(n)) return 'documento do solicitante'
  return 'documento'
}
const tipoEnvio = (r: string) => (r === 'foto' ? 'foto' : r === 'documento do solicitante' ? 'solicitante' : 'documento')

export function resumoRecebidos(rotulos: string[]): string {
  const cont = new Map<string, number>()
  for (const r of rotulos) cont.set(r, (cont.get(r) ?? 0) + 1)
  const partes = [...cont].map(([r, n]) => (n === 1 ? r : `${n} ${r === 'foto' ? 'fotos' : r === 'documento' ? 'documentos' : r}`))
  return partes.length > 1 ? `${partes.slice(0, -1).join(', ')} e ${partes[partes.length - 1]}` : partes[0] ?? ''
}

async function lerCompartilhado(): Promise<{ indice: Indice | null; arquivos: File[] }> {
  try {
    const cache = await caches.open(CACHE)
    const r = await cache.match(base() + 'compartilhado/indice.json')
    if (!r) return { indice: null, arquivos: [] }
    const indice: Indice = await r.json()
    const arquivos: File[] = []
    for (const a of indice.arquivos) {
      const x = await cache.match(a.chave)
      if (x) arquivos.push(new File([await x.blob()], a.nome, { type: a.tipo }))
    }
    return { indice, arquivos }
  } catch { return { indice: null, arquivos: [] } }
}
async function limpar() { try { await caches.delete(CACHE) } catch { /* sem cache */ } }

export default function Compartilhar() {
  const ir = useStore((s) => s.ir)
  const [indice, setIndice] = useState<Indice | null | undefined>(undefined)
  const [arquivos, setArquivos] = useState<File[]>([])
  const [destinos, setDestinos] = useState<Destino[] | null>(null)
  const [miniaturas, setMiniaturas] = useState<string[]>([])
  const [passo, setPasso] = useState('')
  const [feito, setFeito] = useState<{ texto: string; abrir: () => void } | null>(null)
  const [erro, setErro] = useState('')

  useEffect(() => {
    let urls: string[] = []
    void lerCompartilhado().then(({ indice: i, arquivos: a }) => {
      setIndice(i); setArquivos(a)
      urls = a.filter((f) => f.type.startsWith('image/')).slice(0, 4).map((f) => URL.createObjectURL(f))
      setMiniaturas(urls)
    })
    Promise.all([get<JobResumo[]>('/jobs'), get<{ clientes: Cli[] }>('/clientes').catch(() => ({ clientes: [] as Cli[] }))]).then(([jobs, cl]) => {
      const abertos: Destino[] = jobs.filter((j) => j.proximo !== 'Concluído' && j.proximo !== 'Cancelado').map((j) => ({
        tipo: 'job' as const, id: j.id, numero: j.numero, quando: j.atualizado,
        titulo: [j.objeto_parte || j.tipo, j.bairro].filter(Boolean).join(' – ') || `Trabalho nº ${j.numero}`,
        sub: [nomeSolicitante(j.cliente), modalidade(j.modalidade)].filter(Boolean).join(' · '),
      }))
      const clientes: Destino[] = cl.clientes.filter((c) => !c.job_id).map((c) => ({
        tipo: 'cliente' as const, id: c.id, quando: c.atualizado, titulo: c.imovel || c.nome, sub: c.nome,
      }))
      setDestinos([...abertos, ...clientes].sort((a, b) => (b.quando || '').localeCompare(a.quando || '')))
    }).catch((e) => setErro(erroDe(e)))
    return () => { urls.forEach((u) => URL.revokeObjectURL(u)) }
  }, [])

  const importa = ehImportacao(arquivos.filter((f) => tipoArquivo(f.name) !== 'recusado'))
  const validos = arquivos.filter((f) => tipoArquivo(f.name) !== 'recusado' && (importa || f.size <= MAX_SOLTO))
  const recusados = arquivos.length - validos.length
  const texto = indice?.texto?.trim() ?? ''

  async function enviarPara(d: Destino) {
    setErro('')
    const rotulos = validos.map((f) => rotuloArquivo(f.name, f.type))
    let textoFoi = false
    try {
      const conversa = d.tipo === 'cliente' ? d.id
        : importa ? (await get<Detalhe>(`/jobs/${encodeURIComponent(d.id)}`)).tela?.cliente_id || '' : ''
      if (importa && conversa) {
        setPasso('Enviando os arquivos…')                   // o JdB lê tudo em segundo plano
        await importar(conversa, validos)
        if (texto) { await post(`/clientes/${conversa}/mensagem`, { texto, tipo: 'whatsapp' }); textoFoi = true }
      } else if (importa) {
        setErro('Este trabalho não tem conversa de cliente para receber a conversa do WhatsApp. Toque em “Começar um trabalho novo”.')
        return
      } else if (d.tipo === 'job') {
        for (const [i, f] of validos.entries()) {
          setPasso(`Enviando ${i + 1} de ${validos.length}…`)
          const fd = new FormData(); fd.append('tipo', tipoEnvio(rotulos[i])); fd.append('arquivos', f)
          await postForm(`/jobs/${encodeURIComponent(d.id)}/arquivos`, fd)
        }
        if (texto) {
          const det = await get<Detalhe>(`/jobs/${encodeURIComponent(d.id)}`)
          if (det.tela?.cliente_id) { await post(`/clientes/${det.tela.cliente_id}/mensagem`, { texto, tipo: 'whatsapp' }); textoFoi = true }
        }
      } else {
        for (const [i, f] of validos.entries()) {
          setPasso(`Enviando ${i + 1} de ${validos.length}…`)
          const fd = new FormData(); fd.append('arquivo', f); fd.append('tipo', rotulos[i] === 'foto' ? 'foto' : 'documento')
          await postForm(`/clientes/${d.id}/arquivo`, fd)
        }
        if (texto) { await post(`/clientes/${d.id}/mensagem`, { texto, tipo: 'whatsapp' }); textoFoi = true }
      }
      await limpar()
      const onde = d.tipo === 'job' ? `no trabalho ${d.numero}` : `na conversa de ${d.sub}`
      const partes = [validos.length ? `${validos.length} ${validos.length === 1 ? 'arquivo recebido' : 'arquivos recebidos'} ${onde}: ${resumoRecebidos(rotulos)}` : '',
        textoFoi ? 'mensagem anotada na conversa' : texto ? 'a mensagem não foi: este trabalho não tem conversa de cliente' : ''].filter(Boolean)
      setFeito({ texto: partes.join('; ') + '.', abrir: () => (d.tipo === 'job' ? ir('job', d.id) : ir('cliente', d.id)) })
    } catch (e) { setErro(erroDe(e)) } finally { setPasso('') }
  }
  function criarNovo() {
    if (texto) comecarCom(texto)
    comecarComArquivos(validos)
    void limpar(); ir('novo')
  }

  if (indice === undefined) return <p className="texto" role="status">Abrindo…</p>
  if (feito) {
    return (
      <section className="tela-simples">
        <div className="proximo-passo">
          <span className="tag-jdb">Pronto</span>
          <h1 className="titulo-cartao">{feito.texto}</h1>
          <div className="botoes"><button type="button" className="btn-verde" onClick={feito.abrir}>Abrir</button></div>
        </div>
      </section>
    )
  }
  if (!indice || (!arquivos.length && !texto)) {
    return (
      <section className="tela-simples">
        <h1 className="titulo-jdb">Nada para enviar</h1>
        <p className="sub-jdb">Use o Compartilhar do celular e escolha o JdB Laudo.</p>
        <button type="button" className="btn-sec-grande" onClick={() => ir('lista')}>Ver os trabalhos</button>
      </section>
    )
  }
  return (
    <section className="tela-simples">
      <div className="miniaturas-l15" aria-hidden="true">
        {miniaturas.map((u) => <img key={u} src={u} alt="" />)}
        {validos.filter((f) => !f.type.startsWith('image/')).slice(0, 4 - miniaturas.length).map((f) => <span key={f.name} className="mini-doc"><FileText size={22} /></span>)}
      </div>
      <p className="small-jdb">
        {validos.length ? `${validos.length} ${validos.length === 1 ? 'arquivo para enviar' : 'arquivos para enviar'}` : ''}
        {validos.length && texto ? ' e ' : ''}{texto ? 'uma mensagem' : ''}
      </p>
      <h1 className="titulo-jdb">Para qual trabalho?</h1>
      {recusados > 0 && <p className="aviso-simples">{recusados === 1 ? '1 arquivo não pode ir' : `${recusados} arquivos não podem ir`}: programa, formato que eu não abro ou arquivo solto acima de 50 MB.</p>}
      {erro && <p className="aviso-impede" role="alert">{erro}</p>}
      {passo && <p className="texto" role="status">{passo}</p>}
      {destinos === null ? <p className="texto" role="status">Carregando os trabalhos…</p> : (
        <ul className="lista-l20">
          {destinos.map((d) => (
            <li key={`${d.tipo}-${d.id}`}>
              <button type="button" className="linha-l20" disabled={!!passo} onClick={() => void enviarPara(d)}>
                <span className="grid flex-1 text-left"><span>{d.titulo}</span><span className="small-jdb" style={{ fontWeight: 400 }}>{d.sub}</span></span>
                <ChevronRight size={22} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" className="btn-sec-grande w-full" disabled={!!passo} onClick={criarNovo}><Plus size={20} aria-hidden="true" /> Criar trabalho novo</button>
    </section>
  )
}
