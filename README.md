# DDL Benchmark Engine

Python-движок для перебора вариантов DDL (типы/кодеки/индексы), прогонки бенчмарка и выбора лучших конфигураций.

Документ описывает:
1. полный алгоритм работы пайплайна;
2. все ключевые модели конфигурации;
3. все классы и методы runtime-оркестрации;
4. все вспомогательные модули (парсинг DDL, комбинатор, генерация запросов, naming, fetcher).

## 0. Простыми словами

Если объяснить без внутренней кухни, бенчмарк делает вот что:

1. Вы даете JSON-конфиг:
   - куда подключаться (БД/креды);
   - какие базы и таблицы тестировать (все автоматически или вручную);
   - что разрешено менять в DDL (типы, кодеки, индексы);
   - лимиты (например, максимум итераций).
2. Движок строит варианты DDL для каждой выбранной таблицы.
3. Для каждого варианта прогоняются одни и те же тестовые запросы.
4. По каждому прогону считается метрика качества (`score`) и сразу пишется в хранилище результатов (обычно БД), без накопления большого списка в памяти.
5. Если режим `sequential`:
   - сначала тестируются только варианты типов/кодеков;
   - потом из БД выбираются top-N лучших по `score`;
   - и только на этих лучших DDL дополнительно тестируются индексы.
6. В конце у вас есть `benchmark_run_id` запуска и все результаты в БД, откуда можно сделать отчеты и выбрать лучший DDL для продакшена.

Коротко: это автоматический перебор и сравнение DDL-вариантов, чтобы не угадывать вручную, а опираться на реальные замеры.

## 1. Архитектура и поток данных

Пайплайн состоит из трех основных уровней:

1. `loader.py` + `models.py`  
   Загрузка и валидация JSON-конфига в `BenchmarkRootConfig`.
2. `benchmark_engine.py::BenchmarkPlanner`  
   Преобразование конфига в table-level планы (`TableBenchmarkPlan`) с учетом глобальных и локальных override.
3. `benchmark_engine.py::BenchmarkEngine` + `BenchmarkRunner`  
   Генерация `VariantJob` и выполнение через `BenchmarkExecutionAdapter`.

Упрощенный поток:

```text
project json -> ConfigLoader -> BenchmarkRootConfig
BenchmarkRootConfig + MetadataProvider -> BenchmarkPlanner -> TableBenchmarkPlan
TableBenchmarkPlan -> BenchmarkEngine -> VariantJob -> BenchmarkExecutionAdapter -> BenchmarkVariantResult -> BenchmarkResultStore
```

## 2. Алгоритм работы (end-to-end)

### 2.1 Загрузка конфигурации

1. `load_config(path)` вызывает `ConfigLoader.load(path)`.
2. `ConfigLoader` валидирует `BenchmarkProjectConfig`.
3. Подгружает `connections_file`, `rule_banks_file`, при необходимости `benchmarks_file`.
4. Собирает `BenchmarkRootConfig`.
5. Проверяет ссылочную целостность:
   - `benchmark.connection_id` существует;
   - `rules.rule_bank` существует;
   - `default_rule_banks[dbms]` указывает на существующий банк.

### 2.2 Планирование таблиц

Для каждого benchmark:

1. `TableSelector` раскрывает селекторы `databases` и `tables`.
2. Для каждой таблицы ищется локальный `table_rule`.
3. `RuleResolver.merge(global_rules, local_rules)` объединяет правила.
4. `RuleResolver.resolve(...)` выбирает источник правил:
   - explicit `rule_bank`;
   - inline overrides;
   - `default_rule_banks`.
5. Вычисляются итоговые параметры таблицы:
   - `mode`;
   - `max_iterations`;
   - `sequential_top_n`;
   - `column_order_mode`;
   - `queries`;
   - `celery`.
6. Формируется `TableBenchmarkPlan`.

### 2.3 Генерация заданий на выполнение

Для каждого `TableBenchmarkPlan`:

1. `BenchmarkEngine.prepare_table_context(...)`:
   - читает исходный `TableDDL` у `MetadataProvider`;
   - строит сырой `QueryPlan` с placeholder `{table}`.
