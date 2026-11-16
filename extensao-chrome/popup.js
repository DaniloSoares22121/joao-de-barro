/* Janelinha do botão "Enviar ao JdB". Só age quando o Alan clica: lê a aba aberta
 * (extrator.js), captura a parte visível dela e manda ao sistema como referencial escolhido. */
const $ = (id) => document.getElementById(id)
const PADRAO = 'https://joaodebarro.brixly.com.br'
const CONHECIDOS = [PADRAO, 'http://localhost:8866', 'http://127.0.0.1:8866']
let dados = null

function msg(texto, ok) {
  const m = $('msg')
  m.hidden = false
  m.textContent = texto
  m.className = 'msg ' + (ok ? 'ok' : 'erro')
}

function numBR(s) {
  const t = String(s || '').trim().replace(/\s|R\$/g, '')
  if (!t) return null
  const v = /,\d{1,2}$/.test(t) ? Number(t.replace(/\./g, '').replace(',', '.'))
    : /^\d{1,3}(\.\d{3})+$/.test(t) ? Number(t.replace(/\./g, '')) : Number(t)
  return Number.isFinite(v) ? v : null
}
const br = (v) => (v == null ? '' : v.toLocaleString('pt-BR', { maximumFractionDigits: 2 }))

async function config() {
  const c = await new Promise((ok) => chrome.storage.local.get(['servidor', 'jdb_token'], ok))
  return { ...c, servidor: c.servidor || PADRAO }
}

