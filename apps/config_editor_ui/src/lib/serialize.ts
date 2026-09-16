/**
 * Сборка JSON из модели редактора.
 *
 * Гарантии:
 *   - значения по умолчанию не дописываются в файл, если их там не было
 *     (см. `$seen` — список ключей исходного файла);
 *   - `undefined` означает «поле отсутствует», пустой список остаётся пустым списком;
 *   - `$extra` (незнакомые и неразобранные ключи) возвращается в вывод.
 */

import type {
  BenchmarkConfig,
  CodecRuleConfig,
  ColumnRuleConfig,
  IndexConfig,
  IndexRuleConfig,
  OrderByRulesConfig,
  QueriesConfig,
  RulesConfig,
  ScoringConfig,
  StageScoringConfig,
  TableRuleConfig,
  TestQueryConfig,
  WithExtra,
} from '../types/config';
import type { BenchmarksDocument } from './parse';

type Json = Record<string, unknown>;

function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((item, i) => sameValue(item, b[i]));
  }
  return false;
}

class Writer {
  readonly out: Json = {};

  constructor(private readonly node: WithExtra) {}

  /**
   * Пишет ключ, если значение задано и при этом либо ключ был в исходном файле,
   * либо значение отличается от значения по умолчанию модели.
   */
  put(key: string, value: unknown, fallback?: unknown): void {
    if (value === undefined) return;
    const wasPresent = this.node.$seen?.includes(key) ?? false;
    if (!wasPresent && fallback !== undefined && sameValue(value, fallback)) return;
    this.out[key] = value;
  }

  /** Обязательное поле пишется всегда. */
  required(key: string, value: unknown): void {
    this.out[key] = value;
  }

  finish(): Json {
    if (this.node.$extra) {
      for (const [key, value] of Object.entries(this.node.$extra)) {
        this.out[key] = value;
      }
    }
    return this.out;
  }
}

function writeColumnRule(rule: ColumnRuleConfig): Json {
  const w = new Writer(rule);
  w.put('by_type', rule.by_type);
  w.put('by_name', rule.by_name);
  w.put('types', rule.types, []);
  w.put('codecs', rule.codecs, []);
  w.put('auto_generate_alternatives', rule.auto_generate_alternatives, false);
  w.put('auto_compressions_datatype', rule.auto_compressions_datatype);
  return w.finish();
}

function writeCodecRule(rule: CodecRuleConfig): Json {
  const w = new Writer(rule);
  w.put('by_type', rule.by_type);
  w.put('by_name', rule.by_name);
  w.put('codecs', rule.codecs, []);
  w.put('auto_generate_alternatives', rule.auto_generate_alternatives, false);
  w.put('auto_compressions_datatype', rule.auto_compressions_datatype);
  return w.finish();
}

function writeIndexConfig(index: IndexConfig): Json {
  const w = new Writer(index);
  w.required('type', index.type);
  // Исходная форма `"granularity": [4, 8, 16]` сохраняется как массив.
  if (index.$granularityAsArray && index.granularity_values) {
    w.required('granularity', index.granularity_values);
  } else {
    w.put('granularity', index.granularity, 1);
    w.put('granularity_values', index.granularity_values);
  }
  w.put('index_granularity_values', index.index_granularity_values);
  return w.finish();
}

function writeIndexRule(rule: IndexRuleConfig): Json {
  const w = new Writer(rule);
  w.put('by_type', rule.by_type);
  w.put('by_name', rule.by_name);
  w.put('indexes', rule.indexes.map(writeIndexConfig), []);
  w.put('auto_generate_indexes', rule.auto_generate_indexes, false);
  w.put('auto_indexes_datatype', rule.auto_indexes_datatype);
  return w.finish();
}

function writeOrderByRules(rules: OrderByRulesConfig): Json {
  const w = new Writer(rules);
  w.put('first_column', rules.first_column);
  w.put('candidates', rules.candidates);
  w.put('auto_generate_candidates', rules.auto_generate_candidates);
  return w.finish();
}

