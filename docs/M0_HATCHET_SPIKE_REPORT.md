# M0 Hatchet architecture spike: отчёт

Статус на 2026-08-01: **M0-PARTIAL**. Hatchet подтверждён как технически
перспективный orchestrator, но ещё не принят как production baseline. Legacy Celery
runtime не удалён и не подключён к spike.

## Реализованный vertical slice

- Python `>=3.12,<3.13` workspace без imports из legacy `src`;
- real split Hatchet API/Engine с PostgreSQL-only queue/pub-sub;
- отдельные product PostgreSQL database, owner, app role и Alembic migrations;
- atomic Study submission + leased outbox + idempotent Hatchet start;
- durable core task с release-specific child routes;
- отдельный toy plugin image без PostgreSQL client/dependency;
- раздельные versioned Protobuf Attempt/Resource и core-only Finalization API;
- canonical operation contract fingerprint, sealed в job/outbox/Hatchet payload и
  проверяемый до выдачи attempt fence;
- domain attempt, monotonic fence, one accepted result и exact terminal commit;
- attempt-scoped resource registry и независимый Reaper;
- Control API, который читает product projection, а не Hatchet internals;
- hard Compose limits `1 CPU / 1024 MiB` на каждый service/job;
- optional operator UI profile, не являющийся product UI.

Запуск и fault injection описаны в
[`deploy/hatchet_spike/README.md`](../deploy/hatchet_spike/README.md).

## Зафиксированное evidence

Проверялся реальный Docker Compose deployment, а не mock Hatchet:

- Hatchet server `v0.98.9`, `hatchet-sdk==1.37.0`;
- Python image даёт CPython `3.12.13`;
- PostgreSQL image даёт `15.18` — это M0 choice, production major ещё не locked;
- normal full path дважды завершился `RECOMMENDED`;
- повтор submission с тем же key/payload вернул тот же Study;
- тот же key с другим input получил `409 IDEMPOTENCY_CONFLICT`;
- faults `before_side_effect`, `after_side_effect` и `after_commit`: toy worker
  завершался с code `86`, Hatchet делал повторную delivery, каждый Study завершился
  `RECOMMENDED`;
- первые два fault дали `2 attempts / 1 accepted_result`, fault после commit —
  `1 attempt / 1 accepted_result`; orphan resources после lease перешли в `REAPED`;
- при остановленном plugin pool core workflow дошёл до ожидания child task; cancel
  command стал `DISPATCHED`, а product Study завершился `CANCELLED` без attempt;
- plugin image не содержит importable `sqlalchemy` или `psycopg`, а его Docker
  networks не дают маршрута к Finalization API/product PostgreSQL.
- PostgreSQL ACL check: `hatchet` не имеет `CONNECT` к `benchmark_control`, а
  `benchmark_app` — к Hatchet database.

Один fault-recovery/low-activity snapshot активных default components показал RSS от
`22 MiB` до `211 MiB`; все 14 default services/jobs имели
`NanoCpus=1000000000`, memory limit `1073741824`, pids limit `256`,
`no-new-privileges` и `OOMKilled=false`. В момент snapshot product DB имела 5
connections, Hatchet DB — 16.
Это точечное наблюдение, не capacity trace и не HAT-01 PASS.

### Pinned infrastructure images M0

| Component | Exact image |
|---|---|
| Python | `python:3.12-alpine@sha256:f7fd610959cae736251523b54eb26cecb74f60ffa60bf39d9faccf128b526ab8` |
| PostgreSQL | `postgres:15-alpine@sha256:cd17e2ac98240fce1541ad2a803b34009b4eea5aec8a832363cdc7eca62e722e` |
| Hatchet API | `ghcr.io/hatchet-dev/hatchet/hatchet-api@sha256:ecb806e8464a30177c4ac0f3541d76c6f5b362ab0665003e02f767d0b0c7b83b` |
| Hatchet Engine | `ghcr.io/hatchet-dev/hatchet/hatchet-engine@sha256:5c1d23311d7117f9a68c32ab43b9a8b814f7b50982fe310d9d0f720f722e5ac9` |
| Hatchet Frontend | `ghcr.io/hatchet-dev/hatchet/hatchet-frontend@sha256:4ba75418ccb0a1b1bd0a78ca0e354c61f7b7c43afcfa83f6bf2b1d6a8eeab44b` |
| Hatchet Migrate | `ghcr.io/hatchet-dev/hatchet/hatchet-migrate@sha256:fa59227943ca3b607ed025e393cf267b554568b711bdb4b80a15a4581ad78a98` |
| Hatchet Admin | `ghcr.io/hatchet-dev/hatchet/hatchet-admin@sha256:3fe433db638f8c2570aa28dd6bc2578774399390880639cce4ea6918598384f1` |
| Caddy | `caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d` |

