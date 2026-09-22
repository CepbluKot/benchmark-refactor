# Repository instructions for coding agents

## Scope

This file applies to the entire repository unless a deeper AGENTS.md overrides it.

Communicate with the user in Russian unless they use another language. Use English
for code identifiers, protocol fields, schemas, and package names. Architecture and
product documentation may remain in Russian.

## AI execution workflow

For Codex work, the root agent must read and follow
[docs/AI_EXECUTION_WORKFLOW.md](docs/AI_EXECUTION_WORKFLOW.md). It classifies
each request and, when useful, delegates scoped work to Luna Low or read-only
planning to Sol Medium while Terra Medium owns implementation and verification.
The user does not need to route models or transfer briefs between tasks. The
architecture, security, authorization, and verification rules in this file
remain authoritative.

## Current repository state

The repository currently contains a legacy ClickHouse + Celery implementation, a
clean-slate target design, and an isolated greenfield M0 Hatchet architecture spike.
The production target implementation has not started yet.

Do not confuse these two systems:

- Current implementation: existing src, tests, main.py, Celery tasks, ClickHouse
  result schemas, README runtime instructions.
- Target implementation: DB-neutral experiment core, Hatchet durable workflows/tasks,
  PostgreSQL business state, immutable artifacts, and out-of-process database
  plugins, with ClickHouse as the first plugin.
- M0 spike: toy-only feasibility code under the target package layout. It is evidence
  for ADR-0001, not the production engine or a compatibility runtime.

The product decision is to delete and rewrite the legacy implementation, not to
incrementally refactor it. This decision does not authorize deletion during an
unrelated task.

## Locked target stack and operating profile

These choices are explicit product constraints for the greenfield runtime.

### Language and contracts

- Write all maintained v1 application, workflow, task, CLI, service, SDK, and
  ClickHouse plugin source in Python 3.12.
- Declare the target interpreter range as `>=3.12,<3.13` and test against a supported
  Python 3.12 patch release. Production images pin one approved 3.12.x patch and its
  digest. Do not claim support for another minor version without CI evidence and an
  accepted change.
- Do not introduce maintained Go, Rust, Java, or Node.js application, workflow, task,
  CLI, SDK, or plugin source in v1. Generated Protobuf stubs, declarative deployment
  files, and pinned third-party infrastructure binaries such as Hatchet/PostgreSQL
  are not independent maintained application implementations.
- Keep wire contracts language-neutral and versioned even though every v1 runtime
  consumer is Python. A future database plugin may remain Python; another language
  requires a deliberate architecture/toolchain decision.
- A browser UI is a possible later client, not a v1 deliverable. Its frontend stack
  is not selected. Keep the Control API usable by CLI and a future UI without adding
  frontend tooling now.

### UI design system

- For any explicitly requested UI design or frontend work, use the local
  [ADQM design system](/home/oleg/Documents/Codex/2026-09-11/new-chat/work/adqm_design_system-repo/README.md)
  as the visual and component source of truth.
- Read its [React UI documentation](/home/oleg/Documents/Codex/2026-09-11/new-chat/work/adqm_design_system-repo/react-ui/README.md)
  before implementation. Reuse the `@adqm/gpb-ui` components, theme tokens, fonts,
  spacing, and interaction patterns; extend them consistently when needed instead
  of introducing a competing UI kit or visual language.
- Use the library's supported themes. Package styles, fonts, icons, and other
  assets locally so the UI works without Internet access or external CDNs.
- Adapt components to actual benchmark configuration and result contracts; the
  design-system demo data and cluster-management screens are not product requirements.
- Product state must come from the versioned Control API. After the initial
  snapshot, every state transition visible in the browser is delivered through
  the durable WebSocket event stream; REST mutation responses acknowledge a
  command and never act as authoritative UI state. Do not add polling or SSE.
- Do not add mocks, demo fixtures, simulated completions, synthetic candidates,
  or fake connection/run results to product runtime, component tests, or E2E
  checks. Integration proof uses disposable real PostgreSQL, ClickHouse, and
  the configured orchestration path. Pure deterministic unit tests may use
  explicit in-memory values only when they do not stand in for runtime evidence.
