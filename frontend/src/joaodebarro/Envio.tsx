/* Zonas de arquivo + envio (compressão, retry, fachada), compartilhado por "Novo trabalho" e
 * pela tela do trabalho ainda não iniciado ("Enviar mais arquivos"). */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, upload } from './api'
import { comprimirSeNecessario } from './comprimir'
import { novoUploadId } from './controle'
import Dropzone, { type ItemUpload } from './Dropzone'
import { MSG_ARQUIVO_GRANDE, validarArquivo } from './validacao'

export type Tipo = 'documento' | 'foto' | 'solicitante'

export const ZONAS: ReadonlyArray<{ tipo: Tipo; titulo: string; descricao: string; accept?: string; camera?: boolean }> = [
  { tipo: 'documento', titulo: 'Documentos do imóvel',
    descricao: 'Matrícula ou escritura, IPTU, planta, habite-se, notas fiscais de benfeitorias.',
    accept: '.pdf,.doc,.docx,image/*', camera: true },
  { tipo: 'foto', titulo: 'Fotos da vistoria',
    descricao: 'Marque uma foto como “Fachada (capa)” — senão o João de Barro escolhe.', accept: 'image/*', camera: true },
  { tipo: 'solicitante', titulo: 'Documentos do solicitante',
    descricao: 'RG, CNH, CPF ou contrato social. Entram no laudo com os dados pessoais tarjados.',
    accept: '.pdf,image/*', camera: true },
]

const novoId = novoUploadId

export function mensagemErro(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 413) return MSG_ARQUIVO_GRANDE
    if (e.status === 0) return 'Falha de rede. Verifique a conexão e tente novamente.'
    if (e.status === 422) return 'O servidor recusou os dados. Revise os campos.'
    return e.detail
  }
  return 'Erro inesperado.'
}

export const ehAuth = (e: unknown) => e instanceof ApiError && (e.status === 401 || e.status === 403)

export function useEnvio() {
  const [arquivos, setArquivos] = useState<Record<Tipo, ItemUpload[]>>({ documento: [], foto: [], solicitante: [] })
  const [fachadaId, setFachadaId] = useState<string | null>(null)
  const montado = useRef(true)
  useEffect(() => {
    montado.current = true
    return () => { montado.current = false }
  }, [])

  const adicionar = useCallback((tipo: Tipo, files: File[]) => {
    setArquivos((a) => {
      const existentes = new Set(a[tipo].map((i) => `${i.file.name}|${i.file.size}|${i.file.lastModified}`))
      const novos: ItemUpload[] = []
      for (const file of files) {
        const chave = `${file.name}|${file.size}|${file.lastModified}`
        if (existentes.has(chave)) continue
        existentes.add(chave)
        const erro = validarArquivo(file)
        novos.push({ id: novoId(), file, progresso: 0, estado: erro ? 'erro' : 'fila', erro: erro ?? undefined })
      }
      return { ...a, [tipo]: [...a[tipo], ...novos] }
    })
  }, [])

  const remover = useCallback((tipo: Tipo, id: string) => {
    setArquivos((a) => ({ ...a, [tipo]: a[tipo].filter((i) => i.id !== id) }))
    setFachadaId((f) => (f === id ? null : f))
  }, [])

  const atualizar = (tipo: Tipo, id: string, patch: Partial<ItemUpload>) => {
    if (!montado.current) return
    setArquivos((a) => ({ ...a, [tipo]: a[tipo].map((i) => (i.id === id ? { ...i, ...patch } : i)) }))
  }

  const temGrande = ZONAS.some((z) => arquivos[z.tipo].some((i) => i.estado === 'erro' && i.erro === MSG_ARQUIVO_GRANDE))
  const total = ZONAS.reduce((n, z) => n + arquivos[z.tipo].length, 0)
  const pendentes = ZONAS.reduce((n, z) => n + arquivos[z.tipo].filter((i) => i.estado !== 'ok').length, 0)

  /** Envia o que não foi enviado. Devolve nº de falhas, ou null se a sessão caiu (401/403). */
  async function enviarPendentes(jobId: string, passo: (txt: string) => void): Promise<number | null> {
    const fila = ZONAS.flatMap((z) => arquivos[z.tipo].filter((i) => i.estado !== 'ok').map((i) => ({ z, i })))
    let falhou = 0
    let feitos = 0
    for (const { z, i } of fila) {
      feitos += 1
      passo(`Enviando arquivos (${feitos} de ${fila.length})…`)
      atualizar(z.tipo, i.id, { estado: 'enviando', progresso: 0, erro: undefined, nota: undefined })
      try {
        let file = i.file
        if (file.type.startsWith('image/')) {
          atualizar(z.tipo, i.id, { nota: 'Comprimindo…' })
          file = await comprimirSeNecessario(file)
          atualizar(z.tipo, i.id, { nota: undefined })
        }
        await upload(jobId, z.tipo, [file], (p) => atualizar(z.tipo, i.id, { progresso: p }), {
          fachada: z.tipo === 'foto' && fachadaId === i.id,
          uploadId: i.id,
          aoRetentar: (n, ms) => atualizar(z.tipo, i.id, {
            progresso: 0, nota: `Sem rede; tentativa ${n} de 4 em ${Math.round(ms / 1000)} s…` }),
        })
        atualizar(z.tipo, i.id, { estado: 'ok', progresso: 1, nota: undefined })
      } catch (err) {
        if (ehAuth(err)) return null
        falhou += 1
        atualizar(z.tipo, i.id, { estado: 'erro', erro: mensagemErro(err), nota: undefined })
      }
    }
    return falhou
  }

  return { arquivos, adicionar, remover, fachadaId, setFachadaId, temGrande, total, pendentes, enviarPendentes }
}

export function ZonasArquivos({ envio, desabilitado, apenas }: {
  envio: ReturnType<typeof useEnvio>; desabilitado: boolean; apenas?: Tipo
}) {
  return (
    <>
      {ZONAS.filter((z) => !apenas || z.tipo === apenas).map((z) => (
        <Dropzone key={z.tipo} id={`dz-${z.tipo}`} titulo={z.titulo} descricao={z.descricao} accept={z.accept}
                  camera={z.camera} itens={envio.arquivos[z.tipo]} desabilitado={desabilitado}
                  fachadaId={z.tipo === 'foto' ? envio.fachadaId : undefined}
                  onFachada={z.tipo === 'foto' ? envio.setFachadaId : undefined}
                  onAdicionar={(fs) => envio.adicionar(z.tipo, fs)} onRemover={(id) => envio.remover(z.tipo, id)} />
      ))}
    </>
  )
}
