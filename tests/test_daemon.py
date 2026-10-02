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
    assert d._needs_attention(goal.id) is True


def test_needs_attention_when_ready(tmp_path):
    d = _daemon(tmp_path)
    goal = d.svc.create_goal("g")
    d.svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    d.svc.refresh_ready(goal.id)
    assert d._needs_attention(goal.id) is True


def test_no_attention_when_all_done(tmp_path):
    d = _daemon(tmp_path)
    goal = d.svc.create_goal("g")
    d.svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    task = d.svc.store.list_tasks(goal.id)[0]
    d.svc.store.set_task_status(task.id, "done")
    assert d._needs_attention(goal.id) is False


def test_ingest_updates_platform_task(tmp_path):
    d = _daemon(tmp_path)
    d.svc.store.link_platform_task("pt1", "goal", "g1", "out", status="working")
    d._handle_frame({"type": "task", "task": {"id": "pt1", "status": {"state": "completed"}}})
    assert d.svc.store.get_platform_task("pt1")["status"] == "completed"
