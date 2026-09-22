import { useMemo, useState } from 'react';
import { Badge, Button, SelectField } from '@adqm/gpb-ui';
import { ActionIcon } from '../components/ActionIcon';
import { MonitoringTable, type MonitoringTableColumn } from '../components/MonitoringTable';
import type { Benchmark } from '../control/api';
import { useWorkspace } from '../control/workspace';
import { useI18n } from '../i18n';

function strategyLabel(method: string, t: (ru: string, en: string) => string): string {
  return ({ sequential_phased_topn_strategy: t('Поэтапный подбор структуры', 'Phased structural search'), types_strategy: t('Подбор типов колонок', 'Column type search'), indexes_strategy: t('Подбор skip-индексов', 'Skip-index search'), sequential_topn_strategy: t('Подбор порядка сортировки', 'Sort-order search'), combined_strategy: t('Комбинированный подбор', 'Combined search') } as Record<string, string>)[method] ?? '—';
}

export function BenchmarksPage({ onCreate, onEdit }: { onCreate(): void; onEdit(id: string): void }): JSX.Element {
  const { locale, t } = useI18n();
  const { activeWorkspace, benchmarks, sources, strategies, runs, startRun } = useWorkspace();
  const [strategyFilter, setStrategyFilter] = useState('all');
  const workspaceBenchmarks = benchmarks.filter((benchmark) => benchmark.workspaceId === activeWorkspace?.id);
  const rows = useMemo(() => strategyFilter === 'all' ? workspaceBenchmarks : workspaceBenchmarks.filter((benchmark) => benchmark.strategyId === strategyFilter), [strategyFilter, workspaceBenchmarks]);
  const columns: MonitoringTableColumn<Benchmark>[] = [
    { key: 'name', label: t('Название', 'Name'), render: (benchmark) => <strong>{benchmark.name}</strong> },
    { key: 'table', label: t('Таблица', 'Table'), render: (benchmark) => <span className="mono">{benchmark.sourceTable}</span> },
    { key: 'source', label: t('Источник', 'Source'), render: (benchmark) => <span>{sources.find((source) => source.id === benchmark.sourceId)?.name ?? '—'}</span> },
    { key: 'strategy', label: t('Стратегия', 'Strategy'), render: (benchmark) => strategyLabel(strategies.find((strategy) => strategy.id === benchmark.strategyId)?.strategy ?? '', t) },
    { key: 'lastRun', label: t('Последний запуск', 'Last run'), render: (benchmark) => { const run = runs.find((item) => item.benchmarkId === benchmark.id); return run ? new Intl.DateTimeFormat(locale === 'ru' ? 'ru-RU' : 'en-US', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(run.startedAt)) : '—'; } },
    { key: 'state', label: t('Состояние', 'Status'), render: (benchmark) => <Badge tone={sources.find((source) => source.id === benchmark.sourceId)?.status === 'available' ? 'success' : 'neutral'}><span className="status-badge">{sources.find((source) => source.id === benchmark.sourceId)?.status === 'available' ? t('Готов', 'Ready') : t('Источник не проверен', 'Source unchecked')}</span></Badge> },
    { key: 'actions', label: '', render: (benchmark) => <div className="table-actions"><Button variant="secondary" aria-label={`${t('Настроить бенчмарк', 'Configure benchmark')}: ${benchmark.name}`} onClick={() => onEdit(benchmark.id)}><ActionIcon name="configure" />{t('Настроить', 'Configure')}</Button><Button variant="secondary" className="action-icon-primary" aria-label={`${t('Запустить бенчмарк', 'Start benchmark')}: ${benchmark.name}`} onClick={async () => { await startRun(benchmark.id); }}><ActionIcon name="start" />{t('Запустить', 'Start')}</Button></div> },
  ];
  return <div className="page-stack product-page"><div className="page-heading"><div><h1>{t('Бенчмарки', 'Benchmarks')}</h1><p>{t('Задания выбранного пространства', 'Tasks in the selected workspace')}: {activeWorkspace?.name ?? '—'}</p></div><Button variant="primary" onClick={onCreate} disabled={!activeWorkspace}>＋ {t('Создать бенчмарк', 'Create benchmark')}</Button></div><MonitoringTable rows={rows} columns={columns} rowKey={(benchmark) => benchmark.id} title="" description="" searchPlaceholder={t('Поиск по названию, таблице или источнику…', 'Search by name, table, or source…')} searchText={(benchmark) => `${benchmark.name} ${benchmark.sourceTable}`} filters={<SelectField label={t('Стратегия', 'Strategy')} value={strategyFilter} options={[{ value: 'all', label: t('Все стратегии', 'All strategies') }, ...strategies.map((strategy) => ({ value: strategy.id, label: strategy.name }))]} onChange={(event) => setStrategyFilter(event.target.value)} />} filtersActive={strategyFilter !== 'all'} onResetFilters={() => setStrategyFilter('all')} /></div>;
}
