import assert from 'node:assert/strict';
import { optionRequestKey } from '../src/strategies/options';

assert.equal(
  optionRequestKey({ kind: 'codec_alternative', locale: 'en', query: ' ZSTD ', matcherType: 'String', selected: ['ZSTD(3)', 'ZSTD(1)'] }),
  'codec_alternative|en|zstd|String|ZSTD(1),ZSTD(3)',
);
assert.equal(
  optionRequestKey({ kind: 'table_granularity', locale: 'ru', query: '', matcherType: '', selected: [] }),
  'table_granularity|ru|||',
);
console.log('Strategy options request-key checks passed');
