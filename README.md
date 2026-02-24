# DDL Benchmark Engine

Инструмент для автоматического DDL-бенчмарка: перебирает варианты схемы таблиц (типы, кодеки, индексы), запускает тестовые запросы и помогает выбрать лучший вариант по `score`.

Важно: текущий `main.py` — это demo-runner (in-memory таблицы + `NoopExecutionAdapter`).
Для реального прогона на вашем ClickHouse нужен рабочий `BenchmarkExecutionAdapter`.

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
6. Генерируются DDL-варианты и `VariantJob`.
7. Каждый job выполняется через `BenchmarkExecutionAdapter`.
8. Результат сразу пишется в `BenchmarkResultStore` (без накопления большого списка в памяти).

Если режим `sequential`:
1. Сначала гоняются варианты `types`.
2. По score выбираются top-N (`sequential_top_n`).
3. Только для top-N запускаются варианты `indexes`.

Лимиты вставки строк (`insert_rows_limit`/`insert_rows_limits`) применяются по приоритету:
1. `insert_rows_limits[variant_meta.mode]`
2. `insert_rows_limits[job.mode]`
3. `insert_rows_limit`

<a id="layers"></a>
## Слои системы (человеческим языком)

Ниже не про “академическую архитектуру”, а про то, как реально движутся данные.

### Слой 1. Описание формата конфига

Что делает:
1. Описывает все поля JSON и правила валидации.
2. Отсекает кривые значения на входе.

Где:
1. `src/models.py`

На входе:
1. Сырые JSON-объекты.

На выходе:
1. Валидные Pydantic-модели (`BenchmarkConfig`, `BenchmarkRootConfig` и др.).

### Слой 2. Сборка конфига из файлов/секций

Что делает:
1. Склеивает `connections/rule_banks/benchmarks/celery`.
2. Проверяет ссылки между секциями (`connection_id`, `rule_bank`, `default_rule_banks`).

Где:
1. `src/loader.py`
2. `validate_json_config.py` (CLI-проверка)
3. `settings.py` + `main.py` (вариант через env base64)

На входе:
1. `benchmark.project.json` или 4 JSON-секции.

На выходе:
1. Готовый `BenchmarkRootConfig`.

### Слой 3. Резолвинг правил

Что делает:
1. Сливает global + table override.
2. Подтягивает `rule_bank` и `default_rule_banks`.
3. Превращает config-правила в runtime-правила генератора.

Где:
1. `src/resolver.py`

На входе:
1. `RulesConfig` + DBMS + режимы источника правил.

На выходе:
1. `ResolvedRules` (`column_rules`, `index_rules`, `column_order`).

### Слой 4. Получение метаданных из источника

Что делает:
1. Дает список БД/таблиц.
2. Возвращает исходный DDL таблицы.
3. Опционально возвращает размеры колонок для `column_order_mode="compressed_size_desc"`.

Где:
1. Контракт: `src/benchmark_runtime/contracts/metadata.py`
2. Реализация под fetcher: `src/benchmark_runtime/implementations/fetcher/metadata.py`
3. Demo-реализации: `main.py`, `examples/*`

На входе:
1. `connection_id`, `database`, `table`.

На выходе:
1. `TableDDL` и metadata для планирования.

### Слой 5. Планирование по таблицам

Что делает:
1. Раскрывает selectors (`databases`, `tables`).
2. Для каждой таблицы собирает единый план с override.
3. Вшивает `strategy`, внутренний `mode`, лимиты, queries, celery.

Где:
1. `TableSelector` и `BenchmarkPlanner` в `src/benchmark_engine.py`

На входе:
1. `BenchmarkRootConfig` + `MetadataProvider`.

На выходе:
1. Поток `TableBenchmarkPlan`.

### Слой 6. Генерация вариантов DDL

Что делает:
1. Генерирует DDL-варианты по mode (`types`, `indexes`, `combined`, `sequential`).
2. Считает `total_variants`.

Где:
1. `src/variant_generation/contracts/` и `src/variant_generation/implementations/`
2. `src/variant_generation/registry.py`
3. `src/combiner.py` (backward-compatible фасад)
4. Доменные генераторы: `src/column_variants.py`, `src/index_variants.py`

На входе:
1. `TableDDL` + runtime rules + mode.

На выходе:
1. `(variant_ddl, VariantMeta)`.

