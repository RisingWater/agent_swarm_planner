import pytest

from planner_core.config import Settings
from planner_core.platform.planner_ws import ws_url
from planner_core.service.orchestrator import PlannerService


def _svc(tmp_path):
    svc = PlannerService(Settings(server="http://x", api_key="as_x", workspace_id="wid",
                                  db_path=tmp_path / "planner.db", root=tmp_path))
    svc.init()
    return svc


def test_ws_url():
    assert ws_url("http://127.0.0.1:8700", "/ws/planner") == "ws://127.0.0.1:8700/ws/planner"
    assert ws_url("https://h", "/ws/planner") == "wss://h/ws/planner"


@pytest.mark.asyncio
async def test_goal_create_then_state(tmp_path):
    svc = _svc(tmp_path)
    r = await svc.handle_op("goal.create", {"title": "上线 MVP", "success_criteria": "可访问"}, op_id="op1")
    assert r["ok"] and r["goal_id"]
    st = await svc.handle_op("state.get", {})
    assert st["state"]["goals"][0]["title"] == "上线 MVP"


@pytest.mark.asyncio
async def test_op_idempotent(tmp_path):
    svc = _svc(tmp_path)
    r1 = await svc.handle_op("goal.create", {"title": "g"}, op_id="dup")
    r2 = await svc.handle_op("goal.create", {"title": "g"}, op_id="dup")
    assert r1 == r2
    assert len(svc.store.list_goals()) == 1  # 未重复建目标


@pytest.mark.asyncio
async def test_task_accept_reject(tmp_path):
    svc = _svc(tmp_path)
    goal = svc.create_goal("g")
    svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a"}, {"temp_id": "b", "title": "b"}]})
    ta, tb = svc.store.list_tasks(goal.id)
    svc.store.set_task_status(ta.id, "waiting_human")
    svc.store.set_task_status(tb.id, "waiting_human")
    assert (await svc.handle_op("task.accept", {"task_id": ta.id, "result": "人验通过"}))["ok"]
    assert svc.store.get_task(ta.id).status == "done"
    assert svc.store.get_task(ta.id).acceptance_result == "人验通过"
    assert (await svc.handle_op("task.reject", {"task_id": tb.id, "reason": "图像不对"}))["ok"]
    assert svc.store.get_task(tb.id).status == "failed"


@pytest.mark.asyncio
async def test_task_accept_requires_waiting_human(tmp_path):
    svc = _svc(tmp_path)
    goal = svc.create_goal("g")
    svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    t = svc.store.list_tasks(goal.id)[0]  # pending
    r = await svc.handle_op("task.accept", {"task_id": t.id})
    assert r["ok"] is False and "待验收" in r["error"]
    assert svc.store.get_task(t.id).status == "pending"


@pytest.mark.asyncio
async def test_goal_update_and_archive(tmp_path):
    svc = _svc(tmp_path)
    g = svc.create_goal("旧标题")
    assert (await svc.handle_op("goal.update", {"goal_id": g.id, "title": "新标题"}))["ok"]
    assert svc.store.get_goal(g.id).title == "新标题"
    assert (await svc.handle_op("goal.archive", {"goal_id": g.id}))["ok"]
    assert svc.store.get_goal(g.id).status == "archived"


@pytest.mark.asyncio
async def test_plan_approve_sets_approved(tmp_path):
    svc = _svc(tmp_path)
    g = svc.create_goal("g")
    svc.apply_plan(g.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    assert svc.store.get_goal(g.id).plan_status == "draft"
    r = await svc.handle_op("plan.approve", {"goal_id": g.id})
    assert r["ok"]
    assert svc.store.get_goal(g.id).plan_status == "approved"
    await svc.handle_op("plan.revise", {"goal_id": g.id})
    assert svc.store.get_goal(g.id).plan_status == "draft"


@pytest.mark.asyncio
async def test_goal_create_with_expert(tmp_path):
    svc = _svc(tmp_path)
    r = await svc.handle_op("goal.create", {
        "title": "g", "expert_workspace_id": "E1", "expert_name": "领域专家"}, op_id="exp1")
    st = await svc.handle_op("state.get", {})
    goal = st["state"]["goals"][0]
    assert r["ok"] and goal["expert_workspace_id"] == "E1" and goal["expert_name"] == "领域专家"


@pytest.mark.asyncio
async def test_unknown_op(tmp_path):
    svc = _svc(tmp_path)
    r = await svc.handle_op("nope", {})
    assert r["ok"] is False and "未知操作" in r["error"]
