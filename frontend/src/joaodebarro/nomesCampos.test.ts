/* ORDEM 080-5: nenhum nome interno na tela e o mesmo dado uma vez só (casos do 9120, sem dado de cliente). */
import { nomeCampo, semJaSabido, semRepetidos } from './nomesCampos'
import { igual, verifica, type Falha } from './testar'
import type { Campo } from './tipos'

const c = (nome: string, valor: Campo['valor']): Campo => ({ nome, valor, origem: valor == null ? 'pendente' : 'documento', fonte: '' } as Campo)

export function testes(): Falha[] {
  const f: Falha[] = []
  igual(f, 'data da ciência', nomeCampo('itcd_data_ciencia'), 'Data da ciência do comunicado')
  igual(f, 'ano da construção', nomeCampo('ano_construcao'), 'Ano da construção')
  igual(f, 'interno desconhecido vira frase', nomeCampo('itcd_prazo_dias'), 'ITCD prazo dias')
  igual(f, 'nome em português fica', nomeCampo('Matrícula atual do imóvel'), 'Matrícula atual do imóvel')
  igual(f, '084-6: área do IPTU', nomeCampo('area_edificada_iptu'), 'Área edificada IPTU')
  const campos = [c('Quadra', '59'), c('quadra', '59'), c('Matrícula atual do imóvel', '100.200'), c('matricula', '100.200'),
    c('Ano de construção / idade da edificação', null), c('ano_construcao', null), c('itcd_data_ciencia', null),
    c('garagem', 'Garagem coberta lateral')]
  const nomes = semRepetidos(campos).map((x) => x.nome)
  igual(f, 'sem repetidos', nomes.join(' | '),
    'Quadra | Matrícula atual do imóvel | Ano de construção / idade da edificação | itcd_data_ciencia | garagem')
  verifica(f, 'nenhum nome interno na tela', semRepetidos(campos).every((x) => !/_/.test(nomeCampo(x.nome))))
  return f
}

export function testesAindaNaoSei(): Falha[] {
  const f: Falha[] = []
  const t = 'Entendi: laudo para o ITCD.\n\nAinda não sei: data da DITCD; a matrícula atualizada.'
  igual(f, 'data-base chegou: some a DITCD', semJaSabido(t, [], '2026-10-28'),
    'Entendi: laudo para o ITCD.\n\nAinda não sei: a matrícula atualizada.')
  igual(f, 'certidão ainda vazia: a matrícula atualizada continua', semJaSabido(t,
    [c('Matrícula atual do imóvel', '100.200'), c('Certidão atualizada da matrícula', null)], '2026-10-28'),
    'Entendi: laudo para o ITCD.\n\nAinda não sei: a matrícula atualizada.')
  igual(f, 'tudo sabido: a frase sai', semJaSabido('Entendi: x.\n\nAinda não sei: data da DITCD; o endereço do imóvel.',
    [c('Endereço do imóvel', 'Rua XV-9, Quadra 59, Lote 02')], '2026-10-28'), 'Entendi: x.')
  igual(f, 'nada chegou: fica igual', semJaSabido(t, [], null), t)
  return f
}
