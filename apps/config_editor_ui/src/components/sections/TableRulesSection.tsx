/** Раздел «Настройки отдельных таблиц» (`table_rules`). */

import { useState } from 'react';

import type { BenchmarkConfig, TableRuleConfig } from '../../types/config';
import { emptyQueries, emptyScoring } from '../../types/config';
import { patch, removeAt, replaceAt } from '../../lib/edit';
import { STRATEGIES, strategyLabel } from '../../lib/vocab';
import { useEditor } from '../../state/editor';
import { useIssuesFor } from '../fields/Field';
import { Card, IntListField, NumberInputField, StringListField, TextInputField } from '../fields/inputs';
import { LimitsMapEditor } from '../limits/LimitsMapEditor';
import { QueriesEditor } from '../queries/QueriesEditor';
import { RulesEditor } from '../rules/RulesEditor';
import { ScoringEditor } from '../scoring/ScoringEditor';
import { OverrideSlot } from '../tables/OverrideSlot';
import { MODE_KEYS, STAGE_KEYS, WINNER_KEYS } from './LimitsSection';

function TableRuleCard({
  rule,
  index,
  benchmark,
  onChange,
  onRemove,
  duplicate,
}: {
  rule: TableRuleConfig;
  index: number;
  benchmark: BenchmarkConfig;
  onChange(next: TableRuleConfig): void;
  onRemove(): void;
  duplicate: boolean;
}): JSX.Element {
  const [open, setOpen] = useState(index === 0);
  const path = `table_rules[${index}]`;
  const issues = useIssuesFor(path);
  const errorCount = issues.filter((issue) => issue.level === 'error').length;
  const set = (changes: Partial<TableRuleConfig>) => onChange(patch(rule, changes));

  const overrides = [
    rule.strategy !== undefined,
    rule.test_database !== undefined,
    rule.column_order_mode !== undefined,
    rule.queries !== undefined,
    rule.scoring !== undefined,
    rule.order_by_first !== undefined,
    rule.order_by_candidates !== undefined,
    rule.index_granularity_values !== undefined,
    rule.insert_operations_count !== undefined,
    rule.sequential_top_n_limits !== undefined,
    rule.max_winners_per_parent_limits !== undefined,
    rule.final_validation_input_top_n !== undefined,
    rule.sequential_types_top_n_for_indexes !== undefined,
    rule.insert_rows_per_operation_limit !== undefined,
    rule.source_insert_rows_per_operation_limit !== undefined,
    rule.insert_rows_per_operation_limits !== undefined,
    rule.source_insert_rows_per_operation_limits !== undefined,
    rule.max_benchmarks_limits !== undefined,
    Object.keys(rule.rules).some((key) => !key.startsWith('$')),
  ].filter(Boolean).length;

  return (
    <section className="card">
      <div className="card-head">
        <button className="row-toggle" type="button" onClick={() => setOpen(!open)}>
          {open ? '▾' : '▸'}
        </button>
        <span className="mono">
          {rule.database || '—'}.{rule.table || '—'}
        </span>
        <span className="spacer" style={{ marginLeft: 'auto' }}>
          <div className="inline-actions">
            {duplicate ? <span className="badge badge-danger">дубликат таблицы</span> : null}
            {errorCount ? (
              <span className="badge badge-danger">
                <span className="dot dot-danger" /> {errorCount}
              </span>
            ) : null}
            <span className="badge badge-neutral">переопределений: {overrides}</span>
            <button className="btn btn-sm btn-ghost btn-danger" type="button" onClick={onRemove}>
              Удалить
            </button>
          </div>
        </span>
      </div>

      {open ? (
        <div className="card-body stack">
          <div className="grid-2">
            <TextInputField
              label="База данных"
              jsonKey="database"
              path={`${path}.database`}
              value={rule.database}
              onChange={(next) => set({ database: next ?? '' })}
            />
            <TextInputField
              label="Таблица"
              jsonKey="table"
              path={`${path}.table`}
              value={rule.table}
              onChange={(next) => set({ table: next ?? '' })}
            />
          </div>

          <div className="divider" />

          <div className="grid-2">
            <OverrideSlot
              label="Стратегия"
              jsonKey="strategy"
              overridden={rule.strategy !== undefined}
              inherited={`${strategyLabel(benchmark.strategy)} · ${benchmark.strategy}`}
              onDefine={() => set({ strategy: benchmark.strategy })}
              onReset={() => set({ strategy: undefined })}
            >
              <select
                className="control"
                value={rule.strategy ?? ''}
                onChange={(event) =>
                  set({ strategy: event.target.value as TableRuleConfig['strategy'] })
                }
              >
                {STRATEGIES.map((choice) => (
                  <option key={choice.value} value={choice.value}>
                    {choice.label} — {choice.value}
                  </option>
                ))}
              </select>
            </OverrideSlot>

            <OverrideSlot
              label="База для временных таблиц"
              jsonKey="test_database"
              overridden={rule.test_database !== undefined}
              inherited={benchmark.test_database ?? 'база источника'}
              onDefine={() => set({ test_database: benchmark.test_database ?? 'benchmark_tmp' })}
              onReset={() => set({ test_database: undefined })}
            >
              <input
                className="control mono"
                value={rule.test_database ?? ''}
                onChange={(event) => set({ test_database: event.target.value })}
              />
            </OverrideSlot>

            <OverrideSlot
              label="Режим порядка колонок"
              jsonKey="column_order_mode"
              overridden={rule.column_order_mode !== undefined}
              inherited={benchmark.column_order_mode ?? 'не задан'}
              onDefine={() => set({ column_order_mode: 'compressed_size_desc' })}
              onReset={() => set({ column_order_mode: undefined })}
            >
              <select
                className="control"
                value={rule.column_order_mode ?? 'compressed_size_desc'}
                onChange={() => set({ column_order_mode: 'compressed_size_desc' })}
              >
                <option value="compressed_size_desc">
                  По убыванию сжатого размера — compressed_size_desc
                </option>
              </select>
            </OverrideSlot>

            <OverrideSlot
              label="Первая колонка ORDER BY"
              jsonKey="order_by_first"
              overridden={rule.order_by_first !== undefined}
              inherited={
                benchmark.order_by_first ??
                benchmark.global_rules.order_by_rules?.first_column ??
                'не задана'
              }
              onDefine={() => set({ order_by_first: benchmark.order_by_first ?? '' })}
              onReset={() => set({ order_by_first: undefined })}
            >
              <input
                className="control mono"
                value={rule.order_by_first ?? ''}
                onChange={(event) => set({ order_by_first: event.target.value })}
              />
            </OverrideSlot>
          </div>

          <OverrideSlot
            label="Кандидаты ORDER BY"
            jsonKey="order_by_candidates"
            overridden={rule.order_by_candidates !== undefined}
            inherited={
              benchmark.order_by_candidates?.join(', ') ??
              benchmark.global_rules.order_by_rules?.candidates?.join(', ') ??
              'не заданы'
            }
            onDefine={() => set({ order_by_candidates: benchmark.order_by_candidates ?? [] })}
            onReset={() => set({ order_by_candidates: undefined })}
          >
            <StringListField
              label="Кандидаты"
              jsonKey="order_by_candidates"
              path={`${path}.order_by_candidates`}
              value={rule.order_by_candidates}
              onChange={(next) => set({ order_by_candidates: next })}
            />
          </OverrideSlot>

          <div className="divider" />

          <div>
            <div className="field-label" style={{ marginBottom: 8 }}>
              <span>Правила вариантов</span>
              <span className="field-key">{path}.rules</span>
            </div>
            <RulesEditor
              rules={rule.rules}
              path={`${path}.rules`}
              inheritable
              onChange={(next) => set({ rules: next })}
            />
          </div>

          <div className="divider" />

          <OverrideSlot
            label="Тестовые запросы"
            jsonKey="queries"
            overridden={rule.queries !== undefined}
            inherited={`режим ${benchmark.queries.mode}, ручных запросов: ${benchmark.queries.test_queries.length}`}
            onDefine={() => set({ queries: emptyQueries() })}
            onReset={() => set({ queries: undefined })}
          >
            {rule.queries ? (
              <QueriesEditor
                queries={rule.queries}
                path={`${path}.queries`}
                onChange={(next) => set({ queries: next })}
              />
            ) : null}
          </OverrideSlot>

          <div className="divider" />

          <OverrideSlot
            label="Оценка"
            jsonKey="scoring"
            overridden={rule.scoring !== undefined}
            inherited={benchmark.scoring.expression ?? 'формула не задана'}
            onDefine={() => set({ scoring: emptyScoring() })}
            onReset={() => set({ scoring: undefined })}
          >
            {rule.scoring ? (
              <ScoringEditor
                scoring={rule.scoring}
                path={`${path}.scoring`}
                onChange={(next) => set({ scoring: next })}
              />
            ) : null}
          </OverrideSlot>

          <div className="divider" />

          <div className="grid-2">
            <NumberInputField
              label="Количество insert-замеров"
              jsonKey="insert_operations_count"
              path={`${path}.insert_operations_count`}
              value={rule.insert_operations_count}
              onChange={(next) => set({ insert_operations_count: next })}
              optional
              unit="операций"
              defaultHint={`наследуется: ${benchmark.insert_operations_count}`}
            />
            <NumberInputField
              label="Top-N типов для фазы индексов"
              jsonKey="sequential_types_top_n_for_indexes"
              path={`${path}.sequential_types_top_n_for_indexes`}
              value={rule.sequential_types_top_n_for_indexes}
              onChange={(next) => set({ sequential_types_top_n_for_indexes: next })}
              optional
              unit="кандидатов"
              defaultHint={`наследуется: ${benchmark.sequential_types_top_n_for_indexes}`}
            />
            <NumberInputField
              label="Строк за вставку в кандидата"
              jsonKey="insert_rows_per_operation_limit"
              path={`${path}.insert_rows_per_operation_limit`}
              value={rule.insert_rows_per_operation_limit}
              onChange={(next) => set({ insert_rows_per_operation_limit: next })}
              optional
              unit="строк"
              defaultHint={
                benchmark.insert_rows_per_operation_limit === undefined
                  ? 'на уровне бенчмарка тоже не задано'
                  : `наследуется: ${benchmark.insert_rows_per_operation_limit}`
              }
            />
            <NumberInputField
              label="Строк за вставку в baseline"
              jsonKey="source_insert_rows_per_operation_limit"
              path={`${path}.source_insert_rows_per_operation_limit`}
              value={rule.source_insert_rows_per_operation_limit}
              onChange={(next) => set({ source_insert_rows_per_operation_limit: next })}
              optional
              unit="строк"
              defaultHint={
                benchmark.source_insert_rows_per_operation_limit === undefined
                  ? 'на уровне бенчмарка тоже не задано'
                  : `наследуется: ${benchmark.source_insert_rows_per_operation_limit}`
              }
            />
            <NumberInputField
              label="Кандидатов на вход финальной проверки"
              jsonKey="final_validation_input_top_n"
              path={`${path}.final_validation_input_top_n`}
              value={rule.final_validation_input_top_n}
              onChange={(next) => set({ final_validation_input_top_n: next })}
              optional
              unit="кандидатов"
              defaultHint={
                benchmark.final_validation_input_top_n === undefined
                  ? 'на уровне бенчмарка тоже не задано'
                  : `наследуется: ${benchmark.final_validation_input_top_n}`
              }
            />
            <IntListField
              label="Значения index_granularity"
              jsonKey="index_granularity_values"
              path={`${path}.index_granularity_values`}
              value={rule.index_granularity_values}
              onChange={(next) => set({ index_granularity_values: next })}
              hint={
                benchmark.index_granularity_values
                  ? `наследуется: ${benchmark.index_granularity_values.join(', ')}`
                  : undefined
              }
            />
          </div>

          <div className="stack-sm">
            <div className="field-label">
              <span>Top-N по этапам</span>
              <span className="field-key">sequential_top_n_limits</span>
            </div>
            <LimitsMapEditor
              jsonKey="sequential_top_n_limits"
              unit="победителей"
              keys={STAGE_KEYS}
              value={rule.sequential_top_n_limits}
              onChange={(next) => set({ sequential_top_n_limits: next })}
            />
          </div>

          <div className="stack-sm">
            <div className="field-label">
              <span>Победителей на одного parent</span>
              <span className="field-key">max_winners_per_parent_limits</span>
            </div>
            <LimitsMapEditor
              jsonKey="max_winners_per_parent_limits"
              unit="победителей"
              keys={WINNER_KEYS}
              value={rule.max_winners_per_parent_limits}
              onChange={(next) => set({ max_winners_per_parent_limits: next })}
            />
          </div>

          <div className="stack-sm">
            <div className="field-label">
              <span>Лимиты вставки по режимам</span>
              <span className="field-key">insert_rows_per_operation_limits</span>
            </div>
            <LimitsMapEditor
              jsonKey="insert_rows_per_operation_limits"
              unit="строк"
              keys={MODE_KEYS}
              value={rule.insert_rows_per_operation_limits}
              onChange={(next) => set({ insert_rows_per_operation_limits: next })}
            />
          </div>

          <div className="stack-sm">
            <div className="field-label">
              <span>Лимиты вставки в baseline по режимам</span>
              <span className="field-key">source_insert_rows_per_operation_limits</span>
            </div>
            <LimitsMapEditor
              jsonKey="source_insert_rows_per_operation_limits"
              unit="строк"
              keys={MODE_KEYS}
              value={rule.source_insert_rows_per_operation_limits}
              onChange={(next) => set({ source_insert_rows_per_operation_limits: next })}
            />
          </div>

          <div className="stack-sm">
            <div className="field-label">
              <span>Лимиты числа кандидатов</span>
              <span className="field-key">max_benchmarks_limits</span>
            </div>
            <LimitsMapEditor
              jsonKey="max_benchmarks_limits"
              unit="кандидатов"
              keys={STAGE_KEYS}
              value={rule.max_benchmarks_limits}
              onChange={(next) => set({ max_benchmarks_limits: next })}
            />
          </div>
        </div>
      ) : null}
    </section>
  );
}

