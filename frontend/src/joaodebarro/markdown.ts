/* Markdown mínimo (títulos, listas, **negrito**) para exibir pendencias.md sem HTML bruto. */

export interface Trecho { texto: string; negrito: boolean; codigo?: boolean; link?: string }
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

/** Inline mais completo (textos da config, ex.: normas P4): **negrito**, `código`, [texto](url)
 * e links soltos http(s). Só links http(s) viram link; o resto vira texto. Quebras ficam no texto. */
export function trechosRicos(texto: string): Trecho[] {
  const out: Trecho[] = []
  const re = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|(https?:\/\/[^\s)<>]+)/g
  let ult = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(texto)) !== null) {
    if (m.index > ult) out.push({ texto: texto.slice(ult, m.index), negrito: false })
    if (m[1] !== undefined) out.push({ texto: m[1], negrito: true })
    else if (m[2] !== undefined) out.push({ texto: m[2], negrito: false, codigo: true })
    else if (m[3] !== undefined) {
      out.push(/^https?:\/\//i.test(m[4]) ? { texto: m[3], negrito: false, link: m[4] } : { texto: m[3], negrito: false })
    } else out.push({ texto: m[5], negrito: false, link: m[5] })
    ult = m.index + m[0].length
  }
  if (ult < texto.length) out.push({ texto: texto.slice(ult), negrito: false })
  return out
}

const IMPEDITIVA =/^\[impeditiva\]\s*/i

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
