# Целевая архитектура clean-slate rewrite

Статус: Architecture RFC, только дизайн, без реализации

Дата: 2026-08-01

## 0. Принятые решения

Этот RFC исходит из принятых продуктовых и эксплуатационных решений:

1. текущая Python-реализация не рефакторится по частям, а удаляется и пишется заново;
2. первый рабочий backend — ClickHouse, но experiment/orchestration core не должен
   зависеть от ClickHouse и обязан допускать будущие database plugins;
3. весь поддерживаемый production-код первого релиза пишется только на Python 3.12;
4. production работает в закрытом контуре без Internet egress и видит только
   внутреннюю инфраструктуру;
5. Hatchet, PostgreSQL и S3-compatible artifact storage полностью self-hosted;
6. capacity target первого релиза — не более 100 одновременно активных studies;
7. browser UI потенциально нужен, но не входит в v1; v1 предоставляет CLI и
   UI-ready Control API;
8. end-user accounts, RBAC, multi-tenancy и corporate IdP integration не входят в v1;
9. организационных ограничений по лицензиям сейчас нет.

Следствия:

- нет compatibility facades, legacy imports, payload v1, dual-write и shadow runtime;
- старый код не переносится в каталог legacy и не импортируется новой системой;
- перед удалением из него извлекаются только требования, golden/anti-golden fixtures,
  эксплуатационные сценарии и известные failure cases;
- Git tag/history и архивный release сохраняют provenance, но не являются частью
  нового runtime;
- новая config schema, control schema, job protocol и result model начинаются с v1;
- существующие ClickHouse result tables остаются read-only historical data;
- при необходимости для истории создаётся отдельный offline reader/exporter, а не
  compatibility layer внутри новой системы;
- generic core управляет воспроизводимым экспериментом;
- database plugin понимает конкретные schema, workload, sampling, transformations,
  execution и backend-specific metrics;
- нельзя создавать «универсальный DDL» или общий SQL AST для всех СУБД;
- production runtime строится как один product/codebase с Control Service, Hatchet
  workflows/tasks и изолированными backend worker pools;
- Hatchet является authoritative execution-progress engine и task transport;
- PostgreSQL хранит immutable business state, manifests, accepted results, fencing,
  resource registry и audit projection;
- plugins поставляются pinned OCI releases с language-neutral task contracts;
- Celery, RabbitMQ и Redis не входят в минимальную целевую архитектуру;
- self-hosted Hatchet OSS принят как единственный v1 orchestrator candidate; его
  production adoption требует обязательного spike из
  [ADR-0001](adr/0001-hatchet-orchestrator-trial.md), а runtime fallback не строится;
- production runtime, build и deployment не обращаются к PyPI, Docker Hub, GitHub,
  public CDN, SaaS telemetry или другим внешним endpoint;
- все зависимости, OCI images, toolchains и metadata для проверки поставляются через
  approved internal mirrors/registries либо заранее импортированный offline bundle;
- отсутствие пользовательской auth-модели не отменяет service identity, network
  perimeter, least-privilege DB roles, secret isolation и audit;
- API contracts с первого релиза не зависят от CLI presentation и допускают будущий
  browser UI без изменения domain semantics.

Под «100 одновременно активных studies» здесь понимаются принятые, но ещё не
terminal исследования. Это не означает 100 одновременных запросов или materialization
operations к одной СУБД: физический параллелизм ограничивается отдельными profile,
worker-pool и operation quotas, а admission применяет backpressure.

Это greenfield implementation в существующем репозитории, а не постепенная замена
работающего графа классов.

## 1. Целевая задача продукта

### 1.1 Общая формулировка

Для конкретного database backend, source object, зафиксированного набора данных,
репрезентативной workload, разрешённого пространства физических преобразований и
ограниченного бюджета система должна найти physical design, который:

1. сохраняет заявленную семантику данных и запросов;
2. удовлетворяет hard constraints по регрессиям, ресурсам и стоимости;
3. улучшает одну или несколько целевых метрик относительно baseline;
4. подтверждает результат на независимой validation workload/sample;
5. возвращает воспроизводимый отчёт с confidence и границами применимости.

Для ClickHouse physical design выражается DDL-кандидатом с ORDER BY, column types,
codecs, granularity и skip indexes. Для PostgreSQL или другой СУБД набор dimensions
будет иным, но экспериментальный lifecycle остаётся тем же.

Система выдаёт рекомендацию. Она не применяет её к source environment.

### 1.2 Optimization contract

Сначала строится feasible set. Candidate допускается к выбору, только если:

- plugin подтвердил semantic correctness;
- source/backend invariants сохранены;
- защищённые workload cases не нарушают regression thresholds;
- storage, memory, build/migration и execution budgets соблюдены;
- measurement quality прошла gates.

Для feasible candidates система хранит multi-objective Pareto frontier. Scalar
utility разрешена только как versioned policy выбора внутри frontier и не может
компенсировать hard-constraint violation.

Рекомендуемые общие normalized effects:

- latency ratio;
- throughput ratio;
- CPU/read/write amplification;
- peak-memory ratio;
- storage ratio;
- build/migration cost;
- backend-specific effects из namespaced metric registry.

### 1.3 Вход

| Вход | Общая часть | Backend-owned часть |
|---|---|---|
| BackendRef | backend ID и plugin version constraint | connection/profile schema |
| SourceRef | profile ID и logical object ID | database/schema/table semantics |
| WorkloadSpec | cases, weights, SLO, regimes | query language, parser и binding |
| SamplingPolicy | budgets, tune/holdout split, seed | snapshot/materialization method |
| SearchPolicy | budget, beam, fidelity, objective | transformations и stage graph |
| MeasurementPolicy | repetitions, deadlines, precision | backend settings/telemetry |
| SecurityProfile | secret refs, installation scope, sandbox ref | backend roles/quotas/access policy |
| ResourceBudget | time, bytes, concurrency, attempts | backend capacity constraints |

После admission всё нормализуется в immutable StudyManifest. Изменение env/config
после seal не меняет текущий run.

Manifest также pin-ит `core_workflow_release_id`, exact core worker OCI digest,
Hatchet SDK/task-contract version, versioned workflow/action names и наблюдаемый
Hatchet server capability/build fingerprint. Shared Hatchet server upgrade проходит
controlled drain и сохраняется в provenance каждого continuation run.

### 1.4 Выход

ExperimentReport содержит:

- lifecycle и scientific outcome;
- backend ID, plugin/build/environment fingerprints;
- source, snapshot, samples и workload fingerprints;
- baseline и candidate design artifacts;
- generic и backend-specific metric observations;
- correctness/quality/constraint verdicts;
- confidence intervals и Pareto frontier;
- причины prune/promote каждого candidate;
- recommendation artifact и backend-specific change plan;
- risks, applicability, validation и rollback hints;
- raw-measurement artifact references;
- cleanup/resource status.

Possible outcomes:

- RECOMMENDED;
- NO_IMPROVEMENT;
- PARETO_SET_REQUIRES_POLICY;
- INCONCLUSIVE;
- FAILED;
- PARTIAL;
- CANCELLED.

NO_IMPROVEMENT означает качественно доказанный результат. INCONCLUSIVE означает, что
sample, workload, control, environment или precision не позволяют сделать вывод.

### 1.5 Не-цели

- автоматическая миграция source object;
- универсальный DDL или единый parser для всех SQL dialects;
- оптимизация workload, которой нет в manifest;
- exhaustive Cartesian search;
- сокрытие database semantics за lowest-common-denominator CRUD interface;
- использование queue/event stream как источника lifecycle truth;
- совместимость новой реализации с accidental behavior старого кода;
- browser UI в первом релизе;
- end-user login/session, RBAC, multi-tenancy, tenant quotas/billing и corporate IdP;
- работа production runtime через public Internet или SaaS control plane.

## 2. Главная архитектурная граница

### 2.1 DB-neutral experiment core

Core владеет тем, что одинаково для любого backend:

- study/run/experiment lifecycle;
- immutable manifests, identities и fingerprints;
- search DAG execution;
- budgets, priorities и admission;
- logical job, physical attempt, lease и fencing;
- paired experiment blocks;
- generic observation envelope;
- quality gates и error taxonomy;
- Pareto, confidence-aware selection и outcomes;
- resource ownership lifecycle;
- artifact/audit/report metadata;
- cancellation, resume и reconciliation.

Core не знает терминов MergeTree, codec, BRIN, fillfactor, clustered index или
VACUUM. Он не парсит user query и не рендерит DDL.

### 2.2 Database plugin

Plugin владеет всем, что требует знания конкретной СУБД:

- connection/profile validation;
- catalog introspection и capability detection;
- source schema model и canonicalization;
- snapshot/sample materialization;
- workload parser, safety, table binding и result oracle;
- transformation types и dependency rules;
- candidate proposal heuristics;
- candidate compiler и safe execution plan;
- sandbox resource operations;
- measurement execution и native telemetry;
- standard metric mapping;
- semantic validation;
- backend error classification;
- recommendation/change rendering.

