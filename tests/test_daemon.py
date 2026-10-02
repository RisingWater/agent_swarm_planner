from planner_core.config import Settings
from planner_core.service.daemon import PlannerDaemon


def _daemon(tmp_path):
    s = Settings(server="http://x", api_key="as_x", workspace_id="wid",
                 db_path=tmp_path / "planner.db", root=tmp_path)
    d = PlannerDaemon(s, send=False)
    d.svc.init()
    return d


def test_needs_attention_when_no_tasks(tmp_path):
    d = _daemon(tmp_path)
    goal = d.svc.create_goal("g")
    assert d._needs_attention(goal) is True


def test_draft_plan_not_nudged(tmp_path):
    d = _daemon(tmp_path)
    goal = d.svc.create_goal("g")
    d.svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    d.svc.refresh_ready(goal.id)
    assert d.svc.store.get_goal(goal.id).plan_status == "draft"
    assert d._needs_attention(d.svc.store.get_goal(goal.id)) is False  # 等人工审批


def test_needs_attention_when_ready_and_approved(tmp_path):
    d = _daemon(tmp_path)
    goal = d.svc.create_goal("g")
    d.svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    d.svc.refresh_ready(goal.id)
    d.svc.store.set_goal_plan_status(goal.id, "approved")
    assert d._needs_attention(d.svc.store.get_goal(goal.id)) is True


def test_no_attention_when_all_done(tmp_path):
    d = _daemon(tmp_path)
    goal = d.svc.create_goal("g")
    d.svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    task = d.svc.store.list_tasks(goal.id)[0]
    d.svc.store.set_task_status(task.id, "done")
    d.svc.store.set_goal_plan_status(goal.id, "approved")
    assert d._needs_attention(d.svc.store.get_goal(goal.id)) is False


def test_tick_completes_goal_when_all_tasks_done(tmp_path):
    import asyncio

    d = _daemon(tmp_path)
    goal = d.svc.create_goal("g")
    d.svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    task = d.svc.store.list_tasks(goal.id)[0]
    d.svc.store.set_task_status(task.id, "done")
    asyncio.run(d._tick())
    assert d.svc.store.get_goal(goal.id).status == "done"


def test_ingest_updates_platform_task(tmp_path):
    d = _daemon(tmp_path)
    d.svc.store.link_platform_task("pt1", "goal", "g1", "out", status="working")
    d._handle_frame({"type": "task", "task": {"id": "pt1", "status": {"state": "completed"}}})
    assert d.svc.store.get_platform_task("pt1")["status"] == "completed"


def test_ingest_worker_terminal_writes_back_local_task(tmp_path):
    d = _daemon(tmp_path)
    goal = d.svc.create_goal("g")
    d.svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    task = d.svc.store.list_tasks(goal.id)[0]
    d.svc.store.link_platform_task("pt2", "task", task.id, "out", status="working")

    d._handle_frame({"type": "event", "payload": {
        "kind": "status-update", "taskId": "pt2", "status": {"state": "completed"}}})
    assert d.svc.store.get_task(task.id).status == "done"
    assert len(d.svc.store.list_executions(task.id)) == 1


def test_ingest_worker_failed_and_waiting(tmp_path):
    d = _daemon(tmp_path)
    goal = d.svc.create_goal("g")
    d.svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a"}, {"temp_id": "b", "title": "b"}]})
    ta, tb = d.svc.store.list_tasks(goal.id)
    d.svc.store.link_platform_task("ptf", "task", ta.id, "out")
    d.svc.store.link_platform_task("ptw", "task", tb.id, "out")

    d._handle_frame({"type": "task", "task": {"id": "ptf", "status": {"state": "failed"}}})
    d._handle_frame({"type": "task", "task": {"id": "ptw", "status": {"state": "input-required"}}})
    assert d.svc.store.get_task(ta.id).status == "failed"
    assert d.svc.store.get_task(tb.id).status == "waiting_human"
