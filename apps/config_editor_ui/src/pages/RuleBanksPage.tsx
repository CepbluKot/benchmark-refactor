import { useMemo, useState } from 'react';
import { Alert, Button, Modal, SelectField } from '@adqm/gpb-ui';
import { ActionIcon } from '../components/ActionIcon';
import { MonitoringTable, type MonitoringTableColumn } from '../components/MonitoringTable';
import { useWorkspace } from '../control/workspace';
import type { Strategy } from '../control/api';
import { METHOD_LABELS } from '../strategies/model';

const OPTIONS = Object.entries(METHOD_LABELS).map(([value, label]) => ({ value, label }));

export function RuleBanksPage({ onCreate, onEdit }: { onCreate(): void; onEdit(id: string): void }): JSX.Element {
  const { strategies, benchmarks, deleteStrategy } = useWorkspace();
  const [selected, setSelected] = useState<Strategy | null>(null);
  const [strategyFilter, setStrategyFilter] = useState('all');
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const used = selected ? benchmarks.some((item) => item.strategyId === selected.id) : false;
  const rows = useMemo(() => strategyFilter === 'all' ? strategies : strategies.filter((item) => item.strategy === strategyFilter), [strategies, strategyFilter]);
  const remove = async () => { if (!selected || busy || used) return; setBusy(true); setFailure(null); try { await deleteStrategy(selected.id); setSelected(null); } catch (error) { setFailure(error instanceof Error ? error.message : 'Не удалось удалить стратегию'); } finally { setBusy(false); } };
  const columns: MonitoringTableColumn<Strategy>[] = [
    { key: 'name', label: 'Название', render: (item) => <strong>{item.name}</strong> },
    { key: 'actions', label: '', render: (item) => <div className="table-actions"><Button variant="secondary" aria-label={`Изменить стратегию: ${item.name}`} onClick={() => onEdit(item.id)}><ActionIcon name="edit" />Изменить</Button><Button variant="secondary" className="action-icon-danger" aria-label={`Удалить стратегию: ${item.name}`} onClick={() => { setSelected(item); setFailure(null); }}><ActionIcon name="delete" />Удалить</Button></div> },
  ];
  return <div className="page-stack product-page strategies-page"><div className="page-heading"><div><h1>Стратегии поиска</h1><p>Общие шаблоны для всех пространств. Применяются при создании бенчмарка.</p></div><Button variant="primary" onClick={onCreate}>＋ Создать стратегию</Button></div><MonitoringTable rows={rows} columns={columns} rowKey={(item) => item.id} title="" description="" searchPlaceholder="Поиск по названию, методу или этапу…" searchText={(item) => `${item.name} ${item.strategy} ${item.phases.join(' ')}`} filters={<SelectField label="Метод поиска" value={strategyFilter} options={[{ value: 'all', label: 'Все методы' }, ...OPTIONS]} onChange={(event) => setStrategyFilter(event.target.value)} />} filtersActive={strategyFilter !== 'all'} onResetFilters={() => setStrategyFilter('all')} emptyTitle="Стратегий пока нет" emptyDescription="Создайте первую стратегию поиска." /><Modal open={selected !== null} onClose={() => { if (!busy) setSelected(null); }} title="Удалить стратегию" footer={<><Button variant="secondary" disabled={busy} onClick={() => setSelected(null)}>Отмена</Button><Button variant="primary" disabled={busy || used} onClick={() => void remove()}>{busy ? 'Удаление…' : 'Удалить'}</Button></>}><div className="form-stack">{failure ? <Alert tone="danger" title="Не удалось удалить">{failure}</Alert> : null}<p>Удалить стратегию «{selected?.name}»? Это действие нельзя отменить.</p>{used ? <Alert tone="warning" title="Стратегия используется">Сначала выберите другую стратегию в связанных бенчмарках.</Alert> : null}</div></Modal></div>;
}
