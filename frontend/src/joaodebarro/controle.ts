/* Controle do avaliador sobre um trabalho (edição de campos, escolha de referenciais,
 * pendências acionáveis, edição do trabalho, aviso de fim). Lógica pura — controle.test.ts. */
import { unitario } from './calculo'
import { STATUS_FINAIS } from './rotulos'
import type { AcaoPendencia, DadosTrabalho, Referencial } from './tipos'
import { formVazio, paraPayload, type FormTrabalho } from './validacao'

/** Id estável por item de upload (vai no header X-Upload-Id: reenvio não duplica). */
export function novoUploadId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto
  if (c?.randomUUID) return c.randomUUID()
  return `u${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`
}

/** "1.234,56" / "1234.5" / "R$ 5.000" → número; null se não for número. */
export function decimalBR(v: string): number | null {
  let t = v.replace(/[^\d.,-]/g, '')
  if (!t) return null
  if (t.includes(',')) t = t.replace(/\./g, '').replace(',', '.')
  else if ((t.match(/\./g) || []).length > 1 || /^-?\d{1,3}\.\d{3}$/.test(t)) t = t.replace(/\./g, '')
  const n = Number(t)
  return Number.isFinite(n) ? n : null
}

export const RE_VISTORIA = /^vistoria do avaliador em (\d{1,2}\/\d{1,2}\/\d{4}|\d{4}-\d{2}-\d{2})$/i

const chave = (s: string) => (s.replace(/\\/g, '/').trim().split('/').pop() || '').toLowerCase()

/** Espelho da regra do servidor (D-013): a fonte cita um arquivo do trabalho (vistoria: foto)
 * ou, na vistoria, é "vistoria do avaliador em dd/mm/aaaa". Mensagem de erro, ou null. */
export function erroFonte(origem: 'documento' | 'vistoria', fonte: string,
                          arquivos: ReadonlyArray<{ nome: string; caminho: string; tipo: string }>): string | null {
  const f = fonte.trim()
  if (!f) return 'Informe a fonte.'
  if (origem === 'vistoria' && RE_VISTORIA.test(f)) return null
  const regs = origem === 'vistoria' ? arquivos.filter((a) => a.tipo === 'foto') : arquivos
  const fl = f.replace(/\\/g, '/').toLowerCase()
  const cita = regs.some((a) => [a.nome, a.caminho].some((n) => {
    const k = chave(n)
    if (!k) return false
    const i = fl.indexOf(k)
    if (i < 0) return false
    const antes = fl[i - 1] ?? ''
    const depois = fl[i + k.length] ?? ''
    return !/[\w.-]/.test(antes) && !/[\w-]/.test(depois)
  }))
  if (cita) return null
  return origem === 'vistoria'
    ? 'Cite uma foto enviada (ex.: foto/frente.jpg) ou escreva "vistoria do avaliador em dd/mm/aaaa".'
    : 'Cite um arquivo enviado neste trabalho (ex.: documento/iptu.pdf p. 1).'
}

/** Valida a escolha manual de referenciais. Mensagem de erro, ou null. */
export function erroEscolha(escolhidos: ReadonlySet<number>, refs: readonly Referencial[], unit: string): string | null {
  if (escolhidos.size === 0) return 'Escolha ao menos 1 referencial.'
  const us = refs.filter((r) => escolhidos.has(r.n)).map(unitario).filter((u): u is number => u !== null)
  if (!us.length) return 'Nenhum dos escolhidos tem preço e área.'
  if (!unit.trim()) return null
  const u = decimalBR(unit)
  if (u === null) return 'Unitário inválido.'
  const [mi, ma] = [Math.min(...us), Math.max(...us)]
  if (u < mi || u > ma) {
    const br = (x: number) => x.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    return `O unitário deve ficar entre R$ ${br(mi)} e R$ ${br(ma)} por m².`
  }
  return null
}

/** Rótulo do botão de cada ação de pendência. */
export function rotuloAcao(a: AcaoPendencia): string {
  switch (a.tipo) {
    case 'enviar_arquivo':
      return a.tipo_arquivo === 'foto' ? 'Enviar fotos'
        : a.tipo_arquivo === 'solicitante' ? 'Enviar documento do solicitante' : 'Enviar documento'
    case 'editar_campo': return `Editar ${a.campo}`
    case 'ligar_coletor': return 'Ligar o Coletor'
    case 'preencher_trabalho': return 'Editar dados do trabalho'
  }
}

/** Dados do trabalho → formulário P5 (para edição). */
export function formDeDados(d: DadosTrabalho): FormTrabalho {
  return {
    ...formVazio(),
    numero: String(d.numero), modalidade: d.modalidade, finalidade: d.finalidade ?? '',
    cliente: d.cliente ?? '', tipo: d.tipo ?? '', bairro: d.bairro ?? '', cidade: d.cidade ?? '',
    pin_maps: d.pin_maps ?? '', data_base: d.data_base ?? '', data_vistoria: d.data_vistoria ?? '',
    contexto: d.contexto ?? '', processo_numero: d.processo_numero ?? '', vara_juizo: d.vara_juizo ?? '',
    acao: d.acao ?? '', autor: d.partes?.autor ?? '', reu: d.partes?.reu ?? '',
    quesitos: (d.quesitos ?? []).join('\n'),
  }
}

/** Corpo do PUT /jobs/{id}: os campos do P5 sem número/id. */
export function payloadEdicao(form: FormTrabalho) {
  const { numero: _n, ...resto } = paraPayload(form)
  void _n
  return resto
}

/** Notificar quando o status passa de não-final a final enquanto a aba está aberta. */
export function deveNotificar(anterior: string | null | undefined, atual: string | null | undefined): boolean {
  return !!anterior && !STATUS_FINAIS.includes(anterior) && !!atual && STATUS_FINAIS.includes(atual)
}
