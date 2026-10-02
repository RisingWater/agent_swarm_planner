from pathlib import Path

from planner_core.config import load_settings


def test_reads_workspace_id_from_md(tmp_path, monkeypatch):
    (tmp_path / ".agent_swarm").mkdir()
    (tmp_path / ".agent_swarm" / "workspace.md").write_text(
        "WORKSPACE_ID: ws_123\nPURPOSE: x\n", encoding="utf-8"
    )
    monkeypatch.setenv("AGENT_SWARM_SERVER", "http://s")
    monkeypatch.setenv("AGENT_SWARM_API_KEY", "as_k")
    monkeypatch.setenv("PLANNER_WORKSPACE_ID", "")
    monkeypatch.delenv("PLANNER_WORKSPACE_ID", raising=False)
    s = load_settings(tmp_path)
    assert s.workspace_id == "ws_123"
    assert s.server == "http://s"
    assert s.a2a_url.endswith("/a2a/ws_123")


def test_dotenv_parsed(tmp_path, monkeypatch):
    for k in ("AGENT_SWARM_SERVER", "AGENT_SWARM_API_KEY", "PLANNER_DB"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("planner_core.config._load_opencode_config", lambda: {})
    (tmp_path / ".env").write_text(
        "AGENT_SWARM_SERVER=http://from-env\nAGENT_SWARM_API_KEY=as_z\n", encoding="utf-8"
    )
    s = load_settings(tmp_path)
    assert s.server == "http://from-env"
    assert s.api_key == "as_z"
    assert Path(s.db_path) == tmp_path / "data" / "planner.db"
