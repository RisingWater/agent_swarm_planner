"""组装注入给 planner agent 的提示词（todo / 任务树 / 目录 / DB 路径）。

planner-core 只负责"把现状讲清楚"；拆解与决策由 planner agent 用自己的模型完成。
"""

from __future__ import annotations

from ..config import Settings
from ..models import Goal, Task

_STATUS_LABEL = {
    "pending": "待处理",
    "ready": "可执行",
    "running": "执行中",
    "done": "已完成",
    "failed": "失败",
    "blocked": "阻塞",
    "waiting_human": "待人工",
}


def _task_line(t: Task, by_id: dict[str, Task]) -> str:
    label = _STATUS_LABEL.get(t.status, t.status)
    extras = []
    if t.depends_on:
        names = ", ".join(by_id[d].title if d in by_id else d for d in t.depends_on)
        extras.append(f"依赖: {names}")
    if t.assigned_agent:
        extras.append(f"建议执行: {t.assigned_agent}")
    if t.acceptance_type:
        extras.append(f"验收: {t.acceptance_type}")
    if t.retry_count:
        extras.append(f"重试: {t.retry_count}")
    tail = ("；" + "；".join(extras)) if extras else ""
    return f"  - [{t.id}] ({label}) {t.title}{tail}"


def build_prompt(settings: Settings, goal: Goal, tasks: list[Task]) -> str:
    by_id = {t.id: t for t in tasks}
    ready = [t for t in tasks if t.status == "ready"]
    lines: list[str] = []
    lines.append("[planner] 收到规划请求。请作为本工作区的 planner agent 做决策。")
    lines.append("")
    lines.append(f"项目目录: {settings.root}")
    lines.append(f"任务数据库: {settings.db_path}")
    lines.append(f"工作区 ID: {settings.workspace_id}")
    lines.append("命令入口: 在本目录运行 `planner <子命令>`（未安装则用 `.venv\\Scripts\\python.exe -m planner_core <子命令>`）。")
    lines.append("")
    lines.append(f"## 当前目标\n- ID: {goal.id}\n- 标题: {goal.title}")
    if goal.description:
        lines.append(f"- 描述: {goal.description}")
    if goal.success_criteria:
        lines.append(f"- 成功标准: {goal.success_criteria}")
    if goal.deadline:
        lines.append(f"- 截止: {goal.deadline}")
    lines.append("")
    if tasks:
        lines.append("## 当前任务树 / todo")
        lines.extend(_task_line(t, by_id) for t in tasks)
    else:
        lines.append("## 当前任务树 / todo\n  （空：尚未拆解）")
    lines.append("")
    lines.append("## 请执行")
    lines.append(f"0. {settings.first_step}")
    lines.append("1. 读本仓库 AGENTS.md 的「Planner agent playbook」，按其中的 CLI 流程执行。")
    lines.append("2. 读取状态：`planner plan export <goal_id>`（或 `planner plan show <goal_id>`）；")
    lines.append("   任务树为空/不完整则拆解后 `planner plan apply <goal_id> --file plan.json` 写入。")
    lines.append("3. 对 ready 任务用 `planner dispatch <target_wid> \"任务内容\" --task-id <task_id>` 派发；")
    lines.append("   守护进程会在 worker 终态时把该任务回写为 done/failed。")
    lines.append("4. 失败/阻塞用 `planner plan recover <goal_id>`；`waiting_human`（人工验收）任务由你发起提问，")
    lines.append("   批准则 `planner task set <task_id> done`，拒绝则 failed。")
    lines.append("5. 最后运行 `planner plan markdown <goal_id>`，把输出作为本次回答正文"
                 "（平台「规划器」页会展示它）。")
    if ready:
        lines.append("")
        lines.append("### 当前可派发任务")
        for t in ready:
            lines.append(f"  - [{t.id}] {t.title}")
    return "\n".join(lines)
