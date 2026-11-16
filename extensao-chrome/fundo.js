/* Enviar ao JdB — parte de fundo (1.2.0, ORDENS 076 e 077-D).
 * - 077-D: liga-se SOZINHA à sessão do JdB aberta neste Chrome (ligar.js), sem pedir senha.
 * - Registra o BOTÃO FLUTUANTE (botao.js) nos portais de imóveis, depois que o avaliador permite uma vez
 *   ("Permitir o JdB nos portais de imóveis", no popup).
 * - Atende o botão: lista os trabalhos, captura a foto e a página e envia ao JdB (D-082).
 * - Avisa o JdB da versão, se está fixada na barra e se os portais estão permitidos (076-3).
 * Não abre nem lê página sozinho: só age quando o avaliador toca no botão. */
const PADRAO = 'https://joaodebarro.brixly.com.br'
// 079-A: recebe anúncio todo trabalho que não está aprovado, assinado nem cancelado (o servidor decide:
// /extensao/trabalhos). 'PARCIAL — PENDÊNCIAS' recebe: é justamente quando faltam as fotos.
const CANCELADOS = ['CANCELADO', 'CANCELANDO']
const PORTAIS = [
  'https://*.zapimoveis.com.br/*', 'https://*.vivareal.com.br/*', 'https://*.olx.com.br/*',
  'https://*.imovelweb.com.br/*', 'https://*.imovelwebcdn.com/*', 'https://*.62imoveis.com.br/*',
  'https://*.deztop.com.br/*', 'https://*.deztop.com/*', 'https://*.chavesnamao.com.br/*', 'https://*.mitula.com.br/*',
]
const ANUNCIO = [
  /zapimoveis\.com\.br\/imovel\//, /vivareal\.com\.br\/imovel\//,
  /olx\.com\.br\/.*\/imoveis\/.+-\d+/, /imovelweb\.com\.br\/propriedades\//,
]

// 077-D: as páginas do próprio JdB (o app local e o site publicado). A sessão só é aceita delas e só vai
// para o servidor delas (a origem da página que entregou).
const JDB_ABAS = ['http://localhost/*', 'http://127.0.0.1/*', 'https://joaodebarro.brixly.com.br/*']
function origemJdB(url) {
  try {
    const u = new URL(url)
    if (u.protocol === 'http:' && (u.hostname === 'localhost' || u.hostname === '127.0.0.1')) return u.origin
    if (u.origin === 'https://joaodebarro.brixly.com.br') return u.origin
  } catch (e) { /* endereço inválido */ }
  return ''
}

/** Procura as abas do JdB já abertas e lê a sessão delas (ao instalar, ao abrir o Chrome, ao abrir o popup). */
async function procurarAba() {
  let abas = []
  try { abas = await chrome.tabs.query({ url: JDB_ABAS }) } catch (e) { abas = [] }
  let achou = 0
  for (const a of abas) {
    try {
      await chrome.scripting.executeScript({ target: { tabId: a.id }, files: ['ligar.js'] })
      achou++
    } catch (e) { /* aba sem acesso (ex.: carregando) */ }
  }
  return achou
}

async function guardarSessao(sender, token) {
  const origem = origemJdB(sender.url || (sender.tab && sender.tab.url) || '')
  if (sender.id !== chrome.runtime.id || !sender.tab || !origem) return false
  const atual = await chrome.storage.local.get(['servidor', 'jdb_token'])
  if (!token) {                       // saiu do JdB nesta aba: desliga só se era a mesma sessão
    if (atual.servidor === origem) await chrome.storage.local.remove('jdb_token')
    return true
  }
  if (atual.jdb_token === token && atual.servidor === origem) return true
  await chrome.storage.local.set({ servidor: origem, jdb_token: token, ligado_por: 'aba' })
  informarEstado()
  return true
}

async function config() {
  const c = await chrome.storage.local.get(['servidor', 'jdb_token'])
  return { ...c, servidor: (c.servidor || PADRAO).replace(/\/$/, '') }
}

const REINICIANDO = 'O JdB está reiniciando. Tente de novo em instantes.'

