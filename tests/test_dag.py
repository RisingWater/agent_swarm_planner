from planner_core.engine import dag
from planner_core.models import Task


def _t(tid, deps=(), status="pending"):
    return Task(id=tid, goal_id="g", title=tid, status=status, depends_on=list(deps))


def test_topo_order_respects_deps():
    tasks = [_t("c", ["a", "b"]), _t("a"), _t("b", ["a"])]
    order = dag.topo_order(tasks)
    assert order.index("a") < order.index("b") < order.index("c")


def test_validate_rejects_missing_dep():
    import pytest

    with pytest.raises(dag.DagError):
        dag.validate([_t("a", ["ghost"])])


def test_validate_rejects_cycle():
    import pytest

    with pytest.raises(dag.DagError):
        dag.validate([_t("a", ["b"]), _t("b", ["a"])])


def test_ready_ids():
    tasks = [_t("a", status="done"), _t("b", ["a"]), _t("c", ["b"])]
    assert dag.ready_ids(tasks) == ["b"]
