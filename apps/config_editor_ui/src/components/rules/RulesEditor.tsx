/**
 * Редактор блока правил (`global_rules` или `table_rules[].rules`).
 *
 * Для table-level блока каждый список имеет два состояния:
 * «Наследуется» (поле отсутствует) и «Переопределено» (задан список).
 * Сброс переопределения удаляет поле, а не копирует общее значение.
 */

import { Fragment, useState } from 'react';
import type { ReactNode } from 'react';

import type {
  CodecRuleConfig,
  ColumnRuleConfig,
  IndexConfig,
  IndexRuleConfig,
  OrderByRulesConfig,
  RulesConfig,
} from '../../types/config';
import { patch, removeAt, replaceAt } from '../../lib/edit';
import { Field } from '../fields/Field';
import {
  BoolField,
  Disclosure,
  IntListField,
  StringListField,
  TextInputField,
} from '../fields/inputs';

type RulesTab = 'types' | 'codecs' | 'indexes' | 'order_by' | 'column_order';

const TABS: { key: RulesTab; label: string; jsonKey: string }[] = [
  { key: 'types', label: 'Типы колонок', jsonKey: 'column_rules' },
  { key: 'codecs', label: 'Кодеки', jsonKey: 'codec_rules' },
  { key: 'indexes', label: 'Индексы', jsonKey: 'index_rules' },
  { key: 'order_by', label: 'ORDER BY', jsonKey: 'order_by_rules' },
  { key: 'column_order', label: 'Порядок колонок', jsonKey: 'column_order' },
];

export interface RulesEditorProps {
  rules: RulesConfig;
  onChange(next: RulesConfig): void;
  /** Путь блока относительно бенчмарка, например `global_rules`. */
  path: string;
  /** Для table-level блока показываются состояния наследования. */
  inheritable: boolean;
}

function MatcherFields({
  rule,
  onChange,
  path,
}: {
  rule: ColumnRuleConfig | CodecRuleConfig | IndexRuleConfig;
  onChange(changes: Partial<ColumnRuleConfig & CodecRuleConfig & IndexRuleConfig>): void;
  path: string;
}): JSX.Element {
  return (
    <div className="grid-2">
      <TextInputField
        label="Тип колонки"
        jsonKey="by_type"
        path={`${path}.by_type`}
        value={rule.by_type}
        onChange={(next) => onChange({ by_type: next })}
        placeholder="например: String"
        hint="Правило применяется к колонкам этого типа."
      />
      <TextInputField
        label="Имя колонки"
        jsonKey="by_name"
        path={`${path}.by_name`}
        value={rule.by_name}
        onChange={(next) => onChange({ by_name: next })}
        placeholder="например: page_url"
        hint={
          rule.by_name !== undefined && rule.by_type === undefined
            ? 'by_name задан без by_type — модель требует указать тип явно.'
            : 'Сужает правило до одной колонки. Требует заполненного by_type.'
        }
      />
    </div>
  );
}

function ruleTarget(rule: { by_type?: string; by_name?: string }): string {
  if (rule.by_name && rule.by_type) return `${rule.by_name} : ${rule.by_type}`;
  if (rule.by_name) return `${rule.by_name} (без by_type)`;
  return rule.by_type ?? '—';
}

function ListSlot({
  label,
  jsonKey,
  path,
  inheritable,
  defined,
  onDefine,
  onReset,
  children,
}: {
  label: string;
  jsonKey: string;
  path: string;
  inheritable: boolean;
  defined: boolean;
  onDefine(): void;
  onReset(): void;
  children: ReactNode;
}): JSX.Element {
  if (!inheritable) return <>{children}</>;
  return (
    <div className="stack-sm">
      <div className="row">
        {defined ? (
          <span className="override-tag">Переопределено</span>
        ) : (
          <span className="inherit-tag">Наследуется</span>
        )}
        <span className="field-key">{path}</span>
        <span className="spacer" style={{ marginLeft: 'auto' }}>
          {defined ? (
            <button className="btn btn-sm btn-ghost btn-danger" type="button" onClick={onReset}>
              Сбросить переопределение
            </button>
          ) : (
            <button className="btn btn-sm" type="button" onClick={onDefine}>
              Переопределить {label}
            </button>
          )}
        </span>
      </div>
      {defined ? children : (
        <div className="notice">
          Поле <code>{jsonKey}</code> отсутствует: действует общий список бенчмарка.
          Заданный здесь список <strong>замещает</strong> общий, а не дополняет его.
        </div>
      )}
    </div>
  );
}

