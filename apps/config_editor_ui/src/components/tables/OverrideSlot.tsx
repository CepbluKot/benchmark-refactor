/**
 * Обёртка поля с переопределением.
 *
 * «Наследуется» — поля нет в table_rules, действует значение бенчмарка.
 * «Переопределено» — поле задано локально.
 * Сброс удаляет локальное поле, а не копирует общее значение.
 */

import type { ReactNode } from 'react';

export function OverrideSlot({
  label,
  jsonKey,
  overridden,
  inherited,
  onDefine,
  onReset,
  children,
}: {
  label: string;
  jsonKey: string;
  overridden: boolean;
  /** Значение, которое действует при наследовании. */
  inherited: ReactNode;
  onDefine(): void;
  onReset(): void;
  children: ReactNode;
}): JSX.Element {
  return (
    <div className="field">
      <div className="field-label">
        <span>{label}</span>
        <span className="field-key">{jsonKey}</span>
        <span style={{ marginLeft: 'auto' }}>
          {overridden ? (
            <span className="row">
              <span className="override-tag">Переопределено</span>
              <button className="btn btn-sm btn-ghost btn-danger" type="button" onClick={onReset}>
                Сбросить переопределение
              </button>
            </span>
          ) : (
            <span className="row">
              <span className="inherit-tag">Наследуется</span>
              <button className="btn btn-sm" type="button" onClick={onDefine}>
                Переопределить
              </button>
            </span>
          )}
        </span>
      </div>
      {overridden ? (
        children
      ) : (
        <div className="mono faint">
          {inherited === undefined || inherited === null || inherited === '' ? '—' : inherited}
        </div>
      )}
    </div>
  );
}
