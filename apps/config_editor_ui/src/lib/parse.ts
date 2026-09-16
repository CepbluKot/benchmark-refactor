/** Разбор JSON-файла конфигурации в модель редактора. */

import type {
  BenchmarkConfig,
  BenchmarkStrategy,
  CodecRuleConfig,
  ColumnOrderMode,
  ColumnRuleConfig,
  DatabasesSelector,
  IndexConfig,
  IndexRuleConfig,
  ModeLimitsConfig,
  OrderByRulesConfig,
  QueriesConfig,
  QueriesMode,
  QueryType,
  RuleSourceMode,
  RulesConfig,
  ScoringConfig,
  SelectQueryCacheMode,
  StageScoringConfig,
  TableRuleConfig,
  TablesSelector,
  TestQueryConfig,
} from '../types/config';
import { DEFAULT_SCORE_EXPRESSION } from '../types/config';
import type { Issue, SectionId } from './issues';
import { Reader, compact, isPlainObject } from './reader';
import type { ReadContext } from './reader';

const STRATEGY_VALUES = [
  'types_strategy',
  'indexes_strategy',
  'combined_strategy',
  'sequential_topn_strategy',
  'sequential_phased_topn_strategy',
] as const satisfies readonly BenchmarkStrategy[];

const RULE_SOURCE_VALUES = [
  'global_bank_only',
  'global_bank_with_inline_priority',
  'inline_only',
] as const satisfies readonly RuleSourceMode[];

const QUERIES_MODE_VALUES = ['auto', 'manual', 'auto_with_manual'] as const satisfies readonly QueriesMode[];
const QUERY_TYPE_VALUES = ['hit', 'miss', 'manual', 'generic'] as const satisfies readonly QueryType[];
const CACHE_MODE_VALUES = ['warm', 'cold'] as const satisfies readonly SelectQueryCacheMode[];
const COLUMN_ORDER_MODE_VALUES = ['compressed_size_desc'] as const satisfies readonly ColumnOrderMode[];
const TOP_SELECTION_VALUES = ['max', 'min'] as const;
const SCORING_MODE_VALUES = ['expression'] as const;

/** Вид открытого документа. Форматы разных файлов проекта не смешиваются. */
export type DocumentKind = 'benchmarks' | 'project';

export interface BenchmarksDocument {
  kind: DocumentKind;
  benchmarks: BenchmarkConfig[];
  /** Ключи project-обёртки (`connections_file`, `celery`, ...) — сохраняются как есть. */
  wrapper?: Record<string, unknown>;
  /** Незнакомые ключи корня документа. */
  $extra?: Record<string, unknown>;
}

export interface ParseOutcome {
  document?: BenchmarksDocument;
  issues: Issue[];
}

function fileIssue(message: string, path = '', check: Issue['check'] = 'json'): Issue {
  return { level: 'error', check, path, message, section: 'file' };
}

function readColumnRule(raw: Record<string, unknown>, path: string, ctx: ReadContext): ColumnRuleConfig {
  const r = new Reader(raw, path, ctx, 'rules');
  return compact({
    by_type: r.str('by_type'),
    by_name: r.str('by_name'),
    types: r.strList('types') ?? [],
    codecs: r.strList('codecs') ?? [],
    auto_generate_alternatives: r.bool('auto_generate_alternatives') ?? false,
    auto_compressions_datatype: r.str('auto_compressions_datatype'),
    $extra: r.rest(),
    $invalidKeys: r.invalidKeys(),
    $seen: r.seen(),
  }) as ColumnRuleConfig;
}

function readCodecRule(raw: Record<string, unknown>, path: string, ctx: ReadContext): CodecRuleConfig {
  const r = new Reader(raw, path, ctx, 'rules');
  return compact({
    by_type: r.str('by_type'),
    by_name: r.str('by_name'),
    codecs: r.strList('codecs') ?? [],
    auto_generate_alternatives: r.bool('auto_generate_alternatives') ?? false,
    auto_compressions_datatype: r.str('auto_compressions_datatype'),
    $extra: r.rest(),
    $invalidKeys: r.invalidKeys(),
    $seen: r.seen(),
  }) as CodecRuleConfig;
}

