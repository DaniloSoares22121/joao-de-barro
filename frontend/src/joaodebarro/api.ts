/* João de Barro — cliente da API do avaliador (/api/avaliacao/*).
 * Login usa a conta Brixly (/api/auth/login); o token fica em localStorage "jdb_token". */
import { comRetry } from './campo'
import { useStore } from './store'
import { token } from './token'

const BASE = '/api/avaliacao'

export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

function detalhe(corpo: unknown, status: number): string {
  const c = (corpo || {}) as { error?: unknown; detail?: unknown }
  const d = c.detail ?? c.error
  if (typeof d === 'string') return d
  if (d != null) return JSON.stringify(d)
  return `Erro ${status}`
}

/** 401 → limpa a sessão e volta ao login; 403 → tela "acesso restrito ao avaliador". */
function tratarAuth(status: number) {
  if (status === 401) {
    token.limpar()
    useStore.getState().sair()
  } else if (status === 403) {
    useStore.getState().negar()
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const t = token.get()
  const r = await fetch(BASE + path, {
    method,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(t ? { Authorization: `Bearer ${t}` } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  const corpo = await r.json().catch(() => ({}))
  if (!r.ok) {
    tratarAuth(r.status)
    throw new ApiError(r.status, detalhe(corpo, r.status))
  }
  return corpo as T
}

export const get = <T>(path: string) => req<T>('GET', path)
export const post = <T>(path: string, body?: unknown) => req<T>('POST', path, body ?? {})
export const put = <T>(path: string, body?: unknown) => req<T>('PUT', path, body ?? {})

export async function login(email: string, password: string): Promise<void> {
  const r = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  const corpo = await r.json().catch(() => ({}))
  if (!r.ok) throw new ApiError(r.status, detalhe(corpo, r.status))
  const tk = (corpo as { token?: string }).token
  if (!tk) throw new ApiError(500, 'Resposta de login sem token')
  token.set(tk)
  useStore.getState().entrar(tk)
}

export interface Enviado { nome: string; tipo: string; caminho: string; bytes: number }

/** Envia arquivos de um tipo (XHR para ter progresso 0..1). `fachada` marca a foto da capa.
 * Erro de rede (status 0) é retentado 3x (1/3/9 s); a resposta traz o nome final no servidor. */
export function upload(jobId: string, tipo: string, files: File[],
                       onProgress?: (frac: number) => void,
                       opcoes: { fachada?: boolean; uploadId?: string; aoRetentar?: (tentativa: number, ms: number) => void } = {},
): Promise<Enviado[]> {
  return comRetry(() => uploadUmaVez(jobId, tipo, files, onProgress, !!opcoes.fachada, opcoes.uploadId),
                  undefined, opcoes.aoRetentar)
}

/** `uploadId` (um arquivo por envio): o servidor devolve o registro existente se repetir. */
function uploadUmaVez(jobId: string, tipo: string, files: File[],
                      onProgress: ((frac: number) => void) | undefined, fachada: boolean,
                      uploadId?: string): Promise<Enviado[]> {
  return new Promise((resolve, reject) => {
    const fd = new FormData()
    fd.append('tipo', tipo)
    if (fachada) fd.append('fachada', 'true')
    for (const f of files) fd.append('arquivos', f, f.name)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE}/jobs/${encodeURIComponent(jobId)}/arquivos`)
    const t = token.get()
    if (t) xhr.setRequestHeader('Authorization', `Bearer ${t}`)
    if (uploadId && files.length === 1) xhr.setRequestHeader('X-Upload-Id', uploadId)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total)
    }
    xhr.onload = () => {
      let corpo: unknown = {}
      try { corpo = JSON.parse(xhr.responseText || '{}') } catch { /* não-JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(1)
        resolve(corpo as Enviado[])
      } else {
        tratarAuth(xhr.status)
        reject(new ApiError(xhr.status, detalhe(corpo, xhr.status)))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, 'Falha de rede no envio'))
    xhr.send(fd)
  })
}

/** GET autenticado de um arquivo (precisa do Bearer, então fetch → blob). `nome` vem do Content-Disposition. */
export async function baixarRaw(path: string): Promise<{ blob: Blob; nome: string }> {
  const t = token.get()
  const r = await fetch(BASE + path, { headers: t ? { Authorization: `Bearer ${t}` } : {} })
  if (!r.ok) {
    const corpo = await r.json().catch(() => ({}))
    tratarAuth(r.status)
    throw new ApiError(r.status, detalhe(corpo, r.status))
  }
  const cd = r.headers.get('content-disposition') || ''
  const m = /filename\*=UTF-8''([^;]+)/i.exec(cd) || /filename="?([^";]+)"?/i.exec(cd)
  let nome = ''
  try { nome = m ? decodeURIComponent(m[1]) : '' } catch { nome = m ? m[1] : '' }
  return { blob: await r.blob(), nome }
}

/** Baixa um arquivo da entrega do trabalho. */
export async function baixar(jobId: string, arquivo: string): Promise<Blob> {
  const caminho = arquivo.split('/').map(encodeURIComponent).join('/')
  return (await baixarRaw(`/jobs/${encodeURIComponent(jobId)}/entrega/${caminho}`)).blob
}

export function wsUrl(jobId: string): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws/avaliacao/${encodeURIComponent(jobId)}?token=${encodeURIComponent(token.get())}`
}
