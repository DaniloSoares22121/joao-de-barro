/* ORDEM 080-5: nomes dos campos para o avaliador (nunca o nome interno) e o mesmo dado sem repetição. */
import type { Campo } from './tipos'

// 080-5: o avaliador nunca vê nome interno ("itcd_data_ciencia"): todo campo com nome em português
const NOMES: Record<string, string> = {
  endereco: 'Endereço', logradouro: 'Rua', quadra: 'Quadra', lote: 'Lote', bairro: 'Bairro', cidade: 'Cidade', uf: 'Estado (UF)',
  cep: 'CEP', inscricao_imobiliaria: 'Inscrição imobiliária', tipologia: 'Tipo do imóvel', matricula: 'Matrícula',
  cartorio: 'Cartório de registro', registro_titulo: 'Registro do título', titulo_aquisitivo: 'Título aquisitivo',
  proprietarios: 'Proprietários', area_terreno_titulo: 'Área do terreno (título)', confrontacoes_titulo: 'Confrontações (título)',
  area_terreno_iptu: 'Área do terreno (IPTU)', area_construida: 'Área construída', fracao_sublote: 'Fração do sublote',
  valor_venal_iptu_2025: 'Valor venal (IPTU 2025)', itcd_comunicado: 'Comunicado do ITCD', itcd_valor_declarado: 'Valor declarado no ITCD',
  itcd_valor_referencia: 'Valor de referência no ITCD', itcd_data_comunicado: 'Data do comunicado do ITCD',
  itcd_data_ciencia: 'Data da ciência do comunicado', fipe_valor_medio: 'Valor médio FIPE', valor_agehab_2014: 'Valor AGEHAB (2014)',
  solicitante: 'Solicitante', solicitante_cpf: 'CPF do solicitante', solicitante_vinculo: 'Vínculo do solicitante',
  comprovante_endereco: 'Comprovante de endereço', ano_construcao: 'Ano da construção',
  indice_mercado_goiania: 'Índice de mercado (Goiânia)', fachada_muro_frontal: 'Fachada e muro frontal', via_publica: 'Via pública',
  medidores: 'Medidores', garagem: 'Garagem', cobertura: 'Cobertura', area_coberta_fundos: 'Área coberta nos fundos',
  acabamentos_internos: 'Acabamentos internos', estado_conservacao_observado: 'Estado de conservação (vistoria)',
  padrao_construtivo_observado: 'Padrão construtivo (vistoria)', tipologia_observada: 'Tipologia (vistoria)',
  banheiros_observados: 'Banheiros (vistoria)',
}
const SIGLAS: Record<string, string> = { itcd: 'ITCD', iptu: 'IPTU', itbi: 'ITBI', cpf: 'CPF', cep: 'CEP', uf: 'UF', fipe: 'FIPE', cnpj: 'CNPJ',
  // 084-6: palavras com acento ("area_edificada_iptu" -> "Área edificada IPTU")
  area: 'área', construida: 'construída', matricula: 'matrícula', titulo: 'título', ciencia: 'ciência', inscricao: 'inscrição',
  conservacao: 'conservação', construcao: 'construção', referencia: 'referência', vistoria: 'vistoria', util: 'útil', fracao: 'fração' }
const ehInterno = (nome: string) => /^[a-z0-9]+(_[a-z0-9]+)+$|^[a-z]+$/.test(nome)

/** Nome do campo para o avaliador: o nome em português; nome interno vira frase ("data_ciencia" → "Data ciência"). */
export function nomeCampo(nome: string): string {
  if (NOMES[nome]) return NOMES[nome]
  if (!ehInterno(nome)) return nome
  const t = nome.split('_').map((w) => SIGLAS[w] ?? w).join(' ')
  return t.charAt(0).toUpperCase() + t.slice(1)
}

const semAcento = (s: string) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
function mesmoValor(a: Campo['valor'], b: Campo['valor']): boolean {
  const n = (v: Campo['valor']) => semAcento(String(v ?? '')).replace(/[^a-z0-9]/g, '')
  return n(a) !== '' && n(a) === n(b)
}

/** 080-5: o mesmo dado guardado duas vezes (com nome interno e com nome em português) aparece uma vez só. */
export function semRepetidos(campos: Campo[]): Campo[] {
  const pt = campos.filter((c) => !ehInterno(c.nome))
  return campos.filter((c) => {
    if (!ehInterno(c.nome)) return true
    const vazio = c.valor === null || c.valor === undefined || c.valor === ''
    if (!vazio) return !pt.some((x) => mesmoValor(x.valor, c.valor))
    // vazio: some se já há um campo em português, também vazio, sobre a mesma coisa ("Ano de construção…")
    const chave = semAcento(nomeCampo(c.nome)).split(' ').filter((w) => w.length > 3)
    return !pt.some((x) => (x.valor === null || x.valor === undefined || x.valor === '')
      && chave.length > 0 && chave.every((w) => semAcento(x.nome).includes(w.slice(0, 5))))
  })
}

const VAGAS = new Set(['data', 'valor', 'qual', 'quais', 'numero', 'nome', 'sobre', 'para', 'como', 'quem', 'onde', 'ainda', 'imovel'])

/** 080-5: no "Entendimento do caso", o "Ainda não sei: …" só lista o que continua faltando. Item já sabido
 * (o dado chegou num campo, ou a data-base já existe para "data da DITCD") sai; sem nada faltando, a frase sai. */
export function semJaSabido(texto: string, campos: Campo[], dataBase?: string | null): string {
  const cheios = campos.filter((c) => c.valor !== null && c.valor !== undefined && c.valor !== '')
  const sabido = semAcento([...cheios.map((c) => `${nomeCampo(c.nome)} ${c.nome} ${c.valor}`),
    dataBase ? 'data-base data base ditcd declaracao do itcd' : ''].join(' ').replace(/_/g, ' '))
  const vazios = campos.filter((c) => !cheios.includes(c)).map((c) => semAcento(`${nomeCampo(c.nome)} ${c.nome}`.replace(/_/g, ' ')))
  return texto.replace(/Ainda não sei: ([^\n]*?)\.(?=\n|$)/, (_t, lista: string) => {
    const resta = lista.split(';').map((x) => x.trim()).filter((item) => {
      const palavras = semAcento(item).split(/[^a-z0-9]+/).filter((w) => w.length > 3 && !VAGAS.has(w))
      const bate = (txt: string) => palavras.length > 0 && palavras.every((w) => txt.includes(w.slice(0, 5)))
      // na dúvida fica: se um campo AINDA VAZIO também fala disso ("Certidão atualizada da matrícula"), não sabemos
      return !(bate(sabido) && !vazios.some(bate))
    })
    return resta.length ? `Ainda não sei: ${resta.join('; ')}.` : ''
  }).replace(/\n{3,}/g, '\n\n').trim()
}
