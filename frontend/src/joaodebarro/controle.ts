/* Controle do avaliador sobre um trabalho (edição de campos, escolha de referenciais,
 * pendências acionáveis, edição do trabalho, aviso de fim). Lógica pura — controle.test.ts. */
import { unitario } from './calculo'
import { STATUS_FINAIS } from './rotulos'
import type { AcaoPendencia, Campo, DadosTrabalho, Referencial } from './tipos'
import { formVazio, hojeISO, paraPayload, type FormTrabalho } from './validacao'

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

/** 1234.5 → "1.234,50" (para pré-preencher campos que o servidor lê em pt-BR). */
export function br2(x: number): string {
  return x.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

const semAcento = (s: string) => s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()

/** Espelho de selecao.area_construida do servidor: campo com "area" e "constru"/"edificad"
 * (sem terreno/lote), origem documento antes de vistoria. null se não houver. */
export function areaConstruida(campos: ReadonlyArray<Pick<Campo, 'nome' | 'valor' | 'origem'>>,
                               tipo = ''): number | null {
  // apartamento: a unidade é a área PRIVATIVA (igual ao servidor, selecao._areas_construidas)
  if (/apart|apto|flat|kitnet|cobertura/.test(semAcento(tipo))) {
    const priv = areaPor(campos, (n) => n.includes('area') && n.includes('privativ'))
    if (priv !== null) return priv
  }
  return areaPor(campos, (n) => n.includes('area') && (n.includes('constru') || n.includes('edificad')))
}

function areaPor(campos: ReadonlyArray<Pick<Campo, 'nome' | 'valor' | 'origem'>>,
                 casa: (nomeSemAcento: string) => boolean): number | null {
  const achadas: { v: number; doc: boolean }[] = []
  for (const c of campos) {
    const n = semAcento(c.nome)
    if (!casa(n)) continue
    if (['terreno', 'lote', 'sublote'].some((x) => n.includes(x))) continue
    if (c.origem !== 'documento' && c.origem !== 'vistoria') continue
    const v = typeof c.valor === 'number' ? c.valor : decimalBR((/-?\d[\d.]*(?:,\d+)?/.exec(String(c.valor ?? '')) ?? [''])[0])
    if (v !== null && Number.isFinite(v) && v > 0) achadas.push({ v, doc: c.origem === 'documento' })
  }
  const doc = achadas.find((a) => a.doc)
  return (doc ?? achadas[0])?.v ?? null
}

const cent = (x: number) => Math.round((x + Number.EPSILON) * 100) / 100

/** Prévia do valor como o servidor calcula (calculo.py): área × unitário, valor adotado
 * arredondado ao milhar mais próximo, faixa ± % sobre o adotado (arredondada ao real). */
export function previaValor(area: number, unit: number, faixaPct: number) {
  const calculado = cent(area * unit)
  const adotado = Math.round(calculado / 1000) * 1000
  const f = faixaPct / 100
  return { calculado, adotado, min: Math.round(adotado * (1 - f)), max: Math.round(adotado * (1 + f)) }
}

/** ORDEM 010: estatística da amostra escolhida — nº, mínimo, máximo, média e CV (desvio
 * padrão amostral ÷ média; null com menos de 2). */
export function estatisticaAmostra(us: readonly number[]) {
  if (!us.length) return null
  const media = us.reduce((a, b) => a + b, 0) / us.length
  const dp = us.length >= 2 ? Math.sqrt(us.reduce((a, b) => a + (b - media) ** 2, 0) / (us.length - 1)) : null
  return { n: us.length, min: Math.min(...us), max: Math.max(...us), media: cent(media),
           cv: dp !== null && media > 0 ? dp / media : null }
}

const RE_SUPERIOR = /piscina|sauna|alto padr|luxo|hidromassagem|gourmet|todas? (as )?su[ií]tes|nunca habitad|\bnovo\b|lan[cç]amento|condom[ií]nio com (lazer|piscina)/i

const pct1 = (x: number) => `${(x * 100).toFixed(1).replace('.', ',')}%`
const brl2 = (x: number) => x.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function cvDe(xs: readonly number[]): number {
  const m = xs.reduce((a, b) => a + b, 0) / xs.length
  return Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / (xs.length - 1)) / m
}

