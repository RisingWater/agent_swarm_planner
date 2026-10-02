import json

import pytest

from planner_core.config import Settings
from planner_core.mcp_server import PlannerTools, TOOL_SPECS, handle_request


@pytest.fixture()
def tools(tmp_path):
    s = Settings(server="http://x", api_key="as_x", workspace_id="wid",
                 db_path=tmp_path / "planner.db", root=tmp_path)
    return PlannerTools(s)


def _call(tools, name, args):
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": name, "arguments": args}}
    resp = handle_request(tools, req)
    text = resp["result"]["content"][0]["text"]
    try:
        data = json.loads(text)
    except ValueError:
        data = text
    return data, resp["result"]["isError"]


def test_initialize_and_tools_list(tools):
    init = handle_request(tools, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init["result"]["serverInfo"]["name"] == "agent-swarm-planner"
    names = {t["name"] for t in handle_request(tools, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
    assert names == {t["name"] for t in TOOL_SPECS}


def test_notification_returns_none(tools):
    assert handle_request(tools, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_add_goal_and_save_plan_roundtrip(tools):
    goal, err = _call(tools, "planner_add_goal", {"title": "g1", "success_criteria": "ok"})
    assert err is False
    gid = goal["id"]
    created, err = _call(tools, "planner_save_plan", {"goal_id": gid, "tasks": [
        {"temp_id": "a", "title": "a"},
        {"temp_id": "b", "title": "b", "depends_on": ["a"]},
    ]})
    assert err is False and len(created["created"]) == 2
    ready, err = _call(tools, "planner_next_ready", {"goal_id": gid})
    assert err is False
    assert ready["ready"][0]["title"] == "a"
    state, err = _call(tools, "planner_get_state", {"goal_id": gid})
    assert len(state["tasks"]) == 2


def test_unknown_tool_is_error(tools):
    data, err = _call(tools, "planner_nope", {})
    assert err is True
    assert "未知工具" in data or "工具" in json.dumps(data, ensure_ascii=False)


def test_set_status_and_record_execution(tools):
    goal, _ = _call(tools, "planner_add_goal", {"title": "g"})
    created, _ = _call(tools, "planner_save_plan", {"goal_id": goal["id"], "tasks": [{"temp_id": "a", "title": "a"}]})
    tid = created["created"][0]["id"]
    _, err = _call(tools, "planner_set_task_status", {"task_id": tid, "status": "running"})
    assert err is False
    _, err = _call(tools, "planner_record_execution", {"task_id": tid, "output": "ok", "status": "done"})
    assert err is False
    state, _ = _call(tools, "planner_get_state", {"goal_id": goal["id"]})
    assert state["tasks"][0]["status"] == "done"


def test_serve_refuses_without_planner_marker(tools, tmp_path):
    from planner_core.config import Settings
    from planner_core.mcp_server import serve

    s = Settings(server="http://x", api_key="as_x", workspace_id="wid",
                 db_path=tmp_path / "p.db", root=tmp_path)
    with pytest.raises(SystemExit):
        serve(s, enforce_guard=True)