- This design-system choice applies to UI work when requested; it does not add a
  browser UI to the target v1 scope or change the Python server stack.
- Product-facing React screens must use `@adqm/gpb-ui` controls rather than raw form
  elements or a parallel UI kit. Before handing off UI work, run
  `npm run check:ui-kit`, typecheck and production build. The local `/design-system`
  catalogue is the reference for choosing a supported component.

### Closed-contour deployment

- Production runs in a private network with no Internet access and only internal
  infrastructure connectivity.
- Every locally built, loaded, exported, or deployed OCI/Docker image must use the
  literal tag `:local`. This applies to Dockerfiles, Compose `image:` values, build
  commands, deployment commands, archives, and handoff instructions. Do not use
  `:latest`, commit-derived tags, timestamps, or ad hoc feature tags for local
  images. Production release identity remains the pinned immutable digest; `:local`
  is the only permitted mutable tag for local workflows.
- Hatchet, PostgreSQL, and S3-compatible object storage are self-hosted inside that
  contour. Do not depend on Hatchet Cloud, public object storage, or a SaaS control
  plane.
- Runtime and deployment must make zero outbound Internet calls. This includes
  telemetry exporters, update checks, schema fetches, remote UI assets, public
  plugin discovery, and license/feature activation.
- Python packages, OCI images, OS packages, Protobuf toolchains, and vulnerability or
  signature metadata needed by the build must be pinned and available from approved
  internal mirrors/registries or an imported offline bundle.
- Deployments must not pull from PyPI, Docker Hub, GitHub, public CDNs, or other
  external registries. Prove installation and startup with egress disabled.
- All observability, secret storage, image distribution, backup, and restore paths
  used in production must terminate on internal infrastructure.
- The Hatchet spike uses PostgreSQL-only messaging and sets
  `SERVER_MSGQUEUE_KIND=postgres`, `SERVER_MSGQUEUE_PUBSUB_KIND=postgres`, and
  `SERVER_SECURITY_CHECK_ENABLED=false`. Disable or internalize public telemetry,
  OAuth, SMTP, security/update, and remote UI asset endpoints; prove this with
  deny-all egress rather than configuration review alone.

### Capacity and admission

- Design v1 for at most 100 simultaneously active, nonterminal studies. Treat this as
  a capacity assumption and acceptance-test target, not as an unbounded promise.
- Enforce a hard maximum of `1 CPU / 1024 MiB` for each individual deployment/job in
  the Hatchet spike and target profile. One deployment with multiple replicas is
  evaluated by its aggregate requested/limited resources, not by hiding cost per pod.
- Do not translate 100 active studies into 100 simultaneous database operations.
  Enforce separate bounded queues and configurable concurrency/resource quotas per
  target profile, plugin pool, and operation class.
- Admission must backpressure or queue work when a target or worker pool reaches its
  declared limit. It must not overload a source or sandbox merely to keep all studies
  physically executing.

### Identity and access scope

- V1 is one trusted internal deployment. Do not build end-user accounts, RBAC,
  multi-tenancy, tenant billing, or corporate identity-provider integration.
- The lack of end-user auth does not relax service identity, network perimeter,
  source read-only credentials, sandbox roles, secret handling, or audit requirements.
- Do not expose the unauthenticated Control API outside the approved internal network.
- Do not prebuild speculative tenant abstractions. Adding users, RBAC, multi-tenancy,
  or an external UI ingress requires a separate security/data-model ADR.

No organizational license restriction is currently imposed, but dependencies must
still be pinned, reviewable, internally distributable, and included in provenance/SBOM
checks.

The Python application baseline is FastAPI, Pydantic v2 at boundaries, SQLAlchemy 2,
psycopg 3, Alembic, Typer, `uv`, pytest, and Hypothesis as recorded in ADR-0002.
Exact dependency versions belong in the lockfile. The PostgreSQL major,
S3-compatible implementation, Secret Manager, deployment substrate, and future UI
stack are not locked yet; record those choices in an ADR before implementation.

