from planner_core.config import Settings
from planner_core.service.orchestrator import PlannerService


def _svc(tmp_path):
    svc = PlannerService(Settings(server="http://x", api_key="as_x", workspace_id="wid",
                                  db_path=tmp_path / "planner.db", root=tmp_path))
    svc.init()
    return svc


def test_register_marks_planner_and_writes_md(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    seen = {}

    class FakeMCP:
        def __init__(self, settings):
            pass

        def workspace_add(self, path, purpose="", capabilities="", name="", role="planner"):
            seen.update(path=path, role=role, purpose=purpose, capabilities=capabilities)
            return {"workspace_id": "ws_new", "role": role}

    monkeypatch.setattr("planner_core.platform.mcp_client.MCPClient", FakeMCP)
    res = svc.register(role="planner", purpose="规划器", capabilities="DAG")
    assert res["workspace_id"] == "ws_new" and res["role"] == "planner"
    assert seen["role"] == "planner" and seen["path"] == str(tmp_path)

    md = (tmp_path / ".agent_swarm" / "workspace.md").read_text(encoding="utf-8")
    assert "WORKSPACE_ID: ws_new" in md
    assert "PURPOSE: 规划器" in md
    assert "CAPABILITIES: DAG" in md


def test_register_preserves_existing_purpose(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    d = tmp_path / ".agent_swarm"
    d.mkdir()
    (d / "workspace.md").write_text("WORKSPACE_ID: old\nPURPOSE: 旧用途\n", encoding="utf-8")

    class FakeMCP:
        def __init__(self, settings):
            pass

        def workspace_add(self, path, purpose="", capabilities="", name="", role="planner"):
            assert purpose == "旧用途"  # 从 workspace.md 回填
            return {"workspace_id": "wid", "role": role}

    monkeypatch.setattr("planner_core.platform.mcp_client.MCPClient", FakeMCP)
    svc.register(role="planner")
    md = (d / "workspace.md").read_text(encoding="utf-8")
    assert "PURPOSE: 旧用途" in md and "WORKSPACE_ID: wid" in md
