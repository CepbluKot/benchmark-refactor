# Benchmark Plan Creation

## Purpose

The section creates a saved benchmark plan for one source table. The plan defines
what data is measured, which search strategy is copied into the benchmark, which
queries are executed, and which measurement limits apply. Creating a plan does not
start a run.

The product UI is Russian. Code identifiers, API fields, schemas, and persisted
documents remain English.

## Product boundaries

- One benchmark plan belongs to exactly one workspace.
- One benchmark plan targets exactly one source table.
- Data sources are global and are not owned or filtered by a workspace.
- The source connection is read-only.
- Candidate tables are created only with the isolated sandbox identity and only in
  the selected sandbox database.
- The user enters a readable plan name. Technical IDs are generated internally and
  are never shown as form fields.
- Plan creation saves configuration only. A separate explicit action starts a run.

## Navigation and layout

`Create benchmark` opens a dedicated page rather than a modal. The page contains:

- a back action to the benchmark list;
- a visible multi-step stepper;
- one focused form section at a time;
- Back and Next actions;
- Cancel on every step;
- `Create benchmark` only on the final step.

The page uses the local ADQM design system and works without Internet access or
external assets. Validation errors are displayed on the step that owns the invalid
value and prevent progression.

## Step 1: Basics

Fields:

- `Name`: required, human-readable;
- `Workspace`: required and preselected from the current workspace; shown for
  context and changed only through the existing workspace selector;
- optional human-readable description when the benchmark contract supports it.

The page must not contain a technical-ID field or a generated-configuration preview.

## Step 2: Source and table

Fields:

- `Data source`: required; only available ClickHouse sources may be selected;
- `Source table`: required, selected from tables returned by the Control API;
- `Sandbox database`: required.

The selected source table is stored as one canonical `database.table` value. The
form must not accept wildcards, multiple tables, or multiple databases.

Changing the data source clears the previously selected table and reloads the table
list. Failure to load the catalog is shown as an actionable form error. The section
must explain that the source stays unchanged and all candidate writes go to the
sandbox.

Credentials are never entered in this flow. The browser receives no password,
connection URL, or reusable secret value.

## Step 3: Search strategy

The user selects one global strategy template by its readable name. The UI may show
its description, search method, and ordered phases to help the user choose, but it
must not expose raw strategy IDs or editable technical phase names.

When the plan is created, the Control API copies the selected strategy's canonical,
versioned configuration into an immutable `strategy_snapshot` owned by the
benchmark. Later edits to the global template do not change existing plans.

Changing the strategy in an existing benchmark refreshes the snapshot only when the
user explicitly saves that benchmark.

## Step 4: Workload and measurements

### Query list

The user owns the final workload. The runtime executes only the ordered list of SQL
queries explicitly reviewed and saved in the benchmark plan.

- Queries are entered and edited as real SQL.
- The UI may generate query drafts from the selected table and insert them into the
  form.
- Generated drafts have no special status: the user can edit or remove them before
  saving.
- The runtime must not add generated, automatic, or combined queries at execution
  time.
- At least one valid saved query is required.
- Query order is preserved.
- Duplicate, empty, or unsafe queries are rejected with a field-level error.

The browser must not place full SQL text in logs, WebSocket event metadata, metric
labels, or error details. The persisted workload follows the versioned workload and
artifact contract.

### Measurement fields

The normal form contains:

- `Rows per INSERT measurement`: positive integer; number of rows copied for one
  INSERT measurement, not the number of rows returned by a SELECT query;
- `INSERT measurement repetitions`: positive integer;
- workload-query repetitions, when supported by the runtime contract;
- applicable plan-level execution limits that are not already owned by the selected
  strategy snapshot.

Every numeric field shows an explicit unit and a short explanation. Search budget
fields already stored in the selected strategy are displayed as read-only context or
omitted; they are not duplicated as independent benchmark values.

## Step 5: Review and create

The final step presents a concise human-readable review:

- plan name and workspace;
- source and `database.table`;
- sandbox database;
- selected strategy name and version;
- saved query count and query titles or short labels;
- measurement limits and repetitions.

The review does not show:

- enabled-rule counts;
- a workload summary derived from hidden automatic queries;
- limits and Top-N summaries already owned by the strategy;
- raw JSON or a generated configuration preview;
- technical IDs;
- advanced scoring expressions or named scoring variables.

`Create benchmark` is enabled only when all steps are valid. A successful command
returns to the benchmark list only after the authoritative WebSocket event confirms
the saved plan. A `202 Accepted` response is only an acknowledgement and must not be
used as local authoritative state.

## Editing and immutability

The same field groups are used when editing a plan. Saving creates a new benchmark
configuration revision. Existing runs keep the exact plan, strategy snapshot,
workload revision, source fingerprint, and limits with which they started.

Changing a plan never mutates historical run evidence.

## Validation and failure behavior

- Missing workspace, name, source, table, sandbox database, strategy, or workload
  prevents creation.
- All counts and limits must be finite positive integers within server-defined
  bounds.
- The server revalidates every field; browser validation is only immediate feedback.
- An unavailable source or failed capability check prevents a run from starting and
  does not silently select another source.
- A missing or invalid strategy snapshot prevents plan creation.
- Invalid commands create no partial benchmark record or event.
- Duplicate command delivery is handled through the Control API idempotency key.
- Errors never include credentials, secret values, connection URLs, full SQL, DDL,
  or cleanup locators.

## Required persisted contract

The saved benchmark projection must contain or reference:

- benchmark ID generated by the server;
- workspace ID;
- readable name and optional description;
- source ID;
- canonical source table;
- sandbox database;
- selected strategy ID for catalog traceability;
- immutable versioned strategy snapshot;
- immutable versioned workload reference or snapshot;
- measurement limits and repetitions;
- aggregate revision and timestamps.

The exact wire and persistence schema must be versioned. Backend-specific native
documents remain owned by the ClickHouse plugin and are not interpreted by the
generic core.

## Acceptance criteria

- A user can create a plan for one real table through the complete page flow.
- No technical ID is requested from the user.
- Selecting a source reloads its real table catalog and clears stale selection.
- The plan cannot contain more than one source table.
- The saved strategy snapshot is unchanged after the global template is edited.
- Query generation inserts editable drafts only; execution uses exactly the saved
  ordered query list.
- `Rows per INSERT measurement` is labelled and described unambiguously.
- The final review contains only user-relevant choices listed in this specification.
- Creating a plan does not start a run.
- UI state changes only after the durable WebSocket event.
- Typecheck, production build, UI-kit check, Control API contract checks, and a real
  browser flow pass.

## Related contracts

- [Workspaces, benchmarks, and strategy templates](../../docs/superpowers/specs/2026-09-17-workspaces-and-benchmarks-design.md)
- [Strategy template wizard](../../docs/superpowers/specs/2026-09-21-strategy-template-wizard-design.md)
- [Strategy management](strategy-management.md)
- [Control API realtime v1](control_api_realtime_v1.md)
