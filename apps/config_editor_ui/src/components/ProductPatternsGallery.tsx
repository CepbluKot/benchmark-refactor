import { useState } from 'react';
import type { ReactNode } from 'react';
import { Alert, Badge, Button, Modal, SelectField, Switch, TextField } from '@adqm/gpb-ui';
import { ActionIcon } from './ActionIcon';
import { MonitoringTable, type MonitoringTableColumn } from './MonitoringTable';
import { WorkspaceAvatarPicker } from './WorkspaceAvatarPicker';
import { WorkspaceIcon } from './WorkspaceIcon';
import { MaterialIcon } from './MaterialIcon';
import type { WorkspaceIcon as WorkspaceIconName } from './workspaceIcons';

interface CatalogueRow { id: string; name: string; method: string; status: string }
const catalogueRows: CatalogueRow[] = [{ id: 'example', name: 'Оптимизация событий', method: 'Поэтапный Top-N', status: 'Готов' }];
const catalogueColumns: MonitoringTableColumn<CatalogueRow>[] = [
  { key: 'name', label: 'Название', render: (row) => <strong>{row.name}</strong> },
  { key: 'method', label: 'Метод', render: (row) => row.method },
  { key: 'status', label: 'Состояние', render: (row) => <Badge tone="success">{row.status}</Badge> },
  { key: 'actions', label: '', render: (row) => <div className="table-actions"><Button variant="secondary" aria-label={`Настроить: ${row.name}`}><ActionIcon name="configure" />Настроить</Button><Button variant="secondary" aria-label={`Изменить: ${row.name}`}><ActionIcon name="edit" />Изменить</Button></div> },
];

function Pattern({ id, title, description, children }: { id: string; title: string; description: string; children: ReactNode }): JSX.Element {
  return <section id={`pattern-${id}`} className="product-pattern"><header><span>PRODUCT PATTERN</span><h2>{title}</h2><p>{description}</p></header><div className="product-pattern-stage">{children}</div></section>;
}

