/* Opções: endereço do sistema (produção ou PC de teste). */
const PADRAO = 'https://joaodebarro.brixly.com.br'
const campo = document.getElementById('servidor')
const msg = document.getElementById('msg')

chrome.storage.local.get(['servidor'], ({ servidor }) => { campo.value = servidor || PADRAO })

document.getElementById('salvar').addEventListener('click', async () => {
  const servidor = (campo.value.trim() || PADRAO).replace(/\/$/, '')
  try {
    const origem = new URL(servidor).origin + '/*'
    const fixos = [PADRAO, 'http://localhost:8866', 'http://127.0.0.1:8866']
    if (!fixos.includes(new URL(servidor).origin)) {
      const dada = await chrome.permissions.request({ origins: [origem] })
      if (!dada) throw new Error('Permissão negada para esse endereço.')
    }
    const { servidor: antigo } = await chrome.storage.local.get(['servidor'])
    await chrome.storage.local.set({ servidor })
    if (antigo !== servidor) await chrome.storage.local.remove('jdb_token')   // outro sistema: novo login
    msg.textContent = 'Salvo. Abra o JdB neste Chrome: a extensão se liga sozinha, sem senha.'
  } catch (e) {
    msg.textContent = 'Endereço inválido: ' + e.message
  }
})
