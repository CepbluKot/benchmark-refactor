# Scoring step: formula editor, presets, and variable reference

## 1. Scope and precedence

This is a documentation-only implementation handoff. Do not mistake it for an
implemented scoring service or a verified production scoring contract.

Latest user request: scoring must show the actual formula, provide formula presets,
and explain available variables. This supersedes the previous restriction against
formula editing in the strategy wizard. Keep the approved four-step layout and no
summary strip. Scoring remains the last step, `Оценка`.

This document replaces section 12 and the formula-related exclusions of
[the main page handoff](strategy-editor-page-handoff.md).
UI labels are Russian; identifiers are English. Communicate with the user in English.

User-approved intent: actual formulas, presets, and variables.
Proposed design choices in this handoff: exact preset weights, default aggregation,
catalog layout, and new document shape. Implement them as explicitly versioned
policy choices; do not describe them as previously established engine defaults.

## 2. Verified sources and important limitations

Read these before implementation:

- [Legacy evaluator and root/function allowlists](../../src/benchmark_runtime/implementations/clickhouse_celery/scoring.py)
- [Actual scoring-context construction](../../src/benchmark_runtime/implementations/clickhouse_celery/tasks.py)
- [Pre-run expression validation](../../src/scoring_validation.py)
- [Existing formula editor](../../apps/config_editor_ui/src/components/scoring/ScoringEditor.tsx)
- [Frontend vocabulary](../../apps/config_editor_ui/src/lib/vocab.ts)
- [Current Control API](../../apps/realtime_control_api/src/realtime_control_api/main.py)
- [Existing scoring tests](../../tests/test_clickhouse_celery_scoring_expression.py)

Verified facts:

1. A legacy simpleeval-based evaluator exists, with explicit operators/functions.
2. The current product API scoring object stores `priority` and three constraints;
   it does not store arbitrary expression text or named formula definitions.
3. The current local run endpoint does not consume strategy scoring/configuration.
4. A name in the allowlist does not guarantee that a runtime context supplies it.
5. `ratios.select` is populated from `medians.select_read_bytes_speedup`, NOT SELECT
   time acceleration. Never use it in a preset advertised as faster SELECT latency.
6. Some legacy byte metrics substitute ratios when measurements are absent/zero.
   Such effective fields are not necessarily physical byte measurements.
7. Legacy fallback scores and forced score=-1 cases exist. Do not carry these into
   the new scientific contract: missing evidence and errors must remain typed states.

Legacy implementation is a requirements source, not an importable target component.
The generic target core must not learn ClickHouse-specific context keys. A future
plugin metric registry must map them at the appropriate boundary.

## 3. Page layout, top to bottom

Use the existing centered form card, max-width 1080px, with 32px desktop padding.
Keep the four-step horizontal navigator above it.

```text
Оценка
Задайте формулу, по которой сравниваются допустимые варианты.

Пресет формулы                         [Сбалансированно ▾]
Description of selected preset

Формула оценки                         [Больше — лучше ▾]
┌───────────────────────────────────────────────────────────┐
│ pow(read_gain, 1 / 3) * pow(insert_gain, 1 / 3) *           │
│ pow(storage_gain, 1 / 3)                                   │
└───────────────────────────────────────────────────────────┘
[Вставить переменную] [Вставить функцию] [Проверить формулу]
Syntax/validation status, requirements, or located errors

Переменные формулы
read_gain       = source SELECT / tested SELECT   [definition]
insert_gain     = source INSERT / tested INSERT   [definition]
storage_gain    = source bytes / tested bytes     [definition]
[Добавить переменную]

▸ Справочник доступных переменных
▸ Функции и синтаксис

Жёсткие ограничения
[Рост хранения  %] [Замедление INSERT  %] [Сокращение SELECT  %]

Отмена                            Назад    Создать стратегию
```

The wireframe illustrates content order, not runtime values or evaluation results.
Do not retain four large vague priority cards as the entire scoring configuration.
Presets must load visible, inspectable formulas and their definitions.

