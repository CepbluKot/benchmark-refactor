/**
 * Редактор блока `scoring`.
 *
 * Проверка формулы здесь локальная: сверяются имена, функции и запрещённые
 * конструкции. Полную проверку выполняет движок отдельным шагом.
 */

import type { ScoringConfig, StageScoringConfig } from '../../types/config';
import { moveItem, patch } from '../../lib/edit';
import { lintExpression, isValidVariableName } from '../../lib/scoringLint';
import { PHASED_STAGES, SCORING_FUNCTIONS } from '../../lib/vocab';
import { Field } from '../fields/Field';
import { Disclosure, NumberInputField } from '../fields/inputs';

function reorderVariables(
  variables: Record<string, string>,
  from: number,
  to: number,
): Record<string, string> {
  const entries = moveItem(Object.entries(variables), from, to);
  return Object.fromEntries(entries);
}

function renameVariable(
  variables: Record<string, string>,
  from: string,
  to: string,
): Record<string, string> {
  const next: Record<string, string> = {};
  for (const [key, value] of Object.entries(variables)) next[key === from ? to : key] = value;
  return next;
}

function ExpressionField({
  label,
  value,
  declared,
  onChange,
  path,
  rows = 4,
}: {
  label: string;
  value: string | undefined;
  declared: string[];
  onChange(next: string): void;
  path: string;
  rows?: number;
}): JSX.Element {
  const problems = value ? lintExpression(value, declared) : [];
  return (
    <Field
      label={label}
      jsonKey="expression"
      path={path}
      hint={
        <>
          Доступные функции: <code>{SCORING_FUNCTIONS.join(', ')}</code>.
        </>
      }
    >
      <textarea
        className={`sql-area${problems.length ? ' invalid' : ''}`}
        rows={rows}
        spellCheck={false}
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
      />
      {problems.length ? (
        <div className="notice notice-danger" style={{ marginTop: 8, marginBottom: 0 }}>
          <strong>Локальная проверка выражения</strong>
          {problems.map((problem) => (
            <div key={problem.message}>{problem.message}</div>
          ))}
        </div>
      ) : value ? (
        <div className="notice notice-info" style={{ marginTop: 8, marginBottom: 0 }}>
          Локальная проверка имён и функций прошла. Полную проверку выражения выполняет движок —
          здесь она недоступна.
        </div>
      ) : null}
    </Field>
  );
}

