/* Testes do controle do avaliador (controle.ts). */
import {
  decimalBR, deveNotificar, erroEscolha, erroFonte, formDeDados, novoUploadId, payloadEdicao, rotuloAcao,
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

  igual(f, 'rótulo foto', rotuloAcao({ tipo: 'enviar_arquivo', tipo_arquivo: 'foto' }), 'Enviar fotos')
  igual(f, 'rótulo campo', rotuloAcao({ tipo: 'editar_campo', campo: 'quadra' }), 'Editar quadra')
  igual(f, 'rótulo coletor', rotuloAcao({ tipo: 'ligar_coletor' }), 'Ligar o Coletor')

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
  return f
}