## Source of truth

Read the relevant documents before changing architecture or behavior:

1. docs/TARGET_ARCHITECTURE_REFACTOR.md
   - normative target architecture and clean-slate implementation plan;
2. docs/adr/0001-hatchet-orchestrator-trial.md
   - Hatchet trial decision and mandatory production acceptance gates;
3. docs/adr/0002-python-application-stack.md
   - accepted Python application framework/tooling baseline;
4. docs/ARCHITECTURE_AUDIT.md
   - evidence about the current implementation and known risks;
5. docs/M0_HATCHET_SPIKE_REPORT.md
   - current M0 implementation evidence and strict HAT gate status;
6. docs/E2E_TEST_SCENARIOS.md
   - current-runtime risk corpus and future acceptance requirements;
7. LLM_CONTEXT.md
   - map of the current code only;
8. docs/SEQUENTIAL_PHASED_TOPN_PIPELINE_CONTRACT.md
   - current phased behavior as a requirements source, not an automatically
     preserved target contract;
9. README.md
   - current operational instructions, not target architecture.

When documents conflict about the future system, an accepted ADR wins for its scoped
decision and the target RFC wins otherwise. Hatchet is accepted only for the
ADR-0001 architecture spike until its production gates pass. When describing current
behavior, verify it against code and tests.

## Clean-slate policy

The new runtime must not depend on or import the legacy implementation.

Do not add:

- compatibility facades;
- legacy import aliases;
- old Celery task or payload support;
- legacy/phased result-schema dual writes;
- shadow execution of the same physical benchmark;
- old strategy classes wrapped by new interfaces;
- a legacy package inside the new source tree;
- feature flags that switch between legacy and target orchestrators.

Legacy code may be read only to extract requirements, fixtures, metrics, and failure
cases. Do not copy implementation code into the new packages.

### R0 deletion gate

Deleting the legacy runtime requires a separate explicit user task. Before deletion:

1. approve accepted and intentionally rejected behavior;
2. create language-neutral golden and anti-golden fixtures;
3. link each fixture to a written requirement;
4. preserve a provenance Git tag/history reference;
5. define a read-only historical-result export;
6. produce an exact deletion inventory;
7. make deletion a standalone reviewable change.

Never infer permission to delete src, tests, configs, entrypoints, or deployment
files merely because the target is a clean-slate rewrite.

If an implementation request is ambiguous between legacy maintenance and the new
system, ask one concise question before editing code.

## Product contract

The system is a reproducible physical-design experiment engine.

Given a database backend, source object, sealed data samples, versioned workload,
allowed physical-design search space, objective, and budget, it produces an
evidence-backed recommendation.

It does not automatically migrate the source object.

Terminal scientific outcomes are:

- RECOMMENDED;
- NO_IMPROVEMENT;
- PARETO_SET_REQUIRES_POLICY;
- INCONCLUSIVE;
- FAILED;
- PARTIAL;
- CANCELLED.

Failure, missing data, timeout, or an invalid candidate must never be encoded as a
numeric score.

## Architecture boundary

Generalize the experiment protocol, not database semantics.

### Generic core owns

- study/experiment lifecycle;
- immutable manifests and fingerprints;
- search DAG execution;
- budgets, admission, cancellation, and deadlines;
- logical jobs, physical attempts, leases, and fencing;
- paired randomized experiment blocks;
- generic metric registry and observation envelopes;
- quality gates and error taxonomy;
- Pareto/confidence-aware selection;
- ranking snapshots, outcomes, and provenance;
- logical resource ownership and cleanup state.

### Generic core must not know

- ClickHouse, PostgreSQL, or MySQL driver types;
- SQL or DDL dialects;
- MergeTree, codec, skip index, BRIN, GIN, fillfactor, or clustered-index concepts;
- database-specific stage names;
- database-specific cache, maintenance, or query-plan fields;
- physical database/table/schema/query locators;
- backend-specific migration commands.