Plugin не управляет run state, retries, leases, top-level budgets, job acceptance,
ranking snapshots или control schema.

### 2.3 Почему не «абстракция SQLDatabase»

Физический design разных СУБД семантически различается:

| ClickHouse | PostgreSQL | MySQL |
|---|---|---|
| ORDER BY определяет physical sorting | heap обычно не сохраняет physical order | clustered primary key зависит от engine |
| codecs per column | compression/storage semantics другие | row format/compression другие |
| sparse primary index и granules | B-tree/GiST/GIN/BRIN indexes | B-tree/fulltext/spatial indexes |
| skip indexes | partial/expression/include indexes | prefix/generated-column indexes |
| MergeTree parts/merges | pages, WAL, VACUUM, statistics | pages, redo/undo, buffer pool |

Обобщать нужно experiment protocol, а не конкретные tuning knobs.

### 2.4 Plugin SDK

Минимальные contracts:

| Contract | Назначение |
|---|---|
| PluginDescriptor | ID, semantic version, OCI digest, schemas, capabilities |
| ConnectionProfileSchema | boundary validation без secret values |
| CatalogProvider | source metadata и environment fingerprint |
| SourceModelCodec | parse/canonicalize backend schema artifact |
| SnapshotProvider | consistent snapshot/sample plan и materialization |
| WorkloadCompiler | query cases, safety, binding и correctness oracle |
| SearchPlanProvider | backend stage DAG и defaults |
| CandidateProvider | lazy proposals и dependency-aware transformations |
| CandidateCompiler | canonical candidate artifact и execution plan |
| CandidateValidator | static/domain/capability checks |
| ExperimentExecutor | build/load/query/measure one immutable job |
| MetricAdapter | native telemetry -> common + namespaced metrics |
| ResourceDriver | create/list/cancel/drop только allocated resources |
| ErrorClassifier | retryable/permanent/quality/semantic classification |
| RecommendationRenderer | backend-native design diff/change artifact |

SDK contracts версионируются отдельно от plugin. Plugin schema bodies хранятся как
canonical, content-addressed artifacts и проходят plugin-owned validation.

### 2.5 Generic envelopes без потери type safety

Core persist/route модель содержит:

- backend_id;
- plugin_version;
- payload_schema_version;
- artifact hash/reference;
- common identity/budget/deadline fields.

В backend worker plugin декодирует artifact в собственный immutable typed model.
Core не читает его внутренние поля. Для common decisions plugin возвращает
language-neutral SDK results: Proposal, ValidationVerdict, ExecutionPlan,
ObservationBatch и CorrectnessVerdict.

Candidate ID вычисляется из:

- backend ID;
- plugin/compiler version;
- base source-model fingerprint;
- canonical transformation artifact.

Одинаковый design получает одинаковый ID независимо от порядка генерации.

### 2.6 Plugin discovery и trust

- plugin — admin-approved signed OCI image/release, а не runtime Python import;
- declarative descriptor и schemas регистрируются по explicit allowlist;
- user config выбирает только approved profile/release, но не image/module;
- Control Service не импортирует executable plugin code;
- Hatchet versioned task route ведёт в worker pool exact plugin
  release/zone/resource class; отсутствие compatible worker обнаруживается до
  manifest seal;
- OCI digest, descriptor hash и capabilities фиксируются в StudyManifest/Attempt;
- breaking spec change создаёт новую version, а не silent coercion;
- plugin worker не получает unrestricted PostgreSQL control credentials;
- old release нельзя удалить, пока существуют nonterminal studies/resources;
- все maintained v1 application/workflow/task/plugin компоненты, включая ClickHouse
  plugin, используют Python 3.12; pinned Hatchet infrastructure binaries являются
  third-party runtime dependency, а не maintained application source;
- wire contract остаётся Protobuf/canonical-document based и не привязан к Python
  class paths, чтобы новый backend не потребовал нарушения process boundary.

До появления второго реального backend SDK имеет pre-1.0 status. Нельзя заранее
замораживать лишние универсальные interfaces: ClickHouse plugin плюс deterministic
toy plugin проверяют seam, а PostgreSQL spike позже проверит, что boundary не фиктивна.

## 3. Предметная модель

| Сущность | Владелец | Назначение |
|---|---|---|
| Study | core | user intent и общий budget |
| StudyManifest | core | sealed config/versions/fingerprints |
| TargetExperiment | core | один source object/backend |
| EnvironmentFingerprint | plugin -> core | backend/version/settings/topology |
| SourceArtifact | plugin | canonical source semantics |
| SampleManifest | common envelope + plugin body | tune/holdout data contract |
| WorkloadManifest | common envelope + plugin body | frozen workload |
| SearchPlan | common DAG + plugin stage bodies | порядок поиска |
| Candidate | common identity + plugin body | physical design |
| EvaluationJob | core | logical immutable work |
| Attempt | core | конкретная leased execution |
| Resource | core identity + plugin locator | sample/scratch/query/artifact |
| ObservationBatch | SDK | raw generic/native metrics |
| CandidateEvaluation | core | quality, constraints, confidence |
| RankingSnapshot | core | immutable stage decision |
| Recommendation | common outcome + plugin artifact | конечный результат |

### 3.1 Независимые status axes

Study хранит:

- lifecycle: DRAFT, PREPARING, READY, RUNNING, FINALIZING, TERMINAL;
- outcome: один из перечисленных в разделе 1.4;
- cleanup: NOT_STARTED, RUNNING, CLEAN, DEGRADED;
- analytics/report projection: PENDING, READY, FAILED;
- quality: VALID, WARNINGS, INVALID.

CLI submit сообщает ACCEPTED и study ID. Только status/wait сообщает terminal outcome.

### 3.2 Identity

| ID | Правило |
|---|---|
| study_id | UUIDv7/ULID |
| display_number | PostgreSQL sequence, не domain identity |
| experiment_id | UUID внутри study |
| manifest_id | canonical content hash |
| candidate_id | backend/plugin/source/transformation content hash |
| job_id | deterministic hash experiment/stage/candidate/sample/workload/profile |
| attempt_id | новый UUID на каждую physical execution |
| fence_token | monotonic value на claim/reclaim |
| resource_id | UUID registry row |
| observation_id | content hash accepted batch |

Resume принимает study ID. Новый config должен дать тот же manifest hash; иначе
создаётся explicit ForkStudy с parent ID.

## 4. Инварианты

1. Source доступен execution identity только на чтение.
2. В каждом fidelity baseline/candidates используют один sealed sample/batch order.
3. Tune и holdout независимы, immutable и versioned.
4. Query comparison использует один workload case/parameters/regime.
5. Plugin semantic verdict предшествует ranking.
6. Search budget отделён от measurement repetitions.
7. Raw observations append-only.
8. Failed/invalid/incomplete candidate не получает numeric failure score.
9. Candidate identity не зависит от enumeration order.
10. Job и attempt — разные сущности.
11. Один logical job принимает не более одного result.
12. Каждая scratch resource принадлежит одному attempt.
13. Старый fence не может commit result или удалить новый resource.
14. Любое ожидание и retry ограничены deadline/budget.
15. Resume не смешивает manifest/plugin/sample/workload.
16. Worker не получает reusable secrets в job body.
17. Plugin не расширяет allocated sandbox scope.
18. Transport/notification не определяет completion.
19. Нет доказательств — нет winner; outcome INCONCLUSIVE.
20. Study terminal только при известных job/report/cleanup states.

## 5. Generic algorithm полного пути

### 5.1 Submit и admission

1. API принимает schema-versioned config и idempotency key.
2. Registry разрешает backend/plugin version.
3. Plugin валидирует connection profile shape и source reference.
4. Core создаёт DRAFT study с UUID.
5. Plugin получает catalog/source/environment artifacts через read-only identity.
6. Core и plugin совместно проверяют sandbox, security, capabilities и budgets.
7. Plugin строит source, sampling, workload и SearchPlan artifacts.
8. Core canonicalizes common envelopes и atomically seals StudyManifest.
9. До READY ни один physical benchmark job не создаётся.

Empty targets, unsupported plugin/capability или zero candidate space дают явный
validation/outcome, а не успешный пустой запуск.

### 5.2 Snapshot и samples

Plugin обязан создать immutable data contract:

1. выбрать backend-correct snapshot/cutoff;
2. materialize bounded canonical data в isolated sandbox/artifact;
3. разделить tune и holdout seeds/buckets;
4. зафиксировать source/schema/environment fingerprint;
5. зафиксировать selection plan, strata, counts, bytes, checksums и batch order;
6. проверить sample adequacy;
7. зарегистрировать physical resources до использования.

Простой nondeterministic LIMIT запрещён. Generic core не определяет, как получить
snapshot: MVCC database, ClickHouse parts и file database требуют разных mechanisms.

### 5.3 Workload

Common WorkloadCase хранит:

- stable semantic ID;
- weight/frequency/business criticality;
- protected flag и SLO;
- opaque execution-regime IDs and weights;
- repetition/deadline policy;
- correctness policy;
- plugin workload artifact reference.

