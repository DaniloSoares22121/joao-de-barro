/* ORDEM 023-A: tela do trabalho em caixas sanfona — lógica pura (testes em logica.test.ts). */

/** Selo da caixa fechada: "Sua vez" (espera o avaliador), pendências, OK ou aguardando. */
export type Selo = 'vez' | 'pendencias' | 'ok' | 'aguardando' | null

export interface CaixaInfo { id: string; selo: Selo }

export const TEXTO_SELO: Record<Exclude<Selo, null>, string> = {
  vez: 'Sua vez', pendencias: 'Pendências', ok: 'OK', aguardando: 'Aguardando',
}

const PEDE_ATENCAO = (c: CaixaInfo) => c.selo === 'vez' || c.selo === 'pendencias'

/** A caixa que abre sozinha: a primeira que espera o avaliador ("Sua vez"). */
export function caixaDaVez(caixas: readonly CaixaInfo[]): string | null {
  return caixas.find((c) => c.selo === 'vez')?.id ?? null
}

/** "Próxima →": a próxima (depois da atual) que pede atenção; se nenhuma, a seguinte na ordem;
 *  na última, volta ao começo procurando a que pede atenção. null se não houver outra. */
export function proximaCaixa(caixas: readonly CaixaInfo[], atual: string): string | null {
  const i = caixas.findIndex((c) => c.id === atual)
  const depois = caixas.slice(i + 1)
  const antes = caixas.slice(0, Math.max(i, 0))
  return (depois.find(PEDE_ATENCAO) ?? depois[0] ?? antes.find(PEDE_ATENCAO) ?? null)?.id ?? null
}

/** Caixa aberta ao entrar: a lembrada (se ainda existe), senão a da vez, senão nenhuma.
 *  "Sua vez" nova (o trabalho mudou de etapa) vence a lembrada. */
export function caixaInicial(caixas: readonly CaixaInfo[], lembrada: string | null): string | null {
  const vez = caixaDaVez(caixas)
  if (vez) return vez
  return lembrada && caixas.some((c) => c.id === lembrada) ? lembrada : null
}

/** Resumo de 1 linha do "Cálculo do valor". */
export function resumoCalculo(previa: { valor_adotado?: string | null; pendente?: boolean } | null,
                              vigente: { valor_adotado: string } | null,
                              moeda: (v: string) => string): string {
  if (previa && previa.pendente) return 'escolha a base e a área para ver o valor'
  if (previa && previa.valor_adotado) return `${moeda(previa.valor_adotado)} (prévia)`
  if (vigente) return moeda(vigente.valor_adotado)
  return 'aparece depois da seleção'
}

/** Resumo de "Candidatos a referencial". */
export function resumoCandidatos(total: number, escolhidos: number): string {
  if (!total) return 'nenhum candidato ainda'
  return `${total} candidato${total === 1 ? '' : 's'} · ${escolhidos} escolhido${escolhidos === 1 ? '' : 's'}`
}