async function api(caminho, opcoes = {}) {
  const { servidor, jdb_token } = await config()
  const r = await fetch(servidor.replace(/\/$/, '') + caminho, {
    ...opcoes,
    // 070-C: a versão vai junto, para a tela do JdB saber se a extensão está atualizada
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${jdb_token}`,
               'X-JdB-Extensao': chrome.runtime.getManifest().version, ...(opcoes.headers || {}) },
  })
  let corpo = null
  try { corpo = await r.json() } catch (e) { corpo = null }
  if (r.status === 401) {
    await chrome.storage.local.remove('jdb_token')
    throw new Error('A sessão do JdB acabou: abra o JdB neste Chrome.')
  }
  if (!r.ok) throw new Error((corpo && corpo.detail) || `Erro ${r.status}`)
  return corpo
}

function atualizarUnit() {
  const p = numBR($('preco').value), a = numBR($('area').value)
  $('unit').value = p && a ? br(Math.round((p / a) * 100) / 100) : ''
}

async function lerPagina() {
  const [aba] = await chrome.tabs.query({ active: true, currentWindow: true })
  await chrome.scripting.executeScript({ target: { tabId: aba.id }, files: ['extrator.js'] })
  const [res] = await chrome.scripting.executeScript({ target: { tabId: aba.id }, func: () => window.__jdbExtrair() })
  return { aba, d: res.result }
}

async function telaEnviar() {
  $('entrar').hidden = true
  $('enviar').hidden = false
  config().then(({ servidor }) => {
    let onde = ''
    try { onde = new URL(servidor).host } catch (e) { onde = '' }
    $('conectado').textContent = 'Conectado ao JdB ✓' + (onde ? ` (${onde})` : '')
  })
  try {
    const { d } = await lerPagina()
    dados = d
    $('titulo').textContent = d.titulo || d.link
    $('preco').value = br(d.preco)
    $('area').value = br(d.area_m2)
    $('quartos').value = d.quartos ?? ''
    atualizarUnit()
  } catch (e) {
    // 081-3: chrome://, página em branco, aba sem anúncio -> orientação, sem vermelho e sem inglês
    msg('Abra um anúncio de imóvel para enviar.', true)
    $('msg').className = 'msg nota'
  }
  try {
    // 079-A: a mesma lista do botão da página (aprovado, assinado e cancelado não recebem)
    const abertos = await new Promise((ok, erro) => chrome.runtime.sendMessage({ tipo: 'trabalhos' },
      (r) => (r && r.ok ? ok(r.trabalhos) : erro(new Error((r && r.erro) === 'ENTRAR' ? 'A sessão do JdB acabou: abra o JdB neste Chrome.' : ((r && r.erro) || 'sem resposta'))))))
    $('trabalho').innerHTML = abertos.map((j) =>
      `<option value="${j.id}">Nº ${j.numero} – ${(j.cliente || '').replace(/</g, '')} – ${(j.bairro || '').replace(/</g, '')}</option>`).join('')
    $('btn-enviar').disabled = !abertos.length || !dados
    $('btn-pagina').disabled = !abertos.length
    if (!abertos.length) msg('Nenhum trabalho recebendo anúncios agora (laudo aprovado, assinado ou cancelado não recebe).', false)
  } catch (e) {
    msg(e.message, false)
    if (/sessão do JdB acabou/.test(e.message)) ligar()
  }
}

function telaEntrar() {
  $('enviar').hidden = true
  $('entrar').hidden = false
  config().then(({ servidor }) => { $('servidor').value = servidor || PADRAO })
}

$('preco').addEventListener('input', atualizarUnit)
$('area').addEventListener('input', atualizarUnit)

$('btn-entrar').addEventListener('click', async () => {
  const servidor = $('servidor').value.trim().replace(/\/$/, '')
  try {
    const origem = new URL(servidor).origin + '/*'
    // endereço fora dos conhecidos (produção e PC de teste): o Chrome pede a permissão
    if (!CONHECIDOS.includes(new URL(servidor).origin)) {
      const dada = await chrome.permissions.request({ origins: [origem] })
      if (!dada) throw new Error('Permissão negada para o endereço do sistema.')
    }
    const r = await fetch(servidor + '/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: $('email').value.trim(), password: $('senha').value }),
    })
    const corpo = await r.json().catch(() => ({}))
    if (!r.ok || !corpo.token) throw new Error(corpo.detail || 'E-mail ou senha inválidos.')
    await chrome.storage.local.set({ servidor, jdb_token: corpo.token })
    $('senha').value = ''
    telaEnviar()
    mostrarPortais()
  } catch (e) {
    msg(e.message, false)
  }
})

// ORDEM 029-5: recorta a foto principal (retângulo informado pelo extrator) da captura da tela
async function recortar(imagem, ret) {
  if (!ret) return ''
  try {
    const bmp = await createImageBitmap(await (await fetch(imagem)).blob())
    const k = ret.dpr || 1
    const sx = Math.round(ret.x * k), sy = Math.round(ret.y * k)
    const sw = Math.min(bmp.width - sx, Math.round(ret.w * k))
    const sh = Math.min(bmp.height - sy, Math.round(ret.h * k))
    if (sw < 100 || sh < 80) return ''
    const c = new OffscreenCanvas(sw, sh)
    c.getContext('2d').drawImage(bmp, sx, sy, sw, sh, 0, 0, sw, sh)
    const b = await c.convertToBlob({ type: 'image/jpeg', quality: 0.85 })
    return await new Promise((ok) => { const f = new FileReader(); f.onload = () => ok(f.result); f.readAsDataURL(b) })
  } catch (e) {
    return ''     // sem recorte: o sistema usa a imagem da página inteira
  }
}

// ORDEM 039 / D-082 (versão 1.0.4): captura da PÁGINA INTEIRA do anúncio, rolando a aba e
// colando as partes (sem permissão extra). O servidor põe a faixa "Acessado em … — link —
// portal" no rodapé e guarda como prova do anúncio. No máx. 12 telas; volta a rolagem ao fim.
const espera = (ms) => new Promise((ok) => setTimeout(ok, ms))
async function paginaInteira(aba) {
  const [{ result: m }] = await chrome.scripting.executeScript({ target: { tabId: aba.id },
    func: () => ({ h: Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0),
                   vh: window.innerHeight, y0: window.scrollY, dpr: window.devicePixelRatio || 1 }) })
  const telas = Math.min(12, Math.ceil(m.h / m.vh))
  const partes = []
  try {
    for (let i = 0; i < telas; i++) {
      const y = Math.min(i * m.vh, Math.max(0, m.h - m.vh))
      await chrome.scripting.executeScript({ target: { tabId: aba.id }, func: (yy) => window.scrollTo(0, yy), args: [y] })
      await espera(650)    // o Chrome aceita no máx. 2 capturas por segundo
      partes.push({ y, url: await chrome.tabs.captureVisibleTab(undefined, { format: 'jpeg', quality: 70 }) })
    }
  } finally {
    await chrome.scripting.executeScript({ target: { tabId: aba.id }, func: (yy) => window.scrollTo(0, yy), args: [m.y0] })
  }
  const bmps = await Promise.all(partes.map(async (p) => ({ y: p.y, b: await createImageBitmap(await (await fetch(p.url)).blob()) })))
  const k = bmps[0].b.width / (bmps[0].b.width / m.dpr)
  const alt = Math.min(m.h, telas * m.vh)
  const c = new OffscreenCanvas(bmps[0].b.width, Math.round(alt * k))
  const ctx = c.getContext('2d')
  for (const p of bmps) ctx.drawImage(p.b, 0, Math.round(p.y * k))
  const blob = await c.convertToBlob({ type: 'image/jpeg', quality: 0.7 })
  return await new Promise((ok) => { const f = new FileReader(); f.onload = () => ok(f.result); f.readAsDataURL(blob) })
}

$('btn-enviar').addEventListener('click', async () => {
  $('btn-enviar').disabled = true
  try {
    const acessado_em = new Date().toISOString()
    const imagem = await chrome.tabs.captureVisibleTab(undefined, { format: 'jpeg', quality: 80 })
    // 081-2/4: a foto vem do endereço da foto do anúncio (grande, sem propaganda por cima); a tela só se não houver
    const r0 = await new Promise((ok) => chrome.runtime.sendMessage({ tipo: 'foto', dados: dados || {}, imagem }, (x) => { void chrome.runtime.lastError; ok(x) }))
    const foto_principal = (r0 && r0.foto) || await recortar(imagem, dados && dados.foto_rect)
    let pagina_inteira = ''
    try {
      const [aba] = await chrome.tabs.query({ active: true, currentWindow: true })
      pagina_inteira = await paginaInteira(aba)
    } catch (e) {
      pagina_inteira = ''     // sem a página inteira: a prova sai da parte visível
    }
    const { foto_rect, ...lidos } = dados || {}
    const corpo = {
      ...lidos,
      preco: numBR($('preco').value), area_m2: numBR($('area').value),
      quartos: $('quartos').value ? Number($('quartos').value) : null, imagem, foto_principal,
      pagina_inteira, acessado_em,
    }
    const r = await api(`/api/avaliacao/jobs/${encodeURIComponent($('trabalho').value)}/candidatos/enviado`,
      { method: 'POST', body: JSON.stringify(corpo) })
    const un = r.unitario != null ? `, R$ ${br(r.unitario)}/m²` : ''
    msg(r.atualizado
      ? `Referencial nº ${r.n} completado${r.foto ? ' com a foto' : ''} (${br(r.area_m2)} m²${un}).`
      : `Enviado: nº ${r.n} na lista (${br(r.area_m2)} m²${un}).`, true)
  } catch (e) {
    msg(e.message, false)
    $('btn-enviar').disabled = false
  }
})

// ORDEM 019: página de RESULTADOS de busca aberta no Chrome do Alan -> todos os cartões vão para
// a lista de candidatos (o servidor filtra região, repetidos e semelhança). Sem robô.
$('btn-pagina').addEventListener('click', async () => {
  $('btn-pagina').disabled = true
  try {
    const [aba] = await chrome.tabs.query({ active: true, currentWindow: true })
    await chrome.scripting.executeScript({ target: { tabId: aba.id }, files: ['extrator.js'] })
    const [res] = await chrome.scripting.executeScript({ target: { tabId: aba.id }, func: () => window.__jdbCartoes() })
    const pag = res.result
    if (!pag || !pag.cartoes.length) throw new Error('Nenhum anúncio com preço nesta página. Abra a página de resultados da busca.')
    const r = await api(`/api/avaliacao/jobs/${encodeURIComponent($('trabalho').value)}/candidatos/pagina`,
      { method: 'POST', body: JSON.stringify(pag) })
    const pl = (n, um, varios) => `${n} ${n === 1 ? um : varios}`
    msg(r.novos.length
      ? `${pl(r.novos.length, 'anúncio novo', 'anúncios novos')} na lista (nº ${r.novos[0]}–${r.novos[r.novos.length - 1]}). ${pl(r.ignorados, 'ignorado', 'ignorados')}.`
      : 'Nenhum anúncio novo: os desta página já estão na lista ou são de fora da região.', !!r.novos.length)
  } catch (e) {
    msg(e.message, false)
  } finally {
    $('btn-pagina').disabled = false
  }
})

// 077-D: o JdB do Alan abre já logado neste Chrome; a extensão lê essa sessão (ligar.js), sem senha
const JDB_LOCAL = 'http://localhost:5177/assets-jdb/joaodebarro.html'
function ligar() {
  chrome.runtime.sendMessage({ tipo: 'procurar' }, (r) => {
    void chrome.runtime.lastError
    if (r && r.ligado) { telaEnviar(); mostrarPortais() } else telaEntrar()
  })
}
$('btn-abrir').addEventListener('click', async () => {
  const { servidor } = await config()
  const site = /^https:\/\/joaodebarro\.brixly\.com\.br/.test(servidor || '') ? servidor : JDB_LOCAL
  await chrome.tabs.create({ url: site })
  window.close()        // ao abrir o JdB, a extensão se liga sozinha; o popup de novo mostra "Conectado"
})

// 1.1.0 (ORDEM 076): botão na página do anúncio — permissão pedida uma vez, aqui (precisa do toque do avaliador)
const PORTAIS = [
  'https://*.zapimoveis.com.br/*', 'https://*.vivareal.com.br/*', 'https://*.olx.com.br/*',
  'https://*.imovelweb.com.br/*', 'https://*.imovelwebcdn.com/*', 'https://*.62imoveis.com.br/*',
  'https://*.deztop.com.br/*', 'https://*.deztop.com/*', 'https://*.chavesnamao.com.br/*', 'https://*.mitula.com.br/*',
]
async function mostrarPortais() {
  // 081-6: além do botão nos portais, a captura da página (a prova do acesso com data, hora e link)
  const ok = await chrome.permissions.contains({ origins: ['<all_urls>'] })
  $('portais').hidden = ok
  try { $('fixar').hidden = !!(await chrome.action.getUserSettings()).isOnToolbar } catch (e) { $('fixar').hidden = true }
  chrome.runtime.sendMessage({ tipo: 'estado' })
}
$('btn-portais').addEventListener('click', async () => {
  const dada = await chrome.permissions.request({ origins: ['<all_urls>'] })   // portais + captura da prova
  if (!dada) return msg('Sem a permissão, o botão não aparece na página; o ícone da barra continua funcionando.', false)
  chrome.runtime.sendMessage({ tipo: 'registrar' }, () => {
    msg('Pronto: abra (ou recarregue) a página do anúncio e use o botão “Enviar ao JdB” no canto.', true)
    mostrarPortais()
  })
})

config().then(({ jdb_token }) => { if (jdb_token) { telaEnviar(); mostrarPortais() } else ligar() })