Use ADQM SelectField, TextArea, TextField, Button, Alert, and existing table patterns.
Formula text uses a locally bundled monospace font. No remote code editor assets.
Formula field: 4–6 rows initially, full width, no spellcheck, selectable text,
horizontal scrolling within the editor for long expressions, accessible label.
At mobile widths controls wrap and all constraint fields stack vertically.

## 4. Preset selector behavior

Label: `Пресет формулы`. Options listed in section 6 plus `Своя формула`.
Selecting a preset atomically fills expression, direction, named-variable
definitions, required metrics, and immutable preset ID/version.

- Always show the resulting expression; never hide it behind an advanced switch.
- Editing expression, variable definitions, direction, or weights marks it
  `Своя формула` and retains provenance such as `На основе: Сбалансированно`.
- Preserve exact text while typing; canonicalize only at validation/save boundaries.
- Changing a preset after customization asks once whether to replace the customized
  formula. Canceling leaves all fields unchanged.
- Applying a preset does not erase independently entered hard constraints.
- `Восстановить пресет` restores its formula and variables, not unrelated fields.
- A preset requiring SELECT remains selectable before workload binding, but display
  `Для расчёта нужны измерения SELECT`. Execution admission must enforce that need.
- Do not substitute absent read measurements with neutral gain 1.

Default recommendation for a new draft: Balanced. This is a proposed policy default,
not an assertion that the existing engine already implements these weights.

## 5. Definitions used by presets

Use explicit named variables, not unexplained root shortcuts:

| Variable | Proposed canonical definition | Unit | Requirement |
| --- | --- | --- | --- |
| `read_gain` | `medians.source_select_time_ms / medians.tested_select_time_ms` | dimensionless ratio | finite, strictly positive paired SELECT medians |
| `insert_gain` | `medians.source_insert_time_ms / medians.tested_insert_time_ms` | dimensionless ratio | finite, strictly positive paired INSERT medians |
| `storage_gain` | `source_size_bytes / tested_size_bytes` | dimensionless ratio | finite, strictly positive comparable sizes |

`source` means the reference baseline measurement, `tested` means candidate.
Baseline and candidate must use the same sealed data volume, workload, parameters,
regime, measurement aggregation, and compatible storage scope. Size includes indexes
in the inspected legacy candidate context; the new metric contract must explicitly
pin which structures are counted rather than silently changing the denominator.

These ratios mean: 1 = equal, 2 = twice as good in that component, 0.5 = twice as bad.
The score is dimensionless, not a percentage or probability.
If all three gains equal 1, each weighted geometric preset produces score 1.

The proposed read definition uses aggregate medians. For multiple workload queries,
aggregate medians can hide individual regressions. Display its aggregation honestly.
Do not silently switch to per-query geometric means or p95. A future per-query
aggregation must have an explicit version and workload weighting policy.

Direct division is intentional: validate requirements before evaluating. Do not
use `safe_div(..., ..., 1)` to turn missing/zero evidence into a valid score.

## 6. Exact preset formulas

All gain presets maximize. Weights are proposed product policy and must be persisted
with a preset version. They are not scientific confidence estimates.

| Preset label | ID/version | Expression | Required variables |
| --- | --- | --- | --- |
| Сбалансированно | `balanced_geomean_v1` | `pow(read_gain, 1 / 3) * pow(insert_gain, 1 / 3) * pow(storage_gain, 1 / 3)` | all three |
| Приоритет чтения | `read_priority_v1` | `pow(read_gain, 0.6) * pow(insert_gain, 0.2) * pow(storage_gain, 0.2)` | all three |
| Приоритет вставки | `insert_priority_v1` | `pow(read_gain, 0.2) * pow(insert_gain, 0.6) * pow(storage_gain, 0.2)` | all three |
| Приоритет сжатия | `storage_priority_v1` | `pow(read_gain, 0.2) * pow(insert_gain, 0.2) * pow(storage_gain, 0.6)` | all three |
| Только чтение | `read_only_v1` | `read_gain` | read_gain |
| Только вставка | `insert_only_v1` | `insert_gain` | insert_gain |
| Только размер хранения | `storage_only_v1` | `storage_gain` | storage_gain |
| Минимальное время SELECT p95 | `select_p95_min_v1` | `pct(tested_select_time_ms_by_percentile, 95)` | tested SELECT p95; minimize |

