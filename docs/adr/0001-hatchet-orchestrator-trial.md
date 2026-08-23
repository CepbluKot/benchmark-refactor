# ADR-0001: Hatchet как целевой orchestrator для architecture spike

Статус: принято для architecture spike; production adoption условно

Дата: 2026-08-01

## Контекст

Greenfield runtime должен выполнять до 100 одновременно активных исследований в
закрытом контуре. Долгоживущий адаптивный поиск требует durable order, delivery,
retries, deadlines, cancellation, backpressure и восстановления после падения
процесса. Команда поддерживает production-код только на Python 3.12 и не готова
эксплуатировать self-hosted Temporal только ради одного проекта.

Обычная Python-очередь не закрывает этот контракт: поверх неё пришлось бы заново
строить durable workflow state, timers, recovery, version routing и operational UI.
Airflow, Dagster и аналогичные data orchestrators могут исполнять этапы, но хуже
соответствуют динамическому многораундовому алгоритму. Argo Workflows остаётся
разумной альтернативой только при уже предоставленном Kubernetes.

## Решение

1. Hatchet OSS self-hosted выбирается единственным target orchestrator для
   architecture spike. Temporal не является параллельным runtime или fallback.
2. Production-кандидат использует раздельные Hatchet API, Engine и Frontend, а не
   `hatchet-lite`, который предназначен для development и low-volume use cases.
3. Hatchet использует PostgreSQL как persistence и message queue. RabbitMQ в
   минимальный target stack не входит; задаются
   `SERVER_MSGQUEUE_KIND=postgres` и `SERVER_MSGQUEUE_PUBSUB_KIND=postgres`.
4. Для пилота Hatchet и product business state могут использовать один физический
   PostgreSQL deployment, но только через разные databases, owners, credentials и
   migration paths. Приложение не читает внутренние таблицы Hatchet.
5. PostgreSQL product database остаётся authoritative для manifests, accepted
   results, attempt fencing, resources, ranking snapshots и terminal outcomes.
   Hatchet authoritative только для execution progression и task delivery.
6. Hatchet workflow/task payloads содержат только малые schema-versioned references,
   identifiers и hashes. Credentials, full DDL, raw observations и physical cleanup
   locators туда не попадают.
7. Backend plugin workers остаются отдельными pinned OCI deployments. Они не
   импортируются Control Service и не получают unrestricted product PostgreSQL
   credentials.
8. Runtime fallback на Celery, Temporal или второй orchestrator не реализуется. Если
   spike не проходит gate, этот ADR сначала supersede-ится новым решением.
9. Closed-contour profile задаёт `SERVER_SECURITY_CHECK_ENABLED=false`, отключает
   public integrations/telemetry и зеркалирует все images/charts/wheels во внутреннюю
   инфраструктуру.

Hatchet документирует self-hosted durable task queue/workflow execution, retries,
concurrency и rate limiting. Эти свойства позволяют проверить требуемую модель, но
не отменяют at-least-once side-effect safety на нашей стороне.

## Authority boundary

| Authority | Владеет | Не владеет |
|---|---|---|
| Hatchet | workflow/task progression, delivery, timers, retry scheduling, cancellation signal, concurrency | scientific outcome, accepted result, physical resource ownership |
| Product PostgreSQL | immutable business facts, attempts/fences, resources, rankings, terminal outcome, audit projection | внутреннее состояние и migrations Hatchet |
| Artifact store | immutable content-addressed large bodies | lifecycle и terminal state |
| Database plugin | backend semantics и physical operations | retries, fencing, ranking и control migrations |

Workflow считается успешно завершённым только после идемпотентного commit terminal
business outcome в product PostgreSQL. Если commit прошёл, а worker упал до ответа
Hatchet, повтор читает accepted fact и возвращает тот же результат.

## Versioning и routing contract

Каждый `StudyManifest` pin-ит core workflow release/exact worker OCI digest, Hatchet
SDK/task-contract version, plugin semantic version/exact OCI digest, descriptor и
schema hashes, protocol versions и public profile revisions. Spike должен доказать
следующую стратегию:

- task/workflow registration names включают совместимую contract/build version;
- отдельный worker deployment обслуживает одну plugin release/zone/resource class;
- новый release не перехватывает задачи уже запущенного pinned Study;
- старый pool drain-ится только после terminal studies и cleanup;
- отсутствие exact compatible worker обнаруживается до manifest seal и завершается
  явной ошибкой, а не исполнением на latest worker.

