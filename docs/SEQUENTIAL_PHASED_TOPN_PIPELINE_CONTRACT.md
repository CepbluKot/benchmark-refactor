# Sequential Phased Top-N: Runtime Contract

This document describes the **implemented** pipeline for
`sequential_phased_topn_strategy`.

## Stage Flow

Runtime stages are:

1. `order_by`
2. `types` (one-column, independent)
3. `codecs` (one-column, independent; over top type options)
4. `index_granularity` (full-table candidates)
5. `indexes` (one-column, independent; fixed table granularity)
6. `final_validation` (merged schema + local search)

`source_baseline` is stored separately as phase `0`.

## Phase Numbering in Storage

`benchmark_results__phased.phase`:

- `0` -> `source_baseline`
- `1` -> `order_by`
- `2` -> `types`
- `3` -> `codecs`
- `4` -> `index_granularity`
- `5` -> `indexes`
- `6` -> `final_validation`

## Core Behavior by Stage

### 1) ORDER BY

- Tests full-table ORDER BY candidates.
- Keeps top-N ORDER BY branches (`sequential_top_n_limits.order_by` or fallback).

### 2) TYPES (independent per column)

For each ORDER BY branch:

- each column is tested independently;
- top-N type options are kept **per column**.

No full-table merge is done at this stage.

### 3) CODECS (independent per column)

For each ORDER BY branch:

- for each column and for each kept type option, codec variants are tested;
- top-N `(type, codec)` options are kept **per column**.

No full-table merge is done at this stage.

### 3.5) INDEX_GRANULARITY (full-table)

For each ORDER BY branch:

- per-column codec options are merged into temporary whole-table candidates;
- table `SETTINGS index_granularity` is benchmarked on these full-table candidates;
- top-N full-table candidates are kept for next stage.

### 4) INDEXES (independent per column, fixed table granularity)

For each winner from `index_granularity` stage:

- only columns present in query `WHERE` filters are considered;
- index options are benchmarked per column independently;
- stage uses query subset where the tested column is present in `WHERE`;
- top-N index options are kept **per column**;
- if no profitable/valid option remains, fallback is “no index” for that column.

### 5) FINAL VALIDATION + local search

For each `index_granularity` parent:

- merge top-1 index option per column into one full schema;
- run full benchmark (`final_validation`);
- optional post-merge local search:
  - replace one column choice with top-2/top-3/... and re-run,
  - controlled by `sequential_top_n_limits.local_search`.

Final winner is top by score in `final_validation`.

## `variant_params` Fields (actual runtime)

Current runtime writes these keys for phased rows:

- `mode`
- `global_index`
- `execution_uuid`
- `parent_variant_table`
- `phase_name`
- `stage_column_name`
- `merged_columns`
- `table_index_granularity`
- `column_choices`
- `index_choices`

Notes:

- `stage_column_name` is set for one-column stages (`types`, `codecs`, `indexes`).
- `merged_columns` is set for merged whole-table stages (`index_granularity`, `final_validation`).

## Top-N Controls

### Stage top-N

`sequential_top_n_limits` keys:

- `order_by`
- `types`
- `codecs`
- `index_granularity`
- `indexes`
- `final_validation`
- `local_search`
- `sequential` (fallback)

### Per-column top-N

By default, per-column top-N in one-column stages follows stage top-N.

If `max_winners_per_parent_limits` is set for a stage, it overrides per-column limit:

- `types`
- `codecs`
- `indexes`
- `sequential` (fallback)

## Generation Caps

`max_benchmarks_limits` can cap generated jobs per stage:

- `order_by`, `types`, `codecs`, `index_granularity`, `indexes`, `final_validation`, `sequential`.

## Ranking in Result Store

Store computes and updates:

- stage-level ranking: `rank_in_phase`, `is_top_n`;
- one-column ranking: `rank_in_stage_column`, `is_top_n_in_stage_column`.

The strategy also explicitly marks winners with `is_top_n` after each stage.
