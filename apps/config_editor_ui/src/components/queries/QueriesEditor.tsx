/** Редактор блока `queries`: режим, ручные запросы и настройки автогенерации. */

import { useState } from 'react';

import type { QueriesConfig, TestQueryConfig } from '../../types/config';
import { cloneNode, patch, removeAt, replaceAt } from '../../lib/edit';
import { CACHE_MODES, QUERIES_MODES, QUERY_TYPES } from '../../lib/vocab';
import { Field, useIssuesFor } from '../fields/Field';
import {
  BoolField,
  Disclosure,
  NumberInputField,
  RadioCards,
  SelectField,
  StringListField,
} from '../fields/inputs';

export interface QueriesEditorProps {
  queries: QueriesConfig;
  onChange(next: QueriesConfig): void;
  /** Путь блока относительно бенчмарка, например `queries`. */
  path: string;
}

function QueryParams({
  query,
  onChange,
  path,
}: {
  query: TestQueryConfig;
  onChange(next: TestQueryConfig): void;
  path: string;
}): JSX.Element {
  const coldConflict = query.cache_mode === 'cold' && query.warmup_queries.length > 0;

  return (
    <div className="stack">
      <div className="grid-3">
        <Field
          label="Идентификатор запроса"
          jsonKey="query_id"
          path={`${path}.query_id`}
          hint="Не обязателен, но нужен, чтобы находить запрос в результатах."
        >
          <input
            className="control mono"
            value={query.query_id ?? ''}
            placeholder="не задано"
            onChange={(event) =>
              onChange(
                patch(query, {
                  query_id: event.target.value.trim() === '' ? undefined : event.target.value,
                }),
              )
            }
          />
        </Field>
        <SelectField
          label="Тип запроса"
          jsonKey="query_type"
          path={`${path}.query_type`}
          value={query.query_type}
          choices={QUERY_TYPES}
          onChange={(next) => onChange(patch(query, { query_type: next ?? 'manual' }))}
        />
        <SelectField
          label="Режим кеша"
          jsonKey="cache_mode"
          path={`${path}.cache_mode`}
          value={query.cache_mode}
          choices={CACHE_MODES}
          onChange={(next) => onChange(patch(query, { cache_mode: next ?? 'warm' }))}
        />
      </div>

      <div className="grid-2">
        <NumberInputField
          label="Количество измерений"
          jsonKey="select_operations_count"
          path={`${path}.select_operations_count`}
          value={query.select_operations_count}
          onChange={(next) => onChange(patch(query, { select_operations_count: next ?? 1 }))}
          unit="замеров"
          hint="Сколько раз выполнить этот SELECT на каждом кандидате."
        />
        <div className="stack-sm">
          <StringListField
            label="Прогревочные запросы"
            jsonKey="warmup_queries"
            path={`${path}.warmup_queries`}
            value={query.warmup_queries}
            onChange={(next) => onChange(patch(query, { warmup_queries: next ?? [] }))}
            rows={2}
            hint={
              query.cache_mode === 'cold'
                ? 'Режим cold: прогрев запрещён моделью — список должен быть пустым.'
                : 'Выполняются перед замером, сами не замеряются.'
            }
          />
          {coldConflict ? (
            <div className="notice notice-danger">
              <strong>Конфликт настроек</strong>
              <code>cache_mode=cold</code> не допускает <code>warmup_queries</code>.
              <div style={{ marginTop: 6 }}>
                <button
                  className="btn btn-sm"
                  type="button"
                  onClick={() => onChange(patch(query, { warmup_queries: [] }))}
                >
                  Очистить прогрев
                </button>{' '}
                <button
                  className="btn btn-sm"
                  type="button"
                  onClick={() => onChange(patch(query, { cache_mode: 'warm' }))}
                >
                  Переключить на warm
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function QueriesEditor({ queries, onChange, path }: QueriesEditorProps): JSX.Element {
  const [selected, setSelected] = useState(0);
  const set = (changes: Partial<QueriesConfig>) => onChange(patch(queries, changes));
  const current = queries.test_queries[selected];
  const modeIssues = useIssuesFor(`${path}.test_queries`);

  const setQuery = (next: TestQueryConfig) => {
    set({ test_queries: replaceAt(queries.test_queries, selected, next) });
  };

  return (
    <div className="stack">
      <div className="stack-sm">
        <div className="field-label">
          <span>Источник нагрузки</span>
          <span className="field-key">mode</span>
        </div>
        <RadioCards
          name={`${path}-mode`}
          value={queries.mode}
          choices={QUERIES_MODES}
          onChange={(next) => set({ mode: next })}
        />
      </div>

      {queries.mode !== 'auto' || queries.test_queries.length > 0 ? (
        <section className="card" style={{ marginBottom: 0 }}>
          <div className="card-head">
            <h3>Ручные запросы</h3>
            <span className="faint">test_queries</span>
            <span className="spacer" style={{ marginLeft: 'auto' }}>
              <div className="inline-actions">
                <button
                  className="btn btn-sm"
                  type="button"
                  onClick={() => {
                    const next: TestQueryConfig = {
                      query: 'SELECT count() FROM {table}',
                      query_type: 'manual',
                      cache_mode: 'warm',
                      select_operations_count: 1,
                      warmup_queries: [],
                      $seen: ['query', 'query_type', 'cache_mode', 'select_operations_count'],
                    };
                    set({ test_queries: [...queries.test_queries, next] });
                    setSelected(queries.test_queries.length);
                  }}
                >
                  Добавить
                </button>
                <button
                  className="btn btn-sm"
                  type="button"
                  disabled={!current}
                  onClick={() => {
                    if (!current) return;
                    const copy = cloneNode(current);
                    if (copy.query_id) copy.query_id = `${copy.query_id}_copy`;
                    set({
                      test_queries: [
                        ...queries.test_queries.slice(0, selected + 1),
                        copy,
                        ...queries.test_queries.slice(selected + 1),
                      ],
                    });
                    setSelected(selected + 1);
                  }}
                >
                  Дублировать
                </button>
                <button
                  className="btn btn-sm btn-ghost btn-danger"
                  type="button"
                  disabled={!current}
                  onClick={() => {
                    set({ test_queries: removeAt(queries.test_queries, selected) });
                    setSelected((value) => Math.max(0, value - 1));
                  }}
                >
                  Удалить
                </button>
              </div>
            </span>
          </div>

          {queries.test_queries.length === 0 ? (
            <div className="card-body">
              <div
                className={
                  queries.mode === 'manual' ? 'notice notice-danger' : 'notice'
                }
              >
                {queries.mode === 'manual' ? (
                  <>
                    <strong>Список пуст</strong>
                    Режим <code>manual</code> требует хотя бы одного запроса.
                  </>
                ) : (
                  'Ручных запросов нет.'
                )}
              </div>
            </div>
          ) : (
            <div className="query-layout">
              <div className="query-list">
                {queries.test_queries.map((query, index) => {
                  const hasError = modeIssues.some(
                    (issue) =>
                      issue.level === 'error' && issue.path.includes(`test_queries[${index}]`),
                  );
                  return (
                    <button
                      key={index}
                      type="button"
                      className={`query-item${selected === index ? ' active' : ''}`}
                      onClick={() => setSelected(index)}
                    >
                      <div className="query-item-id">
                        {hasError ? <span className="dot dot-danger" /> : null}{' '}
                        {query.query_id ?? `запрос ${index + 1}`}
                      </div>
                      <div className="query-item-meta">
                        <span>{query.query_type}</span>
                        <span>{query.cache_mode}</span>
                        <span>×{query.select_operations_count}</span>
                      </div>
                    </button>
                  );
                })}
              </div>

              <div className="query-editor stack">
                {current ? (
                  <>
                    <Field
                      label="SQL"
                      jsonKey="query"
                      path={`${path}.test_queries[${selected}].query`}
                      hint={
                        <>
                          Подстановки: <code>{'{table}'}</code> — полное имя тестируемой таблицы,{' '}
                          <code>{'{benchmark_id}'}</code> — идентификатор бенчмарка.
                        </>
                      }
                    >
                      <textarea
                        className="sql-area"
                        spellCheck={false}
                        value={current.query}
                        onChange={(event) => setQuery(patch(current, { query: event.target.value }))}
                      />
                    </Field>
                    <QueryParams
                      query={current}
                      path={`${path}.test_queries[${selected}]`}
                      onChange={setQuery}
                    />
                  </>
                ) : null}
              </div>
            </div>
          )}
        </section>
      ) : null}

      <Disclosure
        title="Настройки автоматических запросов"
        defaultOpen={queries.mode !== 'manual'}
      >
        <div className="stack">
          <div className="grid-3">
            <NumberInputField
              label="Лимит строк в SELECT"
              jsonKey="auto_select_limit"
              path={`${path}.auto_select_limit`}
              value={queries.auto_select_limit}
              onChange={(next) => set({ auto_select_limit: next ?? 10 })}
              unit="строк"
            />
            <NumberInputField
              label="Измерений на запрос"
              jsonKey="auto_select_operations_count"
              path={`${path}.auto_select_operations_count`}
              value={queries.auto_select_operations_count}
              onChange={(next) => set({ auto_select_operations_count: next ?? 5 })}
              unit="замеров"
            />
            <NumberInputField
              label="Строк выборки на колонку"
              jsonKey="auto_like_sample_rows_per_column"
              path={`${path}.auto_like_sample_rows_per_column`}
              value={queries.auto_like_sample_rows_per_column}
              onChange={(next) => set({ auto_like_sample_rows_per_column: next ?? 20 })}
              unit="строк"
              hint="Сколько значений колонки прочитать, чтобы построить LIKE-запросы."
            />
          </div>
          <div className="grid-2">
            <NumberInputField
              label="Минимальная длина токена"
              jsonKey="auto_like_min_token_length"
              path={`${path}.auto_like_min_token_length`}
              value={queries.auto_like_min_token_length}
              onChange={(next) => set({ auto_like_min_token_length: next ?? 3 })}
              unit="символов"
            />
            <NumberInputField
              label="Максимальная длина токена"
              jsonKey="auto_like_max_token_length"
              path={`${path}.auto_like_max_token_length`}
              value={queries.auto_like_max_token_length}
              onChange={(next) => set({ auto_like_max_token_length: next ?? 24 })}
              unit="символов"
              hint="Должна быть не меньше минимальной."
            />
          </div>
          <div className="stack-sm">
            <BoolField
              label="Строить LIKE-запросы по измеряемым колонкам"
              jsonKey="auto_like_on_measured_columns"
              value={queries.auto_like_on_measured_columns}
              onChange={(next) => set({ auto_like_on_measured_columns: next })}
            />
            <BoolField
              label="Заменять стандартные автозапросы LIKE-запросами"
              jsonKey="auto_like_replace_default_auto_queries"
              value={queries.auto_like_replace_default_auto_queries}
              onChange={(next) => set({ auto_like_replace_default_auto_queries: next })}
            />
            <BoolField
              label="Добавлять miss-запросы"
              jsonKey="auto_include_miss_queries"
              value={queries.auto_include_miss_queries}
              onChange={(next) => set({ auto_include_miss_queries: next })}
              hint="Запросы, заведомо не находящие строк."
            />
          </div>
        </div>
      </Disclosure>
    </div>
  );
}
