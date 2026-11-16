/* ORDEM 053 (L2): "Novo trabalho — Cole o que você já tem. Eu organizo." Uma caixa só: cola a
 * conversa do WhatsApp ou escreve o que já sabe, anexa arquivos e "Começar". Usa a conversa do
 * cliente da ORDEM 041 (o JdB lê a mensagem e os documentos e separa o que é de cada etapa). A ficha
 * completa continua a um toque, e abre direto no "Novo a partir deste". */
import { FalarAqui } from './Falar'
import { useState } from 'react'
import { ArrowLeft, Paperclip } from 'lucide-react'
import { ApiError, post, postForm } from './api'
import NovoTrabalho from './NovoTrabalho'
import { useStore } from './store'
import { ACEITOS, SolteAqui, ehImportacao, importar, separar, useSoltar } from './Importar'

/** L16 → L2: o guia deixa a modalidade escrita na caixa. */
let textoInicial = ''
export function comecarCom(t: string) { textoInicial = t }
/** ORDEM 049: arquivos que vieram pelo Compartilhar do celular. */
let arquivosIniciais: File[] = []
export function comecarComArquivos(a: File[]) { arquivosIniciais = a }

const erroDe = (e: unknown) => (e instanceof ApiError ? e.message : 'Não deu certo. Tente de novo.')

export default function NovoSimples() {
  const ir = useStore((s) => s.ir)
  const prefill = useStore((s) => s.prefill)
  const [ficha, setFicha] = useState(!!prefill)
  const [texto, setTexto] = useState(() => { const t = textoInicial; textoInicial = ''; return t })
  const [arquivos, setArquivos] = useState<File[]>(() => { const a = arquivosIniciais; arquivosIniciais = []; return a })
  const [passo, setPasso] = useState('')
  const [erro, setErro] = useState('')
  const [aviso, setAviso] = useState('')
  // ORDEM 061: arrastar e soltar (vários arquivos ou o .zip do WhatsApp); executável fica de fora com aviso
  const juntar = (fs: File[]) => {
    const { aceitos, aviso: recusa } = separar(fs)
    setAviso(recusa)
    if (aceitos.length) setArquivos((a) => [...a, ...aceitos])
  }
  const soltar = useSoltar(juntar)
  if (ficha) {
    return (
      <div className="grid gap-4">
        <button type="button" className="voltar-jdb" onClick={() => setFicha(false)}><ArrowLeft size={18} aria-hidden="true" /> Voltar à caixa simples</button>
        <NovoTrabalho />
      </div>
    )
  }
  async function comecar() {
    setErro('')
    if (!texto.trim() && !arquivos.length) { setErro('Cole a conversa, escreva o que já sabe ou anexe um arquivo.'); return }
    try {
      setPasso('Abrindo…')
      const c = await post<{ id: string }>('/clientes', { nome: '' })
      if (texto.trim()) {
        setPasso('Estou lendo…')
        await post(`/clientes/${c.id}/mensagem`, { texto: texto.trim(), tipo: /\[\d{1,2}[:/]\d{2}/.test(texto) ? 'whatsapp' : 'texto' })
      }
      if (ehImportacao(arquivos)) {
        setPasso('Enviando os arquivos…')
        await importar(c.id, arquivos)          // o JdB lê tudo em segundo plano (áudios viram texto)
      } else {
        for (const [i, f] of arquivos.entries()) {
          setPasso(`Enviando arquivo ${i + 1} de ${arquivos.length}…`)
          const fd = new FormData(); fd.append('arquivo', f); fd.append('tipo', f.type.startsWith('image/') ? 'foto' : 'documento')
          await postForm(`/clientes/${c.id}/arquivo`, fd)
        }
        if (!texto.trim()) await post(`/clientes/${c.id}/entendimento`)   // ORDEM 062: resume e pergunta
      }
      ir('cliente', c.id)
    } catch (e) { setErro(erroDe(e)) } finally { setPasso('') }
  }
  return (
    <section className="tela-simples tela-larga">
      <button type="button" className="voltar-jdb" onClick={() => ir('lista')}><ArrowLeft size={18} aria-hidden="true" /> Trabalhos</button>
      <div>
        <h1 className="titulo-jdb">Novo trabalho</h1>
        <p className="sub-jdb">Cole o que você já tem. Eu organizo.</p>
        {/* 155-2: a contagem do plano, no começo do trabalho */}
        <p className="small-jdb">Este trabalho conta 1 laudo do seu plano quando o primeiro rascunho ficar pronto.</p>
      </div>
      <div className="proximo-passo relative" {...soltar.props}>
        {soltar.arrastando && <SolteAqui />}
        <label htmlFor="novo-texto" className="sr-only">Cole a conversa do WhatsApp ou escreva o que você já sabe</label>
        <textarea id="novo-texto" className="caixa-l2" rows={6} value={texto} onChange={(e) => setTexto(e.target.value)}
                  placeholder="Me conte quem é esse cliente e o que ele precisa. Se quiser, exporte a conversa do WhatsApp com ele (com as mídias) e solte aqui: eu leio tudo, inclusive os áudios." />
        <FalarAqui alvo="novo-texto" valor={texto} aoMudar={setTexto} />
        <p className="small-jdb">Como exportar a conversa: no WhatsApp, abra a conversa › ⋮ › Mais › Exportar conversa › Incluir mídia.</p>
        {arquivos.length > 0 && (
          <div className="grid gap-2">
            <p className="small-jdb">{arquivos.length} {arquivos.length === 1 ? 'arquivo anexado' : 'arquivos anexados'}:</p>
            {/* 069-A11: os nomes, cada um com × para tirar */}
            <ul className="anexos-l69">
              {arquivos.map((f, i) => (
                <li key={`${f.name}-${i}`}>
                  <span className="truncate">{f.name}</span>
                  <button type="button" aria-label={`Tirar ${f.name}`} disabled={!!passo}
                          onClick={() => setArquivos((a) => a.filter((_, k) => k !== i))}>×</button>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="botoes">
          <label className="btn-sec-grande">
            <Paperclip size={20} aria-hidden="true" /> Anexar arquivos
            <input type="file" multiple hidden accept={ACEITOS}
                   onChange={(e) => { juntar(Array.from(e.target.files ?? [])); e.target.value = '' }} />
          </label>
          <button type="button" className="btn-verde" disabled={!!passo} onClick={() => void comecar()}>{passo || 'Começar'}</button>
        </div>
        {aviso && <p className="aviso-simples" role="status">{aviso}</p>}
        {erro && <p className="aviso-impede" role="alert">{erro}</p>}
      </div>
      <div className="flex flex-wrap gap-x-8 gap-y-2">
        <button type="button" className="link-l2" onClick={() => ir('guia')}>Primeira vez? Me ensina a fazer</button>
        <button type="button" className="link-l2" onClick={() => setFicha(true)}>Prefiro preencher a ficha completa</button>
      </div>
    </section>
  )
}
