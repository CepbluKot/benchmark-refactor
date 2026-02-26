# LLM Context: DDL Benchmark Engine

Этот файл предназначен для LLM-агентов, которые будут менять проект.
Цель: быстро дать точный технический контекст, чтобы изменения были совместимыми и без регрессий.

## 1) Что делает проект

Проект реализует движок автоматического DDL-бенчмарка:

1. Берет исходные таблицы в БД.
2. Генерирует варианты DDL (типы, кодеки, индексы).
3. Выполняет тестовые SQL-запросы.
4. Получает `score` из execution-адаптера.
5. Сохраняет каждый результат в store.
6. Помогает выбрать лучший DDL-вариант.

Практический фокус сейчас на ClickHouse, но архитектура расширяемая через интерфейсы и стратегии.

## 2) Ключевой принцип: strategy-driven конфиг

Важно:

1. В JSON-конфиге бенчмарка пользователь указывает `strategy`, а не `mode`.
2. `mode` для комбинатора считается внутри planner через `STRATEGY_TO_MODE` (`src/models.py`).
3. Legacy fallback по `mode` в конфиге удален.

Текущие встроенные strategy-ключи:

1. `types_strategy`
2. `indexes_strategy`
3. `combined_strategy`
4. `sequential_topn_strategy`

Маппинг в `src/models.py`:

1. `types_strategy -> types`
2. `indexes_strategy -> indexes`
3. `combined_strategy -> combined`
4. `sequential_topn_strategy -> sequential`

## 3) Архитектура выполнения (planner -> engine -> runner)

Основной поток:

1. `BenchmarkPlanner` (`src/benchmark_engine.py`)
   - раскрывает selectors БД/таблиц;
   - применяет global + table override;
   - резолвит rules;
   - рассчитывает effective `strategy`, внутренний `mode`, лимиты и queries;
   - выдает `TableBenchmarkPlan`.

2. `BenchmarkEngine` (`src/benchmark_engine.py`)
   - читает исходный DDL через metadata provider;
   - строит query-plan;
   - генерирует DDL-варианты через combiner/variant_generation;
   - собирает `VariantJob`.

3. `BenchmarkRunner` (`src/benchmark_engine.py`)
   - до старта run выполняет предвалидацию всех `scoring.expression`
     (warning в лог + остановка запуска при ошибках формулы);
   - перед любой table strategy запускает baseline исходного DDL
     через `execution_adapter.execute_source_benchmark(...)`;
   - сохраняет baseline-контекст таблицы и прокидывает его в
     `VariantJob.source_benchmark` для всех variant jobs;
   - выбирает table execution strategy по `table_plan.strategy`;
   - вызывает execution adapter;
   - сам не сохраняет результат (сохраняет execution backend/воркер);
   - `result_store` опционален, но обязателен для стратегий с top-N чтением.

## 4) Runtime-контракты и реализации

### 4.1 Контракты

Лежат в `src/benchmark_runtime/contracts/`:

1. `execution.py` -> `BenchmarkExecutionAdapter`
2. `metadata.py` -> `MetadataProvider`
3. `result_store.py` -> `BenchmarkResultStore`
4. `run_id.py` -> `BenchmarkRunIdProvider`
5. `table_strategy.py` -> `TableExecutionStrategy`

Важно по execution adapter:
1. `execute_source_benchmark(job)` всегда вызывается runner-ом первым для каждой таблицы.
2. `execute_variant(job)` вызывается после baseline.
3. Runner валидирует identity baseline-результата (`benchmark_run_id`, `benchmark_id`, source-table).
4. Runner не пишет результаты в store.
5. Сохранение результата должно происходить внутри execution backend/воркера.
6. Опционально можно использовать `bind_result_store(result_store)` для in-process demo/test-реализаций.

### 4.2 Built-in реализации

Лежат в `src/benchmark_runtime/implementations/`:

1. `inmemory/`
   - `InMemoryBenchmarkResultStore`
   - `InMemoryBenchmarkRunIdProvider`
