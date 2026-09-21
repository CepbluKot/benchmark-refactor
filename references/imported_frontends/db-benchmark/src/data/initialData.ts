import {
  Workspace,
  DataSource,
  StrategyTemplate,
  Benchmark,
  Run,
} from '../types';

export const INITIAL_WORKSPACES: Workspace[] = [
  {
    id: 'ws-sales',
    name: 'Аналитика продаж',
    description: 'Бенчмарки таблиц заказов, чеков и клиентских событий витрин e-commerce',
    createdAt: '2026-09-01 10:00',
  },
  {
    id: 'ws-logs',
    name: 'Логи веб-сервисов',
    description: 'Эксперименты над структурой логов ingress, nginx и API шлюзов',
    createdAt: '2026-09-05 14:30',
  },
];

export const INITIAL_DATA_SOURCES: DataSource[] = [
  {
    id: 'src-ch-analytics',
    name: 'ch-cluster-analytics.internal',
    type: 'ClickHouse',
    host: 'clickhouse-analytics-01.corp.internal',
    port: 8123,
    login: 'db_benchmark_ro',
    secretRef: 'vault://secrets/infra/clickhouse/analytics-ro-key',
    status: 'ready',
    lastCheckedAt: '2026-09-18 11:20:15',
    availableDatabases: [
      {
        database: 'analytics',
        tables: ['analytics.events_v2', 'analytics.daily_active_users', 'analytics.funnel_steps'],
      },
      {
        database: 'sales',
        tables: ['sales.order_transactions', 'sales.cart_items', 'sales.payment_attempts'],
      },
      {
        database: 'warehouse',
        tables: ['warehouse.stock_snapshots', 'warehouse.supplies_log'],
      },
    ],
  },
  {
    id: 'src-ch-logs',
    name: 'ch-prod-telemetry.corp',
    type: 'ClickHouse',
    host: 'ch-telemetry-node.prod.gpb.cloud',
    port: 9000,
    login: 'bench_agent',
    secretRef: 'vault://secrets/prod/telemetry-token',
    status: 'not_checked',
    lastCheckedAt: undefined,
    availableDatabases: [
      {
        database: 'telemetry',
        tables: ['telemetry.http_requests_log', 'telemetry.app_traces', 'telemetry.audit_trail'],
      },
      {
        database: 'sandbox_benchmarks',
        tables: ['sandbox_benchmarks.candidate_events_v2_bench'],
      },
    ],
  },
  {
    id: 'src-ch-legacy',
    name: 'ch-archive-storage-dmz',
    type: 'ClickHouse',
    host: 'ch-archive-dmz.backup.internal',
    port: 8123,
    login: 'archive_reader',
    secretRef: 'vault://secrets/backup/ch-archive-secret',
    status: 'unavailable',
    lastCheckedAt: '2026-09-17 19:40:02',
    availableDatabases: [],
  },
];

export const INITIAL_STRATEGY_TEMPLATES: StrategyTemplate[] = [
  {
    id: 'strat-phased',
    name: 'Поэтапный подбор структуры',
    technicalType: 'sequential_phased_topn_strategy',
    phases: [
      'Типы колонок',
      'Кодеки сжатия (ZSTD, DoubleDelta, T64)',
      'Ключ сортировки (ORDER BY)',
      'Skip-индексы (minmax, set, bloom_filter)',
      'Финальная верификация',
    ],
    description:
      'Комплексный последовательный проход: оптимизация типов данных, затем выбор кодеков, ключа сортировки и построение гранулярных skip-индексов.',
    isBuiltin: true,
  },
  {
    id: 'strat-types',
    name: 'Подбор типов колонок',
    technicalType: 'types_strategy',
    phases: [
      'Анализ диапазонов числовых значений',
      'Оценка кардинальности и перевод в LowCardinality(String)',
      'Подбор минимальных размерностей Int8/Int16/Int32/Int64',
      'Контроль риска переполнения данных',
    ],
    description:
      'Сфокусированный подбор оптимальных представлений столбцов и словарного сжатия LowCardinality для снижения расхода RAM и ускорения чтения.',
    isBuiltin: true,
  },
  {
    id: 'strat-indexes',
    name: 'Подбор skip-индексов',
    technicalType: 'indexes_strategy',
    phases: [
      'Профилирование селективности предикатов WHERE',
      'Генерация minmax индексов для монотонных полей',
      'Генерация set и bloom_filter индексов для точечных поисков',
      'Оценка оверхеда на запись и размер диска',
    ],
    description:
      'Эксперименты с вторичными пропускающими индексами ClickHouse (minmax, set, bloom_filter) для исключения нерелевантных гранул данных.',
    isBuiltin: true,
  },
  {
    id: 'strat-orderby',
    name: 'Подбор порядка сортировки',
    technicalType: 'sequential_topn_strategy',
    phases: [
      'Анализ кардинальности колонок в предикатах запросов',
      'Перебор перестановок кортежа ORDER BY',
      'Замер сканируемых гранул данных (Granules skipped)',
      'Сравнение коэффициента компрессии строк',
    ],
    description:
      'Поиск оптимального первичного ключа и порядка сортировки таблицы MergeTree для максимального отсечения данных при сканировании.',
    isBuiltin: true,
  },
];

