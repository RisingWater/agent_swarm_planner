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
    "waiting_expert": "待专家验收",
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
    lines.append(f"## 当前目标\n- ID: {goal.id}\n- 标题: {goal.title}\n- 拆解状态: {goal.plan_status}")
    if goal.expert_workspace_id:
        lines.append(f"- 专家工作区: {goal.expert_name or goal.expert_workspace_id} (id={goal.expert_workspace_id})")
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
    lines.append("2. 读取状态：`planner plan export <goal_id>`（或 `planner plan show <goal_id>`）。")
    if goal.expert_workspace_id:
        lines.append("3. 专家拆解：任务树为空/不完整时，先用平台 a2a_call 与该**专家工作区**多轮沟通")
        lines.append("   （from_workspace=本工作区，context_id 续聊），把目标讲清楚，请它**确认/修正成功标准**")
        lines.append("   并给出任务树与**专家验收点**；成功后用")
        lines.append("   `planner goal set-criteria <goal_id> \"<标准>\" --confirmed` 写回成功标准，")
        lines.append("   `planner plan apply` 写入任务树（验收点标 acceptance_type=expert）。")
    else:
        lines.append("3. 无专家工作区时，你可自行拆解并用 `planner plan apply` 写入。")
    lines.append("4. 拆解审批：`plan_status=draft` 时本轮只输出任务树等人工审批（页面「通过拆解」），不要派发。")
    lines.append("5. approved 后派发 ready 任务（**验收点除外**）：")
    lines.append("   `planner dispatch <target_wid> \"任务内容\" --task-id <task_id>`（worker 终态由守护回写）。")
    lines.append("6. 专家验收点（acceptance_type=expert）就绪时：运行 `planner report <goal_id> --task <task_id>`")
    lines.append("   汇总情况，a2a_call 请专家裁决（要求 JSON `{accepted, reason, adjustments?}`）；accepted→`task set done`；")
    lines.append("   有 adjustments→应用调整（`plan apply --replace`，整树替换）后 plan_status 回 draft，等人工再审。")
    lines.append("7. 失败/阻塞用 `planner plan recover <goal_id>`；`waiting_human` 任务由你发起提问，")
    lines.append("   批准则 `planner task set <task_id> done`，拒绝则 failed。")
    lines.append("8. 最后运行 `planner plan markdown <goal_id>`，把输出作为本次回答正文"
                 "（平台「规划器」页会展示它）。")
    if ready:
        lines.append("")
        lines.append("### 当前可派发任务")
        for t in ready:
            lines.append(f"  - [{t.id}] {t.title}")
    return "\n".join(lines)
