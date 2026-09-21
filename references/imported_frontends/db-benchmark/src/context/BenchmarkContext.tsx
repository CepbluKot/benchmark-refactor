import React, { createContext, useContext, useState, useEffect } from 'react';
import {
  Workspace,
  DataSource,
  StrategyTemplate,
  Benchmark,
  Run,
  NavigationTab,
} from '../types';
import {
  INITIAL_WORKSPACES,
  INITIAL_DATA_SOURCES,
  INITIAL_STRATEGY_TEMPLATES,
  INITIAL_BENCHMARKS,
  INITIAL_RUNS,
} from '../data/initialData';

interface BenchmarkContextType {
  // Navigation & View
  currentTab: NavigationTab;
  setCurrentTab: (tab: NavigationTab) => void;
  activeRunId: string | null;
  setActiveRunId: (id: string | null) => void;
  editingBenchmarkId: string | null;
  setEditingBenchmarkId: (id: string | null) => void;
  preselectedStrategyId: string | null;
  setPreselectedStrategyId: (id: string | null) => void;

  // Workspaces
  workspaces: Workspace[];
  activeWorkspaceId: string;
  setActiveWorkspaceId: (id: string) => void;
  createWorkspace: (name: string, description?: string) => Workspace;

  // Data Sources (Shared across all workspaces)
  dataSources: DataSource[];
  createDataSource: (data: Omit<DataSource, 'id' | 'status' | 'availableDatabases'>) => DataSource;
  checkDataSource: (id: string) => Promise<boolean>;
  getTablesForSource: (sourceId: string) => string[];

  // Strategies
  strategies: StrategyTemplate[];
  createStrategy: (data: Omit<StrategyTemplate, 'id'>) => StrategyTemplate;

  // Benchmarks (belonging to current workspace)
  benchmarks: Benchmark[];
  currentWorkspaceBenchmarks: Benchmark[];
  createBenchmark: (data: Omit<Benchmark, 'id' | 'createdAt' | 'updatedAt' | 'readinessStatus'>) => Benchmark;
  updateBenchmark: (id: string, data: Partial<Benchmark>) => void;
  getBenchmarkById: (id: string) => Benchmark | undefined;

  // Runs
  runs: Run[];
  currentWorkspaceRuns: Run[];
  triggerRun: (benchmarkId: string) => Promise<string>;
  getRunById: (id: string) => Run | undefined;

  // Theme
  isDark: boolean;
  toggleTheme: () => void;

  // Real-time backend connection status (FastAPI + WebSocket representation)
  wsConnected: boolean;
  lastEventCursor: number;
  reconnectWs: () => void;

  // Notification / Toast
  toastMessage: string | null;
  showToast: (msg: string) => void;
}

const BenchmarkContext = createContext<BenchmarkContextType | undefined>(undefined);