/** ORDEM 021 (igual ao servidor, routes._quem_dispersa): quem espalha a amostra — até 2
 *  referenciais que, tirados um de cada vez, mais baixam o CV, com o CV sem cada um. */
export function quemDispersa(pares: ReadonlyArray<{ n: number; u: number }>): string {
  if (pares.length < 4) return ''
  let alto = pares[0], baixo = pares[0]
  for (const p of pares) {
    if (p.u > alto.u) alto = p
    if (p.u < baixo.u) baixo = p
  }
  const sem = pares.map((p) => ({ p, cv: cvDe(pares.filter((q) => q.n !== p.n).map((q) => q.u)) }))
  sem.sort((a, b) => a.cv - b.cv)
  return 'Quem mais espalha a amostra: ' + sem.slice(0, 2).map(({ p, cv }) =>
    `nº ${p.n} (R$ ${brl2(p.u)}/m²${p.n === alto.n ? ', o mais alto' : p.n === baixo.n ? ', o mais baixo' : ''}): sem ele, ${pct1(cv)}`).join('; ')
}

/** ORDEM 021: R$/m² do referencial na base do cálculo (terreno: preço ÷ área do lote). */
export function unitarioNaBase(r: Pick<Referencial, 'preco' | 'area_m2' | 'lote_m2'>,
                               base: 'construida' | 'terreno' | null): number | null {
  return base === 'terreno' ? unitario({ preco: r.preco, area_m2: r.lote_m2 }) : unitario(r)
}

/** ORDEM 034-1 / D-010: o anúncio se contradiz (preço ou área diferentes na ficha e no texto). */
export function ehContraditorio(r: Pick<Referencial, 'observacao'>): boolean {
  return /contradit/i.test(r.observacao ?? '')
}

/** ORDEM 010: alertas que pedem "Confirmo mesmo assim, porque…" (mesmas regras do servidor). */
export function alertasValor(escolhidos: readonly Referencial[], unit: number | null,
                             est: ReturnType<typeof estatisticaAmostra>,
                             base: 'construida' | 'terreno' | null = 'construida'): string[] {
  const al: string[] = []
  if (!est) return al
  if (est.cv !== null && est.cv > 0.15) {
    // CV do aviso com o unitário sem arredondar (igual ao servidor)
    const pares = escolhidos.flatMap((r) => {
      const area = base === 'terreno' ? r.lote_m2 : r.area_m2
      return r.preco && area && r.preco > 0 && area > 0 ? [{ n: r.n, u: r.preco / area }] : []
    })
    const quem = quemDispersa(pares)
    al.push(`Amostra dispersa: coeficiente de variação de ${pct1(est.cv)} (acima de 15%).${quem ? ` ${quem}.` : ''}`)
  }
  // ORDEM 034-1 / D-010: anúncio que se contradiz (preço ou área) — igual ao servidor
  const contra = escolhidos.filter(ehContraditorio).map((r) => r.n)
  if (contra.length) al.push(`${contra.length === 1 ? 'Anúncio contraditório' : 'Anúncios contraditórios'} (D-010): nº ${contra.join(', ')}.`)
  const sup = escolhidos.filter((r) => r.nao_recomendado || (r.observacao ?? '').includes('indícios de padrão superior')
    || /alto|superior|luxo/i.test(r.padrao ?? '') || RE_SUPERIOR.test(`${r.descricao ?? ''} ${r.titulo ?? ''}`)).map((r) => r.n)
  if (sup.length) al.push(`${sup.length === 1 ? 'Escolhido' : 'Escolhidos'} com indício de padrão superior ou não recomendado: nº ${sup.join(', ')}.`)
  const nao = escolhidos.filter((r) => r.fonte_coleta !== 'manual' && r.fonte_coleta !== 'avaliador'
    && (r.bloqueado || !r.coletado)).map((r) => r.n)
  if (nao.length) al.push(`${nao.length === 1 ? 'Escolhido não conferido' : 'Escolhidos não conferidos'} — anúncio não aberto ou bloqueado: nº ${nao.join(', ')}.`)
  if (unit !== null) {
    if (Math.abs(unit - est.min) < 0.01) al.push('Unitário adotado no MÍNIMO do intervalo da amostra.')
    else if (Math.abs(unit - est.max) < 0.01) al.push('Unitário adotado no MÁXIMO do intervalo da amostra.')
    const dif = est.media ? Math.abs(unit - est.media) / est.media : 0
    if (dif > 0.15) al.push(`Unitário ${(dif * 100).toFixed(1).replace('.', ',')}% diferente da média da amostra (acima de 15%).`)
  }
  return al
}