Local application images имеют development tags `benchmark-m0-*:local`; production
release обязан pin-ить их собственные signed digests.

## Известные production blockers

- gRPC внутри M0 использует plaintext/insecure channel. Сетевая сегментация не
  заменяет mTLS workload identity и method/release authorization;
- starter/core/plugin пока разделяют один Hatchet worker token, который истекает
  через семь дней; overlap rotation и scoped credentials не реализованы;
- local Compose передаёт database URLs/passwords через environment/config volumes;
  production требует internal secret manager и short-lived grants;
- Reaper маркирует toy resource как `REAPED`, но ещё не запускает versioned physical
  cleanup через pinned database plugin с retries/quarantine;
- нет reconciler для terminal Hatchet failure и bounded outbox dead-letter policy:
  failure/worker-absence outage matrix остаётся HAT-07;
- build использует public package/image sources, а `ingress` network не доказывает
  deny-all egress. Нужен imported offline bundle и отдельный closed-contour profile.

## HAT-01…HAT-10

Строгий итог: **0 PASS / 6 PARTIAL / 4 NOT RUN**. Наличие кода или единичный ручной
прогон не считается полным acceptance proof.

| Gate | Статус | Что уже доказано | Что блокирует PASS |
|---|---|---|---|
| HAT-01 resources | PARTIAL | Все services/jobs имеют hard limit; default runtime помещается в envelope в одном snapshot | Нет idle/steady/burst traces, p95/p99, queue delay, connection/restart timeline и UI profile measurement |
| HAT-02 100 active | PARTIAL | Atomic advisory-lock admission; integration проверяет 100 accepted, 101-й rejected; toy concurrency=4 | Нет 100 real nonterminal Hatchet runs, fairness и отдельных profile/source/operation quotas |
| HAT-03 checkpoint replay | NOT RUN | Durable task и stable child keys существуют | Нет multi-checkpoint loop, kill/eviction matrix и snapshot identity comparison |
| HAT-04 at-least-once/fence | PARTIAL | DB tests для duplicate/stale fence; все три real toy fault points оставили один accepted result | Нет real late-resource race с физическим backend object; evidence ещё не CI artifact |
| HAT-05 cancellation | PARTIAL | Product desired state/fence/cancel outbox, independent Reaper и Compose cancel во время child wait доказаны | Нет отмены во время physical I/O/materialization/finalize и backend cancel evidence |
| HAT-06 A/B routing | PARTIAL | Release-specific routes и sealed release checks | Нет одновременно поднятых A/B pools, pinned old run, drain guard и worker preflight |
| HAT-07 outage matrix | NOT RUN | Leased outbox, idempotency collision handling, restart policies | Не выполнены отдельные API/Engine/DB/worker outages и reconciliation missing terminal commit |
| HAT-08 continuation | NOT RUN | `continuation_no` присутствует в contract | Нет successor command, sealed snapshot chain и bound measurement |
| HAT-09 blocked egress | NOT RUN | External images pinned; telemetry/integrations disabled; internal segmented networks | Build использовал Internet; нет offline bundle/deny-egress/UI-login/backup-restore trace; Frontend имеет public/CDN references |
| HAT-10 authority | PARTIAL | Status берётся из product PG; terminal требует exact accepted result | Нет intentional Hatchet/product divergence и сценария Hatchet-completed без business terminal commit |

## Вывод и следующий gate

Architecture boundary жизнеспособна: Hatchet можно оставить единственным кандидатом
и продолжить spike, не создавая fallback на Celery/Temporal. Однако решение остаётся
условным. Следующий минимальный пакет — автоматизированный Compose fault suite для
всех HAT-04 points, real cancellation, A/B pools, outage/reconciliation matrix,
bounded continuation и полностью offline deny-egress bundle/profile.

ClickHouse full path является более поздним plugin/release acceptance gate. M0
проверяет toy path и не должен притворяться, что уже доказал ClickHouse semantics,
S3 artifacts или научную валидность benchmark algorithm.