2. `noop/`
   - `NoopExecutionAdapter`
3. `fetcher/`
   - `FetcherMetadataProvider`
4. `run_id/`
   - `MaxIdBenchmarkRunIdProvider`
5. `table_strategy/`
   - `DefaultTableExecutionStrategy`
   - `TypesTableExecutionStrategy`
   - `IndexesTableExecutionStrategy`
   - `CombinedTableExecutionStrategy`
   - `SequentialTopNTableExecutionStrategy`
6. `clickhouse_celery/`
   - `CeleryClickHouseExecutionAdapter`
   - `ClickHouseBenchmarkResultStore`
   - worker tasks (`tasks.py`) для baseline/variant benchmark
   - `TaskMonitorCelery` для progress-bar и ожидания Celery batch
     (требует запуск worker с `-E` / `--events`)
     и использует `tqdm_loggable` (как в legacy) для корректного вывода в логах
   - `settings.py` (`BENCH_CELERY_BROKER_URL`, `BENCH_CELERY_BACKEND_URL`,
     `CELERY_WORKER_CONCURRENCY`, retry/stream-limit env)

### 4.3 Backward-compatible re-export

Сохранены совместимые import-path:

1. `src/benchmark_runtime/execution.py`
2. `src/benchmark_runtime/metadata.py`
3. `src/benchmark_runtime/result_store.py`
4. `src/benchmark_runtime/run_id.py`
5. `src/benchmark_runtime/table_strategy.py`

Также `src/benchmark_engine.py` ре-экспортит ключевые runtime-сущности, поэтому старые импорты `from benchmark_engine import ...` продолжают работать.

### 4.4 Runtime DTO

Лежат в `src/benchmark_runtime/types.py`:

1. `TableTarget`
2. `Query`
3. `QueryPlan`
4. `TableBenchmarkPlan`
5. `SourceBenchmarkJob`
6. `SourceBenchmarkResult`
7. `VariantJob`
8. `BenchmarkVariantResult`
9. `StoredBenchmarkResult`
10. `TopTypeVariant`

`VariantJob` содержит обе БД:
1. `source_database` — где лежит исходная таблица;
2. `variant_database` — где создаётся тестовая variant-таблица
   (если `test_database` не задан, равен `source_database`).
3. `source_benchmark` — baseline-результат исходного DDL для этой таблицы.

`SourceBenchmarkJob` также содержит:
1. `test_database` — БД для временной baseline-копии исходной таблицы
   (если не задана, baseline-копия создаётся в `${source_database}__benchmark_tmp`).
2. `scoring` — стратегия вычисления baseline score (`builtin`/`expression`).

`VariantJob` содержит:
1. `scoring` — стратегия вычисления variant score (`builtin`/`expression`), уже с учётом table-level override.

Ключевой формат хранения (`StoredBenchmarkResult`):

1. run-метаданные: `benchmark_run_id`, `benchmark_started_at`, `benchmark_id`.
2. таблица/вариант: `source_db_name`, `source_table_name`, `variant_table`, `variant_mode`.
3. параметры варианта: `variant_params` (нормализованный JSON-словарь из `VariantMeta`).
4. `index_params` оставлен как legacy nullable-колонка; новые данные параметров индексов/типов хранятся в `variant_params`.
5. DDL-снимки: `tested_table_ddl` (обязательный), `source_table_ddl` (опциональный).
6. метрики размера:
   - `tested_table_consumed_compressed_size_bytes_overall` (данные без индексов),
   - `tested_table_consumed_compressed_size_bytes_with_indexes` (данные + размеры skip-индексов).
7. extended combined-метрики: insert/select/compression/indexes поля + `extra_json`.
8. per-query select-метрики хранятся в основной таблице в JSON-полях
   `tested_table_select_metrics_by_query_json`,
   `source_table_select_metrics_by_query_json`,
   `tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json`
   в формате map `query_id -> metrics`.
