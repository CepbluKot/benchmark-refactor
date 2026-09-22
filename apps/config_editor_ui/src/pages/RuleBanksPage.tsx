import { useMemo, useState } from 'react';
import { Alert, Button, Modal, SelectField } from '@adqm/gpb-ui';
import { ActionIcon } from '../components/ActionIcon';
import { MonitoringTable, type MonitoringTableColumn } from '../components/MonitoringTable';
import { useWorkspace } from '../control/workspace';
import type { Strategy } from '../control/api';
import type { StrategyMethod } from '../strategies/model';
import { useI18n } from '../i18n';

function methodOptions(t: (ru: string, en: string) => string): Array<{ value: StrategyMethod; label: string }> {
  return [
    { value: 'types_strategy', label: t('Типы и кодеки', 'Types and codecs') },
    { value: 'indexes_strategy', label: t('Skip-индексы', 'Skip indexes') },
    { value: 'combined_strategy', label: t('Комбинированный', 'Combined') },
    { value: 'sequential_topn_strategy', label: t('Последовательный Top-N', 'Sequential Top-N') },
    { value: 'sequential_phased_topn_strategy', label: t('Поэтапный Top-N', 'Phased Top-N') },
  ];
}

export function RuleBanksPage({ onCreate, onEdit }: { onCreate(): void; onEdit(id: string): void }): JSX.Element {
  const { t } = useI18n();
  const { strategies, benchmarks, deleteStrategy } = useWorkspace();
  const [selected, setSelected] = useState<Strategy | null>(null);
  const [strategyFilter, setStrategyFilter] = useState('all');
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const used = selected ? benchmarks.some((item) => item.strategyId === selected.id) : false;
  const rows = useMemo(() => strategyFilter === 'all' ? strategies : strategies.filter((item) => item.strategy === strategyFilter), [strategies, strategyFilter]);
  const remove = async () => { if (!selected || busy || used) return; setBusy(true); setFailure(null); try { await deleteStrategy(selected.id); setSelected(null); } catch (error) { setFailure(error instanceof Error ? error.message : t('Не удалось удалить стратегию', 'Could not delete strategy')); } finally { setBusy(false); } };
  const columns: MonitoringTableColumn<Strategy>[] = [
    { key: 'name', label: t('Название', 'Name'), render: (item) => <strong>{item.name}</strong> },
    { key: 'actions', label: '', render: (item) => <div className="table-actions"><Button variant="secondary" aria-label={`${t('Изменить стратегию', 'Edit strategy')}: ${item.name}`} onClick={() => onEdit(item.id)}><ActionIcon name="edit" />{t('Изменить', 'Edit')}</Button><Button variant="secondary" className="action-icon-danger" aria-label={`${t('Удалить стратегию', 'Delete strategy')}: ${item.name}`} onClick={() => { setSelected(item); setFailure(null); }}><ActionIcon name="delete" />{t('Удалить', 'Delete')}</Button></div> },
  ];
  return <div className="page-stack product-page strategies-page"><div className="page-heading"><div><h1>{t('Стратегии поиска', 'Search strategies')}</h1><p>{t('Общие шаблоны для всех пространств. Применяются при создании бенчмарка.', 'Shared templates for every workspace. They are applied when a benchmark is created.')}</p></div><Button variant="primary" onClick={onCreate}>＋ {t('Создать стратегию', 'Create strategy')}</Button></div><MonitoringTable rows={rows} columns={columns} rowKey={(item) => item.id} title="" description="" searchPlaceholder={t('Поиск по названию, методу или этапу…', 'Search by name, method, or stage…')} searchText={(item) => `${item.name} ${item.strategy} ${item.phases.join(' ')}`} filters={<SelectField label={t('Метод поиска', 'Search method')} value={strategyFilter} options={[{ value: 'all', label: t('Все методы', 'All methods') }, ...methodOptions(t)]} onChange={(event) => setStrategyFilter(event.target.value)} />} filtersActive={strategyFilter !== 'all'} onResetFilters={() => setStrategyFilter('all')} emptyTitle={t('Стратегий пока нет', 'No strategies yet')} emptyDescription={t('Создайте первую стратегию поиска.', 'Create the first search strategy.')} /><Modal open={selected !== null} onClose={() => { if (!busy) setSelected(null); }} title={t('Удалить стратегию', 'Delete strategy')} footer={<><Button variant="secondary" disabled={busy} onClick={() => setSelected(null)}>{t('Отмена', 'Cancel')}</Button><Button variant="primary" disabled={busy || used} onClick={() => void remove()}>{busy ? t('Удаление…', 'Deleting…') : t('Удалить', 'Delete')}</Button></>}><div className="form-stack">{failure ? <Alert tone="danger" title={t('Не удалось удалить', 'Could not delete')}>{failure}</Alert> : null}<p>{t(`Удалить стратегию «${selected?.name}»? Это действие нельзя отменить.`, `Delete strategy “${selected?.name}”? This action cannot be undone.`)}</p>{used ? <Alert tone="warning" title={t('Стратегия используется', 'Strategy is in use')}>{t('Сначала выберите другую стратегию в связанных бенчмарках.', 'Choose another strategy in linked benchmarks first.')}</Alert> : null}</div></Modal></div>;
}