/** R$/m² de um anúncio digitado no formulário (preço ÷ área), ou null. */
export function unitarioDigitado(preco: string, area: string): number | null {
  const p = decimalBR(preco)
  const a = decimalBR(area)
  if (p === null || a === null || p <= 0 || a <= 0) return null
  return cent(p / a)
}

/** Rótulo do botão de cada ação de pendência. */
export function rotuloAcao(a: AcaoPendencia): string {
  switch (a.tipo) {
    case 'enviar_arquivo':
      return a.tipo_arquivo === 'foto' ? 'Enviar fotos'
        : a.tipo_arquivo === 'solicitante' ? 'Enviar documento do solicitante'
        : a.tipo_arquivo === 'documento' ? 'Enviar documento' : 'Enviar arquivos'
    case 'editar_campo': return `Editar ${a.campo}`
    case 'ligar_coletor': return 'Ligar o programa do mapa'
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
    contexto: d.contexto ?? '', obs_vistoria: d.obs_vistoria ?? '', checklist_vistoria: d.checklist_vistoria ?? '',
    data_emissao: d.data_emissao || hojeISO(), visita_por: d.visita_por ?? '', objeto_parte: d.objeto_parte ?? '', processo_numero: d.processo_numero ?? '', vara_juizo: d.vara_juizo ?? '',
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


/** ORDEM 028-1 (F2 da 026): correções do "Confirmar valor" que pedem a pergunta "vale só para
 *  este laudo ou para todos os seus?" — troca de amostra (tirou/pôs referencial), troca da base
 *  do cálculo e área diferente da de documento. */
export function correcoesDaConfirmacao(o: {
  inicial: readonly number[]; marcados: readonly number[]
  baseAntes: 'construida' | 'terreno' | null; baseDepois: 'construida' | 'terreno' | null
  areaDoc?: { campo: string; valor: number } | null; areaEscolhida?: { campo: string; valor: number } | null
}): { tipo: 'amostra' | 'area'; chave: string; antes: string; depois: string }[] {
  const out: { tipo: 'amostra' | 'area'; chave: string; antes: string; depois: string }[] = []
  const a = [...o.inicial].sort((x, y) => x - y), d = [...o.marcados].sort((x, y) => x - y)
  if (a.join() !== d.join()) {
    const tirou = a.filter((n) => !d.includes(n)), pos = d.filter((n) => !a.includes(n))
    out.push({ tipo: 'amostra', chave: 'amostra (referenciais escolhidos)', antes: `nº ${a.join(', ')}`,
      depois: `nº ${d.join(', ')}` + (tirou.length ? ` (tirou ${tirou.join(', ')})` : '') + (pos.length ? ` (pôs ${pos.join(', ')})` : '') })
  }
  const nome = (b: string | null) => (b === 'terreno' ? 'área total do terreno' : 'só área construída')
  if (o.baseAntes && o.baseDepois && o.baseAntes !== o.baseDepois) {
    out.push({ tipo: 'area', chave: 'base do cálculo', antes: nome(o.baseAntes), depois: nome(o.baseDepois) })
  }
  if (o.areaDoc && o.areaEscolhida && o.areaDoc.campo !== o.areaEscolhida.campo) {
    out.push({ tipo: 'area', chave: 'área do imóvel no cálculo', antes: `${o.areaDoc.campo}: ${o.areaDoc.valor} m²`,
      depois: `${nome(o.baseDepois)} — ${o.areaEscolhida.campo}: ${o.areaEscolhida.valor} m²` })
  }
  return out
}

/** ORDEM 029-5: referencial escolhido que ainda precisa da página do anúncio aberta pelo
 * avaliador (o Coletor não abre: Cloudflare) — sem foto principal ou com dado "a conferir". */
export function faltaFotoOuDados(r: Pick<Referencial, 'foto' | 'descricao' | 'observacao' | 'justificativa'>): boolean {
  return !(r.foto || '').trim() || /a conferir/i.test(`${r.descricao || ''} ${r.observacao || ''}`)
}
