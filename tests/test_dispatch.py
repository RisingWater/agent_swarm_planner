import json

import httpx
import pytest

from planner_core.config import Settings
from planner_core.platform.mcp_client import MCPClient, MCPError
from planner_core.service.orchestrator import PlannerService


def _settings(tmp_path):
    return Settings(server="http://x", api_key="as_x", workspace_id="wid",
                    db_path=tmp_path / "planner.db", root=tmp_path)


def _svc(tmp_path):
    svc = PlannerService(_settings(tmp_path))
    svc.init()
    return svc


def test_wrap_dispatch_prepends_preamble(tmp_path):
    svc = _svc(tmp_path)
    out = svc.wrap_dispatch("给我干个活")
    assert out.startswith("请先压缩")
    assert "给我干个活" in out
    assert "代码边界规则" in out  # 派单固定携带代码边界规则
    assert svc.wrap_dispatch(out) == out  # 不重复加前导


def test_dispatch_links_platform_task(tmp_path, monkeypatch):
    svc = _svc(tmp_path)

    class FakeMCP:
        def __init__(self, settings):
            self.settings = settings

        def a2a_call(self, target, message, from_workspace, wait_seconds=0):
            assert "压缩" in message and target == "wid2" and from_workspace == "wid"
            return {"task_id": "pt9", "status": "queued"}

    monkeypatch.setattr("planner_core.platform.mcp_client.MCPClient", FakeMCP)
    out = svc.dispatch("wid2", "干活")
    assert out["task_id"] == "pt9"
    row = svc.store.get_platform_task("pt9")
    assert row["local_id"] == "wid2" and row["status"] == "queued"


def test_dispatch_with_task_id_sets_running_and_links(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    goal = svc.create_goal("g")
    svc.apply_plan(goal.id, {"tasks": [{"temp_id": "a", "title": "a"}]})
    task = svc.store.list_tasks(goal.id)[0]

    class FakeMCP:
        def __init__(self, settings):
            pass

        def a2a_call(self, target, message, from_workspace, wait_seconds=0):
            return {"task_id": "ptW", "status": "queued"}

    monkeypatch.setattr("planner_core.platform.mcp_client.MCPClient", FakeMCP)
    out = svc.dispatch("wid2", "干活", task_id=task.id)
    assert out["local_task_id"] == task.id
    row = svc.store.get_platform_task("ptW")
    assert row["local_kind"] == "task" and row["local_id"] == task.id
    assert svc.store.get_task(task.id).status == "running"


def _client_with(handler, tmp_path):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return MCPClient(_settings(tmp_path), client=http), http


def test_mcp_client_parses_tool_result(tmp_path):
    def handler(request):
        body = json.loads(request.content)
        assert body["method"] == "tools/call"
        assert body["params"]["name"] == "a2a_call"
        assert request.headers["authorization"] == "Bearer as_x"
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "result": {"content": [{"type": "text", "text": json.dumps({"task_id": "t1", "status": "queued"})}],
                       "isError": False},
        })

    mc, http = _client_with(handler, tmp_path)
    try:
        r = mc.a2a_call("wid2", "msg", "wid1")
        assert r["task_id"] == "t1" and r["status"] == "queued"
    finally:
        http.close()


def test_mcp_client_raises_on_tool_error(tmp_path):
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "result": {"content": [{"type": "text", "text": "ValueError: boom"}], "isError": True},
        })

    mc, http = _client_with(handler, tmp_path)
    try:
        with pytest.raises(MCPError):
            mc.list_workspaces()
    finally:
        http.close()
