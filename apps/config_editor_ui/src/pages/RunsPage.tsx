import { useMemo, useState } from 'react';
import { Alert, Badge, Button, Chart, MetricCard, ProgressBar, SelectField, Status, Tabs } from '@adqm/gpb-ui';

import { MonitoringTable, type MonitoringTableColumn } from '../components/MonitoringTable';
import type { DemoCandidate, DemoRun, RunStatus } from '../demo/model';
import { useWorkspace } from '../demo/workspace';

function runStatus(status: RunStatus): JSX.Element {
  const labels: Record<RunStatus, string> = { queued: 'В очереди', running: 'Выполняется', completed: 'Завершён', failed: 'Ошибка', cancelled: 'Отменён' };
  const tones: Record<RunStatus, 'neutral' | 'warning' | 'success' | 'danger'> = { queued: 'neutral', running: 'warning', completed: 'success', failed: 'danger', cancelled: 'neutral' };
  return <Status status={tones[status]} label={labels[status]} />;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', { timeZone: 'Europe/Moscow', dateStyle: 'short', timeStyle: 'short' }).format(new Date(value));
}

function CandidatesTable({ run, onSelect }: { run: DemoRun; onSelect(candidate: DemoCandidate): void }): JSX.Element {
  const [stageFilter, setStageFilter] = useState('all');
  const stages = useMemo(() => [...new Set(run.candidates.map((candidate) => candidate.stage))], [run.candidates]);
  const rows = useMemo(() => stageFilter === 'all' ? run.candidates : run.candidates.filter((candidate) => candidate.stage === stageFilter), [run.candidates, stageFilter]);
  const columns = useMemo<MonitoringTableColumn<DemoCandidate>[]>(() => [
    { key: 'candidate', label: 'Кандидат', render: (candidate) => <><strong>{candidate.title}</strong><small className="cell-note">{candidate.change}</small></> },
    { key: 'stage', label: 'Этап', render: (candidate) => <Badge tone={candidate.status === 'baseline' ? 'neutral' : 'info'}>{candidate.stage}</Badge> },
    { key: 'score', label: 'Оценка', className: 'num-value', render: (candidate) => candidate.score?.toFixed(2) ?? '—' },
    { key: 'select', label: 'SELECT bytes', render: (candidate) => `${candidate.selectReadBytesRatio?.toFixed(2) ?? '—'}×` },
    { key: 'compression', label: 'Сжатие', render: (candidate) => `${candidate.compressionRatio?.toFixed(2) ?? '—'}×` },
    { key: 'insert', label: 'INSERT', render: (candidate) => `${candidate.insertTimeRatio?.toFixed(2) ?? '—'}×` },
    { key: 'actions', label: '', className: 'monitor-actions-cell', render: (candidate) => <Button variant="secondary" onClick={() => onSelect(candidate)}>Открыть</Button> },
  ], [onSelect]);
  return <MonitoringTable rows={rows} columns={columns} rowKey={(candidate) => candidate.id} title="Проверенные варианты" description="Параметры и отношения метрик относительно baseline." searchPlaceholder="Название, изменение или этап…" searchText={(candidate) => `${candidate.title} ${candidate.change} ${candidate.stage}`} filters={<SelectField label="Этап" value={stageFilter} options={[{ value: 'all', label: 'Все этапы' }, ...stages.map((value) => ({ value, label: value }))]} onChange={(event) => setStageFilter(event.target.value)} />} filtersActive={stageFilter !== 'all'} onResetFilters={() => setStageFilter('all')} />;
}