export const INITIAL_BENCHMARKS: Benchmark[] = [
  {
    id: 'bench-events-v2',
    workspaceId: 'ws-sales',
    name: 'Оптимизация таблицы событий витрины',
    sourceId: 'src-ch-analytics',
    sourceTable: 'analytics.events_v2',
    sandboxDatabase: 'sandbox_benchmarks',
    strategyTemplateId: 'strat-phased',
    strategyName: 'Поэтапный подбор структуры',
    readinessStatus: 'ready',
    createdAt: '2026-09-10 12:00',
    updatedAt: '2026-09-15 15:30',
    lastRunId: 'run-1082',
    lastRunStatus: 'completed',
    lastRunDate: '2026-09-18 09:14',
    rulesConfig: {
      allowedTypes: ['LowCardinality(String)', 'UInt32', 'Int64', 'DateTime64(3)'],
      allowedCodecs: ['ZSTD(1)', 'ZSTD(3)', 'DoubleDelta', 'T64', 'LZ4HC'],
      allowedOrderBy: ['event_type', 'user_id', 'created_at'],
      allowedSkipIndexes: ['minmax', 'bloom_filter(0.01)'],
      indexGranularity: 8192,
    },
    workloadConfig: {
      queriesCount: 5,
      timeBudgetMinutes: 30,
      maxCandidates: 10,
      evaluationTarget: 'balanced',
    },
  },
  {
    id: 'bench-orders-stream',
    workspaceId: 'ws-sales',
    name: 'Сжатие и индексы заказов продаж',
    sourceId: 'src-ch-analytics',
    sourceTable: 'sales.order_transactions',
    sandboxDatabase: 'sandbox_benchmarks',
    strategyTemplateId: 'strat-indexes',
    strategyName: 'Подбор skip-индексов',
    readinessStatus: 'ready',
    createdAt: '2026-09-12 16:40',
    updatedAt: '2026-09-17 11:10',
    lastRunId: 'run-1083',
    lastRunStatus: 'running',
    lastRunDate: '2026-09-18 11:45',
    rulesConfig: {
      allowedSkipIndexes: ['minmax', 'set(100)', 'bloom_filter(0.02)'],
      indexGranularity: 8192,
    },
    workloadConfig: {
      queriesCount: 4,
      timeBudgetMinutes: 20,
      maxCandidates: 6,
      evaluationTarget: 'query_speed',
    },
  },
  {
    id: 'bench-raw-telemetry',
    workspaceId: 'ws-logs',
    name: 'Аудит ingest-таблицы HTTP запросов',
    sourceId: 'src-ch-logs',
    sourceTable: 'telemetry.http_requests_log',
    sandboxDatabase: 'sandbox_benchmarks',
    strategyTemplateId: 'strat-orderby',
    strategyName: 'Подбор порядка сортировки',
    readinessStatus: 'source_not_verified',
    createdAt: '2026-09-14 09:10',
    updatedAt: '2026-09-14 09:10',
    lastRunId: undefined,
    lastRunStatus: undefined,
    lastRunDate: undefined,
  },
  {
    id: 'bench-cart-items',
    workspaceId: 'ws-sales',
    name: 'Словарь LowCardinality корзины покупателей',
    sourceId: 'src-ch-analytics',
    sourceTable: 'sales.cart_items',
    sandboxDatabase: 'sandbox_benchmarks',
    strategyTemplateId: 'strat-types',
    strategyName: 'Подбор типов колонок',
    readinessStatus: 'ready',
    createdAt: '2026-09-16 17:05',
    updatedAt: '2026-09-16 17:05',
    lastRunId: 'run-1079',
    lastRunStatus: 'error',
    lastRunDate: '2026-09-17 18:22',
  },
];

