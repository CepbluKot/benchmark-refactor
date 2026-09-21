# Benchmark UI Demo Implementation Plan

**Goal:** Extend the existing configuration editor with the approved four-page demo using the local ADQM design system.

**Architecture:** Keep the existing parser, serializer, validation, and benchmark section editors. Add an application shell and local demo state for sources, runs, and rule banks. Do not add backend integration or change the target Python runtime.

**Tech Stack:** React 18, TypeScript, Vite, local `@adqm/gpb-ui` package.

## Global Constraints

- Use actual benchmark vocabulary and configuration fields from the repository.
- Mark simulated connection checks and run results as demo data.
- Keep source passwords only in the open form and never in browser storage.
- Package all styles, fonts, and dependencies locally for offline use.
- Preserve existing benchmark JSON round-trip behavior.
- Do not commit, deploy, or change a source database.

## Tasks

- [x] Vendor the local ADQM library and its fonts for offline builds.
- [x] Add focused checks for source validation and immutable run snapshots.
- [x] Add navigation for data sources, benchmarks, runs, and rule banks.
- [x] Reuse the existing benchmark editor inside the new application shell.
- [x] Implement local CRUD for sources and rule banks.
- [x] Implement clearly labelled demo run, cancellation, candidates, comparison, and diagnostics views.
- [x] Update documentation and Docker build inputs.
- [x] Run typecheck, focused checks, round-trip checks, production build, and browser smoke checks.
