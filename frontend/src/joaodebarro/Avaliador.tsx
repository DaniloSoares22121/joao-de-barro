/* ORDEM 042 (D-094 a D-097, K3): cadastro do avaliador, identidade (logo e cores), modelos
 * (do sistema ou os meus, anonimizados antes de guardar), "me ensina a fazer" e Minhas regras.
 * Regras de tela (D-101): letra grande, um próximo passo, detalhes recolhidos. */
import { useCallback, useEffect, useState } from 'react'
import { ApiError, get, post, postForm, put } from './api'
import { DadosDoDono, IdentidadeVisual } from './Config'
import { useStore } from './store'
import ModelosLaudo, { Miniatura, verExemplo } from './ModelosLaudo'

const MODS = [['OV', 'Opinião de Valor'], ['AM', 'PTAM não judicial'], ['AM_GARANTIA', 'PTAM garantia'], ['AMJ', 'PTAM judicial']] as const
const TIPOS = ['casa', 'apartamento', 'lote', 'galpão', 'sala/loja', 'rural']
const erroDe = (e: unknown) => (e instanceof ApiError ? e.message : 'Não deu certo.')

// 186: nenhum destes formulários é de login: o navegador não preenche (senha: "new-password", o resto: "off")
function Campo({ id, rotulo, valor, mudar, tipo = 'text' }: { id: string; rotulo: string; valor: string; mudar: (v: string) => void; tipo?: string }) {
  return (
    <label className="campo-bloco" htmlFor={id}>
      <span className="bloco-rotulo">{rotulo}</span>
      <input id={id} name={`jdb-${id}`} type={tipo} className="campo-grande" value={valor} onChange={(e) => mudar(e.target.value)}
             autoComplete={tipo === 'password' ? 'new-password' : 'off'} data-lpignore="true" data-1p-ignore="" />
    </label>
  )
}

interface Eu { id: string; dados: Record<string, unknown>; tem_logo: boolean; cores: Record<string, string>; laudo_geral: string; modelos: Record<string, string> }

