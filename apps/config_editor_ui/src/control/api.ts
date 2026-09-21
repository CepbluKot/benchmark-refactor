export interface Workspace { id: string; name: string; icon: string }
export interface Source { id: string; name: string; host: string; port: number; login: string; status: 'unchecked' | 'available' | 'unavailable'; checkedAt?: string }
import type { StrategyTemplateConfig } from '../strategies/model';
export interface Strategy { id: string; name: string; description: string; strategy: string; phases: string[]; config: StrategyTemplateConfig }
export interface StrategyInput { name: string; description: string; config: StrategyTemplateConfig }
export interface Benchmark { id: string; workspaceId: string; name: string; sourceId: string; sourceTable: string; sandboxDatabase: string; strategyId: string; strategySnapshot: StrategyTemplateConfig }
export interface Run { id: string; benchmarkId: string; status: 'running' | 'completed' | 'failed'; stage: string; sourceRows?: number; candidateRows?: number; startedAt: string; finishedAt?: string; failureReason?: string }
export interface Bootstrap { event_watermark: number; workspaces: Workspace[]; sources: Source[]; strategies: Strategy[]; benchmarks: Benchmark[]; runs: Run[] }
export interface EventEnvelope { event_id: number; event_type: string; payload: Record<string, unknown> }


function baseUrl(): string {
  const configured = window.__DDL_BENCH_CONFIG__?.apiBaseUrl;
  if (!configured) throw new Error('Адрес Control API не задан для этого контура');
  return configured.replace(/\/$/, '');
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl()}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) } });
  if (!response.ok) throw new Error(`Control API вернул ${response.status}`);
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

export function loadBootstrap(): Promise<Bootstrap> { return request<Bootstrap>('/api/v1/bootstrap'); }
export function command(path: string, body: unknown, method = 'POST'): Promise<void> { return request(path, { method, body: JSON.stringify(body) }).then(() => undefined); }
export function loadTables(sourceId: string): Promise<string[]> { return request<{ tables: string[] }>(`/api/v1/sources/${encodeURIComponent(sourceId)}/tables`).then(({ tables }) => tables); }
export function eventSocket(after: number): WebSocket {
  const url = new URL(baseUrl());
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = `${url.pathname.replace(/\/$/, '')}/api/v1/events`;
  url.searchParams.set('after', String(after));
  return new WebSocket(url.toString());
}
