import { createContext, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import { INITIAL_RULE_BANKS, INITIAL_RUNS, INITIAL_SOURCES } from './data';
import type { DataSource, DemoRun, RuleBankSummary } from './model';
import { createDemoRun, finishDemoRun } from './model';
import type { BenchmarkConfig } from '../types/config';

interface WorkspaceApi {
  sources: DataSource[];
  ruleBanks: RuleBankSummary[];
  runs: DemoRun[];
  saveSource(source: DataSource, previousId?: string): void;
  removeSource(id: string): void;
  checkSource(id: string): void;
  saveRuleBank(bank: RuleBankSummary, previousId?: string): void;
  removeRuleBank(id: string): void;
  startRun(benchmark: BenchmarkConfig): DemoRun;
  completeRun(id: string): void;
  cancelRun(id: string): void;
}

const WorkspaceContext = createContext<WorkspaceApi | null>(null);

export function useWorkspace(): WorkspaceApi {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error('useWorkspace вызван вне WorkspaceProvider');
  return value;
}

export function WorkspaceProvider({ children }: { children: ReactNode }): JSX.Element {
  const [sources, setSources] = useState(INITIAL_SOURCES);
  const [ruleBanks, setRuleBanks] = useState(INITIAL_RULE_BANKS);
  const [runs, setRuns] = useState(INITIAL_RUNS);

  const value = useMemo<WorkspaceApi>(() => ({
    sources,
    ruleBanks,
    runs,
    saveSource(source, previousId) {
      setSources((current) => previousId
        ? current.map((item) => item.id === previousId ? source : item)
        : [...current, source]);
    },
    removeSource(id) {
      setSources((current) => current.filter((item) => item.id !== id));
    },
    checkSource(id) {
      setSources((current) => current.map((item) => item.id === id
        ? { ...item, status: 'available', checkedAt: new Date().toISOString() }
        : item));
    },
    saveRuleBank(bank, previousId) {
      setRuleBanks((current) => previousId
        ? current.map((item) => item.id === previousId ? bank : item)
        : [...current, bank]);
    },
    removeRuleBank(id) {
      setRuleBanks((current) => current.filter((item) => item.id !== id));
    },
    startRun(benchmark) {
      const run = createDemoRun(benchmark, `run-${benchmark.id}-${Date.now()}`);
      setRuns((current) => [run, ...current]);
      return run;
    },
    completeRun(id) {
      setRuns((current) => current.map((run) => run.id === id ? finishDemoRun(run) : run));
    },
    cancelRun(id) {
      setRuns((current) => current.map((run) => run.id === id && run.status === 'running'
        ? { ...run, status: 'cancelled', finishedAt: new Date().toISOString(), stage: 'cancelled' }
        : run));
    },
  }), [ruleBanks, runs, sources]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