2. `BenchmarkEngine.iter_variant_jobs_for_table_plan(...)`:
   - определяет режим генерации;
   - считает `total_variants(...)`;
   - итерирует `iter_variants(...)`;
   - для каждого варианта строит `VariantJob`.

### 2.4 Выполнение

`BenchmarkRunner.run(...)`:

0. Резолвит единый `benchmark_run_id` для всего запуска:
   - из аргумента `run(..., benchmark_run_id=...)`, либо
   - через `BenchmarkRunIdProvider.next_benchmark_run_id()`.
1. Для `mode != "sequential"`:
   - запускает jobs через `execution_adapter.execute_variant(job)`;
   - сразу сохраняет результат в `result_store.store_result(job, result)`.
2. Для `mode == "sequential"`:
   - Stage A: прогоняет только `types`-варианты;
   - сохраняет score/DDL type-этапа в result-store;
   - выбирает top-N (`sequential_top_n`) через `result_store.get_top_type_variants(...)`;
   - Stage B: для DDL лучших type-вариантов прогоняет `indexes`-варианты;
   - сохраняет index-результаты в result-store.

`run(...)` больше не возвращает массив результатов, а возвращает только `benchmark_run_id`.

Сортировка top-N:
- больше `score` = лучше;
- `score=None` уходит в конец.

## 3. Режимы перебора

Режим задается в `BenchmarkConfig.mode` или `TableRuleConfig.mode`.

1. `types`  
   Меняются только типы и кодеки колонок.
2. `indexes`  
   Меняются только skip-индексы.
3. `combined`  
   Декартово произведение type-вариантов и index-вариантов.
4. `sequential`  
   Адаптивный двухфазный режим в `BenchmarkRunner`:
   - types -> score -> top-N -> indexes на top-N DDL.

## 4. Конфиг-модели (`models.py`)

### 4.1 Базовые alias

- `BenchmarkMode = Literal["types", "indexes", "sequential", "combined"]`
- `DatabasesSelector = "*" | List[str]`
- `TablesSelector = "*" | List[str] | Dict[str, "*" | List[str]]`

### 4.2 Модели правил

1. `ColumnRuleConfig`
   - поля: `by_type`, `by_name`, `types`, `codecs`
   - `by_type` матчится строго по полной строке типа (без префиксного матчинга)
   - метод: `check_matchers()`
2. `IndexConfig`
   - поля: `type`, `granularity`
3. `IndexRuleConfig`
   - поля: `by_type`, `by_name`, `indexes`
   - `by_type` матчится строго по полной строке типа (без префиксного матчинга)
   - метод: `check_matchers()`
4. `RuleBankConfig`
   - поля: `column_rules`, `index_rules`, `column_order`
5. `RulesConfig`
   - поля: `rule_bank`, `column_rules`, `index_rules`, `column_order`
   - методы: `has_inline_overrides()`, `is_empty()`, `merged_over(base)`

### 4.3 Модели запросов и выполнения

1. `TestQueryConfig`
   - поля: `query`, `weight` (конфиговое поле, runtime сейчас использует только `query`)
2. `QueriesConfig`
   - поля: `mode`, `warmup_queries`, `test_queries`
   - метод: `check_manual_has_queries()`
3. `CeleryConfig`
   - поля: `workers`, `threads_per_worker`

### 4.4 Модели benchmark-проекта

1. `TableRuleConfig`
   - поля: `database`, `table`, `rules`, `column_order_mode`, `queries`, `max_iterations`, `sequential_top_n`, `mode`
   - метод: `non_empty_table_target(...)`
2. `ConnectionConfig`
   - поля: `id`, `dbms`, `credential_type`, `host`, `port`, `login`, `password`
   - метод: `normalize_tokens(...)`
3. `BenchmarkConfig`
   - поля: `id`, `connection_id`, `mode`, `global_rules`, `column_order_mode`, `databases`, `tables`, `max_iterations`, `sequential_top_n`, `queries`, `table_rules`, `celery`
   - метод: `validate_selectors()`
