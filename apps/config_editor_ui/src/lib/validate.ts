/**
 * Проверка структуры и локальных ограничений модели (уровень 2)
 * и ссылок между файлами, если справочные файлы загружены (уровень 3).
 *
 * Уровни 4 (проверка движком) и 5 (подключение и объекты БД) отсюда
 * недостижимы — их закрывает серверная интеграция.
 */

import type {
  BenchmarkConfig,
  CodecRuleConfig,
  ColumnRuleConfig,
  IndexRuleConfig,
  QueriesConfig,
  RulesConfig,
  ScoringConfig,
  StageScoringConfig,
  TableRuleConfig,
} from '../types/config';
import type { Issue, SectionId } from './issues';
import { isValidVariableName, lintExpression } from './scoringLint';

export interface ReferenceData {
  /** id из загруженного файла подключений; null — файл не загружен. */
  connectionIds: string[] | null;
  /** имена банков правил; null — файл не загружен. */
  ruleBankIds: string[] | null;
}

interface Sink {
  issues: Issue[];
  benchmarkId: string;
}

function push(
  sink: Sink,
  section: SectionId,
  path: string,
  message: string,
  field?: string,
  level: Issue['level'] = 'error',
  check: Issue['check'] = 'structure',
): void {
  sink.issues.push({
    level,
    check,
    path,
    message,
    section,
    benchmarkId: sink.benchmarkId,
    field,
  });
}

function checkMatchers(
  rule: ColumnRuleConfig | CodecRuleConfig | IndexRuleConfig,
  path: string,
  sink: Sink,
): void {
  if (rule.by_name === undefined && rule.by_type === undefined) {
    push(sink, 'rules', path, 'нужно задать хотя бы by_type или by_name', 'by_type');
    return;
  }
  if (rule.by_name !== undefined && rule.by_type === undefined) {
    push(
      sink,
      'rules',
      `${path}.by_type`,
      `by_name=${rule.by_name} задан без by_type — укажи тип колонки явно`,
      'by_type',
    );
  }
}

function checkPositiveIntList(
  values: number[] | undefined,
  path: string,
  sink: Sink,
  section: SectionId,
  field: string,
): void {
  if (values === undefined) return;
  if (values.length === 0) {
    push(sink, section, path, 'список не должен быть пустым', field);
    return;
  }
  const seen = new Set<number>();
  values.forEach((value, index) => {
    if (!Number.isInteger(value) || value <= 0) {
      push(sink, section, `${path}[${index}]`, 'каждое значение должно быть целым числом > 0', field);
    }
    if (seen.has(value)) {
      push(sink, section, `${path}[${index}]`, `значение ${value} повторяется`, field, 'warning');
    }
    seen.add(value);
  });
}

function checkRules(rules: RulesConfig, path: string, sink: Sink, reference: ReferenceData): void {
  if (rules.rule_bank !== undefined && reference.ruleBankIds !== null) {
    if (!reference.ruleBankIds.includes(rules.rule_bank)) {
      push(
        sink,
        'rules',
        `${path}.rule_bank`,
        `банк правил ${rules.rule_bank} не найден в загруженном файле rule_banks`,
        'rule_bank',
        'error',
        'cross-file',
      );
    }
  }

  rules.column_rules?.forEach((rule, index) => {
    checkMatchers(rule, `${path}.column_rules[${index}]`, sink);
    if (
      rule.types.length === 0 &&
      rule.codecs.length === 0 &&
      !rule.auto_generate_alternatives
    ) {
      push(
        sink,
        'rules',
        `${path}.column_rules[${index}]`,
        'правило не порождает вариантов: нет types, нет codecs и выключена автогенерация',
        'types',
        'warning',
      );
    }
  });

  rules.codec_rules?.forEach((rule, index) => {
    checkMatchers(rule, `${path}.codec_rules[${index}]`, sink);
    if (rule.codecs.length === 0 && !rule.auto_generate_alternatives) {
      push(
        sink,
        'rules',
        `${path}.codec_rules[${index}]`,
        'правило не порождает вариантов: нет codecs и выключена автогенерация',
        'codecs',
        'warning',
      );
    }
  });

  rules.index_rules?.forEach((rule, index) => {
    const rulePath = `${path}.index_rules[${index}]`;
    checkMatchers(rule, rulePath, sink);
    if (rule.indexes.length === 0 && !rule.auto_generate_indexes) {
      push(
        sink,
        'rules',
        rulePath,
        'правило не порождает вариантов: нет indexes и выключена автогенерация',
        'indexes',
        'warning',
      );
    }
    rule.indexes.forEach((index_, indexPos) => {
      const indexPath = `${rulePath}.indexes[${indexPos}]`;
      if (!index_.type.trim()) {
        push(sink, 'rules', `${indexPath}.type`, 'тип индекса обязателен', 'type');
      }
      if (!Number.isInteger(index_.granularity) || index_.granularity < 1) {
        push(sink, 'rules', `${indexPath}.granularity`, 'granularity должен быть целым числом >= 1', 'granularity');
      }
      checkPositiveIntList(index_.granularity_values, `${indexPath}.granularity_values`, sink, 'rules', 'granularity_values');
      checkPositiveIntList(
        index_.index_granularity_values,
        `${indexPath}.index_granularity_values`,
        sink,
        'rules',
        'index_granularity_values',
      );
    });
  });

  if (rules.order_by_rules?.candidates !== undefined && rules.order_by_rules.candidates.length === 0) {
    push(sink, 'rules', `${path}.order_by_rules.candidates`, 'список не должен быть пустым', 'candidates');
  }
}

