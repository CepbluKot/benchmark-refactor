/** Раздел «Источник и стратегия». */

import { Fragment } from 'react';

import type { BenchmarkConfig, TablesSelector } from '../../types/config';
import { patch, parseLines } from '../../lib/edit';
import { PHASED_STAGES, STRATEGIES } from '../../lib/vocab';
import { useEditor } from '../../state/editor';
import { Field } from '../fields/Field';
import {
  Card,
  Disclosure,
  RadioCards,
  SelectField,
  StringListField,
  TextInputField,
} from '../fields/inputs';

type TablesKind = 'all' | 'list' | 'map';

function tablesKind(tables: TablesSelector): TablesKind {
  if (tables === '*') return 'all';
  if (Array.isArray(tables)) return 'list';
  return 'map';
}

function PhasedPipeline(): JSX.Element {
  return (
    <div className="stack-sm">
      <div className="pipeline">
        {PHASED_STAGES.map((stage, index) => (
          <Fragment key={stage.key}>
            {index > 0 ? <span className="pipeline-arrow">→</span> : null}
            <div className="pipeline-stage" title={stage.hint}>
              <div className="stage-name">{stage.label}</div>
              <div className="stage-phase">
                фаза {stage.phase} · {stage.key}
              </div>
            </div>
          </Fragment>
        ))}
      </div>
      <div className="faint">
        Схема алгоритма, а не ход выполнения: запуск не начат, состояния этапов неизвестны.
      </div>
    </div>
  );
}

