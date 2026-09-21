export type StrategyMethod = 'types_strategy' | 'indexes_strategy' | 'combined_strategy' | 'sequential_topn_strategy' | 'sequential_phased_topn_strategy';
export type ScoringPriority = 'balanced' | 'faster_reads' | 'faster_inserts' | 'better_compression';

export interface StrategyRulesDraft {
  columnTypes: boolean;
  codecs: boolean;
  skipIndexes: boolean;
  tableIndexGranularity: boolean;
  orderBy: boolean;
  columnOrder: boolean;
}

export interface StrategyBudgetDraft {
  rowsPerInsert: number;
  insertRepetitions: number;
  maxCandidates: number;
  topN: number;
  advanced: boolean;
  baselineRows?: number;
  candidateRows?: number;
  perPhaseCandidates?: number;
  winnersPerParent?: number;
  finalValidationCandidates?: number;
  finalValidationIndexAlternatives?: number;
}

export interface StrategyScoringDraft {
  priority: ScoringPriority;
  maxStorageGrowthPercent?: number;
  maxInsertSlowdownPercent?: number;
  minSelectImprovementPercent?: number;
}

export interface StrategyDraft {
  name: string;
  description: string;
  method: StrategyMethod;
  rules: StrategyRulesDraft;
  budget: StrategyBudgetDraft;
  scoring: StrategyScoringDraft;
}

export interface StrategyTemplateConfig {
  schema_version: 1;
  method: StrategyMethod;
  rules: Partial<Record<'column_types' | 'codecs' | 'skip_indexes' | 'table_index_granularity' | 'order_by' | 'column_order', boolean>>;
  budget: {
    rows_per_insert: number;
    insert_repetitions: number;
    max_candidates: number;
    top_n: number;
    baseline_rows?: number;
    candidate_rows?: number;
    per_phase_candidates?: number;
    winners_per_parent?: number;
    final_validation_candidates?: number;
    final_validation_index_alternatives?: number;
  };
  scoring: {
    priority: ScoringPriority;
    max_storage_growth_percent?: number;
    max_insert_slowdown_percent?: number;
    min_select_improvement_percent?: number;
  };
}

export const METHOD_LABELS: Record<StrategyMethod, string> = {
  types_strategy: 'Типы и кодеки',
  indexes_strategy: 'Skip-индексы',
  combined_strategy: 'Комбинированный поиск',
  sequential_topn_strategy: 'Последовательный Top-N',
  sequential_phased_topn_strategy: 'Поэтапный Top-N',
};

export function deriveStrategyPhases(method: StrategyMethod): string[] {
  return {
    types_strategy: ['types', 'codecs'],
    indexes_strategy: ['indexes'],
    combined_strategy: ['types', 'codecs', 'indexes'],
    sequential_topn_strategy: ['types', 'codecs', 'top_n', 'indexes'],
    sequential_phased_topn_strategy: ['order_by', 'types', 'codecs', 'index_granularity', 'indexes', 'final_validation'],
  }[method];
}

export function createDefaultStrategyDraft(): StrategyDraft {
  return {
    name: '',
    description: '',
    method: 'sequential_phased_topn_strategy',
    rules: { columnTypes: true, codecs: true, skipIndexes: true, tableIndexGranularity: true, orderBy: true, columnOrder: true },
    budget: { rowsPerInsert: 100000, insertRepetitions: 3, maxCandidates: 100, topN: 10, advanced: false },
    scoring: { priority: 'balanced' },
  };
}

const positive = (value: number | undefined): boolean => value !== undefined && Number.isInteger(value) && value > 0;
const finiteOptional = (value: number | undefined): boolean => value === undefined || Number.isFinite(value);

