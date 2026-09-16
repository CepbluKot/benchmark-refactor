/**
 * Локальная проверка scoring expression.
 *
 * Это упрощённое зеркало whitelist движка
 * (`src/benchmark_runtime/implementations/clickhouse_celery/scoring.py`):
 * проверяются только имена, функции и запрещённые конструкции.
 *
 * Полноценную проверку (AST + simpleeval) выполняет движок. Результат этой
 * функции нельзя называть «формула проверена движком».
 */

import { SCORING_FUNCTIONS, SCORING_ROOT_NAMES } from './vocab';

const LITERALS = new Set(['True', 'False', 'None', 'true', 'false', 'null']);

const PYTHON_KEYWORDS = new Set([
  'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break', 'class',
  'continue', 'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global',
  'if', 'import', 'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise',
  'return', 'try', 'while', 'with', 'yield',
]);

const IDENTIFIER_RE = /^[\p{L}\p{Nl}_][\p{L}\p{Nl}\p{Mn}\p{Mc}\p{Nd}\p{Pc}]*$/u;

export function isValidVariableName(name: string): string | undefined {
  const cleaned = name.trim();
  if (!cleaned) return 'имя переменной не должно быть пустым';
  if (!IDENTIFIER_RE.test(cleaned) || PYTHON_KEYWORDS.has(cleaned)) {
    return `недопустимое имя ${cleaned}: нужен валидный Python-идентификатор`;
  }
  if (cleaned.startsWith('_')) return `имя ${cleaned} не должно начинаться с '_'`;
  return undefined;
}

/** Убирает строковые литералы, чтобы их содержимое не читалось как имена. */
function stripStringLiterals(expression: string): string {
  return expression.replace(/'[^']*'|"[^"]*"/g, '""');
}

/** Разбирает выражение на «корневые» имена (без атрибутов после точки). */
function rootNames(expression: string): { name: string; isCall: boolean }[] {
  const found: { name: string; isCall: boolean }[] = [];
  const text = stripStringLiterals(expression);
  const re = /(\.)?([A-Za-z_][A-Za-z0-9_]*)\s*(\()?/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    if (match[1]) continue; // это атрибут: medians.source_select_read_bytes
    found.push({ name: match[2], isCall: Boolean(match[3]) });
  }
  return found;
}

export interface LintProblem {
  message: string;
}

/**
 * @param declared имена переменных, объявленных ДО текущего выражения
 *                 (движок разрешает ссылаться только на них).
 */
export function lintExpression(expression: string, declared: string[]): LintProblem[] {
  const problems: LintProblem[] = [];
  const text = expression.trim();
  if (!text) return [{ message: 'выражение не должно быть пустым' }];
  if (text.length > 4000) problems.push({ message: 'выражение длиннее 4000 символов' });

  if (/\blambda\b/.test(text)) problems.push({ message: 'lambda-выражения не поддерживаются' });
  if (/:=/.test(text)) problems.push({ message: "оператор ':=' не поддерживается" });
  if (/\bfor\b/.test(text)) problems.push({ message: 'comprehensions не поддерживаются' });
  if (/\/\/|<<|>>|[&|^]/.test(text)) {
    problems.push({ message: 'побитовые операторы и // не поддерживаются' });
  }

  const openCount = (text.match(/\(/g) ?? []).length;
  const closeCount = (text.match(/\)/g) ?? []).length;
  if (openCount !== closeCount) problems.push({ message: 'скобки не сбалансированы' });

  const allowedNames = new Set([...SCORING_ROOT_NAMES, ...declared]);
  const allowedFunctions = new Set(SCORING_FUNCTIONS);

  for (const { name, isCall } of rootNames(text)) {
    if (LITERALS.has(name)) continue;
    if (name.startsWith('_')) {
      problems.push({ message: `имя ${name} запрещено: идентификаторы с '_' в начале не допускаются` });
      continue;
    }
    if (isCall) {
      if (!allowedFunctions.has(name)) {
        problems.push({
          message: `функция ${name}() не поддерживается; разрешены: ${SCORING_FUNCTIONS.join(', ')}`,
        });
      }
      continue;
    }
    if (!allowedNames.has(name) && !allowedFunctions.has(name)) {
      problems.push({
        message:
          `неизвестное имя ${name}: это не переменная scoring.variables ` +
          'и не корневое имя метрик движка',
      });
    }
  }
  return problems;
}