9. legacy select-агрегаты удалены из ClickHouse-схемы результатов:
   `tested_table_select_time_ms_measurements`,
   `source_table_select_time_ms_measurements`,
   `tested_table_select_time_ms_measurements_percentiles`,
   `source_table_select_time_ms_measurements_percentiles`,
   `tested_table_select_time_ms_measurements_percentiles_speed_up_coefs`,
   `tested_table_select_rows_per_second_measurements`,
   `source_table_select_rows_per_second_measurements`,
   `tested_table_select_rows_per_second_measurements_percentiles`,
   `source_table_select_rows_per_second_measurements_percentiles`,
   `tested_table_select_bytes_per_second_measurements`,
   `tested_table_select_bytes_per_second_measurements_readable`,
   `source_table_select_bytes_per_second_measurements`,
   `source_table_select_bytes_per_second_measurements_readable`,
   `tested_table_select_bytes_per_second_measurements_percentiles`,
   `tested_table_select_bytes_per_second_measurements_percentiles_readable`,
   `source_table_select_bytes_per_second_measurements_percentiles`,
   `source_table_select_bytes_per_second_measurements_percentiles_readable`.
   `ClickHouseBenchmarkResultStore.ensure_schema()` делает `DROP COLUMN IF EXISTS`
   для этих колонок на уже существующей таблице.
10. SQL-значения перед сохранением форматируются:
   - scalar-поля `*_ddl`, `*_query`;
   - query-поля внутри JSON-метрик (`query`, `source_query`, `warmup_queries`).
11. итог: `score` и `score_calculation_json` (детали формулы/контекста/статуса расчёта);
   для top-N DDL восстанавливается из `tested_table_ddl`.

В `src/benchmark_runtime/types.py` есть helper `build_variant_params(...)`,
который собирает стабильные параметры текущего варианта из `VariantMeta`.

### 4.5 Детали clickhouse_celery runtime (важно не сломать)

Файл: `src/benchmark_runtime/implementations/clickhouse_celery/tasks.py`.

`run_source_benchmark(payload)`:
1. Вычисляет `baseline_database = payload.test_database or f"{payload.source_database}__benchmark_tmp"`.
2. Создаёт временную baseline-таблицу с именем `source_table__source_baseline__<uuid>`.
3. Строит DDL baseline-копии через `TableDDL.from_ddl(...)->to_ddl()`.
   Некорректный DDL должен приводить к ошибке (без fallback-переписи).
4. Переписывает query-level `test_queries` (включая их `warmup_queries`)
   на baseline-копию (`_rewrite_query_payloads_to_baseline_copy`).
5. Снимает baseline insert-метрики через `_measure_insert(...)`.
6. Снимает baseline select-метрики через `_measure_select_queries(...)` с режимами:
   - `cache_mode=warm`: query-level warmup и серия замеров;
   - `cache_mode=cold`: перед каждым замером сбрасывает
     `SYSTEM DROP MARK CACHE` и `SYSTEM DROP UNCOMPRESSED CACHE`.
7. Дополнительно сохраняет per-query source select-метрики (`source_table_select_metrics_by_query`).
8. Возвращает baseline-метрики в `SourceBenchmarkResult.metrics`.
9. Всегда удаляет временную baseline-таблицу в `finally`.

`run_variant_benchmark(payload)`:
1. Создаёт variant-таблицу в `variant_database`.
2. Для insert-замеров использует `_measure_insert(...)`.
3. Для индексных вариантов передаёт `tested_cols` из `variant_params.index_choices`
   (legacy-совместимое поведение).
4. Снимает select/size/index/compression-метрики.
5. Для select считает:
   - агрегированные percentiles/speedup;
   - per-query percentiles;
   - per-query speedup (`source/tested`).
6. Пишет результат через `ClickHouseBenchmarkResultStore.store_worker_result(...)`.
7. Всегда удаляет variant-таблицу в `finally`.
8. На уровне Celery task-wrapper невалидный payload или ошибка variant-бенчмарка
   помечаются как `skipped_*`, логируются и не валят общий benchmark-run
   (важно для корректного завершения progress/wait).

