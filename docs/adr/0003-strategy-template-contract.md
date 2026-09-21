# ADR-0003: Versioned strategy-template configuration

## Status

Accepted for the current Benchmark Studio product surface.

## Context

The original strategy record stored only a display name, a method string, and a
caller-authored phase list. That shape cannot represent reusable search rules,
budgets, or scoring preferences and lets clients submit phases that disagree with
the selected method.

## Decision

Store a schema-versioned JSON strategy configuration in PostgreSQL. The Control API
validates the complete document, derives phases from the selected method, and emits
one canonical strategy shape through bootstrap and durable events. The readable
method and derived phases remain relational projections for catalog queries.

A benchmark stores a copy of the selected configuration when it is saved. Updating
the global template affects future benchmark saves only and never mutates existing
benchmark snapshots.

The first schema version contains portable rule switches, bounded positive-integer
search budgets, a named scoring priority, and optional finite percentage constraints.
Workload queries remain benchmark-owned.

## Consequences

- Clients cannot author phases or submit fields unsupported by the selected method.
- New configuration shapes require an explicit schema-version change and migration.
- Existing strategy rows are backfilled with conservative defaults.
- Strategy and benchmark events carry the same canonical documents returned by
  bootstrap.
