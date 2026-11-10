/* Testes da lógica pura: rótulos, backoff de reconexão, linha do tempo, estatística do cálculo. */
import { estatisticasUnitarias, unitario } from './calculo'
import { estadoDasEtapas, type EventoMin } from './etapas'
import { ATRASOS_MS, atrasoReconexao } from './reconexao'
import {
  ETAPAS, STATUS_BLOQUEADO, STATUS_PARCIAL, STATUS_PRONTO, dataBR, ehFinal, etapaRotulo, modalidade, moeda,
  statusInfo, textoPendencia, textoResumoIA,
} from './rotulos'
import { hojeBR, proximoCodigoDecisao, proximoCodigoNorma } from './codigos'
import { parseMarkdown } from './markdown'
import { igual, verifica, type Falha } from './testar'
import type { Referencial } from './tipos'

const ev = (id: number, etapa: string, nivel: string, msg = '', dados?: unknown): EventoMin =>
  ({ id, etapa, nivel, msg, dados })

const ref = (n: number, preco: number | null, area: number | null, escolhido: boolean): Referencial => ({
  n, link: '', portal: '', bairro: '', tipologia: '', quartos: null, suites: null, lote_m2: null,
  area_m2: area, preco, padrao: '', idade_aparente: '', descricao: '', foto: '', escolhido, justificativa: '',
})