export function MeuCadastro({ parte = 'dados' }: { parte?: 'dados' | 'marca' }) {
  const ir = useStore((s) => s.ir)
  const [eu, setEu] = useState<Eu | null>(null)
  const [d, setD] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState('')
  const [topicos, setTopicos] = useState<string[]>([])
  const [marcados, setMarcados] = useState<Set<number>>(new Set())
  const carregar = useCallback(() => {
    get<Eu>('/avaliadores/eu').then((r) => {
      setEu(r)
      const x = r.dados
      setD({ nome: String(x.nome ?? ''), creci: String(x.creci ?? ''), cnai: String(x.cnai ?? ''), cidade: String(x.cidade ?? ''),
        telefone: String(x.telefone ?? ''), site: String(x.site ?? ''), instagram: String(x.instagram ?? ''), formacao: String(x.formacao ?? '') })
    }).catch(() => undefined)
  }, [])
  useEffect(carregar, [carregar])
  if (!eu) return <p className="texto-grande" role="status">Abrindo…</p>
  const alan = eu.id === 'AV-0001'
  async function salvar() {
    try { await put('/avaliadores/eu', d); setMsg('Cadastro salvo.'); carregar() } catch (e) { setMsg(erroDe(e)) }
  }
  async function enviarLogo(f?: File) {
    if (!f) return
    const fd = new FormData(); fd.append('arquivo', f)
    try { await postForm('/avaliadores/eu/logo', fd); setMsg('Logo enviada.'); carregar() } catch (e) { setMsg(erroDe(e)) }
  }
  async function cores(campo: string, v: string) {
    await put('/avaliadores/eu', { cores: { ...eu!.cores, [campo]: v.replace('#', '') } }); carregar()
  }
  async function subirModelo(qual: string, f?: File) {
    if (!f) return
    const fd = new FormData(); fd.append('arquivo', f); fd.append('qual', qual)
    setMsg('Lendo e tirando os dados de clientes…')
    try {
      const r = await postForm<{ topicos: string[] }>('/avaliadores/eu/modelo', fd)
      setTopicos(r.topicos); setMarcados(new Set(r.topicos.map((_, i) => i)))
      setMsg(qual === 'laudo' ? 'Confira o que entendi do seu laudo.' : 'Modelo guardado sem dados de clientes.')
      carregar()
    } catch (e) { setMsg(erroDe(e)) }
  }
  async function confirmar() {
    await post('/avaliadores/eu/regras-confirmadas', { topicos: topicos.filter((_, i) => marcados.has(i)) })
    setTopicos([]); setMsg('Regras guardadas como suas.')
  }
  async function modelo(qual: string, v: string) { await put('/avaliadores/eu/modelos', { ...eu!.modelos, [qual]: v }); carregar() }
  return (
    <section className="tela-simples">
      <button type="button" className="voltar-jdb" onClick={() => ir('config')}>← Configurações</button>
      <h1 className="titulo-tela">{parte === 'marca' ? 'Marca e modelos' : 'Meus dados'}</h1>
      <p className="linha-tela">{parte === 'marca' ? 'A logo e os modelos que saem nos seus documentos.' : 'O que sai no seu laudo.'}</p>
      {/* 184: o dono via aqui só "Dados do Alan ficam em Configurações"; agora os blocos dele estão aqui */}
      {alan && parte === 'dados' && <DadosDoDono />}
      {alan && parte === 'marca' && <IdentidadeVisual />}
      {/* 194: a galeria dos modelos de laudo (um por modalidade), para o dono e para os outros avaliadores */}
      {parte === 'marca' && <ModelosLaudo />}
      {parte === 'marca' && <ModelosDocumentos modelos={eu.modelos} alan={alan} mudar={(q, v) => void modelo(q, v)} subir={(q, f) => void subirModelo(q, f)} />}
      {msg && <p className="aviso-simples" role="status">{msg}</p>}
      {!alan && parte === 'dados' && (
        <div className="proximo-passo">
          <p className="bloco-rotulo">Próximo passo</p>
          <div className="grade-campos">
            <Campo id="c-nome" rotulo="Nome no laudo" valor={d.nome} mudar={(v) => setD({ ...d, nome: v })} />
            <Campo id="c-creci" rotulo="CRECI" valor={d.creci} mudar={(v) => setD({ ...d, creci: v })} />
            <Campo id="c-cnai" rotulo="CNAI (sem ele, só OV)" valor={d.cnai} mudar={(v) => setD({ ...d, cnai: v })} />
            <Campo id="c-cidade" rotulo="Cidade" valor={d.cidade} mudar={(v) => setD({ ...d, cidade: v })} />
            <Campo id="c-tel" rotulo="Telefone" valor={d.telefone} mudar={(v) => setD({ ...d, telefone: v })} />
            <Campo id="c-site" rotulo="Site" valor={d.site} mudar={(v) => setD({ ...d, site: v })} />
            <Campo id="c-insta" rotulo="Instagram" valor={d.instagram} mudar={(v) => setD({ ...d, instagram: v })} />
            <Campo id="c-form" rotulo="Formação" valor={d.formacao} mudar={(v) => setD({ ...d, formacao: v })} />
          </div>
          <button type="button" className="btn-verde" onClick={() => void salvar()}>Salvar cadastro</button>
        </div>
      )}
      {!alan && parte === 'marca' && (
        <>
          <h2 className="subtitulo">Logo e cores</h2>
          <p className="texto">{eu.tem_logo ? 'Sua logo está guardada.' : 'Sem logo: o laudo sai neutro, sem marca.'}</p>
          <div className="botoes">
            <label className="btn-sec-grande">Enviar logo (PNG)<input type="file" accept="image/png" hidden onChange={(e) => void enviarLogo(e.target.files?.[0])} /></label>
            {(['principal', 'destaque', 'texto'] as const).map((k) => (
              <label key={k} className="texto cor-campo">{k === 'principal' ? 'Cor principal' : k === 'destaque' ? 'Destaque' : 'Texto'}
                <input type="color" value={`#${eu.cores[k] ?? '333333'}`} onChange={(e) => void cores(k, e.target.value)} />
              </label>
            ))}
          </div>
          {/* 194: o "Laudo" (um só para tudo) virou a galeria "Modelos de laudo"; Proposta e Contrato estão em ModelosDocumentos */}
          {topicos.length > 0 && (
            <div className="proximo-passo">
              <p className="bloco-rotulo">Confira o que entendi do seu laudo</p>
              <ul className="lista-marcar">
                {topicos.map((t, i) => (
                  <li key={i}><label className="texto"><input type="checkbox" checked={marcados.has(i)}
                    onChange={() => { const s = new Set(marcados); if (s.has(i)) s.delete(i); else s.add(i); setMarcados(s) }} /> {t}</label></li>
                ))}
              </ul>
              <button type="button" className="btn-verde" onClick={() => void confirmar()}>Guardar como minhas regras</button>
            </div>
          )}
        </>
      )}
      {/* 184-4: o "Me ensina a fazer" daqui saiu: repetia o "Me mostre como se faz" (Coletor e sistema) e o guia do Novo trabalho */}
    </section>
  )
}

