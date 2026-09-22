import assert from 'node:assert/strict';
import { SUPPORTED_LOCALES, resolveLocale, translations } from '../src/i18n';

assert.deepEqual(SUPPORTED_LOCALES, ['ru', 'en']);
assert.equal(resolveLocale('en'), 'en');
assert.equal(resolveLocale('de'), 'ru');
assert.equal(translations.en.navigation.benchmarks, 'Benchmarks');
assert.equal(translations.ru.navigation.benchmarks, 'Бенчмарки');
assert.deepEqual(Object.keys(translations.ru).sort(), Object.keys(translations.en).sort());
console.log('Localization contract checks passed');