async function api(caminho, opcoes = {}) {
  const { servidor, jdb_token } = await config()
  if (!jdb_token) throw new Error('ENTRAR')
  // 081-2: servidor reiniciando (erro 5xx ou sem resposta) -> espera e tenta de novo sozinha, 3 vezes
  let r = null
  for (const pausa of [0, 2500, 5000, 8000]) {
    if (pausa) await espera(pausa)
    try {
      r = await fetch(servidor + caminho, {
        ...opcoes,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${jdb_token}`,
                   'X-JdB-Extensao': chrome.runtime.getManifest().version, ...(opcoes.headers || {}) },
      })
    } catch (e) { r = null }
    if (r && r.status < 500) break
  }
  if (!r || r.status >= 500) throw new Error(REINICIANDO)
  let corpo = null
  try { corpo = await r.json() } catch (e) { corpo = null }
  if (r.status === 401) { await chrome.storage.local.remove('jdb_token'); procurarAba(); throw new Error('ENTRAR') }
  if (!r.ok) throw new Error((corpo && corpo.detail) || `Erro ${r.status}`)
  return corpo
}

// ------------------------------------------------------------ portais: permissão e registro do botão
async function portaisPermitidos() {
  return chrome.permissions.contains({ origins: PORTAIS })
}

async function registrarBotao() {
  const ok = await portaisPermitidos()
  const ja = await chrome.scripting.getRegisteredContentScripts({ ids: ['jdb-botao'] })
  if (!ok) {
    if (ja.length) await chrome.scripting.unregisterContentScripts({ ids: ['jdb-botao'] })
    return false
  }
  if (!ja.length) {
    try {
      await chrome.scripting.registerContentScripts([{
        id: 'jdb-botao', matches: PORTAIS, js: ['extrator.js', 'botao.js'], runAt: 'document_idle', persistAcrossSessions: true,
      }])
    } catch (e) { if (!/Duplicate/.test(e.message)) throw e }   // dois avisos ao mesmo tempo: já registrado
  }
  return true
}

async function fixada() {
  try { return !!(await chrome.action.getUserSettings()).isOnToolbar } catch (e) { return null }
}

async function informarEstado() {
  try {
    await api('/api/avaliacao/extensao/estado', { method: 'POST', body: JSON.stringify({
      versao: chrome.runtime.getManifest().version, fixada: await fixada(), portais: await portaisPermitidos(),
      captura: await chrome.permissions.contains({ origins: ['<all_urls>'] }) }) })
  } catch (e) { /* sem login ainda: informa na próxima vez */ }
}

chrome.runtime.onInstalled.addListener(() => { registrarBotao(); procurarAba().then(informarEstado) })
chrome.runtime.onStartup.addListener(() => { registrarBotao(); procurarAba().then(informarEstado) })
chrome.permissions.onAdded.addListener(() => { registrarBotao(); informarEstado() })
chrome.permissions.onRemoved.addListener(() => { registrarBotao(); informarEstado() })

// lembrete no ícone (como antes): página de anúncio conhecida
chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (!tab.url) return
  const eh = ANUNCIO.some((r) => r.test(tab.url))
  chrome.action.setBadgeText({ tabId, text: eh ? '↑' : '' })
  if (eh) chrome.action.setBadgeBackgroundColor({ tabId, color: '#16283A' })
})

// ------------------------------------------------------------ captura (mesma lógica do popup, D-082)
const espera = (ms) => new Promise((ok) => setTimeout(ok, ms))
const dataUrl = (blob) => new Promise((ok) => { const f = new FileReader(); f.onload = () => ok(f.result); f.readAsDataURL(blob) })

async function recortar(imagem, ret) {
  if (!imagem || !ret) return ''
  try {
    const bmp = await createImageBitmap(await (await fetch(imagem)).blob())
    const k = ret.dpr || 1
    const sx = Math.round(ret.x * k), sy = Math.round(ret.y * k)
    const sw = Math.min(bmp.width - sx, Math.round(ret.w * k)), sh = Math.min(bmp.height - sy, Math.round(ret.h * k))
    if (sw < 100 || sh < 80) return ''
    const c = new OffscreenCanvas(sw, sh)
    c.getContext('2d').drawImage(bmp, sx, sy, sw, sh, 0, 0, sw, sh)
    return await dataUrl(await c.convertToBlob({ type: 'image/jpeg', quality: 0.85 }))
  } catch (e) { return '' }
}

async function baixarFoto(url, minLargura = 0) {   // a foto do próprio anúncio, pelo endereço dela
  if (!url) return ''
  try {
    const r = await fetch(url)
    if (!r.ok) return ''
    const bmp = await createImageBitmap(await r.blob())
    if (Math.max(bmp.width, bmp.height) < minLargura) return ''
    const c = new OffscreenCanvas(bmp.width, bmp.height)
    c.getContext('2d').drawImage(bmp, 0, 0)
    return await dataUrl(await c.convertToBlob({ type: 'image/jpeg', quality: 0.88 }))
  } catch (e) { return '' }
}

/** 081-2/4: a foto principal vem do ENDEREÇO da foto do anúncio (grande), nunca da tela — assim propaganda por
 * cima da página não entra. Só sem endereço nenhum é que se recorta a tela. */
async function fotoDoAnuncio(dados, imagem) {
  const lista = [...new Set([dados.foto_url, ...(dados.fotos_url || [])].filter(Boolean))].slice(0, 4)
  for (const u of lista) { const f = await baixarFoto(u, 600); if (f) return f }
  for (const u of lista) { const f = await baixarFoto(u); if (f) return f }      // só a pequena existe
  return await recortar(imagem, dados.foto_rect)
}

async function esconderBotao(tab, esconder) {   // a prova da página não leva o botão do JdB
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, args: [esconder],
      func: (e) => { const b = document.getElementById('jdb-enviar'); if (b) b.style.visibility = e ? 'hidden' : '' } })
  } catch (e) { /* aba sem acesso */ }
}

async function paginaInteira(tab) {
  const [{ result: m }] = await chrome.scripting.executeScript({ target: { tabId: tab.id },
    func: () => ({ h: Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0),
                   vh: window.innerHeight, y0: window.scrollY, dpr: window.devicePixelRatio || 1 }) })
  const telas = Math.min(6, Math.ceil(m.h / m.vh))     // 100-7
  const partes = []
  try {
    for (let i = 0; i < telas; i++) {
      const y = Math.min(i * m.vh, Math.max(0, m.h - m.vh))
      await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: (yy) => window.scrollTo(0, yy), args: [y] })
      await espera(520)
      partes.push({ y, url: await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'jpeg', quality: 70 }) })
    }
  } finally {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: (yy) => window.scrollTo(0, yy), args: [m.y0] })
  }
  const bmps = await Promise.all(partes.map(async (p) => ({ y: p.y, b: await createImageBitmap(await (await fetch(p.url)).blob()) })))
  const k = m.dpr
  const alt = Math.min(m.h, telas * m.vh)
  const c = new OffscreenCanvas(bmps[0].b.width, Math.round(alt * k))
  const ctx = c.getContext('2d')
  for (const p of bmps) ctx.drawImage(p.b, 0, Math.round(p.y * k))
  return await dataUrl(await c.convertToBlob({ type: 'image/jpeg', quality: 0.7 }))
}

// ------------------------------------------------------------ pedidos do botão da página
async function trabalhos() {
  let jobs
  try { jobs = await api('/api/avaliacao/extensao/trabalhos') } catch (e) {
    if (e.message === 'ENTRAR') throw e
    jobs = (await api('/api/avaliacao/jobs')).filter((j) => !CANCELADOS.includes(j.status))   // servidor antigo
  }
  return jobs
    .sort((a, b) => String(b.atualizado || b.criado || '').localeCompare(String(a.atualizado || a.criado || '')))
    .map((j) => ({ id: j.id, numero: j.numero, cliente: j.cliente || '', bairro: j.bairro || '' }))
}

// ------------------------------------------------------------ 079-1: "Abrir os anúncios" (pedido da tela do JdB)
// Abre, UM DE CADA VEZ e à frente, cada anúncio do laudo que ainda não tem foto e data de acesso, lê a página,
// captura e envia ao trabalho (o mesmo envio do botão). Página com verificação de pessoa: NÃO contorna — deixa a
// aba aberta para o avaliador resolver e segue para o próximo.
let abrindo = null
const VERIFICACAO = /just a moment|have been blocked|bloquead|verify you are human|verifique (que )?voc[eê]|n[aã]o sou um rob[oô]|captcha|acesso negado|access denied/i

function esperarCarregar(tabId, ms = 45000) {
  return new Promise((ok) => {
    const fim = setTimeout(() => { chrome.tabs.onUpdated.removeListener(ouvir); ok(false) }, ms)
    function ouvir(id, info) {
      if (id === tabId && info.status === 'complete') { clearTimeout(fim); chrome.tabs.onUpdated.removeListener(ouvir); ok(true) }
    }
    chrome.tabs.onUpdated.addListener(ouvir)
  })
}

async function tirarVinheta(tabId) {      // 103-3b: a vinheta de tela cheia (#google_vignette) e iframes de propaganda
  try {
    await chrome.scripting.executeScript({ target: { tabId }, func: () => {
      for (const el of document.querySelectorAll('ins.adsbygoogle, iframe[id^="google_ads"], iframe[id^="aswift"], div[id^="google_vignette"]')) el.remove()
      if (location.hash === '#google_vignette') history.replaceState(null, '', location.pathname + location.search)
      document.documentElement.style.overflow = ''
      document.body && (document.body.style.overflow = '')
    } })
  } catch (e) { /* página sem acesso */ }
}

async function abrirAnuncios(trabalho, janela) {
  if (abrindo) return { ok: false, erro: 'Já estou abrindo os anúncios de um trabalho. Espere terminar.' }
  if (!(await portaisPermitidos())) return { ok: false, erro: 'PORTAIS' }
  const lista = await api(`/api/avaliacao/jobs/${encodeURIComponent(trabalho)}/extensao/anuncios`)
  const faltam = lista.faltam || []
  abrindo = { trabalho, total: faltam.length, feitos: 0, verificacao: [], falhas: [] }
  // 110-1: o Chrome adormece a parte de fundo após ~30 s sem chamada da extensão (a espera da página e do envio
  // contavam como "parado") e a fila morria no meio. Uma chamada leve a cada 20 s a mantém acordada; e a fila fica
  // anotada na memória da sessão: se a parte de fundo reiniciar mesmo assim, ela retoma sozinha.
  const acordada = setInterval(() => { try { chrome.runtime.getPlatformInfo(() => void chrome.runtime.lastError) } catch (e) { /* ok */ } }, 20000)
  try { await chrome.storage.session.set({ fila_abrir: { trabalho, janela, desde: Date.now() } }) } catch (e) { /* ok */ }
  ;(async () => {
    try {
      for (const a of faltam) {
        let tab = null
        try {
          tab = await chrome.tabs.create({ url: a.link, active: true, windowId: janela })
          await esperarCarregar(tab.id, 25000)
          await espera(3500)                                // fotos e preço que carregam depois
          await tirarVinheta(tab.id)
          await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['extrator.js'] })
          const [{ result: d }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => window.__jdbExtrair() })
          const tela = `${(d && d.titulo) || ''} ${((d && d.texto) || '').slice(0, 600)}`
          if (!d || !d.preco) {                              // verificação, bloqueio ou página que não carregou:
            ;(VERIFICACAO.test(tela) ? abrindo.verificacao : abrindo.falhas).push(a.n)
            continue                                         // nada é enviado; a aba fica aberta para o avaliador
          }
          await Promise.race([enviarAnuncio(tab, trabalho, { ...d, link: a.link }),    // o mesmo nº do laudo
            espera(40000).then(() => { throw new Error('o anúncio não respondeu em 40 s') })])
          abrindo.feitos++
          await chrome.tabs.remove(tab.id)
        } catch (e) {
          abrindo.falhas.push(a.n)                           // a aba fica aberta: o avaliador usa o botão
        }
      }
    } finally {
      abrindo = null
      clearInterval(acordada)
      try { await chrome.storage.session.remove('fila_abrir') } catch (e) { /* ok */ }
    }
  })()
  return { ok: true, total: faltam.length, ja_recebidos: lista.recebidos }
}

// 110-1: a parte de fundo reiniciou com uma fila pela metade (de menos de 30 min): retoma do que falta
;(async () => {
  try {
    const { fila_abrir: f } = await chrome.storage.session.get('fila_abrir')
    if (f && f.trabalho && Date.now() - (f.desde || 0) < 30 * 60 * 1000 && !abrindo) {
      let janela = f.janela
      try { await chrome.windows.get(janela) } catch (e) { janela = undefined }
      await abrirAnuncios(f.trabalho, janela)
    }
  } catch (e) { /* sem sessão: nada a retomar */ }
})()

async function enviarAnuncio(tab, trabalho, dados) {
  const acessado_em = new Date().toISOString()
  let imagem = '', pagina_inteira = ''
  // a prova do acesso (D-082): a página com data, hora e link — precisa da permissão de captura (081-6)
  await esconderBotao(tab, true)
  try { imagem = await chrome.tabs.captureVisibleTab(tab.windowId, { format: 'jpeg', quality: 80 }) } catch (e) { imagem = '' }
  if (imagem) { try { pagina_inteira = await paginaInteira(tab) } catch (e) { pagina_inteira = '' } }
  await esconderBotao(tab, false)
  const { foto_rect, foto_url, ...lidos } = dados || {}
  const foto_principal = await fotoDoAnuncio({ ...(dados || {}), foto_rect, foto_url }, imagem)
  const r = await api(`/api/avaliacao/jobs/${encodeURIComponent(trabalho)}/candidatos/enviado`, {
    method: 'POST', body: JSON.stringify({ ...lidos, imagem, foto_principal, pagina_inteira, acessado_em }) })
  informarEstado()
  return r
}

chrome.runtime.onMessage.addListener((msg, sender, responder) => {
  (async () => {
    try {
      if (msg.tipo === 'sessao') return responder({ ok: await guardarSessao(sender, msg.token) })
      if (msg.tipo === 'procurar') {
        const achou = await procurarAba()
        await espera(achou ? 800 : 0)
        const c = await config()
        return responder({ ok: true, achou, ligado: !!c.jdb_token, servidor: c.servidor })
      }
      if (msg.tipo === 'abrir_anuncios') {                 // só a tela do próprio JdB pede
        if (sender.id !== chrome.runtime.id || !sender.tab || !origemJdB(sender.url || sender.tab.url || ''))
          return responder({ ok: false, erro: 'pedido recusado' })
        return responder(await abrirAnuncios(String(msg.trabalho || ''), sender.tab.windowId))
      }
      if (msg.tipo === 'trabalhos') return responder({ ok: true, trabalhos: await trabalhos() })
      if (msg.tipo === 'enviar') {
        const r = await enviarAnuncio(sender.tab, msg.trabalho, msg.dados)
        let contagem = null                                     // 079-A: "(2 de 6)"
        try { contagem = await api(`/api/avaliacao/jobs/${encodeURIComponent(msg.trabalho)}/extensao/anuncios`) } catch (e) { contagem = null }
        return responder({ ok: true, r, contagem: contagem && { recebidos: contagem.recebidos, total: contagem.total } })
      }
      if (msg.tipo === 'foto') return responder({ ok: true, foto: await fotoDoAnuncio(msg.dados || {}, msg.imagem || '') })
      if (msg.tipo === 'de_quem') {                             // 079-A: o link já é referencial de um trabalho?
        let dono = {}
        try { dono = await api(`/api/avaliacao/extensao/de-quem?link=${encodeURIComponent(msg.link || '')}`) } catch (e) {
          if (e.message === 'ENTRAR') throw e
          dono = {}
        }
        return responder({ ok: true, dono: dono && dono.trabalho ? dono : null, varios: (dono && dono.varios) || null })
      }
      if (msg.tipo === 'pagina') {
        const r = await api(`/api/avaliacao/jobs/${encodeURIComponent(msg.trabalho)}/candidatos/pagina`,
          { method: 'POST', body: JSON.stringify(msg.pagina) })
        informarEstado()
        return responder({ ok: true, r })
      }
      if (msg.tipo === 'registrar') return responder({ ok: await registrarBotao() })
      if (msg.tipo === 'estado') { await informarEstado(); return responder({ ok: true }) }
      responder({ ok: false, erro: 'pedido desconhecido' })
    } catch (e) {
      responder({ ok: false, erro: e.message })
    }
  })()
  return true      // resposta assíncrona
})