4. `BenchmarkRootConfig`
   - поля: `connections`, `benchmarks`, `rule_banks`, `default_rule_banks`, `celery`
   - методы: `normalize_default_rule_banks(...)`, `validate_uniqueness()`
5. Файловые обертки:
   - `ConnectionsFileConfig` (+ `validate_non_empty()`)
   - `RuleBanksFileConfig` (+ `normalize_default_rule_banks(...)`)
   - `BenchmarksFileConfig` (+ `validate_non_empty()`)
   - `BenchmarkProjectConfig` (+ `normalize_file_refs(...)`, `validate_benchmarks_source()`)

## 5. Loader API (`loader.py`)

### Класс `ConfigLoader`

1. `load(path)`  
   Читает project JSON и запускает сборку.
2. `parse(raw, base_dir=None)`  
   Парсит уже загруженный dict.
3. `_parse_project_config(raw, base_dir)`  
   Внутренний full pipeline сборки.
4. `_resolve_file_path(base_dir, ref)`  
   Резолв относительных путей.
5. `_read_json(path)`  
   Чтение JSON с нормальными ошибками.
6. `_validate_references(config)`  
   Проверка кросс-ссылок.
7. `_validate_table_rule_scope(bench)`  
   Проверка, что table_rules не выходят за `databases`.

### Функции

1. `load_config(path)`
2. `parse_config(raw, base_dir=None)`

## 6. Resolver API (`resolver.py`)

### Функции

1. `_column_rule_from_config(cfg)`
2. `_index_rule_from_config(cfg)`
3. `resolve(rules_config, banks, default_rule_banks=None, dbms=None)`  
   backward-compatible wrapper.

### Класс `ResolvedRules`

Поля:
- `column_rules`
- `index_rules`
- `column_order`
- `source_bank`

Методы:
- `__init__(...)`
- `__repr__()`

### Класс `RuleResolver`

1. `__init__(banks, default_rule_banks=None)`
2. `merge(global_rules, local_rules)`
3. `resolve(rules_config, dbms=None)`
4. `_pick_bank(rules_config, dbms)`
5. `_resolve_bank_name(rules_config, dbms)`

## 7. DDL-модель и парсер (`clickhouse_ddl.py`)

### `ColumnDef`

Поля: `name`, `type`, `codec`, `extra`  
Методы: `to_sql(indent="    ")`, `copy()`

### `IndexDef`

Поля: `name`, `expr`, `index_type`, `granularity`  
Методы: `to_sql(indent="    ")`, `copy()`

### `TableDDL`

Поля:
- `name`, `cluster`
- `columns`, `indexes`
- `other_body_entries`
- `engine`, `partition_by`, `order_by`, `primary_key`, `sample_by`
- `other_table_options`

Парсинг helpers:
1. `_find_closing_paren(text, pos)`
2. `_split_top_level_commas(text)`
3. `_consume_identifier(text)`
4. `_consume_type(text)`
5. `_extract_codec(text)`
6. `from_ddl(ddl)`
7. `_parse_column(text)`
8. `_parse_index(text)`
9. `_parse_table_options(text)`

Сборка/доступ:
1. `to_ddl()`
2. `copy()`
3. `column(name)`
4. `index(name)`

## 8. Правила и генераторы вариантов колонок/индексов

### `column_rules.py`

1. `ColumnAlternatives`
   - `iter_combos(original)`
   - `total(original)`
2. `ColumnRule`
   - поля: `alternatives`, `by_type`, `by_name`
   - метод: `matches(col)`

### `column_variants.py`

1. `ColumnVariantMeta`
2. `_resolve_columns(table, rules, column_order)`
3. `iter_column_variants(table, rules, column_order=None)`
4. `total_column_variants(table, rules, column_order=None)`

### `index_rules.py`

1. `IndexVariant`
   - `to_index_def(col, idx_num)`
2. `IndexAlternatives`
   - `iter_variants(col)`
   - `total()`
3. `IndexRule`
   - `matches(col)`

### `index_variants.py`

1. `IndexVariantMeta`
2. `_resolve_index_columns(table, rules)`
3. `iter_index_variants(table, rules)`
4. `total_index_variants(table, rules)`

