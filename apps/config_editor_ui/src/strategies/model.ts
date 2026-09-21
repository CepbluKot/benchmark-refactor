import { emptyDimensions, type SearchDimensions, type SearchProcedure } from './dimensions';

export type StrategyMethod = 'types_strategy' | 'indexes_strategy' | 'combined_strategy' | 'sequential_topn_strategy' | 'sequential_phased_topn_strategy';
export type ScoringPreset = 'balanced' | 'faster_reads' | 'faster_inserts' | 'better_compression' | 'read_only' | 'insert_only' | 'storage_only' | 'p95_select';
export type ScoreDirection = 'maximize' | 'minimize';
export const METHOD_LABELS: Record<StrategyMethod, string> = { types_strategy: 'Types and codecs', indexes_strategy: 'Skip indexes', combined_strategy: 'Combined', sequential_topn_strategy: 'Sequential Top-N', sequential_phased_topn_strategy: 'Phased Top-N' };

export interface StrategyBudgetDraft { rowsPerInsert: number; insertRepetitions: number; maxCandidates: number; topN: number; advanced: boolean; baselineRows?: number; candidateRows?: number; perPhaseCandidates?: number; winnersPerParent?: number; finalValidationCandidates?: number; finalValidationIndexAlternatives?: number }
export interface StrategyScoringDraft { preset: ScoringPreset | 'custom'; formula: string; direction: ScoreDirection; maxStorageGrowthPercent?: number; maxInsertSlowdownPercent?: number; minSelectImprovementPercent?: number }
export interface StrategyDraft { name: string; description: string; procedure: SearchProcedure; dimensions: SearchDimensions; budget: StrategyBudgetDraft; scoring: StrategyScoringDraft }

export interface StrategyTemplateV1 { schema_version: 1; method: StrategyMethod; rules: Partial<Record<'column_types' | 'codecs' | 'skip_indexes' | 'table_index_granularity' | 'order_by' | 'column_order', boolean>>; budget: StrategyBudgetConfig; scoring: { priority: 'balanced' | 'faster_reads' | 'faster_inserts' | 'better_compression'; max_storage_growth_percent?: number; max_insert_slowdown_percent?: number; min_select_improvement_percent?: number } }
export interface StrategyBudgetConfig { rows_per_insert: number; insert_repetitions: number; max_candidates: number; top_n: number; baseline_rows?: number; candidate_rows?: number; per_phase_candidates?: number; winners_per_parent?: number; final_validation_candidates?: number; final_validation_index_alternatives?: number }
export interface StrategyTemplateV2 { schema_version: 2; procedure: SearchProcedure; search_space: SearchDimensions; budget: StrategyBudgetConfig; scoring: { preset: ScoringPreset | 'custom'; formula: string; direction: ScoreDirection; max_storage_growth_percent?: number; max_insert_slowdown_percent?: number; min_select_improvement_percent?: number } }
export type StrategyTemplateConfig = StrategyTemplateV1 | StrategyTemplateV2;

export const SCORING_PRESETS: Record<ScoringPreset, { title: string; description: string; formula: string; direction: ScoreDirection }> = {
  balanced: { title: 'Balanced', description: 'Equal weight for reads, inserts, and storage.', formula: 'pow(read_gain, 1 / 3) * pow(insert_gain, 1 / 3) * pow(storage_gain, 1 / 3)', direction: 'maximize' },
  faster_reads: { title: 'Faster reads', description: 'Prioritize SELECT performance.', formula: 'pow(read_gain, 0.6) * pow(insert_gain, 0.2) * pow(storage_gain, 0.2)', direction: 'maximize' },
  faster_inserts: { title: 'Faster inserts', description: 'Prioritize INSERT performance.', formula: 'pow(read_gain, 0.2) * pow(insert_gain, 0.6) * pow(storage_gain, 0.2)', direction: 'maximize' },
  better_compression: { title: 'Better compression', description: 'Prioritize reduced storage size.', formula: 'pow(read_gain, 0.2) * pow(insert_gain, 0.2) * pow(storage_gain, 0.6)', direction: 'maximize' },
  read_only: { title: 'Read gain only', description: 'Rank only by SELECT improvement.', formula: 'read_gain', direction: 'maximize' },
  insert_only: { title: 'Insert gain only', description: 'Rank only by INSERT improvement.', formula: 'insert_gain', direction: 'maximize' },
  storage_only: { title: 'Storage gain only', description: 'Rank only by compression improvement.', formula: 'storage_gain', direction: 'maximize' },
  p95_select: { title: 'P95 SELECT latency', description: 'Minimize candidate P95 SELECT time.', formula: 'pct(tested_select_time_ms_by_percentile, 95)', direction: 'minimize' },
};

