/** Раздел «Лимиты»: объём данных, число измерений, кандидаты и победители. */

import type { BenchmarkConfig } from '../../types/config';
import { patch } from '../../lib/edit';
import { useEditor } from '../../state/editor';
import { LimitsMapEditor } from '../limits/LimitsMapEditor';
import { Card, IntListField, NumberInputField } from '../fields/inputs';

export const MODE_KEYS = [
  { key: 'types', label: 'Перебор типов' },
  { key: 'indexes', label: 'Перебор индексов' },
  { key: 'combined', label: 'Комбинированный' },
  { key: 'sequential', label: 'Последовательный / поэтапный' },
];

export const STAGE_KEYS = [
  { key: 'order_by', label: 'ORDER BY' },
  { key: 'types', label: 'Типы' },
  { key: 'codecs', label: 'Кодеки' },
  { key: 'index_granularity', label: 'Index granularity' },
  { key: 'indexes', label: 'Индексы' },
  { key: 'indexes_validation', label: 'Проверка индексов' },
  { key: 'final_validation', label: 'Финальная проверка' },
  { key: 'local_search', label: 'Локальный поиск' },
];

export const WINNER_KEYS = [
  { key: 'types', label: 'Типы' },
  { key: 'codecs', label: 'Кодеки' },
  { key: 'indexes', label: 'Индексы' },
];

export function LimitsSection({ benchmark }: { benchmark: BenchmarkConfig }): JSX.Element {
  const { updateSelected } = useEditor();
  const update = (changes: Partial<BenchmarkConfig>) =>
    updateSelected((current) => patch(current, changes));

  return (
    <>
      <div className="section-head">
        <h2>Лимиты</h2>
        <p>
          Чем ограничен перебор. Объём данных, число измерений, число кандидатов и число
          победителей задаются разными полями — они не взаимозаменяемы. Оценить время
          выполнения по этим значениям нельзя: это зависит от данных и кластера.
        </p>
      </div>

      <Card title="Объём данных" subtitle="строки за одну insert-операцию">
        <div className="stack">
          <div className="grid-2">
            <NumberInputField
              label="Строк за одну вставку в кандидата"
              jsonKey="insert_rows_per_operation_limit"
              value={benchmark.insert_rows_per_operation_limit}
              onChange={(next) => update({ insert_rows_per_operation_limit: next })}
              optional
              unit="строк"
              defaultHint="ограничения нет, используется значение по режиму или весь объём."
            />
            <NumberInputField
              label="Строк за одну вставку в baseline-копию"
              jsonKey="source_insert_rows_per_operation_limit"
              value={benchmark.source_insert_rows_per_operation_limit}
              onChange={(next) => update({ source_insert_rows_per_operation_limit: next })}
              optional
              unit="строк"
              defaultHint="ограничения нет."
            />
          </div>

          <div className="stack-sm">
            <div className="field-label">
              <span>Лимиты вставки в кандидата по режимам</span>
              <span className="field-key">insert_rows_per_operation_limits</span>
            </div>
            <LimitsMapEditor
              jsonKey="insert_rows_per_operation_limits"
              unit="строк"
              keys={MODE_KEYS}
              value={benchmark.insert_rows_per_operation_limits}
              onChange={(next) => update({ insert_rows_per_operation_limits: next })}
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
              value={benchmark.source_insert_rows_per_operation_limits}
              onChange={(next) => update({ source_insert_rows_per_operation_limits: next })}
            />
          </div>
        </div>
      </Card>

      <Card title="Число измерений">
        <NumberInputField
          label="Количество insert-замеров"
          jsonKey="insert_operations_count"
          value={benchmark.insert_operations_count}
          onChange={(next) => update({ insert_operations_count: next ?? 1 })}
          unit="операций"
          hint="Сколько раз повторяется вставка для измерения времени INSERT."
        />
      </Card>

      <Card
        title="Количество кандидатов"
        subtitle="max_benchmarks_limits"
        note="Ограничение сверху на число сгенерированных variant-задач в пределах этапа."
      >
        <LimitsMapEditor
          jsonKey="max_benchmarks_limits"
          unit="кандидатов"
          keys={[...STAGE_KEYS, { key: 'sequential', label: 'Режим sequential целиком' }]}
          value={benchmark.max_benchmarks_limits}
          onChange={(next) => update({ max_benchmarks_limits: next })}
        />
      </Card>

      <Card
        title="Победители, передаваемые дальше"
        subtitle="Top-N"
        note="Top-N этапа отбирает лучших кандидатов этапа; лимит на одного parent ограничивает число победителей внутри одной ветки."
      >
        <div className="stack">
          <div className="stack-sm">
            <div className="field-label">
              <span>Top-N по этапам</span>
              <span className="field-key">sequential_top_n_limits</span>
            </div>
            <LimitsMapEditor
              jsonKey="sequential_top_n_limits"
              unit="победителей"
              keys={STAGE_KEYS}
              value={benchmark.sequential_top_n_limits}
              onChange={(next) => update({ sequential_top_n_limits: next })}
            />
          </div>

          <div className="stack-sm">
            <div className="field-label">
              <span>Победителей на одного parent-кандидата</span>
              <span className="field-key">max_winners_per_parent_limits</span>
            </div>
            <LimitsMapEditor
              jsonKey="max_winners_per_parent_limits"
              unit="победителей"
              keys={WINNER_KEYS}
              value={benchmark.max_winners_per_parent_limits}
              onChange={(next) => update({ max_winners_per_parent_limits: next })}
            />
          </div>

          <div className="grid-2">
            <NumberInputField
              label="Top-N типов, уходящих в фазу индексов"
              jsonKey="sequential_types_top_n_for_indexes"
              value={benchmark.sequential_types_top_n_for_indexes}
              onChange={(next) => update({ sequential_types_top_n_for_indexes: next ?? 1 })}
              unit="кандидатов"
              hint="Используется двухфазным sequential_topn_strategy."
            />
            <NumberInputField
              label="Кандидатов на вход финальной проверки"
              jsonKey="final_validation_input_top_n"
              value={benchmark.final_validation_input_top_n}
              onChange={(next) => update({ final_validation_input_top_n: next })}
              optional
              unit="кандидатов"
              defaultHint="берётся Top-N предыдущего этапа."
            />
          </div>
        </div>
      </Card>

      <Card
        title="Перебор табличной гранулярности"
        subtitle="index_granularity_values"
        note="Значения SETTINGS index_granularity перемножаются с вариантами индексов. Это параметр таблицы, а не GRANULARITY пропускающего индекса."
      >
        <IntListField
          label="Значения index_granularity"
          jsonKey="index_granularity_values"
          value={benchmark.index_granularity_values}
          onChange={(next) => update({ index_granularity_values: next })}
        />
      </Card>
    </>
  );
}
