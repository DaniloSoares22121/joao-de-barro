/* Formatos da API /api/avaliacao (ver backend/lovable/avaliacao/routes.py e modelos.py). */

export type ModalidadeId = 'OV' | 'AM' | 'AM_GARANTIA' | 'AMJ'

/** Item de GET /jobs. */
export interface JobResumo {
  id: string
  numero: number
  etapa: string
  status: string
  criado: string
  atualizado: string
  cliente?: string | null
  modalidade?: string | null
  tipo?: string | null
  bairro?: string | null
  cidade?: string | null
  finalidade?: string | null
  objeto_parte?: string | null
  /** ORDEM 047: etapa (Proposta…Assinatura) e próximo passo em poucas palavras */
  etapa_tela?: string
  proximo?: string
  /** ORDEM 060: laudo já gerado ou assinado (aviso a mais ao apagar). */
  entregue?: boolean
  /** ORDEM 056: status das 5 etapas (feito | fora | atual | …) */
  etapas_st?: string[]
}

export interface DadosTrabalho {
  id: string
  numero: number
  modalidade: ModalidadeId
  finalidade: string
  cliente: string
  tipo: string
  bairro: string
  cidade: string
  pin_maps: string
  data_base: string
  data_vistoria: string
  contexto: string
  obs_vistoria?: string
  checklist_vistoria?: string
  /** "AAAA-MM-DD" ou null (= data do dia da geração). */
  data_emissao?: string | null
  /** D-043: visita técnica feita por parceiro (nome, registro). */
  visita_por?: string
  /** ORDEM 032-2 / D-059: parte do imóvel avaliada ("" = imóvel inteiro). */
  objeto_parte?: string
  processo_numero?: string
  vara_juizo?: string
  acao?: string
  partes?: { autor: string; reu: string } | null
  quesitos?: string[]
}

export interface Job {
  id: string
  numero: number
  etapa: string
  status: string
  criado: string
  atualizado: string
  dados: DadosTrabalho
}

export type Origem = 'documento' | 'vistoria' | 'pesquisa' | 'inferido' | 'pendente'

export interface Campo {
  nome: string
  valor: string | number | null
  unidade: string
  origem: Origem
  fonte: string
  observacao: string
}

export interface Referencial {
  n: number
  link: string
  portal: string
  bairro: string
  tipologia: string
  quartos: number | null
  suites: number | null
  lote_m2: number | null
  area_m2: number | null
  preco: number | null
  padrao: string
  idade_aparente: string
  /** 105-2 / 110-2: de onde veio a idade: "anúncio" | "fotos" | "avaliador" | "relato" | "". */
  idade_fonte?: string
  descricao: string
  foto: string
  /** "coletor": achado pelo Coletor; "banco": reaproveitado; "manual": cadastrado pelo avaliador. */
  fonte_coleta?: FonteColeta
  publicado_em?: string
  visto_em?: string
  /** D-082: data e hora de acesso ao anúncio (ISO) */
  acessado_em?: string
  escolhido: boolean
  justificativa: string
  // ---- lista de candidatos da pesquisa (escolha do avaliador antes de abrir os anúncios)
  decisao?: DecisaoCandidato
  fotos_url?: string[]      // 081-5: fotos grandes da galeria do anúncio
  foto_arte?: boolean
  foto_url_escolhida?: string   // 173: a foto da galeria que vai na tabela
  foto_avaliador?: boolean      // 173: foto enviada pelo avaliador
  motivo_descarte?: string
  /** ★ recomendado pela IA. */
  recomendado?: boolean
  /** Não recomendado (linha riscada). */
  nao_recomendado?: boolean
  /** L201-3 (regra 6): o que destoa do avaliando ("padrão superior", "mais novo") — vai para o fim e pede confirmação. */
  destoa?: string[]
  /** Uma linha: por que ★ ou por que riscado. */
  motivo?: string
  /** O que conferir ao abrir o anúncio. */
  observacao?: string
  /** Portal barrou o robô: abrir no navegador. */
  bloqueado?: boolean
  coletado?: boolean
  rodada?: number | null
  titulo?: string
  rua?: string
  pontos?: number | null
}

export type DecisaoCandidato = '' | 'entra' | 'descarta' | 'comparacao'

/** Resposta de PUT /jobs/{id}/candidatos/{n}. */
export interface RespostaDecisao extends Partial<Referencial> { total_entra?: number }

/** "avaliador": enviado pelo Alan com a extensão do Chrome (ORDEM 010). */
export type FonteColeta = 'coletor' | 'banco' | 'manual' | 'avaliador'

/** Resposta de POST /jobs/{id}/referenciais/manual. */
export interface ReferencialSalvo extends Referencial { unitario: number }

