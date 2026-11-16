/* ORDEM 194: Marca e modelos › "Modelos de laudo".
 * Um cartão por modalidade (OV, PTAM não judicial, PTAM para garantia, PTAM judicial): miniatura e [Ver exemplo]
 * (PDF com dados inventados), "Em uso: o do sistema" ou "Em uso: o meu", [Subir o meu modelo] (PDF ou Word, guardado
 * sem dados de clientes; mostra "o que entendi" para confirmar) e [Voltar para o do sistema]. Trocar ou voltar pede
 * confirmação (183). A modalidade continua sendo do trabalho: o avaliador não escolhe modelo a cada laudo.
 * Proposta e Contrato: um modelo cada, também com [Ver exemplo]. */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Eye, Upload } from 'lucide-react'
import Confirmar from './Confirmar'
import { ApiError, baixarRaw, get, post, postForm } from './api'

interface Mod { cod: string; nome: string; em_uso: 'sistema' | 'proprio'; enviado_em: string; exemplo: string }
interface Resp { modalidades: Mod[]; outros: Record<string, string> }
interface Formato { fonte: string; tamanho: number | null; cor_principal: string; cor_destaque: string }
interface ItemModelo { i: number; titulo: string; depende_do_trabalho: boolean }
const erroDe = (e: unknown) => (e instanceof ApiError ? e.message : 'Não deu certo. Tente de novo.')

/** Abre o PDF de exemplo numa aba nova (a aba abre já no toque: o navegador não bloqueia). */
export async function verExemplo(nome: string, aoErro: (m: string) => void) {
  const aba = window.open('', '_blank')
  try {
    const { blob } = await baixarRaw(`/modelos/exemplo/${encodeURIComponent(nome)}`)
    const u = URL.createObjectURL(blob)
    if (aba) aba.location.href = u; else window.open(u, '_blank')
    window.setTimeout(() => URL.revokeObjectURL(u), 120000)
  } catch (e) { aba?.close(); aoErro(erroDe(e)) }
}

export function Miniatura({ nome, rotulo }: { nome: string; rotulo: string }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let u = ''; let vivo = true
    baixarRaw(`/modelos/exemplo/${encodeURIComponent(nome)}?miniatura=true`)
      .then(({ blob }) => { if (vivo) { u = URL.createObjectURL(blob); setUrl(u) } }).catch(() => undefined)
    return () => { vivo = false; if (u) URL.revokeObjectURL(u) }
  }, [nome])
  return (
    <span style={{ width: 96, height: 132, flex: '0 0 96px', border: '1px solid #d5dbe3', borderRadius: 8, background: '#fff', overflow: 'hidden', display: 'block' }}>
      {url && <img src={url} alt={`Primeira página do exemplo: ${rotulo}`} style={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'top' }} />}
    </span>
  )
}