export const FORMULA_VARIABLES = [
  ['read_gain', 'medians.source_select_time_ms / medians.tested_select_time_ms'],
  ['insert_gain', 'medians.source_insert_time_ms / medians.tested_insert_time_ms'],
  ['storage_gain', 'source_size_bytes / tested_size_bytes'],
  ['medians.source_select_time_ms', 'Median baseline SELECT time, ms'],
  ['medians.tested_select_time_ms', 'Median candidate SELECT time, ms'],
  ['medians.source_insert_time_ms', 'Median baseline INSERT time, ms'],
  ['medians.tested_insert_time_ms', 'Median candidate INSERT time, ms'],
  ['source_size_bytes', 'Baseline size, bytes'],
  ['tested_size_bytes', 'Candidate size, bytes'],
  ['tested_select_time_ms_by_percentile', 'Candidate SELECT observations used by pct()'],
] as const;
export const FORMULA_FUNCTIONS = ['safe_div', 'at', 'pct', 'coalesce', 'clamp', 'median', 'abs', 'min', 'max', 'round', 'sqrt', 'log', 'ln', 'exp', 'pow'] as const;

const defaultDimensions = (): SearchDimensions => ({
  ...emptyDimensions(),
  column_types: [{ by_type: 'String', alternatives: ['LowCardinality(String)'] }],
  codecs: [{ by_type: 'String', alternatives: ['ZSTD(1)', 'ZSTD(3)'] }],
  skip_indexes: [{ by_type: 'String', indexes: [{ type: 'bloom_filter(0.01)', granularity: 4 }] }],
  table_index_granularity_values: [8192],
});

export function createDefaultStrategyDraft(): StrategyDraft { const preset = SCORING_PRESETS.balanced; return { name: '', description: '', procedure: 'phased', dimensions: defaultDimensions(), budget: { rowsPerInsert: 100000, insertRepetitions: 3, maxCandidates: 100, topN: 10, advanced: false }, scoring: { preset: 'balanced', formula: preset.formula, direction: preset.direction } }; }
const positive = (value: number | undefined): boolean => value !== undefined && Number.isInteger(value) && value > 0;
const finiteOptional = (value: number | undefined): boolean => value === undefined || Number.isFinite(value);
export function validateStrategyStep(draft: StrategyDraft, step: number): Record<string, string> {
  const errors: Record<string, string> = {};
  if (step === 0 && !draft.name.trim()) errors.name = 'Укажите название стратегии.';
  if (step === 2) for (const [key, value] of Object.entries({ rowsPerInsert: draft.budget.rowsPerInsert, insertRepetitions: draft.budget.insertRepetitions, maxCandidates: draft.budget.maxCandidates, topN: draft.budget.topN })) if (!positive(value)) errors[key] = 'Введите целое число больше нуля.';
  if (step === 3) { if (!draft.scoring.formula.trim()) errors.formula = 'Введите формулу оценки.'; if (!finiteOptional(draft.scoring.maxStorageGrowthPercent)) errors.maxStorageGrowthPercent = 'Введите конечное число.'; if (!finiteOptional(draft.scoring.maxInsertSlowdownPercent)) errors.maxInsertSlowdownPercent = 'Введите конечное число.'; if (!finiteOptional(draft.scoring.minSelectImprovementPercent)) errors.minSelectImprovementPercent = 'Введите конечное число.'; }
  return errors;
}
export function pruneStrategyDraft(draft: StrategyDraft): { name: string; description: string; config: StrategyTemplateV2 } {
  const budget: StrategyBudgetConfig = { rows_per_insert: draft.budget.rowsPerInsert, insert_repetitions: draft.budget.insertRepetitions, max_candidates: draft.budget.maxCandidates, top_n: draft.budget.topN };
  if (draft.budget.advanced) { if (draft.budget.baselineRows !== undefined) budget.baseline_rows = draft.budget.baselineRows; if (draft.budget.candidateRows !== undefined) budget.candidate_rows = draft.budget.candidateRows; if (draft.budget.perPhaseCandidates !== undefined) budget.per_phase_candidates = draft.budget.perPhaseCandidates; if (draft.budget.winnersPerParent !== undefined) budget.winners_per_parent = draft.budget.winnersPerParent; if (draft.budget.finalValidationCandidates !== undefined) budget.final_validation_candidates = draft.budget.finalValidationCandidates; if (draft.budget.finalValidationIndexAlternatives !== undefined) budget.final_validation_index_alternatives = draft.budget.finalValidationIndexAlternatives; }
  return { name: draft.name.trim(), description: draft.description.trim(), config: { schema_version: 2, procedure: draft.procedure, search_space: draft.dimensions, budget, scoring: { preset: draft.scoring.preset, formula: draft.scoring.formula.trim(), direction: draft.scoring.direction, ...(draft.scoring.maxStorageGrowthPercent !== undefined ? { max_storage_growth_percent: draft.scoring.maxStorageGrowthPercent } : {}), ...(draft.scoring.maxInsertSlowdownPercent !== undefined ? { max_insert_slowdown_percent: draft.scoring.maxInsertSlowdownPercent } : {}), ...(draft.scoring.minSelectImprovementPercent !== undefined ? { min_select_improvement_percent: draft.scoring.minSelectImprovementPercent } : {}) } } };
}