/** Resposta de PUT /jobs/{id}/referenciais. */
export interface RespostaEscolha extends ResultadoSelecao {
  /** null quando a base/área ainda não foram escolhidas (ORDEM 022) */
  valor_adotado: string | null
  valor_min: string | null
  valor_max: string | null
  media: string
  mensagem?: string
}

/** ORDEM 022: prévia do cálculo gravada a cada "Salvar" (sem IA). */
export type PreviaCalculo =
  | (ResultadoCalculo & { base?: 'construida' | 'terreno'; previa: true })
  | { pendente: true; mensagem: string; unitario_adotado?: string }

export type AcaoPendencia =
  /** Sem `tipo_arquivo`: abre as três caixas (documentos, fotos, solicitante). */
  | { tipo: 'enviar_arquivo'; tipo_arquivo?: 'documento' | 'foto' | 'solicitante' }
  | { tipo: 'editar_campo'; campo: string }
  | { tipo: 'ligar_coletor' }
  | { tipo: 'preencher_trabalho'; campo: string }

export interface Pendencia { texto: string; grave: boolean; acao?: AcaoPendencia }

export interface ResultadoCalculo {
  area: string
  valor_adotado: string
  valor_min: string
  valor_max: string
  unitario_adotado: string
}

export interface PropostaIA {
  unitario_adotado: string | null
  justificativa_unitario: string
  faixa_pct: string | null
}

export interface ResultadoSelecao {
  refs?: Referencial[]
  unitario_adotado?: string | number | null
  justificativa_unitario?: string
  faixa_pct?: string | number | null
  declaracao_amostra?: string
  manual?: boolean
  /** Avaliador já confirmou referenciais/unitário/faixa. */
  confirmado?: boolean
  /** O que a IA propôs antes da confirmação do avaliador. */
  proposta_ia?: PropostaIA | null
}

export interface ResultadoExtracao {
  divergencias?: string[]
  documentos_descartados?: { arquivo: string; motivo: string }[]
}

export interface PontoContestacao {
  pagina: string
  ponto: string
  por_que: string
  gravidade: 'alta' | 'media' | 'baixa'
  como_reforcar: string
}

export interface ResultadoEntrega {
  status: string
  arquivos: string[]
  pendencias: Pendencia[]
  /** ORDEM 039 / D-083: contestação simulada (não altera o laudo) */
  contestacao?: { pontos: PontoContestacao[]; altas: number; custo_usd?: number | null } | null
  /** ORDEM 039 / D-084: conferência de coerência (código, sem IA) */
  coerencia?: { ok: boolean; diferencas: string[] } | null
  /** ORDEM 039 / D-086: PDF assinado guardado como final */
  assinado?: string
}

export interface ResumoIA {
  chamadas: number
  custo_usd: number
  tempo_s: number
}

export interface Detalhe {
  job: Job
  etapas: Record<string, unknown>
  arquivos: { id: number; nome: string; tipo: string; caminho: string }[]
  campos: Campo[]
  candidatos: Referencial[]
  resultado: ResultadoCalculo | null
  /** Prévia do "Salvar" no Confirmar valor, mais nova que o cálculo do pipeline. */
  previa_calculo?: PreviaCalculo | null
  pendencias: Pendencia[]
  /** Chamadas de IA do trabalho (custo e tempo). */
  resumo_ia?: ResumoIA
  modelo_laudo?: { modalidade: string; de: 'seu' | 'sistema' }   // 194
  /** Campo/referenciais/dados editados depois da última entrega (falta recalcular). */
  dados_alterados?: boolean
  /** ORDEM 032-3: data das fotos (EXIF) diferente da data da vistoria; "" = tudo certo. */
  alerta_datas?: string
  /** ORDEM 047 / D-101: linha de etapas e próximo passo da tela simples. */
  tela?: TelaTrabalho
}

export interface EtapaTela { etapa: string; rotulo: string; status: 'feito' | 'fora' | 'atual' | 'espera' | 'falta' | 'sem_registro' }
export interface TelaTrabalho { etapas: EtapaTela[]; atual: string; proximo: string; aprovado: boolean; assinado: boolean; cliente_id?: string; revisao?: number; fotos_novas?: number; por_que?: string }

/** Evento do WS /ws/avaliacao/{id}. */
export interface Evento {
  id: number
  etapa: string
  nivel: string
  msg: string
  dados: unknown
  ts: string
}


/** ORDEM 021: opções de área do cálculo (GET /jobs/{id}/areas). */
export type BaseArea = 'construida' | 'terreno'
export interface OpcaoArea { campo: string; valor: number; origem: string; fonte: string; sugerida: boolean }
export interface AreasCalculo {
  construida: OpcaoArea[]
  terreno: OpcaoArea[]
  escolha: { base: BaseArea; campo: string; valor: number; origem: string } | null
}
