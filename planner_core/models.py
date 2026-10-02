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
)

# 终态：不再参与调度
TERMINAL_TASK_STATUSES = ("done", "failed", "blocked")

GOAL_STATUSES = ("active", "archived", "done")

ACCEPTANCE_TYPES = ("auto", "manual")


@dataclass
class Goal:
    id: str
    title: str
    description: str = ""
    priority: int = 0
    deadline: str = ""
    success_criteria: str = ""
    status: str = "active"
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
