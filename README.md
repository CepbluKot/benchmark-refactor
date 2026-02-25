# DDL Benchmark Engine

Инструмент для автоматического DDL-бенчмарка: перебирает варианты схемы таблиц (типы, кодеки, индексы), запускает тестовые запросы и помогает выбрать лучший вариант по `score`.

`main.py` запускает production-пайплайн на ClickHouse + Celery:
metadata через fetcher, исполнение через Celery-задачи, результаты в ClickHouse store.
И ещё важно: runner теперь по умолчанию перед любой strategy сначала запускает baseline
на исходном DDL (`execute_source_benchmark`), а потом прокидывает этот baseline
во все variant jobs через `VariantJob.source_benchmark`.
В ClickHouse+Celery runtime baseline включает не только `SELECT`, но и `INSERT`-замеры:
воркер создаёт временную baseline-таблицу, копирует туда данные, снимает метрики,
и удаляет эту таблицу в `finally`.
Для `SELECT` также сохраняются отдельные per-query метрики (замеры/перцентили/speedup),
чтобы анализировать каждый запрос отдельно, а не только агрегат по всем запросам.

## Оглавление

- [Что это и кому полезно](#what)
- [Что подаём на вход и что получаем на выход](#io)
- [Алгоритм работы бенчмарка](#algorithm)
- [Слои системы (человеческим языком)](#layers)
- [Чек-лист перед первым запуском](#checklist)
- [Быстрый старт](#quick-start)
- [Как собрать конфиг под свой ClickHouse](#clickhouse-config)
- [Как запустить бенчмарк](#run)
- [Валидация JSON-конфигов](#validation)
- [Мини-справочник по полям JSON](#json-reference)
- [Частые ошибки](#faq)
- [Для разработчиков (технические детали)](#dev)

<a id="what"></a>
## Что это и кому полезно

Этот проект нужен, если вы хотите не “на глаз” выбирать DDL, а сравнивать варианты на реальных запросах.

Что делает:
1. Берёт ваши правила мутаций DDL (типы/кодеки/индексы).
2. Генерирует варианты схемы.
3. Гоняет одни и те же запросы на каждом варианте.
4. Сохраняет результаты и score.
5. Позволяет выбрать лучший вариант на основе замеров.

<a id="io"></a>
## Что подаём на вход и что получаем на выход

На вход:
1. Конфиги подключения к БД.
2. Какие БД/таблицы бенчмаркить.
3. Какие правила перебора применяем.
4. Какой режим перебора (`types`, `indexes`, `combined`, `sequential`).
5. Какие запросы запускать.
6. Как считать `score` (`scoring.mode=builtin` или `scoring.mode=expression`).

На выход:
1. `benchmark_run_id` одного запуска.
2. Результаты по каждому варианту (через result store).
3. Возможность взять топ-варианты по score.

<a id="algorithm"></a>
## Алгоритм работы бенчмарка

1. Загружается JSON-конфиг и валидируется.
2. Из настроек `databases`/`tables` строится список целевых таблиц.
3. Для каждой таблицы применяются global + table override.
4. Резолвятся правила из `rule_banks` и inline-правила.
5. Строится `TableBenchmarkPlan`.
6. Перед запуском strategy runner выполняет baseline исходного DDL
   (`SourceBenchmarkJob -> execute_source_benchmark`).
   В ClickHouse runtime это отдельный прогон в воркере:
   создаётся временная baseline-таблица в `test_database`
   (если не задана — в `${source_database}__benchmark_tmp`),
   снимаются baseline insert/select метрики, затем таблица удаляется.
7. Baseline-результат прикладывается к каждому `VariantJob`
   (поле `VariantJob.source_benchmark`).
8. Генерируются DDL-варианты и `VariantJob`.
9. Каждый variant job выполняется через `BenchmarkExecutionAdapter`.
10. `BenchmarkExecutionAdapter`/воркер считает `score` по `scoring` (встроенная формула или expression).
11. `BenchmarkExecutionAdapter`/воркер сохраняет результат в `BenchmarkResultStore`.

Если режим `sequential`:
1. Сначала гоняются варианты `types`.
2. По score выбираются top-N (`sequential_types_top_n_for_indexes`).
3. Только для top-N запускаются варианты `indexes`.

Лимиты вставки строк (`insert_rows_per_operation_limit`/`insert_rows_per_operation_limits`) применяются по приоритету:
1. `insert_rows_per_operation_limits[variant_meta.mode]`
2. `insert_rows_per_operation_limits[job.mode]`
3. `insert_rows_per_operation_limit`

Для baseline исходной схемы есть отдельный лимит:
1. `source_insert_rows_per_operation_limits[table_mode]` (если задан) — используется в `SourceBenchmarkJob`;
2. затем legacy `source_insert_rows_per_operation_limit` (если задан);
3. если не задано, baseline берёт fallback variant-лимитов (`insert_rows_per_operation_limits` -> `insert_rows_per_operation_limit`).

Лимиты числа вариантов:
1. `max_benchmarks_limits[types]` — максимум type/codec-вариантов.
2. `max_benchmarks_limits[indexes]` — максимум index-вариантов.
3. Затем legacy `max_type_benchmarks/max_index_benchmarks`.
4. Если не задано, используется legacy fallback `insert_operations_count`.

Как работают insert-итерации:
1. `insert_operations_count` — это количество insert-замеров (повторов), а не количество строк.
2. Каждый повтор добавляет в таблицу до `insert_rows_per_operation_limit` строк.
3. Таблица между повторами не очищается.
4. Поэтому итоговый размер таблицы после insert-этапа обычно растёт как
   `insert_operations_count * insert_rows_per_operation_limit` (если лимит задан).
5. Перцентили insert считаются по одному общему массиву замеров всех повторов
   (без усреднения “средних по итерациям”).

<a id="layers"></a>
## Слои системы (человеческим языком)

Ниже не “академическая архитектура”, а реальный путь данных от JSON до результата.

### Визуальная схема потока

```mermaid
flowchart LR
    A["JSON конфиги<br/>connections/rule_banks/benchmarks/celery"] --> B["models.py<br/>валидация полей"]
    B --> C["loader.py<br/>сборка BenchmarkRootConfig"]
    C --> D["BenchmarkPlanner<br/>selectors + merge override + rules"]
    D --> E["BenchmarkEngine<br/>TableBenchmarkPlan -> VariantJob"]
    E --> F["BenchmarkRunner<br/>выбор TableExecutionStrategy"]
    F --> G["BenchmarkExecutionAdapter<br/>реальный SQL запуск"]
    G --> H["BenchmarkResultStore<br/>worker-side save + top-N"]

    D -. metadata .-> M["MetadataProvider"]
    D -. rule resolving .-> R["resolver.py"]
    E -. variant generation .-> V["variant_generation/*<br/>+ combiner.py facade"]
    F -. run id .-> I["BenchmarkRunIdProvider"]
    H -. sequential top-N .-> F
```

### Слои по порядку

1. Контракт конфигов (`src/models.py`).
Что это:
Это «правила формы» для JSON. Здесь заранее описано, какие поля вообще разрешены и какие значения считаются корректными.
Зачем это нужно:
Чтобы поймать ошибки сразу на старте, а не посреди запуска бенчмарка.
Что приходит:
Сырые JSON-данные.
Что уходит:
Проверенные Python-объекты (`BenchmarkConfig`, `BenchmarkRootConfig` и т.д.).

2. Сборка root-конфига (`src/loader.py`, `validate_json_config.py`).
Что это:
Слой, который собирает конфиг из частей (`connections`, `rule_banks`, `benchmarks`, `celery`) в один общий объект.
Зачем это нужно:
Чтобы проект работал как с одним файлом, так и с несколькими файлами, и чтобы ссылки между секциями были валидны.
Что приходит:
JSON-секции или `benchmark.project.json`.
Что уходит:
Единый `BenchmarkRootConfig`, готовый к планированию.

3. Резолв правил (`src/resolver.py`).
Что это:
Логика, которая решает, какие именно правила применять к таблице: глобальные, локальные, из банка правил или inline.
Зачем это нужно:
Чтобы не было конфликтов и двусмысленности в правилах мутации DDL.
Что приходит:
`global_rules`, `table_rules`, `rule_bank`/`default_rule_banks`.
Что уходит:
`ResolvedRules` с итоговыми `column_rules`, `index_rules`, `column_order`.

4. Метаданные (`src/benchmark_runtime/contracts/metadata.py` + реализации).
Что это:
Абстракция над источником БД-метаданных.
Зачем это нужно:
Движок не привязывается к одному клиенту БД и может брать DDL/списки таблиц из разных реализаций.
Что приходит:
`connection_id`, `database`, `table`.
Что уходит:
Список БД/таблиц, исходный `TableDDL`, размеры колонок (если поддерживается).

5. Планирование таблиц (`TableSelector`, `BenchmarkPlanner` в `src/benchmark_engine.py`).
Что это:
Слой, который превращает «общие пожелания» из конфига в конкретные планы по каждой таблице.
Зачем это нужно:
Чтобы runner работал уже с точными, детерминированными задачами.
Что приходит:
`BenchmarkRootConfig` + metadata provider.
Что уходит:
Поток `TableBenchmarkPlan` (один план на одну таблицу).

6. Генерация DDL-вариантов (`src/variant_generation/*`, фасад `src/combiner.py`).
Что это:
Слой перебора схемы: создает версии таблицы с разными типами/кодеками/индексами.
Зачем это нужно:
Именно тут рождаются кандидаты, которые потом сравниваются по производительности.
Что приходит:
Исходный `TableDDL`, правила и внутренний `mode`.
Что уходит:
Пары `(variant_ddl, VariantMeta)` и оценка количества вариантов (`total_variants`).

7. Подготовка execution jobs (`BenchmarkEngine`).
Что это:
Преобразователь «DDL-вариантов» в конкретные задания на запуск.
Зачем это нужно:
Чтобы адаптеру исполнения передавать уже полностью готовый job.
Что приходит:
`TableBenchmarkPlan`, варианты DDL, query-настройки.
Что уходит:
`VariantJob` с SQL-запросами, именем variant-таблицы, `variant_database` и итоговым `insert_rows_per_operation_limit`.

8. Оркестрация выполнения (`BenchmarkRunner` + `TableExecutionStrategy`).
Что это:
Координатор всего запуска.
Зачем это нужно:
Он выбирает стратегию исполнения по `benchmark.strategy` и определяет порядок запуска вариантов.
Что приходит:
`TableBenchmarkPlan`.
Что уходит:
Вызовы в execution adapter.
Важно:
Перед любой table strategy runner сначала выполняет baseline исходного DDL
и только потом запускает variant jobs.
Один и тот же baseline-результат прокидывается во все variant jobs этой таблицы
(`VariantJob.source_benchmark`).
Для `sequential_topn_strategy` runner делает 2 этапа: сначала `types`, потом `indexes` только для top-N.
`result_store` в `BenchmarkRunner` теперь опционален, но для top-N стратегий обязателен
(`sequential_topn_strategy`).
Runner не пишет результаты в store. Сохранение выполняет execution backend (обычно Celery-воркер).
`sequential_topn_strategy` внутри себя ставит wait-барьер: ждёт, пока в store появятся все результаты type-stage,
и только потом выбирает top-N и запускает index-stage.
В ClickHouse Celery runtime невалидный variant payload или упавший variant-benchmark
не останавливает весь run: worker логирует skip и завершает задачу как обработанную,
поэтому progress-bar и batch-wait не зависают.

9. Фактическое выполнение SQL (`BenchmarkExecutionAdapter`).
Что это:
Точка, где реально выполняется SQL в БД.
Зачем это нужно:
Ядро не знает, как именно запускать SQL в вашем окружении; это инкапсулируется адаптером.
Что приходит:
`SourceBenchmarkJob` (для baseline исходного DDL) и `VariantJob` (для вариантов).
Что уходит:
`SourceBenchmarkResult` и `BenchmarkVariantResult` (score, `score_calculation_json` и typed-поля метрик).

10. Хранилище результатов (`BenchmarkResultStore`).
Что это:
Слой сохранения и чтения результатов.
Зачем это нужно:
Результаты не держатся «кучей» в памяти и доступны для отборов top-N.
Что приходит:
`VariantJob` + `BenchmarkVariantResult`.
Что уходит:
Сохраненные записи и выборки top type-вариантов.
Что именно сохраняется в `StoredBenchmarkResult`:
- run-метаданные: `benchmark_run_id`, `benchmark_started_at`, `benchmark_id`;
- идентификация таблицы: `source_db_name`, `source_table_name`, `variant_table`;
- параметры варианта: `variant_mode`, `variant_params`;
- `variant_params` теперь содержит всю параметризацию варианта
  (типы/кодеки/индексы/прочие параметры); `index_params` оставлен только как legacy nullable-колонка;
- DDL-снимки: `tested_table_ddl` (как минимум), при наличии `source_table_ddl`;
- размер таблицы: `tested_table_consumed_compressed_size_bytes_overall`
  (данные без индексов) и `tested_table_total_size_bytes_with_indexes`
  (данные + размеры skip-индексов);
- метрики combined-схемы (insert/select/compression/indexes) + `extra_json` для расширений;
- per-query select-метрики хранятся в основной таблице в JSON-полях
  `tested_table_select_metrics_by_query_json`,
  `source_table_select_metrics_by_query_json`,
  `tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json`
  как map `query_id -> metrics`;
- SQL-строки (`*_ddl`, `*_query`, query-поля внутри JSON-метрик) перед записью
  автоматически нормализуются в читабельный формат;
- итог: `score` и рядом `score_calculation_json` (как рассчитан score, с входными параметрами и финальным значением);
  для top-N DDL берется из `tested_table_ddl`.

11. Управление run-id (`BenchmarkRunIdProvider`).
Что это:
Источник идентификатора запуска бенчмарка.
Зачем это нужно:
Чтобы все результаты одного запуска имели общий `benchmark_run_id` и легко группировались.
Что приходит:
Сигнал нового запуска.
Что уходит:
Следующий корректный `benchmark_run_id`.

### Главное о границах ответственности

1. `variant_generation`/`combiner` только генерирует варианты, не исполняет их.
2. `BenchmarkRunner` управляет порядком исполнения и sequential top-N.
3. Контракты и реализации разделены: `contracts/` и `implementations/`.

<a id="checklist"></a>
## Чек-лист перед первым запуском

1. В `connections.json` есть нужный `connection_id`.
2. В `benchmarks.json` этот `connection_id` указан в каждом benchmark.
3. Если используете `rule_bank`, он реально существует в `rule_banks.json`.
4. Если `queries.mode = "manual"`, в `test_queries` есть хотя бы один запрос.
5. Конфиги проходят валидацию через `validate_json_config.py`.
6. Если запускаешь ClickHouse+Celery runtime, worker стартует с `-E` (`--events`).

<a id="quick-start"></a>
## Быстрый старт

### 1) Проверка окружения

```bash
./venv/bin/python -V
./venv/bin/python -m pytest -q
```

### 2) Валидация примерных конфигов

```bash
./venv/bin/python validate_json_config.py parts \
  --celery-path configs/celery.example.json \
  --connections-path configs/connections.example.json \
  --rule-banks-path configs/rule_banks.example.json \
  --benchmarks-path configs/benchmarks.example.json
```

### 3) Запуск demo

Сделай шаги из раздела [Как запустить бенчмарк](#run), вариант A.

<a id="clickhouse-config"></a>
## Как собрать конфиг под свой ClickHouse

Ниже минимальный, рабочий сценарий.

### Шаг 1. `connections.local.json`

```json
{
  "connections": [
    {
      "id": "prod_ch",
      "dbms": "clickhouse",
      "credential_type": "password",
      "host": "clickhouse.my-host.local",
      "port": 9000,
      "login": "bench_user",
      "password": "secret"
    }
  ]
}
```

### Шаг 2. `rule_banks.local.json`

Вариант 1 (самый быстрый): взять готовый baseline и не писать большой банк с нуля.

```json
{
  "rule_banks": {
    "baseline": {
      "column_rules": [
        {
          "by_type": "UInt64",
          "types": ["UInt64", "UInt32"],
          "codecs": ["CODEC(Delta(8), LZ4)", "CODEC(T64, ZSTD(1))"]
        }
      ],
      "index_rules": [
        {
          "by_type": "UInt64",
          "indexes": [
            {"type": "minmax", "granularity": 4},
            {"type": "bloom_filter(0.01)", "granularity": 2}
          ]
        }
      ]
    }
  },
  "default_rule_banks": {
    "clickhouse": "baseline"
  }
}
```

### Шаг 3. `benchmarks.local.json`

```json
{
  "benchmarks": [
    {
      "id": "bench_seq",
      "connection_id": "prod_ch",
      "strategy": "sequential_topn_strategy",
      "databases": ["analytics"],
      "tables": ["events"],
      "test_database": "benchmark_tmp",
      "insert_operations_count": 20,
      "sequential_types_top_n_for_indexes": 2,
      "max_benchmarks_limits": {
        "types": 40,
        "indexes": 60,
        "sequential": 50
      },
      "insert_rows_per_operation_limit": 1000000,
      "source_insert_rows_per_operation_limits": {
        "sequential": 600000
      },
      "insert_rows_per_operation_limits": {
        "types": 800000,
        "indexes": 300000,
        "sequential": 500000
      },
      "global_rules": {
        "rule_bank": "baseline"
      },
      "queries": {
        "mode": "manual",
        "test_queries": [
          {
            "query": "SELECT count() FROM {table}",
            "cache_mode": "warm",
            "select_operations_count": 3
          }
        ]
      }
    }
  ]
}
```

### Шаг 4. `celery.local.json`

```json
{
  "workers": 4,
  "threads_per_worker": 2
}
```

<a id="run"></a>
## Как запустить бенчмарк

### Вариант A. Через текущий `main.py` (env-mode)

1. Укажи пути в `encode_configs_base64.py`:
- `CELERY_JSON_PATH`
- `CONNECTIONS_JSON_PATH`
- `RULE_BANKS_JSON_PATH`
- `BENCHMARKS_JSON_PATH`

2. Сгенерируй `.env`:

```bash
./venv/bin/python encode_configs_base64.py | sed 's/^export //' > .env
```

При необходимости добавь в `.env` уровень логирования:

```bash
BENCH_LOG_LEVEL=INFO
```

Поддерживаются уровни: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
(или числовое значение уровня logging).

Если хочешь, чтобы все variant-таблицы по умолчанию создавались в одной тестовой БД,
добавь в `.env`:

```bash
BENCH_TEST_DATABASE=bench_tmp
```

Это fallback: если в конкретном benchmark уже задан `test_database` в JSON,
он имеет приоритет над `BENCH_TEST_DATABASE`.

Параметры result-store (опционально):

```bash
BENCH_RESULT_CONNECTION_ID=prod_ch
BENCH_RESULT_DATABASE=benchmark_results
BENCH_RESULT_TABLE=combined_benchmark_results
```

Если `BENCH_RESULT_CONNECTION_ID` не задан, берётся первый connection из конфига.

3. Запусти:

```bash
./venv/bin/python main.py
```

Важно: для этого режима должны быть доступны ClickHouse и Celery broker/backend.

### Вариант B. File-mode через project JSON

Создай `configs/benchmark.project.local.json`:

```json
{
  "connections_file": "connections.local.json",
  "rule_banks_file": "rule_banks.local.json",
  "benchmarks_file": "benchmarks.local.json",
  "celery": {
    "workers": 4,
    "threads_per_worker": 2
  }
}
```

Проверка:

```bash
./venv/bin/python validate_json_config.py project --path configs/benchmark.project.local.json
```

Использование в коде:

```python
from loader import load_config

config = load_config("configs/benchmark.project.local.json")
```

### Вариант C. Реальный запуск на своём ClickHouse

Есть встроенный runtime для ClickHouse + Celery:
1. `CeleryClickHouseExecutionAdapter` — отправляет benchmark jobs в Celery.
2. `ClickHouseBenchmarkResultStore` — читает/пишет результаты в ClickHouse (нужен top-N для sequential).
3. `TaskMonitorCelery` — progress bar по Celery events (используется адаптером автоматически; worker должен быть запущен с `-E`).
   Для стабильного вывода в логах используется `tqdm_loggable` (как в legacy).

Что важно:
1. Baseline исходного DDL (`execute_source_benchmark`) тоже выполняется в Celery.
2. Variant-результаты сохраняются в ClickHouse из Celery-воркера, не из launcher-процесса.
3. Для `sequential_topn_strategy` launcher ждёт завершения stage1/stage2 через monitor-hook,
   после чего делает top-N отбор.
4. Baseline-задача в воркере создаёт временную baseline-таблицу и удаляет её в `finally`.
   Если `test_database` не задана, используется fallback `${source_database}__benchmark_tmp`.
   Baseline select/warmup выполняются по baseline-копии, а не по оригинальной таблице.
5. Variant-задача всегда удаляет variant-таблицу в `finally`, даже при ошибке.
6. Для индексных вариантов insert-замеры выполняются с фильтром по индексируемым колонкам
   (legacy-совместимое поведение `tested_cols`).
7. Ошибочные замеры помечаются значениями `< 0` (обычно `-1`), чтобы их можно было легко фильтровать.
8. Для корректного progress/ожидания batch Celery worker обязательно запускай с `-E` (`--events`).
9. Insert-замеры собираются в единые массивы по всем `insert_operations_count` повторов,
   и перцентили считаются по этим единым массивам.

#### 1) Запусти Celery worker

```bash
export RABBITMQ_HOSTNAME='localhost'
export RABBITMQ_LOGIN='guest'
export RABBITMQ_PASSWORD='guest'
export RABBITMQ_PORT='5672'
export CELERY_WORKER_CONCURRENCY='4'
export CLICKHOUSE_MANAGER_MAX_CONCURRENT_STREAMS_PER_PROCESS='1'
export MAX_COPY_N_RETRIES='100'
export MAX_COPY_RETRY_SLEEP_SEC='10'
export MAX_COPY_RETRY_SLEEP_SEC_INCREMENT='2'
# export CLICKHOUSE_STREAM_SLOT_ACQUIRE_TIMEOUT_SEC='5'

# опционально можно переопределить готовыми URL
# export BENCH_CELERY_BROKER_URL='pyamqp://guest:guest@localhost:5672//'
# export BENCH_CELERY_BACKEND_URL='rpc://guest:guest@localhost:5672//'

./venv/bin/celery -A src.benchmark_runtime.implementations.clickhouse_celery.tasks worker -E --loglevel=INFO
```

#### 2) Launcher-код

```python
from src.loader import load_config
from src.benchmark_engine import (
    BenchmarkPlanner,
    BenchmarkEngine,
    BenchmarkRunner,
    FetcherMetadataProvider,
)
from src.fetcher import make_fetcher
from src.benchmark_runtime import (
    CeleryClickHouseExecutionAdapter,
    ClickHouseBenchmarkResultStore,
)

config = load_config("configs/benchmark.project.local.json")
connection = next(c for c in config.connections if c.id == "prod_ch")
fetcher = make_fetcher(connection)

provider = FetcherMetadataProvider(fetcher)
planner = BenchmarkPlanner(config=config, providers_by_connection_id={"prod_ch": provider})
engine = BenchmarkEngine(planner=planner)

result_store = ClickHouseBenchmarkResultStore(
    connection=connection,
    database="benchmark_results",
    table="combined_benchmark_results",
)

runner = BenchmarkRunner(
    engine=engine,
    execution_adapter=CeleryClickHouseExecutionAdapter(
        connections_by_id={c.id: c for c in config.connections},
        result_database="benchmark_results",
        result_table="combined_benchmark_results",
    ),
    result_store=result_store,
)
run_id = runner.run()
print(run_id)
```

Если нужен быстрый ориентир по архитектуре и flow, посмотри:
- `examples/example.py`
- `examples/example_sequential_topn.py`
- `synthetic_interface_playground.py` (синтетический отладочный playground с примерными реализациями интерфейсов)

<a id="validation"></a>
## Валидация JSON-конфигов

Утилита: `validate_json_config.py`.

### Проверить один файл

```bash
./venv/bin/python validate_json_config.py single --type celery --path configs/celery.example.json
./venv/bin/python validate_json_config.py single --type connections --path configs/connections.example.json
./venv/bin/python validate_json_config.py single --type rule_banks --path configs/rule_banks.example.json
./venv/bin/python validate_json_config.py single --type benchmarks --path configs/benchmarks.example.json
./venv/bin/python validate_json_config.py single --type project --path configs/benchmark.project.example.json
```

Поддерживаемые `--type`:
- `celery`
- `connections`
- `rule_banks`
- `benchmarks`
- `project`
- `root`

### Проверить все 4 секции сразу + ссылки

```bash
./venv/bin/python validate_json_config.py parts \
  --celery-path configs/celery.example.json \
  --connections-path configs/connections.example.json \
  --rule-banks-path configs/rule_banks.example.json \
  --benchmarks-path configs/benchmarks.example.json
```

Коды завершения:
- `0` — всё хорошо.
- `1` — ошибка валидации/JSON/ссылок.

### Проверить только scoring формулы

Утилита: `validate_scoring_formula.py`.

```bash
./venv/bin/python validate_scoring_formula.py --type benchmarks --path configs/benchmarks.example.json
./venv/bin/python validate_scoring_formula.py --type project --path configs/benchmark.project.example.json
./venv/bin/python validate_scoring_formula.py --type root --path /path/to/root.config.json
```

Опционально можно ограничить проверку конкретными benchmark id:

```bash
./venv/bin/python validate_scoring_formula.py \
  --type benchmarks \
  --path configs/benchmarks.example.json \
  --benchmark-id bench_a \
  --benchmark-id bench_b
```

Коды завершения:
- `0` — формулы валидны.
- `1` — есть ошибки формул или невалидный JSON.

<a id="json-reference"></a>
## Мини-справочник по полям JSON

Это короткая версия справочника.
Если нужен полный пример со всеми важными полями, смотри:
- `configs/benchmarks.full_fields.example.json`
- `configs/benchmark.project.sequential_topn.example.json`

### `celery.json`

- `workers` (`int > 0`, default `4`)
- `threads_per_worker` (`int > 0`, default `2`)

### `connections.json`

Корень:
- `connections`: список подключений.

Подключение:
- `id` (уникальный id)
- `dbms` (обычно `clickhouse`)
- `credential_type` (обычно `password`)
- `host`, `port`, `login`, `password`

### `rule_banks.json`

Корень:
- `rule_banks`: словарь банков правил
- `default_rule_banks`: дефолтный банк по DBMS

`rule_banks.<bank_id>`:
- `column_rules`
- `index_rules`
- `column_order`

`column_rules` (каждое правило) дополнительно поддерживает:
- `auto_generate_alternatives` (`bool`, default `false`) — включает legacy-автогенерацию type+codec альтернатив;
- `auto_compressions_datatype` (`string`, optional) — datatype-hint для выбора preprocessings при авто-генерации кодеков
  (если не задан, используется `by_type`).

Важно про `auto_generate_alternatives`:
- авто-генерация использует legacy-логику `generate_possible_new_datatypes(...)`
  и `generate_possible_compressions_w_preprocessings(...)`;
- сгенерированные codec-выражения автоматически нормализуются к формату `CODEC(...)`;
- ручные `types`/`codecs` не теряются: они объединяются с авто-сгенерированными значениями.

`index_rules` (каждое правило) дополнительно поддерживает:
- `auto_generate_indexes` (`bool`, default `false`) — включает автогенерацию skip-индексов по типу колонки;
- `auto_indexes_datatype` (`string`, optional) — datatype-hint для авто-генерации индексов
  (если не задан, используется `by_type`).
- `indexes[].index_granularity_values` (`int[]`, optional) — ограничения на
  `SETTINGS index_granularity` именно для этого индекс-варианта.

Важно про `auto_generate_indexes`:
- авто-генерация строится по типовым профилям (numeric/date/string/uuid/ipv/low-cardinality);
- ручные `indexes` не теряются: они объединяются с авто-сгенерированными значениями;
- дубли по паре `(type, granularity)` автоматически удаляются.
- `minmax` автоматически добавляется для range-типов:
  `Int8/16/32/64`, `Float32/64`, `Decimal*`, `Date/DateTime*`.
- `set(...)` и `bloom_filter(...)` в auto-режиме не добавляются:
  если они нужны, указывай их явно в `index_rules[].indexes`.

### `benchmarks.json`

Корень:
- `benchmarks`: список benchmark-конфигов.

Главные поля benchmark:
- `id`, `connection_id`, `strategy`
- `databases`, `tables`
- `test_database` (опционально: отдельная БД для временной baseline-таблицы и variant-таблиц)
- `global_rules`, `table_rules`
- `scoring`
- `insert_operations_count`, `sequential_types_top_n_for_indexes`
- `insert_rows_per_operation_limit`, `insert_rows_per_operation_limits`
- `source_insert_rows_per_operation_limit`, `source_insert_rows_per_operation_limits`
- `max_benchmarks_limits` (опциональные лимиты числа variant jobs по стадиям)
- `index_granularity_values` (опциональный перебор `SETTINGS index_granularity`)
- `queries`
- `column_rules_mode`, `index_rules_mode`

Коротко по новым полям:
- `insert_operations_count`: сколько раз повторить insert/select замер.
- `insert_operations_count`: сколько раз повторить insert-замер.
- `queries.test_queries[].select_operations_count`: сколько раз мерить конкретный select.
- `queries.test_queries[].cache_mode`: `warm` или `cold`.
- `queries.test_queries[].warmup_queries`: query-level прогревы (только для `warm`).
- `queries.test_queries[].query_id`: стабильный ID запроса (если не задан, будет авто-ID).
- SQL-шаблоны поддерживают плейсхолдеры `{table}` и `{benchmark_id}`.
- Глобальный `queries.warmup_queries` не поддерживается.
- `insert_rows_per_operation_limit`: лимит строк на одну insert-операцию.
- `insert_rows_per_operation_limits`: такие же лимиты, но отдельно по mode (`types/indexes/...`).
- `source_insert_rows_per_operation_limits`: baseline-лимит строк по mode (например, `sequential`).
- `source_insert_rows_per_operation_limit`: legacy fallback baseline-лимита.
- `sequential_types_top_n_for_indexes`: сколько лучших вариантов из stage `types` отдать в stage `indexes`.
- `max_benchmarks_limits`: лимиты количества variant jobs по mode (`types/indexes/...`).
- `index_granularity_values`: список значений для `SETTINGS index_granularity`.
  Для `indexes`/`combined`/sequential-index-stage участвует в декартовом произведении
  с вариантами skip-индексов.
  Если у конкретного `indexes[]` задан `index_granularity_values`, используется
  пересечение global-списка и per-index списка (без global — только per-index).
  Если в исходном DDL уже был `SETTINGS index_granularity`, он корректно заменяется:
  в итоговом variant-DDL ключ остаётся один (без конфликтующих дублей).
- `queries.test_queries[].cache_mode = cold`: перед каждым замером выполняется
  `SYSTEM DROP MARK CACHE` и `SYSTEM DROP UNCOMPRESSED CACHE`.
- `queries.test_queries[].cache_mode = warm`: перед серией замеров запроса выполняются
  query-level `warmup_queries`, затем делаются `select_operations_count` замеров.

Примечание: старые ключи (`max_iterations`, `sequential_top_n`, `insert_rows_limit`,
`source_insert_rows_limit`, `insert_rows_limits`, `max_type_benchmarks`,
`max_index_benchmarks`) пока поддерживаются как legacy-алиасы.

### `scoring`: как настроить формулу score

`scoring.mode`:
- `builtin` — стандартная формула runtime.
- `expression` — кастомное безопасное выражение на `simpleeval`.

Формула `builtin`:
- `insert_ratio = median(source_insert_ms) / median(tested_insert_ms)`
- `select_ratio = median(source_select_ms) / median(tested_select_ms)`
- `compression_ratio = source_size_bytes / tested_size_bytes`
- `score = (insert_ratio * select_ratio * compression_ratio) ** (1/3)`

Для `compression_ratio` используются полные размеры таблиц
`данные + skip-индексы` (`*_total_size_bytes_with_indexes`).

`scoring` поля:
- `mode`
- `expression` (обязательно при `mode=expression`)
- `on_error_score` (опционально: если expression упало, будет это значение; иначе `score=None`)

Для обратной совместимости `expression` можно передать также как
`score_expression` или `sql_expression` (алиасы валидации).

Примеры:

```json
{
  "scoring": {
    "mode": "builtin"
  }
}
```

```json
{
  "scoring": {
    "mode": "expression",
    "expression": "pow(safe_div(medians.source_insert_time_ms, medians.tested_insert_time_ms, 1.0) * safe_div(medians.source_select_time_ms, medians.tested_select_time_ms, 1.0) * safe_div(source_size_bytes, tested_size_bytes, 1.0), 1 / 3)",
    "on_error_score": -1
  }
}
```

Готовая формула из ratio + геометрического среднего:
- `insert_ratio = median(source_insert_ms) / median(tested_insert_ms)`
- `select_ratio = median(source_select_ms) / median(tested_select_ms)`
- `compression_ratio = source_size_bytes / tested_size_bytes`
- `score = (insert_ratio * select_ratio * compression_ratio)^(1/3)`

Что доступно внутри `expression`:
- `source` и `tested`:
  - `source.select.time_ms_percentiles`, `tested.insert.time_ms_percentiles`
  - `source.select.time_ms_by_percentile`, `tested.insert.time_ms_by_percentile`
  - также `rows_per_second_*`, `bytes_per_second_*`, `memory_usage_*`
- `speedup.insert.time_ms_percentiles`, `speedup.select.time_ms_percentiles`
- `compression_overall_coef`
- `medians`:
  - `medians.source_insert_time_ms`, `medians.tested_insert_time_ms`
  - `medians.source_select_time_ms`, `medians.tested_select_time_ms`
- `ratios`:
  - `ratios.insert`, `ratios.select`, `ratios.compression`
- `source_size_bytes`, `tested_size_bytes` (полный размер `данные + skip-индексы`)
- `per_query`:
  - `per_query.tested_by_query_id['q_id']`
  - `per_query.source_by_query_id['q_id']`
  - `per_query.speedup_by_query_id['q_id']`
- JSON-aliases (значения уже распарсены в map, ключ = `query_id`):
  - `tested_table_select_metrics_by_query_json['q_id']`
  - `source_table_select_metrics_by_query_json['q_id']`
  - `tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json['q_id']`
- flat aliases:
  - `source_select_time_ms_percentiles`, `tested_select_time_ms_percentiles`
  - `source_select_time_ms_by_percentile`, `tested_select_time_ms_by_percentile`
  - `source_insert_time_ms_percentiles`, `tested_insert_time_ms_percentiles`
  - `source_insert_time_ms_by_percentile`, `tested_insert_time_ms_by_percentile`
- `insert_time_speedup_percentiles`, `select_time_speedup_percentiles`
- `insert_time_speedup_by_percentile`, `select_time_speedup_by_percentile`

Для baseline run (бенчмарк исходного DDL) `source` и `tested` в expression-контексте
заполняются одинаковыми baseline-метриками, поэтому ratio-поля обычно равны `1.0`.

Как обращаться к перцентилям:
- По индексу массива: `source.select.time_ms_percentiles[1]`
  (индекс соответствует порядку `measured_percentiles`).
- По ключу перцентиля: `source_select_time_ms_by_percentile[100]`
  или `source_select_time_ms_by_percentile["p100"]`.

Доступные функции expression:
- `safe_div(a, b, default=0.0)`
- `pct(values_by_percentile, percentile, default=None)`
- `at(container, key, default=None)`
- `coalesce(...)`
- `clamp(value, low, high)`
- `median(values, default=0.0)`
- `abs`, `min`, `max`, `round`, `sqrt`, `log`, `ln`, `pow`

Разрешённые операторы expression:
- арифметика: `+`, `-`, `*`, `/`, `%`, `**`
- сравнения: `==`, `!=`, `>`, `>=`, `<`, `<=`
- унарные: `+x`, `-x`, `not x`
- группировка скобками: `( ... )`

Ограничения безопасности:
- произвольные вызовы/импорты (`__import__`, `eval`, `os.system` и т.п.) запрещены;
- доступны только whitelisted функции из списка выше;
- доступ к атрибутам вида `_...`/`__...` блокируется самим `simpleeval`.

Предзапусковая валидация:
- перед `runner.run()` выполняется проверка всех `scoring.expression` выбранных benchmark/table_rules;
- при ошибке печатается `WARNING` в лог;
- запуск бенчмарка останавливается до dispatch jobs.

Что пишется в колонку `score_calculation_json`:
- `mode` (`builtin`/`expression`);
- формула (`expression` или builtin-формула);
- входные параметры (контекст значений, из которых считался score);
- статус:
  `ok`, `empty`, `error`, `fallback_on_error`, `non_finite`, `fallback_non_finite`, `skipped`;
- итоговый `final_score`.

`table_rules[]` может локально переопределить:
- `test_database`
- `strategy`
- `rules`
- `queries`
- `scoring`
- `insert_operations_count`, `sequential_types_top_n_for_indexes`
- `insert_rows_per_operation_limit`, `insert_rows_per_operation_limits`
- `source_insert_rows_per_operation_limit`, `source_insert_rows_per_operation_limits`
- `max_benchmarks_limits`
- `index_granularity_values`

`strategy`:
- `types_strategy`
- `indexes_strategy`
- `combined_strategy`
- `sequential_topn_strategy`

`queries.mode`:
- `auto`
- `manual`
- `auto_with_manual`

### `benchmark.project.json`

- `connections_file`
- `rule_banks_file`
- ровно одно из:
  - `benchmarks` (inline),
  - `benchmarks_file`
- `celery`

<a id="faq"></a>
## Частые ошибки

1. `connection_id ... не найден в connections`.
Проверь совпадение `benchmarks[].connection_id` и `connections[].id`.

2. `rule_bank ... не найден в rule_banks`.
Проверь `global_rules.rule_bank` и `table_rules[].rules.rule_bank`.

3. `mode=manual требует хотя бы одного test_query`.
Добавь `queries.test_queries`.

4. JSON parse error (`Expecting value`, `Expecting property name`).
Обычно это лишняя запятая или комментарий в JSON.

5. В `sequential` нет этапа индексов.
Проверь, что есть `index_rules`, `sequential_types_top_n_for_indexes > 0`, и адаптер возвращает `score`.

6. Включён `global_bank_only`, но нет доступного bank.
Либо укажи `global_rules.rule_bank`, либо настрой `default_rule_banks` для своего DBMS.

7. Почему в таблице получилось больше строк, чем `insert_rows_per_operation_limit`.
Это ожидаемо: лимит применяется к одной insert-операции, а операций выполняется
`insert_operations_count`.

<a id="dev"></a>
## Для разработчиков (технические детали)

### Как это работает внутри

Если коротко, ядро построено как `planner -> engine -> runner`.

1. `loader` + `models` валидируют JSON и собирают `BenchmarkRootConfig`.
2. `BenchmarkPlanner` раскрывает селекторы БД/таблиц и строит `TableBenchmarkPlan`.
3. `BenchmarkEngine` на основе плана генерирует варианты DDL и превращает их в `VariantJob`.
4. `BenchmarkRunner` выполняет jobs через `BenchmarkExecutionAdapter`.
5. Сохранение результата делает execution backend/воркер в `BenchmarkResultStore`.

Где лежат runtime-контракты:
1. Интерфейсы: `src/benchmark_runtime/contracts/*`.
2. Реализации: `src/benchmark_runtime/implementations/*`.
3. In-memory реализации: `src/benchmark_runtime/implementations/inmemory/*`.
4. Runtime DTO (`VariantJob`, `TableBenchmarkPlan`, `BenchmarkVariantResult`) — `src/benchmark_runtime/types.py`.
5. Файлы `src/benchmark_runtime/execution.py`, `metadata.py`, `result_store.py`, `run_id.py`, `table_strategy.py` оставлены как совместимые re-export.

Почему это удобно:
1. Можно менять способ генерации вариантов отдельно от способа выполнения.
2. Можно подключать свой storage без изменений planner/engine.
3. Логику `sequential` можно развивать независимо от остальных режимов.

### Как расширять функционал

#### 1) Добавить новый режим генерации вариантов

1. Реализуйте `VariantGenerationStrategy` в `src/variant_generation/contracts/strategy.py`.
2. Зарегистрируйте стратегию через `register_variant_generation_strategy("my_mode", strategy)`.
3. Размещать built-in реализации удобно в `src/variant_generation/implementations/`.
4. Если новый mode должен приходить из JSON-стратегии, добавьте соответствующий ключ в `BenchmarkStrategy` и маппинг `STRATEGY_TO_MODE` в `src/models.py`.

#### 2) Добавить особую логику выполнения strategy

1. Реализуйте `TableExecutionStrategy`.
2. Подключите через `runner.register_table_execution_strategy("my_strategy", strategy)`.
3. Класс удобно размещать в `src/benchmark_runtime/implementations/table_strategy/`.

Это нужно, если режим выполняется не просто “прогнать все варианты подряд”, как в `sequential_topn_strategy`.

#### 3) Подключить реальный SQL-бенчмарк

1. Реализуйте `BenchmarkExecutionAdapter`.
2. Класс удобно размещать в `src/benchmark_runtime/implementations/`.
3. Готовая production-ориентированная реализация уже есть: `src/benchmark_runtime/implementations/clickhouse_celery/execution.py`.
3. Внутри `execute_source_benchmark(job)` обычно делаются:
   - создание временной baseline-таблицы (в `job.test_database`, иначе в `${source_database}__benchmark_tmp`);
   - построение DDL baseline-копии через `TableDDL` (DDL должен быть корректным);
   - baseline insert-прогон (source -> baseline copy) с метриками и лимитом `job.insert_rows_limit`
     (который берётся из `source_insert_rows_per_operation_limits[table_mode]`, затем из
     legacy `source_insert_rows_per_operation_limit`, если он задан в конфиге);
   - baseline select-прогон по baseline-копии;
   - расчёт baseline-метрик/score;
   - формирование `score_calculation_json` (с формулой, входными значениями и статусом);
   - очистка временной baseline-таблицы в `finally`;
   - возврат `SourceBenchmarkResult` (который потом попадёт в `VariantJob.source_benchmark`).
4. Внутри `execute_variant(job)` обычно делаются:
   - создание variant-таблицы;
   - `INSERT INTO ... SELECT ...` (с учётом `job.insert_rows_limit`, который соответствует
     `insert_rows_per_operation_limit` в конфиге);
   - warmup-запросы;
   - test-запросы;
   - расчёт как агрегированных select-метрик, так и per-query select-метрик;
   - расчёт итогового `score`;
   - формирование `score_calculation_json` (детальный трейc расчёта score);
   - сохранение результата в `BenchmarkResultStore` (обычно из Celery-воркера);
   - очистка временных таблиц.

#### 4) Подключить реальный источник метаданных

1. Используйте `MetadataProvider` интерфейс.
2. Для ClickHouse можно взять `FetcherMetadataProvider` + `make_fetcher(...)`.
3. Свои реализации удобно размещать в `src/benchmark_runtime/implementations/`.

#### 5) Подключить production-хранилище результатов

1. Реализуйте `BenchmarkResultStore`.
2. Обязательные методы:
   - `store_result(job, result)`;
   - `get_top_type_variants(...)` (критично для `sequential`).
3. Свои реализации удобно размещать в `src/benchmark_runtime/implementations/` (например, подпапка `db/`).

### В каком файле что искать

1. `src/models.py` — контракт JSON (все поля и валидации).
2. `src/loader.py` — сборка конфига и проверка ссылок между секциями.
3. `src/benchmark_engine.py` — planner/engine/runner (оркестрация).
4. `src/benchmark_runtime/contracts/` — все runtime интерфейсы.
5. `src/benchmark_runtime/implementations/inmemory/` — in-memory реализации (`result_store`, `run_id`).
6. `src/benchmark_runtime/implementations/noop/` — `NoopExecutionAdapter`.
7. `src/benchmark_runtime/implementations/fetcher/` — `FetcherMetadataProvider`.
8. `src/benchmark_runtime/implementations/clickhouse_celery/` — готовые ClickHouse+Celery реализации (`execution`, `result_store`, `tasks`, `progress`).
9. `src/benchmark_runtime/implementations/clickhouse_celery/scoring.py` — безопасный evaluator для `scoring.expression`.
10. `src/benchmark_runtime/implementations/run_id/` — `MaxIdBenchmarkRunIdProvider`.
11. `src/benchmark_runtime/implementations/table_strategy/` — built-in стратегии выполнения.
12. `src/benchmark_runtime/types.py` — runtime DTO для planner/engine/runner.
13. `src/variant_generation/contracts/` — контракт генерации вариантов.
14. `src/variant_generation/implementations/` — built-in стратегии генерации (`types/indexes/combined/sequential`).
15. `src/variant_generation/registry.py` — реестр стратегий генерации.
16. `src/combiner.py` — backward-compatible фасад над `variant_generation`.
17. `src/fetcher.py` — ClickHouse-fetcher.
18. `validate_json_config.py` — CLI-валидатор JSON по пути.
19. `validate_scoring_formula.py` — CLI-валидатор только scoring-формул.
20. `configs/*.example.json` — примеры конфигов.
21. `LLM_CONTEXT.md` — подробный технический контекст для LLM-агентов.

### Что проверить после изменений

```bash
# Полный тест-ран
./venv/bin/python -m pytest -q

# Тесты валидатора конфигов
./venv/bin/python -m pytest tests/test_validate_json_config.py -q

# Проверка JSON-синтаксиса конкретного файла
./venv/bin/python -m json.tool configs/benchmarks.example.json >/dev/null
```