function checkQueries(queries: QueriesConfig, path: string, sink: Sink): void {
  if (queries.mode === 'manual' && queries.test_queries.length === 0) {
    push(sink, 'queries', `${path}.test_queries`, 'mode=manual требует хотя бы одного test_query', 'test_queries');
  }
  if (queries.auto_like_max_token_length < queries.auto_like_min_token_length) {
    push(
      sink,
      'queries',
      `${path}.auto_like_max_token_length`,
      'auto_like_max_token_length должен быть >= auto_like_min_token_length',
      'auto_like_max_token_length',
    );
  }

  const seenIds = new Set<string>();
  queries.test_queries.forEach((query, index) => {
    const queryPath = `${path}.test_queries[${index}]`;
    if (!query.query.trim()) {
      push(sink, 'queries', `${queryPath}.query`, 'query не должен быть пустым', 'query');
    }
    if (query.query_id !== undefined) {
      if (seenIds.has(query.query_id)) {
        push(sink, 'queries', `${queryPath}.query_id`, `query_id=${query.query_id} повторяется в test_queries`, 'query_id');
      }
      seenIds.add(query.query_id);
    }
    if (query.cache_mode === 'cold' && query.warmup_queries.length > 0) {
      push(
        sink,
        'queries',
        `${queryPath}.warmup_queries`,
        'warmup_queries нельзя задавать для query с cache_mode=cold',
        'warmup_queries',
      );
    }
    if (!Number.isInteger(query.select_operations_count) || query.select_operations_count < 1) {
      push(sink, 'queries', `${queryPath}.select_operations_count`, 'значение должно быть целым числом > 0', 'select_operations_count');
    }
    if (queries.mode === 'auto') {
      push(
        sink,
        'queries',
        queryPath,
        'запрос задан, но mode=auto — ручные запросы не попадут в замеры',
        'mode',
        'warning',
      );
    }
  });
}

function checkScoringBlock(
  scoring: StageScoringConfig,
  path: string,
  sink: Sink,
  section: SectionId,
): void {
  if (scoring.expression === undefined || !scoring.expression.trim()) {
    push(sink, section, `${path}.expression`, 'mode=expression требует непустой expression', 'expression');
    return;
  }

  const declared: string[] = [];
  if (scoring.variables !== undefined) {
    if (Object.keys(scoring.variables).length === 0) {
      push(sink, section, `${path}.variables`, 'variables не должен быть пустым', 'variables');
    }
    for (const [name, expression] of Object.entries(scoring.variables)) {
      const nameProblem = isValidVariableName(name);
      if (nameProblem) {
        push(sink, section, `${path}.variables.${name}`, nameProblem, 'variables');
      }
      // Движок разрешает ссылаться только на переменные, объявленные выше.
      for (const problem of lintExpression(expression, declared)) {
        push(sink, section, `${path}.variables.${name}`, `локальная проверка: ${problem.message}`, 'variables');
      }
      declared.push(name);
    }
  }

  for (const problem of lintExpression(scoring.expression, declared)) {
    push(sink, section, `${path}.expression`, `локальная проверка: ${problem.message}`, 'expression');
  }
}

