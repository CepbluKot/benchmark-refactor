/**
 * Редактор лимитов по режимам/стадиям.
 *
 * Отсутствующий ключ и явное значение — разные вещи, поэтому пустая ячейка
 * показывается как «—», а не как 0.
 */

import { useState } from 'react';

import type { ModeLimitsConfig } from '../../types/config';

export interface LimitsMapEditorProps {
  value: ModeLimitsConfig | undefined;
  onChange(next: ModeLimitsConfig | undefined): void;
  /** Ожидаемые ключи: подписи строк таблицы. */
  keys: { key: string; label: string }[];
  /** Единица измерения значения: строки, операции, кандидаты, победители. */
  unit: string;
  jsonKey: string;
}

export function LimitsMapEditor({
  value,
  onChange,
  keys,
  unit,
  jsonKey,
}: LimitsMapEditorProps): JSX.Element {
  const [customKey, setCustomKey] = useState('');
  const knownKeys = new Set(keys.map((item) => item.key));
  const extraKeys = Object.keys(value ?? {}).filter((key) => !knownKeys.has(key));

  const setKey = (key: string, raw: string) => {
    const next = { ...(value ?? {}) };
    if (raw.trim() === '') delete next[key];
    else {
      const parsed = Number(raw);
      if (!Number.isFinite(parsed)) return;
      next[key] = parsed;
    }
    onChange(Object.keys(next).length ? next : value === undefined ? undefined : next);
  };

  if (value === undefined) {
    return (
      <div className="row">
        <span className="inherit-tag">Поле не задано</span>
        <span className="field-key">{jsonKey}</span>
        <button className="btn btn-sm" type="button" onClick={() => onChange({})}>
          Задать лимиты
        </button>
      </div>
    );
  }

  return (
    <div className="stack-sm">
      <div className="row">
        <span className="override-tag">Задано</span>
        <span className="field-key">{jsonKey}</span>
        <span style={{ marginLeft: 'auto' }}>
          <button
            className="btn btn-sm btn-ghost btn-danger"
            type="button"
            onClick={() => onChange(undefined)}
          >
            Убрать поле
          </button>
        </span>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Этап / режим</th>
              <th>Ключ</th>
              <th style={{ width: 160 }}>Значение, {unit}</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((item) => (
              <tr key={item.key}>
                <td>{item.label}</td>
                <td className="mono faint">{item.key}</td>
                <td>
                  <input
                    className="control mono"
                    inputMode="numeric"
                    placeholder="—"
                    value={value[item.key] ?? ''}
                    onChange={(event) => setKey(item.key, event.target.value)}
                  />
                </td>
              </tr>
            ))}
            {extraKeys.map((key) => (
              <tr key={key}>
                <td className="muted">дополнительный ключ</td>
                <td className="mono">{key}</td>
                <td>
                  <input
                    className="control mono"
                    inputMode="numeric"
                    placeholder="—"
                    value={value[key] ?? ''}
                    onChange={(event) => setKey(key, event.target.value)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row">
        <input
          className="control mono"
          style={{ maxWidth: 220 }}
          placeholder="свой ключ режима"
          value={customKey}
          onChange={(event) => setCustomKey(event.target.value)}
        />
        <button
          className="btn btn-sm"
          type="button"
          disabled={!customKey.trim()}
          onClick={() => {
            onChange({ ...(value ?? {}), [customKey.trim()]: 1 });
            setCustomKey('');
          }}
        >
          Добавить ключ
        </button>
        <span className="faint">Модель допускает дополнительные ключи для будущих режимов.</span>
      </div>
    </div>
  );
}
