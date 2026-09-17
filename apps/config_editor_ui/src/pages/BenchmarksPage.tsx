import { useMemo, useState } from 'react';
import { Badge, Button, SelectField, Status } from '@adqm/gpb-ui';

import { BenchmarkEditor } from '../components/BenchmarkEditor';
import { MonitoringTable, type MonitoringTableColumn } from '../components/MonitoringTable';
import { useWorkspace } from '../demo/workspace';
import { useEditor } from '../state/editor';
import type { TablesSelector } from '../types/config';

function tablesLabel(tables: TablesSelector): string {
  if (tables === '*') return 'Все таблицы';
  if (Array.isArray(tables)) return tables.join(', ') || 'Не выбраны';
  return Object.entries(tables).map(([database, names]) => names === '*' ? `${database}.*` : names.map((name) => `${database}.${name}`).join(', ')).join(', ');
}

export function BenchmarksPage({ editing, onEditingChange, onOpenRun }: { editing: boolean; onEditingChange(value: boolean): void; onOpenRun(id: string): void }): JSX.Element {
  const editor = useEditor();
  const { startRun } = useWorkspace();
  const [strategyFilter, setStrategyFilter] = useState('all');
  const rows = useMemo(() => strategyFilter === 'all' ? editor.benchmarks : editor.benchmarks.filter((benchmark) => benchmark.strategy === strategyFilter), [editor.benchmarks, strategyFilter]);
  const strategies = useMemo(() => [...new Set(editor.benchmarks.map((benchmark) => benchmark.strategy))], [editor.benchmarks]);
  const columns = useMemo<MonitoringTableColumn<(typeof editor.benchmarks)[number]>[]>(() => [
    { key: 'id', label: 'Бенчмарк', render: (benchmark) => <><strong className="mono">{benchmark.id}</strong>{editor.isBenchmarkDirty(benchmark) ? <small className="cell-note accent-text">изменён</small> : null}</> },
    { key: 'source', label: 'Источник', render: (benchmark) => <span className="mono">{benchmark.connection_id || 'не задан'}</span> },
    { key: 'tables', label: 'Таблицы', render: (benchmark) => tablesLabel(benchmark.tables) },
    { key: 'strategy', label: 'Стратегия', render: (benchmark) => <Badge tone="info">{benchmark.strategy}</Badge> },
    { key: 'validation', label: 'Проверка', render: (benchmark) => { const errors = editor.issues.filter((issue) => issue.benchmarkId === benchmark.id && issue.level === 'error').length; return errors ? <Status status="danger" label={`${errors} ошибок`} /> : <Status status="success" label="Готов" />; } },
    { key: 'actions', label: '', className: 'monitor-actions-cell', render: (benchmark) => { const errors = editor.issues.filter((issue) => issue.benchmarkId === benchmark.id && issue.level === 'error').length; const index = editor.benchmarks.indexOf(benchmark); return <div className="table-actions"><Button variant="secondary" onClick={() => { editor.selectBenchmark(index); onEditingChange(true); }}>Настроить</Button><Button variant="primary" disabled={Boolean(errors)} onClick={() => { const run = startRun(benchmark); onOpenRun(run.id); }}>Демо-запуск</Button></div>; } },
  ], [editor, onEditingChange, onOpenRun, startRun]);
  if (editing) return <BenchmarkEditor onBack={() => onEditingChange(false)} />;

  return <div className="page-stack">
    <div className="page-heading"><div><span className="eyebrow">Эксперименты</span><h1>Бенчмарки</h1><p>Сохранённые настройки поиска физической структуры таблиц.</p></div><div className="heading-actions"><Button variant="secondary" onClick={editor.loadSample}>Загрузить пример</Button><Button variant="primary" onClick={() => { editor.addBenchmark(); onEditingChange(true); }}>Создать бенчмарк</Button></div></div>
    <div className="summary-strip"><div><span>Конфигураций</span><strong>{editor.benchmarks.length}</strong></div><div><span>Ошибок проверки</span><strong>{editor.issues.filter((issue) => issue.level === 'error').length}</strong></div><div><span>Файл</span><strong className="mono compact-value">{editor.fileName ?? 'не открыт'}</strong></div></div>
    <MonitoringTable rows={rows} columns={columns} rowKey={(benchmark) => benchmark.id} title="Конфигурации" description="Один бенчмарк можно запускать многократно; каждый запуск хранит снимок настроек." searchPlaceholder="ID, источник или таблица…" searchText={(benchmark) => `${benchmark.id} ${benchmark.connection_id} ${tablesLabel(benchmark.tables)} ${benchmark.strategy}`} filters={<SelectField label="Стратегия" value={strategyFilter} options={[{ value: 'all', label: 'Все стратегии' }, ...strategies.map((value) => ({ value, label: value }))]} onChange={(event) => setStrategyFilter(event.target.value)} />} filtersActive={strategyFilter !== 'all'} onResetFilters={() => setStrategyFilter('all')} headerAction={<Badge tone="neutral">Текущий формат BenchmarkConfig</Badge>} />
  </div>;
}
