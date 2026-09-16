/** Элементы ввода. Различают «поле не задано» и «задано значение». */

import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { Field, useIssuesFor } from './Field';
import type { Choice } from '../../lib/vocab';
import { parseIntList, parseLines } from '../../lib/edit';

function controlClass(invalid: boolean, mono?: boolean): string {
  return `control${mono ? ' mono' : ''}${invalid ? ' invalid' : ''}`;
}

export interface BaseFieldProps {
  label: string;
  jsonKey: string;
  hint?: ReactNode;
  path?: string;
  focusKey?: string;
}

export function TextInputField({
  label,
  jsonKey,
  hint,
  path,
  focusKey,
  value,
  onChange,
  placeholder,
  mono = true,
  right,
}: BaseFieldProps & {
  value: string | undefined;
  onChange(next: string | undefined): void;
  placeholder?: string;
  mono?: boolean;
  right?: ReactNode;
}): JSX.Element {
  const issues = useIssuesFor(path ?? jsonKey);
  return (
    <Field
      label={label}
      jsonKey={jsonKey}
      hint={hint}
      path={path ?? jsonKey}
      focusKey={focusKey ?? jsonKey}
      right={right}
    >
      <input
        className={controlClass(issues.some((i) => i.level === 'error'), mono)}
        value={value ?? ''}
        placeholder={placeholder ?? 'не задано'}
        onChange={(event) => {
          const next = event.target.value;
          onChange(next.trim() === '' ? undefined : next);
        }}
      />
    </Field>
  );
}

export function NumberInputField({
  label,
  jsonKey,
  hint,
  path,
  focusKey,
  value,
  onChange,
  optional = false,
  unit,
  defaultHint,
}: BaseFieldProps & {
  value: number | undefined;
  onChange(next: number | undefined): void;
  optional?: boolean;
  unit?: string;
  /** Что произойдёт, если поле не задано. */
  defaultHint?: string;
}): JSX.Element {
  const issues = useIssuesFor(path ?? jsonKey);
  const [text, setText] = useState(value === undefined ? '' : String(value));

  useEffect(() => {
    setText(value === undefined ? '' : String(value));
  }, [value]);

  const invalid = text.trim() !== '' && !Number.isFinite(Number(text));

  return (
    <Field
      label={label}
      jsonKey={jsonKey}
      hint={
        <>
          {hint}
          {optional && value === undefined && defaultHint ? (
            <div className="faint">Не задано — {defaultHint}</div>
          ) : null}
        </>
      }
      path={path ?? jsonKey}
      focusKey={focusKey ?? jsonKey}
      right={
        optional && value !== undefined ? (
          <button className="btn btn-ghost btn-sm" onClick={() => onChange(undefined)} type="button">
            Убрать значение
          </button>
        ) : null
      }
    >
      <div className="row" style={{ gap: 6, flexWrap: 'nowrap' }}>
        <input
          className={controlClass(invalid || issues.some((i) => i.level === 'error'), true)}
          inputMode="numeric"
          value={text}
          placeholder={optional ? 'не задано' : ''}
          onChange={(event) => {
            const next = event.target.value;
            setText(next);
            if (next.trim() === '') {
              onChange(undefined);
              return;
            }
            const parsed = Number(next);
            if (Number.isFinite(parsed)) onChange(parsed);
          }}
        />
        {unit ? <span className="faint nowrap">{unit}</span> : null}
      </div>
    </Field>
  );
}

export function BoolField({
  label,
  jsonKey,
  hint,
  path,
  value,
  onChange,
}: BaseFieldProps & {
  value: boolean;
  onChange(next: boolean): void;
}): JSX.Element {
  const id = `${jsonKey}-${label}`;
  return (
    <div className="field" data-path={path ?? jsonKey}>
      <div className="checkbox-row">
        <input
          id={id}
          type="checkbox"
          checked={value}
          onChange={(event) => onChange(event.target.checked)}
        />
        <label htmlFor={id}>
          <span>{label}</span> <span className="field-key">{jsonKey}</span>
          {hint ? <div className="field-hint">{hint}</div> : null}
        </label>
      </div>
    </div>
  );
}

export function SelectField<T extends string>({
  label,
  jsonKey,
  hint,
  path,
  focusKey,
  value,
  choices,
  onChange,
  allowEmpty,
  emptyLabel = 'не задано',
}: BaseFieldProps & {
  value: T | undefined;
  choices: Choice<T>[];
  onChange(next: T | undefined): void;
  allowEmpty?: boolean;
  emptyLabel?: string;
}): JSX.Element {
  const selected = choices.find((choice) => choice.value === value);
  return (
    <Field
      label={label}
      jsonKey={jsonKey}
      hint={selected ? selected.hint : hint}
      path={path ?? jsonKey}
      focusKey={focusKey ?? jsonKey}
    >
      <select
        className="control"
        value={value ?? ''}
        onChange={(event) => {
          const next = event.target.value;
          onChange(next === '' ? undefined : (next as T));
        }}
      >
        {allowEmpty ? <option value="">{emptyLabel}</option> : null}
        {choices.map((choice) => (
          <option key={choice.value} value={choice.value}>
            {choice.label} — {choice.value}
          </option>
        ))}
      </select>
    </Field>
  );
}

