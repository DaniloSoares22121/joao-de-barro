/* ORDEM 041 / D-092: avisos do próprio app (sem agenda externa). Registra o service worker,
 * pede permissão de notificação e inscreve este aparelho no Web Push do servidor.
 * No celular, depende do site publicado com HTTPS (etapa 5); no PC funciona em localhost. */
import { get, post } from './api'

function chaveBytes(b64: string): Uint8Array {
  const pad = '='.repeat((4 - (b64.length % 4)) % 4)
  const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(raw, (c) => c.charCodeAt(0))
}

export function suportado(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

export async function registrar(): Promise<ServiceWorkerRegistration | null> {
  if (!('serviceWorker' in navigator)) return null
  try {
    return await navigator.serviceWorker.register('./sw-jdb.js', { scope: './' })
  } catch {
    return null
  }
}

/** Liga os avisos neste aparelho. Devolve uma frase curta para a tela. */
export async function ativar(): Promise<string> {
  if (!suportado()) return 'Este navegador não mostra avisos.'
  const perm = await Notification.requestPermission()
  if (perm !== 'granted') return 'Avisos bloqueados neste navegador.'
  const reg = await registrar()
  if (!reg) return 'Não consegui ligar os avisos.'
  await navigator.serviceWorker.ready
  const { chave } = await get<{ chave: string }>('/push/chave')
  let sub = await reg.pushManager.getSubscription()
  if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: chaveBytes(chave) as BufferSource })
  await post('/push/inscrever', sub.toJSON())
  return 'Avisos ligados neste aparelho.'
}

export async function testar(): Promise<string> {
  const r = await post<{ enviados: number[] }>('/push/teste')
  return r.enviados.some((s) => s === 201) ? 'Aviso de teste enviado.' : 'Ligue os avisos neste aparelho primeiro.'
}
