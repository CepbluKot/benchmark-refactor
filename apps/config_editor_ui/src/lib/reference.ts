/**
 * Справочные файлы проекта: подключения и банки правил.
 *
 * Эти файлы здесь не редактируются. Они нужны только чтобы включить
 * проверку уровня 3 — существование `connection_id` и `rules.rule_bank`.
 * Пароли из файла подключений не читаются и нигде не отображаются.
 */

import { isPlainObject } from './reader';

export interface ConnectionSummary {
  id: string;
  dbms: string;
  host: string;
  port: number;
}

export type ReferenceKind = 'connections' | 'rule_banks';

export interface ReferenceParseResult {
  kind?: ReferenceKind;
  connections?: ConnectionSummary[];
  ruleBanks?: string[];
  error?: string;
}

export function parseReferenceFile(text: string): ReferenceParseResult {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (error) {
    return { error: `Файл не разобран как JSON: ${(error as Error).message}` };
  }
  if (!isPlainObject(raw)) return { error: 'Ожидался объект JSON на верхнем уровне' };

  if (Array.isArray(raw.connections)) {
    const connections: ConnectionSummary[] = [];
    for (const item of raw.connections) {
      if (!isPlainObject(item) || typeof item.id !== 'string') continue;
      connections.push({
        id: item.id,
        dbms: typeof item.dbms === 'string' ? item.dbms : 'clickhouse',
        host: typeof item.host === 'string' ? item.host : '',
        port: typeof item.port === 'number' ? item.port : 0,
      });
    }
    if (!connections.length) return { error: 'В файле подключений нет ни одной записи с id' };
    return { kind: 'connections', connections };
  }

  if (isPlainObject(raw.rule_banks)) {
    return { kind: 'rule_banks', ruleBanks: Object.keys(raw.rule_banks) };
  }

  return { error: 'Это не файл подключений и не файл банков правил' };
}
