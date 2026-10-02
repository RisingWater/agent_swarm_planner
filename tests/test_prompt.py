from planner_core.config import Settings
from planner_core.engine.prompt import build_prompt
from planner_core.models import Goal, Task


def _settings():
    return Settings(server="http://127.0.0.1:8700", api_key="as_x", workspace_id="wid",
                    db_path="D:/x/planner.db", root="D:/x")


def test_prompt_contains_goal_and_tasks():
    goal = Goal(id="g1", title="上线 MVP", success_criteria="可访问")
    tasks = [
        Task(id="t1", goal_id="g1", title="搭骨架", status="done"),
        Task(id="t2", goal_id="g1", title="写测试", status="ready", depends_on=["t1"]),
    ]
    text = build_prompt(_settings(), goal, tasks)
    assert "上线 MVP" in text
    assert "写测试" in text
    assert "可执行" in text
    assert "当前可派发任务" in text
    assert "D:/x" in text


def test_prompt_empty_tree_asks_decompose():
    text = build_prompt(_settings(), Goal(id="g1", title="g"), [])
    assert "尚未拆解" in text
