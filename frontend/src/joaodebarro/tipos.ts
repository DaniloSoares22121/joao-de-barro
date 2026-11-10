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
  descricao: string
  foto: string
  escolhido: boolean
  justificativa: string
}

export type AcaoPendencia =
  | { tipo: 'enviar_arquivo'; tipo_arquivo: 'documento' | 'foto' | 'solicitante' }
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

export interface ResultadoSelecao {
  unitario_adotado?: string | number | null
  justificativa_unitario?: string
  faixa_pct?: string | number
  declaracao_amostra?: string
  manual?: boolean
}

export interface ResultadoExtracao {
  divergencias?: string[]
  documentos_descartados?: { arquivo: string; motivo: string }[]
}

export interface ResultadoEntrega {
  status: string
  arquivos: string[]
  pendencias: Pendencia[]
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
  pendencias: Pendencia[]
  /** Chamadas de IA do trabalho (custo e tempo). */
  resumo_ia?: ResumoIA
  /** Campo/referenciais/dados editados depois da última entrega (falta recalcular). */
  dados_alterados?: boolean
}

/** Evento do WS /ws/avaliacao/{id}. */
export interface Evento {
  id: number
  etapa: string
  nivel: string
  msg: string
  dados: unknown
  ts: string
}