function readIndexConfig(raw: Record<string, unknown>, path: string, ctx: ReadContext): IndexConfig {
  // Модель принимает `granularity` как массив и раскладывает его в
  // granularity + granularity_values; исходную форму записи запоминаем.
  const granularityRaw = raw.granularity;
  const asArray = Array.isArray(granularityRaw);
  const normalized: Record<string, unknown> = { ...raw };
  if (asArray) {
    const values = granularityRaw as unknown[];
    if (values.length === 0) {
      ctx.issues.push({
        level: 'error',
        check: 'structure',
        path: `${path}.granularity`,
        message: 'granularity как массив не должен быть пустым',
        section: 'rules',
        benchmarkId: ctx.benchmarkId,
        field: 'granularity',
      });
    }
    if (normalized.granularity_values === undefined) normalized.granularity_values = values;
    normalized.granularity = values[0];
  }

  const r = new Reader(normalized, path, ctx, 'rules');
  const granularityValues = r.intList('granularity_values');
  const result = compact({
    type: r.str('type', { required: true }) ?? '',
    granularity: r.int('granularity', { min: 1 }) ?? granularityValues?.[0] ?? 1,
    granularity_values: granularityValues,
    index_granularity_values: r.intList('index_granularity_values'),
    $extra: r.rest(),
    $invalidKeys: r.invalidKeys(),
    $seen: r.seen(),
  }) as IndexConfig;
  if (asArray) result.$granularityAsArray = true;
  return result;
}

function readIndexRule(raw: Record<string, unknown>, path: string, ctx: ReadContext): IndexRuleConfig {
  const r = new Reader(raw, path, ctx, 'rules');
  const indexes = r.objList('indexes');
  return compact({
    by_type: r.str('by_type'),
    by_name: r.str('by_name'),
    indexes: (indexes ?? []).map((item, i) => readIndexConfig(item, `${path}.indexes[${i}]`, ctx)),
    auto_generate_indexes: r.bool('auto_generate_indexes') ?? false,
    auto_indexes_datatype: r.str('auto_indexes_datatype'),
    $extra: r.rest(),
    $invalidKeys: r.invalidKeys(),
    $seen: r.seen(),
  }) as IndexRuleConfig;
}

function readOrderByRules(
  raw: Record<string, unknown>,
  path: string,
  ctx: ReadContext,
): OrderByRulesConfig {
  const r = new Reader(raw, path, ctx, 'rules');
  return compact({
    first_column: r.str('first_column'),
    candidates: r.strList('candidates'),
    auto_generate_candidates: r.bool('auto_generate_candidates'),
    $extra: r.rest(),
    $invalidKeys: r.invalidKeys(),
    $seen: r.seen(),
  }) as OrderByRulesConfig;
}

function readRules(
  raw: Record<string, unknown> | undefined,
  path: string,
  ctx: ReadContext,
): RulesConfig {
  if (raw === undefined) return {};
  const r = new Reader(raw, path, ctx, 'rules');
  const columnRules = r.objList('column_rules');
  const codecRules = r.objList('codec_rules');
  const indexRules = r.objList('index_rules');
  const orderByRules = r.obj('order_by_rules');
  return compact({
    rule_bank: r.str('rule_bank'),
    column_rules: columnRules?.map((item, i) =>
      readColumnRule(item, `${path}.column_rules[${i}]`, ctx),
    ),
    codec_rules: codecRules?.map((item, i) => readCodecRule(item, `${path}.codec_rules[${i}]`, ctx)),
    index_rules: indexRules?.map((item, i) => readIndexRule(item, `${path}.index_rules[${i}]`, ctx)),
    order_by_rules: orderByRules
      ? readOrderByRules(orderByRules, `${path}.order_by_rules`, ctx)
      : undefined,
    column_order: r.intMap('column_order'),
    $extra: r.rest(),
    $invalidKeys: r.invalidKeys(),
    $seen: r.seen(),
  }) as RulesConfig;
}

