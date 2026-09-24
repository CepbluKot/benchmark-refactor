import { useState } from 'react';
import type { ReactNode } from 'react';
import { Alert, Badge, Button, Modal, SelectField, Switch, TextField } from '@adqm/gpb-ui';
import { ActionIcon } from './ActionIcon';
import { MonitoringTable, type MonitoringTableColumn } from './MonitoringTable';
import { WorkspaceAvatarPicker } from './WorkspaceAvatarPicker';
import { WorkspaceIcon } from './WorkspaceIcon';
import { MaterialIcon } from './MaterialIcon';
import type { WorkspaceIcon as WorkspaceIconName } from './workspaceIcons';
import { useI18n } from '../i18n';

interface CatalogueRow { id: string; name: string; method: string; status: string }

function Pattern({ id, title, description, children }: { id: string; title: string; description: string; children: ReactNode }): JSX.Element {
  return <section id={`pattern-${id}`} className="product-pattern"><header><span>PRODUCT PATTERN</span><h2>{title}</h2><p>{description}</p></header><div className="product-pattern-stage">{children}</div></section>;
}

export function ProductPatternsGallery(): JSX.Element {
  const { t } = useI18n();
  const [workspaceIcon, setWorkspaceIcon] = useState<WorkspaceIconName>('target');
  const [advanced, setAdvanced] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const catalogueRows: CatalogueRow[] = [{ id: 'example', name: t('Оптимизация событий', 'Event optimization'), method: t('Последовательный Top-N', 'Sequential Top-N'), status: t('Готов', 'Ready') }];
  const catalogueColumns: MonitoringTableColumn<CatalogueRow>[] = [
    { key: 'name', label: t('Название', 'Name'), render: (row) => <strong>{row.name}</strong> },
    { key: 'method', label: t('Метод', 'Method'), render: (row) => row.method },
    { key: 'status', label: t('Состояние', 'Status'), render: (row) => <Badge tone="success">{row.status}</Badge> },
    { key: 'actions', label: '', render: (row) => <div className="table-actions"><Button variant="secondary" aria-label={`${t('Настроить', 'Configure')}: ${row.name}`}><ActionIcon name="configure" />{t('Настроить', 'Configure')}</Button><Button variant="secondary" aria-label={`${t('Изменить', 'Edit')}: ${row.name}`}><ActionIcon name="edit" />{t('Изменить', 'Edit')}</Button></div> },
  ];
  return <section className="product-patterns" aria-labelledby="product-patterns-title">
    <header className="product-patterns-heading"><span>DB BENCHMARK / PRODUCT UI</span><h1 id="product-patterns-title">{t('Продуктовые паттерны', 'Product patterns')}</h1><p>{t('Элементы, которые используются на рабочих страницах поверх базовых компонентов ADQM.', 'Patterns used on product pages on top of ADQM base components.')}</p></header>
    <Pattern id="navigation-header" title={t('Навигация и шапка', 'Navigation and header')} description={t('Состояния основной навигации, выбора пространства и подключения к потоку событий.', 'States for primary navigation, workspace selection, and event-stream connection.')}>
      <div className="pattern-shell-preview"><aside className="pattern-nav-preview"><div className="product-logo"><span><WorkspaceIcon /></span><strong>DB Benchmark</strong></div><Button variant="primary"><MaterialIcon name="strategy" />{t('Стратегии поиска', 'Search strategies')}</Button><Button variant="secondary"><MaterialIcon name="benchmark" />{t('Бенчмарки', 'Benchmarks')}</Button></aside><div className="pattern-header-preview"><Button variant="secondary">{t('ТЕКУЩЕЕ ПРОСТРАНСТВО · Аналитика', 'CURRENT WORKSPACE · Analytics')}</Button><span className="socket-status" role="status"><MaterialIcon name="settings" size={16} />{t('SOCKET: ПОДКЛЮЧЕН', 'SOCKET: CONNECTED')}</span></div></div>
    </Pattern>
    <Pattern id="monitoring-table" title={t('Таблица мониторинга', 'Monitoring table')} description={t('Единый контейнер таблицы с фильтрами, поиском, статусами и действиями строки.', 'A unified table container with filters, search, statuses, and row actions.')}>
      <MonitoringTable rows={catalogueRows} columns={catalogueColumns} rowKey={(row) => row.id} title={t('Стратегии поиска', 'Search strategies')} description={t('Пример рабочего списка', 'Working-list example')} searchText={(row) => `${row.name} ${row.method}`} filters={<SelectField label={t('Метод поиска', 'Search method')} value="all" options={[{ value: 'all', label: t('Все методы', 'All methods') }]} onChange={() => undefined} />} />
    </Pattern>
    <Pattern id="source-card" title={t('Карточка источника', 'Source card')} description={t('Компактное представление подключения с типом, адресом, статусом и действиями.', 'A compact connection representation with type, address, status, and actions.')}>
      <ul className="source-list pattern-source-list"><li className="source-card"><div className="source-card-icon"><WorkspaceIcon icon="data" /></div><div className="source-card-info"><h2>{t('Локальный ClickHouse', 'Local ClickHouse')}</h2><div className="source-card-meta"><span>ClickHouse</span><span>·</span><span className="mono">clickhouse:8123</span></div></div><div className="source-card-actions"><Badge tone="success"><span className="status-badge">{t('Готов', 'Ready')}</span></Badge><div className="source-card-action-buttons"><Button variant="secondary" className="source-card-action"><ActionIcon name="edit" />{t('Изменить', 'Edit')}</Button><Button variant="secondary" className="source-card-action source-card-action-danger"><ActionIcon name="delete" />{t('Удалить', 'Delete')}</Button></div></div></li></ul>
    </Pattern>
    <Pattern id="wizard-stepper" title={t('Пошаговый сценарий', 'Step-by-step flow')} description={t('Навигация по длинной форме с одним активным этапом и явным прогрессом.', 'Navigation through a long form with one active step and clear progress.')}>
      <nav className="strategy-stepper pattern-stepper" aria-label={t('Пример этапов', 'Step example')}><Button variant="secondary"><span><MaterialIcon name="check" size={16} /></span>{t('Основное', 'Basics')}</Button><Button variant="primary"><span>2</span>{t('Метод поиска', 'Search method')}</Button><Button variant="secondary" disabled><span>3</span>{t('Правила вариантов', 'Variant rules')}</Button><Button variant="secondary" disabled><span>4</span>{t('Бюджет поиска', 'Search budget')}</Button></nav>
    </Pattern>
    <Pattern id="choice-card" title={t('Карточки выбора', 'Choice cards')} description={t('Крупный одиночный выбор с названием и пояснением — для методов и приоритетов.', 'Large single-choice cards with a name and explanation for methods and priorities.')}>
      <div className="strategy-choice-grid"><Button variant="primary" aria-pressed="true"><strong>{t('Последовательный Top-N', 'Sequential Top-N')}</strong><small>{t('После каждого направления оставляет только Top-N лучших вариантов.', 'Keeps only the Top-N best candidates after each dimension.')}</small></Button><Button variant="secondary" aria-pressed="false"><strong>{t('Комбинированный поиск', 'Combined search')}</strong><small>{t('Сравнивает все сочетания типов, кодеков и индексов.', 'Compares all combinations of types, codecs, and indexes.')}</small></Button></div>
    </Pattern>
    <Pattern id="pipeline-preview" title={t('Предпросмотр этапов', 'Stage preview')} description={t('Короткая читаемая последовательность, производная от выбранного метода.', 'A short readable sequence derived from the selected method.')}>
      <div className="strategy-pipeline"><strong>{t('Этапы поиска', 'Search stages')}</strong><div><span>ORDER BY</span><span>→ {t('Типы', 'Types')}</span><span>→ {t('Кодеки', 'Codecs')}</span><span>→ {t('Индексы', 'Indexes')}</span><span>→ {t('Финальная проверка', 'Final validation')}</span></div></div>
    </Pattern>
    <Pattern id="summary-panel" title={t('Закреплённое резюме', 'Pinned summary')} description={t('Ключевые решения формы остаются видимыми без отдельного шага проверки.', 'Key form decisions remain visible without a separate review step.')}>
      <aside className="strategy-summary pattern-summary"><span>{t('Шаблон', 'Template')}</span><strong>{t('Оптимизация событий', 'Event optimization')}</strong><dl><dt>{t('Метод', 'Method')}</dt><dd>{t('Последовательный Top-N', 'Sequential Top-N')}</dd><dt>{t('Кандидатов', 'Candidates')}</dt><dd>100</dd><dt>{t('Top-N на шаг', 'Top-N per step')}</dt><dd>10</dd><dt>{t('Приоритет', 'Priority')}</dt><dd>{t('Сбалансированно', 'Balanced')}</dd></dl></aside>
    </Pattern>
    <Pattern id="workspace-picker" title={t('Выбор иконки пространства', 'Workspace icon selection')} description={t('Фирменный аватар и раскрывающаяся палитра допустимых иконок.', 'A branded avatar and an expandable palette of allowed icons.')}>
      <div className="pattern-inline"><WorkspaceAvatarPicker value={workspaceIcon} onChange={setWorkspaceIcon} disabled={false} /><span>{t('Выбранная иконка пространства', 'Selected workspace icon')}</span></div>
    </Pattern>
    <Pattern id="status-indicators" title={t('Статусы и переключатели', 'Statuses and switches')} description={t('Текст всегда дополняет цвет; расширенные параметры раскрываются явно.', 'Text always complements color; advanced settings are explicitly revealed.')}>
      <div className="pattern-statuses"><Badge tone="success">{t('Готов', 'Ready')}</Badge><Badge tone="warning">{t('Требует внимания', 'Needs attention')}</Badge><Badge tone="danger">{t('Недоступен', 'Unavailable')}</Badge><span className="socket-status"><MaterialIcon name="settings" size={16} />{t('SOCKET: ПОДКЛЮЧЕН', 'SOCKET: CONNECTED')}</span><Switch label={t('Расширенные настройки', 'Advanced settings')} checked={advanced} onChange={(event) => setAdvanced(event.target.checked)} /></div>
    </Pattern>
    <Pattern id="modal-form" title={t('Форма в модальном окне', 'Modal form')} description={t('Короткие локальные операции используют стандартный Modal; длинные сценарии открываются отдельной страницей.', 'Short local operations use the standard Modal; long flows open on a dedicated page.')}>
      <Button variant="primary" onClick={() => setModalOpen(true)}>{t('Открыть пример', 'Open example')}</Button>
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={t('Создать пространство', 'Create workspace')} footer={<><Button variant="secondary" onClick={() => setModalOpen(false)}>{t('Отмена', 'Cancel')}</Button><Button variant="primary" onClick={() => setModalOpen(false)}>{t('Создать', 'Create')}</Button></>}><div className="form-stack"><TextField label={t('Название пространства', 'Workspace name')} placeholder={t('Например, Аналитика витрины', 'For example, Storefront analytics')} /><Alert tone="info" title={t('Область действия', 'Scope')}>{t('Пространство объединяет связанные бенчмарки.', 'A workspace groups related benchmarks.')}</Alert></div></Modal>
    </Pattern>
  </section>;
}
