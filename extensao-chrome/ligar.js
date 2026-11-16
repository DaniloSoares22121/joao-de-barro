/* Enviar ao JdB — liga a extensão à sessão do JdB já aberta neste Chrome (1.2.0, ORDEM 077-D).
 * Roda só nas páginas do próprio JdB (localhost e o site publicado). Lê a sessão que o JdB guarda
 * neste navegador e entrega só à parte de fundo da extensão (nunca em endereço, nunca em log).
 * Sem senha: quem já entrou no JdB neste Chrome não precisa entrar de novo na extensão. */
(() => {
  if (window.__jdbLigar) { window.__jdbLigar(); return }
  const ehJdB = () => !!document.querySelector('link[rel="manifest"][href*="manifest-jdb"]') ||
    /JdB/.test(document.title || '')
  let ultimo = null
  function ligar() {
    if (!ehJdB()) return
    let t = ''
    try { t = localStorage.getItem('jdb_token') || '' } catch (e) { t = '' }
    if (t === ultimo) return
    ultimo = t
    try {
      chrome.runtime.sendMessage({ tipo: 'sessao', token: t }, () => { void chrome.runtime.lastError })
    } catch (e) { clearInterval(relogio) }   // extensão recarregada: esta cópia para; a nova assume
  }
  window.__jdbLigar = () => { ultimo = null; ligar() }
  // a tela do JdB sabe que a extensão está aqui (e a versão), sem perguntar a ninguém
  document.documentElement.dataset.jdbExtensao = chrome.runtime.getManifest().version
  // 079-1: a tela pede "Abrir os anúncios" do trabalho -> a extensão abre e envia um a um
  window.addEventListener('message', (ev) => {
    const m = ev.data
    if (ev.source !== window || ev.origin !== location.origin || !m || m.jdb !== 'abrir-anuncios' || !ehJdB()) return
    ligar()
    try {
      chrome.runtime.sendMessage({ tipo: 'abrir_anuncios', trabalho: String(m.trabalho || '') }, (r) => {
        void chrome.runtime.lastError
        window.postMessage({ jdb: 'abrir-anuncios-resposta', trabalho: m.trabalho, ...(r || { ok: false, erro: 'sem resposta' }) },
          location.origin)
      })
    } catch (e) {
      window.postMessage({ jdb: 'abrir-anuncios-resposta', trabalho: m.trabalho, ok: false, erro: 'RECARREGAR' }, location.origin)
    }
  })
  const relogio = setInterval(ligar, 3000)    // entrou ou saiu do JdB nesta aba
  window.addEventListener('storage', ligar)   // entrou ou saiu em outra aba
  document.addEventListener('visibilitychange', ligar)
  ligar()
})()
