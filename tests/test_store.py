import pytest

from planner_core.store import Store


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "planner.db")
    from planner_core.db import init_db

    init_db(tmp_path / "planner.db")
    return s


def test_goal_and_task_roundtrip(store):
    goal = store.add_goal("做 MVP", priority=1)
    assert store.get_goal(goal.id).title == "做 MVP"

    t1 = store.add_task(goal.id, "搭骨架")
    t2 = store.add_task(goal.id, "写测试", depends_on=[t1.id])
    assert store.get_task(t2.id).depends_on == [t1.id]


def test_refresh_ready_promotes_when_deps_done(store):
    goal = store.add_goal("g")
    a = store.add_task(goal.id, "a")
    b = store.add_task(goal.id, "b", depends_on=[a.id])
    assert store.refresh_ready(goal.id) == [a.id]
    store.set_task_status(a.id, "done")
    assert store.refresh_ready(goal.id) == [b.id]


def test_record_operation_is_idempotent(store):
    assert store.record_operation("op1", "goal.create", {"x": 1}) is True
    assert store.record_operation("op1", "goal.create", {"x": 1}) is False


def test_link_platform_task(store):
    store.link_platform_task("pt1", "goal", "g1", "out", caller="planner-core")
    row = store.get_platform_task("pt1")
    assert row["local_id"] == "g1"