export function validateStrategyStep(draft: StrategyDraft, step: number): Record<string, string> {
  const errors: Record<string, string> = {};
  if (step === 0 && !draft.name.trim()) errors.name = 'Укажите название стратегии.';
  if (step === 3) {
    if (!positive(draft.budget.rowsPerInsert)) errors.rowsPerInsert = 'Введите целое число больше нуля.';
    if (!positive(draft.budget.insertRepetitions)) errors.insertRepetitions = 'Введите целое число больше нуля.';
    if (!positive(draft.budget.maxCandidates)) errors.maxCandidates = 'Введите целое число больше нуля.';
    if (!positive(draft.budget.topN)) errors.topN = 'Введите целое число больше нуля.';
    if (draft.budget.advanced) {
      for (const [key, value] of Object.entries({ baselineRows: draft.budget.baselineRows, candidateRows: draft.budget.candidateRows, perPhaseCandidates: draft.budget.perPhaseCandidates, winnersPerParent: draft.budget.winnersPerParent, finalValidationCandidates: draft.budget.finalValidationCandidates })) {
        if (value !== undefined && !positive(value)) errors[key] = 'Введите целое число больше нуля.';
      }
      if (draft.method === 'sequential_phased_topn_strategy' && draft.budget.finalValidationIndexAlternatives !== undefined && !positive(draft.budget.finalValidationIndexAlternatives)) errors.finalValidationIndexAlternatives = 'Введите целое число больше нуля.';
    }
  }
  if (step === 4) {
    if (!finiteOptional(draft.scoring.maxStorageGrowthPercent)) errors.maxStorageGrowthPercent = 'Введите конечное число.';
    if (!finiteOptional(draft.scoring.maxInsertSlowdownPercent)) errors.maxInsertSlowdownPercent = 'Введите конечное число.';
    if (!finiteOptional(draft.scoring.minSelectImprovementPercent)) errors.minSelectImprovementPercent = 'Введите конечное число.';
  }
  return errors;
}

export function pruneStrategyDraft(draft: StrategyDraft): { name: string; description: string; config: StrategyTemplateConfig } {
  const rules: StrategyTemplateConfig['rules'] = {};
  if (['types_strategy', 'combined_strategy', 'sequential_topn_strategy', 'sequential_phased_topn_strategy'].includes(draft.method)) {
    rules.column_types = draft.rules.columnTypes;
    rules.codecs = draft.rules.codecs;
  }
  if (['indexes_strategy', 'combined_strategy', 'sequential_topn_strategy', 'sequential_phased_topn_strategy'].includes(draft.method)) rules.skip_indexes = draft.rules.skipIndexes;
  if (draft.method === 'sequential_phased_topn_strategy') {
    rules.table_index_granularity = draft.rules.tableIndexGranularity;
    rules.order_by = draft.rules.orderBy;
    rules.column_order = draft.rules.columnOrder;
  }
  const budget: StrategyTemplateConfig['budget'] = { rows_per_insert: draft.budget.rowsPerInsert, insert_repetitions: draft.budget.insertRepetitions, max_candidates: draft.budget.maxCandidates, top_n: draft.budget.topN };
  if (draft.budget.advanced) {
    if (draft.budget.baselineRows !== undefined) budget.baseline_rows = draft.budget.baselineRows;
    if (draft.budget.candidateRows !== undefined) budget.candidate_rows = draft.budget.candidateRows;
    if (draft.budget.perPhaseCandidates !== undefined) budget.per_phase_candidates = draft.budget.perPhaseCandidates;
    if (draft.budget.winnersPerParent !== undefined) budget.winners_per_parent = draft.budget.winnersPerParent;
    if (draft.budget.finalValidationCandidates !== undefined) budget.final_validation_candidates = draft.budget.finalValidationCandidates;
    if (draft.method === 'sequential_phased_topn_strategy' && draft.budget.finalValidationIndexAlternatives !== undefined) budget.final_validation_index_alternatives = draft.budget.finalValidationIndexAlternatives;
  }
  return { name: draft.name.trim(), description: draft.description.trim(), config: { schema_version: 1, method: draft.method, rules, budget, scoring: {
    priority: draft.scoring.priority,
    ...(draft.scoring.maxStorageGrowthPercent !== undefined ? { max_storage_growth_percent: draft.scoring.maxStorageGrowthPercent } : {}),
    ...(draft.scoring.maxInsertSlowdownPercent !== undefined ? { max_insert_slowdown_percent: draft.scoring.maxInsertSlowdownPercent } : {}),
    ...(draft.scoring.minSelectImprovementPercent !== undefined ? { min_select_improvement_percent: draft.scoring.minSelectImprovementPercent } : {}),
  } } };
}
