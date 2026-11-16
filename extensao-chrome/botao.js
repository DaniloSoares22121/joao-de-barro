/* Enviar ao JdB — BOTÃO FLUTUANTE na página (1.1.0, ORDEM 076).
 * Aparece sozinho nos portais de imóveis permitidos pelo avaliador:
 *   - página de ANÚNCIO: "Enviar ao JdB" (foto, dados, data e hora de acesso — D-082);
 *   - página de RESULTADOS: "Enviar resultados desta página".
 * Ao tocar: "Para qual trabalho?" (o mais recente em cima) -> envia -> "✓ Enviado ao trabalho 9120".
 * Roda isolado da página (Shadow DOM): não muda nada do portal e não lê nada sozinho. */
(function () {
  if (window.__jdbBotao) return
  window.__jdbBotao = true

  const ANUNCIO = [
    /zapimoveis\.com\.br\/imovel\//i, /vivareal\.com\.br\/imovel\//i, /olx\.com\.br\/.*-\d{6,}/i,
    /imovelweb\.com\.br\/propriedades\//i, /62imoveis\.com\.br\/.*(imovel|anuncio)/i,
    /deztop\.com(\.br)?\/.*(imovel|anuncio)/i, /chavesnamao\.com\.br\/imovel\//i, /mitula\.com\.br\/.*(imovel|anuncio|detalhe)/i,
  ]
  const ehAnuncio = () => ANUNCIO.some((r) => r.test(location.href))
  const ehResultados = () => !ehAnuncio() && (window.__jdbCartoes ? window.__jdbCartoes().cartoes.length >= 2 : false)

  const host = document.createElement('div')
  host.id = 'jdb-enviar'
  host.style.cssText = 'all:initial;position:fixed;right:16px;bottom:16px;z-index:2147483647;inset:auto 16px 16px auto;' +
    'margin:0;padding:0;border:0;background:transparent;overflow:visible'
  // 086-5: na "camada de cima" do navegador (Popover API): propaganda de tela cheia não cobre o botão nem o aviso
  try { host.popover = 'manual' } catch (e) { /* Chrome antigo: fica o z-index */ }
  const porCima = () => { try { if (host.popover) { if (host.matches(':popover-open')) host.hidePopover(); host.showPopover() } } catch (e) { /* ok */ } }
  const raiz = host.attachShadow({ mode: 'closed' })
  const logo = chrome.runtime.getURL('icones/jdb-escuro-48.png')
  raiz.innerHTML = `
    <style>
      * { box-sizing: border-box; font-family: "Segoe UI", system-ui, Arial, sans-serif; }
      .bt { display: flex; align-items: center; gap: 8px; min-height: 48px; padding: 6px 16px 6px 8px; border: 0;
            border-radius: 24px; background: #16283A; color: #fff; font-size: 15px; font-weight: 700; cursor: pointer;
            box-shadow: 0 6px 18px rgba(0,0,0,.28); border: 2px solid #F5B800; }
      .bt:hover { background: #22364E; }
      .bt:focus-visible { outline: 3px solid #F5B800; outline-offset: 2px; }
      .bt img { width: 34px; height: 34px; }
      .painel { position: absolute; right: 0; bottom: 60px; width: 320px; max-height: 60vh; overflow: auto; background: #fff;
                color: #16283A; border-radius: 14px; box-shadow: 0 10px 30px rgba(0,0,0,.3); padding: 12px; font-size: 15px; }
      .painel h2 { font-size: 16px; margin: 0 0 8px; }
      .tr { display: block; width: 100%; text-align: left; border: 1px solid #c9ced6; background: #fff; color: #16283A;
            border-radius: 10px; padding: 9px 10px; margin: 6px 0; cursor: pointer; font-size: 15px; }
      .tr:hover, .tr:focus-visible { border-color: #16283A; background: #fff8e1; outline: none; }
      .tr b { display: block; }
      .sub { color: #5b6470; font-size: 13px; }
      .ok { color: #14803F; font-weight: 700; } .erro { color: #b42318; }
      .x { float: right; border: 0; background: none; font-size: 18px; cursor: pointer; color: #5b6470; }
    </style>
    <div class="painel" hidden></div>
    <button class="bt" type="button"><img alt="" src="${logo}"><span></span></button>`
  const bt = raiz.querySelector('.bt'), painel = raiz.querySelector('.painel'), rotulo = raiz.querySelector('.bt span')

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
  const pedir = (m) => new Promise((ok) => chrome.runtime.sendMessage(m, (r) => ok(r || { ok: false, erro: 'sem resposta' })))
  function mostrar(html) { porCima(); painel.innerHTML = `<button class="x" aria-label="Fechar">×</button>${html}`; painel.hidden = false
    painel.querySelector('.x').addEventListener('click', () => { painel.hidden = true }) }

  function atualizar() {
    const a = ehAnuncio(), r = !a && ehResultados()
    host.style.display = a || r ? '' : 'none'
    rotulo.textContent = a ? (enviadoA ? `✓ Enviado ao ${enviadoA}` : 'Enviar ao JdB') : 'Enviar resultados desta página'
    bt.setAttribute('aria-label', rotulo.textContent)
  }

  let enviadoA = ''                              // 081-2: "✓ Enviado ao 9120" fica no botão nesta página
  async function enviar(trabalho, numero, direto) {
    const anuncio = ehAnuncio()
    mostrar('<p class="sub">Enviando…</p>')
    rotulo.textContent = 'Enviando…'
    bt.disabled = true
    let r
    if (anuncio) {
      const dados = window.__jdbExtrair ? window.__jdbExtrair() : { link: location.href }
      try { r = await pedir({ tipo: 'enviar', trabalho, dados }) } finally { bt.disabled = false }
    } else {
      r = await pedir({ tipo: 'pagina', trabalho, pagina: window.__jdbCartoes() })
    }
    if (!r.ok) { atualizar(); return mostrar(`<p class="erro">${esc(r.erro)}</p>`) }
    if (anuncio) {
      enviadoA = String(numero); rotulo.textContent = `✓ Enviado ao ${numero}`
      try { chrome.storage.local.set({ ultimo_trabalho: { id: trabalho, numero: String(numero) } }) } catch (e) { /* ok */ }
    }
    if (anuncio && direto) {                    // 079-A: já era referencial deste trabalho
      const c = r.contagem
      mostrar(`<p class="ok">✓ Foto e data guardadas no ${esc(numero)}${c ? ` (${esc(c.recebidos)} de ${esc(c.total)})` : ''}</p>` +
        `<p class="sub">Referencial nº ${esc(r.r.n)}${r.r.foto ? ', com a foto' : ', sem foto: deixe a foto principal visível e envie de novo'}.</p>`)
    } else if (anuncio) {
      mostrar(`<p class="ok">✓ Enviado ao trabalho ${esc(numero)}</p><p class="sub">Referencial nº ${esc(r.r.n)}${r.r.foto ? ', com a foto' : ''}.</p>`)
    } else {
      const n = (r.r.novos || []).length
      mostrar(`<p class="ok">✓ Enviado ao trabalho ${esc(numero)}</p><p class="sub">${n ? `${n} ${n === 1 ? 'anúncio novo' : 'anúncios novos'} na lista.` : 'Nenhum anúncio novo: os desta página já estão na lista ou são de fora da região.'}</p>`)
    }
  }

  bt.addEventListener('click', async () => {
    if (!painel.hidden) { painel.hidden = true; return }
    mostrar('<p class="sub">Carregando os trabalhos…</p>')
    // 086-4: depois de "✓ Enviado", um toque reabre a escolha (para mandar o mesmo anúncio a outro trabalho)
    if (ehAnuncio() && !enviadoA) {             // 079-A: anúncio que já é referencial de UM trabalho -> envia direto
      const q = await pedir({ tipo: 'de_quem', link: location.href })
      if (q.ok && q.dono) return enviar(q.dono.trabalho, q.dono.numero, true)
      // 086-3: o trabalho escolhido por último vem marcado: "Enviar ao 9121 de novo?" [Sim] [Outro]
      const ult = await new Promise((ok) => { try { chrome.storage.local.get('ultimo_trabalho', (x) => ok(x && x.ultimo_trabalho)) } catch (e) { ok(null) } })
      const entre = q.ok && q.varios ? q.varios.some((v) => v.trabalho === (ult && ult.id)) : true
      if (ult && ult.id && entre) {
        mostrar(`<h2>Enviar ao ${esc(ult.numero)} de novo?</h2><button class="tr" type="button" data-r="sim"><b>Sim, ao ${esc(ult.numero)}</b></button>` +
          '<button class="tr" type="button" data-r="outro"><b>Outro trabalho</b></button>')
        const escolha = await new Promise((ok) => painel.querySelectorAll('.tr').forEach((x) => x.addEventListener('click', () => ok(x.dataset.r))))
        if (escolha === 'sim') return enviar(ult.id, ult.numero, !!(q.varios || []).length)
        mostrar('<p class="sub">Carregando os trabalhos…</p>')
      }
    }
    const r = await pedir({ tipo: 'trabalhos' })
    if (!r.ok) {
      return mostrar(r.erro === 'ENTRAR'
        ? '<p>Abra o JdB neste Chrome: a extensão se liga sozinha, sem senha. Depois toque de novo aqui.</p>'
        : `<p class="erro">${esc(r.erro)}</p>`)
    }
    if (!r.trabalhos.length) return mostrar('<p>Nenhum trabalho recebendo anúncios agora (laudo aprovado, assinado ou cancelado não recebe).</p>')
    mostrar('<h2>Para qual trabalho?</h2>' + r.trabalhos.map((t) =>
      `<button class="tr" type="button" data-id="${esc(t.id)}" data-n="${esc(t.numero)}"><b>Nº ${esc(t.numero)}</b>
        <span class="sub">${esc(t.cliente)}${t.bairro ? ' · ' + esc(t.bairro) : ''}</span></button>`).join(''))
    painel.querySelectorAll('.tr').forEach((b) => b.addEventListener('click', () => enviar(b.dataset.id, b.dataset.n)))
  })

  document.documentElement.appendChild(host)
  porCima()
  atualizar()
  // portais de página única: o endereço muda sem recarregar
  let ultimo = location.href
  setInterval(() => { if (location.href !== ultimo) { ultimo = location.href; enviadoA = ''; atualizar() } }, 1000)
  setTimeout(atualizar, 2500)                  // resultados carregados depois
})()
