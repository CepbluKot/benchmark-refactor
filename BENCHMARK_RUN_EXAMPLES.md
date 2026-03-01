# Примеры Запуска Бенчмарков (1 Таблица)

Ниже два отдельных примера вызова:
1. `legacy` стратегия (одна таблица)
2. `sequential_phased_topn_strategy` (новая стратегия, одна таблица)
3. `same_variant_compare` — запуск legacy+phased на одном и том же варианте таблицы

## Общие требования

1. Должны быть доступны ClickHouse, RabbitMQ/другой broker и Redis.
2. Worker запускать с `-E`:

```bash
export BENCH_CELERY_BROKER_URL='pyamqp://guest:guest@localhost:5672//'
export BENCH_CELERY_BACKEND_URL='rpc://guest:guest@localhost:5672//'
export BENCH_RESULT_STORE_REDIS_URL='redis://localhost:6379/0'

./venv/bin/celery -A src.benchmark_runtime.implementations.clickhouse_celery.tasks worker -E --loglevel=INFO
```

3. Для запуска `main.py` обязателен Redis для result-store dedup-lock.

## Пример 1: Legacy (одна таблица)

Используем benchmark:
- `id`: `bench_types_only_example`
- `strategy`: `types_strategy` (legacy)
- таблица: `analytics.user_events`
- источник: `configs/benchmarks.example.json`

### Шаги

1. В `encode_configs_base64.py` выставить пути:

```python
CELERY_JSON_PATH = Path("configs/celery.example.json")
CONNECTIONS_JSON_PATH = Path("configs/connections.example.json")
RULE_BANKS_JSON_PATH = Path("configs/rule_banks.example.json")
BENCHMARKS_JSON_PATH = Path("configs/benchmarks.example.json")
```

2. Сгенерировать `.env`:

```bash
./venv/bin/python encode_configs_base64.py > .env
```

3. Добавить в `.env` (или export перед запуском):

```bash
BENCH_RESULT_STORE_REDIS_URL=redis://localhost:6379/0
```

4. Запустить только этот benchmark:

```bash
BENCH_BENCHMARK_IDS=bench_types_only_example ./venv/bin/python main.py
```

## Пример 2: Новый Phased (одна таблица)

Используем benchmark:
- `id`: `bench_hits_postgres_sequential_topn`
- `strategy`: `sequential_phased_topn_strategy`
- таблица: `default.hits_postgres`
- источник: `configs/hits_postgres/benchmarks.hits_postgres.sequential_topn.local.json`

### Шаги

1. В `encode_configs_base64.py` выставить пути:

```python
CELERY_JSON_PATH = Path("configs/hits_postgres/celery.hits_postgres.local.json")
CONNECTIONS_JSON_PATH = Path("configs/hits_postgres/connections.hits_postgres.local.json")
RULE_BANKS_JSON_PATH = Path("configs/hits_postgres/rule_banks.hits_postgres.local.json")
BENCHMARKS_JSON_PATH = Path("configs/hits_postgres/benchmarks.hits_postgres.sequential_topn.local.json")
```

2. Сгенерировать `.env`:

```bash
./venv/bin/python encode_configs_base64.py > .env
```

3. Добавить в `.env` (или export перед запуском):

```bash
BENCH_RESULT_STORE_REDIS_URL=redis://localhost:6379/0
```

4. Запустить только этот benchmark:

```bash
BENCH_BENCHMARK_IDS=bench_hits_postgres_sequential_topn ./venv/bin/python main.py
```

## Пример 3: Сравнение одного и того же варианта (legacy vs phased)

Используем benchmark-файл:
- `configs/hits_postgres/benchmarks.hits_postgres.same_variant.compare.local.json`

В нём два `benchmark_id`:
- `bench_same_variant_compare_legacy`
- `bench_same_variant_compare_phased`

Оба гоняют одну и ту же таблицу `default.hits_postgres` и один и тот же набор правил
(тип/кодек/индекс), чтобы сравнить именно поведение стратегий и метрики.

### Запуск в один шаг

```bash
./venv/bin/python run_benchmark_example.py same_variant_compare
```

### Или вручную через `main.py`

```bash
BENCH_BENCHMARK_IDS=bench_same_variant_compare_legacy,bench_same_variant_compare_phased \
./venv/bin/python main.py
```

### SQL для сравнения результатов

Готовый SQL-шаблон:
- `compare_same_variant_results.sql`