Низкоуровневые гарантии runtime:
1. Streaming insert: приоритет `raw_stream/raw_insert` (clickhouse-connect),
   fallback — `INSERT ... SELECT` + метрики из `clickhouse_connect` `.summary`.
2. Strict-fill для insert с `numbers(...)`, чтобы можно было набрать нужное число строк,
   даже если исходная таблица меньше.
3. Пер-process stream semaphore (`acquire_stream_slot/release_stream_slot`) обязателен,
   чтобы не открыть несколько stream-операций на одном инстансе.
4. Retry/backoff для insert/select берётся из env:
   `MAX_COPY_N_RETRIES`, `MAX_COPY_RETRY_SLEEP_SEC`, `MAX_COPY_RETRY_SLEEP_SEC_INCREMENT`.
5. Ошибочные замеры маркируются метриками `-1` (удобно фильтровать downstream).
6. Для `TaskMonitorCelery` и wait-барьеров в sequential top-N Celery worker должен
   быть запущен с `-E` (`--events`), иначе launcher не получает task events.

## 5) Генерация вариантов (variant_generation + combiner фасад)

### 5.1 Где что лежит

1. Контракт: `src/variant_generation/contracts/strategy.py`
2. Реестр: `src/variant_generation/registry.py`
3. Реализации: `src/variant_generation/implementations/*`
4. Публичный backward-compatible фасад: `src/combiner.py`

### 5.2 Built-in стратегии генерации

1. `TypesVariantGenerationStrategy` (`types.py`)
2. `IndexesVariantGenerationStrategy` (`indexes.py`)
3. `CombinedVariantGenerationStrategy` (`combined.py`)
4. `SequentialVariantGenerationStrategy` (`sequential.py`)

Важно:

1. `SequentialVariantGenerationStrategy` это только combiner-level последовательная выдача вариантов.
2. Реальный двухфазный top-N sequential делается не здесь, а в `SequentialTopNTableExecutionStrategy`.
3. Для `indexes`/`combined` можно задать `index_granularity_values`:
   это добавляет перебор `SETTINGS index_granularity` и умножает число индексных вариантов.
4. Для каждого `indexes[]` можно задать свой `index_granularity_values`:
   эффективные значения считаются как пересечение global и per-index списков
   (если global не задан — берётся per-index список).
5. При применении нового `index_granularity` старое значение из исходного DDL
   заменяется без дублей; итоговый variant-DDL содержит ровно один ключ.
6. Полностью no-index комбинации (когда в варианте не добавлен ни один индекс)
   по умолчанию исключаются.

### 5.3 Реестр

`MODE_VARIANT_STRATEGIES` содержит mode -> strategy instance.

Регистрация:

1. `register_variant_generation_strategy(mode, strategy, overwrite=False)`
2. `get_variant_generation_strategy(mode)`

## 6) Table execution strategies

### 6.1 Обычные стратегии

`TypesTableExecutionStrategy`, `IndexesTableExecutionStrategy`, `CombinedTableExecutionStrategy` запускают стандартный поток `runner._execute_regular_table(...)`.
Baseline исходного DDL для них уже выполнен runner-ом заранее.

### 6.2 Sequential top-N стратегия

`SequentialTopNTableExecutionStrategy` (`src/benchmark_runtime/implementations/table_strategy/sequential_topn.py`):

1. Стадия `types`:
   - генерирует и выполняет type/codec-варианты.
2. Отбор:
   - берет top-N через `result_store.get_top_type_variants(...)`.
3. Стадия `indexes`:
   - для каждого top type-DDL генерирует index-варианты и выполняет их.
4. Все jobs обеих стадий получают одинаковый `source_benchmark` от runner-а.
5. Если execution adapter поддерживает hooks прогресса (`open_progress_scope`, `wait_for_dispatched_tasks`),
   стратегия открывает progress-scope для stage1/stage2 и ставит explicit wait-барьер по Celery batch.

Стратегия ставит внутренний wait-барьер после dispatch type-stage:
ждёт, пока в store не появятся все `type_total` результатов,
и только затем выбирает top-N и запускает index-stage.