function RunDetail({ run, onBack }: { run: DemoRun; onBack(): void }): JSX.Element {
  const { completeRun, cancelRun } = useWorkspace();
  const [tab, setTab] = useState('overview');
  const [selectedCandidate, setSelectedCandidate] = useState<DemoCandidate | null>(null);
  const best = useMemo(() => [...run.candidates].filter((candidate) => candidate.status !== 'baseline' && candidate.score !== undefined).sort((left, right) => (right.score ?? 0) - (left.score ?? 0))[0], [run.candidates]);
  const progress = run.status === 'running' ? 18 : run.status === 'completed' ? 100 : 62;

  return <div className="page-stack">
    <div className="detail-toolbar"><Button variant="tertiary" onClick={onBack}>← Все запуски</Button><div className="toolbar-spacer" />{run.status === 'running' ? <><Button variant="danger" onClick={() => cancelRun(run.id)}>Отменить</Button><Button variant="primary" onClick={() => completeRun(run.id)}>Завершить демо-запуск</Button></> : null}</div>
    <div className="page-heading"><div><span className="eyebrow">{run.benchmarkId}</span><h1 className="mono">{run.id}</h1><p>{run.table} · {run.strategy}</p></div><div className="run-heading-status">{runStatus(run.status)}<Badge tone="warning">Симуляция</Badge></div></div>
    <ProgressBar label={`Этап: ${run.stage}`} value={progress} tone={run.status === 'failed' ? 'danger' : run.status === 'completed' ? 'success' : 'info'} />
    <Tabs label="Разделы запуска" value={tab} onValueChange={setTab} items={[{ value: 'overview', label: 'Обзор' }, { value: 'candidates', label: `Кандидаты (${run.candidates.length})` }, { value: 'comparison', label: 'Сравнение' }, { value: 'queries', label: 'Запросы' }, { value: 'diagnostics', label: 'Диагностика' }, { value: 'config', label: 'Конфигурация' }]} />
    {tab === 'overview' ? <div className="tab-stack"><div className="metrics-grid"><MetricCard label="Кандидатов измерено" value={run.candidates.length} detail="включая baseline" /><MetricCard label="Лучшая оценка" value={best?.score?.toFixed(2) ?? '—'} detail={best?.title ?? 'запуск не завершён'} /><MetricCard label="Длительность" value={run.duration ?? 'выполняется'} detail={`начат ${formatDate(run.startedAt)}`} /><MetricCard label="Текущий этап" value={run.stage} detail="стадия стратегии" /></div>{best ? <Alert tone="success" title="Лучший вариант в демонстрационных измерениях">{best.title}: {best.change}. Это результат симуляции интерфейса, а не рекомендация движка.</Alert> : <Alert tone="info" title="Результатов пока нет">Завершите демо-запуск, чтобы наполнить экран кандидатами и сравнением.</Alert>}<section className="surface-panel"><div className="panel-heading"><div><h2>Этапы</h2><p>Последовательность `sequential_phased_topn_strategy`.</p></div></div><div className="run-stages">{['source_baseline', 'order_by', 'types', 'codecs', 'index_granularity', 'indexes', 'final_validation'].map((stage, index) => <div className={`run-stage${stage === run.stage ? ' active' : ''}${run.status === 'completed' ? ' complete' : ''}`} key={stage}><span>{index + 1}</span><strong>{stage}</strong></div>)}</div></section></div> : null}
    {tab === 'candidates' ? run.candidates.length ? <CandidatesTable run={run} onSelect={setSelectedCandidate} /> : <div className="empty-inline">Кандидаты появятся после измерений.</div> : null}
    {tab === 'comparison' ? <div className="tab-stack">{run.candidates.length ? <><div className="chart-grid"><Chart title="Оценка кандидатов" kind="bar" data={run.candidates.map((candidate) => ({ label: candidate.title, value: candidate.score ?? 0 }))} /><Chart title="Отношение прочитанных байтов SELECT" kind="bar" unit="×" data={run.candidates.map((candidate) => ({ label: candidate.title, value: candidate.selectReadBytesRatio ?? 0 }))} /></div><Alert tone="info" title="Как читать графики">Значения являются демонстрационными. В реальном экране данные должны приходить из сохранённых наблюдений запуска.</Alert></> : <div className="empty-inline">Для сравнения пока нет измерений.</div>}</div> : null}
    {tab === 'queries' ? <MonitoringTable rows={[run.config.queries]} columns={[{ key: 'mode', label: 'Режим', render: (queries) => <Badge tone="info">{queries.mode}</Badge> }, { key: 'manual', label: 'Ручных запросов', render: (queries) => queries.test_queries.length }, { key: 'auto', label: 'Автоопераций SELECT', render: (queries) => queries.auto_select_operations_count }, { key: 'like', label: 'LIKE по измеряемым колонкам', render: (queries) => queries.auto_like_on_measured_columns ? 'Да' : 'Нет' }]} rowKey={() => run.id} title="Нагрузка запуска" description="Снимок запросов из конфигурации на момент запуска." searchText={() => ''} showFilters={false} compact /> : null}
    {tab === 'diagnostics' ? <div className="tab-stack">{run.diagnostic ? <Alert tone="danger" title="Ошибка запуска">{run.diagnostic}</Alert> : <Alert tone="success" title="Диагностических ошибок нет">В демонстрационном снимке не зарегистрировано ошибок.</Alert>}<section className="surface-panel"><div className="panel-heading"><div><h2>События</h2><p>Сокращённая временная шкала демо-запуска.</p></div></div><ol className="event-list"><li><span>{formatDate(run.startedAt)}</span><strong>Конфигурация зафиксирована</strong><p>Сохранён снимок BenchmarkConfig.</p></li><li><span>{formatDate(run.startedAt)}</span><strong>Запущен baseline</strong><p>Создан контрольный вариант временной таблицы.</p></li>{run.finishedAt ? <li><span>{formatDate(run.finishedAt)}</span><strong>{run.status === 'completed' ? 'Финальная проверка завершена' : 'Запуск остановлен'}</strong><p>Терминальное состояние: {run.status}.</p></li> : null}</ol></section></div> : null}
    {tab === 'config' ? <section className="surface-panel"><div className="panel-heading"><div><h2>Снимок конфигурации</h2><p>Изменения исходного бенчмарка после запуска сюда не попадают.</p></div></div><pre className="code-block">{JSON.stringify(run.config, null, 2)}</pre></section> : null}
    {selectedCandidate ? <div className="drawer-backdrop" onClick={() => setSelectedCandidate(null)}><aside className="candidate-drawer" onClick={(event) => event.stopPropagation()}><div className="drawer-head"><div><span className="eyebrow">{selectedCandidate.stage}</span><h2>{selectedCandidate.title}</h2></div><Button variant="tertiary" onClick={() => setSelectedCandidate(null)}>Закрыть</Button></div><p>{selectedCandidate.change}</p><div className="metrics-grid compact"><MetricCard label="Оценка" value={selectedCandidate.score?.toFixed(2) ?? '—'} /><MetricCard label="SELECT bytes" value={`${selectedCandidate.selectReadBytesRatio?.toFixed(2) ?? '—'}×`} /><MetricCard label="Сжатие" value={`${selectedCandidate.compressionRatio?.toFixed(2) ?? '—'}×`} /></div><h3>DDL кандидата</h3><pre className="code-block">{selectedCandidate.ddl}</pre></aside></div> : null}
  </div>;
}