There must be no backend-ID conditional in core. If adding a backend requires an
if/elif branch in core, the plugin boundary is wrong.

### Database plugin owns

- profile validation and capability handshake;
- catalog/source-model capture;
- snapshot and sample implementation;
- workload parsing, binding, safety, and correctness oracle;
- transformations, candidate generation, and backend stage DAG;
- candidate canonicalization, validation, and compilation;
- physical materialization and measurement;
- native telemetry and standard-metric mapping;
- backend error classification;
- physical resource operations;
- backend-native recommendation and migration-plan rendering.

A plugin must not own run state, retries, fencing, accepted-result uniqueness,
ranking snapshots, or control-database migrations.

## Plugin model

Plugins are admin-approved, signed, pinned OCI releases from an internal registry.
Signing trust roots and verification metadata must also be available inside the
closed contour. The Control Service and deterministic Hatchet durable tasks must not
import executable plugin code.

Every StudyManifest pins:

- core workflow release ID and exact core worker OCI digest;
- Hatchet SDK/task-contract version, release-specific workflow/action names, and
  observed Hatchet server capability/build fingerprint;
- plugin ID and semantic version;
- exact OCI digest;
- descriptor and schema hashes;
- plugin protocol versions;
- backend server/capability fingerprint;
- public profile revisions;
- algorithm, metric, and measurement-contract versions.

Hatchet task payloads contain small versioned JSON operation references and hashes,
not Python class paths or large native documents. Public plugin service contracts are
language-neutral, versioned Protobuf plus content-addressed native documents.

Runtime installation or import selected by user input is forbidden.

The optimizer SDK remains pre-1.0 until a real second backend implements a minimal
vertical slice without backend-specific changes in core.

## ClickHouse plugin rules

ClickHouse is the first plugin, not a core dependency.

ClickHouse v1 may optimize:

- ordering and primary-key design within an explicit engine contract;
- safe physical column types;
- column codec pipelines;
- index_granularity and index_granularity_bytes;
- skip indexes and their parameters;
- bounded joint refinement.

Partitioning, TTL, replication, projections, constraints, and MergeTree semantic
family are locked in v1 unless a separate RFC says otherwise.

Fail closed for unknown engines or server capabilities. Do not silently degrade.

ClickHouse-specific stage names belong only to the ClickHouse plugin.

Source credentials are read-only. Benchmark writes require a separately isolated
sandbox. Falling back to the source database is forbidden.

## Hatchet workflow and task rules

Hatchet OSS self-hosted is the only target orchestrator candidate. Until the
ADR-0001 gates pass, implement only the isolated architecture spike; do not represent
Hatchet as a proven production baseline and do not build a parallel fallback runtime.

Hatchet owns execution progression and task delivery. Product PostgreSQL stores
immutable business facts, accepted results, fencing, resources, and audit/status
projections. Application code never reads Hatchet internal tables.

Hatchet durable orchestration tasks must be deterministic between checkpoints:

- use durable context only for waits/event waits/child spawning;
- no database, network, filesystem, secret, or plugin access;
- no process environment as business input;
- no ambient clock, random, or UUID values in control flow;
- branch only on event history and persisted child-task outputs;
- use only small versioned reference payloads;
- no unbounded child fan-out, event-log, or payload growth.

Regular child tasks perform I/O and are at least once. They must be idempotent at the
domain boundary and define explicit bounded retry, scheduling timeout, and execution
timeout policies. A commit must be safe if execution repeats after a worker crash.

There is no assumed direct equivalent of Continue-As-New. A bounded run seals its
snapshot in PostgreSQL, atomically creates a successor outbox command with a
continuation number/hash, and completes before the starter launches the successor.

Hatchet cancellation is cooperative. Product desired state, domain lease/fence, and
the independent Reaper remain authoritative even when physical work stops late.
Terminal workflow completion happens only after the PostgreSQL terminal business
outcome is committed idempotently.