function checkScoring(scoring: ScoringConfig, path: string, sink: Sink, section: SectionId): void {
  checkScoringBlock(scoring, path, sink, section);
  if (scoring.by_stage !== undefined) {
    if (Object.keys(scoring.by_stage).length === 0) {
      push(sink, section, `${path}.by_stage`, 'by_stage не должен быть пустым', 'by_stage');
    }
    for (const [stage, stageScoring] of Object.entries(scoring.by_stage)) {
      if (!stage.trim()) {
        push(sink, section, `${path}.by_stage`, 'by_stage содержит пустое имя стадии', 'by_stage');
      }
      checkScoringBlock(stageScoring, `${path}.by_stage.${stage}`, sink, section);
    }
  }
}

function checkTableRule(rule: TableRuleConfig, path: string, sink: Sink, reference: ReferenceData): void {
  if (!rule.database.trim() || !rule.table.trim()) {
    push(sink, 'tables', path, 'database и table не должны быть пустыми', 'database');
  }
  checkRules(rule.rules, `${path}.rules`, sink, reference);
  if (rule.queries) checkQueries(rule.queries, `${path}.queries`, sink);
  if (rule.scoring) checkScoring(rule.scoring, `${path}.scoring`, sink, 'tables');
  checkPositiveIntList(rule.index_granularity_values, `${path}.index_granularity_values`, sink, 'tables', 'index_granularity_values');
  if (rule.order_by_candidates !== undefined && rule.order_by_candidates.length === 0) {
    push(sink, 'tables', `${path}.order_by_candidates`, 'список не должен быть пустым', 'order_by_candidates');
  }
}

function checkSelectors(benchmark: BenchmarkConfig, path: string, sink: Sink): void {
  const { databases, tables } = benchmark;
  if (Array.isArray(databases) && databases.length === 0) {
    push(sink, 'source', `${path}.databases`, 'databases не может быть пустым списком', 'databases');
  }
  if (Array.isArray(tables) && tables.length === 0) {
    push(sink, 'source', `${path}.tables`, 'tables не может быть пустым списком', 'tables');
  }
  if (!Array.isArray(tables) && typeof tables === 'object') {
    const keys = Object.keys(tables);
    if (keys.length === 0) {
      push(sink, 'source', `${path}.tables`, 'tables map не может быть пустым', 'tables');
    }
    if (Array.isArray(databases)) {
      const extra = keys.filter((key) => !databases.includes(key)).sort();
      if (extra.length) {
        push(
          sink,
          'source',
          `${path}.tables`,
          `tables содержит БД вне databases: ${extra.join(', ')}`,
          'tables',
        );
      }
    }
    for (const [db, selector] of Object.entries(tables)) {
      if (Array.isArray(selector) && selector.length === 0) {
        push(sink, 'source', `${path}.tables.${db}`, `tables[${db}] не может быть пустым списком`, 'tables');
      }
    }
  }
}

export function validateBenchmark(
  benchmark: BenchmarkConfig,
  index: number,
  reference: ReferenceData,
): Issue[] {
  const path = `benchmarks[${index}]`;
  const sink: Sink = { issues: [], benchmarkId: benchmark.id };

  if (!benchmark.id.trim()) push(sink, 'source', `${path}.id`, 'id обязателен', 'id');
  if (!benchmark.connection_id.trim()) {
    push(sink, 'source', `${path}.connection_id`, 'connection_id обязателен', 'connection_id');
  } else if (reference.connectionIds !== null && !reference.connectionIds.includes(benchmark.connection_id)) {
    push(
      sink,
      'source',
      `${path}.connection_id`,
      `подключение ${benchmark.connection_id} не найдено в загруженном файле connections`,
      'connection_id',
      'error',
      'cross-file',
    );
  }

  checkSelectors(benchmark, path, sink);
  checkRules(benchmark.global_rules, `${path}.global_rules`, sink, reference);
  checkQueries(benchmark.queries, `${path}.queries`, sink);
  checkScoring(benchmark.scoring, `${path}.scoring`, sink, 'scoring');
  checkPositiveIntList(
    benchmark.index_granularity_values,
    `${path}.index_granularity_values`,
    sink,
    'limits',
    'index_granularity_values',
  );
  if (benchmark.order_by_candidates !== undefined && benchmark.order_by_candidates.length === 0) {
    push(sink, 'rules', `${path}.order_by_candidates`, 'список не должен быть пустым', 'order_by_candidates');
  }

  const seenTargets = new Set<string>();
  benchmark.table_rules.forEach((rule, ruleIndex) => {
    const rulePath = `${path}.table_rules[${ruleIndex}]`;
    const key = `${rule.database}.${rule.table}`;
    if (seenTargets.has(key)) {
      push(sink, 'tables', rulePath, `table_rules содержит дубликат для ${key}`, 'database');
    }
    seenTargets.add(key);
    checkTableRule(rule, rulePath, sink, reference);
  });

  return sink.issues;
}