Plugin отвечает за dialect AST, parameter distributions, target binding, safety и
result digest. Он же определяет, означает regime transaction isolation, prepared
plan, cache state, concurrency или arrival process. Nondeterministic queries должны
иметь explicit oracle/policy либо отклоняться.

Production trace предпочтительнее synthetic queries. Auto workload допускается, но
report получает сниженный applicability confidence.

### 5.4 Baseline controls

Plugin строит два идентичных reference candidates:

- B0 — canonical baseline;
- B0-copy — noise/control duplicate.

Они независимо build/load из одного sample. Paired measurements должны попасть в
equivalence bounds. Если две одинаковые конструкции статистически неэквивалентны,
environment считается непригодной и study завершается INCONCLUSIVE.

Baseline anchors повторяются в каждом measurement block. Final recommendation всегда
сравнивается с B0, даже если parent candidate используется для дешёвого pruning.

### 5.5 SearchPlan

SearchPlan — versioned DAG. Stage names и transformation bodies задаёт plugin, а core:

- разрешает dependencies;
- применяет candidate/build/time budgets;
- lazily просит proposals;
- создаёт deterministic logical jobs;
- randomizes/interleaves experiment blocks;
- принимает terminal results из control database;
- применяет common quality/statistics/selection policy;
- seal-ит immutable RankingSnapshot;
- открывает dependent stages.

Stage iteration:

1. CandidateProvider lazily предлагает изменения от parent beam.
2. Plugin canonicalizes/deduplicates/validates candidates.
3. Core применяет proposal budget до materialization Cartesian space.
4. Scheduler создаёт jobs с sample/workload/fidelity refs.
5. Workers выполняют randomized paired blocks.
6. Core исключает invalid/failed/insufficient results.
7. Selector строит Pareto frontier, confidence bounds и diversity groups.
8. Baseline, per-parent survivors, global Pareto и diverse candidates сохраняются.
9. Decision и input-set hash atomically seal stage.

### 5.6 Multi-fidelity racing

Каждый plugin plan может использовать:

1. static legality/domain rejection;
2. backend-native cheap proxy;
3. малый tune sample;
4. minimum paired blocks;
5. confidence-bound prune/promote;
6. больший sample/repetition budget;
7. independent final validation.

Candidate не prune-ится по одному noisy point estimate. Timeout, OOM и semantic
failure не удаляются как outlier.

### 5.7 Final validation

На holdout переходят B0, B0-copy и несколько top/diverse finalists:

- несколько independent physical builds;
- full workload;
- все plugin-declared execution regimes; для ClickHouse это может включать отдельные
  warm/cold profiles;
- production-like concurrency/ingest/background maintenance;
- stricter precision and regression thresholds;
- repeated semantic checks;
- build/migration/storage costs;
- environment/source applicability recheck.

RECOMMENDED возможен только при hard constraints, practical effect и confidence.
Если baseline не хуже — NO_IMPROVEMENT. Несводимый frontier без policy —
PARETO_SET_REQUIRES_POLICY. Недостаток evidence — INCONCLUSIVE.

### 5.8 Finalize

Study становится TERMINAL, когда:

1. все required stages seal-нуты или имеют explicit failure/outcome;
2. все required jobs terminal и live leases отсутствуют;
3. final report artifact принят;
4. resource cleanup запущен и его status известен;
5. audit state согласован.

Worker делает fast cleanup, но независимый Reaper отвечает за crash leftovers.

## 6. Статистический контракт

### 6.1 Paired randomized blocks

Одна статистическая единица содержит:

- одинаковый workload case и parameters;
- contemporaneous baseline/control и candidate;
- randomized/Latin-square order;
- одинаковый backend regime/settings;
- contamination telemetry;
- correctness digest.

Raw observations сохраняются. Central estimate строится по paired log-ratios;
dispersion — robust estimator; confidence interval — block bootstrap. Protected
cases используют regression bounds и multiple-comparison policy.

### 6.2 Adaptive repetitions

- minimum valid blocks обязателен;
- измерение продолжается до precision target, maximum blocks или budget;
- optimistic/pessimistic bounds разрешают early prune/promote;
- contamination инвалидирует весь block только по preregistered rule;
- timeout/OOM/query error остаётся failure/constraint fact;
- search exploratory, final holdout имеет отдельный decision threshold.

### 6.3 Selection order

1. plugin semantic validity;
2. execution/measurement quality;
3. hard constraints;
4. Pareto dominance;
5. confidence и minimum practical effect;
6. versioned utility;
7. deterministic low-risk tie-breaker.

### 6.4 Metric model

Standard metric registry предлагает следующие keys; обязательным является только
явно заявленный capability/measurement contract subset:

- elapsed/latency distributions;
- throughput;
- CPU time;
- peak memory;
- read/write rows and bytes;
- storage bytes;
- build/load/maintenance time;
- errors/timeouts/resource violations.

Backend metrics имеют namespace, например:

- clickhouse.selected_marks;
- clickhouse.primary_index_bytes;
- clickhouse.merge_time;
- postgresql.shared_blks_hit;
- postgresql.wal_bytes.

Objective manifest объявляет direction, unit, aggregation и hard/soft role каждой
metric. Unknown metric не вычисляется молча.

## 7. ClickHouse plugin v1

### 7.1 Scope

Первый plugin реализует только ClickHouse и оптимизирует:

- sorting/primary-key design в разрешённых границах;
- physical column types;
- column codec pipelines;
- index_granularity и index_granularity_bytes;
- skip indexes и их parameters/granularity;
- joint local refinement.

Partitioning, TTL, SAMPLE clause и MergeTree semantic family в v1 locked. Их
автоматическая оптимизация требует отдельного RFC.

### 7.2 ClickHouse SourceModel

Typed model содержит:

- logical columns, domains, nullability и defaults;
- engine family и semantic parameters;
- partition, sorting и primary keys;
- codecs;
- settings;
- skip indexes;
- projections/constraints/TTL as locked artifacts;
- server capabilities/version.

Replicated engine sandbox compile разрешён только в доказуемо эквивалентную
non-replicated family. ON CLUSTER, Keeper paths, source UUID и arbitrary database
authority не попадают в execution plan.

Для Replacing/Collapsing/Aggregating families изменение key может менять семантику и
по умолчанию запрещено.

### 7.3 Type safety

Transformation classes:

- PROVEN_SAFE — lossless/order-preserving для declared future domain;
- SAFE_FOR_SNAPSHOT_ONLY — подходит sample, но не будущим данным;
- POLICY_REQUIRED — precision/null/timezone/Enum-like decision;
- FORBIDDEN.

Автоматический search продвигает только PROVEN_SAFE. Snapshot min/max не считается
future-domain proof.

### 7.4 ClickHouse SearchPlan

~~~mermaid
flowchart LR
    B[baseline controls] --> L[ORDER BY / primary prefix]
    L --> E[type + codec encoding]
    E --> G[index granularity]
    G --> I[skip indexes]
    I --> J[joint refinement]
    J --> V[holdout validation]
~~~

Почему порядок:

- ORDER BY меняет physical locality, sparse index и compression;
- codec/index compatibility зависит от post-type schema;
- granularity влияет на primary/skip index economics;
- skip indexes полезны только относительно final layout/type;
- joint refinement компенсирует ошибки staged pruning.

Beam всегда сохраняет baseline, per-parent winners, global Pareto и несколько
структурно разных candidates.

### 7.5 ClickHouse sample/workload

Sampling стратифицируется по relevant partitions/time, source business dimensions,
predicate selectivity, null/extreme/tail и hit/miss cases. Rows подаются каждому
candidate в одинаковых deterministic batches/order.

Workload преимущественно mining-ится из production query log с real parameter
distributions и selectivity, а не только normalized hash. Plugin отдельно моделирует:

- point/range/IN/LIKE;
- narrow/broad и hit/miss;
- grouping/order/limit;
- queries, не использующие candidate key/index;
- insert batches и concurrent reads during ingest.

Stage query subsets извлекаются из ClickHouse AST, не regex.

### 7.6 ClickHouse measurement

- fresh table state для каждого insert repetition;
- query result cache выключен;
- warm/cold regimes не смешиваются;
- part topology создаётся deterministic ingest batches;
- безусловный OPTIMIZE FINAL запрещён;
- selected marks, read rows/bytes, compression, primary/skip index sizes,
  insert/merge cost и resource telemetry сохраняются;
- B0 и candidate используют один sample/query instances/settings;
- source table до/после сверяется по DDL/count/checksum.

### 7.7 ClickHouse security

Отдельные roles:

- Catalog/Source Reader — SHOW/SELECT только allowlisted source;
- Sandbox Executor — CREATE/INSERT/SELECT/DROP только sandbox;
- Reaper — DROP только allocated sandbox resources;
- Control Migrator — только PostgreSQL control schema;
- optional Analytics Writer — append-only result projection.

Лучший вариант — отдельный ClickHouse sandbox cluster. Fallback в source database
запрещён.

## 8. Будущие database plugins

