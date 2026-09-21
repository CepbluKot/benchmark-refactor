# ADR-0004: Independent strategy dimensions and search procedure

## Status

Accepted for the current Benchmark Studio configuration surface, following the
user-approved separation of independently editable rules from search procedure.

## Decision

Schema version 2 stores `procedure` (`combined`, `sequential`, or `phased`) separately
from `dimensions`: column type rules, codec rules, skip-index rules, ORDER BY rules,
column positions, and table granularity alternatives. Empty collections explicitly
mean that no alternatives of that dimension are configured. No rule bank is inferred.
Budgets and scoring retain their current typed contracts. The four-step wizard is
Basics, Search Configuration, Budget, Scoring; the second step contains both sections.

Existing schema-v1 records and benchmark snapshots remain unchanged. Reading supports
both stored versions; new/updated templates use v2. Editing v1 opens an explicitly
incomplete v2 draft: old booleans contain no recoverable alternatives. Users must
configure at least one real dimension before saving; no synthetic rules are invented.
This is a document-version migration on explicit save, with no physical SQL schema
change. Bootstrap and durable events preserve the stored configuration version.

The catalog `strategy` and `phases` are derived projections. V2 phases are derived
from configured dimensions and procedure. Existing benchmark snapshots are never
rewritten when their source template is edited. The Control API validates all rules.

## Execution boundary

The current local run endpoint copies a table and does not consume strategy
configuration. This change enables editing, validation, persistence, and copying
configuration only. It does not implement an optimizer or connect the legacy engine,
and does not claim production support for executing these procedures.
