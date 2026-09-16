/**
 * TypeScript-зеркало контракта `src/models.py` (pydantic).
 *
 * Правила отображения:
 *   - `Optional[X] = None`  -> `x?: X`  (отсутствие поля и значение различаются);
 *   - `Field(default_factory=list)` -> `x: X[]` (пустой список — валидное значение);
 *   - `extra = "forbid"` -> незнакомые ключи не удаляются молча, а складываются
 *     в `$extra` и показываются как ошибка конфигурации.
 *
 * Имена полей в TS совпадают с JSON-алиасами, которые ждёт движок.
 */

/** Служебные поля редактора. В JSON не экспортируются. */
export interface WithExtra {
  /** Незнакомые (или неразобранные) ключи, сохранённые при импорте. */
  $extra?: Record<string, unknown>;
  /**
   * Подмножество `$extra`: ключи, которые модель знает, но значение в файле
   * имеет неподдерживаемый тип. Отличается от «поля вообще нет в модели».
   */
  $invalidKeys?: string[];
  /**
   * Ключи, которые реально присутствовали в файле.
   * Нужны, чтобы экспорт не дописывал значения по умолчанию,
   * которых в исходном файле не было.
   */
  $seen?: string[];
}

export type BenchmarkStrategy =
  | 'types_strategy'
  | 'indexes_strategy'
  | 'combined_strategy'
  | 'sequential_topn_strategy'
  | 'sequential_phased_topn_strategy';

export type BenchmarkMode = 'types' | 'indexes' | 'combined' | 'sequential';

export type SelectQueryCacheMode = 'warm' | 'cold';
export type QueryType = 'hit' | 'miss' | 'manual' | 'generic';
export type QueriesMode = 'auto' | 'manual' | 'auto_with_manual';
export type ScoringMode = 'expression';
export type ScoreTopSelectionMode = 'max' | 'min';
export type ColumnOrderMode = 'compressed_size_desc';
export type RuleSourceMode =
  | 'global_bank_only'
  | 'global_bank_with_inline_priority'
  | 'inline_only';

/** `"*"` либо явный список. */
export type DatabasesSelector = '*' | string[];
export type TableListSelector = '*' | string[];
/** `"*"`, плоский список таблиц или map `database -> таблицы`. */
export type TablesSelector = '*' | string[] | Record<string, TableListSelector>;

export interface ColumnRuleConfig extends WithExtra {
  by_type?: string;
  by_name?: string;
  types: string[];
  codecs: string[];
  auto_generate_alternatives: boolean;
  auto_compressions_datatype?: string;
}

export interface CodecRuleConfig extends WithExtra {
  by_type?: string;
  by_name?: string;
  codecs: string[];
  auto_generate_alternatives: boolean;
  auto_compressions_datatype?: string;
}

/**
 * Один skip-индекс.
 *
 * `granularity_values` — перебор гранулярности самого индекса
 * (`INDEX ... GRANULARITY N`).
 * `index_granularity_values` — перебор табличного `SETTINGS index_granularity`
 * для этого индекса. Это разные вещи.
 */
export interface IndexConfig extends WithExtra {
  type: string;
  granularity: number;
  granularity_values?: number[];
  index_granularity_values?: number[];
  /**
   * Служебная метка формы записи в исходном файле.
   * Модель принимает `granularity` как массив и раскладывает его в
   * `granularity` + `granularity_values`; при экспорте возвращаем исходную форму.
   * В JSON не попадает.
   */
  $granularityAsArray?: boolean;
}

export interface IndexRuleConfig extends WithExtra {
  by_type?: string;
  by_name?: string;
  indexes: IndexConfig[];
  auto_generate_indexes: boolean;
  auto_indexes_datatype?: string;
}

export interface OrderByRulesConfig extends WithExtra {
  first_column?: string;
  candidates?: string[];
  auto_generate_candidates?: boolean;
}

/**
 * Контейнер правил: ссылка на банк и/или inline-переопределения.
 * `undefined` у списка означает «не задано» и наследование банка,
 * `[]` — явно пустой набор правил.
 */
export interface RulesConfig extends WithExtra {
  rule_bank?: string;
  column_rules?: ColumnRuleConfig[];
  codec_rules?: CodecRuleConfig[];
  index_rules?: IndexRuleConfig[];
  order_by_rules?: OrderByRulesConfig;
  column_order?: Record<string, number>;
}

export interface TestQueryConfig extends WithExtra {
  query_id?: string;
  query: string;
  query_type: QueryType;
  cache_mode: SelectQueryCacheMode;
  select_operations_count: number;
  warmup_queries: string[];
}

export interface QueriesConfig extends WithExtra {
  mode: QueriesMode;
  test_queries: TestQueryConfig[];
  auto_like_on_measured_columns: boolean;
  auto_like_replace_default_auto_queries: boolean;
  auto_like_sample_rows_per_column: number;
  auto_select_limit: number;
  auto_select_operations_count: number;
  auto_include_miss_queries: boolean;
  auto_like_min_token_length: number;
  auto_like_max_token_length: number;
}