Use PostgreSQL-only Hatchet messaging and disable RabbitMQ. Hatchet and product state
may share one physical PostgreSQL deployment during the spike only through separate
databases, roles, credentials, and migration paths. Exact release routing uses
release-specific workflow/action names and separate worker deployments; Beta worker
affinity is never the sole correctness boundary.

## Attempts, fencing, and resources

Logical job, Hatchet workflow/task-run correlation, physical invocation, and domain
attempt are distinct identities. Hatchet IDs are diagnostic correlation only, never
the fencing authority. Every physical invocation has a stable begin-request ID for
idempotent `BeginAttempt` RPC handling.

Each physical execution receives:

- a fresh attempt ID;
- a monotonic fence token;
- attempt-scoped resources;
- a bounded lease/deadline;
- exact plugin/profile/spec fingerprints.

Every external side effect and result commit checks attempt ID plus fence.

A late attempt must not:

- commit a result;
- mutate current state;
- delete a newer attempt's resource;
- reuse a scratch resource.

Register a physical resource before creating or using it. Worker cleanup is a fast
path; the independent Reaper is the recovery path.

Physical locators are server-approved plugin documents. Never trust a database,
table, schema, query, file, or object-store locator from user input or a raw task
payload.

## Scientific validity

The following invariants are mandatory:

1. source data and schema are not modified;
2. each fidelity compares baseline and candidates on the same sealed sample;
3. tune and holdout samples are independent and versioned;
4. baseline and candidate use the same workload case, parameters, and regime;
5. B0 and B0-copy establish an environmental noise/control bound;
6. baseline anchors are measured contemporaneously, not only once at run start;
7. semantic validation precedes ranking;
8. search budget is separate from measurement repetitions;
9. raw observations are append-only;
10. timeout, OOM, and correctness failure are not discarded as outliers;
11. final recommendation is validated on an independent holdout;
12. missing evidence produces INCONCLUSIVE, not a fallback winner.

Use hard constraints before Pareto ranking, confidence bounds, and scalar utility.
Scalar utility may choose only among feasible candidates.

## Persistence and artifacts

Self-hosted PostgreSQL is the fixed target control/business database. Do not make
this storage pluggable merely for symmetry with benchmark backends.

Use relational columns for common searchable identities/state and immutable,
schema-tagged content-addressed documents for plugin-native bodies.

Core must not read undocumented keys from plugin-native documents.

Large catalogs, samples, plans, raw observations, diagnostics, and reports belong in
an immutable self-hosted S3-compatible artifact store inside the closed contour.
PostgreSQL stores authoritative summaries and references.

An analytics sink is optional and rebuildable. Its outage must not change execution
or terminal outcomes.

Schema migrations are run by a dedicated migrator. Workers never migrate control or
analytics schemas.

## Security

Never place reusable credentials, raw connection URLs, sensitive literals, full DDL,
or cleanup targets in:

- Hatchet task inputs/outputs/errors, workflow/task state, and durable event log;
- PostgreSQL native documents;
- logs or exception messages;
- metric labels;
- workflow/task payloads;
- artifact metadata.

Use workload identity and short-lived scoped secret grants.

Keep source, sandbox, cleanup, and migrator roles separate.

Plugin workers have no direct unrestricted PostgreSQL access. Use narrow
Attempt/Resource/Artifact APIs.

Treat plugins as privileged supply-chain artifacts: require signed immutable images,
exact digests, descriptor/schema validation, SBOM/provenance policy, and explicit
release draining. All images, trust roots, verification inputs, secret services, and
telemetry endpoints used by this path must be internal and usable without Internet
egress.

## Target repository structure

Follow the package layout in docs/TARGET_ARCHITECTURE_REFACTOR.md:

~~~text
specs/
fixtures/golden/
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
apps/
adapters/
deploy/
tests/
~~~

Do not introduce a new greenfield architecture under the legacy flat src layout.
Do not create compat or legacy packages.

Dependency direction:

~~~text
experiment_domain      optimizer_sdk
        ^                    ^
        +---- experiment_engine
                  ^
       durable workflows/I-O tasks

optimizer_sdk <- plugin_clickhouse

