from planner_core.engine import acceptance
from planner_core.models import Task


def test_run_command_success():
    r = acceptance.run_command("python -c \"print(1)\"")
    assert r.ok is True
    assert "1" in r.output
    assert r.status == "done"


def test_run_command_failure():
    r = acceptance.run_command("python -c \"import sys; sys.exit(3)\"")
    assert r.ok is False
    assert r.status == "failed"


def test_run_command_timeout():
    r = acceptance.run_command("python -c \"import time; time.sleep(5)\"", timeout=1)
    assert r.ok is False
    assert "超时" in r.output


def test_run_acceptance_uses_spec():
    task = Task(id="t", goal_id="g", title="t", execution_spec='{"accept_command": "python -c \\"print(42)\\""}')
    r = acceptance.run_acceptance(task)
    assert r.ok and "42" in r.output


def test_run_acceptance_without_command():
    task = Task(id="t", goal_id="g", title="t", execution_spec="{}")
    r = acceptance.run_acceptance(task)
    assert r.ok is False
    assert "accept_command" in r.output