Условия для index стадии:

1. Должны быть результаты type-стадии.
2. `sequential_types_top_n_for_indexes > 0`.
3. store должен корректно вернуть top type-варианты.

## 7) JSON-конфиг и валидация

Контракт описан в `src/models.py`.

### 7.1 Главные поля BenchmarkConfig

1. `id`
2. `connection_id`
3. `strategy`
4. `global_rules`
5. `databases`, `tables`
6. `test_database` (опционально, отдельная БД для variant-таблиц)
7. `insert_operations_count`
8. `sequential_types_top_n_for_indexes`
9. `insert_rows_per_operation_limit`
10. `source_insert_rows_per_operation_limit` (legacy fallback baseline-лимита)
11. `source_insert_rows_per_operation_limits`
12. `insert_rows_per_operation_limits`
13. `max_benchmarks_limits`
14. `max_type_benchmarks` (legacy)
15. `max_index_benchmarks` (legacy)
16. `index_granularity_values` (global-перебор `SETTINGS index_granularity`)
17. `column_rules_mode`, `index_rules_mode`
18. `queries`
19. `scoring`
20. `table_rules[]` (локальные override, включая `strategy` и `test_database`)

Дополнительно для `queries.test_queries[]`:
1. `query` — SQL-шаблон (поддерживаются `{table}` и `{benchmark_id}`).
2. `query_id` — стабильный идентификатор запроса (если не задан, генерируется автоматически).
3. `cache_mode` — `warm` или `cold`.
4. `select_operations_count` — число select-замеров конкретного запроса.
5. `warmup_queries` — query-level прогревы для `warm` режима
   (для `cold` запрещены).
6. Глобальный `queries.warmup_queries` не поддерживается.

Дополнительно для `column_rules[]`:
1. `auto_generate_alternatives` (`false` по умолчанию) — включает legacy-автогенерацию type+codec.
2. `auto_compressions_datatype` (опционально) — hint datatype для preprocessings.

Дополнительно для `index_rules[]`:
1. `auto_generate_indexes` (`false` по умолчанию) — включает автогенерацию skip-индексов по типу.
2. `auto_indexes_datatype` (опционально) — hint datatype для авто-генерации индексов.
3. Ручные `indexes` и авто-сгенерированные индексы объединяются; дубли `(type, granularity)` удаляются.
4. Для range-типов (`Int8/16/32/64`, `Float32/64`, `Decimal*`, `Date/DateTime*`) авто-генерация добавляет `minmax`.
5. `set(...)` и `bloom_filter(...)` auto-генератор не добавляет; их задают вручную в `indexes`.
6. В `indexes[]` можно задать `index_granularity_values` для конкретного индекс-варианта.
7. `indexes[].granularity` может быть как `int`, так и `int[]`:
   - `int` => один индекс-вариант;
   - `int[]` => несколько индекс-вариантов (по одному на каждую granularity).

### 7.2 Контракты верхнего уровня

1. `CeleryConfig`
2. `ConnectionsFileConfig`
3. `RuleBanksFileConfig`
4. `BenchmarksFileConfig`
5. `BenchmarkProjectConfig`
6. `BenchmarkRootConfig`

### 7.3 Загрузка и склейка секций

`src/loader.py` (`ConfigLoader`):

1. `load(path)` — project-file режим.
2. `parse_parts(...)` — сборка root из 4 JSON-секций.
3. Валидация ссылок:
   - `connection_id` должен существовать;
   - `rule_bank` должен существовать;
   - `default_rule_banks[dbms]` должен ссылаться на существующий банк;
   - `table_rules` не должны выходить за `databases` selector.

### 7.4 CLI-валидатор конфигов

`validate_json_config.py` поддерживает:

1. `single` — проверка одного JSON по типу (`celery|connections|rule_banks|benchmarks|project|root`).
2. `parts` — проверка 4 секций + сборка root.
3. `project` — проверка project-файла и связанных файлов.

