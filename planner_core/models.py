"""领域模型与枚举常量（对应需求文档 §8）。"""

from __future__ import annotations

from dataclasses import dataclass, field

# 任务状态机（需求文档 §8 tasks.status）
TASK_STATUSES = (
    "pending",
    "ready",
    "running",
    "done",
    "failed",
    "blocked",
    "waiting_human",
    "waiting_expert",
)

# 终态：不再参与调度
TERMINAL_TASK_STATUSES = ("done", "failed", "blocked")

GOAL_STATUSES = ("active", "archived", "done")

ACCEPTANCE_TYPES = ("auto", "manual", "expert")

# 优先级：高/中/低 ↔ 2/1/0（排序按数值大优先）
PRIORITY_LEVELS = {"高": 2, "中": 1, "低": 0}
PRIORITY_LABELS = {2: "高", 1: "中", 0: "低"}


def priority_label(p: int) -> str:
    return PRIORITY_LABELS.get(int(p or 0), str(p))


@dataclass
class Goal:
    id: str
    title: str
    description: str = ""
    priority: int = 0
    deadline: str = ""
    success_criteria: str = ""
    status: str = "active"
    plan_status: str = "draft"   # draft | approved
    criteria_confirmed: int = 0  # 成功标准是否经专家确认
    expert_workspace_id: str = ""
    expert_name: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Task:
    id: str
    goal_id: str
    title: str
    parent_id: str = ""
    description: str = ""
    status: str = "pending"
    assigned_agent: str = ""
    execution_spec: str = "{}"  # JSON 文本：输入/输出/验收标准
    acceptance_type: str = "auto"
    acceptance_result: str = ""
    retry_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    depends_on: list[str] = field(default_factory=list)
