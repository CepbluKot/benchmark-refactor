/** Русские подписи и пояснения к техническим значениям конфига. */

import type {
  BenchmarkStrategy,
  QueriesMode,
  QueryType,
  RuleSourceMode,
  SelectQueryCacheMode,
} from '../types/config';

export interface Choice<T extends string> {
  value: T;
  label: string;
  hint: string;
}

export const STRATEGIES: Choice<BenchmarkStrategy>[] = [
  {
    value: 'types_strategy',
    label: 'Перебор типов',
    hint: 'Проверяет только альтернативные типы и кодеки колонок. Режим замеров: types.',
  },
  {
    value: 'indexes_strategy',
    label: 'Перебор индексов',
    hint: 'Проверяет только пропускающие индексы. Режим замеров: indexes.',
  },
  {
    value: 'combined_strategy',
    label: 'Комбинированный перебор',
    hint: 'Декартово произведение вариантов типов, кодеков и индексов. Режим замеров: combined.',
  },
  {
    value: 'sequential_topn_strategy',
    label: 'Последовательный отбор Top-N',
    hint: 'Сначала типы, затем индексы поверх Top-N лучших типов. Режим замеров: sequential.',
  },
  {
    value: 'sequential_phased_topn_strategy',
    label: 'Поэтапный отбор Top-N',
    hint: 'Полный поэтапный конвейер: ORDER BY → типы → кодеки → index_granularity → индексы → финальная проверка. Режим замеров: sequential.',
  },
];

/**
 * Стадии `sequential_phased_topn_strategy`.
 * Источник: docs/SEQUENTIAL_PHASED_TOPN_PIPELINE_CONTRACT.md.
 */
export interface StageInfo {
  key: string;
  label: string;
  phase: number;
  hint: string;
}

export const PHASED_STAGES: StageInfo[] = [
  {
    key: 'source_baseline',
    label: 'Baseline',
    phase: 0,
    hint: 'Контрольный замер копии исходной таблицы. Хранится отдельно как фаза 0.',
  },
  {
    key: 'order_by',
    label: 'ORDER BY',
    phase: 1,
    hint: 'Полнотабличные кандидаты ключа сортировки. Дальше уходят Top-N веток.',
  },
  {
    key: 'types',
    label: 'Types',
    phase: 2,
    hint: 'Каждая колонка проверяется независимо; Top-N вариантов типа сохраняется на колонку.',
  },
  {
    key: 'codecs',
    label: 'Codecs',
    phase: 3,
    hint: 'Кодеки поверх отобранных типов; Top-N пар (тип, кодек) на колонку.',
  },
  {
    key: 'index_granularity',
    label: 'Index granularity',
    phase: 4,
    hint: 'Колоночные варианты собираются в полнотабличных кандидатов, перебирается SETTINGS index_granularity.',
  },
  {
    key: 'indexes',
    label: 'Indexes',
    phase: 5,
    hint: 'Пропускающие индексы по колонкам из WHERE, при фиксированной табличной гранулярности.',
  },
  {
    key: 'final_validation',
    label: 'Final validation',
    phase: 6,
    hint: 'Слияние лучших вариантов в полную схему, полный замер и опциональный локальный поиск.',
  },
];

/** Ключи, встречающиеся в `*_limits` у реальных конфигов. */
export const LIMIT_STAGE_KEYS = [
  'order_by',
  'types',
  'codecs',
  'index_granularity',
  'indexes',
  'indexes_validation',
  'final_validation',
  'local_search',
] as const;

/** Ключи режимов (`mode`) для лимитов вставки. */
export const LIMIT_MODE_KEYS = ['types', 'indexes', 'combined', 'sequential'] as const;

export const RULE_SOURCE_MODES: Choice<RuleSourceMode>[] = [
  {
    value: 'global_bank_only',
    label: 'Только банк правил',
    hint: 'Берётся только rule_bank; inline-списки игнорируются.',
  },
  {
    value: 'global_bank_with_inline_priority',
    label: 'Банк + приоритет inline',
    hint: 'Берётся банк, но заданный локально список того же вида замещает банковский.',
  },
  {
    value: 'inline_only',
    label: 'Только inline',
    hint: 'Банк не используется, действуют только правила, заданные здесь.',
  },
];

export const QUERIES_MODES: Choice<QueriesMode>[] = [
  { value: 'auto', label: 'Автоматические', hint: 'Запросы генерирует движок по метаданным таблицы.' },
  { value: 'manual', label: 'Ручные', hint: 'Замеряются только запросы из test_queries. Нужен хотя бы один.' },
  {
    value: 'auto_with_manual',
    label: 'Автоматические и ручные',
    hint: 'Объединение сгенерированного набора и test_queries.',
  },
];

export const QUERY_TYPES: Choice<QueryType>[] = [
  { value: 'hit', label: 'hit', hint: 'Запрос, попадающий в данные.' },
  { value: 'miss', label: 'miss', hint: 'Запрос, заведомо не находящий строк.' },
  { value: 'manual', label: 'manual', hint: 'Значение по умолчанию для ручного запроса.' },
  { value: 'generic', label: 'generic', hint: 'Запрос без специальной семантики.' },
];

export const CACHE_MODES: Choice<SelectQueryCacheMode>[] = [
  { value: 'warm', label: 'warm', hint: 'Замер по прогретому кешу; допускаются warmup_queries.' },
  { value: 'cold', label: 'cold', hint: 'Замер по холодному кешу; warmup_queries запрещены.' },
];

/** Whitelist движка: src/benchmark_runtime/implementations/clickhouse_celery/scoring.py */
export const SCORING_FUNCTIONS = [
  'safe_div',
  'at',
  'pct',
  'coalesce',
  'clamp',
  'median',
  'abs',
  'min',
  'max',
  'round',
  'sqrt',
  'log',
  'ln',
  'exp',
  'pow',
];

export const SCORING_ROOT_NAMES = [
  'measured_percentiles',
  'source',
  'tested',
  'speedup',
  'compression',
  'compression_overall_coef',
  'ratios',
  'medians',
  'source_size_bytes',
  'tested_size_bytes',
  'per_query',
  'source_insert_time_ms_percentiles',
  'source_insert_time_ms_by_percentile',
  'tested_insert_time_ms_percentiles',
  'tested_insert_time_ms_by_percentile',
  'insert_time_speedup_percentiles',
  'insert_time_speedup_by_percentile',
  'source_select_time_ms_percentiles',
  'source_select_time_ms_by_percentile',
  'tested_select_time_ms_percentiles',
  'tested_select_time_ms_by_percentile',
  'select_time_speedup_percentiles',
  'select_time_speedup_by_percentile',
  'select_time_speedup_by_query',
  'tested_table_insert_metrics_json',
  'source_table_insert_metrics_json',
  'tested_table_select_metrics_by_query_json',
  'source_table_select_metrics_by_query_json',
  'tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json',
  'tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json',
];

export function strategyLabel(value: BenchmarkStrategy): string {
  return STRATEGIES.find((item) => item.value === value)?.label ?? value;
}
