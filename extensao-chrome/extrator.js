/* Lê a página de anúncio QUE O ALAN ESTÁ VENDO (nada de abrir outras páginas, nada de robô).
 * Roda dentro da aba quando o Alan clica no botão. Devolve:
 * { link, titulo, preco, area_m2, lote_m2, quartos, suites, bairro, texto }.
 * O servidor ainda relê o texto com as mesmas regras da lista de candidatos. */
(function () {
  function num(s) {
    if (s == null) return null
    const t = String(s).trim().replace(/\s/g, '')
    if (!t) return null
    // 1.234.567,89 | 1234567.89 | 650.000
    let v
    if (/,\d{1,2}$/.test(t)) v = Number(t.replace(/\./g, '').replace(',', '.'))
    else if (/^\d{1,3}(\.\d{3})+$/.test(t)) v = Number(t.replace(/\./g, ''))
    else v = Number(t.replace(/,/g, ''))
    return Number.isFinite(v) ? v : null
  }

  function jsonLd() {
    const out = []
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const d = JSON.parse(s.textContent || 'null')
        const lista = Array.isArray(d) ? d : (d && d['@graph']) ? d['@graph'] : [d]
        for (const x of lista) if (x && typeof x === 'object') out.push(x)
      } catch (e) { /* JSON-LD inválido: ignora */ }
    }
    return out
  }

  function meta(nome) {
    const m = document.querySelector(`meta[property="${nome}"], meta[name="${nome}"]`)
    return m ? (m.getAttribute('content') || '').trim() : ''
  }

  function extrairAnuncio() {
    const url = new URL(location.href)
    const link = url.origin + url.pathname
    const ld = jsonLd()
    const h1 = document.querySelector('h1')
    const titulo = (meta('og:title') || (h1 && h1.innerText) || document.title || '').trim().slice(0, 300)
    const corpo = (document.body && document.body.innerText) || ''
    const plano = corpo.replace(/ /g, ' ')

    let preco = null, area = null, lote = null, quartos = null, suites = null, bairro = ''
    for (const x of ld) {
      const of = x.offers || {}
      if (preco == null) preco = num(of.price || (of.priceSpecification || {}).price || x.price)
      const fs = x.floorSize || {}
      if (area == null) area = num(fs.value || fs)
      if (quartos == null) quartos = num(x.numberOfRooms || x.numberOfBedrooms)
      const ad = x.address || {}
      if (!bairro) bairro = ad.neighborhood || ad.addressNeighborhood || ''
    }
    // preço: maior "R$ ..." que não seja condomínio/IPTU (como a lista de candidatos)
    if (preco == null) {
      let maior = null
      const re = /R\$\s*([\d.]+(?:,\d{2})?)/g
      let m
      while ((m = re.exec(plano))) {
        const antes = plano.slice(Math.max(0, m.index - 16), m.index).toLowerCase()
        if (antes.includes('cond') || antes.includes('iptu')) continue
        const v = num(m[1])
        if (v && v >= 20000 && (maior == null || v > maior)) maior = v
      }
      preco = maior
    }
    // área: rótulo de área útil/construída/privativa primeiro; senão o 1º "NNN m²"
    if (area == null) {
      const rot = /(?:[áa]rea\s*(?:[úu]til|constru[íi]da|privativa|total)?)[^\d]{0,20}([\d.,]+)\s*m(?:²|2)/i.exec(plano)
      const solto = /([\d.,]+)\s*m(?:²|2)\b/i.exec(plano)
      area = num((rot || solto || [])[1])
    }
    const lt = /(?:terreno|lote)[^\d]{0,20}([\d.,]+)\s*m(?:²|2)/i.exec(plano)
    if (lt) lote = num(lt[1])
    if (quartos == null) {
      const q = /(\d+)\s*(?:quartos?|dormit[óo]rios?)/i.exec(plano)
      if (q) quartos = Number(q[1])
    }
    const s = /(\d+)\s*su[íi]tes?/i.exec(plano)
    if (s) suites = Number(s[1])
    return {
      link, titulo, preco, area_m2: area, lote_m2: lote, quartos, suites, bairro: bairro || '',
      texto: (titulo + '\n' + plano).slice(0, 15000),
      foto_rect: fotoPrincipal(),
      foto_url: fotoUrl(),
      fotos_url: fotos(),          // 081-5: as outras fotos (o avaliador troca a principal, se precisar)
    }
  }

  /* 081-4: a foto GRANDE (a da galeria), nunca a miniatura. ZAP e Viva Real servem a mesma foto em vários tamanhos
   * pelo próprio endereço (?dimension=167x297, /fit-in/400x300/); pedimos a grande. */
  const PROPAGANDA = /doubleclick|googlesyndication|googleadservices|adservice|adsystem|\/ads?\/|banner|logo|sprite|icone?s?\/|app-?store|google-?play|play\.google|apple\.com|badge|selo|whatsapp|qr-?code|avatar|perfil/i
  function ampliar(u) {
    if (!/^https?:/i.test(u || '')) return ''
    try {
      const x = new URL(u)
      if (/resizedimgs\.(zapimoveis|vivareal)\.com\.br$/.test(x.hostname)) {
        if (x.searchParams.has('dimension')) { x.searchParams.set('dimension', '1920x1080'); x.searchParams.set('action', 'fit-in') }
        x.pathname = x.pathname.replace(/\/(fit-in|crop)\/\d+x\d+\//, '/fit-in/1920x1080/')
      }
      return x.toString()
    } catch (err) { return u }
  }
  function maiorDoSrcset(s) {
    let melhor = '', w = 0
    for (const parte of String(s || '').split(',')) {
      const [u, d] = parte.trim().split(/\s+/)
      const v = parseFloat(d) || 1
      if (u && v > w) { w = v; melhor = u }
    }
    return melhor
  }
  /** As fotos do anúncio, na ordem da galeria, em tamanho grande (até 12). Sem propaganda, logo ou ícone. */
  function fotos() {
    const out = []
    const por = (u) => { const a = ampliar(u); if (a && !PROPAGANDA.test(a) && !out.includes(a)) out.push(a) }
    por(meta('og:image'))
    for (const o of jsonLd()) {
      const im = o && o.image
      for (const u of Array.isArray(im) ? im : [im]) por(typeof u === 'string' ? u : u && u.url)
    }
    for (const im of document.querySelectorAll('img, picture source')) {
      const u = maiorDoSrcset(im.getAttribute('srcset') || im.getAttribute('data-srcset')) || im.currentSrc || im.src || im.getAttribute('data-src')
      const w = im.naturalWidth || 0, h = im.naturalHeight || 0
      if (im.tagName === 'IMG' && w && h && Math.max(w, h) < 400) continue          // 089-3: ícone, selo, miniatura (< 400 px)
      if ((im.getAttribute('alt') || '').match(/app store|google play|baixe|baixar|logo/i)) continue
      if (im.closest && im.closest('iframe, [id*="google_ads"], [class*="publicidade"], [class*="advert"]')) continue
      por(u)
      if (out.length >= 12) break
    }
    return out.slice(0, 12)
  }
  function fotoUrl() { return fotos()[0] || '' }

  /* ORDEM 029-5: onde está a foto principal NA TELA (a maior imagem visível). O popup recorta
   * esse pedaço da captura da tela; nada é baixado de outro site. */
  function fotoPrincipal() {
    let melhor = null
    const vw = window.innerWidth, vh = window.innerHeight
    for (const im of document.querySelectorAll('img, picture, [style*="background-image"]')) {
      const r = im.getBoundingClientRect()
      const x = Math.max(0, r.left), y = Math.max(0, r.top)
      const w = Math.min(vw, r.right) - x, h = Math.min(vh, r.bottom) - y
      if (w < 200 || h < 150) continue            // ícone, logo, miniatura
      if (w / h > 3.5 || h / w > 3.5) continue     // faixa/banner
      if (!melhor || w * h > melhor.w * melhor.h) melhor = { x, y, w, h }
    }
    return melhor ? { ...melhor, dpr: window.devicePixelRatio || 1 } : null
  }

  /* ORDEM 019: cartões da página de RESULTADOS de busca que o Alan está vendo (mesma regra do
   * JS_CARTOES do Coletor, com textContent): link do anúncio + texto do cartão com "R$". */
  function cartoes() {
    const vistos = new Set(); const out = []
    for (const a of document.querySelectorAll('a[href]')) {
      const href = a.href
      if (!/^https?:/i.test(href) || vistos.has(href)) continue
      let el = a, txt = ''
      for (let i = 0; i < 8 && el; i++) {
        txt = (el.textContent || '').replace(/\s+/g, ' ').trim()
        if (txt.length >= 40 && /R\$\s?\d/.test(txt)) break
        el = el.parentElement
      }
      if (!txt || txt.length < 40 || txt.length > 1500 || !/R\$\s?\d/.test(txt)) continue
      vistos.add(href)
      out.push({ link: href, texto: txt.slice(0, 1500) })
      if (out.length >= 120) break
    }
    return { url: location.href, cartoes: out }
  }

  window.__jdbExtrair = extrairAnuncio
  window.__jdbCartoes = cartoes
})()
