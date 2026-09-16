/** Раздел «Правила вариантов»: что именно разрешено менять в схеме таблицы. */

import type { BenchmarkConfig } from '../../types/config';
import { patch } from '../../lib/edit';
import { RULE_SOURCE_MODES } from '../../lib/vocab';
import { useEditor } from '../../state/editor';
import { RulesEditor } from '../rules/RulesEditor';
import { Card, Disclosure, RadioCards, StringListField, TextInputField } from '../fields/inputs';

function OrderBySources({ benchmark }: { benchmark: BenchmarkConfig }): JSX.Element {
  const rules = benchmark.global_rules.order_by_rules;
  const rows: { path: string; value: string; note: string }[] = [
    {
      path: 'benchmarks[].order_by_first',
      value: benchmark.order_by_first ?? '—',
      note: 'Приоритет 2 (после table_rules[].order_by_first).',
    },
    {
      path: 'benchmarks[].order_by_candidates',
      value: benchmark.order_by_candidates?.join(', ') ?? '—',
      note: 'Приоритет 2 (после table_rules[].order_by_candidates).',
    },
    {
      path: 'global_rules.order_by_rules.first_column',
      value: rules?.first_column ?? '—',
      note: 'Приоритет 3: используется, если order_by_first не задан.',
    },
    {
      path: 'global_rules.order_by_rules.candidates',
      value: rules?.candidates?.join(', ') ?? '—',
      note: 'Приоритет 3: используется, если order_by_candidates не задан.',
    },
    {
      path: 'global_rules.order_by_rules.auto_generate_candidates',
      value:
        rules?.auto_generate_candidates === undefined
          ? '—'
          : String(rules.auto_generate_candidates),
      note: 'Единственный источник: на уровне бенчмарка такого поля нет.',
    },
  ];

  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Путь в конфигурации</th>
            <th>Текущее значение</th>
            <th>Как применяется</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.path}>
              <td className="mono">{row.path}</td>
              <td className="mono">{row.value}</td>
              <td className="muted">{row.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RulesSection({ benchmark }: { benchmark: BenchmarkConfig }): JSX.Element {
  const { updateSelected } = useEditor();
  const update = (changes: Partial<BenchmarkConfig>) =>
    updateSelected((current) => patch(current, changes));

  return (
    <>
      <div className="section-head">
        <h2>Правила вариантов</h2>
        <p>
          Общие правила бенчмарка: <code>global_rules</code>. Они определяют, какие типы,
          кодеки, индексы и ключи сортировки движок имеет право проверять.
        </p>
      </div>

      <Card title="Общие правила" subtitle="global_rules">
        <RulesEditor
          rules={benchmark.global_rules}
          path="global_rules"
          inheritable={false}
          onChange={(next) => update({ global_rules: next })}
        />
      </Card>

      <Card
        title="Источник правил"
        subtitle="column_rules_mode / index_rules_mode"
        note="Заданный локально список правил замещает банковский список того же вида — списки не склеиваются."
      >
        <div className="grid-2">
          <div className="stack-sm">
            <div className="field-label">
              <span>Правила колонок</span>
              <span className="field-key">column_rules_mode</span>
            </div>
            <RadioCards
              name="column_rules_mode"
              value={benchmark.column_rules_mode}
              choices={RULE_SOURCE_MODES}
              onChange={(next) => update({ column_rules_mode: next })}
            />
            {benchmark.column_rules_mode === undefined ? (
              <div className="faint">
                Поле не задано — действует режим по умолчанию, выбранный движком.
              </div>
            ) : (
              <button
                className="btn btn-sm btn-ghost"
                type="button"
                onClick={() => update({ column_rules_mode: undefined })}
              >
                Убрать поле
              </button>
            )}
          </div>
          <div className="stack-sm">
            <div className="field-label">
              <span>Правила индексов</span>
              <span className="field-key">index_rules_mode</span>
            </div>
            <RadioCards
              name="index_rules_mode"
              value={benchmark.index_rules_mode}
              choices={RULE_SOURCE_MODES}
              onChange={(next) => update({ index_rules_mode: next })}
            />
            {benchmark.index_rules_mode === undefined ? (
              <div className="faint">
                Поле не задано — действует режим по умолчанию, выбранный движком.
              </div>
            ) : (
              <button
                className="btn btn-sm btn-ghost"
                type="button"
                onClick={() => update({ index_rules_mode: undefined })}
              >
                Убрать поле
              </button>
            )}
          </div>
        </div>
      </Card>

      <Card
        title="ORDER BY: где что задано"
        subtitle="три разных пути в конфигурации"
        note="Порядок применения подтверждён по коду планировщика: table_rules[] → benchmarks[] → global_rules.order_by_rules. Импорт и экспорт сохраняют исходное расположение полей."
      >
        <div className="stack">
          <OrderBySources benchmark={benchmark} />
          <Disclosure title="Редактировать поля уровня бенчмарка">
            <div className="grid-2">
              <TextInputField
                label="Первая колонка ORDER BY"
                jsonKey="order_by_first"
                value={benchmark.order_by_first}
                onChange={(next) => update({ order_by_first: next })}
              />
              <StringListField
                label="Кандидаты ORDER BY"
                jsonKey="order_by_candidates"
                value={benchmark.order_by_candidates}
                onChange={(next) => update({ order_by_candidates: next })}
                optional
              />
            </div>
          </Disclosure>
        </div>
      </Card>
    </>
  );
}
