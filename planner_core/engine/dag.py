"""DAG 校验与拓扑排序（纯函数，便于单测）。"""

from __future__ import annotations

from ..models import Task


class DagError(ValueError):
    """任务树不是合法 DAG（依赖缺失或存在环）。"""


def validate(tasks: list[Task]) -> None:
    ids = {t.id for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            if dep not in ids:
                raise DagError(f"任务 {t.id} 依赖不存在的任务 {dep}")
            if dep == t.id:
                raise DagError(f"任务 {t.id} 不能依赖自身")
    topo_order(tasks)  # 有环会在此抛出


def topo_order(tasks: list[Task]) -> list[str]:
    """Kahn 拓扑排序，返回任务 id 顺序。"""
    indeg: dict[str, int] = {t.id: 0 for t in tasks}
    adj: dict[str, list[str]] = {t.id: [] for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            if dep not in indeg:
                raise DagError(f"任务 {t.id} 依赖不存在的任务 {dep}")
            indeg[t.id] += 1
            adj[dep].append(t.id)
    queue = [tid for tid, d in indeg.items() if d == 0]
    order: list[str] = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    if len(order) != len(tasks):
        raise DagError("任务树存在循环依赖")
    return order


def ready_ids(tasks: list[Task]) -> list[str]:
    """依赖全部 done 且自身 pending/ready 的任务 id。"""
    status = {t.id: t.status for t in tasks}
    out: list[str] = []
    for t in tasks:
        if t.status not in ("pending", "ready"):
            continue
        if all(status.get(d) == "done" for d in t.depends_on):
            out.append(t.id)
    return out
