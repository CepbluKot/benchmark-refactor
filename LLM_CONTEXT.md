# LLM Context: DDL Benchmark Engine

Этот файл предназначен для LLM-агентов, которые будут вносить изменения в проект.
Цель: быстро дать полный технический контекст, чтобы изменения были корректными и совместимыми.

## 1) Что делает проект

Проект реализует движок автоматического DDL-бенчмарка:

1. Берет исходные таблицы.
2. Генерирует DDL-варианты (типы, кодеки, индексы).
3. Запускает тестовые запросы по вариантам.
4. Считает `score` через execution-адаптер.
5. Сохраняет результаты в result-store.
6. Позволяет выбрать лучший вариант.

Практический фокус сейчас на ClickHouse, но архитектура расширяемая.

## 2) Архитектурное ядро

Основной поток: `planner -> engine -> runner`.

Главные классы в `src/benchmark_engine.py`:

1. `BenchmarkPlanner`:
   - раскрывает selectors БД/таблиц;
   - применяет global + table override;
   - резолвит rules;
   - возвращает `TableBenchmarkPlan`.
2. `BenchmarkEngine`:
   - загружает source DDL;
   - генерирует варианты через `combiner`;
   - строит `VariantJob`.
3. `BenchmarkRunner`:
   - выбирает стратегию table-level выполнения;
   - вызывает execution adapter;
   - сразу пишет результат в result store.

## 3) Runtime-контракты и реализации

### 3.1 Контракты

Контракты лежат в `src/benchmark_runtime/contracts/`:

1. `execution.py` -> `BenchmarkExecutionAdapter`
2. `metadata.py` -> `MetadataProvider`
3. `result_store.py` -> `BenchmarkResultStore`
4. `run_id.py` -> `BenchmarkRunIdProvider`
5. `table_strategy.py` -> `TableExecutionStrategy`

### 3.2 Встроенные реализации

Реализации лежат в `src/benchmark_runtime/implementations/`:

1. `inmemory/`:
   - `InMemoryBenchmarkResultStore`
   - `InMemoryBenchmarkRunIdProvider`
2. `noop/`:
   - `NoopExecutionAdapter`
3. `fetcher/`:
   - `FetcherMetadataProvider`
4. `run_id/`:
   - `MaxIdBenchmarkRunIdProvider`
5. `table_strategy/`:
   - `DefaultTableExecutionStrategy`
   - `SequentialTopNTableExecutionStrategy`

### 3.3 Runtime DTO

DTO лежат в `src/benchmark_runtime/types.py`:

1. `TableTarget`
2. `Query`
3. `QueryPlan`
4. `TableBenchmarkPlan`
5. `VariantJob`
6. `BenchmarkVariantResult`
7. `StoredBenchmarkResult`
8. `TopTypeVariant`

### 3.4 Backward compatibility

Сохранены re-export файлы:

1. `src/benchmark_runtime/execution.py`
2. `src/benchmark_runtime/metadata.py`
3. `src/benchmark_runtime/result_store.py`
4. `src/benchmark_runtime/run_id.py`
5. `src/benchmark_runtime/table_strategy.py`

Также `src/benchmark_engine.py` импортирует и ре-экспортит ключевые runtime-сущности.
Из-за этого старые импорты `from benchmark_engine import ...` продолжают работать.

## 4) Конфигурация JSON

Контракт описан в `src/models.py`.

Основные типы:

1. `BenchmarkMode = Literal["types", "indexes", "sequential", "combined"]`
2. `BenchmarkStrategy = Literal["types_strategy", "indexes_strategy", "combined_strategy", "sequential_topn_strategy"]`
3. `RuleSourceMode = Literal["global_bank_only", "global_bank_with_inline_priority", "inline_only"]`
4. `ColumnOrderMode = Literal["compressed_size_desc"]`

Основные JSON-секции:

1. `celery.json`
2. `connections.json`
3. `rule_banks.json`
4. `benchmarks.json`
5. `benchmark.project.json` (обертка multi-file)

Сборка и проверка ссылок:

1. `src/loader.py` -> `ConfigLoader`
2. Валидация ссылок:
   - `connection_id` должен существовать;
   - `rule_bank` должен существовать;
   - `default_rule_banks[dbms]` должен указывать на существующий банк;
   - scope `table_rules` должен соответствовать selector `databases`.

## 5) Режимы генерации вариантов

Где что лежит:

1. Контракт: `src/variant_generation/contracts/strategy.py`.
2. Реестр: `src/variant_generation/registry.py`.
3. Реализации: `src/variant_generation/implementations/*`.
4. Backward-compatible фасад: `src/combiner.py`.

Built-in mode:

1. `types`:
   - меняются только типы/кодеки;
   - индексы не трогаются.
2. `indexes`:
   - меняются только индексы;
   - типы/кодеки не трогаются.
3. `combined`:
   - декартово произведение types x indexes.
4. `sequential`:
   - в combiner это последовательная выдача;
   - полноценный двухэтапный top-N sequential делается на уровне runner-стратегии.

Расширение combiner:

1. Реализовать `VariantGenerationStrategy`.
2. Зарегистрировать через `register_variant_generation_strategy(mode, strategy)`.
3. Если новый mode должен быть доступен из JSON-конфига, добавить соответствующий ключ в `BenchmarkStrategy` и маппинг `STRATEGY_TO_MODE` в `src/models.py`.

