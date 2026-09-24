import assert from 'node:assert/strict';
import { SCORING_PRESETS, createDefaultStrategyDraft, pruneStrategyDraft, validateStrategyStep } from '../src/strategies/model';
import { dimensionPhases, validateDimensions } from '../src/strategies/dimensions';

const draft = createDefaultStrategyDraft();
assert.equal(draft.procedure, 'combined');
assert.equal(draft.scoring.preset, 'balanced');
assert.equal(draft.scoring.formula, SCORING_PRESETS.balanced.formula);
assert.deepEqual(dimensionPhases(draft.dimensions, 'combined'), []);
assert.deepEqual(draft.dimensions.column_types, []);
assert.deepEqual(draft.dimensions.codecs, []);
assert.deepEqual(draft.dimensions.skip_indexes, []);
assert.deepEqual(draft.dimensions.table_index_granularity_values, []);
assert.equal(validateDimensions(draft.dimensions), undefined);
assert.deepEqual(dimensionPhases(draft.dimensions, 'combined'), []);
assert.deepEqual(dimensionPhases(draft.dimensions, 'sequential'), []);
assert.deepEqual(dimensionPhases(draft.dimensions, 'phased'), []);
assert.equal(
  validateDimensions({
    ...draft.dimensions,
    column_types: [{ by_type: 'String', alternatives: [] }],
  }),
  'Для каждого правила задайте исходный тип и хотя бы одну альтернативу.',
);
assert.equal(
  validateDimensions({
    ...draft.dimensions,
    skip_indexes: [{ by_type: 'String', indexes: [] }],
  }),
  'Для индекса задайте исходный тип, тип индекса и целую гранулярность больше нуля.',
);
assert.equal(validateStrategyStep({ ...draft, name: '' }, 0).name, 'Укажите название стратегии.');
assert.equal(validateStrategyStep({ ...draft, scoring: { ...draft.scoring, formula: '' } }, 3).formula, 'Введите формулу оценки.');

const payload = pruneStrategyDraft({ ...draft, name: '  Warehouse  ', description: '  Test  ' });
assert.equal(payload.name, 'Warehouse');
assert.equal(payload.config.schema_version, 2);
if (payload.config.schema_version !== 2) throw new Error('Expected v2 config');
assert.equal(payload.config.procedure, 'combined');
assert.equal(payload.config.scoring.formula, SCORING_PRESETS.balanced.formula);
assert.equal('method' in payload.config, false);
assert.equal('rules' in payload.config, false);

const legacyAdvancedPayload = pruneStrategyDraft({
  ...draft,
  budget: {
    ...draft.budget,
    advanced: true,
    baselineRows: 50_000,
    candidateRows: 40_000,
    perPhaseCandidates: 25,
    winnersPerParent: 5,
    finalValidationCandidates: 8,
    finalValidationIndexAlternatives: 2,
  },
});
assert.equal(legacyAdvancedPayload.config.budget.baseline_rows, 50_000);
assert.equal(legacyAdvancedPayload.config.budget.candidate_rows, 40_000);
assert.equal(legacyAdvancedPayload.config.budget.per_phase_candidates, 25);
assert.equal(legacyAdvancedPayload.config.budget.winners_per_parent, 5);
assert.equal(legacyAdvancedPayload.config.budget.final_validation_candidates, 8);
assert.equal(legacyAdvancedPayload.config.budget.final_validation_index_alternatives, 2);

const newPayload = pruneStrategyDraft({ ...draft, budget: { ...draft.budget, advanced: false } });
assert.equal('baseline_rows' in newPayload.config.budget, false);
assert.equal('candidate_rows' in newPayload.config.budget, false);
assert.equal('per_phase_candidates' in newPayload.config.budget, false);
assert.equal('winners_per_parent' in newPayload.config.budget, false);
assert.equal('final_validation_candidates' in newPayload.config.budget, false);
assert.equal('final_validation_index_alternatives' in newPayload.config.budget, false);
console.log('Strategy template model checks passed');