### 8.1 Что должен доказать второй plugin

Новый backend принимается, когда он:

1. не добавляет backend conditionals в core;
2. реализует SDK conformance suite;
3. имеет consistent snapshot/sample contract;
4. компилирует typed candidates без raw untrusted DDL;
5. предоставляет workload safety и correctness oracle;
6. отображает native telemetry в common/namespaced metrics;
7. использует generic job/attempt/resource lifecycle;
8. имеет isolated sandbox и least-privilege roles;
9. выдаёт backend-native recommendation artifact;
10. проходит full-path, crash/resume и cleanup E2E.

### 8.2 Возможный PostgreSQL plugin

Его search dimensions будут другими:

- B-tree, Hash, GiST, SP-GiST, GIN, BRIN;
- multicolumn order, INCLUDE и partial/expression indexes;
- storage parameters/fillfactor;
- safe type choices;
- optional clustering/partitioning только под отдельной policy;
- planner statistics/maintenance profiles.

Snapshot может использовать MVCC/consistent export semantics, а metrics —
EXPLAIN ANALYZE/BUFFERS, WAL, shared blocks, temp IO и maintenance costs. Эти детали
не должны появляться в generic core.

### 8.3 Правило против преждевременного framework design

ClickHouse v1 реализуется полностью. Затем делается небольшой PostgreSQL vertical
spike: one table, one index dimension, one workload, one result. Только после этого
Plugin SDK получает stable 1.0. Fake plugin проверяет orchestration contracts, но не
заменяет проверку второй реальной СУБД.

## 9. Целевая системная архитектура

~~~mermaid
flowchart LR
    USER[CLI / future UI] --> API[Control API]
    API --> PG[(PostgreSQL business state)]
    API --> STARTER[Command Starter]
    STARTER --> HAPI[Hatchet API]
    HAPI --> HPG[(Hatchet PostgreSQL)]
    HAPI --> HENGINE[Hatchet Engine]
    HUI[Hatchet operator UI] --> HAPI
    HENGINE --> COREW[Core Workers]
    COREW --> PG
    COREW --> ART[(Artifact Store)]
    HENGINE --> CHQ[Versioned ClickHouse task route]
    CHQ --> CHW[ClickHouse plugin workers]
    HENGINE --> FUTQ[Future backend task routes]
    FUTQ --> FUTW[PostgreSQL / MySQL plugin workers]
    CHW --> WORKERAPI[Attempt / Resource API]
    FUTW --> WORKERAPI
    WORKERAPI --> PG
    CHW --> SECRET[Secret Broker]
    FUTW --> SECRET
    CHW --> SOURCE[(Source ClickHouse)]
    CHW --> SANDBOX[(ClickHouse sandbox)]
    FUTW --> FUTDB[(Future source / sandbox)]
    CHW --> ART
    FUTW --> ART
    REAPER[Resource Reaper] --> HAPI
    PROJECTOR[Optional analytics projector] --> ANALYTICS[(Analytics sink)]
    PG --> PROJECTOR
    ART --> PROJECTOR
~~~

### 9.1 Authority boundaries

Hatchet отвечает за:

- durable workflow order;
- task delivery and retry scheduling;
- timers/deadlines;
- heartbeat/cancellation;
- process-crash recovery;
- declared concurrency/rate limits.

PostgreSQL отвечает за:

- client submissions и idempotency;
- immutable manifests/documents;
- approved plugin/profile registry;
- accepted job results;
- attempt fencing;
- resource ownership;
- ranking snapshots;
- terminal business outcome;
- audit/status projection.

Это не две конкурирующие business state machines. Hatchet владеет execution
progression, PostgreSQL — durable business facts/external side effects. Workflow
завершает `FinalizeStudy` task только после idempotent commit terminal outcome в
PostgreSQL.

Если task успела commit, но worker упал до ответа Hatchet, retry читает уже
accepted fact и возвращает тот же result.

### 9.2 Почему Hatchet выбран для architecture spike

Long-running phased search требует durable timers, retries, heartbeat, cancellation,
child workflows и process recovery как основных функций. В clean-slate проекте нет
причины сохранять Celery ради совместимости.

