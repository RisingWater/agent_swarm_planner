"""PlannerService：确定性编排。

职责：目标/任务 CRUD、DAG 就绪计算、组装并（可选）投递提示词给 planner agent。
不调用任何 LLM。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from ..config import Settings
from ..db import init_db
from ..engine import dag
from ..engine.prompt import build_prompt
from ..models import Goal, Task
from ..platform.a2a_client import A2AClient
from ..store import Store


def _read_workspace_md(root) -> dict[str, str]:
    from pathlib import Path

    f = Path(root) / ".agent_swarm" / "workspace.md"
    out: dict[str, str] = {}
    if f.is_file():
        for raw in f.read_text(encoding="utf-8").splitlines():
            if ":" in raw:
                k, _, v = raw.partition(":")
                out[k.strip().upper()] = v.strip()
    return out


def _write_workspace_md(root, workspace_id: str, purpose: str, capabilities: str, role: str = "") -> None:
    from pathlib import Path

    f = Path(root) / ".agent_swarm" / "workspace.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    cur = _read_workspace_md(root)
    cur["WORKSPACE_ID"] = workspace_id
    if purpose:
        cur["PURPOSE"] = purpose
    if capabilities:
        cur["CAPABILITIES"] = capabilities
    if role:
        cur["ROLE"] = role
    order = ["WORKSPACE_ID", "ROLE", "PURPOSE", "CAPABILITIES"]
    lines = [f"{k}: {cur[k]}" for k in order if k in cur]
    lines += [f"{k}: {v}" for k, v in cur.items() if k not in order]
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")


class PlannerService:
    def __init__(self, settings: Settings, store: Store | None = None):
        self.settings = settings
        self.store = store or Store(settings.db_path)
        self._last_nudge: dict[str, float] = {}

    # ---------------------------------------------------------------- setup
    def init(self) -> None:
        init_db(self.settings.db_path)

    # ---------------------------------------------------------------- goals
    def create_goal(
        self,
        title: str,
        description: str = "",
        priority: int = 0,
        deadline: str = "",
        success_criteria: str = "",
        expert_workspace_id: str = "",
        expert_name: str = "",
    ) -> Goal:
        return self.store.add_goal(title, description, priority, deadline, success_criteria,
                                   expert_workspace_id, expert_name)

    def list_goals(self) -> list[Goal]:
        return self.store.list_goals()

    # ---------------------------------------------------------------- tasks
    def add_task(self, **kwargs: Any) -> Task:
        task = self.store.add_task(**kwargs)
        # 新任务必须满足 DAG 约束
        dag.validate(self.store.list_tasks(task.goal_id))
        return task

    def refresh_ready(self, goal_id: str) -> list[str]:
        return self.store.refresh_ready(goal_id)

    def validate_goal(self, goal_id: str) -> None:
        dag.validate(self.store.list_tasks(goal_id))

    # ---------------------------------------------------------------- 计划
    def apply_plan(self, goal_id: str, plan: dict[str, Any], replace: bool = False) -> list[Task]:
        """把 agent/专家拆解出的 JSON 计划写入任务树。

        计划格式：
        {"tasks": [{"temp_id","title","description","depends_on":[temp_id],
                    "assigned_agent","acceptance_type","execution_spec"}]}
        两趟写入以支持任意顺序的依赖引用；最后统一校验 DAG。
        replace=True 时先删除该目标现有任务（专家调整计划用）。
        """
        if self.store.get_goal(goal_id) is None:
            raise KeyError(f"目标不存在: {goal_id}")
        if replace:
            self.store.delete_tasks(goal_id)
        specs = plan.get("tasks") or []
        temp_to_real: dict[str, str] = {}
        created: list[Task] = []
        # 第一趟：建任务
        for spec in specs:
            title = str(spec.get("title") or "").strip()
            if not title:
                raise ValueError("计划中存在没有 title 的任务")
            task = self.store.add_task(
                goal_id=goal_id,
                title=title,
                description=str(spec.get("description") or ""),
                assigned_agent=str(spec.get("assigned_agent") or spec.get("agent") or ""),
                acceptance_type=str(spec.get("acceptance_type") or "auto"),
                execution_spec=spec.get("execution_spec") or {},
                parent_id=str(spec.get("parent_id") or ""),
            )
            temp = str(spec.get("temp_id") or spec.get("id") or task.id)
            temp_to_real[temp] = task.id
            created.append(task)
        # 第二趟：连依赖
        for spec in specs:
            temp = str(spec.get("temp_id") or spec.get("id") or "")
            task_id = temp_to_real.get(temp)
            if not task_id:
                continue
            for dep in spec.get("depends_on") or []:
                dep_id = temp_to_real.get(str(dep), str(dep))
                self.store.add_dependency(task_id, dep_id)
        self.validate_goal(goal_id)
        self.store.set_goal_plan_status(goal_id, "draft")
        return created

    def export_goal(self, goal_id: str) -> dict[str, Any]:
        goal = self.store.get_goal(goal_id)
        if goal is None:
            raise KeyError(f"目标不存在: {goal_id}")
        tasks = self.store.list_tasks(goal_id)
        return {
            "goal": goal.__dict__,
            "tasks": [t.__dict__ for t in tasks],
            "ready": [t.id for t in tasks if t.status == "ready"],
        }

    def _goal_dict(self, goal: Goal, tasks: list[Task]) -> dict[str, Any]:
        d = goal.__dict__.copy()
        d["progress"] = {"done": sum(1 for t in tasks if t.status == "done"), "total": len(tasks)}
        return d

    def _task_dict(self, task: Task) -> dict[str, Any]:
        d = task.__dict__.copy()
        d["suggested_agent"] = task.assigned_agent  # 平台弹窗用该键名
        return d

    def state(self, goal_id: str | None = None) -> dict[str, Any]:
        """供平台/agent 读取的完整状态快照（字段名与协议文档 §3 对齐）。"""
        if goal_id:
            goal = self.store.get_goal(goal_id)
            if goal is None:
                raise KeyError(f"目标不存在: {goal_id}")
            tasks = self.store.list_tasks(goal_id)
            return {"goals": [self._goal_dict(goal, tasks)], "tasks": [self._task_dict(t) for t in tasks]}
        goals = self.list_goals()
        out_goals: list[dict[str, Any]] = []
        out_tasks: list[dict[str, Any]] = []
        for g in goals:
            ts = self.store.list_tasks(g.id)
            out_goals.append(self._goal_dict(g, ts))
            out_tasks.extend(self._task_dict(t) for t in ts)
        return {"goals": out_goals, "tasks": out_tasks}

    def next_ready(self, goal_id: str) -> list[dict[str, Any]]:
        """提升就绪并返回当前可派发任务的摘要。"""
        self.refresh_ready(goal_id)
        return [
            {"id": t.id, "title": t.title, "assigned_agent": t.assigned_agent,
             "acceptance_type": t.acceptance_type}
            for t in self.store.list_tasks(goal_id)
            if t.status == "ready"
        ]

    def record_execution(
        self,
        task_id: str,
        agent: str = "",
        output: str = "",
        anchor: str = "",
        status: str = "done",
    ) -> dict[str, Any]:
        if self.store.get_task(task_id) is None:
            raise KeyError(f"任务不存在: {task_id}")
        eid = self.store.add_execution(task_id, agent=agent, output=output, anchor=anchor, status=status)
        self.store.set_task_status(task_id, status)
        return {"execution_id": eid, "task_id": task_id, "status": status}

    def apply_acceptance(self, task_id: str) -> dict[str, Any]:
        """worker 任务终态（成功）后按验收策略落状态。

        - `acceptance_type=manual` → `waiting_human`（等人在平台确认）
        - `acceptance_type=auto` 且配了 `accept_command` → 跑命令，done/failed
        - 否则直接 `done`
        """
        from ..engine import acceptance

        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(f"任务不存在: {task_id}")
        if task.status == "done":
            return {"task_id": task_id, "status": "done", "reason": "already done"}
        if task.acceptance_type == "manual":
            self.store.set_task_status(task_id, "waiting_human")
            return {"task_id": task_id, "status": "waiting_human", "reason": "manual acceptance"}
        if task.acceptance_type == "expert":
            self.store.set_task_status(task_id, "waiting_expert")
            return {"task_id": task_id, "status": "waiting_expert", "reason": "expert acceptance"}
        spec = acceptance.acceptance_spec(task)
        if spec.get("accept_command") or spec.get("command"):
            return self.run_acceptance(task_id)
        self.store.add_execution(task_id, agent="worker", anchor="auto-accept (no command)", status="done")
        self.store.set_task_status(task_id, "done")
        return {"task_id": task_id, "status": "done", "reason": "auto (no command)"}

    def run_acceptance(self, task_id: str) -> dict[str, Any]:
        """执行任务配置的自动验收命令，回写状态 + execution。"""
        from ..engine import acceptance

        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(f"任务不存在: {task_id}")
        result = acceptance.run_acceptance(task, default_cwd=str(self.settings.root))
        self.store.set_task_status(task_id, result.status, acceptance_result=result.output[:8000])
        self.store.add_execution(
            task_id, agent="planner-core", output=result.output, anchor=result.output[:2000],
            status=result.status,
        )
        return {
            "task_id": task_id,
            "ok": result.ok,
            "status": result.status,
            "duration": round(result.duration, 3),
            "output": result.output[-4000:],
        }

    # ---------------------------------------------------------------- 恢复
    def recover(self, goal_id: str) -> list[dict[str, str]]:
        """失败任务重试策略：未超上限 → 回 pending；超限 → blocked（触发重规划/人工）。

        返回本轮变更列表 [{"task_id","action"}]。幂等：只在 failed 上动作。
        """
        actions: list[dict[str, str]] = []
        for t in self.store.list_tasks(goal_id):
            if t.status != "failed":
                continue
            if t.retry_count < self.settings.max_retry:
                self.store.inc_retry(t.id)
                self.store.set_task_status(t.id, "pending")
                actions.append({"task_id": t.id, "action": "retry"})
            else:
                self.store.set_task_status(t.id, "blocked")
                actions.append({"task_id": t.id, "action": "blocked"})
        if actions:
            self.refresh_ready(goal_id)
        return actions

    # ---------------------------------------------------------------- 平台操作
    async def handle_op(self, op: str, payload: dict[str, Any] | None = None, op_id: str = "") -> dict[str, Any]:
        """处理平台经 WS 下发的操作。op_id 非空时幂等（结果存 operations 表）。"""
        payload = payload or {}
        if op_id:
            row = self.store.get_operation(op_id)
            if row is not None:
                try:
                    return json.loads(row["payload"] or "{}")
                except ValueError:
                    return {"ok": True, "duplicate": True}
        result = await self._do_op(op, payload)
        if op_id:
            self.store.record_operation(op_id, op, result)
        return result

    async def _do_op(self, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        if op == "goal.create":
            goal = self.create_goal(
                title=str(payload.get("title") or "").strip(),
                description=str(payload.get("description") or ""),
                priority=int(payload.get("priority") or 0),
                deadline=str(payload.get("deadline") or ""),
                success_criteria=str(payload.get("success_criteria") or ""),
                expert_workspace_id=str(payload.get("expert_workspace_id") or ""),
                expert_name=str(payload.get("expert_name") or ""),
            )
            return {"ok": True, "goal_id": goal.id}
        if op == "goal.update":
            gid = str(payload.get("goal_id") or "")
            if self.store.get_goal(gid) is None:
                return {"ok": False, "error": f"目标不存在: {gid}"}
            self.store.update_goal(gid, **{k: payload.get(k) for k in
                                           ("title", "description", "priority", "deadline",
                                            "success_criteria", "criteria_confirmed",
                                            "expert_workspace_id", "expert_name")})
            return {"ok": True}
        if op == "goal.archive":
            self.store.set_goal_status(str(payload.get("goal_id") or ""), "archived")
            return {"ok": True}
        if op == "goal.activate":
            gid = str(payload.get("goal_id") or "")
            if self.store.get_goal(gid) is None:
                return {"ok": False, "error": f"目标不存在: {gid}"}
            self.store.set_goal_status(gid, "active")
            return {"ok": True}
        if op == "goal.delete":
            return self.delete_goal(str(payload.get("goal_id") or ""))
        if op in ("plan.approve", "plan.revise", "goal.nudge"):
            gid = str(payload.get("goal_id") or "")
            if self.store.get_goal(gid) is None:
                return {"ok": False, "error": f"目标不存在: {gid}"}
            if op == "plan.approve":
                self.store.set_goal_plan_status(gid, "approved")
            elif op == "plan.revise":
                self.store.set_goal_plan_status(gid, "draft")
            self._schedule_nudge(gid)
            return {"ok": True, "nudged": True}
        if op in ("task.accept", "task.reject"):
            tid = str(payload.get("task_id") or "")
            task = self.store.get_task(tid)
            if task is None:
                return {"ok": False, "error": f"任务不存在: {tid}"}
            if task.status not in ("waiting_human", "waiting_expert"):
                # 只接受“待人/待专家验收”的任务，避免误点；终态视为幂等成功
                if task.status in ("done", "failed", "blocked"):
                    return {"ok": True, "note": f"任务已是终态 {task.status}"}
                return {"ok": False, "error": f"任务不在待验收状态（当前 {task.status}）"}
            if op == "task.accept":
                self.store.set_task_status(tid, "done", acceptance_result=str(payload.get("result") or "人工验收通过"))
            else:
                self.store.set_task_status(tid, "failed", acceptance_result=str(payload.get("reason") or "人工验收拒绝"))
            return {"ok": True}
        if op == "state.get":
            return {"ok": True, "state": self.state()}
        return {"ok": False, "error": f"未知操作: {op}"}

    def _schedule_nudge(self, goal_id: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.nudge(goal_id, send=True, force=True))

    # ---------------------------------------------------------------- 注册
    def register(self, role: str = "planner", purpose: str = "", capabilities: str = "") -> dict[str, Any]:
        """用 MCP `workspace_add` 把本目录注册/标记为 planner 工作区，并写 workspace.md。"""
        from ..platform.mcp_client import MCPClient

        s = self.settings
        md = _read_workspace_md(s.root)
        purpose = purpose or md.get("PURPOSE", "")
        capabilities = capabilities or md.get("CAPABILITIES", "")
        res = MCPClient(s).workspace_add(
            path=str(s.root), purpose=purpose, capabilities=capabilities, role=role
        )
        wid = str(res.get("workspace_id") or s.workspace_id)
        _write_workspace_md(s.root, wid, purpose, capabilities, role=role)
        return {"workspace_id": wid, "role": str(res.get("role") or role), "result": res}

    # ---------------------------------------------------------------- 专家
    def list_workspaces(self, include_offline: bool = False) -> list[dict[str, Any]]:
        from ..platform.mcp_client import MCPClient

        return MCPClient(self.settings).list_workspaces(include_offline=include_offline)

    def set_expert(self, goal_id: str, expert_workspace_id: str, expert_name: str = "") -> dict[str, Any]:
        if self.store.get_goal(goal_id) is None:
            raise KeyError(f"目标不存在: {goal_id}")
        self.store.set_goal_expert(goal_id, expert_workspace_id, expert_name)
        return {"ok": True, "goal_id": goal_id, "expert_workspace_id": expert_workspace_id}

    def delete_goal(self, goal_id: str) -> dict[str, Any]:
        """硬删除目标（含任务树/执行记录级联）。"""
        if self.store.get_goal(goal_id) is None:
            return {"ok": False, "error": f"目标不存在: {goal_id}"}
        self.store.delete_goal(goal_id)
        return {"ok": True, "deleted": goal_id}

    # ---------------------------------------------------------------- 派单
    def wrap_dispatch(self, message: str) -> str:
        """派单固定前导：先要求对方压缩上下文（规则机械化，不依赖 agent 记忆）。"""
        pre = (self.settings.dispatch_preamble or "").strip()
        msg = (message or "").strip()
        if pre and not msg.startswith(pre):
            return f"{pre}\n\n{msg}"
        return msg

    def dispatch(self, target: str, message: str, wait_seconds: int = 0, task_id: str = "") -> dict[str, Any]:
        """经平台 MCP `a2a_call` 把（带前导的）任务派给目标工作区。

        task_id：本地任务 ID。传了就把平台任务映射到该本地任务，并在 worker 终态时回写。
        """
        from ..platform.mcp_client import MCPClient

        wrapped = self.wrap_dispatch(message)
        result = MCPClient(self.settings).a2a_call(
            target, wrapped, self.settings.workspace_id, wait_seconds
        )
        ptid = str(result.get("task_id") or result.get("id") or "")
        if ptid:
            if task_id:
                self.store.link_platform_task(
                    ptid, local_kind="task", local_id=task_id, direction="out",
                    caller=self.settings.caller, status=str(result.get("status") or ""),
                )
                self.store.set_task_status(task_id, "running")
            else:
                self.store.link_platform_task(
                    ptid, local_kind="dispatch", local_id=target, direction="out",
                    caller=self.settings.caller, status=str(result.get("status") or ""),
                )
        return {"task_id": ptid, "target": target, "local_task_id": task_id,
                "message": wrapped, "result": result}

    # ---------------------------------------------------------------- nudge
    def build_nudge(self, goal_id: str) -> str:
        goal = self.store.get_goal(goal_id)
        if goal is None:
            raise KeyError(f"目标不存在: {goal_id}")
        tasks = self.store.list_tasks(goal_id)
        return build_prompt(self.settings, goal, tasks)

    def _throttled(self, goal_id: str) -> bool:
        last = self._last_nudge.get(goal_id, 0.0)
        return (time.monotonic() - last) < self.settings.nudge_min_interval

    async def nudge(self, goal_id: str, send: bool = False, force: bool = False) -> dict[str, Any]:
        """组装提示词；send=True 时经 A2A 网关投递给 planner 工作区。

        返回 {"prompt": str, "sent": bool, "task_id": str|None, "result": ...}
        """
        prompt = self.build_nudge(goal_id)
        out: dict[str, Any] = {"prompt": prompt, "sent": False, "task_id": None}
        if not send:
            return out
        if not force and self._throttled(goal_id):
            out["skipped"] = "nudge throttled"
            return out

        client = A2AClient(self.settings)
        result = await client.send(prompt)
        task_id = str(result.get("id") or "")
        self._last_nudge[goal_id] = time.monotonic()
        if task_id:
            self.store.link_platform_task(
                task_id, local_kind="goal", local_id=goal_id, direction="out",
                caller=self.settings.caller, status=str((result.get("status") or {}).get("state", "")),
            )
        out.update({"sent": True, "task_id": task_id, "result": result})
        return out

    # ---------------------------------------------------------------- 展示
    def overview(self) -> str:
        """跨目标概览。"""
        goals = self.list_goals()
        if not goals:
            return "（暂无目标）"
        lines = []
        for g in goals:
            tasks = self.store.list_tasks(g.id)
            done = sum(1 for t in tasks if t.status == "done")
            ready = sum(1 for t in tasks if t.status == "ready")
            blocked = sum(1 for t in tasks if t.status == "blocked")
            waiting = sum(1 for t in tasks if t.status == "waiting_human")
            lines.append(
                f"[{g.id}] {g.status:>8}  {done}/{len(tasks)}  {g.title}"
                f"  (ready {ready} / blocked {blocked} / waiting {waiting})"
            )
        return "\n".join(lines)

    def status_text(self, goal_id: str) -> str:
        goal = self.store.get_goal(goal_id)
        if goal is None:
            return f"目标不存在: {goal_id}"
        tasks = self.store.list_tasks(goal_id)
        by_id = {t.id: t for t in tasks}
        lines = [f"目标 [{goal.id}] {goal.title} ({goal.status})"]
        if not tasks:
            lines.append("  （暂无任务）")
        for t in tasks:
            deps = ",".join(by_id[d].title if d in by_id else d for d in t.depends_on)
            line = f"  - [{t.id}] {t.status:>12}  {t.title}"
            if deps:
                line += f"  (依赖: {deps})"
            if t.assigned_agent:
                line += f"  @{t.assigned_agent}"
            lines.append(line)
        return "\n".join(lines)

    def report(self, goal_id: str, task_id: str = "") -> str:
        """验收情况报告：目标 + 执行 + 证据，供 planner agent 交给专家验收。"""
        goal = self.store.get_goal(goal_id)
        if goal is None:
            return f"目标不存在: {goal_id}"
        tasks = self.store.list_tasks(goal_id)
        by_id = {t.id: t for t in tasks}
        done = sum(1 for t in tasks if t.status == "done")
        lines = [
            f"# 验收情况报告：{goal.title}",
            "",
            f"- 目标 ID：{goal.id}",
            f"- 专家工作区：{goal.expert_name or goal.expert_workspace_id or '(未指定)'}"
            + (f" (`{goal.expert_workspace_id}`)" if goal.expert_workspace_id else ""),
            f"- 拆解状态：{goal.plan_status} · 进度：{done}/{len(tasks)}",
        ]
        if goal.success_criteria:
            lines.append(f"- 成功标准：{goal.success_criteria}")
        lines.append("")
        if task_id and task_id in by_id:
            lines.append(f"> 本报告聚焦验收点 [{task_id}] {by_id[task_id].title}")
            lines.append("")
        lines.append("## 任务与执行")
        for t in tasks:
            mark = " ★验收点" if t.acceptance_type == "expert" else ""
            deps = ", ".join(by_id[d].title if d in by_id else d for d in t.depends_on)
            lines.append(f"- [{t.id}] {t.title} — **{t.status}**（验收 {t.acceptance_type}）{mark}")
            if deps:
                lines.append(f"    · 依赖：{deps}")
            if t.acceptance_result:
                lines.append(f"    · 验收结果：{t.acceptance_result[:300]}")
            for e in self.store.list_executions(t.id)[:2]:
                if e["output"]:
                    lines.append(f"    · 执行输出：{str(e['output'])[:400]}")
                if e["anchor"]:
                    lines.append(f"    · 锚点：{str(e['anchor'])[:400]}")
        lines.append("")
        lines.append("## 请专家裁决")
        lines.append("请回复 JSON：`{\"accepted\": true|false, \"reason\": \"...\", \"adjustments\": [...]}`")
        lines.append("（adjustments 为可选的调整后的任务列表，格式同 plan apply）")
        return "\n".join(lines)

    def markdown(self, goal_id: str) -> str:
        """任务树 markdown 快照（平台「规划器」页读 artifact 渲染用）。"""
        goal = self.store.get_goal(goal_id)
        if goal is None:
            return f"目标不存在: {goal_id}"
        tasks = self.store.list_tasks(goal_id)
        done = sum(1 for t in tasks if t.status == "done")
        by_id = {t.id: t for t in tasks}

        def esc(s: str) -> str:
            return (s or "").replace("|", "\\|").replace("\n", " ")

        lines = [
            f"# 目标：{goal.title}",
            "",
            f"- 状态：{goal.status} · 拆解：{goal.plan_status} · 优先级：{goal.priority} · 进度：{done}/{len(tasks)}",
        ]
        if goal.expert_workspace_id:
            lines.append(f"- 专家工作区：{goal.expert_name or goal.expert_workspace_id} (`{goal.expert_workspace_id}`)")
        if goal.success_criteria:
            mark = "（专家已确认）" if goal.criteria_confirmed else "（待专家确认）"
            lines.append(f"- 成功标准：{goal.success_criteria}{mark}")
        if goal.deadline:
            lines.append(f"- 截止：{goal.deadline}")
        lines.append("")
        lines.append("| 任务 | 状态 | 依赖 | 执行 | 验收 |")
        lines.append("|---|---|---|---|---|")
        for t in tasks:
            deps = ", ".join(esc(by_id[d].title) if d in by_id else d for d in t.depends_on)
            lines.append(
                f"| {esc(t.title)} | {t.status} | {deps} | {esc(t.assigned_agent)} | {t.acceptance_type} |"
            )
        return "\n".join(lines)
