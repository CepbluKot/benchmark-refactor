# AI execution workflow

## Purpose

Let the root Codex agent route work inside one user task. The user states the
goal once; the agent classifies the work, delegates only when useful, integrates
the result, and reports back. Keep a compact, verified execution state instead
of passing a growing transcript to subagents. This convention does not replace
the repository's architecture, security, testing, or authorization rules.

## Model routing

- The root agent runs on **Terra Medium** and owns triage, integration,
  implementation, verification, and the final answer.
- Delegate to **Luna Low** only for a sufficiently substantial, independent,
  mechanical subtask with named files, an expected result, known verification,
  and no design decision. The root does tiny edits itself; a spawn has overhead.
- Delegate to **Sol Medium** for read-only planning when work needs a material
  architecture or public-contract decision, changes a security boundary, needs
  a migration or deployment strategy, or remains unclear after focused initial
  investigation.
- Set both model and reasoning effort explicitly on every spawn: Luna Low,
  Terra Medium, or Sol Medium. Never use Astra, Sol High, or any model/reasoning
  combination above the user's Sol Medium ceiling.

## Triage and routing

At the start of each user request, the Terra root checks the concrete risk
signals above and chooses an execution path without asking the user to select
a model. File count alone does not require Sol. Ordinary or uncertain work
stays with Terra after focused investigation. The root does not create a Luna
subagent merely to classify work or delegate work so small that coordination
costs more than execution.

When a listed risk requires stronger planning, the root spawns one Sol Medium
subagent with a read-only, bounded question and waits for its Implementation
Brief. The root validates that Brief against current code and instructions,
resolves any required user decision, then implements and verifies on Terra.
If the brief is incomplete or contradicts evidence, send a focused follow-up
to the same planner with fresh evidence; do not silently guess. Additional
review subagents required by this repository's development practices remain
read-only and are chosen at the lowest adequate tier.

An instruction file cannot change the root model mid-task. Automatic routing
here means scoped subagent delegation within the current task, not a hidden
switch of the running model or creation of a separate user-owned task. If
subagents are unavailable, the root continues on Terra within its competence
and discloses any unperformed Sol review; it does not claim that escalation
occurred.

## Handoff artifacts

The Sol planning subagent returns an **Implementation Brief** to the Terra
root. The root keeps the current **Execution State** and passes only the
relevant compact facts and evidence to any subagent, not the full transcript.

Keep both artifacts concise. They must not contain credentials, raw connection
URLs, sensitive literals, full unredacted logs, or speculative history. Facts in
the state require a source: an inspected file, a command result, a test result,
or an explicit user decision.

### Implementation Brief

Use this structure:

```text
Goal:
Non-goals:
Accepted decisions and constraints:
Steps: each step names affected paths, contract changes, and success criteria.
Verification: commands or checks required for each relevant step.
Risks and escalation conditions:
```

The planner is read-only. It must inspect the applicable repository instructions
and existing behavior before issuing the Brief. Only the root authorizes an
implementation within the user's original task scope.

### Execution State

Use this structure and replace obsolete entries instead of appending a diary:

```text
Goal:
Phase: implementation | verification | blocked | complete
Accepted decisions:
Completed, with evidence:
Next concrete action:
Affected paths:
Verification: command/check -> current result
Blocker or decision needed:
```

The root reads the relevant source again; the state is a compact handoff, not
a substitute for current repository evidence. Update facts after
a verified environment outcome and decisions after an explicit user decision.
A failed command remains represented as a short, actionable fact until resolved;
do not carry the entire old output forward.

## Task flow

1. The Terra root inspects the applicable instructions, intended `HEAD`,
   worktree, and uncommitted changes, then classifies the request.
2. For ordinary work, the root implements and verifies directly. For a sizable
   independent mechanical slice, it may delegate that slice to Luna Low; no
   overlapping edits, and the root reviews and verifies the result.
3. For the listed material risks, the root delegates read-only planning to Sol
   Medium, waits for the Brief, then implements and verifies in the same task.
   It retains ownership of all edits, contracts, authorization, and outcome.
4. On a contradiction with live code, unclear verification failure, or new
   material design decision, the root sends fresh evidence and compact state
   to the planner. It does not repeatedly retry or widen scope without a
   decision. Ask the user only when a material choice or new authority is
   genuinely needed, never to route models or copy a Brief.
5. Subagents share the root task's working context only as supported by the
   current runtime; each must verify the actual checkout before editing or
   reviewing. For independent write-heavy work, isolate worktrees when needed.
   Do not commit merely to transfer state. A new user-owned task and Codex
   Handoff are optional manual workflows, not required steps in this routing.

## Calibration

After several representative tasks, compare which subagents were used, total
usage if available, elapsed time, accepted result, and rework. Adjust routing
only from observed outcomes; spawning more agents can cost more, and savings
are not guaranteed.

## Completion

The final task report names changed files, checks actually run and their result,
checks not run, and remaining risks. The project-specific definition of done and
authorization rules remain authoritative.
