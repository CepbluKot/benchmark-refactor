import type { DataSource, DemoRun, RuleBankSummary } from './model';
import { DEMO_CANDIDATES } from './model';
import { parseDocument } from '../lib/parse';
import { SAMPLE_BENCHMARKS_JSON } from '../lib/samples';

const parsed = parseDocument(SAMPLE_BENCHMARKS_JSON);
const sampleBenchmark = parsed.document?.benchmarks[0];

if (!sampleBenchmark) throw new Error('Демонстрационный BenchmarkConfig не разобран');

export const INITIAL_SOURCES: DataSource[] = [
  {
    id: 'local_ch_hits',
    dbms: 'clickhouse',
    credential_type: 'password',
    host: 'clickhouse.internal',
    port: 8123,
    login: 'bench_user',
    status: 'unchecked',
  },
];

export const INITIAL_RULE_BANKS: RuleBankSummary[] = [
  {
    id: 'clickhouse_universal_baseline',
    description: 'Универсальные безопасные варианты типов и кодеков ClickHouse из конфигурации проекта.',
    columnRules: 14,
    codecRules: 14,
    indexRules: 5,
    orderByRules: 1,
    defaultFor: ['clickhouse'],
  },
  {
    id: 'aggressive_zstd',
    description: 'Расширенный набор ZSTD-кодеков для отдельных экспериментов.',
    columnRules: 9,
    codecRules: 18,
    indexRules: 0,
    orderByRules: 0,
    defaultFor: [],
  },
];

export const INITIAL_RUNS: DemoRun[] = [
  {
    id: 'run-hits-20260916-1842',
    benchmarkId: sampleBenchmark.id,
    sourceId: sampleBenchmark.connection_id,
    table: 'default.hits_postgres',
    strategy: sampleBenchmark.strategy,
    status: 'completed',
    stage: 'final_validation',
    startedAt: '2026-09-16T15:42:00.000Z',
    finishedAt: '2026-09-16T15:54:48.000Z',
    duration: '12 мин 48 сек',
    config: JSON.parse(JSON.stringify(sampleBenchmark)),
    candidates: DEMO_CANDIDATES,
  },
  {
    id: 'run-hits-20260916-1710',
    benchmarkId: sampleBenchmark.id,
    sourceId: sampleBenchmark.connection_id,
    table: 'default.hits_postgres',
    strategy: sampleBenchmark.strategy,
    status: 'failed',
    stage: 'indexes',
    startedAt: '2026-09-16T14:10:00.000Z',
    finishedAt: '2026-09-16T14:14:31.000Z',
    duration: '4 мин 31 сек',
    config: JSON.parse(JSON.stringify(sampleBenchmark)),
    candidates: DEMO_CANDIDATES.slice(0, 2),
    diagnostic: 'Демонстрационная ошибка: временная таблица кандидата не ответила в пределах лимита этапа.',
  },
];