Hatchet объединяет durable task queue, workflow orchestration, retries, concurrency,
rate limits, API и operator dashboard вокруг PostgreSQL. Он существенно легче
выбранного ранее Temporal stack и имеет официальный Python SDK.
[Hatchet architecture and guarantees](https://docs.hatchet.run/v1/architecture-and-guarantees)

Для dynamic search используются Hatchet durable tasks: wait/child-spawn создают
checkpoints, а resume replay-ит детерминированный code path по durable event log.
Side effects и чтение внешнего state выносятся в child tasks.
[Hatchet durable tasks](https://docs.hatchet.run/v1/durable-tasks)

Доставка внешней task может повториться, поэтому PostgreSQL uniqueness, domain
attempt fencing и attempt-scoped resources остаются обязательны. Orchestrator retry
не является exactly-once commit.

Большие candidate sets не удерживаются в одном unbounded workflow payload/history.
Core открывает bounded stage/batch только из sealed snapshot hash; task payload
содержит reference, а не candidate bodies. Версия workflow/task и exact plugin
worker routing pin-ятся в manifest и доказываются отдельным A/B release test.

Пока прямой production-эквивалент Continue-As-New не доказан, rollover является
product protocol: текущий bounded run seal-ит stage/snapshot в PostgreSQL, atomically
пишет successor outbox command с `continuation_no` и previous snapshot hash, затем
завершается; starter запускает следующий versioned Hatchet run. Два continuation
runs не могут одновременно владеть одним logical job/attempt fence.

Hatchet принят условно: до production implementation обязательны resource,
crash/cancel, version-routing и blocked-egress gates из
[ADR-0001](adr/0001-hatchet-orchestrator-trial.md). Недоказанные свойства не
считаются гарантиями Hatchet.

### 9.3 Deployment units

Логически один product, физически:

- Control API;
- command starter/reconciler;
- Hatchet API, Engine и optional operator Frontend;
- Core Hatchet Workers;
- plugin registry/admission;
- one worker pool per plugin release/zone/resource class;
- Attempt/Resource/Secret Broker APIs;
- Resource Reaper;
- optional Analytics Projector;
- CLI; future UI является отдельным клиентом Control API.

На раннем этапе Control API, starter и narrow internal APIs можно объединить в один
deployment. Backend workers остаются изолированными OCI images. Hatchet и product
business state могут использовать один физический PostgreSQL deployment только как
разные databases/owners/migration paths; cross-database reads запрещены.

## 10. Workflow topology и lifecycle

### 10.1 Workflows

- BenchmarkStudyWorkflow — общий submit, targets и terminal aggregation;
- TargetExperimentWorkflow — snapshot, baseline, search и validation одной source;
- StageWorkflow — bounded candidate batch/barrier/selection;
- CleanupWorkflow — release retained samples/scratch resources;
- optional BuildShardWorkflow — ограниченный fan-out тяжёлых candidates.

Hatchet durable orchestration task детерминирована между checkpoints:

- не вызывает DB/network/filesystem;
- не импортирует plugin;
- не читает process env как business input;
- не использует ambient clock/random/UUID для control flow;
- основывает ветвление только на event history и persisted child-task outputs;
- передаёт child tasks только small immutable references;
- не создаёт unbounded child fan-out или payload/history growth.

Обычные child tasks выполняют I/O и могут исполняться at least once. Они не считаются
частью replay-safe code path и обязаны быть идемпотентными на domain boundary.

### 10.2 Study lifecycle

~~~mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> PREPARING
    PREPARING --> READY
    READY --> RUNNING
    RUNNING --> FINALIZING
    FINALIZING --> TERMINAL
    DRAFT --> TERMINAL: validation/cancel
    PREPARING --> TERMINAL: failure/cancel
    READY --> TERMINAL: cancel
    RUNNING --> FINALIZING: cancel/fatal failure
~~~

TERMINAL фиксирует отдельный outcome, а не просто Hatchet completion.

### 10.3 Stage, job и attempt

Stage:

~~~text
BLOCKED -> READY -> RUNNING -> SELECTING -> SEALED
                     |             |
                     +-----------> FAILED / INCONCLUSIVE / CANCELLED
~~~

SEALED содержит immutable input-set hash и RankingSnapshot.

Logical job:

~~~text
BLOCKED -> READY -> ACTIVE -> SUCCEEDED
                         -> FAILED_FINAL
                         -> SKIPPED
                         -> CANCELLED
~~~

Domain attempt:

~~~text
CREATED -> LEASED -> RUNNING -> RESULT_ACCEPTED -> SUCCEEDED
                  |         +-> FAILED_RETRYABLE
                  |         +-> FAILED_FINAL
                  |         +-> LOST / TIMED_OUT / CANCELLED
                  +----------> REJECTED_STALE
~~~

Hatchet workflow/task-run IDs, physical invocation и domain attempt являются разными
identities. Hatchet IDs используются только для correlation. Каждый реальный вход в
I/O task создаёт `physical_invocation_id` и stable `begin_request_id` для повторного
RPC; `BeginAttempt` idempotently возвращает один domain attempt/fence для этого
request. Новая physical invocation после потери lease получает новый domain attempt и
fence.

### 10.4 Полный sequence

1. API atomically пишет Study submission и outbox command с product idempotency key.
2. Starter проверяет PostgreSQL workflow projection и запускает versioned Hatchet
   workflow только при отсутствии принятого mapping.
3. Возвращённый Hatchet workflow-run ID сохраняется в projection; повтор starter
   использует product mapping, а не полагается только на Hatchet idempotency.
4. Workflow pin-ит plugin release/profile revisions.
5. Plugin child task делает capability/catalog handshake.
6. Core child task seal-ит `StudyManifest`.
7. Target durable task вызывает sample materialization по versioned plugin task route.
8. Plugin worker вызывает `BeginAttempt`, получает fence и short-lived secret grants.
9. Resource API выделяет server-approved sandbox locators.
10. Worker создаёт sample, пишет artifact, `CompleteAttempt` принимает result один раз.
11. Baseline/control и candidate I/O tasks используют те же sealed refs.
12. Core I/O task aggregates observations и seal-ит `RankingSnapshot`.
13. Durable task открывает следующий bounded stage из snapshot hash.
14. Final validation и report child tasks фиксируют terminal business outcome.
15. `CleanupWorkflow`/Reaper очищает resources pinned plugin release.
16. Optional projector копирует artifacts в analytical sink.

Resume после process failure использует Hatchet durable event-log replay/checkpoints
и PostgreSQL sealed facts. Изменённый config/plugin/profile/capability создаёт
`ForkStudy`, а не мутирует текущий manifest. Точный recovery contract должен пройти
ADR-0001 spike до production adoption.

## 11. PostgreSQL business model

### 11.1 Core tables

- studies — identity, idempotency, manifest, outcome, desired state, timestamps;
- workflow_projection — Hatchet workflow/root-task run IDs, continuation number,
  workflow contract/build ID, projection version и API/CLI status;
- manifests — immutable common document refs/hashes;
- backend_documents — plugin release, kind, schema ID/version, hash, JSONB/object URI;
- target_experiments — backend/profile/catalog/sample/workload refs;
- stages/dependencies — DAG state и ranking snapshot;
- candidates — identity, lineage, native design ref и human summary;
- jobs — logical key, spec ref, measurement contract, deadline;
- attempts — Hatchet correlation IDs, physical invocation/begin-request IDs, domain
  UUID, fence, lease heartbeat/outcome;
- accepted_results — unique job result, quality, canonical summary, artifact refs;
- metric_definitions — common/plugin registry snapshot;
- ranking_snapshots/entries — append-only selection;
- resources — plugin locator ref, owner/fence/lifecycle/expiry;
- plugin_releases — descriptor, OCI digest, signature, schemas, state;
- worker_pools — plugin release/queue/zone/resource class/health;
- connection_profiles — non-secret revision, secret ref, backend access policy, zone;
- commands/audit_events — append-only;
- projection_status — optional analytics/report sinks.

### 11.2 Constraints

1. one study per installation/idempotency key; v1 имеет одну installation scope без
   project/tenant identity;
2. one logical job per study/logical key;
3. one accepted result per job;
4. one active domain attempt/fence per job;
5. one resource locator per plugin release/profile/kind/hash;
6. manifest immutable after READY;
7. commit only current attempt + fence;
8. stage seal only against declared terminal input set;
9. plugin document validates exact registered schema/hash;
10. terminal outcome committed before workflow completion.

### 11.3 Native documents

Common searchable fields остаются relational. Backend detail хранится opaque,
schema-tagged и content-addressed. Core:

- проверяет descriptor/schema/hash;
- не читает undocumented keys;
- не мигрирует old native documents in place;
- хранит sanitized human summary на случай retirement plugin executable.

Не нужны EAV, universal ORM inheritance или plugin-specific columns в core tables.

### 11.4 Artifacts и analytics

S3-compatible store по умолчанию содержит:

- catalog/source artifacts;
- sample manifests/data references;
- workload/candidate/execution plans;
- raw observation batches;
- result digests;
- sanitized diagnostics;
- final reports.

PostgreSQL хранит authoritative summaries/refs. Analytics sink optional и rebuildable:
это может быть ClickHouse, warehouse или PostgreSQL projection. Его outage не меняет
execution outcome.

Control database не делается pluggable: PostgreSQL transactions, uniqueness, fencing
и immutable commits являются platform contract, а не абстракцией «любой SQL DB».

## 12. Task protocol, attempts и resources

### 12.1 OperationRef

Small language-neutral reference содержит:

- protocol_version;
- study/experiment/stage/job IDs;
- operation kind;
- plugin release ID + descriptor hash;
- backend spec ref + SHA-256;
- measurement contract ID;
- budget/deadline profile refs;
- expected catalog/sample/capability fingerprints;
- trace context.

В Hatchet payload/event history отсутствуют:

- passwords/URLs;
- full DDL/query;
- physical cleanup targets;
- arbitrary database names;
- large raw measurements;
- sensitive sampled literals.

Control/plugin service wire contracts — Protobuf/gRPC. Hatchet task input — малая
versioned JSON `OperationRef` без Python class path; она содержит те же stable IDs,
references и hashes. Extensible plugin bodies — canonical JSON/document schemas по
content hash и не передаются как task payload.

### 12.2 Begin/heartbeat/complete

1. I/O task worker создаёт `physical_invocation_id`/`begin_request_id` и вызывает
   `BeginAttempt` с доступными Hatchet workflow/task-run correlation IDs.
2. API idempotently создаёт/возвращает domain attempt, fence и execution grant.
3. Secret Broker проверяет worker identity, plugin release, profile role и fence.
4. AllocateResource создаёт server-approved locator.
5. Domain lease heartbeat несёт progress/checkpoint/resource IDs, но не secrets/raw
   data.
6. CompleteAttempt принимает result hash/summary только current fence.
7. Retry после accepted commit получает ALREADY_APPLIED.
8. FailAttempt передаёт typed error; core retry policy остаётся authoritative.

При потере heartbeat новая task delivery получает новый domain attempt/fence и новую
scratch resource. Late worker не может commit или drop новый resource.

Domain lease heartbeat не отождествляется с Hatchet worker connection heartbeat,
durable-task checkpoint или refresh timeout. Hatchet cancellation является
кооперативным signal: product `desired_state`, lease expiry, fence и Reaper остаются
authoritative, даже если физическая операция не остановилась мгновенно.

### 12.3 Error taxonomy

- CONFIG_INVALID;
- PLUGIN_UNAVAILABLE/UNSUPPORTED;
- SOURCE_DRIFT;
- CANDIDATE_INVALID;
- UNSAFE_OPERATION;
- SEMANTIC_MISMATCH;
- AUTHORIZATION — backend/service credential или infrastructure access failure, не
  end-user RBAC verdict;
- TRANSIENT_INFRASTRUCTURE;
- RESOURCE_EXHAUSTED;
- MEASUREMENT_UNSTABLE;
- TIMEOUT;
- CANCELLED;
- RESULT_REJECTED_STALE;
- CLEANUP_FAILURE;
- PLUGIN_BUG;
- CORE_BUG.

Hatchet tasks получают bounded explicit retry, scheduling timeout и execution timeout
policies. Validation/auth/semantic errors non-retryable; transient errors bounded;
OOM не меняет sample/profile молча.

### 12.4 Resource registry и reaper

Resource kinds:

- canonical sample;
- candidate build artifact;
- backend execution handle;
- artifact upload;
- optional isolated compute job.

Конкретные table/schema/database/query/session locators остаются plugin-native.

Lifecycle:

~~~text
ALLOCATED -> CREATING -> ACTIVE -> RETAINED / CLEANUP_PENDING
          -> CLEANING -> CLEANED | QUARANTINED
~~~

Worker сначала регистрирует resource, затем создаёт. Sample после success может
перейти из attempt ownership в experiment ownership. Scratch resource всегда
attempt-owned.

Reaper:

1. выбирает expired/terminal resources;
2. route-ит cleanup в pinned plugin release;
3. проверяет descriptor, profile, fence и locator hash;
4. удаляет только registry-owned object;
5. retry bounded;
6. после threshold переводит QUARANTINED и alert.

Sandbox inventory обнаруживает unregistered orphan. Unknown object автоматически
не удаляется без строгой namespace/age policy.

### 12.5 Cancellation

1. Control API commit-ит product `desired_state=CANCELLED`.
2. Reconciler отправляет cancellation в root Hatchet run и известные child runs.
3. Worker регулярно проверяет cooperative cancellation signal и передаёт его
   поддерживаемому backend execution handle.
4. Current domain lease/fence инвалидируется, поэтому late completion не принимается.
5. Reaper независимо доводит registered resources до cleaned/quarantined state.
6. Terminal `CANCELLED` фиксируется product transition, а не выводится напрямую из
   Hatchet status.

До ADR-0001 spike нельзя предполагать автоматическую каскадную отмену всех dynamic
children, мгновенную остановку sync Python task или уже отправленного ClickHouse
query, либо отсутствие late task completion.

## 13. Security model

### 13.1 Plugin supply chain

- signed immutable OCI image;
- exact digest in manifest;
- descriptor/schema signatures;
- SBOM, vulnerability and provenance policy;
- internal OCI registry and internally available signing trust roots/verification data;
- admin approval before ACTIVE;
- release states ACTIVE, DEPRECATED, DRAINING, RETIRED;
- uninstall blocked by nonterminal studies/resources;
- no runtime pip/install/import from user input.

### 13.2 Worker isolation

- one plugin release/zone/trust tier per pool;
- rootless/read-only filesystem;
- seccomp/AppArmor/no unnecessary capabilities;
- CPU/memory/temp-disk limits;
- internal egress allowlist; public Internet egress denied;
- no direct PostgreSQL credentials;
- narrow Attempt/Resource/Artifact APIs;
- workload identity and short-lived secret grants;
- third-party plugins in separate trust boundary/account.

### 13.3 Database access

Every backend plugin declares source/sandbox/cleanup privilege contracts.

Common rules:

- source identity technically read-only;
- sandbox identity writes only allocated namespace;
- cleanup identity drops only registered sandbox resources;
- metadata identity cannot execute tuning DDL;
- environment/profile revision pinned;
- arbitrary user/plugin locator not trusted;
- limits from core are non-relaxable; plugin may only tighten them.

### 13.4 Data and logs

- TLS/mTLS for all control paths;
- secret refs instead of values;
- field-based redaction before serialization;
- encrypted/restricted sensitive artifacts;
- Hatchet inputs/results/errors проходят schema validation, size bounds и redaction;
- structured audit for secret grant/resource operation/cancel/fork;
- no raw credentials in Hatchet payload/event history, PostgreSQL docs, artifacts or
  logs.

## 14. Greenfield repository structure

~~~text
specs/
  product/
  experiment/
  lifecycle/
  measurement/
  search/
  security/
  plugin_sdk/
  backends/clickhouse/

fixtures/golden/
  source_models/
  samples/
  workloads/
  candidates/
  observations/
  decisions/
  reports/
  anti_regressions/

packages/
  experiment_domain/
  optimizer_sdk/
  experiment_engine/
  core_workflows/
  core_tasks/
  runtime_services/
  plugin_tck/

plugins/
  clickhouse/
    descriptor/
    catalog/
    source_model/
    sampling/
    workload/
    candidates/
    search_plan/
    compiler/
    executor/
    metrics/
    validation/
    resources/
    reporting/

apps/
  control_api/
  command_starter/
  durable_workflow_worker/
  core_task_worker/
  plugin_registry/
  attempt_resource_api/
  resource_reaper/
  artifact_projector/
  cli/
  migrator/

adapters/
  postgres/
  hatchet/
  object_store/
  secret_manager/
  telemetry/
  memory/

deploy/
tests/
  architecture/
  contracts/
  integration/
  e2e/
  chaos/
  performance/
~~~

Нет каталогов compat или legacy.

### 14.1 Dependency rule

~~~text
experiment_domain      optimizer_sdk
        ^                    ^
        +---- experiment_engine
                  ^
       durable workflows/I-O tasks

optimizer_sdk <- plugin_clickhouse

apps/adapters compose dependencies at boundaries
core never imports plugin_clickhouse
~~~

Architecture tests запрещают:

- database drivers/parsers in core;
- ClickHouse stage names/types in core;
- environment settings imports in domain;
- plugin imports from workflows;
- direct plugin access to PostgreSQL;
- application import from apps/adapters;
- conditionals по backend ID внутри core.

### 14.2 Entrypoints

- control-api;
- durable-workflow-worker;
- core-task-worker;
- plugin-clickhouse-worker;
- resource-reaper;
- artifact-projector;
- control-migrator;
- CLI.

Pure domain/unit tests используют in-memory adapters. Replay/retry/cancellation и
version-routing tests используют disposable real Hatchet + PostgreSQL; `hatchet-lite`
допустим только как developer convenience, но не как production proof. ClickHouse
component tests используют disposable isolated instance. Local mode не создаёт
отдельную business semantics.

Browser UI не входит в v1. Control API с первого релиза остаётся presentation-neutral:
CLI не получает привилегированный in-process путь и использует те же commands/queries,
которые сможет использовать будущий UI.

### 14.3 Runtime language

- target runtime — CPython `>=3.12,<3.13`;
- все maintained application/plugin source и generated runtime bindings проверяются
  на Python 3.12;
- maintained v1 application, workflow, task, CLI, service, SDK и plugin source не
  добавляет Go, Rust, Java или Node.js; pinned third-party infrastructure binaries,
  включая Hatchet/PostgreSQL/object storage, не считаются maintained application
  implementation;
- Protobuf остаётся language-neutral contract, но v1 генерирует только Python runtime
  bindings;
- новый database backend по умолчанию также реализуется на Python 3.12; polyglot
  runtime требует отдельного решения;
- Python API/persistence/migration/build baseline зафиксирован в
  [ADR-0002](adr/0002-python-application-stack.md); точные versions фиксируются
  lockfile и не возникают неявно в implementation PR;
- frontend language/framework выбирается только при фактическом старте UI.

## 15. Deployment и observability

### 15.1 Production

- self-hosted Hatchet API, Engine и optional operator Frontend внутри закрытого
  контура;
- self-hosted PostgreSQL HA + PITR backups;
- self-hosted S3-compatible immutable/versioned artifact storage;
- внутренний Secret Manager либо эквивалентный approved secret store;
- внутренний OCI registry с pinned plugin/service images;
- one Control API replica in the initial resource profile; HA scale-out requires a
  measured deployment profile;
- durable-workflow и core I/O-task worker pools;
- pinned plugin OCI worker pools per zone/resource class;
- isolated target sandbox databases/clusters;
- independent Reaper and optional projector deployments;
- внутренний OpenTelemetry/metrics/logging backend без SaaS exporters.

Конкретный deployment substrate — Kubernetes, VM/container services или их внутренний
эквивалент — пока не выбран. Если контур предоставляет Kubernetes, очень тяжёлый
attempt plugin может делегировать approved Kubernetes Job Launcher, но не передаёт
arbitrary PodSpec. Hatchet в любом варианте остаётся execution-progress authority.

Каждый отдельный deployment имеет hard limit не более `1 CPU / 1024 MiB`. Начальный
profile использует one Engine replica, one API replica, PostgreSQL-backed Hatchet
queue без RabbitMQ и bounded worker slots. Это production candidate только после
ADR-0001 capacity spike; Helm requests сами по себе не считаются доказательством.

### 15.2 Offline supply chain

Production и production-like CI не требуют Internet egress:

- Python wheels/sdists, OCI images, OS packages и Protobuf toolchain доступны во
  внутреннем mirror/registry либо offline bundle;
- dependency graph и images pinned, проверяемы и воспроизводимы без online resolve;
- plugin discovery работает только по внутреннему allowlist/registry;
- runtime не делает update/license/schema checks во внешнюю сеть;
- UI в будущем не использует remote scripts, fonts, analytics или CDN assets;
- telemetry, crash reports и vulnerability/signature verification не отправляют
  данные наружу;
- installation, migrations, startup, benchmark full path, backup и restore проходят
  acceptance test при заблокированном egress.

Hatchet offline profile явно задаёт PostgreSQL-only transport и отключает public
security check:

~~~text
SERVER_MSGQUEUE_KIND=postgres
SERVER_MSGQUEUE_PUBSUB_KIND=postgres
SERVER_SECURITY_CHECK_ENABLED=false
~~~

Sentry, PostHog, Pylon, public OAuth, external SMTP, update/security endpoints и
внешние OpenTelemetry exporters отсутствуют либо направлены только во внутренние
approved endpoints. Hatchet UI проверяется на отсутствие remote scripts/fonts/assets.

Отсутствие лицензионного allowlist не отменяет SBOM, provenance и проверку того, что
зависимости разрешено хранить и распространять во внутреннем контуре.

### 15.3 Capacity и backpressure

V1 проектируется и тестируется для 100 одновременно active/nonterminal Study
workflows. Это control-plane concurrency, а не требование одновременно исполнять 100
физических операций в ClickHouse.

- admission имеет общий bounded limit active studies;
- каждый connection/profile задаёт собственные query/build/storage limits;
- plugin pool и operation class имеют отдельные worker/concurrency quotas;
- excess work остаётся в durable bounded orchestration queue либо отклоняется явным
  capacity outcome до выделения backend resources;
- fairness не позволяет одному study или target бесконечно вытеснять остальные;
- load test на 100 active studies проверяет API/status latency, Hatchet queue/task
  state, checkpoint/event/payload growth, PostgreSQL contention, memory и отсутствие
  source overload.

Точные численные per-target limits настраиваются после capacity rehearsal и входят в
profile revision/manifest. Их нельзя подменять process-global semaphore без durable
admission semantics.

До утверждения capacity profile действуют fail-safe defaults:

- `max_inflight_studies = 100` на installation;
- `max_active_attempts_per_study = 1`;
- `max_active_attempts_per_source_or_sandbox = 1`;
- undeclared physical capacity означает один global execution slot для соответствующего
  plugin pool/operation class;
- 101-я submission получает явный retryable `CAPACITY_EXHAUSTED` до создания Study,
  а не попадает в неограниченную очередь.

### 15.4 Worker routing

Queue/routing identity включает:

- core workflow release ID и exact core worker OCI digest;
- plugin release digest;
- network/data-residency zone;
- resource class;
- operation capability.

Несовместимые releases никогда не регистрируют одинаковое action name. Нормативный
шаблон:

~~~text
core.<workflow>.<core_release_id>
plugin.<plugin_id>.<plugin_release_id>.<operation>.<protocol_version>
~~~

Preflight требует healthy workers, зарегистрированных для exact versioned task names,
до manifest seal. Old plugin pool drain-ится только после terminal pinned studies и
cleanup resources. Hatchet worker affinity не считается достаточным pinning без A/B
release acceptance test.

### 15.5 Observability

Каждый signal несёт:

- study, experiment, stage, job;
- Hatchet workflow/task-run/delivery-attempt correlation;
- domain attempt/fence;
- plugin release/worker build;
- resource/execution IDs;
- trace context.

Metrics:

- workflow/task/stage latency;
- retry/timeout/cancel/error classes;
- Hatchet checkpoint/event/payload size и bounded continuation count;
- plugin queue backlog/poller health;
- accepted/stale results;
- resource/cleanup/quarantine age;
- artifact/projection lag;
- sample/workload drift;
- measurement variance/invalid ratio;
- budget and source/sandbox load;
- secret/redaction violations.

Будущий UI читает только Control API, а не PostgreSQL/Hatchet напрямую. Status API
строится по PostgreSQL business projection и показывает Hatchet correlation, cleanup
и analytics states отдельно. Hatchet Frontend остаётся operator-only. В v1 этот
контракт используется CLI и automation.

### 15.6 Identity boundary v1

Первый релиз работает как одна trusted internal installation:

- нет end-user registry, login/session flow, RBAC, tenant isolation/billing и IdP;
- API доступен только через approved internal network perimeter;
- service-to-service identity, TLS policy, database roles и secret grants остаются
  обязательными infrastructure controls;
- source identity read-only, sandbox writer, cleanup role и control migrator разделены;
- audit фиксирует system/service/operator-supplied label, но не выдаёт его за
  криптографически подтверждённую end-user identity;
- domain и persistence model не получают speculative tenant hierarchy.

Появление пользователей, RBAC, multi-tenancy либо внешнего UI ingress требует
отдельного security/data migration ADR и threat model.

## 16. Clean-slate implementation plan

### M0 — Hatchet feasibility и architecture spike

До R0 deletion и до production implementation выполняется изолированный toy full
path на real self-hosted Hatchet + PostgreSQL:

- PostgreSQL-only Hatchet queue, RabbitMQ отключён;
- one API replica, one Engine replica, optional Frontend, one core worker и one toy
  plugin worker;
- hard limit `1 CPU / 1024 MiB` на каждый deployment/job;
- 100 active Studies при bounded physical slots и явный отказ 101-й submission;
- checkpoint replay/eviction, task duplicate, worker kill и late fence;
- cooperative parent/child cancellation и independent Reaper;
- A/B core/plugin worker releases с exact versioned task routes и drain;
- API/Engine/Hatchet-PG/product-PG outage/restart matrix;
- blocked-egress install, migrations, startup, UI и workflow;
- bounded checkpoint/event/payload growth через stage continuation.

Exit gate:

- все acceptance и reject gates ADR-0001 документированы воспроизводимыми tests;
- PostgreSQL-only queue выдерживает target workload;
- ни один correctness path не полагается только на Beta worker affinity;
- обязательный external egress отсутствует;
- если gate не пройден, ADR-0001 supersede-ится до R0, а dual orchestrator/fallback
  не создаётся.

Текущая реализация и evidence зафиксированы в
[`M0_HATCHET_SPIKE_REPORT.md`](M0_HATCHET_SPIKE_REPORT.md). Статус `M0-PARTIAL`:
этот vertical slice не закрывает exit gate и не разрешает production adoption/R0.

### R0 — Distill, tag, delete

До написания нового runtime:

1. утвердить этот RFC и ADRs;
2. превратить полезные требования в language-neutral specs;
3. создать JSON/YAML/SQL/Parquet golden и anti-golden fixtures;
4. связать каждый fixture с accepted/rejected requirement;
5. зафиксировать provenance tag current implementation;
6. сохранить read-only historical data/export format;
7. удалить старые Python source files, tests, entrypoints и runtime configs;
8. удалить Celery/RabbitMQ/Redis dependencies из нового dependency set;
9. создать пустой greenfield package skeleton.

Старые tests не копируются как Python code. Полезные input/output cases переписываются
как spec-backed fixtures и новые tests.

Exit gate:

- список accepted product semantics подписан;
- список intentionally rejected quirks подписан;
- новый import/build graph не содержит legacy modules;
- Git history достаточна для provenance;
- удаление является отдельным reviewable commit.

### M1 — Domain, SDK и deterministic toy plugin

- identities/manifests/outcomes;
- generic metric registry;
- search DAG/budgets/statistical decisions;
- optimizer SDK 0.x + Protobuf contracts;
- deterministic toy plugin;
- architecture/property/model tests;
- in-memory artifact/control adapters.

Exit gate:

- local toy full path deterministic;
- no backend conditionals in core;
- duplicate/out-of-order transitions safe;
- INCONCLUSIVE/NO_IMPROVEMENT/Pareto scenarios доказаны.

### M2 — PostgreSQL business state и Hatchet workflows/tasks

- migrations/repositories;
- submit/start/cancel/status commands;
- Benchmark/Target/Stage/Cleanup workflows;
- idempotent core I/O tasks;
- attempt fencing/resource registry;
- bounded retry/deadline policies;
- checkpoint replay, retry, cancellation и version-routing tests.

Exit gate:

- kill/restart API/workers resumes study;
- task retry after commit does not duplicate result;
- cancellation and stale fence work;
- backup/restore rehearsal;
- no plugin/source yet required.

### M3 — ClickHouse minimal vertical slice

Scope:

- one MergeTree table;
- sealed sample;
- B0/B0-copy;
- one useful safe candidate family;
- one parameterized workload;
- measurements/correctness;
- one stage decision/report;
- cleanup/reaper.

Exit gate:

- real ClickHouse full path;
- source DDL/count/checksum unchanged;
- exact plugin release routing;
- crash after each physical step leaves no permanent orphan;
- secret/scope tests pass.

### M4 — ClickHouse product algorithm

- complete SourceModel/capabilities;
- production-trace/manual workload;
- stratified tune/holdout;
- ORDER BY/types/codecs/granularity/skip-index stages;
- multi-fidelity beam/joint refinement;
- common/native metrics;
- final validation and migration report.

Exit gate:

- normative ClickHouse golden corpus;
- supported version/engine matrix;
- statistical improvement/tie/regression cases;
- lazy budgets and load limits;
- production plugin TCK.

### M5 — Production hardening

- internal signed OCI registry/admission;
- Secret Broker and workload identity;
- self-hosted HA deployment;
- quotas/backpressure;
- artifact retention;
- chaos/security/load;
- runbooks/alerts/operator dashboards, API и CLI;
- plugin release draining;
- disaster recovery;
- offline dependency/image bundle и blocked-egress installation test.

Exit gate:

- concurrency, cancellation and cleanup SLO;
- no secret leakage;
- Hatchet API/Engine/PG, product PG и object-store outage drills;
- source/sandbox isolation proven;
- 100 active studies проходят capacity test при bounded per-target concurrency;
- full path и restore проходят без Internet egress;
- staging soak without unexplained failures.

### M6 — Second-backend architecture probe

Implement minimal PostgreSQL plugin:

- catalog/source fingerprint;
- consistent sample;
- baseline;
- one index candidate;
- one workload;
- metrics/correctness;
- cleanup/report.

Exit gate:

- no core changes conditioned on PostgreSQL;
- plugin passes benchmark-basic TCK;
- SDK changes documented/versioned;
- only then optimizer SDK may become 1.0.

### M7 — Production rehearsal and cutover

- translate production intent into new config;
- archive historical results read-only;
- deploy exact core/plugin digests;
- freeze old submissions;
- ensure no old in-flight runs;
- synthetic smoke;
- allowlisted real studies;
- full ingress after go/no-go.

После clean-slate decision rollback возможен только к предыдущему greenfield release
либо fail-closed forward fix. Возврат к legacy runtime не является поддерживаемым path.

## 17. Что извлекается из старого проекта

Сохраняется только как specification/provenance:

- product intent;
- ClickHouse transformation vocabulary;
- принятые phased dependencies;
- config examples как requirements, не schema;
- raw metric definitions;
- representative DDL/query/data fixtures;
- scoring examples для переоценки;
- audits и failure scenarios;
- operational lessons;
- historical result export.

Не сохраняется:

- source modules/classes/functions;
- Python tests/import paths;
- Pydantic DTO shape;
- env/base64 bootstrap;
- strategy class hierarchy;
- Celery task names/payloads/events;
- Redis locks;
- legacy/phased result schemas;
- max + 1 IDs;
- physical naming;
- runner private call order;
- failure score sentinels;
- compatibility aliases.

Known bad behavior превращается в anti-golden:

- write/fallback в source namespace;
- unscored winner;
- completion after dispatch;
- event barrier;
- resume по temp-table name;
- secret/raw DDL in task;
- non-isolated retries;
- unbounded generation/wait;
- schema migration in worker;
- invalid measurement in ranking.

## 18. Plugin conformance test kit

Любой plugin обязан пройти:

### 18.1 Descriptor/package

- unique ID/version/digest/signature;
- supported backend/protocol/schema ranges;
- import/start without side effects;
- descriptor/schema hash consistency;
- SBOM/provenance checks.

### 18.2 Determinism

- stable catalog/source/candidate/sample/workload hashes;
- same seed -> same proposal/sample;
- enumeration order does not alter identity;
- round-trip native documents;
- no process-global mutable planning state.

### 18.3 Source and sandbox safety

- read-only source role;
- all writes only allocated sandbox;
- identifiers cannot escape scope;
- unsupported capability fails before resource creation;
- partial build cleanup;
- source before/after invariants.

### 18.4 Sampling/workload/correctness

- consistent snapshot contract;
- independent tune/holdout;
- parameter/session/transaction reproduction;
- unique correlation IDs;
- deterministic result digest;
- ordered/unordered result policies;
- controlled semantic corruption detection.

### 18.5 Execution/resources

- unique parallel namespaces;
- idempotent materialization/cleanup;
- cancel and timeout;
- crash before/after each physical step;
- stale fence rejection;
- orphan inventory/reaper;
- source/backend restart handling.

### 18.6 Metrics/errors

- registered key/unit/direction/scope/missing policy;
- missing is not zero;
- proxy differs from measured metric;
- raw observations append-only;
- native metrics preserved;
- typed error taxonomy;
- invalid measurement never gets numeric score.

### 18.7 Versioning/operations

- pinned release resume;
- unavailable release fails clearly;
- worker capability routing;
- release drain/retirement;
- logs/traces IDs;
- canary secret redaction;
- supported backend-version matrix.

Certification levels:

- catalog;
- benchmark-basic;
- schema-search;
- production.

ClickHouse v1 должен пройти production. Future plugin не называется supported до
benchmark-basic.

## 19. Test pyramid

### 19.1 Core without DB

Deterministic toy plugin моделирует known noisy objective surface, constraints,
timeouts, missing metrics и cleanup failures. Через него проверяются:

- paired randomization;
- multi-fidelity racing;
- beam/Pareto/diversity;
- confidence/precision stopping;
- budgets;
- every outcome;
- checkpoint replay/resume/cancel;
- duplicate/out-of-order tasks;
- bounded stage continuation and event/payload growth.

Если core tests импортируют ClickHouse DTO, boundary сломана.

### 19.2 Component

- PostgreSQL constraints/idempotent tasks/fencing;
- Hatchet durable-task checkpoint replay/retry/cancellation/version-routing;
- object-store content integrity;
- Secret Broker grants;
- plugin registry/routing;
- ClickHouse plugin live TCK.

### 19.3 E2E/chaos

- full ClickHouse happy path;
- load/soak 100 inflight studies с admission/backpressure, retries, cancellation,
  cleanup и отсутствием identity/resource collisions;
- реальная ClickHouse concurrency ограничена объявленными sandbox capacity slots;
- task duplicate/worker kill/late completion;
- Hatchet API/Engine/PG, product PG, object-store и ClickHouse outage;
- source drift;
- cancellation each stage;
- cleanup and quarantine;
- plugin version drain;
- unsafe DDL/query/tampered artifacts;
- performance/backpressure/history limits.

## 20. Architectural decisions

| Decision | Причина | Цена |
|---|---|---|
| Clean-slate, no compat | не переносить flawed lifecycle | one-time cutover, no legacy rollback |
| Generic experiment core | future backends without core forks | строгий opaque plugin boundary |
| Out-of-process OCI plugins | dependency/security/version isolation | больше deployment units |
| Hatchet durable workflows/tasks | durable stages/timers/cancel/recovery | checkpoint determinism и conditional production spike |
| PostgreSQL-only Hatchet queue | не нужен отдельный broker | общий PostgreSQL требует contention/capacity proof |
| PostgreSQL business state | transactions/fencing/audit | dual authority must stay explicit |
| S3 artifacts | immutable large native documents | retention/integrity operations |
| Protobuf + versioned documents | language-neutral plugins | schema governance |
| No universal SQL/DDL | preserve backend semantics | more plugin code |
| Pareto/confidence first | scientific correctness | harder report/UI |
| Separate sandbox | source safety | infrastructure cost |
| Optional analytics sink | no result-store coupling | eventual projection |
| Python 3.12-only v1 | один знакомый production toolchain | polyglot services и frontend отложены |
| FastAPI/Pydantic/SQLAlchemy/psycopg/Alembic/uv baseline | явный единый Python application stack | framework changes требуют ADR |
| Self-hosted closed contour | соответствует внутренней инфраструктуре и data boundary | offline supply-chain/operations обязательны |
| `1 CPU / 1024 MiB` per deployment/job | соответствует доступному resource profile | требует bounded slots и измеренного headroom |
| 100 active-study capacity target | достаточно для ожидаемого масштаба v1 | per-target concurrency всё равно требует quotas |
| No end-user auth/multi-tenancy in v1 | меньше scope при trusted internal perimeter | внешний ingress потребует security/data-model ADR |
| UI-ready API, UI deferred | не блокирует будущий browser client | frontend stack и UX не проверяются в v1 |

Self-hosted Hatchet OSS является единственным v1 orchestrator candidate. Production
adoption разрешён только после gates из ADR-0001; запасной orchestrator, Temporal и
Celery runtime параллельно не реализуются.

## 21. Production-ready Definition of Done

- old runtime code отсутствует в build/import graph;
- core содержит zero backend-specific branches/types/stage names;
- ClickHouse plugin — отдельный pinned OCI release;
- manifest pin-ит core workflow/worker, Hatchet task contract, plugin/server/profile,
  sample/workload/algorithm versions;
- concurrent studies не делят jobs/attempts/resources;
- Task retry не принимает второй result;
- late fence не меняет state/resources;
- source identity не может писать;
- baseline/candidates используют sealed data/workload;
- invalid/failed/unscored candidate не ранжируется;
- recommendation имеет correctness, confidence и practical effect;
- terminal business outcome commit-нут до workflow completion;
- all retries/waits/fan-out bounded;
- worker kill очищается Reaper в SLA;
- secrets отсутствуют в Hatchet payload/event history, PG, artifacts и logs;
- ClickHouse plugin production TCK green;
- second backend spike не требует backend branch в core;
- все maintained runtime components работают на Python 3.12;
- install/start/full path не требуют Internet egress;
- Hatchet, PostgreSQL, object store, registries и telemetry endpoints self-hosted;
- ADR-0001 HAT-01…HAT-10 gates пройдены на exact image/config digests;
- 100 active studies выдерживаются с bounded queue/concurrency и без source overload;
- Control API не требует UI и не доступен за пределами approved internal perimeter;
- cutover/backup/restore/fail-closed drills пройдены.

## 22. Первый implementation slice после RFC

1. утвердить accepted/rejected semantics;
2. создать language-neutral golden/anti-golden corpus;
3. поставить provenance tag и удалить old Python runtime отдельным commit;
4. создать новый repository skeleton/dependency gates;
5. реализовать experiment domain + optimizer SDK 0.x;
6. реализовать deterministic toy plugin;
7. реализовать один local full path до outcome/report/cleanup;
8. только затем подключить PostgreSQL/Hatchet и пройти ADR-0001 spike;
9. первый live slice ClickHouse: sample -> B0/B0-copy -> one candidate -> report;
10. review boundary до расширения ClickHouse search space.

Этот slice доказывает domain/plugin boundary раньше, чем команда напишет большой
ClickHouse worker второй раз.

## 23. Связанные документы

- [ADR-0001: Hatchet orchestrator trial](adr/0001-hatchet-orchestrator-trial.md)
- [ADR-0002: Python application stack](adr/0002-python-application-stack.md)
- [Архитектурный аудит текущего кода](ARCHITECTURE_AUDIT.md)
- [Каталог full-path рисков и сценариев](E2E_TEST_SCENARIOS.md)
- [Карта удаляемой текущей реализации](../LLM_CONTEXT.md)
- [Текущий phased algorithm как источник требований](SEQUENTIAL_PHASED_TOPN_PIPELINE_CONTRACT.md)