function readTestQuery(
  raw: Record<string, unknown>,
  path: string,
  ctx: ReadContext,
): TestQueryConfig {
  const r = new Reader(raw, path, ctx, 'queries');
  return compact({
    query_id: r.str('query_id'),
    query: r.str('query', { required: true }) ?? '',
    query_type: r.enumOf('query_type', QUERY_TYPE_VALUES) ?? 'manual',
    cache_mode: r.enumOf('cache_mode', CACHE_MODE_VALUES) ?? 'warm',
    select_operations_count: r.int('select_operations_count', { min: 1 }) ?? 1,
    warmup_queries: r.strList('warmup_queries') ?? [],
    $extra: r.rest(),
    $invalidKeys: r.invalidKeys(),
    $seen: r.seen(),
  }) as TestQueryConfig;
}

function readQueries(
  raw: Record<string, unknown> | undefined,
  path: string,
  ctx: ReadContext,
): QueriesConfig | undefined {
  if (raw === undefined) return undefined;
  const r = new Reader(raw, path, ctx, 'queries');
  const testQueries = r.objList('test_queries');
  return compact({
    mode: r.enumOf('mode', QUERIES_MODE_VALUES) ?? 'auto',
    test_queries: (testQueries ?? []).map((item, i) =>
      readTestQuery(item, `${path}.test_queries[${i}]`, ctx),
    ),
    auto_like_on_measured_columns: r.bool('auto_like_on_measured_columns') ?? false,
    auto_like_replace_default_auto_queries:
      r.bool('auto_like_replace_default_auto_queries') ?? false,
    auto_like_sample_rows_per_column: r.int('auto_like_sample_rows_per_column', { min: 1 }) ?? 20,
    auto_select_limit: r.int('auto_select_limit', { min: 1 }) ?? 10,
    auto_select_operations_count: r.int('auto_select_operations_count', { min: 1 }) ?? 5,
    auto_include_miss_queries: r.bool('auto_include_miss_queries') ?? false,
    auto_like_min_token_length: r.int('auto_like_min_token_length', { min: 1 }) ?? 3,
    auto_like_max_token_length: r.int('auto_like_max_token_length', { min: 1 }) ?? 24,
    $extra: r.rest(),
    $invalidKeys: r.invalidKeys(),
    $seen: r.seen(),
  }) as QueriesConfig;
}

function readStageScoring(
  raw: Record<string, unknown>,
  path: string,
  ctx: ReadContext,
): StageScoringConfig {
  const r = new Reader(raw, path, ctx, 'scoring');
  return compact({
    mode: r.enumOf('mode', SCORING_MODE_VALUES) ?? 'expression',
    top_selection: r.enumOf('top_selection', TOP_SELECTION_VALUES) ?? 'max',
    expression: r.has('expression') ? r.str('expression') : DEFAULT_SCORE_EXPRESSION,
    on_error_score: r.float('on_error_score'),
    variables: r.strMap('variables'),
    $extra: r.rest(),
    $invalidKeys: r.invalidKeys(),
    $seen: r.seen(),
  }) as StageScoringConfig;
}

function readScoring(
  raw: Record<string, unknown> | undefined,
  path: string,
  ctx: ReadContext,
): ScoringConfig | undefined {
  if (raw === undefined) return undefined;
  const r = new Reader(raw, path, ctx, 'scoring');
  const byStage = r.obj('by_stage');
  const stages: Record<string, StageScoringConfig> = {};
  if (byStage) {
    for (const [stageName, stageRaw] of Object.entries(byStage)) {
      if (!isPlainObject(stageRaw)) {
        ctx.issues.push({
          level: 'error',
          check: 'structure',
          path: `${path}.by_stage.${stageName}`,
          message: 'ожидался объект с настройками оценки',
          section: 'scoring',
          benchmarkId: ctx.benchmarkId,
        });
        continue;
      }
      stages[stageName.trim().toLowerCase()] = readStageScoring(
        stageRaw,
        `${path}.by_stage.${stageName}`,
        ctx,
      );
    }
  }
  return compact({
    mode: r.enumOf('mode', SCORING_MODE_VALUES) ?? 'expression',
    top_selection: r.enumOf('top_selection', TOP_SELECTION_VALUES) ?? 'max',
    expression: r.has('expression') ? r.str('expression') : DEFAULT_SCORE_EXPRESSION,
    on_error_score: r.float('on_error_score'),
    variables: r.strMap('variables'),
    by_stage: byStage ? stages : undefined,
    $extra: r.rest(),
    $invalidKeys: r.invalidKeys(),
    $seen: r.seen(),
  }) as ScoringConfig;
}