function ColumnRulesTable({
  rules,
  onChange,
  path,
}: {
  rules: ColumnRuleConfig[];
  onChange(next: ColumnRuleConfig[]): void;
  path: string;
}): JSX.Element {
  const [expanded, setExpanded] = useState<number | null>(rules.length ? 0 : null);

  return (
    <div className="stack-sm">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: 28 }} />
              <th>К каким колонкам</th>
              <th>Варианты типов</th>
              <th>Кодеки</th>
              <th>Автогенерация</th>
              <th style={{ width: 92 }} />
            </tr>
          </thead>
          <tbody>
            {rules.length === 0 ? (
              <tr>
                <td colSpan={6} className="muted">
                  Список пуст: правил подбора типов нет.
                </td>
              </tr>
            ) : null}
            {rules.map((rule, index) => (
              <Fragment key={index}>
                <tr key={`row-${index}`} className={expanded === index ? 'expanded' : ''}>
                  <td>
                    <button
                      className="row-toggle"
                      type="button"
                      onClick={() => setExpanded(expanded === index ? null : index)}
                    >
                      {expanded === index ? '▾' : '▸'}
                    </button>
                  </td>
                  <td className="mono">{ruleTarget(rule)}</td>
                  <td className="mono">{rule.types.length ? rule.types.join(', ') : '—'}</td>
                  <td className="mono">{rule.codecs.length ? `${rule.codecs.length} шт.` : '—'}</td>
                  <td>
                    {rule.auto_generate_alternatives ? (
                      <span className="badge badge-accent">включена</span>
                    ) : (
                      <span className="faint">выключена</span>
                    )}
                  </td>
                  <td>
                    <button
                      className="btn btn-sm btn-ghost btn-danger"
                      type="button"
                      onClick={() => onChange(removeAt(rules, index))}
                    >
                      Удалить
                    </button>
                  </td>
                </tr>
                {expanded === index ? (
                  <tr key={`detail-${index}`}>
                    <td colSpan={6} className="detail-cell">
                      <div className="stack">
                        <MatcherFields
                          rule={rule}
                          path={`${path}[${index}]`}
                          onChange={(changes) =>
                            onChange(replaceAt(rules, index, patch(rule, changes)))
                          }
                        />
                        <div className="grid-2">
                          <StringListField
                            label="Проверяемые типы"
                            jsonKey="types"
                            path={`${path}[${index}].types`}
                            value={rule.types}
                            onChange={(next) =>
                              onChange(replaceAt(rules, index, patch(rule, { types: next ?? [] })))
                            }
                            hint="Каждая строка — вариант типа колонки."
                            placeholder={'UInt64\nUInt32'}
                          />
                          <StringListField
                            label="Кодеки"
                            jsonKey="codecs"
                            path={`${path}[${index}].codecs`}
                            value={rule.codecs}
                            onChange={(next) =>
                              onChange(replaceAt(rules, index, patch(rule, { codecs: next ?? [] })))
                            }
                            hint="Строка сохраняется как есть: CODEC(Delta(8), LZ4)."
                            placeholder={'CODEC(Delta(8), LZ4)\nCODEC(ZSTD(1))'}
                          />
                        </div>
                        <BoolField
                          label="Автоматически подбирать альтернативы"
                          jsonKey="auto_generate_alternatives"
                          value={rule.auto_generate_alternatives}
                          onChange={(next) =>
                            onChange(
                              replaceAt(rules, index, patch(rule, { auto_generate_alternatives: next })),
                            )
                          }
                          hint="Движок сам добавит варианты типов и кодеков к перечисленным."
                        />
                        <TextInputField
                          label="Подсказка типа для автогенерации кодеков"
                          jsonKey="auto_compressions_datatype"
                          path={`${path}[${index}].auto_compressions_datatype`}
                          value={rule.auto_compressions_datatype}
                          onChange={(next) =>
                            onChange(
                              replaceAt(rules, index, patch(rule, { auto_compressions_datatype: next })),
                            )
                          }
                          hint="Legacy-подсказка: какой тип данных считать базовым при автоподборе кодеков."
                        />
                      </div>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <button
          className="btn btn-sm"
          type="button"
          onClick={() => {
            onChange([
              ...rules,
              { types: [], codecs: [], auto_generate_alternatives: false },
            ]);
            setExpanded(rules.length);
          }}
        >
          Добавить правило
        </button>
      </div>
    </div>
  );
}

function CodecRulesTable({
  rules,
  onChange,
  path,
}: {
  rules: CodecRuleConfig[];
  onChange(next: CodecRuleConfig[]): void;
  path: string;
}): JSX.Element {
  const [expanded, setExpanded] = useState<number | null>(rules.length ? 0 : null);

  return (
    <div className="stack-sm">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: 28 }} />
              <th>К каким колонкам</th>
              <th>Кодеки</th>
              <th>Автогенерация</th>
              <th style={{ width: 92 }} />
            </tr>
          </thead>
          <tbody>
            {rules.length === 0 ? (
              <tr>
                <td colSpan={5} className="muted">
                  Список пуст: отдельных правил для кодеков нет.
                </td>
              </tr>
            ) : null}
            {rules.map((rule, index) => (
              <Fragment key={index}>
                <tr key={`row-${index}`} className={expanded === index ? 'expanded' : ''}>
                  <td>
                    <button
                      className="row-toggle"
                      type="button"
                      onClick={() => setExpanded(expanded === index ? null : index)}
                    >
                      {expanded === index ? '▾' : '▸'}
                    </button>
                  </td>
                  <td className="mono">{ruleTarget(rule)}</td>
                  <td className="mono">{rule.codecs.length ? `${rule.codecs.length} шт.` : '—'}</td>
                  <td>
                    {rule.auto_generate_alternatives ? (
                      <span className="badge badge-accent">включена</span>
                    ) : (
                      <span className="faint">выключена</span>
                    )}
                  </td>
                  <td>
                    <button
                      className="btn btn-sm btn-ghost btn-danger"
                      type="button"
                      onClick={() => onChange(removeAt(rules, index))}
                    >
                      Удалить
                    </button>
                  </td>
                </tr>
                {expanded === index ? (
                  <tr key={`detail-${index}`}>
                    <td colSpan={5} className="detail-cell">
                      <div className="stack">
                        <MatcherFields
                          rule={rule}
                          path={`${path}[${index}]`}
                          onChange={(changes) =>
                            onChange(replaceAt(rules, index, patch(rule, changes)))
                          }
                        />
                        <StringListField
                          label="Кодеки"
                          jsonKey="codecs"
                          path={`${path}[${index}].codecs`}
                          value={rule.codecs}
                          onChange={(next) =>
                            onChange(replaceAt(rules, index, patch(rule, { codecs: next ?? [] })))
                          }
                          rows={4}
                          hint="Текст выражения сохраняется без изменений и редактируется вручную."
                          placeholder={'CODEC(ZSTD(1))\nCODEC(T64, ZSTD(1))'}
                        />
                        <BoolField
                          label="Автоматически подбирать кодеки"
                          jsonKey="auto_generate_alternatives"
                          value={rule.auto_generate_alternatives}
                          onChange={(next) =>
                            onChange(
                              replaceAt(rules, index, patch(rule, { auto_generate_alternatives: next })),
                            )
                          }
                        />
                        <TextInputField
                          label="Подсказка типа для автогенерации"
                          jsonKey="auto_compressions_datatype"
                          path={`${path}[${index}].auto_compressions_datatype`}
                          value={rule.auto_compressions_datatype}
                          onChange={(next) =>
                            onChange(
                              replaceAt(rules, index, patch(rule, { auto_compressions_datatype: next })),
                            )
                          }
                        />
                      </div>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <button
          className="btn btn-sm"
          type="button"
          onClick={() => {
            onChange([...rules, { codecs: [], auto_generate_alternatives: false }]);
            setExpanded(rules.length);
          }}
        >
          Добавить правило
        </button>
      </div>
    </div>
  );
}

function IndexEditor({
  index,
  onChange,
  onRemove,
  path,
}: {
  index: IndexConfig;
  onChange(next: IndexConfig): void;
  onRemove(): void;
  path: string;
}): JSX.Element {
  return (
    <div className="card" style={{ marginBottom: 8 }}>
      <div className="card-head">
        <span className="mono">{index.type || 'новый индекс'}</span>
        <span className="spacer" style={{ marginLeft: 'auto' }}>
          <button className="btn btn-sm btn-ghost btn-danger" type="button" onClick={onRemove}>
            Удалить индекс
          </button>
        </span>
      </div>
      <div className="card-body stack">
        <TextInputField
          label="Тип индекса"
          jsonKey="type"
          path={`${path}.type`}
          value={index.type}
          onChange={(next) => onChange(patch(index, { type: next ?? '' }))}
          placeholder="minmax, set(100), bloom_filter(0.01), ngrambf_v1(3, 32768, 3, 0)"
          hint="Строка передаётся в DDL как есть, вместе с параметрами."
        />
        <div className="grid-2">
          <IntListField
            label="Гранулярность индекса"
            jsonKey="granularity_values"
            path={`${path}.granularity_values`}
            value={
              index.granularity_values ?? (index.granularity ? [index.granularity] : undefined)
            }
            onChange={(next) =>
              onChange(
                patch(index, {
                  granularity_values: next,
                  granularity: next?.[0] ?? index.granularity,
                  $granularityAsArray: next && next.length > 1 ? true : index.$granularityAsArray,
                }),
              )
            }
            placeholder="например: 4, 8, 16"
            hint="GRANULARITY у самого пропускающего индекса: сколько гранул таблицы покрывает одна запись индекса. Несколько значений — перебор."
          />
          <IntListField
            label="Табличный index_granularity для этого индекса"
            jsonKey="index_granularity_values"
            path={`${path}.index_granularity_values`}
            value={index.index_granularity_values}
            onChange={(next) => onChange(patch(index, { index_granularity_values: next }))}
            placeholder="например: 8192, 16384"
            hint="Настройка таблицы SETTINGS index_granularity — размер гранулы в строках. Это другой параметр."
          />
        </div>
      </div>
    </div>
  );
}

function IndexRulesTable({
  rules,
  onChange,
  path,
}: {
  rules: IndexRuleConfig[];
  onChange(next: IndexRuleConfig[]): void;
  path: string;
}): JSX.Element {
  const [expanded, setExpanded] = useState<number | null>(rules.length ? 0 : null);

  return (
    <div className="stack-sm">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: 28 }} />
              <th>К каким колонкам</th>
              <th>Индексы</th>
              <th>Автогенерация</th>
              <th style={{ width: 92 }} />
            </tr>
          </thead>
          <tbody>
            {rules.length === 0 ? (
              <tr>
                <td colSpan={5} className="muted">
                  Список пуст: правил подбора индексов нет.
                </td>
              </tr>
            ) : null}
            {rules.map((rule, index) => (
              <Fragment key={index}>
                <tr key={`row-${index}`} className={expanded === index ? 'expanded' : ''}>
                  <td>
                    <button
                      className="row-toggle"
                      type="button"
                      onClick={() => setExpanded(expanded === index ? null : index)}
                    >
                      {expanded === index ? '▾' : '▸'}
                    </button>
                  </td>
                  <td className="mono">{ruleTarget(rule)}</td>
                  <td className="mono">
                    {rule.indexes.length
                      ? rule.indexes.map((item) => item.type).join(' · ')
                      : '—'}
                  </td>
                  <td>
                    {rule.auto_generate_indexes ? (
                      <span className="badge badge-accent">включена</span>
                    ) : (
                      <span className="faint">выключена</span>
                    )}
                  </td>
                  <td>
                    <button
                      className="btn btn-sm btn-ghost btn-danger"
                      type="button"
                      onClick={() => onChange(removeAt(rules, index))}
                    >
                      Удалить
                    </button>
                  </td>
                </tr>
                {expanded === index ? (
                  <tr key={`detail-${index}`}>
                    <td colSpan={5} className="detail-cell">
                      <div className="stack">
                        <MatcherFields
                          rule={rule}
                          path={`${path}[${index}]`}
                          onChange={(changes) =>
                            onChange(replaceAt(rules, index, patch(rule, changes)))
                          }
                        />
                        <div>
                          <div className="field-label" style={{ marginBottom: 6 }}>
                            <span>Проверяемые индексы</span>
                            <span className="field-key">indexes</span>
                          </div>
                          {rule.indexes.map((item, itemIndex) => (
                            <IndexEditor
                              key={itemIndex}
                              index={item}
                              path={`${path}[${index}].indexes[${itemIndex}]`}
                              onChange={(next) =>
                                onChange(
                                  replaceAt(
                                    rules,
                                    index,
                                    patch(rule, { indexes: replaceAt(rule.indexes, itemIndex, next) }),
                                  ),
                                )
                              }
                              onRemove={() =>
                                onChange(
                                  replaceAt(
                                    rules,
                                    index,
                                    patch(rule, { indexes: removeAt(rule.indexes, itemIndex) }),
                                  ),
                                )
                              }
                            />
                          ))}
                          <button
                            className="btn btn-sm"
                            type="button"
                            onClick={() =>
                              onChange(
                                replaceAt(
                                  rules,
                                  index,
                                  patch(rule, {
                                    indexes: [...rule.indexes, { type: '', granularity: 1 }],
                                  }),
                                ),
                              )
                            }
                          >
                            Добавить индекс
                          </button>
                        </div>
                        <BoolField
                          label="Автоматически подбирать индексы"
                          jsonKey="auto_generate_indexes"
                          value={rule.auto_generate_indexes}
                          onChange={(next) =>
                            onChange(
                              replaceAt(rules, index, patch(rule, { auto_generate_indexes: next })),
                            )
                          }
                        />
                        <TextInputField
                          label="Подсказка типа для автогенерации индексов"
                          jsonKey="auto_indexes_datatype"
                          path={`${path}[${index}].auto_indexes_datatype`}
                          value={rule.auto_indexes_datatype}
                          onChange={(next) =>
                            onChange(
                              replaceAt(rules, index, patch(rule, { auto_indexes_datatype: next })),
                            )
                          }
                        />
                      </div>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <button
          className="btn btn-sm"
          type="button"
          onClick={() => {
            onChange([...rules, { indexes: [], auto_generate_indexes: false }]);
            setExpanded(rules.length);
          }}
        >
          Добавить правило
        </button>
      </div>
    </div>
  );
}

function OrderByRulesEditor({
  value,
  onChange,
  path,
}: {
  value: OrderByRulesConfig;
  onChange(next: OrderByRulesConfig): void;
  path: string;
}): JSX.Element {
  return (
    <div className="stack">
      <TextInputField
        label="Первая колонка ключа сортировки"
        jsonKey="first_column"
        path={`${path}.first_column`}
        value={value.first_column}
        onChange={(next) => onChange(patch(value, { first_column: next }))}
      />
      <StringListField
        label="Кандидаты ORDER BY"
        jsonKey="candidates"
        path={`${path}.candidates`}
        value={value.candidates}
        onChange={(next) => onChange(patch(value, { candidates: next }))}
        optional
        rows={4}
        hint="Порядок строк сохраняется. Пустой список запрещён моделью."
      />
      <Field
        label="Автоматически дополнять кандидатов"
        jsonKey="auto_generate_candidates"
        path={`${path}.auto_generate_candidates`}
        hint="Трёхзначное поле: не задано / true / false. Это единственный путь для такой настройки — на уровне бенчмарка аналога нет."
      >
        <div className="segmented">
          <button
            type="button"
            className={value.auto_generate_candidates === undefined ? 'active' : ''}
            onClick={() => onChange(patch(value, { auto_generate_candidates: undefined }))}
          >
            не задано
          </button>
          <button
            type="button"
            className={value.auto_generate_candidates === true ? 'active' : ''}
            onClick={() => onChange(patch(value, { auto_generate_candidates: true }))}
          >
            true
          </button>
          <button
            type="button"
            className={value.auto_generate_candidates === false ? 'active' : ''}
            onClick={() => onChange(patch(value, { auto_generate_candidates: false }))}
          >
            false
          </button>
        </div>
      </Field>
    </div>
  );
}

function ColumnOrderEditor({
  value,
  onChange,
}: {
  value: Record<string, number>;
  onChange(next: Record<string, number>): void;
}): JSX.Element {
  const entries = Object.entries(value);
  return (
    <div className="stack-sm">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Колонка</th>
              <th style={{ width: 120 }}>Позиция</th>
              <th style={{ width: 92 }} />
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 ? (
              <tr>
                <td colSpan={3} className="muted">
                  Порядок колонок не задан.
                </td>
              </tr>
            ) : null}
            {entries.map(([column, position]) => (
              <tr key={column}>
                <td>
                  <input
                    className="control mono"
                    value={column}
                    onChange={(event) => {
                      const next: Record<string, number> = {};
                      for (const [key, item] of entries) {
                        next[key === column ? event.target.value : key] = item;
                      }
                      onChange(next);
                    }}
                  />
                </td>
                <td>
                  <input
                    className="control mono"
                    inputMode="numeric"
                    value={position}
                    onChange={(event) => {
                      const parsed = Number(event.target.value);
                      if (!Number.isFinite(parsed)) return;
                      onChange({ ...value, [column]: parsed });
                    }}
                  />
                </td>
                <td>
                  <button
                    className="btn btn-sm btn-ghost btn-danger"
                    type="button"
                    onClick={() => {
                      const next = { ...value };
                      delete next[column];
                      onChange(next);
                    }}
                  >
                    Удалить
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <button
          className="btn btn-sm"
          type="button"
          onClick={() => onChange({ ...value, [`column_${entries.length + 1}`]: entries.length + 1 })}
        >
          Добавить колонку
        </button>
      </div>
    </div>
  );
}

export function RulesEditor({ rules, onChange, path, inheritable }: RulesEditorProps): JSX.Element {
  const [tab, setTab] = useState<RulesTab>('types');
  const set = (changes: Partial<RulesConfig>) => onChange(patch(rules, changes));

  return (
    <div className="stack">
      <div className="section-tabs" style={{ padding: 0, borderBottom: '1px solid var(--border)' }}>
        {TABS.map((item) => {
          const defined =
            item.key === 'types'
              ? rules.column_rules !== undefined
              : item.key === 'codecs'
                ? rules.codec_rules !== undefined
                : item.key === 'indexes'
                  ? rules.index_rules !== undefined
                  : item.key === 'order_by'
                    ? rules.order_by_rules !== undefined
                    : rules.column_order !== undefined;
          const count =
            item.key === 'types'
              ? rules.column_rules?.length
              : item.key === 'codecs'
                ? rules.codec_rules?.length
                : item.key === 'indexes'
                  ? rules.index_rules?.length
                  : item.key === 'column_order'
                    ? Object.keys(rules.column_order ?? {}).length
                    : undefined;
          return (
            <button
              key={item.key}
              type="button"
              className={`section-tab${tab === item.key ? ' active' : ''}`}
              onClick={() => setTab(item.key)}
            >
              {item.label}
              {defined ? (
                <span className="badge badge-neutral">{count ?? 'задано'}</span>
              ) : (
                <span className="faint">—</span>
              )}
            </button>
          );
        })}
      </div>

      {tab === 'types' ? (
        <ListSlot
          label="правила типов"
          jsonKey="column_rules"
          path={`${path}.column_rules`}
          inheritable={inheritable}
          defined={rules.column_rules !== undefined}
          onDefine={() => set({ column_rules: [] })}
          onReset={() => set({ column_rules: undefined })}
        >
          <ColumnRulesTable
            rules={rules.column_rules ?? []}
            path={`${path}.column_rules`}
            onChange={(next) => set({ column_rules: next })}
          />
        </ListSlot>
      ) : null}

      {tab === 'codecs' ? (
        <ListSlot
          label="правила кодеков"
          jsonKey="codec_rules"
          path={`${path}.codec_rules`}
          inheritable={inheritable}
          defined={rules.codec_rules !== undefined}
          onDefine={() => set({ codec_rules: [] })}
          onReset={() => set({ codec_rules: undefined })}
        >
          <CodecRulesTable
            rules={rules.codec_rules ?? []}
            path={`${path}.codec_rules`}
            onChange={(next) => set({ codec_rules: next })}
          />
        </ListSlot>
      ) : null}

      {tab === 'indexes' ? (
        <ListSlot
          label="правила индексов"
          jsonKey="index_rules"
          path={`${path}.index_rules`}
          inheritable={inheritable}
          defined={rules.index_rules !== undefined}
          onDefine={() => set({ index_rules: [] })}
          onReset={() => set({ index_rules: undefined })}
        >
          <IndexRulesTable
            rules={rules.index_rules ?? []}
            path={`${path}.index_rules`}
            onChange={(next) => set({ index_rules: next })}
          />
        </ListSlot>
      ) : null}

      {tab === 'order_by' ? (
        <ListSlot
          label="order_by_rules"
          jsonKey="order_by_rules"
          path={`${path}.order_by_rules`}
          inheritable={inheritable}
          defined={rules.order_by_rules !== undefined}
          onDefine={() => set({ order_by_rules: {} })}
          onReset={() => set({ order_by_rules: undefined })}
        >
          {rules.order_by_rules ? (
            <OrderByRulesEditor
              value={rules.order_by_rules}
              path={`${path}.order_by_rules`}
              onChange={(next) => set({ order_by_rules: next })}
            />
          ) : (
            <div className="row">
              <span className="muted">Блок order_by_rules отсутствует.</span>
              <button className="btn btn-sm" type="button" onClick={() => set({ order_by_rules: {} })}>
                Добавить блок
              </button>
            </div>
          )}
        </ListSlot>
      ) : null}

      {tab === 'column_order' ? (
        <ListSlot
          label="порядок колонок"
          jsonKey="column_order"
          path={`${path}.column_order`}
          inheritable={inheritable}
          defined={rules.column_order !== undefined}
          onDefine={() => set({ column_order: {} })}
          onReset={() => set({ column_order: undefined })}
        >
          <div className="stack-sm">
            <div className="faint">
              Явный порядок колонок в CREATE TABLE. Действует вместе с column_order_mode.
            </div>
            <ColumnOrderEditor
              value={rules.column_order ?? {}}
              onChange={(next) => set({ column_order: next })}
            />
          </div>
        </ListSlot>
      ) : null}

      <Disclosure title="Банк правил">
        <TextInputField
          label="Имя банка правил"
          jsonKey="rule_bank"
          path={`${path}.rule_bank`}
          value={rules.rule_bank}
          onChange={(next) => set({ rule_bank: next })}
          hint="Ссылка на именованный набор правил из файла rule_banks. Сам банк здесь не редактируется."
        />
      </Disclosure>
    </div>
  );
}