export function RunsPage({ selectedId, onSelectedId }: { selectedId: string | null; onSelectedId(id: string | null): void }): JSX.Element {
  const { runs } = useWorkspace();
  const [statusFilter, setStatusFilter] = useState('all');
  const selected = runs.find((run) => run.id === selectedId);
  if (selected) return <RunDetail run={selected} onBack={() => onSelectedId(null)} />;
  const rows = statusFilter === 'all' ? runs : runs.filter((run) => run.status === statusFilter);
  const columns: MonitoringTableColumn<DemoRun>[] = [
    { key: 'run', label: 'Запуск', render: (run) => <><strong className="mono">{run.id}</strong><small className="cell-note">{run.stage}</small></> },
    { key: 'benchmark', label: 'Бенчмарк', render: (run) => <span className="mono">{run.benchmarkId}</span> },
    { key: 'table', label: 'Таблица', render: (run) => <span className="mono">{run.table}</span> },
    { key: 'started', label: 'Начало', render: (run) => formatDate(run.startedAt) },
    { key: 'duration', label: 'Длительность', render: (run) => run.duration ?? '—' },
    { key: 'status', label: 'Состояние', render: (run) => runStatus(run.status) },
    { key: 'actions', label: '', className: 'monitor-actions-cell', render: (run) => <Button variant="secondary" onClick={() => onSelectedId(run.id)}>Открыть</Button> },
  ];
  return <div className="page-stack"><div className="page-heading"><div><span className="eyebrow">Выполнение</span><h1>Запуски</h1><p>История запусков, кандидаты, измерения и диагностика.</p></div><Badge tone="warning">Все результаты на этой странице демонстрационные</Badge></div><MonitoringTable rows={rows} columns={columns} rowKey={(run) => run.id} title="История запусков" description={`${runs.length} запуска · время отображается в Europe/Moscow`} searchPlaceholder="ID запуска, бенчмарк или таблица…" searchText={(run) => `${run.id} ${run.benchmarkId} ${run.table} ${run.stage}`} filters={<SelectField label="Состояние" value={statusFilter} options={[{ value: 'all', label: 'Все состояния' }, { value: 'queued', label: 'В очереди' }, { value: 'running', label: 'Выполняется' }, { value: 'completed', label: 'Завершён' }, { value: 'failed', label: 'Ошибка' }, { value: 'cancelled', label: 'Отменён' }]} onChange={(event) => setStatusFilter(event.target.value)} />} filtersActive={statusFilter !== 'all'} onResetFilters={() => setStatusFilter('all')} /></div>;
}