## 9. Комбинатор режимов (`combiner.py`)

### `VariantMeta`

Поля:
- `global_index`
- `mode`
- `column_meta`
- `index_meta`

Методы-свойства:
- `column_choices`
- `index_choices`

### Публичные функции

1. `iter_variants(table, mode, column_rules, index_rules, column_order=None, max_iterations=None)`
2. `total_variants(table, mode, column_rules, index_rules, column_order=None, max_iterations=None)`

### Внутренние генераторы

1. `_make_generator(...)`
2. `_gen_types(...)`
3. `_gen_indexes(...)`
4. `_gen_sequential(...)`
5. `_gen_combined(...)`

## 10. Генерация тестовых SQL (`query_generator.py`)

### Helper-функции классификации типов

1. `_base_type(col)`
2. `_is_integer(col)`
3. `_is_float(col)`
4. `_is_numeric(col)`
5. `_is_datetime(col)`
6. `_is_string(col)`
7. `_is_low_cardinality(col)`
8. `_is_nullable(col)`

### `GeneratedQuery`

Поля: `query`, `description`

### `QueryGenerator`

1. `__init__(table)`
2. `generate()`
3. `_full_scan_queries()`
4. `_datetime_range_queries()`
5. `_order_by_filter_queries()`
6. `_aggregate_queries()`
7. `_group_by_queries()`

### Публичная функция

1. `generate_queries(table)`

## 11. Naming (`naming.py`)

1. `_sanitize(s)`
2. `variant_table_name(original_table, benchmark_id, variant_index)`
3. `parse_variant_name(name)`
4. `is_variant_table(name)`

## 12. Fetcher (`fetcher.py`)

### Модели/исключения

1. `TableMetrics`
   - property: `compression_ratio`
2. `QueryResult`
3. `FetcherError`

### Класс `Fetcher`

Lifecycle:
1. `__init__(connection)`
2. `connect()`
3. `disconnect()`
4. `__enter__()`
5. `__exit__(...)`

Core SQL:
1. `_execute(query, params=None)`

Metadata/DDl:
1. `list_databases(exclude_system=True)`
2. `list_tables(database)`
3. `table_exists(database, table)`
4. `fetch_ddl(database, table)`
5. `fetch_table_ddl(database, table)` (alias)
6. `create_table(table_ddl)`
7. `drop_table(database, table, if_exists=True)`

Data + metrics:
1. `insert_from(source_database, source_table, target_database, target_table, limit=None)`
2. `fetch_metrics(database, table)`
3. `run_query(query)`
4. `_generate_query_id()`
5. `warmup(query)`

Фабрика:
1. `make_fetcher(connection)`

## 13. Core runtime API (`benchmark_engine.py`)

### Runtime модели

1. `_FrozenModel`
2. `TableTarget`
3. `Query`
4. `QueryPlan`
5. `TableBenchmarkPlan`
6. `VariantJob`
7. `BenchmarkVariantResult`
8. `StoredBenchmarkResult`
9. `TopTypeVariant`

`VariantJob` и `BenchmarkVariantResult` содержат `benchmark_run_id` (целое > 0),
общее для всех benchmark'ов, выполняемых в рамках одного запуска конфига.

### Result store

1. `BenchmarkResultStore`
   - `store_result(job, result)`
   - `get_top_type_variants(benchmark_run_id, benchmark_id, source_database, source_table, top_n)`
2. `InMemoryBenchmarkResultStore`
   - тестовая in-memory реализация; в production рекомендуется DB-backed реализация.

### Metadata abstraction

1. `MetadataProvider`
   - `list_databases()`
   - `list_tables(database)`
   - `fetch_table_ddl(database, table)`
2. `FetcherMetadataProvider`
   - `__init__(fetcher)`
   - `list_databases()`
   - `list_tables(database)`
   - `fetch_table_ddl(database, table)`

### `TableSelector`

1. `select_targets(benchmark, provider)`
2. `_resolve_databases(benchmark, provider)`
3. `_resolve_tables(benchmark, databases, provider)`
4. `_deduplicate(targets)`

