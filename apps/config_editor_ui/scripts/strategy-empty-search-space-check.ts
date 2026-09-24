import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const page = readFileSync(
  resolve(process.cwd(), 'src/pages/StrategyEditorPage.tsx'),
  'utf8',
);

assert.match(page, /hasSearchDimensions/);
assert.match(page, /Направления поиска не настроены/);
assert.match(page, /Стратегию можно сохранить, но при запуске новые варианты создаваться не будут\./);
assert.match(page, /No search dimensions configured/);
assert.match(page, /no candidate variants will be created when it runs\./);
assert.match(page, /tone="warning"/);
assert.doesNotMatch(page, /Настройте хотя бы одно направление оптимизации/);
assert.doesNotMatch(page, /Configure at least one optimization dimension/);

console.log('Empty strategy search-space UI checks passed');
