/**
 * DB Benchmark - Domain Types & API Contracts
 * Based on DB Benchmark Specification (React + FastAPI + PostgreSQL + ClickHouse)
 */

export interface Workspace {
  id: string;
  name: string;
  description?: string;
  createdAt: string;
}

export type DataSourceStatus = 'not_checked' | 'ready' | 'unavailable';

export interface DataSource {
  id: string;
  name: string;
  type: 'ClickHouse';
  host: string;
  port: number;
  login: string;
  secretRef: string;
  status: DataSourceStatus;
  lastCheckedAt?: string;
  availableDatabases: {
    database: string;
    tables: string[];
  }[];
}

export type StrategyTechnicalType =
  | 'sequential_phased_topn_strategy'
  | 'types_strategy'
  | 'indexes_strategy'
  | 'sequential_topn_strategy';

export interface StrategyTemplate {
  id: string;
  name: string; // Friendly name (e.g. «Поэтапный подбор структуры»)
  technicalType: StrategyTechnicalType; // Technical key
  phases: string[];
  description: string;
  isBuiltin?: boolean;
}

export type BenchmarkReadiness = 'ready' | 'source_not_verified' | 'incomplete';

export interface Benchmark {
  id: string;
  workspaceId: string;
  name: string;
  sourceId: string;
  sourceTable: string; // Format: database.table (e.g. "analytics.events_v2")
  sandboxDatabase: string; // e.g. "sandbox_benchmarks"
  strategyTemplateId: string;
  strategyName: string;
  readinessStatus: BenchmarkReadiness;
  createdAt: string;
  updatedAt: string;
  lastRunId?: string;
  lastRunStatus?: 'running' | 'completed' | 'error';
  lastRunDate?: string;
  // Future extension blocks (UI preview only, not connected to current backend API)
  rulesConfig?: {
    allowedTypes?: string[];
    allowedCodecs?: string[];
    allowedOrderBy?: string[];
    allowedSkipIndexes?: string[];
    indexGranularity?: number;
  };
  workloadConfig?: {
    queriesCount?: number;
    timeBudgetMinutes?: number;
    maxCandidates?: number;
    evaluationTarget?: 'query_speed' | 'disk_size' | 'balanced';
  };
}

export type RunStatus = 'running' | 'completed' | 'error';

export interface RunLogEntry {
  timestamp: string;
  level: 'INFO' | 'WARN' | 'ERROR';
  message: string;
  details?: string;
}

export interface Run {
  id: string;
  benchmarkId: string;
  benchmarkName: string;
  workspaceId: string;
  startedAt: string;
  finishedAt?: string;
  status: RunStatus;
  currentPhase: string;
  sourceRows: number;
  copyRows: number;
  progressPercent: number; // Conditional fixed progress indicator for running status (spec section 10)
  sandboxTableCreated: string;
  errorMessage?: string;
  logs: RunLogEntry[];
}

export type NavigationTab =
  | 'benchmarks'
  | 'runs'
  | 'data-sources'
  | 'strategies'
  | 'design-system'
  | 'benchmark-create'
  | 'benchmark-edit'
  | 'run-detail';
