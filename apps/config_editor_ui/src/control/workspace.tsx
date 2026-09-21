import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { command, eventSocket, loadBootstrap, loadTables } from '../control/api';
import type { Benchmark, Run, Source, Strategy, StrategyInput, Workspace } from '../control/api';

interface WorkspaceApi {
  ready: boolean;
  error: string | null;
  lastSocketEventAt: string | null;
  workspaces: Workspace[];
  activeWorkspaceId: string;
  activeWorkspace: Workspace | undefined;
  sources: Source[];
  strategies: Strategy[];
  benchmarks: Benchmark[];
  runs: Run[];
  sourceTables(sourceId: string): Promise<string[]>;
  selectWorkspace(id: string): void;
  createWorkspace(name: string, icon: string): Promise<void>;
  createSource(input: Omit<Source, 'id' | 'status' | 'checkedAt'> & { secretRef: string }): Promise<void>;
  updateSource(id: string, input: Omit<Source, 'id' | 'status' | 'checkedAt'> & { secretRef: string }): Promise<void>;
  deleteSource(id: string): Promise<void>;
  checkSource(id: string): Promise<void>;
  createStrategy(input: StrategyInput): Promise<void>;
  updateStrategy(id: string, input: StrategyInput): Promise<void>;
  deleteStrategy(id: string): Promise<void>;
  createBenchmark(input: Omit<Benchmark, 'id' | 'strategySnapshot'>): Promise<void>;
  updateBenchmark(id: string, input: Omit<Benchmark, 'id' | 'strategySnapshot'>): Promise<void>;
  startRun(benchmarkId: string): Promise<void>;
}

const WorkspaceContext = createContext<WorkspaceApi | null>(null);
export function useWorkspace(): WorkspaceApi { const value = useContext(WorkspaceContext); if (!value) throw new Error('useWorkspace вызван вне WorkspaceProvider'); return value; }

