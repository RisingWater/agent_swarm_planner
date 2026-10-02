# AGENTS.md

## What this is

Local autonomous **goal → task-tree planner** that drives other agents through the
external `agent_swarm` platform. It runs as a special workspace on the platform.

Design rule that overrides everything else: **determinism lives in this repo's Python;
reasoning lives in an agent.** The Python service must NOT call any LLM / vendor SDK.
Goal decomposition and replanning are done by whichever agent the user runs in the
planner workspace (opencode / claude / deepseek / …).

## Commands

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest pytest-asyncio   # dev
.\.venv\Scripts\python.exe -m pytest -q                           # tests (asyncio_mode=auto)
.\.venv\Scripts\python.exe -m planner_core info                   # resolved config (key masked)
.\.venv\Scripts\python.exe -m planner_core init                   # create SQLite
```

On Windows/PowerShell, Chinese output/args get mojibake unless you set
`chcp 65001` + `[Console]::OutputEncoding=[Text.Encoding]::UTF8` + `$env:PYTHONUTF8=1`.
PowerShell 5.1 has no `&&`; use separate statements.

## Planner agent playbook (CLI — no MCP needed)

When planner-core injects you a planning prompt, you are the **planner agent**. All state
lives in SQLite; drive it with the CLI (`planner <sub>`; or `.venv\Scripts\python.exe -m planner_core <sub>`):

1. **Compress context first** (the injected step 0) — always.
2. Read state: `planner plan export <goal_id>` (machine-readable) / `planner plan show <goal_id>`.
3. Decompose: write a JSON plan, then `planner plan apply <goal_id> --file plan.json`.
   Format: `{"tasks":[{"temp_id","title","depends_on":[],"assigned_agent","acceptance_type","execution_spec"}]}`
   (`temp_id` references may be out of order; the DAG is validated). This sets `plan_status=draft`.
4. Approval gate: while `plan_status=draft`, only output the task tree for human approval (the
   platform page has "通过拆解"); do NOT dispatch. After approval, dispatch ready tasks:
   `planner dispatch <target_wid> "任务内容" --task-id <task_id>` — auto-prepends
   `PLANNER_DISPATCH_PREAMBLE` ("compress context first") and links the worker task back to the
   local task (worker terminal state is written back by `planner serve`).
5. Failures/blocks: `planner plan recover <goal_id>`.
6. Human acceptance: tasks in `waiting_human` (or `acceptance_type=manual`) need a human
   decision — ask via your native question/permission (the platform surfaces it as
   `input-required`); on approval `planner task set <id> done`, on reject `... failed`.
7. Finish: `planner plan markdown <goal_id>` and use that output as your reply — the platform
   "Planner" page renders it as the task tree.

## Config resolution (in order)

`planner_core/config.py`: process env → project `.env` → `~/.config/opencode/agent-swarm.json`
(`serverUrl`/`apiKey`) → `.agent_swarm/workspace.md` `WORKSPACE_ID:` line. The workspace is
already registered (`XVgn9ogswmCbzrwzFPJheF`); reuse it, don't re-register blindly.

## Architecture facts an agent will otherwise get wrong

- **Two processes**: `planner-core` (this repo, deterministic: SQLite/DAG/scheduling/
  acceptance/prompt injection) and the **planner agent** (any agent the user runs —
  opencode/claude/deepseek — which does the thinking and dispatches workers).
- **Self-injection is the intended mechanism.** The MCP tool `a2a_call` refuses
  `target == from_workspace`, but the raw gateway `POST /a2a/{wid}` (apikey auth) does
  NOT. That's how the non-agent Python service sends prompts to its own workspace.
  Don't "fix" it by adding a separate caller workspace.
- The planner workspace must be **dispatchable** (fresh heartbeat / TUI open, or
  `execution_mode="background"`), else the gateway returns 409.
- Platform contract details live in the `agent_swarm` repo at
  `D:\wangxu\work\agent_swarm` (`server/nexus_a2a.py` `/ws/plugin`, `/ws/nexus`;
  `docs/desktop-client-nexus-integration.md`). Read it before touching protocol code.
  Platform changes (e.g. a planner flag / goal UI) belong to THAT repo — hand tasks to
  its workspace, and respect its `dev`-branch convention.

## Repo layout

- `planner_core/` — Python core. `engine/dag.py` + `engine/prompt.py` are pure and unit-tested.
- `planner_core/platform/a2a_client.py` — `POST /a2a/{wid}` `message/send` / `message/stream`.
- `planner_core/platform/observer.py` — `/ws/nexus` subscription.
- `planner_core/platform/mcp_client.py` — minimal stateless `/mcp/` client (`tools/call`
  works without `initialize`); backs `planner_dispatch`, which mechanically prepends
  `PLANNER_DISPATCH_PREAMBLE` ("compress context first") to every worker dispatch.
- `planner_core/service/daemon.py` — `planner serve`: observer + tick (refresh ready, throttled nudge).
- `planner_core/engine/acceptance.py` — runs `execution_spec.accept_command`.
- `tests/` — pytest. `data/` and `.env` are gitignored.
- `docs/requirement_v1.md` — original spec (Chinese); use its exact DB columns, task-status
  enum (`pending/ready/running/done/failed/blocked/waiting_human`), and message concepts.

## Conventions

- Comments/docstrings and handoff notes in Chinese, matching `docs/`.
- Timestamps are UTC everywhere.
- SQLite: short-lived connections, never hold one across an `await` (platform froze its
  event loop this way once).
- `plan apply` accepts out-of-order `temp_id` references (two-pass), then validates the DAG.
