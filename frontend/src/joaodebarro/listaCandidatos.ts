/* Lista de candidatos da pesquisa (escolha do avaliador antes de abrir os anúncios).
 * Lógica pura — testada em logica.test.ts. */
import type { DecisaoCandidato, Referencial } from './tipos'

export const MIN_ESCOLHIDOS = 5

export const decisaoDe = (r: Referencial): DecisaoCandidato => r.decisao ?? ''

/** Mesma regra do servidor em /pesquisa/continuar: "entra" ou manual não descartado. */
export function entraNoLaudo(r: Referencial): boolean {
  const d = decisaoDe(r)
  return d === 'entra' || (r.fonte_coleta === 'manual' && d !== 'descarta')
}

export const totalEntra = (refs: Referencial[]) => refs.filter(entraNoLaudo).length

/** D-056: do mais parecido (mais pontos) para o menos; empate pelo nº; os não recomendados
 * (riscados) vão para o fim — ou somem, se `mostrarRiscados` for falso. */
export function ordenarCandidatos(refs: Referencial[], mostrarRiscados = true): Referencial[] {
  const vis = mostrarRiscados ? refs : refs.filter((r) => !r.nao_recomendado)
  return [...vis].sort((a, b) => Number(!!a.nao_recomendado) - Number(!!b.nao_recomendado)
    || Number(!!a.destoa?.length) - Number(!!b.destoa?.length)        // L201-3: mais novo / padrão superior descem
    || (b.pontos ?? 0) - (a.pontos ?? 0) || a.n - b.n)
}

/** "https://www.zapimoveis.com.br/imovel/…" → "zapimoveis.com.br" (null se não for http/https). */
export function dominio(url: string): string | null {
  try {
    const u = new URL(url)
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return null
    return u.hostname.replace(/^www\./i, '')
  } catch { return null }
}

/** Rótulo do botão de busca: a primeira lista ou mais candidatos. */
export const rotuloBuscar = (qtd: number) => (qtd ? 'Pedir mais referenciais' : 'Pesquisar referenciais')
