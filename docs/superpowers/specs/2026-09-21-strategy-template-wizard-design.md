# Strategy Template Wizard

## Goal

Replace modal-based strategy creation with a dedicated multi-step page for reusable
search-strategy templates. A template contains portable search rules, budgets, and
scoring preferences. Selecting a template while creating a benchmark copies its
configuration; later template edits never change existing benchmarks.

The current product UI uses Russian copy. Code identifiers and protocol fields remain
English.

## Scope

The page creates and edits global strategy templates. It does not configure a data
source, source table, test database, credentials, workspace, run state, or workload.
The strategy entity ID is generated internally and is never shown or entered by
the user.

Workload remains benchmark-owned because queries depend on the selected table. A
future benchmark workload editor may generate editable query drafts, but runtime
execution must use only the queries explicitly reviewed and saved by the user.

## Navigation and layout

`Create strategy` opens a dedicated product page rather than a modal. The page uses
the ADQM design system and has:

- a back action to the strategy catalog;
- a horizontal four-step stepper with numbered circles and completed-step markers;
- one centered, wide form card with a heading and guidance for the active step;
- no persistent summary strip or summary sidebar (user-approved design revision);
- Back and Next actions;
- Cancel on every step;
- Create strategy only on the final step.

Validation errors are shown on the owning step and prevent progression when a
required value is invalid.

The selected visual direction is the focused wizard (option B). Use explanatory
selection cards for methods and priorities, descriptive switch rows for rules,
and explicit guidance for optional constraints and final-validation alternatives.
Keep the action footer inside the form card. On narrow screens, wrap form fields
and preserve readable step labels. This layout applies to both creation and editing.

## Step 1: Basics

- Name: required, human-readable.
- Description: optional.

No technical identifier or pipeline preview is shown on this step.

## Step 2: Search Configuration

Search procedure and variant rules share one step, in clearly separated sections.
The wizard sequence is Basics, Search Configuration, Search Budget, Scoring.

### Search Method

The user selects one method from large explanatory cards:

- Types;
- Indexes;
- Combined;
- Sequential Top-N;
- Phased Top-N.

Each card explains the method's purpose. After selection, the page shows the derived
pipeline. Phases are fixed by the method and cannot be manually edited.

The implemented pipelines are:

- Types: types and codecs;
- Indexes: skip indexes;
- Combined: types, codecs, and indexes in one combined search;
- Sequential Top-N: types and codecs, Top-N selection, then indexes;
- Phased Top-N: ORDER BY, types, codecs, table index granularity, indexes, and final
  validation with optional nearby index alternatives.

### Variant Rules

The page exposes only rule groups used by the selected method:

- column type alternatives;
- codec alternatives;
- skip-index types and index granularity;
- table `index_granularity` alternatives;
- ORDER BY candidates;
- column order.

Rules preserve the current engine distinctions between column rules, codec rules,
index rules, skip-index granularity, and table index granularity. Irrelevant groups
are hidden rather than disabled. The template stores explicit portable rules; the
user does not select or edit a separate rule-bank entity.

## Step 3: Search Budget

Default fields:

- Rows copied per INSERT measurement.
- INSERT measurement repetitions.
- Maximum candidates.
- Top-N winners.

The same row limit applies to baseline and candidate measurements by default.

Advanced settings:

- separate baseline and candidate row limits;
- per-phase candidate limits;
- winners per parent candidate;
- final-validation input size;
- index alternatives checked during final validation.

`Index alternatives checked during final validation` applies only to Phased Top-N.
A value of one checks only the best index combination. Higher values also replace
one column at a time with its second-, third-, and later-ranked index option. It does
not recursively enumerate every combination.

Method-specific budget controls are hidden when the selected method cannot use
them. All numeric values are positive integers and receive explicit units.

## Step 4: Scoring

The normal UI offers optimization priorities:

- Balanced;
- Faster reads;
- Faster inserts;
- Better compression.

Optional hard constraints:

- maximum storage growth;
- maximum INSERT slowdown;
- minimum SELECT improvement.

The UI does not expose raw scoring expressions, named expression variables,
maximize/minimize direction, or per-phase scoring overrides. The backend maps each
supported priority to a versioned scoring definition and stores the chosen priority
and constraints in the template configuration.

## Removed concepts

Strategy creation does not include:

- workload or query configuration;
- a separate review step;
- a technical ID field;
- manual phase names;
- generated configuration preview;
- rule-count, workload, limits, or Top-N summary blocks;
- raw scoring expressions;
- named scoring variables;
- maximize/minimize controls;
- per-phase scoring overrides.

## Persistence and contracts

The current `name`, `strategy`, and `phases` strategy record is insufficient. The
strategy contract must gain a versioned template configuration containing:

- optional description;
- selected search method;
- portable variant rules;
- search-budget settings;
- scoring priority and hard constraints;
- schema version.

Derived phases are validated from the selected method and are not accepted as an
independent user-authored list. Strategy create/update commands remain acknowledged
with HTTP 202, while the browser continues to receive authoritative state through
the durable WebSocket event stream.

Deleting a strategy used by a benchmark remains forbidden. Updating a template
changes the configuration used by future benchmark copies and does not mutate
configuration already copied into existing benchmarks.

This contract changes the public API and persistence schema and therefore requires
an ADR plus a database migration before implementation.

## Validation

- Name is required.
- Search method is required.
- Every visible rule and budget value must satisfy the current engine contract.
- Hidden method-inapplicable fields are removed from the submitted configuration.
- Scoring constraints must be finite and use explicit percentage units.
- The backend independently validates the entire versioned template document.
- Invalid commands create no strategy event or partial record.

## Verification

- focused unit tests for method-to-phase derivation and method-specific field pruning;
- API tests for create, update, bootstrap, events, invalid documents, and deletion guard;
- persistence migration and round-trip tests;
- UI tests for step validation, conditional rule groups, Simple/Advanced budgets,
  cancellation, and final submission;
- `npm run typecheck`;
- `npm run check:ui-kit`;
- production frontend build;
- Control API checks;
- Docker rebuild and recreation;
- browser verification of the complete strategy-creation flow;
- `git diff --check`.