/**
 * Список строк. Пустой ввод означает пустой список, а не «поле не задано»,
 * поэтому у опциональных списков есть отдельное действие «Убрать поле».
 */
export function StringListField({
  label,
  jsonKey,
  hint,
  path,
  focusKey,
  value,
  onChange,
  optional = false,
  rows = 3,
  placeholder,
}: BaseFieldProps & {
  value: string[] | undefined;
  onChange(next: string[] | undefined): void;
  optional?: boolean;
  rows?: number;
  placeholder?: string;
}): JSX.Element {
  const [text, setText] = useState((value ?? []).join('\n'));
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!dirty) setText((value ?? []).join('\n'));
  }, [value, dirty]);

  const issues = useIssuesFor(path ?? jsonKey);

  return (
    <Field
      label={label}
      jsonKey={jsonKey}
      hint={
        <>
          {hint}
          {optional && value === undefined ? <div className="faint">Поле не задано.</div> : null}
        </>
      }
      path={path ?? jsonKey}
      focusKey={focusKey ?? jsonKey}
      right={
        optional ? (
          value === undefined ? (
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => onChange([])}>
              Задать список
            </button>
          ) : (
            <button
              className="btn btn-ghost btn-sm"
              type="button"
              onClick={() => {
                setDirty(false);
                onChange(undefined);
              }}
            >
              Убрать поле
            </button>
          )
        ) : null
      }
    >
      {optional && value === undefined ? (
        <div className="faint mono">—</div>
      ) : (
        <textarea
          className={`control mono${issues.some((i) => i.level === 'error') ? ' invalid' : ''}`}
          rows={rows}
          value={text}
          placeholder={placeholder ?? 'по одному значению в строке'}
          onChange={(event) => {
            setDirty(true);
            setText(event.target.value);
            onChange(parseLines(event.target.value));
          }}
          onBlur={() => setDirty(false)}
        />
      )}
    </Field>
  );
}

/** Список целых чисел, вводится через запятую или пробел. */
export function IntListField({
  label,
  jsonKey,
  hint,
  path,
  focusKey,
  value,
  onChange,
  placeholder = 'например: 8192, 16384',
}: BaseFieldProps & {
  value: number[] | undefined;
  onChange(next: number[] | undefined): void;
  placeholder?: string;
}): JSX.Element {
  const [text, setText] = useState((value ?? []).join(', '));
  const [dirty, setDirty] = useState(false);
  const [invalidTokens, setInvalidTokens] = useState<string[]>([]);

  useEffect(() => {
    if (!dirty) setText((value ?? []).join(', '));
  }, [value, dirty]);

  return (
    <Field
      label={label}
      jsonKey={jsonKey}
      hint={
        <>
          {hint}
          {value === undefined ? <div className="faint">Поле не задано.</div> : null}
          {invalidTokens.length ? (
            <div className="field-error">
              не целые положительные числа: {invalidTokens.join(', ')}
            </div>
          ) : null}
        </>
      }
      path={path ?? jsonKey}
      focusKey={focusKey ?? jsonKey}
      right={
        value !== undefined ? (
          <button
            className="btn btn-ghost btn-sm"
            type="button"
            onClick={() => {
              setDirty(false);
              setInvalidTokens([]);
              onChange(undefined);
            }}
          >
            Убрать поле
          </button>
        ) : null
      }
    >
      <input
        className={`control mono${invalidTokens.length ? ' invalid' : ''}`}
        value={text}
        placeholder={placeholder}
        onChange={(event) => {
          const next = event.target.value;
          setDirty(true);
          setText(next);
          if (next.trim() === '') {
            setInvalidTokens([]);
            onChange(undefined);
            return;
          }
          const { values, invalid } = parseIntList(next);
          setInvalidTokens(invalid);
          onChange(values);
        }}
        onBlur={() => setDirty(false)}
      />
    </Field>
  );
}

export function RadioCards<T extends string>({
  value,
  choices,
  onChange,
  name,
}: {
  value: T | undefined;
  choices: Choice<T>[];
  onChange(next: T): void;
  name: string;
}): JSX.Element {
  return (
    <div className="radio-cards">
      {choices.map((choice) => (
        <label
          key={choice.value}
          className={`radio-card${value === choice.value ? ' active' : ''}`}
        >
          <input
            type="radio"
            name={name}
            checked={value === choice.value}
            onChange={() => onChange(choice.value)}
          />
          <span>
            <span className="radio-card-title">
              <strong>{choice.label}</strong>
              <span className="field-key">{choice.value}</span>
            </span>
            <span className="radio-card-hint">{choice.hint}</span>
          </span>
        </label>
      ))}
    </div>
  );
}

export function Disclosure({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
}): JSX.Element {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="disclosure">
      <button className="disclosure-toggle" type="button" onClick={() => setOpen(!open)}>
        <span className="mono">{open ? '▾' : '▸'}</span>
        {title}
      </button>
      {open ? <div className="disclosure-body">{children}</div> : null}
    </div>
  );
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  note,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  note?: ReactNode;
}): JSX.Element {
  return (
    <section className="card">
      <div className="card-head">
        <h3>{title}</h3>
        {subtitle ? <span className="faint">{subtitle}</span> : null}
        {actions ? <span className="spacer">{actions}</span> : null}
      </div>
      <div className="card-body">{children}</div>
      {note ? <div className="card-note">{note}</div> : null}
    </section>
  );
}
