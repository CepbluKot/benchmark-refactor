import { useMemo, useState } from 'react';
import { Alert, Badge, Button, Modal, SelectField, Status, TextField } from '@adqm/gpb-ui';

import { MonitoringTable, type MonitoringTableColumn } from '../components/MonitoringTable';
import type { DataSource } from '../demo/model';
import { sourceError } from '../demo/model';
import { useWorkspace } from '../demo/workspace';
import { useEditor } from '../state/editor';

interface SourceDraft extends DataSource { password: string }

function emptySource(): SourceDraft {
  return { id: '', dbms: 'clickhouse', credential_type: 'password', host: '', port: 8123, login: '', password: '', status: 'unchecked' };
}

function status(source: DataSource): JSX.Element {
  if (source.status === 'available') return <Status status="success" label="Доступно" />;
  if (source.status === 'unavailable') return <Status status="danger" label="Недоступно" />;
  return <Status status="neutral" label="Не проверено" />;
}

export function SourcesPage(): JSX.Element {
  const { sources, saveSource, removeSource, checkSource } = useWorkspace();
  const { benchmarks } = useEditor();
  const [draft, setDraft] = useState<SourceDraft | null>(null);
  const [previousId, setPreviousId] = useState<string | undefined>();
  const [showValidation, setShowValidation] = useState(false);
  const [statusFilter, setStatusFilter] = useState('all');
  const usedBy = useMemo(() => Object.fromEntries(sources.map((source) => [source.id, benchmarks.filter((benchmark) => benchmark.connection_id === source.id).length])), [benchmarks, sources]);
  const visibleSources = useMemo(() => statusFilter === 'all' ? sources : sources.filter((source) => source.status === statusFilter), [sources, statusFilter]);
  const columns = useMemo<MonitoringTableColumn<DataSource>[]>(() => [
    { key: 'id', label: 'Подключение', render: (source) => <strong className="mono">{source.id}</strong> },
    { key: 'dbms', label: 'СУБД', render: () => <Badge tone="info">ClickHouse</Badge> },
    { key: 'address', label: 'Адрес', render: (source) => <span className="mono">{source.host}:{source.port}</span> },
    { key: 'login', label: 'Пользователь', render: (source) => <span className="mono">{source.login}</span> },
    { key: 'status', label: 'Состояние', render: (source) => <>{status(source)}{source.checkedAt ? <small className="cell-note">демо-проверка {new Date(source.checkedAt).toLocaleTimeString('ru-RU')}</small> : null}</> },
    { key: 'usage', label: 'Используется', render: (source) => `${usedBy[source.id] ?? 0} бенчмарка` },
    { key: 'actions', label: '', className: 'monitor-actions-cell', render: (source) => <div className="table-actions"><Button variant="tertiary" onClick={() => checkSource(source.id)}>Проверить</Button><Button variant="secondary" onClick={() => open(source)}>Изменить</Button><Button variant="danger" disabled={Boolean(usedBy[source.id])} title={usedBy[source.id] ? 'Сначала измените ссылки в бенчмарках' : 'Удалить источник'} onClick={() => removeSource(source.id)}>Удалить</Button></div> },
  ], [checkSource, removeSource, usedBy]);
  const error = draft ? sourceError(draft, sources.filter((item) => item.id !== previousId)) : '';

  const open = (source?: DataSource) => {
    setShowValidation(false);
    setPreviousId(source?.id);
    setDraft(source ? { ...source, password: '' } : emptySource());
  };

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div><span className="eyebrow">Конфигурация среды</span><h1>Источники данных</h1><p>Подключения к ClickHouse, которые выбираются в настройках бенчмарков.</p></div>
        <Button variant="primary" onClick={() => open()}>Добавить источник</Button>
      </div>
      <Alert tone="info" title="Демо-режим">Проверка соединения меняет только локальный статус интерфейса. Запрос к базе данных не выполняется.</Alert>
      <MonitoringTable rows={visibleSources} columns={columns} rowKey={(source) => source.id} title="Подключения" description={`${sources.length} настроено · пароли не отображаются и не сохраняются в браузере`} searchPlaceholder="ID, адрес или пользователь…" searchText={(source) => `${source.id} ${source.host} ${source.port} ${source.login}`} filters={<SelectField label="Состояние" value={statusFilter} options={[{ value: 'all', label: 'Все состояния' }, { value: 'available', label: 'Доступно' }, { value: 'unavailable', label: 'Недоступно' }, { value: 'unchecked', label: 'Не проверено' }]} onChange={(event) => setStatusFilter(event.target.value)} />} filtersActive={statusFilter !== 'all'} onResetFilters={() => setStatusFilter('all')} />
      <Modal open={Boolean(draft)} onClose={() => setDraft(null)} title={previousId ? `Подключение ${previousId}` : 'Новое подключение'} footer={<><Button variant="secondary" onClick={() => setDraft(null)}>Отмена</Button><Button variant="primary" onClick={() => { if (!draft || error) { setShowValidation(true); return; } const { password: _password, ...source } = draft; saveSource({ ...source, status: previousId ? source.status : 'unchecked' }, previousId); setDraft(null); }}>Сохранить</Button></>}>
        {draft ? <div className="form-stack">
          {showValidation && error ? <Alert tone="danger" title="Проверьте форму">{error}</Alert> : null}
          <TextField label="Идентификатор" value={draft.id} onChange={(event) => setDraft({ ...draft, id: event.target.value })} placeholder="local_ch_hits" />
          <SelectField label="СУБД" value={draft.dbms} options={[{ value: 'clickhouse', label: 'ClickHouse' }]} onChange={() => undefined} />
          <div className="form-grid"><TextField label="Хост" value={draft.host} onChange={(event) => setDraft({ ...draft, host: event.target.value })} placeholder="clickhouse.internal" /><TextField label="Порт" type="number" value={draft.port} onChange={(event) => setDraft({ ...draft, port: Number(event.target.value) })} /></div>
          <div className="form-grid"><TextField label="Пользователь" value={draft.login} onChange={(event) => setDraft({ ...draft, login: event.target.value })} /><TextField label="Пароль" type="password" value={draft.password} onChange={(event) => setDraft({ ...draft, password: event.target.value })} placeholder={previousId ? 'Оставьте пустым, чтобы не менять' : 'Не сохраняется в демо'} /></div>
          <p className="field-help">В реальном продукте пароль должен передаваться серверу и храниться в Secret Manager. В демо он удаляется при закрытии формы.</p>
        </div> : null}
      </Modal>
    </div>
  );
}
