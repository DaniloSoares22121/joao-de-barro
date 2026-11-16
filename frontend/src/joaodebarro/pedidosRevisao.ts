/* 114: o quadro único "O que você quer mudar?" — o modelo e a conferência de que há pedido além dele. */

/** O quadro já abre com o modelo escrito (texto de verdade, editável). */
export const MODELO_AJUSTE = 'Onde fica: \nO que mudar: '

/** Há algo escrito além do modelo "Onde fica: / O que mudar:"? */
export function temPedido(texto: string): boolean {
  return texto.split('\n').some((l) => l.replace(/^\s*(onde\s+fica|o\s+que\s+mudar)\s*:/i, '').trim() !== '')
}

/** [+ Outro ajuste]: mais um par no fim, depois de uma linha em branco. */
export function maisUmPar(texto: string): string {
  return `${texto.replace(/\s+$/, '')}\n\n${MODELO_AJUSTE}`
}

/** 116-e: o cursor está numa linha "O que mudar:" (modo misto: o ditado entra só nesse campo)? Devolve o fim da linha. */
export function campoOQueNoCursor(texto: string, pos: number): number | null {
  const ini = texto.lastIndexOf('\n', Math.max(0, pos - 1)) + 1
  const fimN = texto.indexOf('\n', pos)
  const fim = fimN < 0 ? texto.length : fimN
  return /^\s*o\s+que\s+mudar\s*:/i.test(texto.slice(ini, fim)) ? fim : null
}

/** Põe o texto ditado no fim da linha do "O que mudar:" (com espaço se já houver algo). */
export function inserirNoCampo(texto: string, fimDaLinha: number, falado: string): string {
  const antes = texto.slice(0, fimDaLinha)
  const sep = /:\s*$/.test(antes) ? (antes.endsWith(' ') ? '' : ' ') : ' '
  return antes + sep + falado.trim() + texto.slice(fimDaLinha)
}

/** 116-c/d: os pares ditados entram no quadro; o modelo vazio que estava lá é trocado por eles. */
export function juntarQuadro(texto: string, quadro: string): string {
  const q = quadro.trim()
  if (!q) return texto
  const blocos = texto.replace(/\r\n/g, '\n').split(/\n\s*\n/).filter((b) => temPedido(b))
  return [...blocos.map((b) => b.trim()), q].join('\n\n') + '\n'
}
