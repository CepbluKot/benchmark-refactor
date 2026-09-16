/** Иммутабельные правки модели с сохранением семантики «задано / не задано». */

import type { WithExtra } from '../types/config';

/**
 * Применяет изменения к узлу конфигурации.
 *
 * Дополнительно:
 *   - ключ помечается как «присутствует в файле» (`$seen`), поэтому явно
 *     выставленное значение по умолчанию не исчезнет при экспорте;
 *   - если ключ лежал в `$extra` как неразобранный, он оттуда убирается —
 *     правка пользователя важнее сохранённого исходного значения.
 */
export function patch<T extends WithExtra>(node: T, changes: Partial<T>): T {
  const next = { ...node, ...changes } as T;
  const keys = Object.keys(changes);

  const seen = new Set(node.$seen ?? []);
  for (const key of keys) {
    if ((changes as Record<string, unknown>)[key] === undefined) seen.delete(key);
    else seen.add(key);
  }
  next.$seen = [...seen];

  if (node.$extra) {
    const extra = { ...node.$extra };
    let changed = false;
    for (const key of keys) {
      if (key in extra) {
        delete extra[key];
        changed = true;
      }
    }
    if (changed) next.$extra = Object.keys(extra).length ? extra : undefined;
  }

  if (node.$invalidKeys) {
    const rest = node.$invalidKeys.filter((key) => !keys.includes(key));
    next.$invalidKeys = rest.length ? rest : undefined;
  }
  return next;
}

export function replaceAt<T>(items: T[], index: number, value: T): T[] {
  const next = items.slice();
  next[index] = value;
  return next;
}

export function removeAt<T>(items: T[], index: number): T[] {
  const next = items.slice();
  next.splice(index, 1);
  return next;
}

export function insertAt<T>(items: T[], index: number, value: T): T[] {
  const next = items.slice();
  next.splice(index, 0, value);
  return next;
}

export function moveItem<T>(items: T[], from: number, to: number): T[] {
  if (to < 0 || to >= items.length || from === to) return items;
  const next = items.slice();
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

/** Глубокая копия без служебных ссылок (используется при дублировании). */
export function cloneNode<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/** Разбирает многострочный ввод в список непустых строк. */
export function parseLines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/** Разбирает список целых чисел из строки вида "8192, 16384". */
export function parseIntList(text: string): { values: number[]; invalid: string[] } {
  const values: number[] = [];
  const invalid: string[] = [];
  for (const token of text.split(/[\s,]+/).filter(Boolean)) {
    const parsed = Number(token);
    if (!Number.isInteger(parsed) || parsed <= 0) invalid.push(token);
    else values.push(parsed);
  }
  return { values, invalid };
}