export const INITIAL_RUNS: Run[] = [
  {
    id: 'run-1083',
    benchmarkId: 'bench-orders-stream',
    benchmarkName: 'Сжатие и индексы заказов продаж',
    workspaceId: 'ws-sales',
    startedAt: '2026-09-18 11:45:02',
    status: 'running',
    currentPhase: 'Копирование данных в sandbox',
    sourceRows: 852400,
    copyRows: 383580,
    progressPercent: 45, // Fixed representation according to section 10
    sandboxTableCreated: 'sandbox_benchmarks.candidate_order_transactions_bench',
    logs: [
      {
        timestamp: '11:45:02.102',
        level: 'INFO',
        message: 'Инициализирован запуск бенчмарка bench-orders-stream (ClickHouse)',
      },
      {
        timestamp: '11:45:02.845',
        level: 'INFO',
        message: 'Проверка подключения к источнику: ch-cluster-analytics.internal — OK',
      },
      {
        timestamp: '11:45:03.119',
        level: 'INFO',
        message: 'Получена DDL структура исходной таблицы sales.order_transactions',
      },
      {
        timestamp: '11:45:04.550',
        level: 'INFO',
        message: 'Подсчёт исходного числа строк: 852,400 строк обнаружено',
      },
      {
        timestamp: '11:45:05.200',
        level: 'INFO',
        message:
          'Создание sandbox-копии таблицы sandbox_benchmarks.candidate_order_transactions_bench',
      },
      {
        timestamp: '11:45:08.410',
        level: 'INFO',
        message:
          'INSERT INTO sandbox_benchmarks.candidate_order_transactions_bench SELECT * FROM sales.order_transactions...',
      },
    ],
  },
  {
    id: 'run-1082',
    benchmarkId: 'bench-events-v2',
    benchmarkName: 'Оптимизация таблицы событий витрины',
    workspaceId: 'ws-sales',
    startedAt: '2026-09-18 09:14:10',
    finishedAt: '2026-09-18 09:16:35',
    status: 'completed',
    currentPhase: 'Завершён',
    sourceRows: 1420500,
    copyRows: 1420500,
    progressPercent: 100,
    sandboxTableCreated: 'sandbox_benchmarks.candidate_events_v2_bench',
    logs: [
      {
        timestamp: '09:14:10.012',
        level: 'INFO',
        message: 'Запуск bench-events-v2. Подключение к источнику ch-cluster-analytics.internal',
      },
      {
        timestamp: '09:14:11.230',
        level: 'INFO',
        message: 'Проверка прав на sandbox-базу sandbox_benchmarks: доступ на запись подтверждён',
      },
      {
        timestamp: '09:14:12.600',
        level: 'INFO',
        message: 'Исходная таблица: analytics.events_v2 (Engine = MergeTree)',
      },
      {
        timestamp: '09:14:13.910',
        level: 'INFO',
        message: 'Строк в источнике: 1,420,500',
      },
      {
        timestamp: '09:14:14.500',
        level: 'INFO',
        message: 'Создана копия таблицы sandbox_benchmarks.candidate_events_v2_bench',
      },
      {
        timestamp: '09:15:58.210',
        level: 'INFO',
        message: 'Перенос данных завершён. Подсчёт строк в созданной копии...',
      },
      {
        timestamp: '09:16:34.900',
        level: 'INFO',
        message: 'Строк в копии: 1,420,500. Сохранение результатов запуска.',
      },
      {
        timestamp: '09:16:35.105',
        level: 'INFO',
        message: 'Операция физического копирования и подсчета строк успешно завершена.',
      },
    ],
  },
  {
    id: 'run-1079',
    benchmarkId: 'bench-cart-items',
    benchmarkName: 'Словарь LowCardinality корзины покупателей',
    workspaceId: 'ws-sales',
    startedAt: '2026-09-17 18:22:04',
    finishedAt: '2026-09-17 18:22:31',
    status: 'error',
    currentPhase: 'Ошибка',
    sourceRows: 319200,
    copyRows: 0,
    progressPercent: 100,
    sandboxTableCreated: 'sandbox_benchmarks.candidate_cart_items_bench',
    errorMessage:
      'Code: 497. DB::Exception: User bench_agent is not allowed to CREATE TABLE in database sandbox_benchmarks. ACCESS_DENIED.',
    logs: [
      {
        timestamp: '18:22:04.300',
        level: 'INFO',
        message: 'Старт бенчмарка bench-cart-items',
      },
      {
        timestamp: '18:22:05.110',
        level: 'INFO',
        message: 'Подсчитано строк в sales.cart_items: 319,200',
      },
      {
        timestamp: '18:22:07.450',
        level: 'ERROR',
        message: 'Сбой выполнения CREATE TABLE в sandbox_benchmarks: недостаточно прав (ACCESS_DENIED)',
        details:
          'ClickHouse server response: DB::Exception: User bench_agent is not allowed to execute CREATE TABLE on database `sandbox_benchmarks`. Check server permissions.',
      },
    ],
  },
];
