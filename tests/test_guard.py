from planner_core.guard import cwd_within, guard, planner_marker_ok, read_role


def _write_md(root, role="planner"):
    d = root / ".agent_swarm"
    d.mkdir(parents=True, exist_ok=True)
    (d / "workspace.md").write_text(
        f"WORKSPACE_ID: w1\nROLE: {role}\nPURPOSE: x\n", encoding="utf-8"
    )


def test_marker_ok(tmp_path):
    _write_md(tmp_path, "planner")
    assert read_role(tmp_path) == "planner"
    assert planner_marker_ok(tmp_path) == (True, "")


def test_marker_missing_file(tmp_path):
    ok, why = planner_marker_ok(tmp_path)
    assert ok is False and "workspace.md" in why


def test_marker_wrong_role(tmp_path):
    _write_md(tmp_path, "agent")
    ok, why = planner_marker_ok(tmp_path)
    assert ok is False and "不是 planner" in why


def test_cwd_within(tmp_path):
    child = tmp_path / "sub"
    child.mkdir()
    assert cwd_within(tmp_path, tmp_path) is True
    assert cwd_within(tmp_path, child) is True
    assert cwd_within(tmp_path, tmp_path.parent) is False


def test_guard_combined(tmp_path):
    _write_md(tmp_path, "planner")
    assert guard(tmp_path, tmp_path)[0] is True
    # 从别处启动 → 拒绝
    other = tmp_path.parent / "elsewhere"
    other.mkdir()
    ok, why = guard(tmp_path, other)
    assert ok is False and "不在 planner 仓库" in why