export function isEmptyRules(rules: RulesConfig): boolean {
  return (
    rules.rule_bank === undefined &&
    rules.column_rules === undefined &&
    rules.codec_rules === undefined &&
    rules.index_rules === undefined &&
    rules.order_by_rules === undefined &&
    rules.column_order === undefined &&
    rules.$extra === undefined
  );
}

function writeRules(rules: RulesConfig): Json {
  const w = new Writer(rules);
  w.put('rule_bank', rules.rule_bank);
  if (rules.column_rules) w.required('column_rules', rules.column_rules.map(writeColumnRule));
  if (rules.codec_rules) w.required('codec_rules', rules.codec_rules.map(writeCodecRule));
  if (rules.index_rules) w.required('index_rules', rules.index_rules.map(writeIndexRule));
  if (rules.order_by_rules) w.required('order_by_rules', writeOrderByRules(rules.order_by_rules));
  if (rules.column_order) w.required('column_order', rules.column_order);
  return w.finish();
}

function writeTestQuery(query: TestQueryConfig): Json {
  const w = new Writer(query);
  w.put('query_id', query.query_id);
  w.required('query', query.query);
  w.put('query_type', query.query_type, 'manual');
  w.put('cache_mode', query.cache_mode, 'warm');
  w.put('select_operations_count', query.select_operations_count, 1);
  w.put('warmup_queries', query.warmup_queries, []);
  return w.finish();
}

function writeQueries(queries: QueriesConfig): Json {
  const w = new Writer(queries);
  w.put('mode', queries.mode, 'auto');
  w.put('test_queries', queries.test_queries.map(writeTestQuery), []);
  w.put('auto_like_on_measured_columns', queries.auto_like_on_measured_columns, false);
  w.put(
    'auto_like_replace_default_auto_queries',
    queries.auto_like_replace_default_auto_queries,
    false,
  );
  w.put('auto_like_sample_rows_per_column', queries.auto_like_sample_rows_per_column, 20);
  w.put('auto_select_limit', queries.auto_select_limit, 10);
  w.put('auto_select_operations_count', queries.auto_select_operations_count, 5);
  w.put('auto_include_miss_queries', queries.auto_include_miss_queries, false);
  w.put('auto_like_min_token_length', queries.auto_like_min_token_length, 3);
  w.put('auto_like_max_token_length', queries.auto_like_max_token_length, 24);
  return w.finish();
}

function writeStageScoring(scoring: StageScoringConfig): Json {
  const w = new Writer(scoring);
  w.put('mode', scoring.mode, 'expression');
  w.put('top_selection', scoring.top_selection, 'max');
  w.put('expression', scoring.expression);
  w.put('on_error_score', scoring.on_error_score);
  w.put('variables', scoring.variables);
  return w.finish();
}

function writeScoring(scoring: ScoringConfig): Json {
  const out = writeStageScoring(scoring);
  if (scoring.by_stage) {
    const stages: Json = {};
    for (const [name, stage] of Object.entries(scoring.by_stage)) {
      stages[name] = writeStageScoring(stage);
    }
    out.by_stage = stages;
  }
  return out;
}

