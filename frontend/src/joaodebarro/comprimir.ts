/* Compressão de fotos no navegador antes do envio (canvas → JPEG 0,85, máx. 2000 px).
 * A orientação EXIF é aplicada pelo createImageBitmap(imageOrientation: 'from-image'). PDFs e
 * qualquer coisa que não seja imagem decodificável seguem intactos; em falha, envia o original. */
import { QUALIDADE_JPEG, dimensoesAlvo, ehImagemComprimivel, nomeJpeg } from './campo'

export async function comprimirSeNecessario(file: File): Promise<File> {
  if (!ehImagemComprimivel(file.type) || typeof createImageBitmap !== 'function') return file
  let bmp: ImageBitmap | null = null
  try {
    bmp = await createImageBitmap(file, { imageOrientation: 'from-image' })
    const alvo = dimensoesAlvo(bmp.width, bmp.height, file.size)
    if (!alvo) return file
    const canvas = document.createElement('canvas')
    canvas.width = alvo.w
    canvas.height = alvo.h
    const ctx = canvas.getContext('2d')
    if (!ctx) return file
    ctx.drawImage(bmp, 0, 0, alvo.w, alvo.h)
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, 'image/jpeg', QUALIDADE_JPEG))
    const reduziu = alvo.w < bmp.width
    if (!blob || (!reduziu && blob.size >= file.size)) return file // recompressão não ajudou
    return new File([blob], nomeJpeg(file.name), { type: 'image/jpeg', lastModified: file.lastModified })
  } catch {
    return file
  } finally {
    bmp?.close()
  }
}
