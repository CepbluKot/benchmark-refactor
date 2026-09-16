/**
 * Чтение сырого JSON в типизированную модель.
 *
 * Принципы:
 *   - отсутствие ключа и явное значение различаются;
 *   - незнакомый ключ не удаляется, а попадает в `$extra` и даёт ошибку;
 *   - ключ с неподдерживаемым типом тоже сохраняется в `$extra`,
 *     чтобы экспорт не терял содержимое файла.
 */

import type { Issue, SectionId } from './issues';

export interface ReadContext {
  issues: Issue[];
  benchmarkId?: string;
}

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export class Reader {
  private readonly used = new Set<string>();
  /** Ключи с неподдерживаемым значением: сохраняются ради честного экспорта. */
  private readonly invalid: Record<string, unknown> = {};

  constructor(
    private readonly raw: Record<string, unknown>,
    readonly path: string,
    private readonly ctx: ReadContext,
    private readonly section: SectionId,
  ) {}

  private at(key: string): string {
    return this.path ? `${this.path}.${key}` : key;
  }

  error(path: string, message: string, field?: string): void {
    this.ctx.issues.push({
      level: 'error',
      check: 'structure',
      path,
      message,
      section: this.section,
      benchmarkId: this.ctx.benchmarkId,
      field,
    });
  }

  private reject(key: string, message: string): undefined {
    this.error(this.at(key), message, key);
    this.markInvalid(key);
    return undefined;
  }

  /**
   * Помечает ключ как «значение не разобрано».
   * Исходное содержимое переносится в `$extra`, чтобы экспорт его не потерял.
   */
  private markInvalid(key: string): void {
    this.invalid[key] = this.raw[key];
  }

  private take(key: string): unknown {
    this.used.add(key);
    return this.raw[key];
  }

  /** Ключи, присутствовавшие в исходном объекте. */
  seen(): string[] {
    return Object.keys(this.raw);
  }

  has(key: string): boolean {
    return Object.prototype.hasOwnProperty.call(this.raw, key);
  }

  str(key: string, opts: { required?: boolean } = {}): string | undefined {
    const value = this.take(key);
    if (value === undefined) {
      if (opts.required) this.error(this.at(key), 'обязательное поле не заполнено', key);
      return undefined;
    }
    if (typeof value !== 'string') return this.reject(key, 'ожидалась строка');
    const cleaned = value.trim();
    if (!cleaned) return this.reject(key, 'значение не должно быть пустым');
    return cleaned;
  }

  int(key: string, opts: { required?: boolean; min?: number } = {}): number | undefined {
    const value = this.take(key);
    if (value === undefined) {
      if (opts.required) this.error(this.at(key), 'обязательное поле не заполнено', key);
      return undefined;
    }
    if (typeof value !== 'number' || !Number.isInteger(value)) {
      return this.reject(key, 'ожидалось целое число');
    }
    if (opts.min !== undefined && value < opts.min) {
      return this.reject(key, `значение должно быть >= ${opts.min}`);
    }
    return value;
  }

  float(key: string): number | undefined {
    const value = this.take(key);
    if (value === undefined) return undefined;
    if (typeof value !== 'number' || !Number.isFinite(value)) {
      return this.reject(key, 'ожидалось число');
    }
    return value;
  }

  bool(key: string): boolean | undefined {
    const value = this.take(key);
    if (value === undefined) return undefined;
    if (typeof value !== 'boolean') return this.reject(key, 'ожидалось true или false');
    return value;
  }

  enumOf<T extends string>(
    key: string,
    allowed: readonly T[],
    opts: { required?: boolean } = {},
  ): T | undefined {
    const value = this.take(key);
    if (value === undefined) {
      if (opts.required) this.error(this.at(key), 'обязательное поле не заполнено', key);
      return undefined;
    }
    if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) {
      return this.reject(key, `допустимые значения: ${allowed.join(', ')}`);
    }
    return value as T;
  }

  strList(key: string): string[] | undefined {
    const value = this.take(key);
    if (value === undefined) return undefined;
    if (!Array.isArray(value)) return this.reject(key, 'ожидался список строк');
    const result: string[] = [];
    for (let i = 0; i < value.length; i += 1) {
      const item = value[i];
      if (typeof item !== 'string') {
        this.error(`${this.at(key)}[${i}]`, 'ожидалась строка', key);
        this.markInvalid(key);
        continue;
      }
      result.push(item);
    }
    return result;
  }

  intList(key: string): number[] | undefined {
    const value = this.take(key);
    if (value === undefined) return undefined;
    if (!Array.isArray(value)) return this.reject(key, 'ожидался список целых чисел');
    const result: number[] = [];
    for (let i = 0; i < value.length; i += 1) {
      const item = value[i];
      if (typeof item !== 'number' || !Number.isInteger(item)) {
        this.error(`${this.at(key)}[${i}]`, 'ожидалось целое число', key);
        this.markInvalid(key);
        continue;
      }
      result.push(item);
    }
    return result;
  }

  strMap(key: string): Record<string, string> | undefined {
    const value = this.take(key);
    if (value === undefined) return undefined;
    if (!isPlainObject(value)) return this.reject(key, 'ожидался объект');
    const result: Record<string, string> = {};
    for (const [name, item] of Object.entries(value)) {
      if (typeof item !== 'string') {
        this.error(`${this.at(key)}.${name}`, 'ожидалась строка', key);
        this.markInvalid(key);
        continue;
      }
      result[name] = item;
    }
    return result;
  }

  intMap(key: string): Record<string, number> | undefined {
    const value = this.take(key);
    if (value === undefined) return undefined;
    if (!isPlainObject(value)) return this.reject(key, 'ожидался объект');
    const result: Record<string, number> = {};
    for (const [name, item] of Object.entries(value)) {
      if (typeof item !== 'number' || !Number.isInteger(item)) {
        this.error(`${this.at(key)}.${name}`, 'ожидалось целое число', key);
        this.markInvalid(key);
        continue;
      }
      result[name] = item;
    }
    return result;
  }

  obj(key: string): Record<string, unknown> | undefined {
    const value = this.take(key);
    if (value === undefined) return undefined;
    if (!isPlainObject(value)) return this.reject(key, 'ожидался объект');
    return value;
  }

  objList(key: string): Record<string, unknown>[] | undefined {
    const value = this.take(key);
    if (value === undefined) return undefined;
    if (!Array.isArray(value)) return this.reject(key, 'ожидался список объектов');
    const result: Record<string, unknown>[] = [];
    for (let i = 0; i < value.length; i += 1) {
      const item = value[i];
      if (!isPlainObject(item)) {
        this.error(`${this.at(key)}[${i}]`, 'ожидался объект', key);
        this.markInvalid(key);
        continue;
      }
      result.push(item);
    }
    return result;
  }

  /** Произвольное значение без проверки типа (селекторы databases/tables). */
  any(key: string): unknown {
    return this.take(key);
  }

  /** Имена ключей, значение которых не удалось разобрать. */
  invalidKeys(): string[] | undefined {
    const keys = Object.keys(this.invalid);
    return keys.length ? keys : undefined;
  }

  /**
   * Возвращает оставшиеся ключи. Каждый из них — ошибка для движка
   * (`model_config = {"extra": "forbid"}`), но значение сохраняется.
   */
  rest(): Record<string, unknown> | undefined {
    const extra: Record<string, unknown> = { ...this.invalid };
    let found = Object.keys(this.invalid).length > 0;
    for (const [key, value] of Object.entries(this.raw)) {
      if (this.used.has(key)) continue;
      found = true;
      extra[key] = value;
      this.ctx.issues.push({
        level: 'error',
        check: 'structure',
        path: this.at(key),
        message: 'поле не поддерживается моделью конфигурации и будет отклонено движком',
        section: this.section,
        benchmarkId: this.ctx.benchmarkId,
        field: key,
      });
    }
    return found ? extra : undefined;
  }
}

/** Убирает undefined-поля, чтобы «не задано» не превращалось в ключ со значением. */
export function compact<T extends Record<string, unknown>>(value: T): T {
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (item === undefined) continue;
    result[key] = item;
  }
  return result as T;
}