### Слой 7. Сборка job-ов для исполнения

Что делает:
1. Превращает variant DDL в `VariantJob`.
2. Рендерит SQL-запросы с именем variant-таблицы.
3. Вычисляет итоговый `insert_rows_limit` по приоритету.

Где:
1. `BenchmarkEngine` в `src/benchmark_engine.py`
2. `src/query_generator.py`
3. `src/naming.py`

На входе:
1. `TableBenchmarkPlan` + source DDL + варианты из combiner.

На выходе:
1. Поток `VariantJob`.

### Слой 8. Оркестрация исполнения

Что делает:
1. Берет `TableBenchmarkPlan` и выбирает table strategy по `strategy`.
2. Для `types_strategy/indexes_strategy/combined_strategy` просто прогоняет jobs.
3. Для `sequential_topn_strategy` делает 2 стадии: types -> top-N -> indexes.

Где:
1. `BenchmarkRunner` в `src/benchmark_engine.py`
2. Контракт стратегии: `src/benchmark_runtime/contracts/table_strategy.py`
3. Реализации: `src/benchmark_runtime/implementations/table_strategy/*`

На входе:
1. `TableBenchmarkPlan`.

На выходе:
1. Вызовы execution adapter + сохраненные результаты.

### Слой 9. Фактическое выполнение SQL

Что делает:
1. Создает variant-таблицу.
2. Копирует данные, гоняет warmup/test.
3. Считает `score`.

Где:
1. Контракт: `src/benchmark_runtime/contracts/execution.py`
2. Встроенный demo: `src/benchmark_runtime/implementations/noop/execution.py`
3. Реальный прод-адаптер — ваша реализация.

На входе:
1. `VariantJob`.

На выходе:
1. `BenchmarkVariantResult`.

### Слой 10. Хранилище результатов и top-N

Что делает:
1. Сохраняет результат каждого варианта сразу (без большого списка в памяти).
2. Возвращает `top type variants` для sequential index-стадии.

Где:
1. Контракт: `src/benchmark_runtime/contracts/result_store.py`
2. In-memory: `src/benchmark_runtime/implementations/inmemory/result_store.py`

На входе:
1. `VariantJob` + `BenchmarkVariantResult`.

На выходе:
1. Персистентные записи + top-N выборки.

### Слой 11. Run ID и запуск run-а

Что делает:
1. Выдает единый `benchmark_run_id` на весь запуск.
2. Позволяет serial запуск в памяти или от `max(existing_id)+1`.

Где:
1. Контракт: `src/benchmark_runtime/contracts/run_id.py`
2. Реализации: `src/benchmark_runtime/implementations/inmemory/run_id.py`, `src/benchmark_runtime/implementations/run_id/max_id.py`

На входе:
1. Сигнал запуска.

На выходе:
1. Корректный `benchmark_run_id`.

### Что важно помнить про слои

1. `combiner` отвечает только за генерацию вариантов, не за исполнение и не за score.
2. `runner` отвечает за оркестрацию исполнения, в том числе за sequential top-N.
3. Контракты и реализации разделены: `contracts/` и `implementations/`.
4. Старые импорты сохранены через re-export, чтобы не ломать совместимость.

<a id="checklist"></a>
## Чек-лист перед первым запуском

