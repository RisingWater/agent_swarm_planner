"""待办通知（notify 边沿帧）与幂等去重（协议 §7，任务 task_b5ac1c6521cd）。"""

import json

import pytest

from planner_core.config import Settings
from planner_core.platform.planner_ws import flush_notifications
from planner_core.service.orchestrator import PlannerService


def _svc(tmp_path):
    svc = PlannerService(Settings(server="http://x", api_key="as_x", workspace_id="wid",
                                  db_path=tmp_path / "planner.db", root=tmp_path))
    svc.init()
    return svc


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(json.loads(data))

    def types(self):
        return [m.get("type") for m in self.sent]

    def notifies(self):
        return [m["payload"] for m in self.sent if m.get("type") == "notify"]


def test_plan_rev_increments_on_entering_draft(tmp_path):
    svc = _svc(tmp_path)
    g = svc.create_goal("g")
    svc.apply_plan(g.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    assert svc.store.get_goal(g.id).plan_rev == 1
    svc.store.set_goal_plan_status(g.id, "approved")
    assert svc.store.get_goal(g.id).plan_rev == 1  # approved 不自增
    svc.store.set_goal_plan_status(g.id, "draft")  # revise 重新进入 draft
    assert svc.store.get_goal(g.id).plan_rev == 2


def test_pending_plan_approval(tmp_path):
    svc = _svc(tmp_path)
    g = svc.create_goal("上线 MVP")
    svc.apply_plan(g.id, {"tasks": [{"temp_id": "a", "title": "a"},
                                   {"temp_id": "b", "title": "b"}]})
    pend = svc.store.pending_notifications()
    assert len(pend) == 1
    p = pend[0]
    assert p["kind"] == "plan_approval"
    assert p["key"] == f"plan:{g.id}:1"
    assert p["goal_id"] == g.id and p["task_id"] == ""
    assert "拆解待审批" in p["title"]


def test_pending_excludes_archived_and_taskless(tmp_path):
    svc = _svc(tmp_path)
    empty = svc.create_goal("空目标")            # draft 但无任务 → 不通知
    arch = svc.create_goal("归档目标")
    svc.apply_plan(arch.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    svc.store.set_goal_status(arch.id, "archived")  # 非 active → 不通知
    keys = {p["key"] for p in svc.store.pending_notifications()}
    assert all(k.startswith(f"plan:{empty.id}:") is False for k in keys)
    assert not any(k.startswith(f"plan:{arch.id}:") for k in keys)


def test_mark_notified_suppresses(tmp_path):
    svc = _svc(tmp_path)
    g = svc.create_goal("g")
    svc.apply_plan(g.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    key = f"plan:{g.id}:1"
    assert [p["key"] for p in svc.store.pending_notifications()] == [key]
    svc.store.mark_notified(key, "plan_approval", g.id, "")
    assert svc.store.pending_notifications() == []


def test_pending_task_acceptance_only_manual_waiting_human(tmp_path):
    svc = _svc(tmp_path)
    g = svc.create_goal("g")
    svc.apply_plan(g.id, {"tasks": [
        {"temp_id": "m", "title": "人工验收", "acceptance_type": "manual"},
        {"temp_id": "x", "title": "专家验收", "acceptance_type": "expert"},
        {"temp_id": "a", "title": "自动验收", "acceptance_type": "auto"},
    ]})
    tasks = {t.title: t for t in svc.store.list_tasks(g.id)}
    svc.store.set_task_status(tasks["人工验收"].id, "waiting_human")
    svc.store.set_task_status(tasks["专家验收"].id, "waiting_human")  # 专家点不在此通知
    svc.store.set_task_status(tasks["自动验收"].id, "waiting_human")
    acc = [p for p in svc.store.pending_notifications() if p["kind"] == "task_acceptance"]
    assert len(acc) == 1
    assert acc[0]["task_id"] == tasks["人工验收"].id
    assert acc[0]["key"] == f"accept:{tasks['人工验收'].id}:0"


@pytest.mark.asyncio
async def test_flush_sends_once_then_marks(tmp_path):
    svc = _svc(tmp_path)
    g = svc.create_goal("上线 MVP")
    svc.apply_plan(g.id, {"tasks": [{"temp_id": "a", "title": "a"}]})

    ws = FakeWS()
    await flush_notifications(ws, svc)
    notifies = ws.notifies()
    assert len(notifies) == 1
    assert notifies[0]["kind"] == "plan_approval"
    assert notifies[0]["workspace_id"] == "wid"
    assert notifies[0]["key"] == f"plan:{g.id}:1"

    # 已落键 → 再次 flush（含断线重连后）不重发
    ws2 = FakeWS()
    await flush_notifications(ws2, svc)
    assert ws2.notifies() == []


@pytest.mark.asyncio
async def test_flush_failure_does_not_mark(tmp_path):
    svc = _svc(tmp_path)
    g = svc.create_goal("g")
    svc.apply_plan(g.id, {"tasks": [{"temp_id": "a", "title": "a"}]})

    class Boom:
        async def send(self, _):
            raise ConnectionError("ws down")

    await flush_notifications(Boom(), svc)
    # 发送失败不落键 → 下次仍待发
    assert len(svc.store.pending_notifications()) == 1
