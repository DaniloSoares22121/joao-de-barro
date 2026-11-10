/* Estatística de exibição dos referenciais escolhidos (valor unitário R$/m²). O valor oficial do
 * laudo vem do backend (etapa "calculo"); aqui só se resume a amostra para a tela. */
import type { Referencial } from './tipos'

export interface EstatUnit { n: number; minimo: number; media: number; maximo: number }

export function unitario(r: Pick<Referencial, 'preco' | 'area_m2'>): number | null {
  if (!r.preco || !r.area_m2 || r.preco <= 0 || r.area_m2 <= 0) return null
  return Math.round((r.preco / r.area_m2) * 100) / 100
}

/** Mín/média/máx do unitário dos referenciais escolhidos (ignora os sem preço ou sem área). */
export function estatisticasUnitarias(refs: Referencial[]): EstatUnit | null {
  const us = refs.filter((r) => r.escolhido).map(unitario).filter((u): u is number => u !== null)
  if (!us.length) return null
  const soma = us.reduce((a, b) => a + b, 0)
  return {
    n: us.length,
    minimo: Math.min(...us),
    media: Math.round((soma / us.length) * 100) / 100,
    maximo: Math.max(...us),
  }
}
