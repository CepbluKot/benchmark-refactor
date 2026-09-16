/**
 * Проверка сохранности конфигурации: импорт → экспорт.
 *
 * Запуск: npm run check:roundtrip -- <файл.json> [<файл.json> ...]
 * Без аргументов проверяются конфигурации проекта из configs/.
 */

import { readFileSync } from 'node:fs';
import { argv, exit } from 'node:process';

import { parseDocument } from '../src/lib/parse';
import { toJsonText, writeDocument } from '../src/lib/serialize';
import { collectExtraIssues, validateBenchmarks } from '../src/lib/validate';

function canonical(value: unknown): string {
  const sort = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(sort);
    if (item && typeof item === 'object') {
      const entries = Object.entries(item as Record<string, unknown>).sort(([a], [b]) =>
        a.localeCompare(b),
      );
      return Object.fromEntries(entries.map(([key, child]) => [key, sort(child)]));
    }
    return item;
  };
  return JSON.stringify(sort(value), null, 2);
}

const files = argv.slice(2);
if (files.length === 0) {
  console.error('Укажите хотя бы один файл конфигурации.');
  exit(2);
}

let failed = 0;
for (const file of files) {
  const text = readFileSync(file, 'utf8');
  const outcome = parseDocument(text);
  if (!outcome.document) {
    console.log(`✗ ${file}: не разобран`);
    for (const issue of outcome.issues) console.log(`    ${issue.path} ${issue.message}`);
    failed += 1;
    continue;
  }

  const exported = writeDocument(outcome.document);
  const before = canonical(JSON.parse(text));
  const after = canonical(exported);

  const issues = [
    ...outcome.issues,
    ...validateBenchmarks(outcome.document.benchmarks, { connectionIds: null, ruleBankIds: null }),
    ...collectExtraIssues(outcome.document.benchmarks),
  ];
  const errors = issues.filter((issue) => issue.level === 'error');

  if (before !== after) {
    failed += 1;
    console.log(`✗ ${file}: экспорт отличается от исходного файла`);
    const beforeLines = before.split('\n');
    const afterLines = after.split('\n');
    for (let i = 0; i < Math.max(beforeLines.length, afterLines.length); i += 1) {
      if (beforeLines[i] !== afterLines[i]) {
        console.log(`    строка ${i + 1}`);
        console.log(`      было:  ${beforeLines[i] ?? '(нет)'}`);
        console.log(`      стало: ${afterLines[i] ?? '(нет)'}`);
      }
    }
  } else {
    console.log(`✓ ${file}: импорт → экспорт без потерь`);
  }

  if (errors.length) {
    console.log(`  ошибок проверки: ${errors.length}`);
    for (const issue of errors.slice(0, 10)) {
      console.log(`    [${issue.check}] ${issue.path}: ${issue.message}`);
    }
  }
  const warnings = issues.filter((issue) => issue.level === 'warning');
  if (warnings.length) console.log(`  замечаний: ${warnings.length}`);
  if (toJsonText(exported).trim().length === 0) failed += 1;
}

exit(failed ? 1 : 0);
