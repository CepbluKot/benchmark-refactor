/** Короткие описания конфигурации для списка и сводки. */

import type { BenchmarkConfig } from '../types/config';
import { STRATEGY_TO_MODE } from '../types/config';
import { strategyLabel } from './vocab';

export function describeTarget(benchmark: BenchmarkConfig): string {
  const { databases, tables } = benchmark;
  const dbText = databases === '*' ? '*' : databases.join(', ');

  if (tables === '*') return `${dbText}.*`;
  if (Array.isArray(tables)) return `${dbText}: ${tables.join(', ')}`;

  const parts = Object.entries(tables).map(([db, selector]) =>
    selector === '*' ? `${db}.*` : selector.map((table) => `${db}.${table}`).join(', '),
  );
  return parts.join('; ');
}

export interface SummaryRow {
  label: string;
  value: string;
}

export function summaryRows(benchmark: BenchmarkConfig): SummaryRow[] {
  const queries = benchmark.queries;
  const globalRules = benchmark.global_rules;

  const ruleCounts = [
    globalRules.column_rules ? `типы: ${globalRules.column_rules.length}` : null,
    globalRules.codec_rules ? `кодеки: ${globalRules.codec_rules.length}` : null,
    globalRules.index_rules ? `индексы: ${globalRules.index_rules.length}` : null,
    globalRules.order_by_rules ? 'order_by: задан' : null,
    globalRules.rule_bank ? `банк: ${globalRules.rule_bank}` : null,
  ].filter(Boolean);

  return [
    { label: 'Бенчмарк', value: benchmark.id },
    { label: 'Подключение', value: benchmark.connection_id || '—' },
    {
      label: 'Стратегия',
      value: `${strategyLabel(benchmark.strategy)} (${STRATEGY_TO_MODE[benchmark.strategy]})`,
    },
    { label: 'Источник', value: describeTarget(benchmark) },
    { label: 'Временная база', value: benchmark.test_database ?? 'база источника' },
    { label: 'Правила', value: ruleCounts.length ? ruleCounts.join(', ') : 'не заданы' },
    {
      label: 'Запросы',
      value:
        queries.mode === 'auto'
          ? 'автоматические'
          : `${queries.mode}, ручных: ${queries.test_queries.length}`,
    },
    { label: 'Insert-замеров', value: String(benchmark.insert_operations_count) },
    {
      label: 'Top-N этапов',
      value: benchmark.sequential_top_n_limits
        ? Object.entries(benchmark.sequential_top_n_limits)
            .map(([stage, value]) => `${stage}=${value}`)
            .join(', ')
        : 'не задан',
    },
    {
      label: 'Отбор',
      value: `${benchmark.scoring.top_selection === 'max' ? 'больше — лучше' : 'меньше — лучше'}`,
    },
    { label: 'Формула', value: benchmark.scoring.expression ?? '—' },
    {
      label: 'Переопределения',
      value: benchmark.table_rules.length
        ? benchmark.table_rules.map((rule) => `${rule.database}.${rule.table}`).join(', ')
        : 'нет',
    },
  ];
}
