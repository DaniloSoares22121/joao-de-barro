/* Markdown mínimo (títulos, listas, **negrito**) para exibir pendencias.md sem HTML bruto. */

export interface Trecho { texto: string; negrito: boolean }
export type Bloco =
  | { tipo: 'titulo'; nivel: number; trechos: Trecho[] }
  | { tipo: 'item'; trechos: Trecho[]; impeditiva: boolean }
  | { tipo: 'paragrafo'; trechos: Trecho[] }

export function trechos(linha: string): Trecho[] {
  const out: Trecho[] = []
  const partes = linha.split(/(\*\*[^*]+\*\*)/g)
  for (const p of partes) {
    if (!p) continue
    if (p.startsWith('**') && p.endsWith('**') && p.length > 4) out.push({ texto: p.slice(2, -2), negrito: true })
    else out.push({ texto: p, negrito: false })
  }
  return out
}

const IMPEDITIVA = /^\[impeditiva\]\s*/i

export function parseMarkdown(md: string): Bloco[] {
  const blocos: Bloco[] = []
  for (const bruta of md.split(/\r?\n/)) {
    const ln = bruta.trim()
    if (!ln) continue
    const t = /^(#{1,6})\s+(.*)$/.exec(ln)
    if (t) { blocos.push({ tipo: 'titulo', nivel: t[1].length, trechos: trechos(t[2]) }); continue }
    const li = /^[-*]\s+(.*)$/.exec(ln)
    if (li) {
      const impeditiva = IMPEDITIVA.test(li[1])
      blocos.push({ tipo: 'item', trechos: trechos(li[1].replace(IMPEDITIVA, '')), impeditiva })
      continue
    }
    blocos.push({ tipo: 'paragrafo', trechos: trechos(ln) })
  }
  return blocos
}