export const BenchmarkProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Navigation State
  const [currentTab, setCurrentTab] = useState<NavigationTab>(() =>
    window.location.pathname === '/design-system' ? 'design-system' : 'benchmarks'
  );
  const [activeRunId, setActiveRunId] = useState<string | null>('run-1083');
  const [editingBenchmarkId, setEditingBenchmarkId] = useState<string | null>(null);
  const [preselectedStrategyId, setPreselectedStrategyId] = useState<string | null>(null);

  // Entities State
  const [workspaces, setWorkspaces] = useState<Workspace[]>(INITIAL_WORKSPACES);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string>('ws-sales');
  const [dataSources, setDataSources] = useState<DataSource[]>(INITIAL_DATA_SOURCES);
  const [strategies, setStrategies] = useState<StrategyTemplate[]>(INITIAL_STRATEGY_TEMPLATES);
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>(INITIAL_BENCHMARKS);
  const [runs, setRuns] = useState<Run[]>(INITIAL_RUNS);

  // Connection & events
  const [wsConnected, setWsConnected] = useState<boolean>(true);
  const [lastEventCursor, setLastEventCursor] = useState<number>(1084);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Theme state
  const [isDark, setIsDark] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('db_bench_theme');
      if (saved) return saved === 'dark';
      return window.matchMedia('(prefers-color-scheme: dark)').matches;
    }
    return false;
  });

  useEffect(() => {
    const root = document.documentElement;
    if (isDark) {
      root.classList.add('dark');
      localStorage.setItem('db_bench_theme', 'dark');
    } else {
      root.classList.remove('dark');
      localStorage.setItem('db_bench_theme', 'light');
    }
  }, [isDark]);

  useEffect(() => {
    const path = currentTab === 'design-system' ? '/design-system' : '/';
    if (window.location.pathname !== path) window.history.replaceState(null, '', path);
  }, [currentTab]);

  const toggleTheme = () => {
    setIsDark((prev) => !prev);
  };

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => {
      setToastMessage((cur) => (cur === msg ? null : cur));
    }, 3500);
  };

  const reconnectWs = () => {
    setWsConnected(true);
    showToast('Соединение с сервером событий WebSocket восстановлено');
  };

  // Workspaces operations
  const createWorkspace = (name: string, description?: string): Workspace => {
    const newWs: Workspace = {
      id: `ws-${Date.now().toString(36)}`,
      name,
      description,
      createdAt: new Date().toISOString().replace('T', ' ').substring(0, 16),
    };
    setWorkspaces((prev) => [...prev, newWs]);
    setActiveWorkspaceId(newWs.id);
    showToast(`Пространство «${name}» успешно создано`);
    return newWs;
  };

  // Data Sources operations
  const createDataSource = (
    data: Omit<DataSource, 'id' | 'status' | 'availableDatabases'>
  ): DataSource => {
    const newSource: DataSource = {
      ...data,
      id: `src-${Date.now().toString(36)}`,
      status: 'not_checked',
      availableDatabases: [
        {
          database: 'default',
          tables: ['default.system_events', 'default.user_actions'],
        },
        {
          database: 'sandbox_benchmarks',
          tables: [],
        },
      ],
    };
    setDataSources((prev) => [newSource, ...prev]);
    showToast(`Источник данных «${data.name}» добавлен`);
    return newSource;
  };

  const checkDataSource = async (id: string): Promise<boolean> => {
    // Realistic simulation of backend check ClickHouse endpoint
    await new Promise((resolve) => setTimeout(resolve, 800));
    const target = dataSources.find((s) => s.id === id);
    if (!target) return false;

    const isSuccess = target.host.includes('internal') || target.host.includes('corp');
    const newStatus = isSuccess ? 'ready' : 'unavailable';
    const nowStr = new Date().toISOString().replace('T', ' ').substring(0, 19);

    setDataSources((prev) =>
      prev.map((s) => (s.id === id ? { ...s, status: newStatus, lastCheckedAt: nowStr } : s))
    );

    // Update readiness of benchmarks using this source
    setBenchmarks((prev) =>
      prev.map((b) => {
        if (b.sourceId === id) {
          return {
            ...b,
            readinessStatus: newStatus === 'ready' ? 'ready' : 'source_not_verified',
          };
        }
        return b;
      })
    );

    if (isSuccess) {
      showToast(`Проверка «${target.name}»: соединение успешно установлено`);
    } else {
      showToast(`Проверка «${target.name}»: сервер ClickHouse недоступен`);
    }
    return isSuccess;
  };

  const getTablesForSource = (sourceId: string): string[] => {
    const src = dataSources.find((s) => s.id === sourceId);
    if (!src) return [];
    return src.availableDatabases.flatMap((d) => d.tables);
  };

  // Strategies operations
  const createStrategy = (data: Omit<StrategyTemplate, 'id'>): StrategyTemplate => {
    const newStrat: StrategyTemplate = {
      ...data,
      id: `strat-${Date.now().toString(36)}`,
      isBuiltin: false,
    };
    setStrategies((prev) => [...prev, newStrat]);
    showToast(`Шаблон стратегии «${data.name}» создан`);
    return newStrat;
  };

  // Benchmarks operations
  const currentWorkspaceBenchmarks = benchmarks.filter(
    (b) => b.workspaceId === activeWorkspaceId
  );

  const createBenchmark = (
    data: Omit<Benchmark, 'id' | 'createdAt' | 'updatedAt' | 'readinessStatus'>
  ): Benchmark => {
    const source = dataSources.find((s) => s.id === data.sourceId);
    const readiness: Benchmark['readinessStatus'] =
      source?.status === 'ready' ? 'ready' : 'source_not_verified';

    const now = new Date().toISOString().replace('T', ' ').substring(0, 16);
    const newBench: Benchmark = {
      ...data,
      id: `bench-${Date.now().toString(36)}`,
      readinessStatus: readiness,
      createdAt: now,
      updatedAt: now,
    };

    setBenchmarks((prev) => [newBench, ...prev]);
    showToast(`Бенчмарк «${newBench.name}» успешно сохранён`);
    return newBench;
  };

  const updateBenchmark = (id: string, data: Partial<Benchmark>) => {
    const now = new Date().toISOString().replace('T', ' ').substring(0, 16);
    setBenchmarks((prev) =>
      prev.map((b) => (b.id === id ? { ...b, ...data, updatedAt: now } : b))
    );
    showToast('Настройки бенчмарка обновлены');
  };

  const getBenchmarkById = (id: string) => benchmarks.find((b) => b.id === id);

  // Runs operations
  const currentWorkspaceRuns = runs.filter((r) => r.workspaceId === activeWorkspaceId);

  const getRunById = (id: string) => runs.find((r) => r.id === id);

  const triggerRun = async (benchmarkId: string): Promise<string> => {
    const benchmark = benchmarks.find((b) => b.id === benchmarkId);
    if (!benchmark) throw new Error('Бенчмарк не найден');

    const runId = `run-${Math.floor(1000 + Math.random() * 9000)}`;
    const nowTime = new Date().toTimeString().split(' ')[0] + '.' + Math.floor(Math.random() * 900);
    const dateStr = new Date().toISOString().replace('T', ' ').substring(0, 19);

    const sourceNameParts = benchmark.sourceTable.split('.');
    const rawTableName = sourceNameParts[1] || 'table';
    const sandboxCandidateTable = `${benchmark.sandboxDatabase}.candidate_${rawTableName}_bench`;

    const newRun: Run = {
      id: runId,
      benchmarkId: benchmark.id,
      benchmarkName: benchmark.name,
      workspaceId: benchmark.workspaceId,
      startedAt: dateStr,
      status: 'running',
      currentPhase: 'Проверка подключения к источнику и прав sandbox',
      sourceRows: 0,
      copyRows: 0,
      progressPercent: 35, // Representative fixed indicator per section 10
      sandboxTableCreated: sandboxCandidateTable,
      logs: [
        {
          timestamp: nowTime,
          level: 'INFO',
          message: `Инициализирован запуск ${runId} для таблицы ${benchmark.sourceTable}`,
        },
        {
          timestamp: nowTime,
          level: 'INFO',
          message: `Проверка прав на тестовую базу ${benchmark.sandboxDatabase}... Права подтверждены`,
        },
      ],
    };

    setRuns((prev) => [newRun, ...prev]);
    setBenchmarks((prev) =>
      prev.map((b) =>
        b.id === benchmarkId
          ? {
              ...b,
              lastRunId: runId,
              lastRunStatus: 'running',
              lastRunDate: dateStr.substring(0, 16),
            }
          : b
      )
    );
    setLastEventCursor((c) => c + 1);
    showToast(`Запуск ${runId} начат`);

    // Simulated background step execution reflecting ClickHouse copy + row count logic
    setTimeout(() => {
      const time2 = new Date().toTimeString().split(' ')[0] + '.140';
      const estimatedSourceRows = 940000 + Math.floor(Math.random() * 350000);
      setRuns((prev) =>
        prev.map((r) =>
          r.id === runId
            ? {
                ...r,
                currentPhase: 'Подсчёт строк в источнике и создание копии в sandbox',
                sourceRows: estimatedSourceRows,
                logs: [
                  ...r.logs,
                  {
                    timestamp: time2,
                    level: 'INFO',
                    message: `Получена структура ${benchmark.sourceTable}. Подсчитано строк: ${estimatedSourceRows.toLocaleString()}`,
                  },
                  {
                    timestamp: time2,
                    level: 'INFO',
                    message: `Создание таблицы-кандидата: CREATE TABLE ${sandboxCandidateTable} AS ${benchmark.sourceTable} ENGINE = MergeTree`,
                  },
                ],
              }
            : r
        )
      );
      setLastEventCursor((c) => c + 1);
    }, 1800);

    setTimeout(() => {
      const time3 = new Date().toTimeString().split(' ')[0] + '.520';
      setRuns((prev) =>
        prev.map((r) =>
          r.id === runId
            ? {
                ...r,
                currentPhase: 'Перенос данных и подсчёт строк копии',
                copyRows: r.sourceRows,
                progressPercent: 70,
                logs: [
                  ...r.logs,
                  {
                    timestamp: time3,
                    level: 'INFO',
                    message: `Выполнен перенос строк в ${sandboxCandidateTable} через INSERT SELECT`,
                  },
                  {
                    timestamp: time3,
                    level: 'INFO',
                    message: `Подсчёт строк в созданной копии: ${r.sourceRows.toLocaleString()}`,
                  },
                ],
              }
            : r
        )
      );
      setLastEventCursor((c) => c + 1);
    }, 3800);

    setTimeout(() => {
      const finishDateStr = new Date().toISOString().replace('T', ' ').substring(0, 19);
      const time4 = new Date().toTimeString().split(' ')[0] + '.890';
      setRuns((prev) =>
        prev.map((r) =>
          r.id === runId
            ? {
                ...r,
                status: 'completed',
                currentPhase: 'Завершён',
                finishedAt: finishDateStr,
                progressPercent: 100,
                logs: [
                  ...r.logs,
                  {
                    timestamp: time4,
                    level: 'INFO',
                    message: `Запуск успешно завершён. Копия таблицы сохранена в ${sandboxCandidateTable}.`,
                  },
                ],
              }
            : r
        )
      );
      setBenchmarks((prev) =>
        prev.map((b) =>
          b.id === benchmarkId
            ? {
                ...b,
                lastRunStatus: 'completed',
              }
            : b
        )
      );
      setLastEventCursor((c) => c + 1);
      showToast(`Запуск ${runId} завершён`);
    }, 6000);

    return runId;
  };

  return (
    <BenchmarkContext.Provider
      value={{
        currentTab,
        setCurrentTab,
        activeRunId,
        setActiveRunId,
        editingBenchmarkId,
        setEditingBenchmarkId,
        preselectedStrategyId,
        setPreselectedStrategyId,

        workspaces,
        activeWorkspaceId,
        setActiveWorkspaceId,
        createWorkspace,

        dataSources,
        createDataSource,
        checkDataSource,
        getTablesForSource,

        strategies,
        createStrategy,

        benchmarks,
        currentWorkspaceBenchmarks,
        createBenchmark,
        updateBenchmark,
        getBenchmarkById,

        runs,
        currentWorkspaceRuns,
        triggerRun,
        getRunById,

        isDark,
        toggleTheme,

        wsConnected,
        lastEventCursor,
        reconnectWs,

        toastMessage,
        showToast,
      }}
    >
      {children}
    </BenchmarkContext.Provider>
  );
};

export const useBenchmark = (): BenchmarkContextType => {
  const context = useContext(BenchmarkContext);
  if (!context) {
    throw new Error('useBenchmark must be used within a BenchmarkProvider');
  }
  return context;
};
