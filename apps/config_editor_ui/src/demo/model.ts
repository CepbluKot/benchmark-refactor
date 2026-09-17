import type { BenchmarkConfig } from '../types/config';

export type SourceStatus = 'unchecked' | 'available' | 'unavailable';

export interface DataSource {
  id: string;
  dbms: 'clickhouse';
  credential_type: 'password';
  host: string;
  port: number;
  login: string;
  status: SourceStatus;
  checkedAt?: string;
}

export interface RuleBankSummary {
  id: string;
  description: string;
  columnRules: number;
  codecRules: number;
  indexRules: number;
  orderByRules: number;
  defaultFor: string[];
}

export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface DemoCandidate {
  id: string;
  title: string;
  stage: string;
  score?: number;
  selectReadBytesRatio?: number;
  compressionRatio?: number;
  insertTimeRatio?: number;
  ddl: string;
  change: string;
  status: 'baseline' | 'candidate' | 'error';
}

export interface DemoRun {
  id: string;
  benchmarkId: string;
  sourceId: string;
  table: string;
  strategy: string;
  status: RunStatus;
  stage: string;
  startedAt: string;
  finishedAt?: string;
  duration?: string;
  config: BenchmarkConfig;
  candidates: DemoCandidate[];
  diagnostic?: string;
}

export function sourceError(source: Pick<DataSource, 'id' | 'host' | 'port' | 'login'>, existing: Pick<DataSource, 'id'>[]): string {
  if (!source.id.trim()) return 'Укажите идентификатор подключения';
  if (existing.some((item) => item.id === source.id)) return 'Подключение с таким идентификатором уже существует';
  if (!source.host.trim()) return 'Укажите хост';
  if (!Number.isInteger(source.port) || source.port < 1 || source.port > 65535) return 'Порт должен быть целым числом от 1 до 65535';
  if (!source.login.trim()) return 'Укажите пользователя';
  return '';
}

function cloneBenchmark(benchmark: BenchmarkConfig): BenchmarkConfig {
  return JSON.parse(JSON.stringify(benchmark)) as BenchmarkConfig;
}

function tableLabel(benchmark: BenchmarkConfig): string {
  if (benchmark.tables === '*') return '*';
  if (Array.isArray(benchmark.tables)) return benchmark.tables[0] ?? '*';
  const first = Object.entries(benchmark.tables)[0];
  if (!first) return '*';
  const [database, tables] = first;
  return tables === '*' ? `${database}.*` : `${database}.${tables[0] ?? '*'}`;
}

export function createDemoRun(benchmark: BenchmarkConfig, id: string): DemoRun {
  return {
    id,
    benchmarkId: benchmark.id,
    sourceId: benchmark.connection_id,
    table: tableLabel(benchmark),
    strategy: benchmark.strategy,
    status: 'running',
    stage: 'source_baseline',
    startedAt: new Date().toISOString(),
    config: cloneBenchmark(benchmark),
    candidates: [],
  };
}

export function finishDemoRun(run: DemoRun): DemoRun {
  if (run.status === 'cancelled') return run;
  return {
    ...run,
    status: 'completed',
    stage: 'final_validation',
    finishedAt: new Date().toISOString(),
    duration: '12 мин 48 сек',
    candidates: DEMO_CANDIDATES,
  };
}

export const DEMO_CANDIDATES: DemoCandidate[] = [
  {
    id: 'baseline',
    title: 'Исходная структура',
    stage: 'source_baseline',
    score: 1,
    selectReadBytesRatio: 1,
    compressionRatio: 1,
    insertTimeRatio: 1,
    ddl: 'CREATE TABLE default.hits_postgres (...) ENGINE = MergeTree ORDER BY event_date',
    change: 'Контрольный вариант без изменений',
    status: 'baseline',
  },
  {
    id: 'orderby-country',
    title: 'ORDER BY event_date, country',
    stage: 'order_by',
    score: 1.29,
    selectReadBytesRatio: 1.42,
    compressionRatio: 1.11,
    insertTimeRatio: 0.96,
    ddl: 'CREATE TABLE benchmark_tmp.hits_postgres_candidate (...) ENGINE = MergeTree ORDER BY (event_date, country)',
    change: 'В ключ сортировки добавлена колонка country',
    status: 'candidate',
  },
  {
    id: 'page-url-index',
    title: 'Skip index для page_url',
    stage: 'indexes',
    score: 1.46,
    selectReadBytesRatio: 1.91,
    compressionRatio: 1.08,
    insertTimeRatio: 0.91,
    ddl: 'CREATE TABLE benchmark_tmp.hits_postgres_candidate (...) INDEX page_url_idx page_url TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 8',
    change: 'Добавлен ngrambf_v1 индекс для page_url, granularity 8',
    status: 'candidate',
  },
  {
    id: 'combined-final',
    title: 'Итоговая комбинация',
    stage: 'final_validation',
    score: 1.57,
    selectReadBytesRatio: 2.04,
    compressionRatio: 1.13,
    insertTimeRatio: 0.89,
    ddl: 'CREATE TABLE benchmark_tmp.hits_postgres_candidate (...) ENGINE = MergeTree ORDER BY (event_date, country) INDEX page_url_idx page_url TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 8 SETTINGS index_granularity = 8192',
    change: 'ORDER BY, skip index и index_granularity объединены для финальной проверки',
    status: 'candidate',
  },
];