## 6) Sequential Top-N (как реально работает)

`SequentialTopNTableExecutionStrategy` (`implementations/table_strategy/sequential_topn.py`) делает:

1. Стадия types:
   - прогоняет все type/codec варианты;
   - сохраняет результаты.
2. Отбор:
   - берет top-N через `result_store.get_top_type_variants(...)`.
3. Стадия indexes:
   - прогоняет индексные варианты только на top type-DDL.

Важно:

1. Для выбора top-N нужен `score` в `BenchmarkVariantResult`.
2. Если top-результатов нет, index стадия не запускается.

## 7) Лимиты вставки строк

Есть два уровня:

1. `insert_rows_limit` (общий fallback)
2. `insert_rows_limits` (по mode, включая custom-keys)

Итоговый приоритет в `BenchmarkEngine.resolve_insert_rows_limit(...)`:

1. `insert_rows_limits[variant_mode]`
2. `insert_rows_limits[job_mode or table_plan.mode]`
3. `insert_rows_limit`

Для sequential это позволяет задавать отдельно лимиты на:

1. `types` стадию
2. `indexes` стадию
3. общий `sequential` fallback

## 8) Rule resolving

`src/resolver.py`:

1. `merge(global, local)`:
   - table-local поля перезаписывают global.
2. `resolve(...)`:
   - поддерживает default path (если `column_rules_mode/index_rules_mode` не заданы);
   - поддерживает `column_rules_mode`/`index_rules_mode`.

Режимы rule source:

1. `global_bank_only`:
   - только банк.
2. `global_bank_with_inline_priority`:
   - inline + bank (inline идет раньше).
3. `inline_only`:
   - только inline.

Если выбран bank-required режим, но global bank недоступен, это валидная ошибка.

## 9) Selectors и table-level override

`BenchmarkConfig` поддерживает:

1. `databases="*"` или список.
2. `tables="*"` или список, или map `{db: "*"|[tables]}`.

`TableSelector`:

1. раскрывает все варианты selectors;
2. дедуплицирует `(database, table)`.

`TableRuleConfig` может override:

1. `rules`
2. `column_order_mode`
3. `queries`
4. `max_iterations`
5. `sequential_top_n`
6. `insert_rows_limit`
7. `insert_rows_limits`
8. `strategy`

## 10) Entry points и запуск

### 10.1 Demo entrypoint

`main.py`:

1. читает base64-конфиги из env через `settings.py`;
2. использует `StubMetadataProvider`;
3. использует `NoopExecutionAdapter` + `InMemoryBenchmarkResultStore`;
4. это demo-runner, не production-execution.

### 10.2 Примеры

1. `examples/example.py` - общий demo.
2. `examples/example_sequential_topn.py` - sequential top-N demo.

### 10.3 Валидатор конфигов

`validate_json_config.py`:

1. `single` - проверка одного JSON.
2. `parts` - проверка 4 секций + сборка root.
3. `project` - проверка project file + linked files.

## 11) Тесты

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

На момент подготовки файла тесты проходили: `92 passed`.

## 12) Правила изменения кода для LLM-агента

1. Не ломать публичные импорты из `benchmark_engine` без явной задачи на breaking changes.
2. При переносе/рефакторе сохранять backward-compatible re-export.
3. При добавлении нового mode:
   - обновить `models.BenchmarkMode`, `models.BenchmarkStrategy` и `models.STRATEGY_TO_MODE`;
   - зарегистрировать стратегию в `variant_generation.registry` (через фасад `combiner` или напрямую);
   - покрыть тестами mode + edge-cases.
4. При изменении семантики лимитов вставки:
   - явно документировать приоритеты;
   - добавлять тесты на `global + table override`.
5. Любые изменения planner/engine/runner проверять через `tests/test_planner_engine_runner.py`.
6. Любые изменения конфиг-моделей проверять через `tests/test_models_and_resolver.py` и `tests/test_loader.py`.

## 13) Известные нюансы и подводные камни

1. `BenchmarkMode` и `BenchmarkStrategy` сейчас `Literal`; новые mode/strategy требуют явного добавления в `models.py`.
2. `by_type` matching в правилах строгий по строке типа (см. доменные тесты).
3. Sequential top-N оркестрируется отдельно в table strategy; combiner-level `sequential` не делает top-N.
4. В репозитории есть отслеживаемые `__pycache__` файлы; массовое удаление может засорить diff.
5. `main.py` не делает реальный SQL-бенчмарк, это лишь демонстрационный запуск.

## 14) Рекомендуемый workflow для LLM

Перед правкой:

1. Прочитать `models.py`, `benchmark_engine.py`, `benchmark_runtime/*`, целевой тестовый файл.
2. Проверить, не ломает ли задача backward compatibility.

После правки:

1. Обновить docs (`README.md` и этот файл), если структура/контракты изменились.
2. Запустить тесты:
   - `./venv/bin/python -m pytest -q`
3. Проверить `git diff` на случайных артефактах (`__pycache__`, временные файлы).

---

Если нужно быстро стартовать, начните с:

1. `README.md` (пользовательский и dev-гайд),
2. `src/benchmark_engine.py` (ядро оркестрации),
3. `src/benchmark_runtime/contracts/*` (контракты),
4. `tests/test_planner_engine_runner.py` (самый полный behavioral reference).