Descriptions must distinguish priority (still considers all three) from only
(requires just that component). Do not evaluate unused preset variables; otherwise
a storage-only preset would incorrectly require SELECT measurements.

For p95 preset, output unit is ms, smaller is better, and baseline score is not
necessarily 1. Missing p95 is not substituted with p50 or zero.

Why geometric presets: ratios are multiplicative and dimensionless; weighted
geometric means make component weights explicit. This is a configurable utility
policy, not proof of statistical improvement or a substitute for feasibility gates.

## 7. Formula editor and direction

Label: `Формула оценки`. Next to it place `Направление`:

- `Больше — лучше` → `max`.
- `Меньше — лучше` → `min`.

Direction is explicit, saved, and shown for every formula. Preset selection sets it.
Changing it marks the preset customized. Do not rank every expression descending.

Use a controlled expression field. `Вставить переменную` opens a searchable ADQM
picker; picking inserts the exact path at the saved caret position and restores
focus. If no caret was captured, append to the end with safe token separation.
Do not execute expressions as browser JavaScript or Python eval.

Below the field:

- Local lint status: `Локальная проверка синтаксиса` (only what was actually checked).
- Backend validation action: `Проверить формулу`.
- Successful structural validation: `Формула корректна. Значение появится после измерений.`
- Missing runtime evidence is a separate condition, not a syntax error.
- Highlight errors by field and location where available; never claim runtime
  validity merely because names pass the frontend regular-expression linter.

No score preview with invented benchmark measurements. Optional calculator examples
must be explicitly isolated educational tools; they are not required for this page.

## 8. Named variables editor

Heading: `Переменные формулы`. Use a compact table with columns `Имя`, `Выражение`,
`Описание`, and row actions. Preset variables are visible and editable. Definitions
such as `read_gain` are user-level aliases, NOT built-in evaluator roots.

Actions: `Добавить переменную`, remove, reorder if evaluation uses declaration order.
Names follow `[A-Za-z][A-Za-z0-9_]*`, are unique, and cannot shadow a root/function
or use private/dunder names. Reject duplicate names before serialization.

Persist definitions as an ordered array or an explicit dependency DAG. Do not rely
on JSONB object-key order: the legacy editor evaluates previously declared variables
in order, which must survive database round trips. Recommend ordered array for the
first implementation; definitions may reference only roots and earlier definitions.

Removing/renaming a referenced variable must show affected references and prevent
invalid save. No automatic string replacement that edits substrings inside other
identifiers or quoted query IDs. Use syntax-aware rename or require manual correction.

## 9. Variable catalog UX

Disclosure: `Справочник доступных переменных`. Search field: `Найти переменную`.
Group variables by storage, INSERT, SELECT, per-query metrics, and advanced context.
Columns: exact path, meaning, type/unit, availability, insert action.

Mark whether an entry is a scalar, percentile lookup, list, or object. Container
roots cannot serve as a final numeric score. Include examples of numeric access.
Show availability as required measurement metadata, not a fabricated current value.

Generate the catalog from a versioned backend registry where possible. Frontend
and backend must share roots, functions, units, and availability. Never maintain an
independent hand-copied list without parity tests.

### Primary numeric paths verified in legacy context

