import { useState } from 'react';
import { Alert, Badge, Button, Modal, SelectField, TextField } from '@adqm/gpb-ui';
import { ActionIcon } from '../components/ActionIcon';
import { MaterialIcon } from '../components/MaterialIcon';
import type { Source } from '../control/api';
import { useWorkspace } from '../control/workspace';

interface SourceDraft { name: string; host: string; port: number; login: string; secretRef: string }
const emptySource = (): SourceDraft => ({ name: '', host: '', port: 8123, login: '', secretRef: '' });
const sourceDraft = (source: Source): SourceDraft => ({ name: source.name, host: source.host, port: source.port, login: source.login, secretRef: '' });
function sourceStatus(source: Source): JSX.Element { return <Badge tone={source.status === 'available' ? 'success' : source.status === 'unavailable' ? 'danger' : 'neutral'}><span className="status-badge">{source.status === 'available' ? 'Готов' : source.status === 'unavailable' ? 'Недоступен' : 'Не проверен'}</span></Badge>; }

export function SourcesPage(): JSX.Element {
  const { sources, benchmarks, createSource, updateSource, deleteSource } = useWorkspace();
  const [mode, setMode] = useState<'create' | 'edit' | 'delete' | null>(null); const [selected, setSelected] = useState<Source | null>(null); const [draft, setDraft] = useState<SourceDraft | null>(null); const [statusFilter, setStatusFilter] = useState('all'); const [failure, setFailure] = useState<string | null>(null); const [saving, setSaving] = useState(false);
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);
  const visible = sources.filter(source => (statusFilter === 'all' || source.status === statusFilter)
    && `${source.name} ClickHouse ${source.host}:${source.port}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const pageCount = Math.max(1, Math.ceil(visible.length / 12));
  const currentPage = Math.min(page, pageCount - 1);
  const pageSources = visible.slice(currentPage * 12, (currentPage + 1) * 12);
  const openCreate = () => { setFailure(null); setSelected(null); setDraft(emptySource()); setMode('create'); };
  const openEdit = (source: Source) => { setFailure(null); setSelected(source); setDraft(sourceDraft(source)); setMode('edit'); };
  const openDelete = (source: Source) => { setFailure(null); setSelected(source); setDraft(null); setMode('delete'); };
  const close = () => { if (!saving) { setMode(null); setSelected(null); setDraft(null); } };
  const save = async () => { if (!draft) return; if (!draft.name.trim() || !draft.host.trim() || !draft.login.trim() || !draft.secretRef.trim()) { setFailure('Заполните название, хост, логин и ссылку на секрет.'); return; } setSaving(true); setFailure(null); try { if (mode === 'edit' && selected) await updateSource(selected.id, draft); else await createSource(draft); setMode(null); setSelected(null); setDraft(null); } catch (error) { setFailure(error instanceof Error ? error.message : 'Не удалось сохранить источник'); } finally { setSaving(false); } };
  const remove = async () => { if (!selected) return; setSaving(true); setFailure(null); try { await deleteSource(selected.id); setMode(null); setSelected(null); } catch (error) { setFailure(error instanceof Error ? error.message : 'Не удалось удалить источник'); } finally { setSaving(false); } };
  const sourceUsed = selected ? benchmarks.some((benchmark) => benchmark.sourceId === selected.id) : false;
  return <div className="page-stack product-page sources-page"><div className="page-heading"><div><h1>Источники данных</h1></div><Button variant="primary" onClick={openCreate}>＋ Создать источник</Button></div>{failure && !mode ? <Alert tone="danger" title="Ошибка">{failure}</Alert> : null}<div className="source-list-toolbar">
      <TextField label="Поиск источников" placeholder="Название, тип или адрес…" value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} />
      <SelectField label="Статус" value={statusFilter} options={[{ value: 'all', label: 'Все состояния' }, { value: 'available', label: 'Готов' }, { value: 'unchecked', label: 'Не проверен' }, { value: 'unavailable', label: 'Недоступен' }]} onChange={event => { setStatusFilter(event.target.value); setPage(0); }} />
      <span className="source-list-count" aria-live="polite">Найдено: {visible.length}</span>
    </div>
    <ul className="source-list" aria-label="Источники данных">
      {pageSources.map(source => <li key={source.id} className="source-card">
        <div className="source-card-icon" aria-hidden="true"><MaterialIcon name="data" size={28} /></div>
        <div className="source-card-info"><h2>{source.name}</h2><div className="source-card-meta"><span>ClickHouse</span><span aria-hidden="true">·</span><span className="mono">{source.host}:{source.port}</span></div></div>
        <div className="source-card-actions">{sourceStatus(source)}<div className="source-card-action-buttons"><Button variant="secondary" className="source-card-action" onClick={() => openEdit(source)}><ActionIcon name="edit" />Изменить</Button><Button variant="secondary" className="source-card-action source-card-action-danger" onClick={() => openDelete(source)}><ActionIcon name="delete" />Удалить</Button></div></div>
      </li>)}
    </ul>
    {!visible.length ? <div className="source-list-empty"><h2>{sources.length ? 'Источники не найдены' : 'Источников пока нет'}</h2><p>{sources.length ? 'Измените поисковый запрос или статус.' : 'Создайте подключение, чтобы выбрать таблицы для бенчмарков.'}</p>{sources.length ? <Button variant="secondary" onClick={() => { setQuery(''); setStatusFilter('all'); setPage(0); }}>Сбросить фильтры</Button> : null}</div> : null}
    {pageCount > 1 ? <div className="source-list-pagination"><span>Страница {currentPage + 1} из {pageCount}</span><Button variant="secondary" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Назад</Button><Button variant="secondary" disabled={currentPage === pageCount - 1} onClick={() => setPage(currentPage + 1)}>Вперёд</Button></div> : null}

    <Modal open={mode !== null} onClose={close} title={mode === 'delete' ? 'Удалить источник' : mode === 'edit' ? 'Редактировать источник' : 'Создать источник'} footer={<><Button variant="secondary" disabled={saving} onClick={close}>Отмена</Button>{mode === 'delete' ? <Button variant="primary" disabled={saving || sourceUsed} onClick={() => void remove()}>{saving ? 'Удаление…' : 'Удалить'}</Button> : <Button variant="primary" disabled={saving} onClick={() => void save()}>{saving ? 'Сохранение…' : mode === 'edit' ? 'Сохранить' : 'Создать'}</Button>}</>}>{mode === 'delete' ? <div className="form-stack">{sourceUsed ? <Alert tone="warning" title="Источник используется">Сначала выберите другой источник в связанных бенчмарках.</Alert> : null}<p>Удалить источник «{selected?.name}»? Это действие нельзя отменить.</p></div> : draft ? <div className="form-stack source-modal-form">{failure ? <Alert tone="danger" title="Проверьте форму">{failure}</Alert> : null}<TextField label="Название подключения" value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="Например, prod_clickhouse" /><SelectField label="Тип источника" value="clickhouse" options={[{ value: 'clickhouse', label: 'ClickHouse' }]} onChange={() => undefined} /><div className="form-grid"><TextField label="Хост" value={draft.host} onChange={(event) => setDraft({ ...draft, host: event.target.value })} placeholder="clickhouse.internal" /><TextField label="Порт" type="number" value={draft.port} onChange={(event) => setDraft({ ...draft, port: Number(event.target.value) })} /></div><TextField label="Логин" value={draft.login} onChange={(event) => setDraft({ ...draft, login: event.target.value })} placeholder="benchmark_reader" /><TextField label="Ссылка на секрет" value={draft.secretRef} onChange={(event) => setDraft({ ...draft, secretRef: event.target.value })} placeholder="secret://benchmark/source-reader" /><p className="field-help">Пароль не передаётся через браузер. Укажите ссылку на секрет, доступный Control API.</p></div> : null}</Modal></div>;
}
