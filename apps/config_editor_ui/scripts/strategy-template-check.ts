import assert from 'node:assert/strict';
import { SCORING_PRESETS, createDefaultStrategyDraft, pruneStrategyDraft, validateStrategyStep } from '../src/strategies/model';
import { dimensionPhases, validateDimensions } from '../src/strategies/dimensions';

const draft = createDefaultStrategyDraft();
assert.equal(draft.procedure, 'phased');
assert.equal(draft.scoring.preset, 'balanced');
assert.equal(draft.scoring.formula, SCORING_PRESETS.balanced.formula);
assert.deepEqual(dimensionPhases(draft.dimensions, 'phased'), ['types', 'codecs', 'index_granularity', 'indexes', 'final_validation']);
assert.equal(validateDimensions({ ...draft.dimensions, column_types: [], codecs: [], skip_indexes: [], table_index_granularity_values: [] }), 'Настройте хотя бы одно направление оптимизации.');
assert.equal(validateStrategyStep({ ...draft, name: '' }, 0).name, 'Укажите название стратегии.');
assert.equal(validateStrategyStep({ ...draft, scoring: { ...draft.scoring, formula: '' } }, 3).formula, 'Введите формулу оценки.');

const payload = pruneStrategyDraft({ ...draft, name: '  Warehouse  ', description: '  Test  ' });
assert.equal(payload.name, 'Warehouse');
assert.equal(payload.config.schema_version, 2);
if (payload.config.schema_version !== 2) throw new Error('Expected v2 config');
assert.equal(payload.config.procedure, 'phased');
assert.equal(payload.config.scoring.formula, SCORING_PRESETS.balanced.formula);
assert.equal('method' in payload.config, false);
assert.equal('rules' in payload.config, false);
console.log('Strategy template model checks passed');
