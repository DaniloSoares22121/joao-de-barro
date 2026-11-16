/* ORDEM 019: pesquisa pelo Chrome do avaliador — links de busca de cada portal + a extensão
 * "Enviar resultados desta página". Sem robô: quem abre a página é a pessoa. */
import { useEffect, useState } from 'react'
import { ExternalLink, Globe, Puzzle, Search } from 'lucide-react'
import { get } from './api'
import { AdicionarReferencial } from './Referenciais'

interface LinkBusca { portal: string; local: string; url: string }
// D-064 (ORDEM 037-1): pesquisa na internet inteira quando faltam semelhantes nos portais
interface Internet { url: string; consulta: string; minimo: number; semelhantes: number }

// ORDEM 076-3: a extensão está no Chrome? está fixada? permitida nos portais? (a extensão 1.1.0 informa)
interface EstadoExtensao { instalada: boolean; vista: string; atual: string; atualizar: boolean
  fixada: boolean | null; portais: boolean | null; captura?: boolean | null }

const PASTA_EXTENSAO = 'joao-de-barro\\extensao-chrome'

function AvisoExtensao() {
  const [e, setE] = useState<EstadoExtensao | null>(null)
  const [como, setComo] = useState(false)
  useEffect(() => {
    let vivo = true
    get<EstadoExtensao>('/extensao/estado').then((r) => { if (vivo) setE(r) }).catch(() => { /* sem aviso */ })
    return () => { vivo = false }
  }, [])
  if (!e) return null
  const passos = (
    <ol className="ml-5 list-decimal space-y-1">
      <li>No Chrome, abra <strong>chrome://extensions</strong> (copie e cole na barra de endereço).</li>
      <li>Ligue o <strong>“Modo do desenvolvedor”</strong>, no canto de cima, à direita.</li>
      <li>Toque em <strong>“Carregar sem compactação”</strong> e escolha a pasta <strong className="break-all">{PASTA_EXTENSAO}</strong>.</li>
    </ol>
  )
  if (!e.instalada) {
    return (
      <div className="min-w-0 overflow-hidden rounded-lg border border-[var(--amarelo)] bg-[#fff8e1] px-3 py-2" role="status" data-testid="aviso-extensao">
        <p className="flex flex-wrap items-center gap-2">
          <Puzzle size={16} aria-hidden="true" /> <strong>A extensão do JdB não está no seu Chrome.</strong>
          <button type="button" className="btn-sec btn-peq" onClick={() => setComo((c) => !c)} aria-expanded={como}>Como instalar</button>
        </p>
        {como && (
          <div className="mt-2 space-y-2">
            {passos}
            <img src="./jdb-marca/instalar-extensao.png" alt="A página chrome://extensions com o Modo do desenvolvedor ligado e o botão Carregar sem compactação"
                 className="block h-auto w-full max-w-[560px] rounded-lg border border-[var(--borda)]" loading="lazy" />
          </div>
        )}
      </div>
    )
  }
  const linhas: string[] = []
  if (e.atualizar) linhas.push(`Há uma versão nova da extensão (${e.atual}; a sua é a ${e.vista}). Em chrome://extensions, toque em ↻ no “Enviar ao JdB”.`)
  if (e.portais === false) linhas.push('Para o botão aparecer na página do anúncio: toque no ícone do JdB, no alto à direita do Chrome, e em “Permitir o JdB nos portais de imóveis”.')
  else if (e.captura === false) linhas.push('Para guardar a prova do acesso (a página com data, hora e link): toque no ícone do JdB e em “Permitir o JdB nos portais de imóveis” mais uma vez.')
  if (e.fixada === false) linhas.push('Toque na peça de quebra-cabeça 🧩, no alto à direita do Chrome, e fixe o “Enviar ao JdB”.')
  if (!linhas.length) return null
  return (
    <div className="min-w-0 space-y-1 rounded-lg border border-[var(--borda)] bg-[#f8f9fa] px-3 py-2 [overflow-wrap:anywhere]" role="status" data-testid="aviso-extensao">
      {linhas.map((l) => <p key={l} className="flex gap-2"><Puzzle size={16} className="mt-1 shrink-0" aria-hidden="true" /> {l}</p>)}
    </div>
  )
}

