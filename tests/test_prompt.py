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
    assert "压缩" in text  # 第 0 步：先压缩上下文


def test_prompt_empty_tree_asks_decompose():
    text = build_prompt(_settings(), Goal(id="g1", title="g"), [])
    assert "尚未拆解" in text


def test_prompt_self_expert_no_a2a():
    from planner_core.models import Goal as G

    text = build_prompt(_settings(), G(id="g1", title="g", expert_workspace_id="wid", expert_name="我"), [])
    assert "你自己" in text and "不要 a2a_call" in text


def test_prompt_remote_expert_uses_a2a():
    from planner_core.models import Goal as G

    text = build_prompt(_settings(), G(id="g1", title="g", expert_workspace_id="OTHER", expert_name="外部专家"), [])
    assert "a2a_call" in text and "外部专家" in text