1. В `connections.json` есть нужный `connection_id`.
2. В `benchmarks.json` этот `connection_id` указан в каждом benchmark.
3. Если используете `rule_bank`, он реально существует в `rule_banks.json`.
4. Если `queries.mode = "manual"`, в `test_queries` есть хотя бы один запрос.
5. Конфиги проходят валидацию через `validate_json_config.py`.

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
      "max_iterations": 20,
      "sequential_top_n": 2,
      "insert_rows_limit": 1000000,
      "insert_rows_limits": {
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
            "weight": 1.0
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

3. Запусти:

```bash
./venv/bin/python main.py
```

Важно: это demo-runner (без реального SQL execution).

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

Для реального прогона нужны 3 вещи:
1. `MetadataProvider`, который читает реальные таблицы из ClickHouse.
2. `BenchmarkExecutionAdapter`, который реально создаёт variant-таблицы, вставляет данные, гоняет warmup/test SQL и считает score.
3. `BenchmarkResultStore` (обычно DB-backed), куда сохраняются результаты.

Примечание:
1. Реальные интерфейсы лежат в `src/benchmark_runtime/contracts/*`.
2. Встроенные реализации лежат в `src/benchmark_runtime/implementations/*`.
3. Импорт через `benchmark_engine` сохранён для обратной совместимости.

Минимальный шаблон:

```python
from loader import load_config
from benchmark_engine import (
    BenchmarkPlanner,
    BenchmarkEngine,
    BenchmarkRunner,
    FetcherMetadataProvider,
)
from fetcher import make_fetcher

config = load_config("configs/benchmark.project.local.json")
connection = next(c for c in config.connections if c.id == "prod_ch")
fetcher = make_fetcher(connection)

provider = FetcherMetadataProvider(fetcher)
planner = BenchmarkPlanner(config=config, providers_by_connection_id={"prod_ch": provider})
engine = BenchmarkEngine(planner=planner)

runner = BenchmarkRunner(
    engine=engine,
    execution_adapter=YourClickHouseExecutionAdapter(fetcher),  # реализуете сами
    result_store=YourResultStore(),  # реализуете сами
)
run_id = runner.run()
print(run_id)
```

Если нужен быстрый ориентир по структуре адаптера, посмотри:
- `examples/example.py`
- `examples/example_sequential_topn.py`

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

### `benchmarks.json`

Корень:
- `benchmarks`: список benchmark-конфигов.

Главные поля benchmark:
- `id`, `connection_id`, `strategy`
- `databases`, `tables`
- `global_rules`, `table_rules`
- `max_iterations`, `sequential_top_n`
- `insert_rows_limit`, `insert_rows_limits`
- `queries`
- `column_rules_mode`, `index_rules_mode`

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
Проверь, что есть `index_rules`, `sequential_top_n > 0`, и адаптер возвращает `score`.

6. Включён `global_bank_only`, но нет доступного bank.
Либо укажи `global_rules.rule_bank`, либо настрой `default_rule_banks` для своего DBMS.

<a id="dev"></a>
## Для разработчиков (технические детали)

### Как это работает внутри

Если коротко, ядро построено как `planner -> engine -> runner`.

1. `loader` + `models` валидируют JSON и собирают `BenchmarkRootConfig`.
2. `BenchmarkPlanner` раскрывает селекторы БД/таблиц и строит `TableBenchmarkPlan`.
3. `BenchmarkEngine` на основе плана генерирует варианты DDL и превращает их в `VariantJob`.
4. `BenchmarkRunner` выполняет jobs через `BenchmarkExecutionAdapter`.
5. Каждый результат сразу сохраняется в `BenchmarkResultStore`.

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
2. Класс удобно размещать в `src/benchmark_runtime/implementations/` (например, отдельный подпакет `clickhouse/`).
3. Внутри `execute_variant(job)` обычно делаются:
   - создание variant-таблицы;
   - `INSERT INTO ... SELECT ...` (с учётом `job.insert_rows_limit`);
   - warmup-запросы;
   - test-запросы;
   - расчёт итогового `score`;
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
8. `src/benchmark_runtime/implementations/run_id/` — `MaxIdBenchmarkRunIdProvider`.
9. `src/benchmark_runtime/implementations/table_strategy/` — built-in стратегии выполнения.
10. `src/benchmark_runtime/types.py` — runtime DTO для planner/engine/runner.
11. `src/variant_generation/contracts/` — контракт генерации вариантов.
12. `src/variant_generation/implementations/` — built-in стратегии генерации (`types/indexes/combined/sequential`).
13. `src/variant_generation/registry.py` — реестр стратегий генерации.
14. `src/combiner.py` — backward-compatible фасад над `variant_generation`.
15. `src/fetcher.py` — ClickHouse-fetcher.
16. `validate_json_config.py` — CLI-валидатор JSON по пути.
17. `configs/*.example.json` — примеры конфигов.
18. `LLM_CONTEXT.md` — подробный технический контекст для LLM-агентов.

### Что проверить после изменений

```bash
# Полный тест-ран
./venv/bin/python -m pytest -q

# Тесты валидатора конфигов
./venv/bin/python -m pytest tests/test_validate_json_config.py -q

# Проверка JSON-синтаксиса конкретного файла
./venv/bin/python -m json.tool configs/benchmarks.example.json >/dev/null
```
