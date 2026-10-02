# AGENTS.md

## Project status

**Spec-only / greenfield.** There is no source code, build, or test tooling yet — only `docs/requirement_v1.md` and an empty git history. Do not invent build/lint/test commands; there are none. When adding code, also add the tooling for it.

## Authoritative spec

`docs/requirement_v1.md` (written in Chinese) is the implementation basis and the source of truth. Read it before making architectural decisions. Its DB schema, WS message types, task-status enum, and flows are the contract — reuse those exact names rather than inventing variants.

## Stack

- **Python** (team-confirmed; the spec left it open).
- **SQLite** for storage.
- Communication: WS long connection to the platform + an A2A client for dispatching to other agents.
- Scheduling: plain DAG topological sort — the spec explicitly says no heavy orchestration framework.
- LLM provider must be configurable (local or remote).

## Architecture invariants (easy to get wrong)

This project is a **local autonomous planner** that plugs into the external `agent-swarm` platform as a special agent:

- **Task truth lives locally** in SQLite. The platform stores no task state; it is only a human I/O + display surface.
- **Works offline**: if the platform is down, the planner still runs; only A2A and notifications degrade.
- **Idempotency is mandatory**: every platform→planner operation carries an `op_id`; dedupe through the `operations` table so WS reconnects cannot re-create goals or duplicate work.
- Replanning, decomposition, and scheduling are planner-local. Changing strategy/model must not require platform changes.

## Conventions from the spec

- Task status values: `pending / ready / running / done / failed / blocked / waiting_human`.
- Acceptance types: `auto` (tests/lint/build/logs) and `manual` (hardware, human confirms).
- WS message names are fixed (e.g. `goal.create`, `plan.snapshot`, `task.need_acceptance`); see spec §9 before adding any new message.

## Repository layout

- `docs/` — requirements/design docs. Add new design docs here.
- Working directory is `agent_swarm_planner`; the project is named `agent-swarm-planner`. Keep naming consistent within code you add.
