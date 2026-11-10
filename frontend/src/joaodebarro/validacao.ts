/* Validação do formulário "Novo trabalho" (P5). Lógica pura, sem React — testada em validacao.test.ts. */

export const MODALIDADES_VALIDAS = ['OV', 'AM', 'AM_GARANTIA', 'AMJ'] as const
export const MAX_BYTES = 50 * 1024 * 1024
export const MSG_ARQUIVO_GRANDE = 'arquivo acima de 50 MB'

export interface FormTrabalho {
  numero: string
  modalidade: string
  finalidade: string
  cliente: string
  tipo: string
  bairro: string
  cidade: string
  pin_maps: string
  data_base: string
  data_vistoria: string
  contexto: string
  // AMJ (processo opcional em AM)
  processo_numero: string
  vara_juizo: string
  acao: string
  autor: string
  reu: string
  /** Um quesito por linha. */
  quesitos: string
}

export type CampoForm = keyof FormTrabalho
export type Erros = Partial<Record<CampoForm, string>>

export function formVazio(hoje: string = hojeISO()): FormTrabalho {
  return {
    numero: '', modalidade: '', finalidade: '', cliente: '', tipo: '', bairro: '', cidade: '',
    pin_maps: '', data_base: hoje, data_vistoria: '', contexto: '',
    processo_numero: '', vara_juizo: '', acao: '', autor: '', reu: '', quesitos: '',
  }
}

/** Data local de hoje no formato AAAA-MM-DD. */
export function hojeISO(d: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** "AAAA-MM-DD" que existe no calendário. */
export function dataISOValida(s: string): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s)
  if (!m) return false
  const [a, mes, dia] = [Number(m[1]), Number(m[2]), Number(m[3])]
  const d = new Date(Date.UTC(a, mes - 1, dia))
  return d.getUTCFullYear() === a && d.getUTCMonth() === mes - 1 && d.getUTCDate() === dia
}

/** Acrescenta https:// quando o usuário cola o link sem o esquema. */
export function normalizarPin(pin: string): string {
  const t = pin.trim()
  if (!t) return ''
  return /^[a-z][a-z0-9+.-]*:/i.test(t) ? t : `https://${t}`
}

/** Aceita links do Google Maps: maps.app.goo.gl/…, goo.gl/maps/…, google.com(.br)/maps/…, maps.google.com/…. */
export function pinValido(pin: string): boolean {
  let u: URL
  try { u = new URL(normalizarPin(pin)) } catch { return false }
  if (u.protocol !== 'https:' && u.protocol !== 'http:') return false
  const host = u.hostname.toLowerCase().replace(/^www\./, '')
  const caminho = u.pathname
  if (host === 'maps.app.goo.gl') return caminho.length > 1
  if (host === 'goo.gl') return caminho.startsWith('/maps') && caminho.length > '/maps'.length + 1
  if (host === 'maps.google.com' || host === 'maps.google.com.br') return true
  if (host === 'google.com' || host === 'google.com.br') return caminho === '/maps' || caminho.startsWith('/maps/')
  return false
}

const OBRIGATORIOS: ReadonlyArray<[CampoForm, string]> = [
  ['finalidade', 'Informe a finalidade (venda, locação, ambos ou outra).'],
  ['cliente', 'Informe o solicitante (nome ou razão social).'],
  ['tipo', 'Informe o tipo do imóvel.'],
  ['bairro', 'Informe o bairro ou condomínio.'],
  ['cidade', 'Informe a cidade.'],
]

/** Devolve {campo: mensagem} — vazio quando o formulário está completo e válido. */
export function validar(form: FormTrabalho): Erros {
  const e: Erros = {}

  const n = form.numero.trim()
  if (!n) e.numero = 'Informe o número do trabalho.'
  else if (!/^\d+$/.test(n) || Number(n) < 1) e.numero = 'O número deve ser um inteiro positivo.'

  if (!form.modalidade) e.modalidade = 'Escolha a modalidade.'
  else if (!(MODALIDADES_VALIDAS as readonly string[]).includes(form.modalidade)) e.modalidade = 'Modalidade inválida.'

  for (const [campo, msg] of OBRIGATORIOS) {
    if (!form[campo].trim()) e[campo] = msg
  }

  if (!form.pin_maps.trim()) e.pin_maps = 'Cole o link do pin no Google Maps.'
  else if (!pinValido(form.pin_maps)) {
    e.pin_maps = 'Link inválido. Use um link do Google Maps (maps.app.goo.gl ou google.com/maps).'
  }

  if (!form.data_base) e.data_base = 'Informe a data-base.'
  else if (!dataISOValida(form.data_base)) e.data_base = 'Data-base inválida.'

  if (!form.data_vistoria) e.data_vistoria = 'Informe a data da vistoria.'
  else if (!dataISOValida(form.data_vistoria)) e.data_vistoria = 'Data da vistoria inválida.'

  return e
}

/** Corpo do POST /jobs (só chamar com `validar(form)` vazio). */
export function paraPayload(form: FormTrabalho) {
  return {
    numero: Number(form.numero.trim()),
    modalidade: form.modalidade,
    finalidade: form.finalidade.trim(),
    cliente: form.cliente.trim(),
    tipo: form.tipo.trim(),
    bairro: form.bairro.trim(),
    cidade: form.cidade.trim(),
    pin_maps: normalizarPin(form.pin_maps),
    data_base: form.data_base,
    data_vistoria: form.data_vistoria,
    contexto: form.contexto.trim(),
    ...dadosProcesso(form),
  }
}

/** Quesitos digitados um por linha (linhas vazias ignoradas). */
export function quesitosLista(texto: string): string[] {
  return texto.split(/\r?\n/).map((q) => q.trim()).filter(Boolean)
}

/** Campos do processo: AMJ envia tudo; AM só o processo (opcional); demais, nada. */
export function dadosProcesso(form: FormTrabalho) {
  if (form.modalidade !== 'AMJ' && form.modalidade !== 'AM') return {}
  const base = {
    processo_numero: form.processo_numero.trim(),
    vara_juizo: form.vara_juizo.trim(),
    acao: form.acao.trim(),
  }
  if (form.modalidade === 'AM') return base
  const autor = form.autor.trim()
  const reu = form.reu.trim()
  return { ...base, partes: autor || reu ? { autor, reu } : null, quesitos: quesitosLista(form.quesitos) }
}

/** null quando o arquivo pode ser enviado; senão a mensagem de erro. */
export function validarArquivo(f: { size: number }): string | null {
  return f.size > MAX_BYTES ? MSG_ARQUIVO_GRANDE : null
}

export function tamanhoLegivel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`
}