function VariablesTable({
  variables,
  onChange,
  path,
}: {
  variables: Record<string, string> | undefined;
  onChange(next: Record<string, string> | undefined): void;
  path: string;
}): JSX.Element {
  if (variables === undefined) {
    return (
      <div className="row">
        <span className="inherit-tag">Переменные не заданы</span>
        <span className="field-key">{path}</span>
        <button
          className="btn btn-sm"
          type="button"
          onClick={() => onChange({ compression_ratio: 'safe_div(source_size_bytes, tested_size_bytes, 1.0)' })}
        >
          Добавить переменные
        </button>
      </div>
    );
  }

  const entries = Object.entries(variables);

  return (
    <div className="stack-sm">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th style={{ width: 210 }}>Имя переменной</th>
              <th>Выражение</th>
              <th style={{ width: 118 }} />
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 ? (
              <tr>
                <td colSpan={3} className="muted">
                  Пустой список переменных модель не принимает.
                </td>
              </tr>
            ) : null}
            {entries.map(([name, expression], index) => {
              const declared = entries.slice(0, index).map(([key]) => key);
              const nameProblem = isValidVariableName(name);
              const problems = lintExpression(expression, declared);
              return (
                <tr key={index}>
                  <td>
                    <input
                      className={`control mono${nameProblem ? ' invalid' : ''}`}
                      value={name}
                      onChange={(event) =>
                        onChange(renameVariable(variables, name, event.target.value))
                      }
                    />
                    {nameProblem ? <div className="field-error">{nameProblem}</div> : null}
                  </td>
                  <td>
                    <textarea
                      className={`control mono${problems.length ? ' invalid' : ''}`}
                      rows={2}
                      spellCheck={false}
                      value={expression}
                      onChange={(event) => onChange({ ...variables, [name]: event.target.value })}
                    />
                    {problems.map((problem) => (
                      <div className="field-error" key={problem.message}>
                        {problem.message}
                      </div>
                    ))}
                  </td>
                  <td>
                    <div className="inline-actions">
                      <button
                        className="btn btn-sm btn-ghost"
                        type="button"
                        disabled={index === 0}
                        title="Выше: переменная должна быть объявлена до использования"
                        onClick={() => onChange(reorderVariables(variables, index, index - 1))}
                      >
                        ↑
                      </button>
                      <button
                        className="btn btn-sm btn-ghost"
                        type="button"
                        disabled={index === entries.length - 1}
                        onClick={() => onChange(reorderVariables(variables, index, index + 1))}
                      >
                        ↓
                      </button>
                      <button
                        className="btn btn-sm btn-ghost btn-danger"
                        type="button"
                        onClick={() => {
                          const next = { ...variables };
                          delete next[name];
                          onChange(next);
                        }}
                      >
                        ✕
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="row">
        <button
          className="btn btn-sm"
          type="button"
          onClick={() => onChange({ ...variables, [`var_${entries.length + 1}`]: '1.0' })}
        >
          Добавить переменную
        </button>
        <button
          className="btn btn-sm btn-ghost btn-danger"
          type="button"
          onClick={() => onChange(undefined)}
        >
          Убрать блок переменных
        </button>
        <span className="faint">
          Порядок важен: выражение может ссылаться только на переменные, объявленные выше.
        </span>
      </div>
    </div>
  );
}

function TopSelection({
  value,
  onChange,
}: {
  value: 'max' | 'min';
  onChange(next: 'max' | 'min'): void;
}): JSX.Element {
  return (
    <Field
      label="Направление отбора"
      jsonKey="top_selection"
      path="scoring.top_selection"
      hint="Что считать лучшим результатом при сортировке кандидатов."
    >
      <div className="segmented">
        <button
          type="button"
          className={value === 'max' ? 'active' : ''}
          onClick={() => onChange('max')}
        >
          Больше — лучше (max)
        </button>
        <button
          type="button"
          className={value === 'min' ? 'active' : ''}
          onClick={() => onChange('min')}
        >
          Меньше — лучше (min)
        </button>
      </div>
    </Field>
  );
}

export function StageScoringEditor({
  scoring,
  onChange,
  path,
}: {
  scoring: StageScoringConfig;
  onChange(next: StageScoringConfig): void;
  path: string;
}): JSX.Element {
  const declared = Object.keys(scoring.variables ?? {});
  return (
    <div className="stack">
      <TopSelection
        value={scoring.top_selection}
        onChange={(next) => onChange(patch(scoring, { top_selection: next }))}
      />
      <VariablesTable
        variables={scoring.variables}
        path={`${path}.variables`}
        onChange={(next) => onChange(patch(scoring, { variables: next }))}
      />
      <ExpressionField
        label="Формула итоговой оценки"
        value={scoring.expression}
        declared={declared}
        path={`${path}.expression`}
        onChange={(next) => onChange(patch(scoring, { expression: next }))}
      />
      <NumberInputField
        label="Оценка при ошибке замера"
        jsonKey="on_error_score"
        path={`${path}.on_error_score`}
        value={scoring.on_error_score}
        onChange={(next) => onChange(patch(scoring, { on_error_score: next }))}
        optional
        defaultHint="кандидат с ошибкой остаётся без оценки."
        hint="Поле текущего формата конфигурации. В целевой архитектуре числовая оценка вместо ошибки запрещена — это другой контракт, не смешивайте их."
      />
    </div>
  );
}

export function ScoringEditor({
  scoring,
  onChange,
  path,
}: {
  scoring: ScoringConfig;
  onChange(next: ScoringConfig): void;
  path: string;
}): JSX.Element {
  const stages = scoring.by_stage ?? {};

  return (
    <div className="stack">
      <StageScoringEditor
        scoring={scoring}
        path={path}
        onChange={(next) => onChange(patch(scoring, next as Partial<ScoringConfig>))}
      />

      <Disclosure
        title={`Формулы по этапам (${Object.keys(stages).length})`}
        defaultOpen={Object.keys(stages).length > 0}
      >
        <div className="stack">
          <div className="faint">
            Переопределяют общую формулу на конкретной стадии конвейера.
          </div>
          {Object.entries(stages).map(([stageName, stageScoring]) => (
            <section className="card" key={stageName} style={{ marginBottom: 0 }}>
              <div className="card-head">
                <span className="mono">{stageName}</span>
                <span className="spacer" style={{ marginLeft: 'auto' }}>
                  <button
                    className="btn btn-sm btn-ghost btn-danger"
                    type="button"
                    onClick={() => {
                      const next = { ...stages };
                      delete next[stageName];
                      onChange(
                        patch(scoring, {
                          by_stage: Object.keys(next).length ? next : undefined,
                        }),
                      );
                    }}
                  >
                    Убрать формулу этапа
                  </button>
                </span>
              </div>
              <div className="card-body">
                <StageScoringEditor
                  scoring={stageScoring}
                  path={`${path}.by_stage.${stageName}`}
                  onChange={(next) =>
                    onChange(patch(scoring, { by_stage: { ...stages, [stageName]: next } }))
                  }
                />
              </div>
            </section>
          ))}
          <div className="row">
            <select
              className="control"
              style={{ maxWidth: 260 }}
              value=""
              onChange={(event) => {
                const stage = event.target.value;
                if (!stage || stages[stage]) return;
                onChange(
                  patch(scoring, {
                    by_stage: {
                      ...stages,
                      [stage]: {
                        mode: 'expression',
                        top_selection: scoring.top_selection,
                        expression: scoring.expression,
                        $seen: ['mode', 'top_selection', 'expression'],
                      },
                    },
                  }),
                );
              }}
            >
              <option value="">добавить формулу для этапа…</option>
              {PHASED_STAGES.filter((stage) => !stages[stage.key]).map((stage) => (
                <option key={stage.key} value={stage.key}>
                  {stage.label} — {stage.key}
                </option>
              ))}
            </select>
          </div>
        </div>
      </Disclosure>
    </div>
  );
}