### `QueryPlanBuilder`

1. `build(table_ddl, queries_config)`
2. `render_for_table(plan, database, table)`

### `BenchmarkPlanner`

1. `__init__(config, providers_by_connection_id, table_selector=None, rule_resolver=None)`
2. `provider_for_connection(connection_id)`
3. `iter_table_plans(benchmark_ids=None)`
4. `_find_table_rule(benchmark, target)`

### `BenchmarkEngine`

1. `__init__(planner, query_builder=None)`
2. `iter_table_plans(benchmark_ids=None)`
3. `prepare_table_context(table_plan)`
4. `build_variant_job(table_plan, raw_query_plan, variant_ddl, variant_meta, total_variants, job_mode=None)`
5. `iter_variant_jobs_for_table_plan(table_plan)`
6. `iter_variant_jobs(benchmark_ids=None)`

### Execution adapter

1. `BenchmarkExecutionAdapter`
   - `execute_variant(job)`
2. `NoopExecutionAdapter`
   - `execute_variant(job)`

### Run id provider

1. `BenchmarkRunIdProvider`
   - `next_benchmark_run_id()`
2. `InMemoryBenchmarkRunIdProvider`
   - serial id в памяти процесса (`1, 2, 3, ...`)
3. `MaxIdBenchmarkRunIdProvider`
   - принимает `max_id_getter()`;
   - выдает `max(existing_id)+1`;
   - хранит локальный reserved id, чтобы не выдавать дубликаты между вызовами.

### `BenchmarkRunner`

1. `__init__(engine, execution_adapter, result_store, run_id_provider=None)`
2. `run(benchmark_ids=None, benchmark_run_id=None)`
3. `_run_sequential(table_plan)`
4. `_next_run_id()`
5. `_execute_and_store(job)`

## 14. Как запускать

### 14.1 Обычное демо

```bash
./venv/bin/python example.py
```

### 14.2 Демо нового sequential top-N

```bash
./venv/bin/python example_sequential_topn.py
```

### 14.3 Тесты

```bash
./venv/bin/python -m pytest -q
```

## 15. Примеры конфигов

1. `benchmark.project.example.json`  
   Базовый mixed пример (`types`, `combined`, table overrides).
2. `benchmark.project.sequential_topn.example.json`  
   Пример двухфазного `sequential` с `sequential_top_n` и локальными override.
3. `connections.example.json`
4. `rule_banks.example.json`
5. `rule_banks.clickhouse_baseline.json`  
   Отдельный большой универсальный baseline bank для ClickHouse (только `by_type`).

## 16. Важные практические детали

1. `TestQueryConfig.weight` пока остается в конфиге для совместимости, но runtime `Query` работает только с текстом запроса.
2. Для `sequential` индексный этап зависит от `score` адаптера, поэтому корректный `execute_variant(...)` критичен.
3. Если у варианта `score=None`, он почти всегда проиграет ранжирование top-N.
4. Если `sequential_top_n` больше количества type-вариантов, фактически берутся все.
5. Автоподстановки builtin rule bank больше нет: если нужны дефолтные правила, укажи `default_rule_banks` в своем JSON.
6. Готовый baseline для ClickHouse вынесен в `rule_banks.clickhouse_baseline.json`.
7. `by_type` матчится строго по полному типу: `LowCardinality(String)` и `LowCardinality` — это разные значения.
8. `column_order_mode="compressed_size_desc"` автоматически расставляет приоритет колонок по убыванию `data_compressed_bytes` в исходной таблице.
9. Для serial run id из БД:

```python
from benchmark_engine import (
    BenchmarkRunner,
    MaxIdBenchmarkRunIdProvider,
    InMemoryBenchmarkResultStore,
)

provider = MaxIdBenchmarkRunIdProvider(
    max_id_getter=lambda: fetch_max_run_id_from_db(),  # верни int | None
)
result_store = InMemoryBenchmarkResultStore()  # в проде: ваш DB-backed store
runner = BenchmarkRunner(
    engine=engine,
    execution_adapter=adapter,
    result_store=result_store,
    run_id_provider=provider,
)
run_id = runner.run()
```