export function SourceSection({ benchmark }: { benchmark: BenchmarkConfig }): JSX.Element {
  const { updateSelected, reference } = useEditor();
  const update = (changes: Partial<BenchmarkConfig>) =>
    updateSelected((current) => patch(current, changes));

  const kind = tablesKind(benchmark.tables);
  const tablesMap = kind === 'map' ? (benchmark.tables as Record<string, '*' | string[]>) : {};

  const setTablesKind = (next: TablesKind) => {
    if (next === 'all') update({ tables: '*' });
    else if (next === 'list') update({ tables: Array.isArray(benchmark.tables) ? benchmark.tables : [] });
    else update({ tables: kind === 'map' ? tablesMap : {} });
  };

  const setMapEntry = (database: string, selector: '*' | string[]) => {
    update({ tables: { ...tablesMap, [database]: selector } });
  };

  const renameMapEntry = (from: string, to: string) => {
    const next: Record<string, '*' | string[]> = {};
    for (const [key, value] of Object.entries(tablesMap)) next[key === from ? to : key] = value;
    update({ tables: next });
  };

  const removeMapEntry = (database: string) => {
    const next = { ...tablesMap };
    delete next[database];
    update({ tables: next });
  };

  return (
    <>
      <div className="section-head">
        <h2>Источник и стратегия</h2>
        <p>
          Что исследуем, где создаются временные таблицы и каким алгоритмом перебираются
          варианты физической структуры.
        </p>
      </div>

      <Card title="Идентификация">
        <div className="grid-2">
          <TextInputField
            label="Идентификатор бенчмарка"
            jsonKey="id"
            value={benchmark.id}
            onChange={(next) => update({ id: next ?? '' })}
            hint="Уникален в пределах файла. Используется в именах временных таблиц и в результатах."
          />
          <Field
            label="Подключение"
            jsonKey="connection_id"
            path="connection_id"
            hint={
              reference.connectionIds === null
                ? 'Ссылка на запись в отдельном файле подключений. Логин и пароль в бенчмарке не хранятся.'
                : `Загружен файл ${reference.connectionsFileName}: ${reference.connectionIds.length} подключений.`
            }
          >
            {reference.connectionIds === null ? (
              <input
                className="control mono"
                value={benchmark.connection_id}
                placeholder="например: local_ch_hits"
                onChange={(event) => update({ connection_id: event.target.value })}
              />
            ) : (
              <select
                className="control mono"
                value={benchmark.connection_id}
                onChange={(event) => update({ connection_id: event.target.value })}
              >
                <option value="">не выбрано</option>
                {reference.connections.map((connection) => (
                  <option key={connection.id} value={connection.id}>
                    {connection.id} — {connection.dbms} {connection.host}:{connection.port}
                  </option>
                ))}
                {reference.connectionIds.includes(benchmark.connection_id) ? null : benchmark
                    .connection_id ? (
                  <option value={benchmark.connection_id}>
                    {benchmark.connection_id} (нет в файле подключений)
                  </option>
                ) : null}
              </select>
            )}
          </Field>
        </div>
      </Card>

      <Card
        title="Стратегия"
        note={
          benchmark.strategy === 'sequential_phased_topn_strategy' ? (
            <PhasedPipeline />
          ) : (
            <span>
              Режим замеров для этой стратегии:{' '}
              <code>
                {benchmark.strategy === 'types_strategy'
                  ? 'types'
                  : benchmark.strategy === 'indexes_strategy'
                    ? 'indexes'
                    : benchmark.strategy === 'combined_strategy'
                      ? 'combined'
                      : 'sequential'}
              </code>
              . Он определяет, какие ключи читаются из лимитов по режимам.
            </span>
          )
        }
      >
        <RadioCards
          name="strategy"
          value={benchmark.strategy}
          choices={STRATEGIES}
          onChange={(next) => update({ strategy: next })}
        />
      </Card>

      <Card
        title="Источник данных"
        note={
          <>
            Каталог баз и таблиц читается из ClickHouse. Без серверной интеграции список
            недоступен, поэтому имена вводятся вручную и здесь не проверяются на существование.
          </>
        }
      >
        <div className="stack">
          <Field
            label="Базы данных"
            jsonKey="databases"
            path="databases"
            hint='«*» — все базы, доступные подключению.'
          >
            <div className="stack-sm">
              <div className="segmented">
                <button
                  type="button"
                  className={benchmark.databases === '*' ? 'active' : ''}
                  onClick={() => update({ databases: '*' })}
                >
                  Все базы (*)
                </button>
                <button
                  type="button"
                  className={benchmark.databases !== '*' ? 'active' : ''}
                  onClick={() =>
                    update({ databases: Array.isArray(benchmark.databases) ? benchmark.databases : [] })
                  }
                >
                  Список
                </button>
              </div>
              {benchmark.databases !== '*' ? (
                <textarea
                  className="control mono"
                  rows={3}
                  value={(benchmark.databases as string[]).join('\n')}
                  placeholder="по одной базе в строке"
                  onChange={(event) => update({ databases: parseLines(event.target.value) })}
                />
              ) : null}
            </div>
          </Field>

          <Field
            label="Таблицы"
            jsonKey="tables"
            path="tables"
            hint="Плоский список применяется ко всем выбранным базам. Вариант «по базам» задаёт объект database → таблицы."
          >
            <div className="stack-sm">
              <div className="segmented">
                <button
                  type="button"
                  className={kind === 'all' ? 'active' : ''}
                  onClick={() => setTablesKind('all')}
                >
                  Все таблицы (*)
                </button>
                <button
                  type="button"
                  className={kind === 'list' ? 'active' : ''}
                  onClick={() => setTablesKind('list')}
                >
                  Список
                </button>
                <button
                  type="button"
                  className={kind === 'map' ? 'active' : ''}
                  onClick={() => setTablesKind('map')}
                >
                  По базам
                </button>
              </div>

              {kind === 'list' ? (
                <textarea
                  className="control mono"
                  rows={3}
                  value={(benchmark.tables as string[]).join('\n')}
                  placeholder="по одной таблице в строке"
                  onChange={(event) => update({ tables: parseLines(event.target.value) })}
                />
              ) : null}

              {kind === 'map' ? (
                <div className="stack-sm">
                  {Object.entries(tablesMap).map(([database, selector]) => (
                    <div className="card" key={database} style={{ marginBottom: 0 }}>
                      <div className="card-head">
                        <input
                          className="control mono"
                          style={{ maxWidth: 220 }}
                          value={database}
                          onChange={(event) => renameMapEntry(database, event.target.value)}
                        />
                        <span className="spacer">
                          <div className="row">
                            <div className="segmented">
                              <button
                                type="button"
                                className={selector === '*' ? 'active' : ''}
                                onClick={() => setMapEntry(database, '*')}
                              >
                                Все (*)
                              </button>
                              <button
                                type="button"
                                className={selector !== '*' ? 'active' : ''}
                                onClick={() =>
                                  setMapEntry(database, Array.isArray(selector) ? selector : [])
                                }
                              >
                                Список
                              </button>
                            </div>
                            <button
                              className="btn btn-ghost btn-sm btn-danger"
                              type="button"
                              onClick={() => removeMapEntry(database)}
                            >
                              Убрать базу
                            </button>
                          </div>
                        </span>
                      </div>
                      {selector !== '*' ? (
                        <div className="card-body">
                          <textarea
                            className="control mono"
                            rows={2}
                            value={(selector as string[]).join('\n')}
                            placeholder="по одной таблице в строке"
                            onChange={(event) =>
                              setMapEntry(database, parseLines(event.target.value))
                            }
                          />
                        </div>
                      ) : null}
                    </div>
                  ))}
                  <div>
                    <button
                      className="btn btn-sm"
                      type="button"
                      onClick={() => setMapEntry(`database_${Object.keys(tablesMap).length + 1}`, [])}
                    >
                      Добавить базу
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          </Field>

          <div className="grid-2">
            <TextInputField
              label="База для временных таблиц"
              jsonKey="test_database"
              value={benchmark.test_database}
              onChange={(next) => update({ test_database: next })}
              hint="Где создаются таблицы-кандидаты. Если не задано — используется база исходной таблицы."
              placeholder="не задано — база источника"
            />
            <SelectField
              label="Режим порядка колонок"
              jsonKey="column_order_mode"
              value={benchmark.column_order_mode}
              choices={[
                {
                  value: 'compressed_size_desc' as const,
                  label: 'По убыванию сжатого размера',
                  hint: 'Порядок колонок в CREATE TABLE вычисляется по сжатому размеру колонок.',
                },
              ]}
              onChange={(next) => update({ column_order_mode: next })}
              allowEmpty
              emptyLabel="не задано — порядок исходной таблицы"
            />
          </div>
        </div>
      </Card>

      <Disclosure title="Дополнительно: ORDER BY на уровне бенчмарка">
        <div className="grid-2">
          <TextInputField
            label="Первая колонка ORDER BY"
            jsonKey="order_by_first"
            value={benchmark.order_by_first}
            onChange={(next) => update({ order_by_first: next })}
            hint="Путь benchmarks[].order_by_first. Приоритетнее, чем global_rules.order_by_rules.first_column."
          />
          <StringListField
            label="Кандидаты ORDER BY"
            jsonKey="order_by_candidates"
            value={benchmark.order_by_candidates}
            onChange={(next) => update({ order_by_candidates: next })}
            optional
            hint="Путь benchmarks[].order_by_candidates. Подробности и второй источник — в разделе «Правила вариантов»."
          />
        </div>
      </Disclosure>
    </>
  );
}
