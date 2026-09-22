import { useState } from 'react';
import { Alert, Badge, Button, Modal, SelectField, TextField } from '@adqm/gpb-ui';
import { ActionIcon } from '../components/ActionIcon';
import { MaterialIcon } from '../components/MaterialIcon';
import type { Source } from '../control/api';
import { useWorkspace } from '../control/workspace';
import { useI18n } from '../i18n';

interface SourceDraft { name: string; host: string; port: number; login: string; secretRef: string }
const emptySource = (): SourceDraft => ({ name: '', host: '', port: 8123, login: '', secretRef: '' });
const sourceDraft = (source: Source): SourceDraft => ({ name: source.name, host: source.host, port: source.port, login: source.login, secretRef: '' });
function sourceStatus(source: Source, t: (ru: string, en: string) => string): JSX.Element { return <Badge tone={source.status === 'available' ? 'success' : source.status === 'unavailable' ? 'danger' : 'neutral'}><span className="status-badge">{source.status === 'available' ? t('Готов', 'Ready') : source.status === 'unavailable' ? t('Недоступен', 'Unavailable') : t('Не проверен', 'Unchecked')}</span></Badge>; }

export function SourcesPage(): JSX.Element {
  const { t } = useI18n();
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
  const save = async () => { if (!draft) return; if (!draft.name.trim() || !draft.host.trim() || !draft.login.trim() || !draft.secretRef.trim()) { setFailure(t('Заполните название, хост, логин и ссылку на секрет.', 'Fill in the name, host, login, and secret reference.')); return; } setSaving(true); setFailure(null); try { if (mode === 'edit' && selected) await updateSource(selected.id, draft); else await createSource(draft); setMode(null); setSelected(null); setDraft(null); } catch (error) { setFailure(error instanceof Error ? error.message : t('Не удалось сохранить источник', 'Could not save source')); } finally { setSaving(false); } };
  const remove = async () => { if (!selected) return; setSaving(true); setFailure(null); try { await deleteSource(selected.id); setMode(null); setSelected(null); } catch (error) { setFailure(error instanceof Error ? error.message : t('Не удалось удалить источник', 'Could not delete source')); } finally { setSaving(false); } };
  const sourceUsed = selected ? benchmarks.some((benchmark) => benchmark.sourceId === selected.id) : false;
  return <div className="page-stack product-page sources-page"><div className="page-heading"><div><h1>{t('Источники данных', 'Data sources')}</h1></div><Button variant="primary" onClick={openCreate}>＋ {t('Создать источник', 'Create source')}</Button></div>{failure && !mode ? <Alert tone="danger" title={t('Ошибка', 'Error')}>{failure}</Alert> : null}<div className="source-list-toolbar">
      <TextField label={t('Поиск источников', 'Search sources')} placeholder={t('Название, тип или адрес…', 'Name, type, or address…')} value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} />
      <SelectField label={t('Статус', 'Status')} value={statusFilter} options={[{ value: 'all', label: t('Все состояния', 'All statuses') }, { value: 'available', label: t('Готов', 'Ready') }, { value: 'unchecked', label: t('Не проверен', 'Unchecked') }, { value: 'unavailable', label: t('Недоступен', 'Unavailable') }]} onChange={event => { setStatusFilter(event.target.value); setPage(0); }} />
      <span className="source-list-count" aria-live="polite">{t('Найдено', 'Found')}: {visible.length}</span>
    </div>
    <ul className="source-list" aria-label={t('Источники данных', 'Data sources')}>
      {pageSources.map(source => <li key={source.id} className="source-card">
        <div className="source-card-icon" aria-hidden="true"><MaterialIcon name="data" size={28} /></div>
        <div className="source-card-info"><h2>{source.name}</h2><div className="source-card-meta"><span>ClickHouse</span><span aria-hidden="true">·</span><span className="mono">{source.host}:{source.port}</span></div></div>
        <div className="source-card-actions">{sourceStatus(source, t)}<div className="source-card-action-buttons"><Button variant="secondary" className="source-card-action" onClick={() => openEdit(source)}><ActionIcon name="edit" />{t('Изменить', 'Edit')}</Button><Button variant="secondary" className="source-card-action source-card-action-danger" onClick={() => openDelete(source)}><ActionIcon name="delete" />{t('Удалить', 'Delete')}</Button></div></div>
      </li>)}
    </ul>
    {!visible.length ? <div className="source-list-empty"><h2>{sources.length ? t('Источники не найдены', 'No sources found') : t('Источников пока нет', 'No sources yet')}</h2><p>{sources.length ? t('Измените поисковый запрос или статус.', 'Change the search query or status.') : t('Создайте подключение, чтобы выбрать таблицы для бенчмарков.', 'Create a connection to select tables for benchmarks.')}</p>{sources.length ? <Button variant="secondary" onClick={() => { setQuery(''); setStatusFilter('all'); setPage(0); }}>{t('Сбросить фильтры', 'Reset filters')}</Button> : null}</div> : null}
    {pageCount > 1 ? <div className="source-list-pagination"><span>{t('Страница', 'Page')} {currentPage + 1} {t('из', 'of')} {pageCount}</span><Button variant="secondary" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>{t('Назад', 'Back')}</Button><Button variant="secondary" disabled={currentPage === pageCount - 1} onClick={() => setPage(currentPage + 1)}>{t('Вперёд', 'Next')}</Button></div> : null}

    <Modal open={mode !== null} onClose={close} title={mode === 'delete' ? t('Удалить источник', 'Delete source') : mode === 'edit' ? t('Редактировать источник', 'Edit source') : t('Создать источник', 'Create source')} footer={<><Button variant="secondary" disabled={saving} onClick={close}>{t('Отмена', 'Cancel')}</Button>{mode === 'delete' ? <Button variant="primary" disabled={saving || sourceUsed} onClick={() => void remove()}>{saving ? t('Удаление…', 'Deleting…') : t('Удалить', 'Delete')}</Button> : <Button variant="primary" disabled={saving} onClick={() => void save()}>{saving ? t('Сохранение…', 'Saving…') : mode === 'edit' ? t('Сохранить', 'Save') : t('Создать', 'Create')}</Button>}</>}>{mode === 'delete' ? <div className="form-stack">{sourceUsed ? <Alert tone="warning" title={t('Источник используется', 'Source is in use')}>{t('Сначала выберите другой источник в связанных бенчмарках.', 'Choose another source in linked benchmarks first.')}</Alert> : null}<p>{t(`Удалить источник «${selected?.name}»? Это действие нельзя отменить.`, `Delete source “${selected?.name}”? This action cannot be undone.`)}</p></div> : draft ? <div className="form-stack source-modal-form">{failure ? <Alert tone="danger" title={t('Проверьте форму', 'Check the form')}>{failure}</Alert> : null}<TextField label={t('Название подключения', 'Connection name')} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder={t('Например, prod_clickhouse', 'For example, prod_clickhouse')} /><SelectField label={t('Тип источника', 'Source type')} value="clickhouse" options={[{ value: 'clickhouse', label: 'ClickHouse' }]} onChange={() => undefined} /><div className="form-grid"><TextField label={t('Хост', 'Host')} value={draft.host} onChange={(event) => setDraft({ ...draft, host: event.target.value })} placeholder="clickhouse.internal" /><TextField label={t('Порт', 'Port')} type="number" value={draft.port} onChange={(event) => setDraft({ ...draft, port: Number(event.target.value) })} /></div><TextField label={t('Логин', 'Login')} value={draft.login} onChange={(event) => setDraft({ ...draft, login: event.target.value })} placeholder="benchmark_reader" /><TextField label={t('Ссылка на секрет', 'Secret reference')} value={draft.secretRef} onChange={(event) => setDraft({ ...draft, secretRef: event.target.value })} placeholder="secret://benchmark/source-reader" /><p className="field-help">{t('Пароль не передаётся через браузер. Укажите ссылку на секрет, доступный Control API.', 'The password is not sent through the browser. Provide a secret reference available to Control API.')}</p></div> : null}</Modal></div>;
}
