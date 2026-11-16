/* Testes da lógica pura: rótulos, backoff de reconexão, linha do tempo, estatística do cálculo. */
import { estatisticasUnitarias, unitario } from './calculo'
import { estadoDasEtapas, type EventoMin } from './etapas'
import { ATRASOS_MS, atrasoReconexao } from './reconexao'
import {
  ETAPAS, STATUS_AGUARDANDO_AVALIADOR, aguardandoEscolha, STATUS_BLOQUEADO, STATUS_PARCIAL, STATUS_PRONTO, dataBR, ehFinal, emExecucao,
  etapaRotulo, modalidade, moeda, statusInfo, textoPendencia, textoResumoIA,
  STATUS_ERRO_TECNICO, TEXTO_ERRO_TECNICO, etapaDoErro, msgSegura,
} from './rotulos'
import { hojeBR, proximoCodigoDecisao, proximoCodigoNorma } from './codigos'
import { dominio, ordenarCandidatos, rotuloBuscar, totalEntra } from './listaCandidatos'
import { parseMarkdown, trechosRicos } from './markdown'
import { andar, contarResolvidos, pedidoVago } from './ListaErros'
import { MODELO_AJUSTE, campoOQueNoCursor, inserirNoCampo, juntarQuadro, maisUmPar, temPedido } from './pedidosRevisao'
import { plural, resumoDadosExtraidos } from './rotulos'
import { caixaDaVez, caixaInicial, proximaCaixa, resumoCalculo, resumoCandidatos } from './caixas'
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
  igual(f, 'statusInfo mantém o texto', statusInfo(STATUS_PARCIAL).texto, 'Laudo gerado com pendências')
  igual(f, 'pendência com etapa', textoPendencia('selecao: áreas divergentes'), 'Seleção de referenciais: áreas divergentes')
  igual(f, 'pendência sem etapa', textoPendencia('campo essencial pendente: Quadra'), 'campo essencial pendente: Quadra')
  verifica(f, 'ehFinal', ehFinal(STATUS_BLOQUEADO) && !ehFinal('executando') && !ehFinal(undefined))
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

  const avaliador = est({ etapa: 'selecao', status: STATUS_AGUARDANDO_AVALIADOR }, [])
  igual(f, 'aguardando avaliador', [avaliador.pesquisa, avaliador.selecao, avaliador.calculo],
    ['concluida', 'aguardando_avaliador', 'pendente'])
  igual(f, 'status aguardando avaliador', statusInfo(STATUS_AGUARDANDO_AVALIADOR),
    { texto: 'Aguardando sua confirmação', tom: 'aviso' })
  igual(f, 'status aguardando escolha (pesquisa)', statusInfo(STATUS_AGUARDANDO_AVALIADOR, 'pesquisa').texto,
    'Aguardando sua escolha de referenciais')
  const escolha = est({ etapa: 'pesquisa', status: STATUS_AGUARDANDO_AVALIADOR }, [])
  igual(f, 'aguardando escolha na pesquisa', [escolha.extracao, escolha.pesquisa, escolha.selecao],
    ['concluida', 'aguardando_avaliador', 'pendente'])
  verifica(f, 'aguardandoEscolha', aguardandoEscolha({ etapa: 'pesquisa', status: STATUS_AGUARDANDO_AVALIADOR })
    && !aguardandoEscolha({ etapa: 'selecao', status: STATUS_AGUARDANDO_AVALIADOR }))

  // lista de candidatos
  const c = (n: number, extra: Partial<Referencial> = {}): Referencial => ({ ...ref(n, 100, 10, false), ...extra })
  const lista = [c(3, { nao_recomendado: true }), c(1, { decisao: 'entra' }), c(2, { decisao: 'descarta' }),
    c(4, { fonte_coleta: 'manual' }), c(5, { fonte_coleta: 'manual', decisao: 'descarta' })]
  igual(f, 'total entra (manual conta, descartado não)', totalEntra(lista), 2)
  igual(f, 'riscados no fim', ordenarCandidatos(lista).map((r) => r.n), [1, 2, 4, 5, 3])
  igual(f, 'esconder riscados', ordenarCandidatos(lista, false).map((r) => r.n), [1, 2, 4, 5])
  igual(f, 'D-056: mais parecido primeiro', ordenarCandidatos([c(1, { pontos: 5 }), c(2, { pontos: 12 }),
    c(3, { pontos: 12 }), c(4, { pontos: 30, nao_recomendado: true }), c(5, { pontos: 8 })]).map((r) => r.n), [2, 3, 5, 1, 4])
  igual(f, 'L201-3: o que destoa desce (depois dos parecidos, antes dos riscados)', ordenarCandidatos([
    c(1, { pontos: 30, destoa: ['mais novo'] }), c(2, { pontos: 5 }), c(3, { nao_recomendado: true }),
    c(4, { pontos: 9, destoa: [] })]).map((r) => r.n), [4, 2, 1, 3])
  igual(f, 'domínio sem www', dominio('https://www.zapimoveis.com.br/imovel/x?y=1'), 'zapimoveis.com.br')
  igual(f, 'domínio inválido', dominio('javascript:alert(1)'), null)
  igual(f, 'rótulo buscar', [rotuloBuscar(0), rotuloBuscar(3)], ['Pesquisar referenciais', 'Pedir mais referenciais'])
  verifica(f, 'emExecucao', emExecucao({ etapa: 'calculo', status: 'pendente' })
    && !emExecucao({ etapa: 'nova', status: 'pendente' }) && !emExecucao({ etapa: 'selecao', status: STATUS_AGUARDANDO_AVALIADOR }))

  const fila = estadoDasEtapas({ etapa: 'extracao', status: 'pendente' }, []).find((l) => l.id === 'extracao')
  igual(f, 'na fila', [fila?.estado, fila?.mensagem], ['pendente', 'Na fila'])

  const completos = ETAPAS.map((e, i) => ev(i + 1, e.id, 'resultado'))
  const pronto = est({ etapa: 'entrega', status: STATUS_PRONTO }, completos)
  igual(f, 'final pronto: tudo concluído', Object.values(pronto).every((s) => s === 'concluida'), true)

  const bloq = est({ etapa: 'entrega', status: STATUS_BLOQUEADO }, [ev(1, 'triagem', 'resultado'), ev(2, 'entrega', 'resultado')])
  igual(f, 'bloqueado: parou na triagem, entrega não concluída', [bloq.triagem, bloq.extracao, bloq.entrega], ['bloqueado', 'pendente', 'pendente'])
  const bloqExt = estadoDasEtapas({ etapa: 'entrega', status: STATUS_BLOQUEADO },
    [ev(1, 'triagem', 'resultado'), ev(2, 'extracao', 'resultado')], 'extracao')
  igual(f, 'bloqueado na extração', bloqExt.slice(0, 3).map((l) => l.estado), ['concluida', 'bloqueado', 'pendente'])
  const tec = estadoDasEtapas({ etapa: 'extracao', status: STATUS_ERRO_TECNICO },
    [ev(1, 'triagem', 'resultado'), ev(2, 'extracao', 'erro', 'Falha')]).find((l) => l.id === 'extracao')
  igual(f, 'erro técnico', [tec?.estado, tec?.mensagem], ['erro', 'Falha'])
  igual(f, 'etapa do erro', [etapaDoErro([ev(1, 'extracao', 'erro')]), etapaDoErro([ev(1, 'orquestrador', 'erro')]),
    etapaDoErro([])], ['extracao', 'triagem', 'triagem'])
  igual(f, 'markdown rico', trechosRicos('a **b** `c` [d](https://x.y) e'), [
    { texto: 'a ', negrito: false }, { texto: 'b', negrito: true }, { texto: ' ', negrito: false },
    { texto: 'c', negrito: false, codigo: true }, { texto: ' ', negrito: false },
    { texto: 'd', negrito: false, link: 'https://x.y' }, { texto: ' e', negrito: false }])
  igual(f, 'msg segura',[msgSegura('ValueError Exception x'), msgSegura('Tudo certo')], [TEXTO_ERRO_TECNICO, 'Tudo certo'])

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

  // ORDEM 022: caixa "Alterar dados extraídos dos documentos"
  igual(f, 'dados: pendentes que impedem', resumoDadosExtraidos(62, 10, 2), '62 campos · 10 pendentes — 2 impedem o laudo')
  igual(f, 'dados: sem pendência', resumoDadosExtraidos(62, 0, 0), '62 campos')
  igual(f, 'dados: 1 pendente', resumoDadosExtraidos(5, 1, 1), '5 campos · 1 pendente — 1 impede o laudo')
  igual(f, 'dados: vazio', resumoDadosExtraidos(0, 0, 0), 'ainda sem dados extraídos')

  // ORDEM 023-A: caixas sanfona
  const cx = [{ id: 'andamento', selo: 'aguardando' as const }, { id: 'confirmar', selo: 'vez' as const },
    { id: 'dados', selo: 'pendencias' as const }, { id: 'calculo', selo: null }, { id: 'trabalho', selo: null }]
  igual(f, 'caixa da vez', caixaDaVez(cx), 'confirmar')
  igual(f, 'sem caixa da vez', caixaDaVez([{ id: 'a', selo: 'ok' }]), null)
  igual(f, 'próxima pede atenção', proximaCaixa(cx, 'andamento'), 'confirmar')
  igual(f, 'próxima depois da vez', proximaCaixa(cx, 'confirmar'), 'dados')
  igual(f, 'próxima na ordem', proximaCaixa(cx, 'dados'), 'calculo')
  igual(f, 'última volta à que pede atenção', proximaCaixa(cx, 'trabalho'), 'confirmar')
  igual(f, 'inicial: a da vez vence a lembrada', caixaInicial(cx, 'calculo'), 'confirmar')
  igual(f, 'inicial: lembrada', caixaInicial([{ id: 'a', selo: null }, { id: 'b', selo: null }], 'b'), 'b')
  igual(f, 'inicial: lembrada que sumiu', caixaInicial([{ id: 'a', selo: null }], 'x'), null)
  const m = (v: string) => `R$ ${v}`
  igual(f, 'resumo cálculo prévia', resumoCalculo({ valor_adotado: '5981000' }, null, m), 'R$ 5981000 (prévia)')
  igual(f, 'resumo cálculo pendente', resumoCalculo({ pendente: true }, null, m), 'escolha a base e a área para ver o valor')
  igual(f, 'resumo cálculo vigente', resumoCalculo(null, { valor_adotado: '1' }, m), 'R$ 1')
  igual(f, 'resumo candidatos', resumoCandidatos(20, 6), '20 candidatos · 6 escolhidos')

  // ORDEM 028-2: plural certo
  igual(f, 'plural 1', plural(1, 'aviso', 'avisos'), '1 aviso')
  igual(f, 'plural 32', plural(32, 'aviso', 'avisos'), '32 avisos')
  igual(f, 'plural 0', plural(0, 'ponto', 'pontos'), '0 pontos')
  igual(f, 'plural milhar', plural(1162, 'registro', 'registros'), '1.162 registros')

  // 114: quadro único da revisão
  igual(f, 'modelo vazio não é pedido', temPedido(MODELO_AJUSTE), false)
  igual(f, 'par preenchido é pedido', temPedido('Onde fica: 8\nO que mudar: trocar A'), true)
  igual(f, 'texto livre é pedido', temPedido('a área correta é 148 m²'), true)
  igual(f, 'outro ajuste', maisUmPar('Onde fica: 8\nO que mudar: x\n'), 'Onde fica: 8\nO que mudar: x\n\nOnde fica: \nO que mudar: ')
  // 116-2: ditado
  const q = 'Onde fica: 8\nO que mudar: '
  igual(f, 'cursor no O que mudar', campoOQueNoCursor(q, q.length), q.length)
  igual(f, 'cursor no Onde fica', campoOQueNoCursor(q, 3), null)
  igual(f, 'ditado no campo', inserirNoCampo(q, q.length, ' trocar novo por nova '), 'Onde fica: 8\nO que mudar: trocar novo por nova')
  igual(f, 'ditado troca o modelo vazio', juntarQuadro(MODELO_AJUSTE, 'Onde fica: página 8\nO que mudar: x'),
    'Onde fica: página 8\nO que mudar: x\n')
  igual(f, 'ditado junta ao que já tem', juntarQuadro('Onde fica: 7.4\nO que mudar: y\n\n' + MODELO_AJUSTE, 'Onde fica: \nO que mudar: z'),
    'Onde fica: 7.4\nO que mudar: y\n\nOnde fica: \nO que mudar: z\n')

  // 132-6: "refaça" solto pergunta "refazer o quê?"
  igual(f, 'refaça vago', pedidoVago('refaça'), true)
  igual(f, 'refaça até sair certo', pedidoVago('refaça, até sair do jeito certo.'), true)
  igual(f, '141 andar: próximo', andar(2, 14, 1), 3)
  igual(f, '141 andar: volta do fim ao 1º', andar(13, 14, 1), 0)
  igual(f, '141 andar: anterior do 1º vai ao último', andar(0, 14, -1), 13)
  igual(f, '142 contador: antes de usar, só os deixados', contarResolvidos(14, 2, null), 2)
  igual(f, '142 contador: conferência acha 3 de 14', contarResolvidos(14, 2, 3), 11)
  igual(f, '142 contador: nunca passa do total', contarResolvidos(3, 1, 0), 3)
  igual(f, 'pedido com o quê', pedidoVago('refaça o mapa com contorno fino'), false)

  return f
}
