import { useMemo, useState } from 'react';
import { Badge, Button, SelectField } from '@adqm/gpb-ui';
import { ActionIcon } from '../components/ActionIcon';
import { MonitoringTable, type MonitoringTableColumn } from '../components/MonitoringTable';
import type { Benchmark } from '../control/api';
import { useWorkspace } from '../control/workspace';

const STRATEGY_LABELS: Record<string, string> = { sequential_phased_topn_strategy: 'Поэтапный подбор структуры', types_strategy: 'Подбор типов колонок', indexes_strategy: 'Подбор skip-индексов', sequential_topn_strategy: 'Подбор порядка сортировки', combined_strategy: 'Комбинированный подбор' };

export function BenchmarksPage({ onCreate, onEdit }: { onCreate(): void; onEdit(id: string): void }): JSX.Element {
  const { activeWorkspace, benchmarks, sources, strategies, runs, startRun } = useWorkspace();
  const [strategyFilter, setStrategyFilter] = useState('all');
  const workspaceBenchmarks = benchmarks.filter((benchmark) => benchmark.workspaceId === activeWorkspace?.id);
  const rows = useMemo(() => strategyFilter === 'all' ? workspaceBenchmarks : workspaceBenchmarks.filter((benchmark) => benchmark.strategyId === strategyFilter), [strategyFilter, workspaceBenchmarks]);
  const columns: MonitoringTableColumn<Benchmark>[] = [
    { key: 'name', label: 'Название', render: (benchmark) => <strong>{benchmark.name}</strong> },
    { key: 'table', label: 'Таблица', render: (benchmark) => <span className="mono">{benchmark.sourceTable}</span> },
    { key: 'source', label: 'Источник', render: (benchmark) => <span>{sources.find((source) => source.id === benchmark.sourceId)?.name ?? '—'}</span> },
    { key: 'strategy', label: 'Стратегия', render: (benchmark) => STRATEGY_LABELS[strategies.find((strategy) => strategy.id === benchmark.strategyId)?.strategy ?? ''] ?? '—' },
    { key: 'lastRun', label: 'Последний запуск', render: (benchmark) => { const run = runs.find((item) => item.benchmarkId === benchmark.id); return run ? new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(run.startedAt)) : '—'; } },
    { key: 'state', label: 'Состояние', render: (benchmark) => <Badge tone={sources.find((source) => source.id === benchmark.sourceId)?.status === 'available' ? 'success' : 'neutral'}><span className="status-badge">{sources.find((source) => source.id === benchmark.sourceId)?.status === 'available' ? 'Готов' : 'Источник не проверен'}</span></Badge> },
    { key: 'actions', label: '', render: (benchmark) => <div className="table-actions"><Button variant="secondary" aria-label={`Настроить бенчмарк: ${benchmark.name}`} onClick={() => onEdit(benchmark.id)}><ActionIcon name="configure" />Настроить</Button><Button variant="secondary" className="action-icon-primary" aria-label={`Запустить бенчмарк: ${benchmark.name}`} onClick={async () => { await startRun(benchmark.id); }}><ActionIcon name="start" />Запустить</Button></div> },
  ];
  return <div className="page-stack product-page"><div className="page-heading"><div><h1>Бенчмарки</h1><p>Задания выбранного пространства: {activeWorkspace?.name ?? '—'}</p></div><Button variant="primary" onClick={onCreate} disabled={!activeWorkspace}>＋ Создать бенчмарк</Button></div><MonitoringTable rows={rows} columns={columns} rowKey={(benchmark) => benchmark.id} title="" description="" searchPlaceholder="Поиск по названию, таблице или источнику…" searchText={(benchmark) => `${benchmark.name} ${benchmark.sourceTable}`} filters={<SelectField label="Стратегия" value={strategyFilter} options={[{ value: 'all', label: 'Все стратегии' }, ...strategies.map((strategy) => ({ value: strategy.id, label: strategy.name }))]} onChange={(event) => setStrategyFilter(event.target.value)} />} filtersActive={strategyFilter !== 'all'} onResetFilters={() => setStrategyFilter('all')} /></div>;
}