export function WorkspaceProvider({ children }: { children: ReactNode }): JSX.Element {
  const [snapshot, setSnapshot] = useState<{ watermark: number; workspaces: Workspace[]; sources: Source[]; strategies: Strategy[]; benchmarks: Benchmark[]; runs: Run[] }>({ watermark: 0, workspaces: [], sources: [], strategies: [], benchmarks: [], runs: [] });
  const [activeWorkspaceId, setActiveWorkspaceId] = useState('');
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastSocketEventAt, setLastSocketEventAt] = useState<string | null>(null);
  const watermark = useRef(0);

  useEffect(() => {
    let socket: WebSocket | undefined;
    let cancelled = false;
    const apply = (event: { event_id: number; event_type: string; payload: Record<string, unknown> }) => {
      if (event.event_id <= watermark.current) return;
      watermark.current = event.event_id;
      setLastSocketEventAt(new Date().toISOString());
      const item = event.payload;
      setSnapshot((current) => {
        const next = { ...current, watermark: event.event_id };
        if (event.event_type === 'workspace.created') next.workspaces = [...current.workspaces, item as unknown as Workspace];
        if (event.event_type === 'source.created') next.sources = [...current.sources, item as unknown as Source];
        if (event.event_type === 'source.updated') next.sources = current.sources.map((source) => source.id === item.id ? item as unknown as Source : source);
        if (event.event_type === 'source.checked') next.sources = current.sources.map((source) => source.id === item.id ? { ...source, ...item } as Source : source);
        if (event.event_type === 'source.deleted') next.sources = current.sources.filter((source) => source.id !== item.id);
        if (event.event_type === 'strategy.created') next.strategies = [...current.strategies, item as unknown as Strategy];
        if (event.event_type === 'strategy.updated') next.strategies = current.strategies.map(strategy => strategy.id === item.id ? item as unknown as Strategy : strategy);
        if (event.event_type === 'strategy.deleted') next.strategies = current.strategies.filter(strategy => strategy.id !== item.id);
        if (event.event_type === 'benchmark.created') next.benchmarks = [...current.benchmarks, item as unknown as Benchmark];
        if (event.event_type === 'benchmark.updated') next.benchmarks = current.benchmarks.map((benchmark) => benchmark.id === item.id ? item as unknown as Benchmark : benchmark);
        if (event.event_type === 'run.started') next.runs = [item as unknown as Run, ...current.runs];
        if (event.event_type === 'run.completed' || event.event_type === 'run.failed') next.runs = current.runs.map((run) => run.id === item.id ? { ...run, ...item } as Run : run);
        return next;
      });
    };
    const connect = async () => {
      try {
        const initial = await loadBootstrap();
        if (cancelled) return;
        watermark.current = initial.event_watermark;
        setSnapshot({ watermark: initial.event_watermark, workspaces: initial.workspaces, sources: initial.sources, strategies: initial.strategies, benchmarks: initial.benchmarks, runs: initial.runs });
        setActiveWorkspaceId((current) => current || initial.workspaces[0]?.id || '');
        setReady(true); setError(null);
        socket = eventSocket(initial.event_watermark);
        socket.onmessage = (message) => apply(JSON.parse(message.data) as { event_id: number; event_type: string; payload: Record<string, unknown> });
        socket.onclose = () => { if (!cancelled) setError('Поток обновлений отключён. Перезагрузите страницу для восстановления.'); };
      } catch (reason) { if (!cancelled) setError(reason instanceof Error ? reason.message : 'Не удалось подключиться к Control API'); }
    };
    void connect();
    return () => { cancelled = true; socket?.close(); };
  }, []);

  const value = useMemo<WorkspaceApi>(() => ({
    ready, error, lastSocketEventAt, workspaces: snapshot.workspaces, activeWorkspaceId, activeWorkspace: snapshot.workspaces.find((workspace) => workspace.id === activeWorkspaceId), sources: snapshot.sources, strategies: snapshot.strategies, benchmarks: snapshot.benchmarks, runs: snapshot.runs,
    sourceTables: loadTables,
    selectWorkspace: setActiveWorkspaceId,
    createWorkspace: (name, icon) => command('/api/v1/workspaces', { name, icon }),
    createSource: ({ name, host, port, login, secretRef }) => command('/api/v1/sources', { name, host, port, login, secret_ref: secretRef }),
    updateSource: (id, { name, host, port, login, secretRef }) => command(`/api/v1/sources/${encodeURIComponent(id)}`, { name, host, port, login, secret_ref: secretRef }, 'PUT'),
    deleteSource: (id) => command(`/api/v1/sources/${encodeURIComponent(id)}`, {}, 'DELETE'),
    checkSource: (id) => command(`/api/v1/sources/${encodeURIComponent(id)}/check`, {}),
    createStrategy: (input) => command('/api/v1/strategies', input),
    updateStrategy: (id, input) => command(`/api/v1/strategies/${encodeURIComponent(id)}`, input, 'PUT'),
    deleteStrategy: (id) => command(`/api/v1/strategies/${encodeURIComponent(id)}`, {}, 'DELETE'),
    createBenchmark: (input) => command('/api/v1/benchmarks', { workspace_id: input.workspaceId, name: input.name, source_id: input.sourceId, source_table: input.sourceTable, sandbox_database: input.sandboxDatabase, strategy_id: input.strategyId }),
    updateBenchmark: (id, input) => command(`/api/v1/benchmarks/${encodeURIComponent(id)}`, { workspace_id: input.workspaceId, name: input.name, source_id: input.sourceId, source_table: input.sourceTable, sandbox_database: input.sandboxDatabase, strategy_id: input.strategyId }, 'PUT'),
    startRun: (benchmarkId) => command('/api/v1/runs', { benchmark_id: benchmarkId, idempotency_key: crypto.randomUUID() }),
  }), [activeWorkspaceId, error, lastSocketEventAt, ready, snapshot]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
