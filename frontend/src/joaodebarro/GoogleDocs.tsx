/* ORDEM 169: o laudo editável no Google Docs, numa pasta do JdB no Drive do próprio avaliador.
 * - "Google" nas Configurações: conta ligada, [Conectar o Google] / [Desligar]; a chave do app (só o dono).
 * - abrirLaudoEditavel(): com o Google ligado, sobe (uma vez) e abre o Google Docs numa aba nova, sempre a mesma;
 *   sem a chave do app ainda cadastrada, continua o editor do JdB (reserva); com a chave e sem a conta ligada, pede
 *   para conectar antes. A chave e os tokens nunca voltam para a tela. */
import { useEffect, useState } from 'react'
import { ApiError, get, post, put } from './api'
import { abrirEditavel } from './EditorLaudo'

export interface StatusGoogle { configurado: boolean; conectado: boolean; email: string }

export async function statusGoogle(): Promise<StatusGoogle | null> {
  try { return await get<StatusGoogle>('/google/status') } catch { return null }
}

/** Abre a janela do login do Google; avisa quando voltar (a página de retorno manda 'google-conectado'). */
export async function conectarGoogle(aoConectar?: () => void): Promise<void> {
  const { url } = await get<{ url: string }>('/google/conectar')
  const w = window.open(url, 'jdb-google-login', 'popup=yes,width=520,height=680')
  const ouvir = (ev: MessageEvent) => {
    if ((ev.data as { jdb?: string } | null)?.jdb !== 'google-conectado') return
    window.removeEventListener('message', ouvir); aoConectar?.()
  }
  window.addEventListener('message', ouvir)
  const t = window.setInterval(() => { if (!w || w.closed) { window.clearInterval(t); window.removeEventListener('message', ouvir); aoConectar?.() } }, 1500)
}

export class PrecisaConectar extends Error {}

/** 169-3: [Abrir o laudo editável]. Devolve 'google' | 'jdb' (reserva). Lança PrecisaConectar sem a conta ligada. */
export async function abrirLaudoEditavel(jobId: string, pagina?: number, trecho?: string, modo?: 'revisao'): Promise<'google' | 'jdb'> {
  const st = await statusGoogle()
  if (!st || !st.configurado) {                    // a chave do Google ainda não existe: o editor do JdB (reserva)
    abrirEditavel(jobId, pagina, trecho, modo)
    return 'jdb'
  }
  if (!st.conectado) throw new PrecisaConectar('Conecte o seu Google para abrir o laudo editável (Configurações → Google).')
  // 169-4: o cartão leva ao ponto do Docs — a âncora (título/marcador) mais próxima antes da frase; a frase vai para a
  // área de transferência, para achar com Ctrl+F (o Google não aceita link para uma frase)
  if (trecho) { try { void navigator.clipboard?.writeText(trecho) } catch { /* sem permissão: segue */ } }
  const aba = window.open('', `jdb-gdocs-${jobId}`)        // abre já (o navegador só deixa abrir aba no toque)
  try {
    const r = await post<{ url: string }>(`/jobs/${encodeURIComponent(jobId)}/google/abrir`, {})
    let url = r.url
    if (trecho) {
      try {
        const a = await get<{ ancora: string }>(`/jobs/${encodeURIComponent(jobId)}/google/ancora?trecho=${encodeURIComponent(trecho.slice(0, 200))}`)
        if (a.ancora) url = r.url.split('#')[0] + a.ancora
      } catch { /* sem âncora: abre no começo */ }
    }
    if (aba) aba.location.href = url
    else window.open(url, `jdb-gdocs-${jobId}`)
    return 'google'
  } catch (e) {
    aba?.close()
    throw e
  }
}

/** Para os botões: abre e, se faltar a conta Google, pergunta se conecta agora (nunca um toque sem resposta). */
export function abrirOuAvisar(jobId: string, pagina?: number, trecho?: string, modo?: 'revisao'): void {
  abrirLaudoEditavel(jobId, pagina, trecho, modo).catch((e) => {
    if (e instanceof PrecisaConectar) {
      if (window.confirm('Para abrir o laudo editável no Google Docs, conecte o seu Google. Conectar agora?')) void conectarGoogle()
      return
    }
    window.alert(e instanceof ApiError ? e.message : 'Não consegui abrir o laudo editável. Tente de novo.')
  })
}

/** "Google" nas Configurações. */
export function GoogleConta({ dono }: { dono: boolean }) {
  const [st, setSt] = useState<StatusGoogle | null>(null)
  const [msg, setMsg] = useState('')
  const [cid, setCid] = useState('')
  const [seg, setSeg] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const ler = () => { void statusGoogle().then(setSt) }
  useEffect(ler, [])
  async function agir(f: () => Promise<unknown>, ok: string) {
    setMsg(''); setOcupado(true)
    try { await f(); setMsg(ok); ler() } catch (e) { setMsg(e instanceof ApiError ? e.message : 'Não deu certo. Tente de novo.') }
    finally { setOcupado(false) }
  }
  if (!st) return null
  return (
    <section className="cartao-pad grid gap-2" aria-labelledby="google-titulo">
      <h2 id="google-titulo" className="titulo-cartao">Google (laudo editável no seu Drive)</h2>
      {st.conectado ? (
        <>
          <p className="texto">Conta ligada: <b>{st.email || 'conta Google'}</b>. O JdB só vê os arquivos que ele mesmo cria, na pasta “João de Barro”.</p>
          <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} disabled={ocupado}
                  onClick={() => void agir(() => post('/google/desligar', {}), 'Google desligado.')}>Desligar</button>
        </>
      ) : st.configurado ? (
        <>
          <p className="texto">Ligue a sua conta Google: o laudo editável abre no Google Docs, numa pasta “João de Barro” do seu Drive.</p>
          <button type="button" className="btn-verde" style={{ width: 'auto' }} disabled={ocupado}
                  onClick={() => void agir(() => conectarGoogle(ler), 'Termine o login na janela do Google.')}>Conectar o Google</button>
        </>
      ) : (
        <p className="texto">A chave do Google ainda não foi cadastrada. Até lá, o laudo editável abre no editor do próprio JdB.</p>
      )}
      {dono && (                                   // a chave do app: só o dono; nunca volta para a tela
        <details>
          <summary className="texto">Chave do app no Google (só o dono)</summary>
          <div className="grid gap-2" style={{ marginTop: 8 }}>
            <label className="rotulo" htmlFor="g-cid">ID do cliente</label>
            <input id="g-cid" className="input" autoComplete="off" value={cid} onChange={(e) => setCid(e.target.value)} />
            <label className="rotulo" htmlFor="g-seg">Chave secreta</label>
            <input id="g-seg" className="input" type="password" autoComplete="off" value={seg} onChange={(e) => setSeg(e.target.value)} />
            <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} disabled={ocupado || !cid.trim() || !seg.trim()}
                    onClick={() => void agir(async () => { await put('/google/cliente', { client_id: cid, client_secret: seg }); setCid(''); setSeg('') },
                                             'Chave guardada neste computador. Ela não aparece de novo na tela.')}>
              Guardar a chave</button>
            <p className="small-jdb">{st.configurado ? 'Já há uma chave guardada. Guardar de novo troca a chave.' : 'Nenhuma chave guardada.'}</p>
          </div>
        </details>
      )}
      {msg && <p className="small-jdb" role="status">{msg}</p>}
    </section>
  )
}