export default function ModelosLaudo() {
  const [r, setR] = useState<Resp | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; texto: string } | null>(null)
  const [ocupado, setOcupado] = useState('')
  const [entendi, setEntendi] = useState<{ cod: string; nome: string; guardado: string; topicos: string[]; marcados: Set<number>
    formato: Formato; itens: ItemModelo[]; itensMarcados: Set<number>; usarFormato: boolean; fora: string[] } | null>(null)
  const [perguntar, setPerguntar] = useState<{ tipo: 'trocar' | 'voltar'; m: Mod } | null>(null)
  const arquivo = useRef<HTMLInputElement>(null)
  const alvo = useRef<Mod | null>(null)
  const carregar = useCallback(() => { get<Resp>('/avaliadores/eu/modelos-laudo').then(setR).catch(() => setMsg({ ok: false, texto: 'Não deu para abrir os modelos.' })) }, [])
  useEffect(carregar, [carregar])

  function escolherArquivo(m: Mod) { alvo.current = m; arquivo.current?.click() }
  async function subir(f: File | undefined) {
    const m = alvo.current
    if (!f || !m) return
    setOcupado(m.cod); setMsg({ ok: true, texto: 'Lendo o seu modelo e tirando os dados de clientes…' })
    try {
      const fd = new FormData(); fd.append('arquivo', f); fd.append('qual', 'laudo'); fd.append('modalidade', m.cod)
      const x = await postForm<{ guardado: string; topicos: string[]; formato: Formato; itens: ItemModelo[]; fora_estrutura?: string[] }>('/avaliadores/eu/modelo', fd)
      const itens = x.itens ?? []
      setEntendi({ cod: m.cod, nome: m.nome, guardado: x.guardado, topicos: x.topicos, marcados: new Set(x.topicos.map((_, i) => i)),
                   formato: x.formato, itens, itensMarcados: new Set(itens.filter((i) => !i.depende_do_trabalho).map((i) => i.i)),
                   usarFormato: !!(x.formato?.fonte || x.formato?.cor_principal), fora: x.fora_estrutura ?? [] })
      setMsg(null)
    } catch (e) { setMsg({ ok: false, texto: erroDe(e) }) } finally { setOcupado('') }
  }
  async function usar() {
    if (!entendi) return
    setOcupado(entendi.cod)
    try {
      await post('/avaliadores/eu/regras-confirmadas', { topicos: entendi.topicos.filter((_, i) => entendi.marcados.has(i)),
                                                           modalidade: entendi.cod, guardado: entendi.guardado,
                                                           itens: [...entendi.itensMarcados], usar_formato: entendi.usarFormato })
      setMsg({ ok: true, texto: `Pronto: o seu modelo de ${entendi.nome} está em uso.` }); setEntendi(null); carregar()
    } catch (e) { setMsg({ ok: false, texto: erroDe(e) }) } finally { setOcupado('') }
  }
  async function voltar(m: Mod) {
    setOcupado(m.cod)
    try { await post(`/avaliadores/eu/modelos-laudo/${encodeURIComponent(m.cod)}/voltar`); setMsg({ ok: true, texto: `${m.nome}: voltou para o modelo do sistema.` }); carregar() }
    catch (e) { setMsg({ ok: false, texto: erroDe(e) }) } finally { setOcupado('') }
  }
  if (!r) return <p className="texto" role="status">{msg?.texto ?? 'Abrindo os modelos…'}</p>
  return (
    <section className="grid gap-3" aria-labelledby="modelos-laudo-t">
      <h2 id="modelos-laudo-t" className="subtitulo">Modelos de laudo</h2>
      <p className="texto">Um modelo por modalidade. O trabalho usa o modelo da modalidade dele; você não escolhe a cada laudo.
        Os exemplos têm dados inventados.</p>
      {/* L198: sem prometer o que não faz */}
      <p className="texto">O laudo segue o padrão JdB, com a sua formatação e os itens a mais do seu modelo.</p>
      <input ref={arquivo} type="file" accept=".pdf,.docx" hidden onChange={(e) => { void subir(e.target.files?.[0]); e.target.value = '' }} />
      <ul className="grid gap-3" aria-label="Modelos de laudo por modalidade">
        {r.modalidades.map((m) => (
          <li key={m.cod} className="cartao-pad flex flex-wrap items-start gap-3" aria-label={m.nome}>
            <Miniatura nome={m.exemplo} rotulo={m.nome} />
            <div className="grid min-w-0 flex-1 gap-2" style={{ flexBasis: 220 }}>
              <p className="titulo-cartao" style={{ margin: 0 }}>{m.nome}</p>
              <span className={m.em_uso === 'proprio' ? 'etiqueta-ok' : 'etiqueta-neutra'}
                    style={{ justifySelf: 'start', borderRadius: 999, padding: '2px 10px', fontWeight: 700, fontSize: 15,
                             background: m.em_uso === 'proprio' ? '#E6F4EC' : '#EEF1F5', color: m.em_uso === 'proprio' ? '#14803F' : '#1C2B3A' }}>
                {m.em_uso === 'proprio' ? `Em uso: o meu${m.enviado_em ? ` (enviado em ${m.enviado_em})` : ''}` : 'Em uso: o do sistema'}</span>
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} onClick={() => void verExemplo(m.exemplo, (t) => setMsg({ ok: false, texto: t }))}>
                  <Eye size={18} aria-hidden="true" /> Ver exemplo</button>
                <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} disabled={!!ocupado}
                        onClick={() => (m.em_uso === 'proprio' ? setPerguntar({ tipo: 'trocar', m }) : escolherArquivo(m))}>
                  <Upload size={18} aria-hidden="true" /> {ocupado === m.cod ? 'Lendo…' : m.em_uso === 'proprio' ? 'Trocar o meu modelo' : 'Subir o meu modelo'}</button>
                {m.em_uso === 'proprio' && (
                  <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} disabled={!!ocupado} onClick={() => setPerguntar({ tipo: 'voltar', m })}>
                    Voltar para o do sistema</button>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {entendi && (
        <div className="proximo-passo" role="group" aria-label={`O que entendi do seu modelo de ${entendi.nome}`}>
          <p className="bloco-rotulo">Confira o que entendi do seu modelo de {entendi.nome}</p>
          {(entendi.formato?.fonte || entendi.formato?.cor_principal) ? (
            <label className="texto"><input type="checkbox" checked={entendi.usarFormato} onChange={() => setEntendi({ ...entendi, usarFormato: !entendi.usarFormato })} />
              {' '}Formatação que vou usar: {[entendi.formato.fonte && `fonte ${entendi.formato.fonte}`, entendi.formato.tamanho && `tamanho ${String(entendi.formato.tamanho).replace('.', ',')}`].filter(Boolean).join(', ')}
              {(entendi.formato.cor_principal || entendi.formato.cor_destaque) && <>, cores {[entendi.formato.cor_principal, entendi.formato.cor_destaque].filter(Boolean).map((c) => (
                <span key={c} title={`#${c}`} aria-label={`cor #${c}`} style={{ display: 'inline-block', width: 18, height: 18, borderRadius: 4, background: `#${c}`, verticalAlign: 'middle', margin: '0 3px', border: '1px solid #ccc' }} />))}</>}
            </label>
          ) : <p className="texto">Não achei formatação no arquivo: fica a do padrão JdB.</p>}
          {entendi.itens.filter((i) => !i.depende_do_trabalho).length > 0 && (
            <>
              <p className="texto" style={{ marginBottom: 0 }}><b>Itens do seu modelo que vou acrescentar</b> (entram antes da Assinatura):</p>
              <ul className="lista-marcar">
                {entendi.itens.filter((i) => !i.depende_do_trabalho).map((it) => (
                  <li key={it.i}><label className="texto"><input type="checkbox" checked={entendi.itensMarcados.has(it.i)} onChange={() => {
                    const s = new Set(entendi.itensMarcados); if (s.has(it.i)) s.delete(it.i); else s.add(it.i); setEntendi({ ...entendi, itensMarcados: s })
                  }} /> {it.titulo}</label></li>
                ))}
              </ul>
            </>
          )}
          <p className="texto" style={{ marginBottom: 0 }}><b>Regras de escrita</b> que tirei do seu modelo:</p>
          {entendi.topicos.length === 0 ? <p className="texto">Não consegui tirar pontos deste arquivo. Você pode usar assim mesmo ou cancelar.</p> : (
            <ul className="lista-marcar">
              {entendi.topicos.map((t, i) => (
                <li key={i}><label className="texto"><input type="checkbox" checked={entendi.marcados.has(i)} onChange={() => {
                  const s = new Set(entendi.marcados); if (s.has(i)) s.delete(i); else s.add(i); setEntendi({ ...entendi, marcados: s })
                }} /> {t}</label></li>
              ))}
            </ul>
          )}
          {/* L199: estrutura e diagramação não viram regra (o laudo segue o padrão JdB) */}
          {(entendi.fora.length > 0 || entendi.itens.some((i) => i.depende_do_trabalho)) && (
            <div className="small-jdb" role="note">
              <b>Ficam de fora:</b>
              <ul style={{ margin: '4px 0 0 18px' }}>
                {entendi.fora.map((f) => <li key={f}>{f} — o laudo segue o padrão JdB</li>)}
                {entendi.itens.filter((i) => i.depende_do_trabalho).map((i) => <li key={`i${i.i}`}>{i.titulo} — muda a cada trabalho</li>)}
              </ul>
            </div>
          )}
          <p className="small-jdb">Guardado sem dados de clientes. O que você marcar vira regra sua, só para os laudos de {entendi.nome}.</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-verde" style={{ width: 'auto' }} disabled={!!ocupado} onClick={() => void usar()}>Usar este modelo</button>
            <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} onClick={() => setEntendi(null)}>Cancelar</button>
          </div>
        </div>
      )}
      {msg && <p className={msg.ok ? 'aviso-simples' : 'aviso-impede'} role={msg.ok ? 'status' : 'alert'}>{msg.texto}</p>}
      {perguntar && (
        <Confirmar titulo={perguntar.tipo === 'voltar' ? `Voltar para o modelo do sistema em ${perguntar.m.nome}?` : `Trocar o seu modelo de ${perguntar.m.nome}?`}
                   texto={perguntar.tipo === 'voltar'
                     ? 'Os próximos laudos dessa modalidade saem no modelo do sistema. As regras tiradas do seu modelo ficam desligadas.'
                     : 'Você escolhe o arquivo novo e confere o que entendi. As regras do modelo anterior ficam desligadas.'}
                   rotuloConfirmar={perguntar.tipo === 'voltar' ? 'Voltar para o do sistema' : 'Escolher o arquivo novo'}
                   aoConfirmar={() => { const p = perguntar; setPerguntar(null); if (p.tipo === 'voltar') void voltar(p.m); else escolherArquivo(p.m) }}
                   aoCancelar={() => setPerguntar(null)} />
      )}
    </section>
  )
}
