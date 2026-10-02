import pytest

from planner_core.config import Settings
from planner_core.service.orchestrator import PlannerService


def _service(tmp_path):
    s = Settings(server="http://x", api_key="as_x", workspace_id="wid",
                 db_path=tmp_path / "planner.db", root=tmp_path)
    svc = PlannerService(s)
    svc.init()
    return svc


def test_apply_plan_resolves_out_of_order_temp_ids(tmp_path):
    svc = _service(tmp_path)
    goal = svc.create_goal("g")
    created = svc.apply_plan(goal.id, {"tasks": [
        {"temp_id": "verify", "title": "验收", "depends_on": ["a2a"], "acceptance_type": "manual"},
        {"temp_id": "scaffold", "title": "搭骨架"},
        {"temp_id": "a2a", "title": "接 A2A", "depends_on": ["scaffold"]},
    ]})
    assert len(created) == 3
    tasks = {t.title: t for t in svc.store.list_tasks(goal.id)}
    assert tasks["接 A2A"].depends_on == [tasks["搭骨架"].id]
    assert tasks["验收"].depends_on == [tasks["接 A2A"].id]
    # 搭骨架无依赖 → 立即 ready
    assert tasks["搭骨架"].id in svc.refresh_ready(goal.id)


def test_apply_plan_rejects_cycle(tmp_path):
    from planner_core.engine.dag import DagError

    svc = _service(tmp_path)
    goal = svc.create_goal("g")
    with pytest.raises(DagError):
        svc.apply_plan(goal.id, {"tasks": [
            {"temp_id": "a", "title": "a", "depends_on": ["b"]},
            {"temp_id": "b", "title": "b", "depends_on": ["a"]},
        ]})


def test_export_goal(tmp_path):
    svc = _service(tmp_path)
    goal = svc.create_goal("g")
    svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    svc.refresh_ready(goal.id)
    out = svc.export_goal(goal.id)
    assert out["goal"]["id"] == goal.id
    assert len(out["tasks"]) == 1
    assert len(out["ready"]) == 1


def test_recover_retries_then_blocks(tmp_path):
    svc = _service(tmp_path)
    svc.settings.max_retry = 1
    goal = svc.create_goal("g")
    svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    svc.refresh_ready(goal.id)
    task = svc.store.list_tasks(goal.id)[0]

    svc.store.set_task_status(task.id, "failed")
    assert svc.recover(goal.id) == [{"task_id": task.id, "action": "retry"}]
    assert svc.store.get_task(task.id).status == "ready"  # pending 后依赖已满足 → ready

    svc.store.set_task_status(task.id, "failed")
    assert svc.recover(goal.id) == [{"task_id": task.id, "action": "blocked"}]
    assert svc.store.get_task(task.id).status == "blocked"


def test_markdown_snapshot(tmp_path):
    svc = _service(tmp_path)
    goal = svc.create_goal("上线", success_criteria="可访问")
    svc.apply_plan(goal.id, {"tasks": [
        {"temp_id": "a", "title": "搭骨架"},
        {"temp_id": "b", "title": "写 | 测试", "depends_on": ["a"]},
    ]})
    md = svc.markdown(goal.id)
    assert "# 目标：上线" in md
    assert "| 任务 | 状态 |" in md
    assert "写 \\| 测试" in md
    assert "0/2" in md


def test_apply_acceptance_manual_sets_waiting_human(tmp_path):
    svc = _service(tmp_path)
    goal = svc.create_goal("g")
    svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a", "acceptance_type": "manual"}]})
    t = svc.store.list_tasks(goal.id)[0]
    r = svc.apply_acceptance(t.id)
    assert r["status"] == "waiting_human"
    assert svc.store.get_task(t.id).status == "waiting_human"


def test_apply_acceptance_auto_runs_command(tmp_path):
    svc = _service(tmp_path)
    goal = svc.create_goal("g")
    svc.apply_plan(goal.id, {"tasks": [{
        "temp_id": "a", "title": "a", "acceptance_type": "auto",
        "execution_spec": {"accept_command": 'python -c "print(1)"'},
    }]})
    t = svc.store.list_tasks(goal.id)[0]
    r = svc.apply_acceptance(t.id)
    assert r["status"] == "done"
    assert svc.store.get_task(t.id).status == "done"


def test_apply_acceptance_auto_no_command_done(tmp_path):
    svc = _service(tmp_path)
    goal = svc.create_goal("g")
    svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a", "acceptance_type": "auto"}]})
    t = svc.store.list_tasks(goal.id)[0]
    assert svc.apply_acceptance(t.id)["status"] == "done"


def test_set_expert_and_expert_acceptance(tmp_path):
    svc = _service(tmp_path)
    goal = svc.create_goal("g")
    svc.set_expert(goal.id, "E1", "领域专家")
    assert svc.store.get_goal(goal.id).expert_workspace_id == "E1"
    svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "验收点", "acceptance_type": "expert"}]})
    t = svc.store.list_tasks(goal.id)[0]
    assert t.acceptance_type == "expert"
    assert svc.apply_acceptance(t.id)["status"] == "waiting_expert"
    assert svc.store.get_task(t.id).status == "waiting_expert"
