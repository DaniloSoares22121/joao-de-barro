import { igual, verifica, type Falha } from './testar'
import {
  MSG_ARQUIVO_GRANDE, dadosProcesso, dataISOValida, formVazio, normalizarPin, paraPayload, pinValido, validar,
  validarArquivo, type FormTrabalho,
} from './validacao'

const completo: FormTrabalho = {
  ...formVazio(),
  numero: '121', modalidade: 'OV', finalidade: 'Venda', cliente: 'Fulano de Tal', tipo: 'Casa',
  bairro: 'Jardim Vila Boa', cidade: 'Goiânia', pin_maps: 'https://maps.app.goo.gl/abc123',
  data_base: '2026-10-16', data_vistoria: '2026-10-16', contexto: '',
}

export function testes(): Falha[] {
  const f: Falha[] = []

  igual(f, 'completo → {}', validar(completo), {})

  const semModalidadeEPin = validar({ ...completo, modalidade: '', pin_maps: '' })
  verifica(f, 'sem modalidade → mensagem', !!semModalidadeEPin.modalidade, semModalidadeEPin)
  verifica(f, 'sem pin → mensagem', !!semModalidadeEPin.pin_maps, semModalidadeEPin)
  igual(f, 'só esses dois campos', Object.keys(semModalidadeEPin).sort(), ['modalidade', 'pin_maps'])

  const pinRuim = validar({ ...completo, pin_maps: 'https://exemplo.com/maps/x' })
  verifica(f, 'pin inválido → mensagem', !!pinRuim.pin_maps && pinRuim.pin_maps.includes('inválido'), pinRuim)

  igual(f, 'vazio exige tudo', Object.keys(validar(formVazio('2026-10-20'))).sort(),
    ['bairro', 'cidade', 'cliente', 'data_vistoria', 'finalidade', 'modalidade', 'numero', 'pin_maps', 'tipo'])

  verifica(f, 'número não inteiro', !!validar({ ...completo, numero: '12.5' }).numero)
  verifica(f, 'número zero', !!validar({ ...completo, numero: '0' }).numero)
  verifica(f, 'modalidade desconhecida', !!validar({ ...completo, modalidade: 'XX' }).modalidade)
  verifica(f, 'espaços não contam como preenchido', !!validar({ ...completo, cliente: '   ' }).cliente)
  verifica(f, 'data impossível', !!validar({ ...completo, data_base: '2026-02-30' }).data_base)
  verifica(f, 'contexto é opcional', validar({ ...completo, contexto: '' }).contexto === undefined)

  // pin
  for (const ok of [
    'https://maps.app.goo.gl/abc123', 'maps.app.goo.gl/abc123',
    'https://www.google.com/maps/place/Casa/@-16.6,-49.2,17z', 'https://google.com/maps?q=-16.6,-49.2',
    'https://www.google.com.br/maps/@-16.6,-49.2,15z', 'https://maps.google.com/?q=-16.6,-49.2',
    'https://goo.gl/maps/xyz789',
  ]) verifica(f, `pin válido: ${ok}`, pinValido(ok))
  for (const ruim of [
    '', 'texto qualquer', 'https://google.com/search?q=maps', 'https://evil.com/maps/x',
    'https://maps.app.goo.gl.evil.com/x', 'javascript:alert(1)', 'https://maps.app.goo.gl/',
    'ftp://maps.app.goo.gl/abc', 'https://notgoogle.com/maps/x',
  ]) verifica(f, `pin inválido: ${ruim}`, !pinValido(ruim))

  igual(f, 'normalizarPin acrescenta https', normalizarPin(' maps.app.goo.gl/a '), 'https://maps.app.goo.gl/a')
  igual(f, 'normalizarPin mantém esquema', normalizarPin('http://google.com/maps'), 'http://google.com/maps')

  // datas
  verifica(f, 'data válida', dataISOValida('2026-10-20'))
  verifica(f, 'bissexto', dataISOValida('2028-02-29') && !dataISOValida('2027-02-29'))
  verifica(f, 'formato errado', !dataISOValida('20/10/2026'))

  // payload
  const p = paraPayload({ ...completo, numero: ' 121 ', cliente: ' Fulano ', pin_maps: 'maps.app.goo.gl/x' })
  igual(f, 'payload.numero', p.numero, 121)
  igual(f, 'payload.cliente', p.cliente, 'Fulano')
  igual(f, 'payload.pin_maps', p.pin_maps, 'https://maps.app.goo.gl/x')

  // processo (AMJ / AM)
  igual(f, 'OV sem processo', JSON.stringify(dadosProcesso(completo)), '{}')
  const amj = dadosProcesso({ ...completo, modalidade: 'AMJ', processo_numero: ' 01 ', autor: 'A', reu: '', quesitos: 'Q1' + String.fromCharCode(10) + String.fromCharCode(10) + ' Q2 ' })
  igual(f, 'AMJ quesitos', JSON.stringify(amj), JSON.stringify({ processo_numero: '01', vara_juizo: '', acao: '', partes: { autor: 'A', reu: '' }, quesitos: ['Q1', 'Q2'] }))
  igual(f, 'AM só processo', JSON.stringify(dadosProcesso({ ...completo, modalidade: 'AM', autor: 'X' })), JSON.stringify({ processo_numero: '', vara_juizo: '', acao: '' }))

  // arquivos
  igual(f, '50 MB exato passa', validarArquivo({ size: 50 * 1024 * 1024 }), null)
  igual(f, 'acima de 50 MB', validarArquivo({ size: 50 * 1024 * 1024 + 1 }), MSG_ARQUIVO_GRANDE)

  return f
}
