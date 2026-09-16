/** Модель проблем конфигурации и уровней проверки. */

export type IssueLevel = 'error' | 'warning';

/**
 * Уровни проверки. Фронтенд без сервера честно закрывает только 1–2;
 * 3 — частично (ссылки внутри загруженных файлов); 4–5 требуют бэкенда.
 */
export type CheckLevel =
  | 'json'        // 1. синтаксис JSON
  | 'structure'   // 2. структура и локальные ограничения модели
  | 'cross-file'  // 3. межфайловые ссылки (connection_id, rule_bank)
  | 'engine'      // 4. проверка средствами движка
  | 'connection'; // 5. подключение и объекты БД

export const CHECK_LEVEL_LABEL: Record<CheckLevel, string> = {
  json: '1. Синтаксис JSON',
  structure: '2. Структура и ограничения',
  'cross-file': '3. Межфайловые ссылки',
  engine: '4. Проверка движком',
  connection: '5. Подключение и объекты БД',
};

export type SectionId =
  | 'file'
  | 'source'
  | 'rules'
  | 'queries'
  | 'limits'
  | 'scoring'
  | 'tables';

export interface Issue {
  level: IssueLevel;
  check: CheckLevel;
  /** Технический путь в JSON, например `benchmarks[0].queries.test_queries[1].query`. */
  path: string;
  message: string;
  /** Раздел редактора, который надо открыть по клику. */
  section: SectionId;
  /** id бенчмарка, к которому относится проблема. */
  benchmarkId?: string;
  /** Ключ поля для передачи фокуса (data-field в разметке). */
  field?: string;
}

export const SECTION_TITLE: Record<SectionId, string> = {
  file: 'Файл',
  source: 'Источник и стратегия',
  rules: 'Правила вариантов',
  queries: 'Тестовые запросы',
  limits: 'Лимиты',
  scoring: 'Оценка',
  tables: 'Настройки отдельных таблиц',
};

/** Короткие подписи для вкладок редактора. */
export const SECTION_TAB_LABEL: Record<SectionId, string> = {
  file: 'Файл',
  source: 'Источник',
  rules: 'Правила',
  queries: 'Запросы',
  limits: 'Лимиты',
  scoring: 'Оценка',
  tables: 'Таблицы',
};

export function issueKey(issue: Issue): string {
  return `${issue.benchmarkId ?? '-'}|${issue.path}|${issue.message}`;
}