Эта стратегия является требованием проекта, а не заявленным без проверки свойством
Hatchet worker affinity.

## Обязательный acceptance spike

Production adoption разрешён только после воспроизводимого прогона, в котором:

1. каждый Hatchet API, Engine, Frontend, migrator/admin job, PostgreSQL, core worker и
   toy/plugin worker работает с hard limit не более `1 CPU / 1024 MiB`;
2. 100 active Studies не создают unbounded fan-out, а physical attempts ограничены
   отдельными per-profile, per-plugin и per-operation quotas;
3. worker kill до side effect, после side effect и после accepted commit не создаёт
   второй accepted result;
4. late attempt с устаревшим fence не меняет state и не удаляет новый resource;
5. cancellation проходит через workflow, active attempt и cleanup/reaper path;
6. restart API, Engine, worker и PostgreSQL по отдельности приводит к documented
   recovery либо явному fail-closed outcome;
7. deployment release B не меняет код, исполняющий pinned Study release A;
8. установка, migrations, startup и полный toy path M0 проходят при
   заблокированном Internet egress и не обращаются к `security.hatchet.run` либо
   другим public endpoints;
9. payload/history growth остаётся bounded на максимальном candidate plan;
10. Hatchet operational UI не является источником product status: CLI и будущий UI
    получают его только из Control API/PostgreSQL projection.

Blocked-egress ClickHouse full path остаётся обязательным более поздним
plugin/release acceptance gate. Он не подменяет изолированный toy M0 и не может быть
заявлен пройденным на основании этого spike.

Официальные Helm defaults укладывают CPU requests ниже одного core, но для части
компонентов задают memory request/limit ровно `1024Mi`. Это подтверждает возможность
spike, но не является доказательством production headroom. CI-профиль с меньшими
requests также не считается capacity proof.

## Последствия

- `adapters/hatchet` заменяет планировавшийся `adapters/temporal`.
- Hatchet durable orchestration tasks следуют его checkpoint/replay contract: код
  между checkpoints детерминирован, не читает DB/network/filesystem и не использует
  ambient clock/random/UUID для control flow; I/O выполняют child tasks.
- Workflow code не полагается на Temporal-specific clocks/version APIs,
  Continue-As-New или Temporal Worker Versioning. Clock, IDs и randomness приходят
  из persisted child-task outputs/facts.
- Большой поиск разбивается на bounded stages, batches и child runs. Новый batch
  открывается только из sealed PostgreSQL snapshot/hash.
- Hatchet task-run attempt и domain attempt являются разными identities.
- Все I/O tasks идемпотентны и имеют bounded timeout/retry policy.
- Hatchet cancellation трактуется как cooperative signal; product desired state,
  lease/fence и independent Reaper остаются authoritative.
- Hatchet Frontend используется для operator diagnostics, но не заменяет product UI
  и не доступен конечному клиенту как privileged control path.

## Рассмотренные альтернативы

- Temporal отклонён для v1 из-за несоразмерной эксплуатационной стоимости.
- Airflow отклонён как основной orchestrator из-за static-DAG/data-pipeline модели и
  необходимости внешнего adaptive controller.
- Argo Workflows остаётся fallback architecture option только при наличии Kubernetes,
  но не разворачивается параллельно.
- DBOS требует иной recovery/operations trade-off и остаётся минимальным fallback.
- Restate потребовал бы самостоятельно реализовать часть admission/rate-limit
  semantics.
- Celery, Dramatiq, Taskiq, Procrastinate и другие очереди являются task transport,
  а не заменой durable workflow authority.

## Ссылки

- [Hatchet architecture and guarantees](https://docs.hatchet.run/v1/architecture-and-guarantees)
- [Hatchet durable tasks](https://docs.hatchet.run/v1/durable-tasks)
- [Hatchet cancellation](https://docs.hatchet.run/v1/cancellation)
- [Hatchet Lite](https://docs.hatchet.run/self-hosting/hatchet-lite)
- [Hatchet configuration options](https://docs.hatchet.run/self-hosting/configuration-options)
- [Hatchet Helm API defaults](https://github.com/hatchet-dev/hatchet-charts/blob/main/charts/hatchet-api/values.yaml)
- [Hatchet Helm lightweight CI profile](https://github.com/hatchet-dev/hatchet-charts/blob/main/charts/hatchet-stack/ci/ct-values.yaml)
