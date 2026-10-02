"""PlannerService：确定性编排。

职责：目标/任务 CRUD、DAG 就绪计算、组装并（可选）投递提示词给 planner agent。
不调用任何 LLM。
"""

from __future__ import annotations

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


def _write_workspace_md(root, workspace_id: str, purpose: str, capabilities: str) -> None:
    from pathlib import Path

    f = Path(root) / ".agent_swarm" / "workspace.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    cur = _read_workspace_md(root)
    cur["WORKSPACE_ID"] = workspace_id
    if purpose:
        cur["PURPOSE"] = purpose
    if capabilities:
        cur["CAPABILITIES"] = capabilities
    order = ["WORKSPACE_ID", "PURPOSE", "CAPABILITIES"]
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
    ) -> Goal:
        return self.store.add_goal(title, description, priority, deadline, success_criteria)

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
    def apply_plan(self, goal_id: str, plan: dict[str, Any]) -> list[Task]:
        """把 agent 拆解出的 JSON 计划写入任务树。

        计划格式：
        {"tasks": [{"temp_id","title","description","depends_on":[temp_id],
                    "assigned_agent","acceptance_type","execution_spec"}]}
        两趟写入以支持任意顺序的依赖引用；最后统一校验 DAG。
        """
        if self.store.get_goal(goal_id) is None:
            raise KeyError(f"目标不存在: {goal_id}")
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

    def state(self, goal_id: str | None = None) -> dict[str, Any]:
        """供 agent 读取的完整状态快照。"""
        if goal_id:
            goal = self.store.get_goal(goal_id)
            if goal is None:
                raise KeyError(f"目标不存在: {goal_id}")
            return {"goals": [goal.__dict__], "tasks": [t.__dict__ for t in self.store.list_tasks(goal_id)]}
        goals = self.list_goals()
        tasks: list[dict[str, Any]] = []
        for g in goals:
            tasks.extend(t.__dict__ for t in self.store.list_tasks(g.id))
        return {"goals": [g.__dict__ for g in goals], "tasks": tasks}

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
        _write_workspace_md(s.root, wid, purpose, capabilities)
        return {"workspace_id": wid, "role": str(res.get("role") or role), "result": res}

    # ---------------------------------------------------------------- 派单
    def wrap_dispatch(self, message: str) -> str:
        """派单固定前导：先要求对方压缩上下文（规则机械化，不依赖 agent 记忆）。"""
        pre = (self.settings.dispatch_preamble or "").strip()
        msg = (message or "").strip()
        if pre and not msg.startswith(pre):
            return f"{pre}\n\n{msg}"
        return msg

    def dispatch(self, target: str, message: str, wait_seconds: int = 0) -> dict[str, Any]:
        """经平台 MCP `a2a_call` 把（带前导的）任务派给目标工作区。"""
        from ..platform.mcp_client import MCPClient

        wrapped = self.wrap_dispatch(message)
        result = MCPClient(self.settings).a2a_call(
            target, wrapped, self.settings.workspace_id, wait_seconds
        )
        task_id = str(result.get("task_id") or result.get("id") or "")
        if task_id:
            self.store.link_platform_task(
                task_id, local_kind="dispatch", local_id=target, direction="out",
                caller=self.settings.caller, status=str(result.get("status") or ""),
            )
        return {"task_id": task_id, "target": target, "message": wrapped, "result": result}

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
            f"- 状态：{goal.status} · 优先级：{goal.priority} · 进度：{done}/{len(tasks)}",
        ]
        if goal.success_criteria:
            lines.append(f"- 成功标准：{goal.success_criteria}")
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