Отдельно для формул:

1. `validate_scoring_formula.py` — проверка `scoring.expression` в файле типа
   `benchmarks|root|project`.
2. При ошибках печатает `WARNING` и завершает работу с exit code `1`.

### 7.5 Настройка scoring (builtin/expression)

`BenchmarkConfig.scoring` и `TableRuleConfig.scoring` поддерживают:

1. `mode="builtin"` — стандартный runtime score.
2. `mode="expression"` — безопасное выражение на `simpleeval`.
3. `on_error_score` — fallback при ошибке expression (иначе `score=None`).
4. Для совместимости `expression` можно передать alias-ключами `score_expression`/`sql_expression`.

`builtin` считает:
1. `insert_ratio = median(source_insert_ms) / median(tested_insert_ms)`.
2. `select_ratio = median(source_select_ms) / median(tested_select_ms)`.
3. `compression_ratio = source_size_bytes / tested_size_bytes`
   (используются `*_consumed_compressed_size_bytes_with_indexes`).
4. `score = (insert_ratio * select_ratio * compression_ratio) ** (1/3)`.

Приоритет override:

1. `table_rules[].scoring`;
2. `benchmark.scoring`.

Важные детали expression-контекста:

1. Есть nested-объекты `source`/`tested`/`speedup`.
2. Есть flat алиасы (`source_select_time_ms_percentiles`, `tested_select_time_ms_by_percentile` и т.д.).
3. Есть `compression_overall_coef`, `source_size_bytes`, `tested_size_bytes`.
4. Есть precomputed блоки:
   - `medians.source_insert_time_ms`, `medians.tested_insert_time_ms`,
     `medians.source_select_time_ms`, `medians.tested_select_time_ms`;
   - `ratios.insert`, `ratios.select`, `ratios.compression`.
5. Для per-query есть и list (`select_time_speedup_by_query`), и map-доступы через `per_query`:
   - `per_query.tested_by_query_id['q_id']`
   - `per_query.source_by_query_id['q_id']`
   - `per_query.speedup_by_query_id['q_id']`
6. Есть JSON-alias root-поля (уже распарсенные в map по `query_id`):
   - `tested_table_select_metrics_by_query_json['q_id']`
   - `source_table_select_metrics_by_query_json['q_id']`
   - `tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json['q_id']`

Рекомендуемая expression-формула (ratio + геометрическое среднее):

1. `insert_ratio = median(source_insert_ms) / median(tested_insert_ms)`.
2. `select_ratio = median(source_select_ms) / median(tested_select_ms)`.
3. `compression_ratio = source_size_bytes / tested_size_bytes`.
4. `score = (insert_ratio * select_ratio * compression_ratio)^(1/3)`.
5. В runtime это обычно задаётся как:
   `pow(safe_div(medians.source_insert_time_ms, medians.tested_insert_time_ms, 1.0) * safe_div(medians.source_select_time_ms, medians.tested_select_time_ms, 1.0) * safe_div(source_size_bytes, tested_size_bytes, 1.0), 1 / 3)`.

Для baseline run (`run_source_benchmark`) `source` и `tested` в контексте совпадают
и рассчитываются из baseline-метрик.

Доступ к перцентилям:

1. По индексу массива: `source.select.time_ms_percentiles[1]`.
2. По ключу перцентиля: `source_select_time_ms_by_percentile[100]`, `["100"]`, `["p100"]`.
3. Через helper: `pct(source_select_time_ms_by_percentile, 100)`.

Разрешённые функции:

1. `safe_div`, `pct`, `at`, `coalesce`, `clamp`, `median`.
2. `abs`, `min`, `max`, `round`, `sqrt`, `log`, `ln`, `pow`.

Разрешённые операторы:

1. Арифметика: `+`, `-`, `*`, `/`, `%`, `**`.
2. Сравнения: `==`, `!=`, `>`, `>=`, `<`, `<=`.
3. Унарные: `+x`, `-x`, `not x`.
4. Группировка через скобки `( ... )`.

Ограничения безопасности:

