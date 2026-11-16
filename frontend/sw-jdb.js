/* ORDEM 041 / D-092: service worker do JdB Laudo (app instalável). Recebe o aviso do próprio
 * app (Web Push) e mostra a notificação, mesmo com a aba fechada. Sem agenda externa. */
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))

self.addEventListener('push', (e) => {
  let d = { titulo: 'JdB Laudo', corpo: '' }
  try { d = { ...d, ...e.data.json() } } catch (err) { if (e.data) d.corpo = e.data.text() }
  e.waitUntil((async () => {
    await self.registration.showNotification(d.titulo, {
      body: d.corpo, icon: 'jdb-marca/jdb-laudo-icone-app-192.png', badge: 'jdb-marca/jdb-laudo-favicon-32.png', tag: 'jdb-' + Date.now(), requireInteraction: true, data: { url: d.url || '' },
    })
    // registro para o teste no PC: a página aberta recebe "aviso-recebido"
    for (const c of await self.clients.matchAll({ includeUncontrolled: true })) c.postMessage({ tipo: 'aviso-recebido', ...d })
  })())
})

self.addEventListener('notificationclick', (e) => {
  e.notification.close()
  e.waitUntil((async () => {
    const abertas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    if (abertas.length) return abertas[0].focus()
    return self.clients.openWindow(self.registration.scope + 'joaodebarro.html')
  })())
})

/* ORDEM 049 / D-102: "Compartilhar → JdB Laudo" (Web Share Target, POST multipart). O service worker só
 * guarda os arquivos e o texto NESTE aparelho (Cache Storage) e abre a tela "Para qual trabalho?". Quem
 * envia para o servidor é a tela do app, com o login do avaliador: nada chega ao servidor sem login. */
const CACHE_COMPARTILHAR = 'jdb-compartilhar'
self.addEventListener('fetch', (e) => {
  const u = new URL(e.request.url)
  if (e.request.method !== 'POST' || !u.pathname.endsWith('/compartilhar')) return
  e.respondWith((async () => {
    const fd = await e.request.formData()
    const cache = await caches.open(CACHE_COMPARTILHAR)
    for (const k of await cache.keys()) await cache.delete(k)
    const arquivos = fd.getAll('arquivos').filter((f) => f && typeof f !== 'string')
    const lista = []
    for (const [i, f] of arquivos.entries()) {
      const chave = self.registration.scope + 'compartilhado/' + i
      await cache.put(new Request(chave), new Response(f, { headers: { 'Content-Type': f.type || 'application/octet-stream' } }))
      lista.push({ chave, nome: f.name || ('arquivo-' + (i + 1)), tipo: f.type || '', tamanho: f.size })
    }
    const texto = ['title', 'text', 'url'].map((k) => fd.get(k)).filter((v) => typeof v === 'string' && v.trim()).join('\n')
    await cache.put(new Request(self.registration.scope + 'compartilhado/indice.json'),
      new Response(JSON.stringify({ arquivos: lista, texto, quando: Date.now() }), { headers: { 'Content-Type': 'application/json' } }))
    return Response.redirect(self.registration.scope + 'joaodebarro.html#/compartilhar', 303)
  })())
})