apps/adapters compose dependencies
core never imports a backend plugin
~~~

## Coding standards for new code

- Prefer immutable domain values and explicit state transitions.
- Keep framework DTOs at I/O boundaries; do not leak them into domain logic.
- Use complete type annotations and avoid untyped dictionaries across boundaries.
- Use explicit units in metric names/types.
- Reject non-finite numeric values at ingestion.
- In Hatchet durable tasks, derive control flow only from event history and persisted
  child-task outputs; inject clock, ID, and randomness through those outputs.
- Make canonical serialization deterministic and versioned.
- Avoid process-global mutable registries or import-time side effects.
- Keep I/O in regular tasks/adapters and pure decisions in domain/engine.
- Keep errors typed; do not branch on exception-message text.
- Keep public contracts small and capability-driven.
- Comments should explain invariants and reasons, not restate code.

Do not add a runtime framework, database, broker, or plugin mechanism that contradicts
the RFC without an accepted ADR.

## Development workflow

Before editing:

1. identify whether the task targets legacy, R0, core, orchestration, or a plugin;
2. read the relevant RFC/spec sections;
3. list affected contracts, persisted documents, and failure paths;
4. check the worktree and preserve unrelated user changes;
5. choose the smallest vertical slice that proves the contract.

During implementation:

- update specs before or with behavior;
- add tests for success, failure, retry, cancellation, and cleanup as applicable;
- keep changes within one architectural boundary where practical;
- never silently add compatibility behavior;
- never relax a security or scientific invariant to make a test pass.

At handoff report:

- outcome first;
- changed files/contracts;
- tests and checks actually run;
- checks not run and why;
- migrations/deployment impact;
- remaining risks or explicit follow-up.

## General development practices

These practices are adapted from the Proactive Monitoring workspace's development
rules. This repository's architecture, runtime contracts, resource limits, and
explicit authorization rules remain authoritative.

### Source ownership and artifacts

- Read the nearest component instructions and derive commands from that component;
  do not assume another repository's build or test commands apply here.
- Fix the authoritative source and regenerate derived bundles, schemas, snapshots,
  or exports. Do not hand-edit generated output unless the task targets that export.
- Keep durable deliverables, manifests, and checksums in this repository. Temporary
  processing directories must not become the only copy of a deliverable. Preserve
  source provenance and report any intentionally external artifact location.
- Before declaring a file or component missing, inspect its actual filesystem path,
  including ignored and untracked files; Git visibility alone is not evidence of
  absence. Do not reconstruct source from an archive or image without verification.

### Regression and contract verification

- For a reproducible behavioral bug, establish a focused failing test before
  accepting the fix and retain it as a regression test. If the component cannot
  reproduce it locally, report the missing coverage explicitly.
- Make the smallest coherent change at the owning layer. For changes consumed by
  multiple components, verify producers and consumers and regenerate affected
  contract artifacts.
- For material reliability, security, state-machine, SQL, scale, or cross-component
  changes, use read-only subagents for boundary/test analysis and final diff review.
  Keep parallel work read-heavy; never assign overlapping edits concurrently.
- Tests, typechecks, artifact checks, and runtime evidence take precedence over LLM
  review. Review cannot waive a failed check. Preserve reusable failure cases in
  sanitized regression fixtures without copying production secrets or payloads.
- For authorized deployment changes, verify health and at least one real semantic
  path. A running container or HTTP success alone does not prove correct behavior.
  Use a verified deployment definition; do not invent one from container inspection.
- Hooks and automated review provide guardrails, not proof that tests ran or
  authorization for deployment, commits, destructive actions, or external writes.

### Reliability and diagnostics

- Preserve stable correlation identities across service and task boundaries. After
  an ambiguous timeout or broken response to a side-effecting request, reconcile the
  existing operation before retrying; use the contract's idempotency mechanism.
- Validate semantic outcomes separately from transport success. Stale observations
  must not regress terminal state or overwrite newer authoritative state.
