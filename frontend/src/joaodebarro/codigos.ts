/* Códigos sequenciais das tabelas editáveis de Configurações (P3 decisões "D-023", P4 normas "N7"). */

function maior(codigos: string[], re: RegExp): number {
  let m = 0
  for (const c of codigos) {
    const r = re.exec(c.trim())
    if (r) m = Math.max(m, Number(r[1]))
  }
  return m
}

/** Mesmo critério do backend (db.proximo_codigo_decisao): D-001, D-002… */
export function proximoCodigoDecisao(codigos: string[]): string {
  return `D-${String(maior(codigos, /^D-(\d+)$/) + 1).padStart(3, '0')}`
}

/** N1, N2… (as variantes "N5a" contam pelo número). */
export function proximoCodigoNorma(codigos: string[]): string {
  return `N${maior(codigos, /^N(\d+)[a-z]?$/i) + 1}`
}

/** Data de hoje no padrão da P3 (dd/mm/aaaa). */
export function hojeBR(d: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()}`
}