export function ProductPatternsGallery(): JSX.Element {
  const [workspaceIcon, setWorkspaceIcon] = useState<WorkspaceIconName>('target');
  const [advanced, setAdvanced] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  return <section className="product-patterns" aria-labelledby="product-patterns-title">
    <header className="product-patterns-heading"><span>DB BENCHMARK / PRODUCT UI</span><h1 id="product-patterns-title">Продуктовые паттерны</h1><p>Элементы, которые используются на рабочих страницах поверх базовых компонентов ADQM.</p></header>

    <Pattern id="navigation-header" title="Навигация и шапка" description="Состояния основной навигации, выбора пространства и подключения к потоку событий.">
      <div className="pattern-shell-preview"><aside className="pattern-nav-preview"><div className="product-logo"><span><WorkspaceIcon /></span><strong>DB Benchmark</strong></div><Button variant="primary"><MaterialIcon name="strategy" />Стратегии поиска</Button><Button variant="secondary"><MaterialIcon name="benchmark" />Бенчмарки</Button></aside><div className="pattern-header-preview"><Button variant="secondary">ТЕКУЩЕЕ ПРОСТРАНСТВО · Аналитика</Button><span className="socket-status" role="status"><MaterialIcon name="settings" size={16} />СОКЕТ: ПОДКЛЮЧЕН</span></div></div>
    </Pattern>

    <Pattern id="monitoring-table" title="Таблица мониторинга" description="Единый контейнер таблицы с фильтрами, поиском, статусами и действиями строки.">
      <MonitoringTable rows={catalogueRows} columns={catalogueColumns} rowKey={(row) => row.id} title="Стратегии поиска" description="Пример рабочего списка" searchText={(row) => `${row.name} ${row.method}`} filters={<SelectField label="Метод поиска" value="all" options={[{ value: 'all', label: 'Все методы' }]} onChange={() => undefined} />} />
    </Pattern>

    <Pattern id="source-card" title="Карточка источника" description="Компактное представление подключения с типом, адресом, статусом и действиями.">
      <ul className="source-list pattern-source-list"><li className="source-card"><div className="source-card-icon"><WorkspaceIcon icon="data" /></div><div className="source-card-info"><h2>Локальный ClickHouse</h2><div className="source-card-meta"><span>ClickHouse</span><span>·</span><span className="mono">clickhouse:8123</span></div></div><div className="source-card-actions"><Badge tone="success"><span className="status-badge">Готов</span></Badge><div className="source-card-action-buttons"><Button variant="secondary" className="source-card-action"><ActionIcon name="edit" />Изменить</Button><Button variant="secondary" className="source-card-action source-card-action-danger"><ActionIcon name="delete" />Удалить</Button></div></div></li></ul>
    </Pattern>

    <Pattern id="wizard-stepper" title="Пошаговый сценарий" description="Навигация по длинной форме с одним активным этапом и явным прогрессом.">
      <nav className="strategy-stepper pattern-stepper" aria-label="Пример этапов"><Button variant="secondary"><span><MaterialIcon name="check" size={16} /></span>Основное</Button><Button variant="primary"><span>2</span>Метод поиска</Button><Button variant="secondary" disabled><span>3</span>Правила вариантов</Button><Button variant="secondary" disabled><span>4</span>Бюджет поиска</Button></nav>
    </Pattern>

    <Pattern id="choice-card" title="Карточки выбора" description="Крупный одиночный выбор с названием и пояснением — для методов и приоритетов.">
      <div className="strategy-choice-grid"><Button variant="primary" aria-pressed="true"><strong>Поэтапный Top-N</strong><small>Полный поэтапный поиск с финальной проверкой.</small></Button><Button variant="secondary" aria-pressed="false"><strong>Комбинированный поиск</strong><small>Типы, кодеки и индексы в одном поиске.</small></Button></div>
    </Pattern>

    <Pattern id="pipeline-preview" title="Предпросмотр этапов" description="Короткая читаемая последовательность, производная от выбранного метода.">
      <div className="strategy-pipeline"><strong>Этапы поиска</strong><div><span>ORDER BY</span><span>→ Типы</span><span>→ Кодеки</span><span>→ Индексы</span><span>→ Финальная проверка</span></div></div>
    </Pattern>

    <Pattern id="summary-panel" title="Закреплённое резюме" description="Ключевые решения формы остаются видимыми без отдельного шага проверки.">
      <aside className="strategy-summary pattern-summary"><span>Шаблон</span><strong>Поэтапная оптимизация</strong><dl><dt>Метод</dt><dd>Поэтапный Top-N</dd><dt>Этапов</dt><dd>6</dd><dt>Кандидатов</dt><dd>100</dd><dt>Приоритет</dt><dd>Сбалансированно</dd></dl></aside>
    </Pattern>

    <Pattern id="workspace-picker" title="Выбор иконки пространства" description="Фирменный аватар и раскрывающаяся палитра допустимых иконок.">
      <div className="pattern-inline"><WorkspaceAvatarPicker value={workspaceIcon} onChange={setWorkspaceIcon} disabled={false} /><span>Выбранная иконка пространства</span></div>
    </Pattern>

    <Pattern id="status-indicators" title="Статусы и переключатели" description="Текст всегда дополняет цвет; расширенные параметры раскрываются явно.">
      <div className="pattern-statuses"><Badge tone="success">Готов</Badge><Badge tone="warning">Требует внимания</Badge><Badge tone="danger">Недоступен</Badge><span className="socket-status"><MaterialIcon name="settings" size={16} />СОКЕТ: ПОДКЛЮЧЕН</span><Switch label="Расширенные настройки" checked={advanced} onChange={(event) => setAdvanced(event.target.checked)} /></div>
    </Pattern>

    <Pattern id="modal-form" title="Форма в модальном окне" description="Короткие локальные операции используют стандартный Modal; длинные сценарии открываются отдельной страницей.">
      <Button variant="primary" onClick={() => setModalOpen(true)}>Открыть пример</Button>
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Создать пространство" footer={<><Button variant="secondary" onClick={() => setModalOpen(false)}>Отмена</Button><Button variant="primary" onClick={() => setModalOpen(false)}>Создать</Button></>}><div className="form-stack"><TextField label="Название пространства" placeholder="Например, Аналитика витрины" /><Alert tone="info" title="Область действия">Пространство объединяет связанные бенчмарки.</Alert></div></Modal>
    </Pattern>
  </section>;
}