export interface StageScoringConfig extends WithExtra {
  mode: ScoringMode;
  top_selection: ScoreTopSelectionMode;
  expression?: string;
  on_error_score?: number;
  variables?: Record<string, string>;
}

export interface ScoringConfig extends StageScoringConfig {
  by_stage?: Record<string, StageScoringConfig>;
}

/**
 * Лимиты по режимам/стадиям. Модель разрешает произвольные дополнительные ключи
 * (`extra = "allow"`), поэтому здесь это просто map с целыми значениями > 0.
 */
export type ModeLimitsConfig = Record<string, number>;

export interface TableRuleConfig extends WithExtra {
  database: string;
  table: string;
  test_database?: string;
  rules: RulesConfig;
  column_order_mode?: ColumnOrderMode;
  queries?: QueriesConfig;
  scoring?: ScoringConfig;
  insert_operations_count?: number;
  sequential_types_top_n_for_indexes?: number;
  sequential_top_n_limits?: ModeLimitsConfig;
  final_validation_input_top_n?: number;
  max_winners_per_parent_limits?: ModeLimitsConfig;
  insert_rows_per_operation_limit?: number;
  source_insert_rows_per_operation_limit?: number;
  source_insert_rows_per_operation_limits?: ModeLimitsConfig;
  insert_rows_per_operation_limits?: ModeLimitsConfig;
  max_benchmarks_limits?: ModeLimitsConfig;
  index_granularity_values?: number[];
  strategy?: BenchmarkStrategy;
  order_by_first?: string;
  order_by_candidates?: string[];
}

export interface BenchmarkConfig extends WithExtra {
  id: string;
  connection_id: string;
  strategy: BenchmarkStrategy;
  global_rules: RulesConfig;
  column_order_mode?: ColumnOrderMode;
  scoring: ScoringConfig;

  databases: DatabasesSelector;
  tables: TablesSelector;
  test_database?: string;

  insert_operations_count: number;
  sequential_types_top_n_for_indexes: number;
  sequential_top_n_limits?: ModeLimitsConfig;
  final_validation_input_top_n?: number;
  max_winners_per_parent_limits?: ModeLimitsConfig;
  insert_rows_per_operation_limit?: number;
  source_insert_rows_per_operation_limit?: number;
  source_insert_rows_per_operation_limits?: ModeLimitsConfig;
  insert_rows_per_operation_limits?: ModeLimitsConfig;
  max_benchmarks_limits?: ModeLimitsConfig;
  index_granularity_values?: number[];
  column_rules_mode?: RuleSourceMode;
  index_rules_mode?: RuleSourceMode;
  queries: QueriesConfig;
  table_rules: TableRuleConfig[];
  order_by_first?: string;
  order_by_candidates?: string[];
}

/** Файл `benchmarks.*.json` в project-режиме. */
export interface BenchmarksFile extends WithExtra {
  benchmarks: BenchmarkConfig[];
}

/** Значения по умолчанию из pydantic-модели. */
export const DEFAULT_SCORE_EXPRESSION =
  'pow(' +
  'safe_div(medians.source_insert_time_ms, medians.tested_insert_time_ms, 1.0) ' +
  '* safe_div(medians.source_select_time_ms, medians.tested_select_time_ms, 1.0) ' +
  '* safe_div(source_size_bytes, tested_size_bytes, 1.0), ' +
  '1 / 3)';

export const STRATEGY_TO_MODE: Record<BenchmarkStrategy, BenchmarkMode> = {
  types_strategy: 'types',
  indexes_strategy: 'indexes',
  combined_strategy: 'combined',
  sequential_topn_strategy: 'sequential',
  sequential_phased_topn_strategy: 'sequential',
};

export function emptyQueries(): QueriesConfig {
  return {
    mode: 'auto',
    test_queries: [],
    auto_like_on_measured_columns: false,
    auto_like_replace_default_auto_queries: false,
    auto_like_sample_rows_per_column: 20,
    auto_select_limit: 10,
    auto_select_operations_count: 5,
    auto_include_miss_queries: false,
    auto_like_min_token_length: 3,
    auto_like_max_token_length: 24,
  };
}

export function emptyScoring(): ScoringConfig {
  return {
    mode: 'expression',
    top_selection: 'max',
    expression: DEFAULT_SCORE_EXPRESSION,
  };
}

export function emptyBenchmark(id: string): BenchmarkConfig {
  return {
    id,
    connection_id: '',
    strategy: 'sequential_phased_topn_strategy',
    global_rules: {},
    scoring: emptyScoring(),
    databases: '*',
    tables: '*',
    insert_operations_count: 100,
    sequential_types_top_n_for_indexes: 1,
    queries: emptyQueries(),
    table_rules: [],
  };
}
