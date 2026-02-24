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
5. `sequential_topn_stage1_dispatch_strategy`
6. `sequential_topn_stage2_dispatch_strategy`

Маппинг в `src/models.py`:

1. `types_strategy -> types`
2. `indexes_strategy -> indexes`
3. `combined_strategy -> combined`
4. `sequential_topn_strategy -> sequential`
5. `sequential_topn_stage1_dispatch_strategy -> sequential`
6. `sequential_topn_stage2_dispatch_strategy -> sequential`

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
1. `execute_variant(job)` всегда вызывается runner-ом.
2. Runner не пишет результаты в store.
3. Сохранение результата должно происходить внутри execution backend/воркера.
4. Опционально можно использовать `bind_result_store(result_store)` для in-process demo/test-реализаций.

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
   - `SequentialTopNDispatchTypesTableExecutionStrategy`
   - `SequentialTopNDispatchIndexesTableExecutionStrategy`

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
5. `VariantJob`
6. `BenchmarkVariantResult`
7. `StoredBenchmarkResult`
8. `TopTypeVariant`

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

### 5.3 Реестр

`MODE_VARIANT_STRATEGIES` содержит mode -> strategy instance.

Регистрация:

1. `register_variant_generation_strategy(mode, strategy, overwrite=False)`
2. `get_variant_generation_strategy(mode)`

## 6) Table execution strategies

### 6.1 Обычные стратегии

`TypesTableExecutionStrategy`, `IndexesTableExecutionStrategy`, `CombinedTableExecutionStrategy` запускают стандартный поток `runner._execute_regular_table(...)`.

### 6.2 Sequential top-N стратегия

`SequentialTopNTableExecutionStrategy` (`src/benchmark_runtime/implementations/table_strategy/sequential_topn.py`):

1. Стадия `types`:
   - генерирует и выполняет type/codec-варианты.
2. Отбор:
   - берет top-N через `result_store.get_top_type_variants(...)`.
3. Стадия `indexes`:
   - для каждого top type-DDL генерирует index-варианты и выполняет их.

Стратегия ставит внутренний wait-барьер после dispatch type-stage:
ждёт, пока в store не появятся все `type_total` результатов,
и только затем выбирает top-N и запускает index-stage.

Условия для index стадии:

1. Должны быть результаты type-стадии.
2. `sequential_top_n > 0`.
3. store должен корректно вернуть top type-варианты.

### 6.3 Sequential top-N dispatch (для Celery fire-and-forget)

Если launcher не должен ждать и не должен писать результаты:

1. `sequential_topn_stage1_dispatch_strategy`
   - отправляет только type-stage jobs;
   - использует `runner._execute_without_store(...)`.
2. `sequential_topn_stage2_dispatch_strategy`
   - читает top-N type-вариантов из `result_store`;
   - отправляет index-stage jobs;
   - launcher также ничего не пишет в store.

Типовой поток:

1. Запустить stage1 dispatch.
2. Внешний процесс ждёт завершения всех type-задач и запись метрик воркерами.
3. Запустить stage2 dispatch с тем же `benchmark_run_id`.

## 7) JSON-конфиг и валидация

Контракт описан в `src/models.py`.

### 7.1 Главные поля BenchmarkConfig

1. `id`
2. `connection_id`
3. `strategy`
4. `global_rules`
5. `databases`, `tables`
6. `max_iterations`
7. `sequential_top_n`
8. `insert_rows_limit`
9. `insert_rows_limits`
10. `column_rules_mode`, `index_rules_mode`
11. `queries`
12. `table_rules[]` (локальные override, включая `strategy`)

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

## 8) Правила и их резолв

`src/resolver.py`:

1. `merge(global, local)`:
   - локальные поля перезаписывают глобальные.
2. `resolve(...)`:
   - собирает итоговые runtime-правила.

`RuleSourceMode`:

1. `global_bank_only`
2. `global_bank_with_inline_priority`
3. `inline_only`

Если выбран bank-required режим и bank недоступен, это валидная ошибка.

## 9) Лимиты вставки строк

Два уровня:

1. `insert_rows_limit` — общий fallback.
2. `insert_rows_limits` — лимиты по mode-ключам (включая будущие custom ключи).

Приоритет `BenchmarkEngine.resolve_insert_rows_limit(...)`:

1. `insert_rows_limits[variant_mode]`
2. `insert_rows_limits[job_mode or table_plan.mode]`
3. `insert_rows_limit`

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
4. `max_iterations`
5. `sequential_top_n`
6. `insert_rows_limit`
7. `insert_rows_limits`
8. `strategy`

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

Запуск:

```bash
./venv/bin/python -m pytest -q
```

На текущем состоянии проекта: `92 passed`.

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
2. `BenchmarkResultStore` для production persistence.
3. `MetadataProvider` для источника метаданных.

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