function readLimits(
  r: Reader,
  key: string,
  path: string,
  ctx: ReadContext,
  section: SectionId,
): ModeLimitsConfig | undefined {
  const raw = r.obj(key);
  if (raw === undefined) return undefined;
  const result: ModeLimitsConfig = {};
  for (const [name, value] of Object.entries(raw)) {
    if (typeof value !== 'number' || !Number.isInteger(value) || value <= 0) {
      ctx.issues.push({
        level: 'error',
        check: 'structure',
        path: `${path}.${key}.${name}`,
        message: 'значение лимита должно быть целым числом > 0',
        section,
        benchmarkId: ctx.benchmarkId,
        field: key,
      });
      continue;
    }
    result[name] = value;
  }
  return result;
}

function readDatabasesSelector(
  value: unknown,
  path: string,
  ctx: ReadContext,
): DatabasesSelector | undefined {
  if (value === undefined) return undefined;
  if (value === '*') return '*';
  if (Array.isArray(value) && value.every((item) => typeof item === 'string')) {
    return value as string[];
  }
  ctx.issues.push({
    level: 'error',
    check: 'structure',
    path: `${path}.databases`,
    message: 'ожидается "*" или список имён баз',
    section: 'source',
    benchmarkId: ctx.benchmarkId,
    field: 'databases',
  });
  return undefined;
}

function readTablesSelector(
  value: unknown,
  path: string,
  ctx: ReadContext,
): TablesSelector | undefined {
  if (value === undefined) return undefined;
  if (value === '*') return '*';
  if (Array.isArray(value) && value.every((item) => typeof item === 'string')) {
    return value as string[];
  }
  if (isPlainObject(value)) {
    const result: Record<string, '*' | string[]> = {};
    let ok = true;
    for (const [db, selector] of Object.entries(value)) {
      if (selector === '*') {
        result[db] = '*';
      } else if (Array.isArray(selector) && selector.every((item) => typeof item === 'string')) {
        result[db] = selector as string[];
      } else {
        ok = false;
        ctx.issues.push({
          level: 'error',
          check: 'structure',
          path: `${path}.tables.${db}`,
          message: 'ожидается "*" или список имён таблиц',
          section: 'source',
          benchmarkId: ctx.benchmarkId,
          field: 'tables',
        });
      }
    }
    return ok ? result : undefined;
  }
  ctx.issues.push({
    level: 'error',
    check: 'structure',
    path: `${path}.tables`,
    message: 'ожидается "*", список таблиц или объект database -> таблицы',
    section: 'source',
    benchmarkId: ctx.benchmarkId,
    field: 'tables',
  });
  return undefined;
}

