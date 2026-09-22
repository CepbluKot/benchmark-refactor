# ADR-0005: Read-only strategy-options catalogue

## Status

Accepted for the current Benchmark Studio configuration surface.

## Decision

The strategy editor retrieves generic, read-only suggestions through
`POST /api/v1/strategy-options/suggest`. The endpoint accepts only bounded typed
input: a v2 kind, matcher type, free-text query, already-selected canonical values,
and a requested locale. It returns a locally packaged, versioned declarative
catalogue response with canonical expressions, explanation, applicability state,
and optional parameter descriptors.

Suggestions assist editing only. Selecting a suggestion or manual entry changes a
client draft; the authoritative v2 strategy validation runs again when the strategy
is created or updated. Suggestions do not create database records, emit WebSocket
events, modify a source, or execute SQL.

The initial scope is a generic global template. It does not accept source IDs,
tables, connection data, or physical locators. Source-specific capability filtering
requires a separate ADR and an opaque server-approved SourceModel reference.

The current Control API owns transport validation and a pinned, local descriptor for
this UI surface. It does not import legacy candidate generators or executable plugin
code. The eventual target runtime keeps backend compatibility/canonicalization with
the database plugin behind its approved boundary.

## Consequences

- A catalogue result labelled `supported` means descriptor compatibility only, never
  a performance guarantee, data-conversion guarantee, or successful benchmark run.
- All results have stable IDs and a catalogue revision; the browser removes entries
  already selected in the same rule and ignores responses for stale requests.
- The v2 template document remains the only persisted strategy format for new or
  edited strategies. Picker state, row IDs, search terms and results are not saved.
- The endpoint has explicit payload and result bounds and does not rely on public
  networks or a third-party autocomplete service.