| Path | Meaning | Unit/caution |
| --- | --- | --- |
| `source_size_bytes` | reference total size used by scorer | bytes; includes index scope in inspected path |
| `tested_size_bytes` | candidate total size used by scorer | bytes; same scope required |
| `medians.source_insert_time_ms` | median reference INSERT duration | ms |
| `medians.tested_insert_time_ms` | median candidate INSERT duration | ms |
| `medians.source_select_time_ms` | median reference SELECT duration | ms; aggregate scope |
| `medians.tested_select_time_ms` | median candidate SELECT duration | ms; aggregate scope |
| `medians.source_insert_rows_per_second` | reference INSERT throughput median | rows/s |
| `medians.tested_insert_rows_per_second` | candidate INSERT throughput median | rows/s |
| `medians.source_select_rows_per_second` | reference SELECT throughput median | rows/s; verify bucket scope |
| `medians.tested_select_rows_per_second` | candidate SELECT throughput median | rows/s; verify bucket scope |
| `medians.source_insert_bytes_per_second` | reference INSERT throughput median | bytes/s |
| `medians.tested_insert_bytes_per_second` | candidate INSERT throughput median | bytes/s |
| `medians.source_select_bytes_per_second` | reference SELECT throughput median | bytes/s |
| `medians.tested_select_bytes_per_second` | candidate SELECT throughput median | bytes/s |
| `medians.insert_time_speedup` | median of INSERT speedup values | ratio; not necessarily ratio of medians |
| `medians.select_time_speedup` | median of SELECT speedup values | ratio; not necessarily ratio of medians |
| `medians.select_time_speedup_by_query_geomean` | per-query time-speedup geometric aggregate | ratio; verify weighting/coverage |
| `medians.select_read_bytes_speedup` | effective SELECT byte reduction | ratio; legacy fallback possible |
| `ratios.insert` | INSERT ratio from ratio-details builder | dimensionless; inspect builder semantics |
| `ratios.select` | SELECT read-byte reduction | NOT time speedup |
| `ratios.compression` | size ratio from ratio-details builder | dimensionless |
| `compression_overall_coef` | legacy compression coefficient | verify numerator/storage scope before using |
| `compression.overall_coef` | alias of preceding coefficient | dimensionless |
| `speedup.compression_overall_coef` | same coefficient inside speedup container | dimensionless |

Additional median byte paths include source/tested × insert_read_bytes,
insert_written_bytes, select_read_bytes, each with `_raw` variants where constructed.
The non-raw effective fields may use legacy fallback values. Human-readable
`*_readable` entries are strings and must not be presented as numeric variables.
Also present: insert_read_bytes_speedup, insert_written_bytes_speedup,
select_read_bytes_speedup_by_query_geomean, and corresponding mode metadata.
Before exposing nested paths, extract the exact keys from `_build_score_context_medians`
and add runtime/schema tests; this table is a verified starting catalog, not a claim
that every nested path exists for every phase.

### Full legacy root-name allowlist

The following list is the complete root-name allowlist inspected in scoring.py.
Some roots are aliases or advanced containers; allowlisted does not mean populated.

```text
measured_percentiles
source
tested
speedup
compression
compression_overall_coef
ratios
medians
source_size_bytes
tested_size_bytes
per_query
source_insert_time_ms_percentiles
source_insert_time_ms_by_percentile
tested_insert_time_ms_percentiles
tested_insert_time_ms_by_percentile
insert_time_speedup_percentiles
insert_time_speedup_by_percentile
source_select_time_ms_percentiles
source_select_time_ms_by_percentile
tested_select_time_ms_percentiles
tested_select_time_ms_by_percentile
select_time_speedup_percentiles
select_time_speedup_by_percentile
select_time_speedup_by_query
tested_table_insert_metrics_json
source_table_insert_metrics_json
tested_table_select_metrics_by_query_json
source_table_select_metrics_by_query_json
tested_table_select_time_ms_percentiles_speed_up_coefs_by_query_json
tested_table_select_read_bytes_percentiles_speed_up_coefs_by_query_json
```

Interpretation:

- `measured_percentiles`: sequence of percentile labels; not an observation array.
- `*_percentiles`: numeric arrays aligned with measured_percentiles; positional
  access is fragile and should be under advanced usage.
- `*_by_percentile`: lookup accepting numeric 95, string "95", or "p95" via pct.
- `source`, `tested`: measurement containers with insert/select buckets.
- `speedup`: insert/select ratio buckets, plus compression alias.
- `per_query`: structured query contexts, including source_by_query_id,
  tested_by_query_id, and speedup_by_query_id in the inspected path.
