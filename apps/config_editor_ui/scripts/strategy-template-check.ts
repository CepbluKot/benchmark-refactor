import assert from 'node:assert/strict';
import { createDefaultStrategyDraft, deriveStrategyPhases, pruneStrategyDraft, validateStrategyStep } from '../src/strategies/model';

assert.deepEqual(deriveStrategyPhases('types_strategy'), ['types', 'codecs']);
assert.deepEqual(deriveStrategyPhases('indexes_strategy'), ['indexes']);
assert.deepEqual(deriveStrategyPhases('combined_strategy'), ['types', 'codecs', 'indexes']);
assert.deepEqual(deriveStrategyPhases('sequential_topn_strategy'), ['types', 'codecs', 'top_n', 'indexes']);
assert.deepEqual(deriveStrategyPhases('sequential_phased_topn_strategy'), ['order_by', 'types', 'codecs', 'index_granularity', 'indexes', 'final_validation']);

const draft = createDefaultStrategyDraft();
draft.method = 'types_strategy';
draft.rules.skipIndexes = true;
draft.budget.finalValidationIndexAlternatives = 3;
const pruned = pruneStrategyDraft(draft);
assert.equal('skip_indexes' in pruned.config.rules, false);
assert.equal('final_validation_index_alternatives' in pruned.config.budget, false);
draft.budget.maxCandidates = 0;
assert.ok(validateStrategyStep(draft, 3).maxCandidates);
draft.budget.maxCandidates = 10;
draft.scoring.maxStorageGrowthPercent = Number.POSITIVE_INFINITY;
assert.ok(validateStrategyStep(draft, 4).maxStorageGrowthPercent);
console.log('Strategy template model checks passed');