export default function LinksBusca({ jobId, colar = true }: { jobId: string; colar?: boolean }) {
  const [links, setLinks] = useState<LinkBusca[] | null>(null)
  const [internet, setInternet] = useState<Internet | null>(null)
  const [erro, setErro] = useState('')
  const [aberto, setAberto] = useState(false)
  const [aviso, setAviso] = useState('')

  async function abrir() {
    setAberto((a) => !a)
    if (links !== null) return
    try {
      const r = await get<{ links: LinkBusca[]; internet?: Internet }>(`/jobs/${encodeURIComponent(jobId)}/pesquisa/links`)
      setLinks(r.links)
      setInternet(r.internet ?? null)
    } catch {
      setErro('Não foi possível montar os links de busca.')
    }
  }

  return (
    // 076: dentro de "Ver ou mudar a escolha", a tabela larga não pode esticar este bloco além da tela
    <div className="sticky left-0 max-w-[min(760px,calc(100vw-72px))] space-y-2">
    <div className="rounded-xl border border-[var(--borda)] bg-white">
      <button type="button" onClick={() => void abrir()} aria-expanded={aberto}
              className="foco flex min-h-[48px] w-full items-center gap-2 px-3 py-2.5 text-left text-[16px] font-semibold">
        <Search size={16} aria-hidden="true" /> Pesquisar no seu Chrome
        <span className="ml-auto text-[16px] font-normal text-[var(--cinza)]">{aberto ? 'fechar' : 'abrir'}</span>
      </button>
      {aberto && (
        <div className="space-y-2 border-t border-[var(--borda)] px-3 py-3 text-[16px]">
          <p className="text-[var(--cinza)]">
            Abra a busca do portal no seu Chrome. Vai aparecer o botão <strong>Enviar ao JdB</strong> no canto da
            página: na lista de resultados ele manda todos os anúncios da página; num anúncio aberto, manda aquele
            anúncio com foto e dados. Os anúncios entram nesta lista pelos mesmos filtros (região, repetidos e semelhança).
          </p>
          {erro && <p className="erro-txt" role="alert">{erro}</p>}
          {links === null && !erro && <p className="text-[16px] text-[var(--cinza)]">Montando os links…</p>}
          {links && links.length === 0 && <p className="text-[16px] text-[var(--cinza)]">Sem links para este trabalho.</p>}
          {links && links.length > 0 && (
            <ul className="flex flex-wrap gap-2">
              {links.map((l) => (
                <li key={l.url}>
                  <a href={l.url} target="_blank" rel="noopener noreferrer"
                     className="btn-sec btn-peq inline-flex items-center gap-1.5">
                    {l.portal} · {l.local} <ExternalLink size={12} aria-hidden="true" />
                  </a>
                </li>
              ))}
            </ul>
          )}
          {internet && (
            <div className={`rounded-lg border px-3 py-2 ${internet.semelhantes < internet.minimo ? 'border-[var(--amarelo)] bg-[#fff8e1]' : 'border-[var(--borda)]'}`}>
              {internet.semelhantes < internet.minimo && (
                <p className="mb-1 text-[16px]">
                  Só {internet.semelhantes} {internet.semelhantes === 1 ? 'semelhante' : 'semelhantes'} nos portais (o mínimo é {internet.minimo}).
                  Amplie a busca para sites de imobiliárias e outros sites de anúncio.
                </p>
              )}
              <a href={internet.url} target="_blank" rel="noopener noreferrer"
                 className="btn-sec btn-peq inline-flex items-center gap-1.5" title={internet.consulta}>
                <Globe size={14} aria-hidden="true" /> Ampliar a busca na internet <ExternalLink size={12} aria-hidden="true" />
              </a>
              <p className="mt-1 text-[16px] text-[var(--cinza)]">
                Abra o anúncio. Vai aparecer o botão <strong>Enviar ao JdB</strong> no canto da página: o sistema lê preço,
                áreas e endereço e confere a área do anúncio com o texto.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
    <AvisoExtensao />
    {colar && (
      <div className="flex flex-wrap items-center gap-2" data-testid="colar-link">
        <AdicionarReferencial jobId={jobId} aoMudar={setAviso} rotulo="+ Colar o link de um anúncio" />
        {aviso && <span className="text-[16px] text-[var(--cinza)]" role="status">{aviso}</span>}
      </div>
    )}
    </div>
  )
}