- Recovery must be bounded and follow persisted execution intent and the owning
  state-machine contract. Missing intent is not permission to execute old work.
  For recovery changes, compare state before and after startup, including dormant
  and terminal work, and verify that only eligible operations resume.
- Emit bounded structured application logs with timestamps, severity, component,
  event, and available correlation IDs. Record durations, classified failures, and
  actual accepted state transitions at I/O boundaries; respect the prohibition on
  I/O and ambient clocks inside deterministic durable orchestration tasks.
- Make background failures and reconciliation outcomes diagnosable. Redact secrets
  recursively, including exception text and stack traces; prefer safe counts and
  fingerprints to full payloads, SQL, or native documents. Test changed error paths
  for correlation and redaction as well as behavior.
- Keep visualization sampling separate from experiment inputs and raw evidence.
  Bound frontend processing and display volume; avoid unbounded recursion or
  spreading large arrays into function arguments. Define stable pagination semantics
  rather than inferring totals from the currently loaded page.

## Testing and quality gates

Do not claim green tests unless they were executed.

New core changes require:

- unit/property tests for deterministic pure logic;
- state/model tests for duplicate and out-of-order transitions;
- architecture import-boundary tests;
- deterministic toy-plugin coverage;
- explicit missing/invalid metric cases.

Plugin changes require the applicable plugin TCK profiles:

- descriptor/package;
- determinism;
- source/sandbox safety;
- sample/workload/correctness;
- execution/resources;
- metrics/errors;
- versioning/operations.

Distributed changes require real component/E2E coverage proportional to risk:

- PostgreSQL uniqueness/fencing;
- Hatchet checkpoint replay/retry/cooperative cancellation/version-routing/recovery;
- Hatchet API/Engine/Hatchet-PG/product-PG outage and outbox reconciliation;
- exact A/B release-specific action routing without relying only on Beta affinity;
- bounded checkpoint/event/payload growth and successor-run continuation;
- object-store integrity;
- worker crash and late completion;
- resource cleanup/reaper;
- concurrent studies;
- source immutability;
- secret-redaction canary;
- blocked-egress installation/startup/full-path execution;
- every required deployment/job under `1 CPU / 1024 MiB`;
- bounded-load behavior at 100 active studies and explicit admission rejection for
  the 101st submission where applicable.

Legacy tests are evidence about the current implementation, not target contracts.
After R0 they are deleted and replaced by spec-backed new tests.

For documentation-only work, at minimum run:

- local Markdown link validation;
- trailing-whitespace check;
- git diff --check.

## ADR triggers

Create or update an ADR before changing:

- Hatchet versus another orchestrator;
- PostgreSQL business-state ownership;
- generic core versus plugin responsibility;
- plugin execution/trust model;
- wire/document/persistence schema;
- identity, fencing, or terminal-state semantics;
- sample/workload/statistical contract;
- mandatory metric definitions;
- source-write or migration authority;
- secret, ACL, or sandbox boundaries;
- clean-slate deletion/cutover policy;
- support for a new database backend;
- the Python minor version or introduction of another production language;
- the API/persistence/dependency/deployment framework baseline;
- end-user authentication, RBAC, multi-tenancy, or external UI ingress.

## Destructive and Git operations

Do not use destructive Git commands or discard unrelated changes.

Do not delete legacy code outside the explicit R0 deletion task.

Before any material deletion:

- resolve exact targets;
- verify provenance/spec/fixture gates;
- show the deletion inventory;
- keep the operation reviewable and recoverable through Git history;
- report what was removed.

Do not commit, tag, push, or publish artifacts unless the user explicitly requests it.

## Definition of done

A task is complete only when:

- behavior matches the relevant target/current contract;
- architecture boundaries remain intact;
- source safety and secret handling are preserved;
- retry/idempotency/cleanup paths are addressed;
- no unapproved Internet or public-registry dependency was introduced;
- the Python 3.12-only boundary is preserved unless the task explicitly changes it;
- required tests/checks pass or missing checks are disclosed;
- affected specs and documentation are synchronized;
- no unrelated user work is overwritten;
- the final response clearly distinguishes completed work from future work.