export function TableRulesSection({ benchmark }: { benchmark: BenchmarkConfig }): JSX.Element {
  const { updateSelected } = useEditor();
  const rules = benchmark.table_rules;

  const counts = new Map<string, number>();
  for (const rule of rules) {
    const key = `${rule.database}.${rule.table}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  const setRules = (next: TableRuleConfig[]) =>
    updateSelected((current) => patch(current, { table_rules: next }));

  return (
    <>
      <div className="section-head">
        <h2>Настройки отдельных таблиц</h2>
        <p>
          Локальные переопределения для конкретной пары <code>database</code> +{' '}
          <code>table</code>. Всё, что не переопределено, берётся из общих настроек бенчмарка.
        </p>
      </div>

      {rules.length === 0 ? (
        <div className="notice">
          <strong>Переопределений нет</strong>
          Все выбранные таблицы обрабатываются по общим настройкам бенчмарка.
        </div>
      ) : null}

      {rules.map((rule, index) => (
        <TableRuleCard
          key={index}
          rule={rule}
          index={index}
          benchmark={benchmark}
          duplicate={(counts.get(`${rule.database}.${rule.table}`) ?? 0) > 1}
          onChange={(next) => setRules(replaceAt(rules, index, next))}
          onRemove={() => setRules(removeAt(rules, index))}
        />
      ))}

      <Card title="Добавить таблицу">
        <button
          className="btn"
          type="button"
          onClick={() =>
            setRules([
              ...rules,
              { database: '', table: '', rules: {}, $seen: ['database', 'table'] },
            ])
          }
        >
          Добавить переопределение
        </button>
      </Card>
    </>
  );
}