function readTableRule(
  raw: Record<string, unknown>,
  path: string,
  ctx: ReadContext,
): TableRuleConfig {
  const r = new Reader(raw, path, ctx, 'tables');
  return compact({
    database: r.str('database', { required: true }) ?? '',
    table: r.str('table', { required: true }) ?? '',
    test_database: r.str('test_database'),
    rules: readRules(r.obj('rules'), `${path}.rules`, ctx),
    column_order_mode: r.enumOf('column_order_mode', COLUMN_ORDER_MODE_VALUES),
    queries: readQueries(r.obj('queries'), `${path}.queries`, ctx),
    scoring: readScoring(r.obj('scoring'), `${path}.scoring`, ctx),
    insert_operations_count: r.int('insert_operations_count', { min: 1 }),
    sequential_types_top_n_for_indexes: r.int('sequential_types_top_n_for_indexes', { min: 1 }),
    sequential_top_n_limits: readLimits(r, 'sequential_top_n_limits', path, ctx, 'tables'),
    final_validation_input_top_n: r.int('final_validation_input_top_n', { min: 1 }),
    max_winners_per_parent_limits: readLimits(r, 'max_winners_per_parent_limits', path, ctx, 'tables'),
    insert_rows_per_operation_limit: r.int('insert_rows_per_operation_limit', { min: 1 }),
    source_insert_rows_per_operation_limit: r.int('source_insert_rows_per_operation_limit', {
      min: 1,
    }),
    source_insert_rows_per_operation_limits: readLimits(
      r,
      'source_insert_rows_per_operation_limits',
      path,
      ctx,
      'tables',
    ),
    insert_rows_per_operation_limits: readLimits(
      r,
      'insert_rows_per_operation_limits',
      path,
      ctx,
      'tables',
    ),
    max_benchmarks_limits: readLimits(r, 'max_benchmarks_limits', path, ctx, 'tables'),
    index_granularity_values: r.intList('index_granularity_values'),
    strategy: r.enumOf('strategy', STRATEGY_VALUES),
    order_by_first: r.str('order_by_first'),
    order_by_candidates: r.strList('order_by_candidates'),
    $extra: r.rest(),
    $invalidKeys: r.invalidKeys(),
    $seen: r.seen(),
  }) as TableRuleConfig;
}

function readBenchmark(raw: Record<string, unknown>, index: number, issues: Issue[]): BenchmarkConfig {
  const path = `benchmarks[${index}]`;
  const rawId = typeof raw.id === 'string' ? raw.id.trim() : undefined;
  const ctx: ReadContext = { issues, benchmarkId: rawId };
  const r = new Reader(raw, path, ctx, 'source');

  const tableRules = r.objList('table_rules');
  return compact({
    id: r.str('id', { required: true }) ?? '',
    connection_id: r.str('connection_id', { required: true }) ?? '',
    strategy: r.enumOf('strategy', STRATEGY_VALUES, { required: true }) ?? 'sequential_phased_topn_strategy',
    global_rules: readRules(r.obj('global_rules'), `${path}.global_rules`, ctx),
    column_order_mode: r.enumOf('column_order_mode', COLUMN_ORDER_MODE_VALUES),
    scoring: readScoring(r.obj('scoring'), `${path}.scoring`, ctx) ?? {
      mode: 'expression',
      top_selection: 'max',
      expression: DEFAULT_SCORE_EXPRESSION,
    },
    databases: readDatabasesSelector(r.any('databases'), path, ctx) ?? '*',
    tables: readTablesSelector(r.any('tables'), path, ctx) ?? '*',
    test_database: r.str('test_database'),
    insert_operations_count: r.int('insert_operations_count', { min: 1 }) ?? 100,
    sequential_types_top_n_for_indexes:
      r.int('sequential_types_top_n_for_indexes', { min: 1 }) ?? 1,
    sequential_top_n_limits: readLimits(r, 'sequential_top_n_limits', path, ctx, 'limits'),
    final_validation_input_top_n: r.int('final_validation_input_top_n', { min: 1 }),
    max_winners_per_parent_limits: readLimits(r, 'max_winners_per_parent_limits', path, ctx, 'limits'),
    insert_rows_per_operation_limit: r.int('insert_rows_per_operation_limit', { min: 1 }),
    source_insert_rows_per_operation_limit: r.int('source_insert_rows_per_operation_limit', {
      min: 1,
    }),
    source_insert_rows_per_operation_limits: readLimits(
      r,
      'source_insert_rows_per_operation_limits',
      path,
      ctx,
      'limits',
    ),
    insert_rows_per_operation_limits: readLimits(
      r,
      'insert_rows_per_operation_limits',
      path,
      ctx,
      'limits',
    ),
    max_benchmarks_limits: readLimits(r, 'max_benchmarks_limits', path, ctx, 'limits'),
    index_granularity_values: r.intList('index_granularity_values'),
    column_rules_mode: r.enumOf('column_rules_mode', RULE_SOURCE_VALUES),
    index_rules_mode: r.enumOf('index_rules_mode', RULE_SOURCE_VALUES),
    queries: readQueries(r.obj('queries'), `${path}.queries`, ctx) ?? {
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
    },
    table_rules: (tableRules ?? []).map((item, i) =>
      readTableRule(item, `${path}.table_rules[${i}]`, ctx),
    ),
    order_by_first: r.str('order_by_first'),
    order_by_candidates: r.strList('order_by_candidates'),
    $extra: r.rest(),
    $invalidKeys: r.invalidKeys(),
    $seen: r.seen(),
  }) as BenchmarkConfig;
}

