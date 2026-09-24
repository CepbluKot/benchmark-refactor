import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const page = readFileSync(resolve(root, 'src/pages/StrategyEditorPage.tsx'), 'utf8');
const editorPath = resolve(root, 'src/components/StrategyBudgetEditor.tsx');

assert.equal(existsSync(editorPath), true, 'StrategyBudgetEditor must exist');
const editor = readFileSync(editorPath, 'utf8');

assert.match(page, /<StrategyBudgetEditor/);
assert.doesNotMatch(page, /Расширенные настройки бюджета|Advanced budget settings/);
assert.match(page, /baselineRows: config\.budget\.baseline_rows/);
assert.match(page, /candidateRows: config\.budget\.candidate_rows/);
assert.match(page, /perPhaseCandidates: config\.budget\.per_phase_candidates/);
assert.match(page, /winnersPerParent: config\.budget\.winners_per_parent/);
assert.match(page, /finalValidationCandidates: config\.budget\.final_validation_candidates/);
assert.match(page, /finalValidationIndexAlternatives: config\.budget\.final_validation_index_alternatives/);
assert.match(editor, /Данные для INSERT-теста/);
assert.match(editor, /Ограничения поиска/);
assert.match(editor, /rowsPerInsert/);
assert.match(editor, /insertRepetitions/);
assert.match(editor, /maxCandidates/);
assert.match(editor, /procedure === 'sequential'/);
assert.match(editor, /topN/);
assert.doesNotMatch(editor, /baselineRows|candidateRows|perPhaseCandidates|winnersPerParent|finalValidationCandidates|finalValidationIndexAlternatives/);

console.log('Strategy budget layout checks passed');