function writeTableRule(rule: TableRuleConfig): Json {
  const w = new Writer(rule);
  w.required('database', rule.database);
  w.required('table', rule.table);
  w.put('test_database', rule.test_database);
  w.put('strategy', rule.strategy);
  w.put('column_order_mode', rule.column_order_mode);
  w.put('order_by_first', rule.order_by_first);
  w.put('order_by_candidates', rule.order_by_candidates);
  w.put('insert_operations_count', rule.insert_operations_count);
  w.put('sequential_types_top_n_for_indexes', rule.sequential_types_top_n_for_indexes);
  w.put('sequential_top_n_limits', rule.sequential_top_n_limits);
  w.put('final_validation_input_top_n', rule.final_validation_input_top_n);
  w.put('max_winners_per_parent_limits', rule.max_winners_per_parent_limits);
  w.put('insert_rows_per_operation_limit', rule.insert_rows_per_operation_limit);
  w.put('source_insert_rows_per_operation_limit', rule.source_insert_rows_per_operation_limit);
  w.put('source_insert_rows_per_operation_limits', rule.source_insert_rows_per_operation_limits);
  w.put('insert_rows_per_operation_limits', rule.insert_rows_per_operation_limits);
  w.put('max_benchmarks_limits', rule.max_benchmarks_limits);
  w.put('index_granularity_values', rule.index_granularity_values);
  if (!isEmptyRules(rule.rules)) w.required('rules', writeRules(rule.rules));
  else if (rule.$seen?.includes('rules')) w.required('rules', writeRules(rule.rules));
  if (rule.queries) w.required('queries', writeQueries(rule.queries));
  if (rule.scoring) w.required('scoring', writeScoring(rule.scoring));
  return w.finish();
}

export function writeBenchmark(benchmark: BenchmarkConfig): Json {
  const w = new Writer(benchmark);
  w.required('id', benchmark.id);
  w.required('connection_id', benchmark.connection_id);
  w.required('strategy', benchmark.strategy);
  w.put('column_rules_mode', benchmark.column_rules_mode);
  w.put('index_rules_mode', benchmark.index_rules_mode);
  w.put('column_order_mode', benchmark.column_order_mode);
  w.put('order_by_first', benchmark.order_by_first);
  w.put('order_by_candidates', benchmark.order_by_candidates);
  w.put('databases', benchmark.databases, '*');
  w.put('tables', benchmark.tables, '*');
  w.put('test_database', benchmark.test_database);
  w.put('insert_operations_count', benchmark.insert_operations_count, 100);
  w.put('sequential_types_top_n_for_indexes', benchmark.sequential_types_top_n_for_indexes, 1);
  w.put('sequential_top_n_limits', benchmark.sequential_top_n_limits);
  w.put('final_validation_input_top_n', benchmark.final_validation_input_top_n);
  w.put('max_winners_per_parent_limits', benchmark.max_winners_per_parent_limits);
  w.put('insert_rows_per_operation_limit', benchmark.insert_rows_per_operation_limit);
  w.put('source_insert_rows_per_operation_limit', benchmark.source_insert_rows_per_operation_limit);
  w.put(
    'source_insert_rows_per_operation_limits',
    benchmark.source_insert_rows_per_operation_limits,
  );
  w.put('insert_rows_per_operation_limits', benchmark.insert_rows_per_operation_limits);
  w.put('max_benchmarks_limits', benchmark.max_benchmarks_limits);
  w.put('index_granularity_values', benchmark.index_granularity_values);

  const scoringJson = writeScoring(benchmark.scoring);
  if (Object.keys(scoringJson).length || benchmark.$seen?.includes('scoring')) {
    w.required('scoring', scoringJson);
  }

  if (!isEmptyRules(benchmark.global_rules) || benchmark.$seen?.includes('global_rules')) {
    w.required('global_rules', writeRules(benchmark.global_rules));
  }
  w.put('table_rules', benchmark.table_rules.map(writeTableRule), []);

  const queriesJson = writeQueries(benchmark.queries);
  if (Object.keys(queriesJson).length || benchmark.$seen?.includes('queries')) {
    w.required('queries', queriesJson);
  }
  return w.finish();
}

export function writeDocument(document: BenchmarksDocument): Json {
  const out: Json = {};
  if (document.wrapper) {
    for (const [key, value] of Object.entries(document.wrapper)) {
      if (key === 'benchmarks_file') continue;
      out[key] = value;
    }
  }
  out.benchmarks = document.benchmarks.map(writeBenchmark);
  if (document.$extra) {
    for (const [key, value] of Object.entries(document.$extra)) out[key] = value;
  }
  return out;
}

export function toJsonText(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`;
}