export function testes(): Falha[] {
  const f: Falha[] = []

  // rótulos
  igual(f, 'ordem das etapas', ETAPAS.map((e) => e.id),
    ['triagem', 'extracao', 'pesquisa', 'selecao', 'calculo', 'redacao', 'montagem', 'revisao', 'entrega'])
  igual(f, 'OV', modalidade('OV'), 'Opinião de Valor')
  igual(f, 'resumo IA', textoResumoIA({ chamadas: 12, custo_usd: 0.8412, tempo_s: 200.4 }), '12 chamadas de IA · US$ 0,84 · 3 min 20 s')
  igual(f, 'resumo IA 1', textoResumoIA({ chamadas: 1, custo_usd: 0, tempo_s: 9 }), '1 chamada de IA · US$ 0,00 · 9 s')
  igual(f, 'AM', modalidade('AM'), 'PTAM')
  igual(f, 'AM_GARANTIA', modalidade('AM_GARANTIA'), 'PTAM — Garantia')
  igual(f, 'AMJ', modalidade('AMJ'), 'PTAM Judicial')
  igual(f, 'status finais exatos', [STATUS_PRONTO, STATUS_PARCIAL, STATUS_BLOQUEADO],
    ['PRONTO PARA REVISÃO', 'PARCIAL — PENDÊNCIAS', 'BLOQUEADO'])
  igual(f, 'statusInfo mantém o texto', statusInfo(STATUS_PARCIAL).texto, 'PARCIAL — PENDÊNCIAS')
  igual(f, 'pendência com etapa', textoPendencia('selecao: áreas divergentes'), 'Seleção de referenciais: áreas divergentes')
  igual(f, 'pendência sem etapa', textoPendencia('campo essencial pendente: Quadra'), 'campo essencial pendente: Quadra')
  verifica(f, 'ehFinal', ehFinal(STATUS_BLOQUEADO) && !ehFinal('executando') && !ehFinal(undefined))
  igual(f, 'etapaRotulo coletor', etapaRotulo('aguardando_coletor'), 'Aguardando o Coletor')
  igual(f, 'dataBR', dataBR('2026-10-20'), '20/10/2026')
  verifica(f, 'moeda pt-BR', moeda('123456').replace(/\s/g, ' ').includes('123.456,00'), moeda('123456'))
  igual(f, 'moeda vazia', moeda(null), '—')

  // backoff
  igual(f, 'agenda', [...ATRASOS_MS], [1000, 2000, 5000, 10000])
  igual(f, 'tentativas 0..6', [0, 1, 2, 3, 4, 5, 6].map(atrasoReconexao), [1000, 2000, 5000, 10000, 10000, 10000, 10000])
  igual(f, 'negativo/NaN → 1 s', [atrasoReconexao(-3), atrasoReconexao(NaN)], [1000, 1000])

  // linha do tempo
  const est = (job: { etapa: string; status: string }, es: EventoMin[]) =>
    Object.fromEntries(estadoDasEtapas(job, es).map((l) => [l.id, l.estado]))

  const nova = est({ etapa: 'nova', status: 'pendente' }, [])
  igual(f, 'nova: tudo pendente', Object.values(nova).every((s) => s === 'pendente'), true)

  const rodando = est({ etapa: 'selecao', status: 'executando' }, [])
  igual(f, 'andamento', [rodando.triagem, rodando.pesquisa, rodando.selecao, rodando.calculo],
    ['concluida', 'concluida', 'rodando', 'pendente'])

  const coletor = est({ etapa: 'aguardando_coletor', status: 'aguardando' }, [])
  igual(f, 'aguardando coletor', [coletor.extracao, coletor.pesquisa, coletor.selecao],
    ['concluida', 'aguardando_coletor', 'pendente'])

  const fila = estadoDasEtapas({ etapa: 'extracao', status: 'pendente' }, []).find((l) => l.id === 'extracao')
  igual(f, 'na fila', [fila?.estado, fila?.mensagem], ['pendente', 'Na fila'])

  const completos = ETAPAS.map((e, i) => ev(i + 1, e.id, 'resultado'))
  const pronto = est({ etapa: 'entrega', status: STATUS_PRONTO }, completos)
  igual(f, 'final pronto: tudo concluído', Object.values(pronto).every((s) => s === 'concluida'), true)

  const bloq = est({ etapa: 'entrega', status: STATUS_BLOQUEADO }, [ev(1, 'triagem', 'resultado'), ev(2, 'entrega', 'resultado')])
  igual(f, 'bloqueado: só triagem e entrega', [bloq.triagem, bloq.extracao, bloq.entrega], ['concluida', 'pendente', 'concluida'])

  const erro = estadoDasEtapas({ etapa: 'entrega', status: STATUS_PARCIAL }, [
    ev(1, 'triagem', 'resultado'), ev(2, 'extracao', 'inicio'), ev(3, 'extracao', 'erro', 'IA falhou: x'),
    ev(4, 'entrega', 'resultado'),
  ]).find((l) => l.id === 'extracao')
  igual(f, 'erro aberto', [erro?.estado, erro?.mensagem], ['erro', 'IA falhou: x'])

  const erroSuperado = est({ etapa: 'entrega', status: STATUS_PRONTO }, [
    ev(1, 'montagem', 'erro', 'PDF não gerado'), ev(2, 'montagem', 'resultado'), ev(3, 'entrega', 'resultado'),
  ])
  igual(f, 'erro seguido de resultado não conta', erroSuperado.montagem, 'concluida')

  // volta (correção): resultados/erros anteriores à barreira não valem
  const comVolta = est({ etapa: 'selecao', status: 'executando' }, [
    ev(1, 'selecao', 'inicio'), ev(2, 'selecao', 'erro', 'velho'), ev(3, 'orquestrador', 'volta', 'corr', { etapa: 'selecao' }),
  ])
  igual(f, 'erro antigo ignorado após volta', comVolta.selecao, 'rodando')

  const avisos = estadoDasEtapas({ etapa: 'selecao', status: 'executando' }, [
    ev(1, 'selecao', 'aviso', 'antigo'), ev(2, 'selecao', 'inicio'), ev(3, 'selecao', 'aviso', 'novo'),
  ]).find((l) => l.id === 'selecao')
  igual(f, 'só avisos da execução atual', avisos?.avisos, ['novo'])

  // estatística
  igual(f, 'unitário', unitario(ref(1, 500000, 100, true)), 5000)
  igual(f, 'unitário sem área', unitario(ref(1, 500000, null, true)), null)
  const st = estatisticasUnitarias([
    ref(1, 400000, 100, true), ref(2, 600000, 100, true), ref(3, 900000, 100, false), ref(4, 500000, null, true),
  ])
  igual(f, 'só escolhidos com preço e área', st, { n: 2, minimo: 4000, media: 5000, maximo: 6000 })
  igual(f, 'sem escolhidos', estatisticasUnitarias([ref(1, 1, 1, false)]), null)

  // markdown simples (pendencias.md)
  const md = parseMarkdown(
    ['# Pendências — PARCIAL — PENDÊNCIAS', '', '- [impeditiva] sem fotos', '- aviso **leve** aqui', 'Texto solto'].join('\n'))
  igual(f, 'md: tipos', md.map((b) => b.tipo), ['titulo', 'item', 'item', 'paragrafo'])
  igual(f, 'md: impeditiva', md.map((b) => (b.tipo === 'item' ? b.impeditiva : null)), [null, true, false, null])
  const item2 = md[2]
  igual(f, 'md: negrito', item2.tipo === 'item' ? item2.trechos : [],
    [{ texto: 'aviso ', negrito: false }, { texto: 'leve', negrito: true }, { texto: ' aqui', negrito: false }])
  igual(f, 'md: vazio', parseMarkdown(''), [])

  // códigos da configuração
  igual(f, 'próxima decisão', proximoCodigoDecisao(['D-000', 'D-022', 'D-009']), 'D-023')
  igual(f, 'primeira decisão', proximoCodigoDecisao([]), 'D-001')
  igual(f, 'próxima norma', proximoCodigoNorma(['N1', 'N5a', 'N6']), 'N7')
  igual(f, 'hojeBR', hojeBR(new Date(2026, 9, 5)), '05/10/2026')

  return f
}