export function validateBenchmarks(
  benchmarks: BenchmarkConfig[],
  reference: ReferenceData,
): Issue[] {
  const issues: Issue[] = [];
  if (benchmarks.length === 0) {
    issues.push({
      level: 'error',
      check: 'structure',
      path: 'benchmarks',
      message: 'benchmarks не должен быть пустым списком',
      section: 'file',
    });
  }

  const seenIds = new Map<string, number>();
  benchmarks.forEach((benchmark, index) => {
    const previous = seenIds.get(benchmark.id);
    if (previous !== undefined) {
      issues.push({
        level: 'error',
        check: 'structure',
        path: `benchmarks[${index}].id`,
        message: `id ${benchmark.id} повторяется (уже используется в benchmarks[${previous}])`,
        section: 'source',
        benchmarkId: benchmark.id,
        field: 'id',
      });
    } else {
      seenIds.set(benchmark.id, index);
    }
    issues.push(...validateBenchmark(benchmark, index, reference));
  });
  return issues;
}

/**
 * Ключи, которые не поддерживаются моделью (`extra = "forbid"`) или не были
 * разобраны из-за неподдерживаемого типа. Они сохраняются в `$extra`
 * и остаются ошибкой до тех пор, пока их не уберут из файла.
 */
export function collectExtraIssues(benchmarks: BenchmarkConfig[]): Issue[] {
  const issues: Issue[] = [];

  const report = (
    node: { $extra?: Record<string, unknown>; $invalidKeys?: string[] } | undefined,
    path: string,
    section: SectionId,
    benchmarkId: string,
  ): void => {
    if (!node?.$extra) return;
    const invalid = new Set(node.$invalidKeys ?? []);
    for (const key of Object.keys(node.$extra)) {
      issues.push({
        level: 'error',
        check: 'structure',
        path: `${path}.${key}`,
        message: invalid.has(key)
          ? 'значение поля имеет неподдерживаемый тип и не разобрано; исходное содержимое сохранено при экспорте'
          : 'поле не поддерживается моделью конфигурации и будет отклонено движком',
        section,
        benchmarkId,
        field: key,
      });
    }
  };

  const reportRules = (rules: RulesConfig, path: string, id: string): void => {
    report(rules, path, 'rules', id);
    rules.column_rules?.forEach((rule, i) => report(rule, `${path}.column_rules[${i}]`, 'rules', id));
    rules.codec_rules?.forEach((rule, i) => report(rule, `${path}.codec_rules[${i}]`, 'rules', id));
    rules.index_rules?.forEach((rule, i) => {
      report(rule, `${path}.index_rules[${i}]`, 'rules', id);
      rule.indexes.forEach((index, j) =>
        report(index, `${path}.index_rules[${i}].indexes[${j}]`, 'rules', id),
      );
    });
    report(rules.order_by_rules, `${path}.order_by_rules`, 'rules', id);
  };

  const reportQueries = (queries: QueriesConfig, path: string, id: string): void => {
    report(queries, path, 'queries', id);
    queries.test_queries.forEach((query, i) =>
      report(query, `${path}.test_queries[${i}]`, 'queries', id),
    );
  };

  const reportScoring = (
    scoring: ScoringConfig,
    path: string,
    id: string,
    section: SectionId,
  ): void => {
    report(scoring, path, section, id);
    for (const [stage, stageScoring] of Object.entries(scoring.by_stage ?? {})) {
      report(stageScoring, `${path}.by_stage.${stage}`, section, id);
    }
  };

  benchmarks.forEach((benchmark, index) => {
    const path = `benchmarks[${index}]`;
    const id = benchmark.id;
    report(benchmark, path, 'source', id);
    reportRules(benchmark.global_rules, `${path}.global_rules`, id);
    reportQueries(benchmark.queries, `${path}.queries`, id);
    reportScoring(benchmark.scoring, `${path}.scoring`, id, 'scoring');
    benchmark.table_rules.forEach((rule, i) => {
      const rulePath = `${path}.table_rules[${i}]`;
      report(rule, rulePath, 'tables', id);
      reportRules(rule.rules, `${rulePath}.rules`, id);
      if (rule.queries) reportQueries(rule.queries, `${rulePath}.queries`, id);
      if (rule.scoring) reportScoring(rule.scoring, `${rulePath}.scoring`, id, 'tables');
    });
  });

  return issues;
}