1. Только whitelisted функции.
2. Нельзя вызывать произвольные объекты (`__import__`, методы, атрибуты с `_` и т.д.).
3. Любая ошибка expression -> warning + `on_error_score`/`None`.
4. До старта run `BenchmarkRunner` валидирует expression статически и не запускает
   benchmark при ошибках формулы.

Отдельно по трассировке расчёта:

1. `_resolve_score(...)` всегда формирует `score_calculation_json`.
2. Для `builtin` внутри хранятся формула и использованные компоненты.
3. Для `expression` внутри хранятся исходная строка expression, контекст, статус, ошибка (если есть) и итог.
4. Для baseline skip (`source_table_empty`) тоже формируется `score_calculation_json` со статусом `skipped`.
5. Возможные статусы: `ok`, `empty`, `error`, `fallback_on_error`,
   `non_finite`, `fallback_non_finite`, `skipped`.

## 8) Правила и их резолв

`src/resolver.py`:

1. `merge(global, local)`:
   - локальные поля перезаписывают глобальные.
2. `resolve(...)`:
   - собирает итоговые runtime-правила.

Автогенерация column alternatives:
1. Лежит в `src/datatype_alternatives.py`.
2. Используются legacy-совместимые функции:
   - `generate_possible_compressions_w_preprocessings`
   - `generate_possible_new_datatypes`
3. Включается per-rule через `column_rules[].auto_generate_alternatives=true`.

`RuleSourceMode`:

1. `global_bank_only`
2. `global_bank_with_inline_priority`
3. `inline_only`

Если выбран bank-required режим и bank недоступен, это валидная ошибка.

## 9) Лимиты вставки строк и числа вариантов

Пять полей:

1. `insert_rows_per_operation_limit` — общий fallback.
2. `insert_rows_per_operation_limits` — лимиты по mode-ключам (включая будущие custom ключи).
3. `source_insert_rows_per_operation_limit` — legacy fallback baseline-лимита.
4. `source_insert_rows_per_operation_limits` — baseline-лимиты по mode.
5. `max_benchmarks_limits` — лимиты числа variant jobs по mode.
6. `max_type_benchmarks` / `max_index_benchmarks` — legacy compatibility.

Приоритет `BenchmarkEngine.resolve_insert_rows_limit(...)`:

1. `insert_rows_per_operation_limits[variant_mode]`
2. `insert_rows_per_operation_limits[job_mode or table_plan.mode]`
3. `insert_rows_per_operation_limit`

Приоритет `BenchmarkEngine.resolve_variant_generation_limit(...)`:

1. `max_benchmarks_limits[variant_mode]`;
2. `max_benchmarks_limits[job_mode or table_plan.mode]`;
3. legacy `max_type_benchmarks` / `max_index_benchmarks`;
4. legacy fallback `insert_operations_count`.

Для baseline source benchmark:

1. если задан `source_insert_rows_per_operation_limits[table_mode]`, используется он;
2. затем используется legacy `source_insert_rows_per_operation_limit`, если задан;
3. иначе используется стандартный fallback
   `insert_rows_per_operation_limits -> insert_rows_per_operation_limit`.

Семантика итераций и метрик:

1. `insert_operations_count` — это количество insert-замеров (повторов).
2. `insert_rows_per_operation_limit` — лимит строк на один insert-замер.
3. Между повторами таблица не очищается.
4. Итоговый объём строк в тестовой таблице после insert-этапа обычно:
   `insert_operations_count * insert_rows_per_operation_limit`.
5. Insert-перцентили считаются по одному объединённому массиву замеров
   (без mean-of-means между итерациями).

Для sequential это позволяет задавать разные лимиты отдельно для:

1. type/codec части;
2. index части;
3. общего sequential fallback.

## 10) Селекторы БД/таблиц и override

`BenchmarkConfig`:

1. `databases`: `"*"` или список.
2. `tables`: `"*"`, список, или map `{db: "*"|[tables]}`.

`TableSelector`:

1. раскрывает selectors;
2. строит список `TableTarget`;
3. дедуплицирует `(database, table)`.

`TableRuleConfig` может локально override:

1. `rules`
2. `column_order_mode`
3. `queries`
4. `insert_operations_count`
5. `sequential_types_top_n_for_indexes`
6. `insert_rows_per_operation_limit`
7. `source_insert_rows_per_operation_limit`
8. `source_insert_rows_per_operation_limits`
9. `insert_rows_per_operation_limits`
10. `max_benchmarks_limits`
11. `max_type_benchmarks` / `max_index_benchmarks` (legacy)
12. `index_granularity_values`
13. `strategy`
14. `test_database`
15. `scoring`

## 11) Entry points

1. `main.py`:
   - demo-runner;
   - читает base64-конфиги из env;
   - использует `StubMetadataProvider`, `NoopExecutionAdapter`, `InMemoryBenchmarkResultStore`.
2. `examples/example.py` — общий демо-сценарий.
3. `examples/example_sequential_topn.py` — sequential top-N демо.

## 12) Тесты и текущий статус

Основные тесты:

1. `tests/test_planner_engine_runner.py`
2. `tests/test_models_and_resolver.py`
3. `tests/test_combiner_and_naming.py`
4. `tests/test_loader.py`
5. `tests/test_validate_json_config.py`
6. `tests/test_validate_scoring_formula.py`

Запуск:

```bash
./venv/bin/python -m pytest -q
```

На текущем состоянии проекта: `199 passed, 11 subtests passed`.

## 13) Как расширять проект корректно

### 13.1 Добавить новый mode генерации

1. Реализовать `VariantGenerationStrategy`.
2. Зарегистрировать mode в `variant_generation.registry`.
3. При необходимости добавить built-in файл в `src/variant_generation/implementations/`.

### 13.2 Сделать mode доступным из JSON strategy

1. Добавить новый ключ в `BenchmarkStrategy` (`src/models.py`).
2. Обновить `STRATEGY_TO_MODE`.
3. Зарегистрировать/подключить table execution strategy для этого ключа в `BenchmarkRunner`.
4. Обновить docs и тесты.

### 13.3 Добавить особую логику выполнения

1. Реализовать `TableExecutionStrategy`.
2. Подключить через `runner.register_table_execution_strategy("my_strategy", strategy)`.
3. Размещать в `src/benchmark_runtime/implementations/table_strategy/`.

### 13.4 Добавить production execution/storage/metadata

1. `BenchmarkExecutionAdapter` для реального SQL-бенчмарка.
2. В адаптере реализовать оба метода:
   - `execute_source_benchmark(job)` для baseline исходного DDL;
   - `execute_variant(job)` для вариантов.
3. `BenchmarkResultStore` для production persistence.
4. `MetadataProvider` для источника метаданных.

## 14) Ограничения и подводные камни

1. `BenchmarkStrategy` и `BenchmarkMode` заданы как `Literal`: новые значения нужно явно добавлять в `models.py`.
2. Сопоставление `by_type` в правилах строгое по строке типа.
3. Combiner-level `sequential` не равно runner-level `sequential_topn_strategy`.
4. В репозитории отслеживаются `__pycache__`; не удалять массово без явной задачи.
5. `main.py` — демонстрационный запуск, не production execution.

## 15) Workflow для LLM-агента

Перед правкой:

1. Прочитать `src/models.py`, `src/benchmark_engine.py`, `src/benchmark_runtime/*`, целевые тесты.
2. Проверить требования на backward compatibility.

После правки:

1. Обновить `README.md` и этот файл, если изменились контракты/архитектура.
2. Прогнать тесты:

```bash
./venv/bin/python -m pytest -q
```

3. Проверить diff на случайные артефакты (`__pycache__`, временные файлы).

---

Быстрый минимум для входа в проект:

1. `README.md`
2. `src/benchmark_engine.py`
3. `src/benchmark_runtime/contracts/*`
4. `src/variant_generation/*`
5. `tests/test_planner_engine_runner.py`
