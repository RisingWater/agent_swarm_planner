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
    lines.append("1. 读取任务数据库（或调用 planner-core 暴露的状态接口）获取全量状态。")
    lines.append("2. 若任务树为空或不完整：把目标拆解为有依赖关系的任务，写入数据库。")
    lines.append("3. 对状态为「可执行(ready)」的任务：选择合适的 agent 工作区，")
    lines.append("   用 a2a_call 派发（from_workspace 填本工作区 ID），并回写执行状态。")
    lines.append("4. 若任务失败/阻塞：判断重试或重规划；需要人工决策时发起提问等待确认。")
    lines.append("5. 完成后回写任务状态；本轮无需人类介入时，简要说明你的决策即可。")
    if ready:
        lines.append("")
        lines.append("### 当前可派发任务")
        for t in ready:
            lines.append(f"  - [{t.id}] {t.title}")
    return "\n".join(lines)