/** 194-5: Proposta e Contrato — um modelo cada, com [Ver exemplo] (dados inventados). */
function ModelosDocumentos({ modelos, alan, mudar, subir }: { modelos: Record<string, string>; alan: boolean
  mudar: (q: string, v: string) => void; subir: (q: string, f?: File) => void }) {
  const [erro, setErro] = useState('')
  return (
    <section className="grid gap-3" aria-labelledby="modelos-docs-t">
      <h2 id="modelos-docs-t" className="subtitulo">Proposta e contrato</h2>
      <ul className="grid gap-3">
        {(['proposta', 'contrato'] as const).map((q) => (
          <li key={q} className="cartao-pad flex flex-wrap items-start gap-3" aria-label={q === 'proposta' ? 'Proposta' : 'Contrato'}>
            <Miniatura nome={q} rotulo={q === 'proposta' ? 'Proposta' : 'Contrato'} />
            <div className="grid min-w-0 flex-1 gap-2" style={{ flexBasis: 220 }}>
              <p className="titulo-cartao" style={{ margin: 0 }}>{q === 'proposta' ? 'Proposta' : 'Contrato'}</p>
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn-sec-grande" style={{ width: 'auto' }} onClick={() => void verExemplo(q, setErro)}>Ver exemplo</button>
                {!alan && <>
                  <button type="button" className={modelos[q] === 'proprio' ? 'btn-sec-grande' : 'btn-verde'} style={{ width: 'auto' }} onClick={() => mudar(q, 'sistema')}>Do sistema</button>
                  <label className={modelos[q] === 'proprio' ? 'btn-verde' : 'btn-sec-grande'} style={{ width: 'auto' }}>O meu
                    <input type="file" accept=".pdf,.docx" hidden onChange={(e) => subir(q, e.target.files?.[0])} /></label>
                </>}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {erro && <p className="aviso-impede" role="alert">{erro}</p>}
    </section>
  )
}

export function CadastrarAvaliador() {
  const [f, setF] = useState({ email: '', senha: '', nome: '', creci: '', cnai: '', cidade: '' })
  const [mods, setMods] = useState<string[]>(['OV'])
  const [tipos, setTipos] = useState<string[]>([])
  const [compart, setCompart] = useState<boolean | null>(null)
  const [lista, setLista] = useState<{ id: string; nome: string }[]>([])
  const [msg, setMsg] = useState('')
  const carregar = useCallback(() => { get<{ avaliadores: { id: string; nome: string }[] }>('/avaliadores').then((r) => setLista(r.avaliadores)).catch(() => undefined) }, [])
  useEffect(carregar, [carregar])
  const [dono, setDono] = useState<boolean | null>(null)       // 185: só o dono cadastra; o comum via o formulário e o servidor recusava
  useEffect(() => { get<{ id: string }>('/avaliadores/eu').then((r) => setDono(r.id === 'AV-0001')).catch(() => setDono(false)) }, [])
  async function cadastrar() {
    try {
      const r = await post<{ id: string }>('/avaliadores', { ...f, modalidades: mods, tipos, compartilhar: compart })
      setMsg(`Avaliador cadastrado: ${r.id}.`); carregar()
    } catch (e) { setMsg(erroDe(e)) }
  }
  const alterna = (l: string[], v: string) => (l.includes(v) ? l.filter((x) => x !== v) : [...l, v])
  if (dono === null) return <p className="texto-grande" role="status">Abrindo…</p>
  if (!dono) return (
    <section className="tela-simples">
      <h1 className="titulo-tela">Avaliadores</h1>
      <p className="aviso-simples">Só o dono do sistema cadastra avaliadores.</p>
    </section>
  )
  return (
    <section className="tela-simples">
      <h1 className="titulo-tela">Avaliadores</h1>
      <p className="linha-tela">Cada avaliador vê só os dados dele.</p>
      <div className="proximo-passo">
        <p className="bloco-rotulo">Cadastrar avaliador</p>
        <div className="grade-campos">
          {/* 186: um campo escondido "isca" segura o preenchimento automático do Chrome com o login do dono */}
          <input type="text" name="username" autoComplete="username" tabIndex={-1} aria-hidden="true" readOnly value=""
                 style={{ position: 'absolute', opacity: 0, height: 0, width: 0, pointerEvents: 'none' }} />
          <input type="password" name="password" autoComplete="current-password" tabIndex={-1} aria-hidden="true" readOnly value=""
                 style={{ position: 'absolute', opacity: 0, height: 0, width: 0, pointerEvents: 'none' }} />
          <Campo id="a-email" rotulo="E-mail de acesso" valor={f.email} mudar={(v) => setF({ ...f, email: v })} />
          <Campo id="a-senha" rotulo="Senha" tipo="password" valor={f.senha} mudar={(v) => setF({ ...f, senha: v })} />
          <Campo id="a-nome" rotulo="Nome no laudo" valor={f.nome} mudar={(v) => setF({ ...f, nome: v })} />
          <Campo id="a-creci" rotulo="CRECI" valor={f.creci} mudar={(v) => setF({ ...f, creci: v })} />
          <Campo id="a-cnai" rotulo="CNAI" valor={f.cnai} mudar={(v) => setF({ ...f, cnai: v })} />
          <Campo id="a-cidade" rotulo="Cidade" valor={f.cidade} mudar={(v) => setF({ ...f, cidade: v })} />
        </div>
        <p className="bloco-rotulo">Modalidades</p>
        <div className="botoes">{MODS.map(([k, r]) => <button key={k} type="button" className={mods.includes(k) ? 'btn-verde' : 'btn-sec-grande'} onClick={() => setMods(alterna(mods, k))}>{r}</button>)}</div>
        <p className="bloco-rotulo">Tipos de imóvel</p>
        <div className="botoes">{TIPOS.map((k) => <button key={k} type="button" className={tipos.includes(k) ? 'btn-verde' : 'btn-sec-grande'} onClick={() => setTipos(alterna(tipos, k))}>{k}</button>)}</div>
        <p className="texto">Compartilhar o raciocínio com a base comum, sem dados de clientes?</p>
        <div className="botoes">
          <button type="button" className={compart === true ? 'btn-verde' : 'btn-sec-grande'} onClick={() => setCompart(true)}>Sim</button>
          <button type="button" className={compart === false ? 'btn-verde' : 'btn-sec-grande'} onClick={() => setCompart(false)}>Não</button>
        </div>
        <button type="button" className="btn-verde" onClick={() => void cadastrar()}>Cadastrar avaliador</button>
      </div>
      {msg && <p className="aviso-simples" role="status">{msg}</p>}
      {lista.length > 0 && <ul className="lista-simples">{lista.map((a) => <li key={a.id}><span>{a.nome}</span><strong>{a.id}</strong></li>)}</ul>}
    </section>
  )
}

interface Ficha { id: string; titulo: string; decisao: string; ativa: boolean }

export function MinhasRegras() {
  const [lista, setLista] = useState<Ficha[]>([])
  const [hist, setHist] = useState<{ data: string; regra: string; acao: string; detalhe: string }[]>([])
  const [nova, setNova] = useState({ titulo: '', decisao: '' })
  const [aviso, setAviso] = useState('')
  const [confirmar, setConfirmar] = useState(false)
  const carregar = useCallback(() => {
    get<{ fichas: Ficha[] }>('/fichas/minhas').then((r) => setLista(r.fichas)).catch(() => undefined)
    get<{ historico: typeof hist }>('/fichas/minhas/historico').then((r) => setHist(r.historico)).catch(() => undefined)
  }, [])
  useEffect(carregar, [carregar])
  async function salvar() {
    const r = await post<{ precisa_confirmar?: boolean; aviso?: string }>('/fichas/minhas', { ...nova, confirmo: confirmar })
    if (r.precisa_confirmar) { setAviso(r.aviso ?? ''); setConfirmar(true); return }
    setAviso(r.aviso ? `Guardada. ${r.aviso}` : 'Regra guardada.'); setConfirmar(false); setNova({ titulo: '', decisao: '' }); carregar()
  }
  return (
    <section className="tela-simples">
      <h1 className="titulo-tela">Minhas regras</h1>
      <p className="linha-tela">Mude qualquer regra só para você.</p>
      <div className="proximo-passo">
        <p className="bloco-rotulo">Nova regra</p>
        <input className="campo-grande" placeholder="Ex.: Limite de dispersão" value={nova.titulo} onChange={(e) => setNova({ ...nova, titulo: e.target.value })} />
        <input className="campo-grande" placeholder="Ex.: aceito coeficiente de variação até 20%" value={nova.decisao} onChange={(e) => setNova({ ...nova, decisao: e.target.value })} />
        {aviso && <p className={confirmar ? 'aviso-impede' : 'aviso-simples'}>{aviso}</p>}
        <button type="button" className="btn-verde" disabled={!nova.titulo || !nova.decisao} onClick={() => void salvar()}>
          {confirmar ? 'Guardar mesmo assim' : 'Guardar regra'}
        </button>
      </div>
      <ul className="lista-simples">{lista.map((f) => <li key={f.id}><span>{f.titulo}</span><span>{f.decisao}</span></li>)}</ul>
      <details className="detalhes">
        <summary>Ver histórico</summary>
        {hist.length === 0 && <p className="texto detalhes-corpo">Nenhuma mudança ainda.</p>}{/* 185: abria vazio */}
        <ul className="lista-simples detalhes-corpo">{hist.map((h, i) => <li key={i}><span>{h.data} · {h.regra}</span><span>{h.detalhe}</span></li>)}</ul>
      </details>
    </section>
  )
}