- `select_time_speedup_by_query`: per-query speedup collection; inspect schema
  before offering a nested numeric insertion.
- Long `*_json` aliases are legacy structures, not necessarily JSON strings.
  Two INSERT JSON roots are allowlisted but not present in the inspected candidate
  expression-context construction; mark unavailable unless their producer is verified.
- SELECT JSON aliases reference query-ID maps. Query IDs come from the benchmark
  workload, so portable templates cannot assume that a particular query exists.

Example validated-access style: `pct(tested_select_time_ms_by_percentile, 95)`.
For per-query formulas, let the user select a known query ID only when workload
context exists. Otherwise record a required binding and validate at benchmark admission.

## 10. Functions and expression language

Verified legacy whitelist:

| Function | Behavior and warning |
| --- | --- |
| `safe_div(a, b, default=0.0)` | fallback on invalid/zero operands; must not mask required missing evidence |
| `at(container, key, default=None)` | map/list access with fallback |
| `pct(lookup, percentile, default=None)` | percentile lookup; accepts supported key representations |
| `coalesce(*values)` | first non-None/non-NaN/non-Inf value; not proof a value is numeric |
| `clamp(value, low, high)` | bound a numeric value |
| `median(values, default=0.0)` | ignores nonfinite/unconvertible values; fallback on empty data |
| `min`, `max` | legacy wrappers support variadic/list forms and fallbacks |
| `abs`, `round` | numeric absolute value / rounding |
| `sqrt` | square root; domain must be valid |
| `log`, `ln` | natural logarithm; input must be positive |
| `exp` | exponential; check overflow |
| `pow` | numeric power; check domain and finite result |

Operators explicitly supported include `+ - * / % **`, unary +/-, comparisons
`== != > >= < <=`, and `not`, `and`, `or`. Literal True/False/None are recognized.
Legacy evaluation has support for literal containers. Do not infer arbitrary Python
language support from these facts; the new service must enforce an AST allowlist.

Reject imports, attribute traversal into private names, arbitrary calls, lambdas,
comprehensions, generators, assignment/walrus, and unbounded work. Set limits for
expression length, AST depth/node count, variable count, literal collection sizes,
numeric magnitudes, and evaluation time. No network, filesystem, secrets, or process
environment access. Never execute formulas through eval/exec/Function.

Final result must be a finite numeric scalar; explicitly reject booleans even if
a legacy float conversion accepts True as 1. Empty/list/object/string/NaN/Inf results
are invalid. Local lint is advisory; backend validation is authoritative.

## 11. Hard constraints: exact meaning

Keep constraints below the formula and variable catalog. They are feasibility gates,
not penalties hidden inside the score. Evaluate them before ranking feasible candidates.

Let S0/Sc be baseline/candidate size, I0/Ic paired INSERT time, Q0/Qc paired SELECT time.
Require positive finite comparable measurements for each active constraint.

| Label | Value calculation | Passing condition |
| --- | --- | --- |
| Максимальный рост хранения | `100 * (Sc / S0 - 1)` | value <= entered maximum |
| Максимальное замедление INSERT | `100 * (Ic / I0 - 1)` | value <= entered maximum |
| Минимальное сокращение времени SELECT | `100 * (1 - Qc / Q0)` | value >= entered minimum |

Use the last label instead of ambiguous `ускорение`: doubling speed is 50% less
time, not 100% less time. Document the API meaning/version if retaining the old
`min_select_improvement_percent` identifier. Never change it silently for saved data.

An empty field means no constraint; 0 is an explicit constraint, not empty.
Proposed bounds: growth/slowdown maximum >= 0; required SELECT time reduction
0 <= x < 100. These are a NEW proposed contract tightening; old API only checks
finiteness. Add ADR/version and migration decisions before enforcing them on old data.
Do not silently coerce historical negative or out-of-range settings.

Missing required measurements => unevaluable/inconclusive, never passing by default.
Timeout/OOM/correctness failure => classified failure/infeasible evidence, never
a numeric score of 0, -1, or a favorable fallback.