/** Разбирает текст файла. Возвращает документ и список найденных проблем. */
export function parseDocument(text: string): ParseOutcome {
  const issues: Issue[] = [];
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (error) {
    return { issues: [fileIssue(`Файл не разобран как JSON: ${(error as Error).message}`)] };
  }

  if (!isPlainObject(raw)) {
    return { issues: [fileIssue('Ожидался объект JSON на верхнем уровне')] };
  }

  const hasBenchmarks = Array.isArray(raw.benchmarks);
  const isProject =
    typeof raw.connections_file === 'string' || typeof raw.rule_banks_file === 'string';

  if (!hasBenchmarks) {
    if (Array.isArray(raw.connections)) {
      return {
        issues: [
          fileIssue(
            'Это файл подключений (connections). Редактор работает с файлом бенчмарков; ' +
              'connection_id ссылается на такой файл, но не редактируется здесь.',
            '',
            'structure',
          ),
        ],
      };
    }
    if (isPlainObject(raw.rule_banks)) {
      return {
        issues: [
          fileIssue(
            'Это файл банков правил (rule_banks). Редактор работает с файлом бенчмарков; ' +
              'банк подключается по имени в rules.rule_bank.',
            '',
            'structure',
          ),
        ],
      };
    }
    if (isProject && typeof raw.benchmarks_file === 'string') {
      return {
        issues: [
          fileIssue(
            `Project-конфиг ссылается на отдельный файл бенчмарков: ${raw.benchmarks_file}. ` +
              'Откройте именно его.',
            'benchmarks_file',
            'structure',
          ),
        ],
      };
    }
    return {
      issues: [
        fileIssue('В файле нет списка benchmarks — это не конфигурация бенчмарков.', '', 'structure'),
      ],
    };
  }

  const rawBenchmarks = raw.benchmarks as unknown[];
  if (rawBenchmarks.length === 0) {
    issues.push(fileIssue('benchmarks не должен быть пустым списком', 'benchmarks', 'structure'));
  }

  const benchmarks: BenchmarkConfig[] = [];
  rawBenchmarks.forEach((item, index) => {
    if (!isPlainObject(item)) {
      issues.push(fileIssue('элемент benchmarks должен быть объектом', `benchmarks[${index}]`, 'structure'));
      return;
    }
    benchmarks.push(readBenchmark(item, index, issues));
  });

  const wrapper: Record<string, unknown> = {};
  const rootExtra: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (key === 'benchmarks') continue;
    if (isProject && ['connections_file', 'rule_banks_file', 'benchmarks_file', 'celery'].includes(key)) {
      wrapper[key] = value;
      continue;
    }
    rootExtra[key] = value;
    issues.push({
      level: 'error',
      check: 'structure',
      path: key,
      message: 'ключ верхнего уровня не поддерживается форматом файла бенчмарков',
      section: 'file',
    });
  }

  return {
    document: {
      kind: isProject ? 'project' : 'benchmarks',
      benchmarks,
      wrapper: Object.keys(wrapper).length ? wrapper : undefined,
      $extra: Object.keys(rootExtra).length ? rootExtra : undefined,
    },
    issues,
  };
}
