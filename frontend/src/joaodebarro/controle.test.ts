/* Testes do controle do avaliador (controle.ts). */
import {
  areaConstruida, br2, decimalBR, deveNotificar, erroEscolha, erroFonte, formDeDados, novoUploadId, payloadEdicao,
  correcoesDaConfirmacao, ehContraditorio, faltaFotoOuDados, previaValor, quemDispersa, rotuloAcao, unitarioDigitado, unitarioNaBase,
} from './controle'
import { STATUS_PARCIAL, STATUS_PRONTO } from './rotulos'
import { igual, verifica, type Falha } from './testar'
import type { DadosTrabalho, Referencial } from './tipos'

const ref = (n: number, preco: number | null, area: number | null): Referencial => ({
  n, link: '', portal: '', bairro: '', tipologia: '', quartos: null, suites: null, lote_m2: null,
  area_m2: area, preco, padrao: '', idade_aparente: '', descricao: '', foto: '', escolhido: false, justificativa: '',
})

export function testes(): Falha[] {
  const f: Falha[] = []

  const a = novoUploadId()
  verifica(f, 'upload id não vazio e único', a.length >= 8 && a !== novoUploadId(), a)

  igual(f, 'decimal 1.234,56', decimalBR('1.234,56'), 1234.56)
  igual(f, 'decimal R$ 5.000', decimalBR('R$ 5.000'), 5000)
  igual(f, 'decimal 2734.5', decimalBR('2734.5'), 2734.5)
  igual(f, 'decimal vazio', decimalBR('abc'), null)

  const arqs = [{ nome: 'iptu.pdf', caminho: 'documento/iptu.pdf', tipo: 'documento' },
    { nome: 'frente.jpg', caminho: 'foto/frente.jpg', tipo: 'foto' }]
  igual(f, 'fonte documento ok', erroFonte('documento', 'documento/iptu.pdf p. 2', arqs), null)
  verifica(f, 'fonte documento sem arquivo', erroFonte('documento', 'o cliente disse', arqs) !== null)
  verifica(f, 'fonte por token exato', erroFonte('documento', 'planta_iptu.pdf', arqs) !== null)
  igual(f, 'vistoria por data', erroFonte('vistoria', 'vistoria do avaliador em 16/10/2026', arqs), null)
  igual(f, 'vistoria por foto', erroFonte('vistoria', 'foto/frente.jpg', arqs), null)
  verifica(f, 'vistoria não aceita documento', erroFonte('vistoria', 'iptu.pdf', arqs) !== null)
  verifica(f, 'fonte vazia', erroFonte('documento', ' ', arqs) !== null)

  const refs = [ref(1, 100000, 100), ref(2, 300000, 100), ref(3, null, 100)]
  verifica(f, 'escolha vazia', erroEscolha(new Set(), refs, '') !== null)
  igual(f, 'escolha sem unitário', erroEscolha(new Set([1, 2]), refs, ''), null)
  igual(f, 'unitário dentro', erroEscolha(new Set([1, 2]), refs, '2.000,00'), null)
  verifica(f, 'unitário fora', erroEscolha(new Set([1, 2]), refs, '3500') !== null)
  verifica(f, 'só referencial sem preço', erroEscolha(new Set([3]), refs, '') !== null)

  const campo = (nome: string, valor: string | number, origem: 'documento' | 'vistoria' | 'inferido') => ({ nome, valor, origem })
  igual(f, 'área construída documento antes de vistoria', areaConstruida([
    campo('Área construída (vistoria)', '350,00', 'vistoria'), campo('Área edificada', '364,00 m²', 'documento')]), 364)
  igual(f, 'área construída número', areaConstruida([campo('area_construida', 198, 'vistoria')]), 198)
  igual(f, 'área ignora terreno e inferido', areaConstruida([
    campo('Área construída do lote', 500, 'documento'), campo('Área construída', 120, 'inferido')]), null)
  igual(f, 'prévia arredonda ao milhar', previaValor(364, 2735.85, 10),
    { calculado: 995849.4, adotado: 996000, min: 896400, max: 1095600 })
  igual(f, 'R$/m² digitado', unitarioDigitado('650.000,00', '198,00'), 3282.83)
  igual(f, 'R$/m² sem área', unitarioDigitado('650.000,00', ''), null)
  igual(f, 'br2', br2(2735.8), '2.735,80')

  igual(f, 'rótulo foto', rotuloAcao({ tipo: 'enviar_arquivo', tipo_arquivo: 'foto' }), 'Enviar fotos')
  igual(f, 'rótulo campo', rotuloAcao({ tipo: 'editar_campo', campo: 'quadra' }), 'Editar quadra')
  igual(f, 'rótulo coletor', rotuloAcao({ tipo: 'ligar_coletor' }), 'Ligar o programa do mapa')

  const d: DadosTrabalho = {
    id: 'j1', numero: 7, modalidade: 'AMJ', finalidade: 'Judicial', cliente: 'X', tipo: 'Casa', bairro: 'B',
    cidade: 'C', pin_maps: 'https://maps.app.goo.gl/abc', data_base: '2026-10-01', data_vistoria: '2026-10-02',
    contexto: '', processo_numero: '123', vara_juizo: '1ª Vara', acao: 'Divórcio',
    partes: { autor: 'A', reu: 'R' }, quesitos: ['q1', 'q2'],
  }
  const form = formDeDados(d)
  igual(f, 'form quesitos', form.quesitos, 'q1\nq2')
  const p = payloadEdicao(form) as Record<string, unknown>
  verifica(f, 'edição sem número', !('numero' in p), p)
  igual(f, 'edição partes', p.partes, { autor: 'A', reu: 'R' })

  verifica(f, 'notifica ao terminar', deveNotificar('executando', STATUS_PRONTO))
  verifica(f, 'não notifica final→final', !deveNotificar(STATUS_PARCIAL, STATUS_PRONTO))
  verifica(f, 'não notifica na 1ª carga', !deveNotificar(undefined, STATUS_PRONTO))
  // ORDEM 021: quem espalha a amostra (9118 sem o nº 8) — mesmo texto do servidor
  const a9118: Array<[number, number, number]> = [[1, 6000000, 2170], [2, 4600000, 1800], [3, 4800000, 1800],
    [4, 4670000, 2336], [5, 3700000, 1670], [6, 5100000, 1650], [9, 7149000, 2836], [10, 4500000, 1300]]
  igual(f, 'quem dispersa 9118', quemDispersa(a9118.map(([n, p, a]) => ({ n, u: p / a }))),
    'Quem mais espalha a amostra: nº 10 (R$ 3.461,54/m², o mais alto): sem ele, 14,1%; '
    + 'nº 4 (R$ 1.999,14/m², o mais baixo): sem ele, 14,9%')
  igual(f, 'quem dispersa < 4', quemDispersa([{ n: 1, u: 1 }, { n: 2, u: 2 }, { n: 3, u: 9 }]), '')
  igual(f, 'anúncio contraditório (D-010)', ehContraditorio({ observacao: 'x; ANÚNCIO CONTRADITÓRIO (D-010): preço' }), true)
  igual(f, 'anúncio comum', ehContraditorio({ observacao: 'enviado pelo avaliador' }), false)
  igual(f, 'sem foto: faltam foto/dados', faltaFotoOuDados(ref(1, 1, 1)), true)
  igual(f, 'com foto e sem "a conferir": completo', faltaFotoOuDados({ ...ref(1, 1, 1), foto: 'mercado/x.jpg' }), false)
  igual(f, 'com foto mas "a conferir": faltam', faltaFotoOuDados({ ...ref(1, 1, 1), foto: 'm/x.jpg',
    descricao: 'Padrão e idade a conferir no anúncio.' }), true)
  igual(f, 'unitário na base terreno', unitarioNaBase({ ...ref(1, 900000, 300), lote_m2: 900 }, 'terreno'), 1000)
  igual(f, 'unitário na base construída', unitarioNaBase({ ...ref(1, 900000, 300), lote_m2: 900 }, 'construida'), 3000)
  igual(f, 'terreno sem lote', unitarioNaBase(ref(1, 900000, 300), 'terreno'), null)
  // ORDEM 028-1: troca de amostra e de base pedem a pergunta; sem troca, nada
  const sem = correcoesDaConfirmacao({ inicial: [1, 2, 3], marcados: [3, 2, 1], baseAntes: 'construida', baseDepois: 'construida' })
  igual(f, 'sem troca, sem pergunta', sem.length, 0)
  const tr = correcoesDaConfirmacao({ inicial: [1, 2, 3, 9, 11, 13, 14], marcados: [1, 6, 10, 11, 14, 15],
    baseAntes: 'terreno', baseDepois: 'construida' })
  igual(f, 'troca de amostra', tr[0]?.tipo, 'amostra')
  igual(f, 'troca de amostra: o que mudou', tr[0]?.depois, 'nº 1, 6, 10, 11, 14, 15 (tirou 2, 3, 9, 13) (pôs 6, 10, 15)')
  igual(f, 'troca de base', tr[1]?.chave, 'base do cálculo')
  igual(f, 'base: antes/depois', `${tr[1]?.antes} -> ${tr[1]?.depois}`, 'área total do terreno -> só área construída')
  const ar = correcoesDaConfirmacao({ inicial: [1], marcados: [1], baseAntes: null, baseDepois: 'construida',
    areaDoc: { campo: 'IPTU', valor: 6363.65 }, areaEscolhida: { campo: 'Galpão 01', valor: 1982.96 } })
  igual(f, 'área diferente da de documento', ar.map((x) => x.chave).join(), 'área do imóvel no cálculo')

  return f
}