## 12. Proposed persisted scoring document

Before implementation update the contract ADR and schema version. Do not squeeze
custom formulas into the old priority enum or silently add unvalidated JSON fields.

```json
{
  "mode": "expression",
  "preset_id": "balanced_geomean_v1",
  "preset_version": 1,
  "expression_language_version": 1,
  "metric_contract_version": 1,
  "top_selection": "max",
  "variables": [
    {"name": "read_gain", "expression": "medians.source_select_time_ms / medians.tested_select_time_ms"},
    {"name": "insert_gain", "expression": "medians.source_insert_time_ms / medians.tested_insert_time_ms"},
    {"name": "storage_gain", "expression": "source_size_bytes / tested_size_bytes"}
  ],
  "expression": "pow(read_gain, 1 / 3) * pow(insert_gain, 1 / 3) * pow(storage_gain, 1 / 3)",
  "missing_metric_policy": "inconclusive",
  "constraints": {}
}
```

This is a proposed payload, not an existing endpoint example. Required metrics must
be derived/validated server-side from expression dependencies and preset metadata;
never trust a client-provided list to omit required evidence. Persist the fully
expanded expression and immutable definitions so preset changes cannot alter history.
Custom formulas may keep originating preset provenance but must not claim an exact
preset match after edits. Empty variable definitions use an explicit empty list.

Old priority-only records must not be assigned fabricated historical formulas.
On editing, show that their exact expression was not stored, offer a visible preset
conversion, and require explicit save. Preserve existing benchmark/run snapshots.
REST acknowledgement and durable WebSocket authority remain unchanged.

## 13. Verification and implementation sequence

1. Correct the older spec/plan and ADR to remove the prohibition on expressions.
2. Define versioned metric availability/units, expression language, ordered variables,
   presets, missing-data rules, and constraints before UI wiring.
3. Add meaningful failing tests for parsing, dependency order, invalid values,
   serialization round trip, and preset semantics.
4. Implement backend validation and versioned persistence without legacy imports.
5. Build the ADQM formula editor, selector, variable definitions, searchable catalog,
   and constraints with the layout above.
6. Verify actual API create/update/bootstrap/event parity on disposable infrastructure.
7. Browser-test editing, preset switching, insertion at caret, errors, keyboard,
   narrow screens, dark/light, save/reopen, and reconnect behavior.

Deterministic unit examples (test inputs only, never runtime fixtures):

- All gains 1 => every geometric preset score 1.
- Gains read=2, insert=1, storage=1 => Balanced `pow(2, 1/3)`;
  Read priority `pow(2, 0.6)`; Insert/Storage priority `pow(2, 0.2)`.
- Storage-only works with valid sizes and no SELECT/INSERT metrics.
- Balanced with missing read metric is inconclusive, never neutral gain 1.
- p95 missing but p50 present does not silently score p50.
- Candidate size 120 vs 100 => growth 20%; exact boundary passes a 20% maximum.
- Candidate SELECT 50ms vs 100ms => reduction 50%.
- Division by zero, negative geometric inputs, overflow, object/bool result fail.
- Reordering dependent variable definitions cannot silently change meaning.
- Unknown/private names and injection-like expressions are rejected safely.
- An expression using `ratios.select` is labeled read-byte semantics, not latency.
- Preset IDs, formula, direction, and variable order survive database round trip.
- Old benchmark snapshots remain unchanged after template edit.

Run repository frontend checks, relevant Python 3.12 tests, documentation link and
whitespace checks, and git diff --check. Report what was actually executed.
Do not deploy or claim a working optimizer merely because formula editing works.

## 14. Definition of done

The user can see the exact formula, choose a documented preset, customize it,
inspect and insert supported variables/functions, understand units and missing-data
requirements, validate it, and save/reopen the same formula and variable definitions.
The displayed direction and constraints match ranking semantics. Unsupported or
missing evidence is explicit. Formula changes do not rewrite historical snapshots.
