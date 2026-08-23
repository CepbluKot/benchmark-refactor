# ADR-0002: Python application stack первого релиза

Статус: принято как implementation baseline

Дата: 2026-08-01

## Контекст

Целевой runtime пишется с нуля на Python 3.12. До первого implementation PR нужно
явно выбрать API, persistence, migrations, dependency и test tooling, чтобы framework
решения не проникли в domain случайно. Все production build и runtime операции
должны работать в закрытом контуре через внутренние mirrors и registries.

## Решение

| Область | Baseline |
|---|---|
| Interpreter | CPython `>=3.12,<3.13`, approved patch и image digest |
| Control API | FastAPI, REST/JSON, generated OpenAPI |
| Boundary validation | Pydantic v2 только в API/config/plugin boundaries |
| PostgreSQL access | SQLAlchemy 2 repositories поверх psycopg 3 |
| Schema migrations | Alembic, отдельный migrator entrypoint |
| Workflow SDK | Hatchet Python SDK |
| Plugin wire protocol | versioned Protobuf + gRPC; small reference payloads |
| CLI | Typer как клиент того же Control API |
| Dependency management | `uv` lockfile; offline wheelhouse/internal Python mirror |
| ClickHouse adapter | `clickhouse-connect` только внутри ClickHouse plugin |
| Tests | pytest, Hypothesis, real component/E2E fixtures |
| Telemetry | OpenTelemetry APIs/SDK, Prometheus-compatible metrics, JSON logs |
| Packaging | pinned OCI images из внутреннего registry |

Точные dependency versions фиксируются lockfile и проверяются offline CI. Выбор
конкретной PostgreSQL major version, S3-compatible implementation, Secret Manager и
deployment substrate остаётся отдельным infrastructure decision после compatibility
и resource spike. Browser UI не входит в v1, поэтому frontend stack не выбирается.

## Architecture constraints

- Framework DTO не попадает в `experiment_domain` и `experiment_engine`.
- Domain зависит только от собственных immutable values/protocols и standard library.
- SQLAlchemy models/repositories находятся в `adapters/postgres`.
- Hatchet decorators/client types не попадают в domain; они ограничены
  `core_workflows`, `core_tasks` и `adapters/hatchet`.
- `clickhouse-connect` разрешён только в `plugins/clickhouse` и его composition root.
- CLI не импортирует repositories или application services и использует Control API.
- Workers не запускают migrations.
- Generated Protobuf code хранится/проверяется воспроизводимо, а toolchain доступен
  без Internet egress.

## Последствия

- FastAPI/Pydantic дают UI-ready OpenAPI contract, но не определяют domain model.
- SQLAlchemy/Alembic упрощают migration ownership, но optimistic assumptions не
  заменяют database uniqueness, transactions и fencing constraints.
- `uv` не получает права обращаться к публичному PyPI в production build; lockfile
  должен разрешаться из approved mirror/offline bundle.
- Другой framework, ORM, migration tool, dependency manager, Python minor или новый
  production language требует superseding ADR и migration impact assessment.
- Декларативные deployment files и third-party Hatchet binaries не считаются
  дополнительным maintained application language.
