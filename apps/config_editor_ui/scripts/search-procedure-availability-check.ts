import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const editor = readFileSync(resolve(root, 'src/pages/StrategyEditorPage.tsx'), 'utf8');
const ruleBanks = readFileSync(resolve(root, 'src/pages/RuleBanksPage.tsx'), 'utf8');
const gallery = readFileSync(resolve(root, 'src/components/ProductPatternsGallery.tsx'), 'utf8');
const backlog = resolve(root, '..', '..', 'docs/backlog/phased-top-n-reintegration.md');

assert.equal(editor.includes("{ value: 'phased', title:"), false, 'Phased Top-N must not be selectable in the strategy editor');
assert.equal(editor.includes('Итоговая последовательность'), false, 'The effective-sequence panel must not be rendered');
assert.equal(editor.includes("draft.procedure === 'phased'"), true, 'A saved hidden procedure must require an explicit replacement before saving');
assert.equal(ruleBanks.includes("value: 'sequential_phased_topn_strategy'"), false, 'Phased Top-N must not appear as a strategy filter');
assert.equal(gallery.includes("t('Поэтапный Top-N'"), false, 'The product gallery must not advertise Phased Top-N');
assert.equal(existsSync(backlog), true, 'The deferred Phased Top-N work must be recorded in the backlog');

console.log('Search procedure availability checks passed');
