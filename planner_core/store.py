"""SQLite 仓储层（短事务，不跨 await 持连接）。"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import db as dbmod
from .models import Goal, Task


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _row_to_goal(row) -> Goal:
    return Goal(
        id=row["id"],
        title=row["title"],
        description=row["description"] or "",
        priority=row["priority"] or 0,
        deadline=row["deadline"] or "",
        success_criteria=row["success_criteria"] or "",
        status=row["status"] or "active",
        plan_status=(row["plan_status"] if "plan_status" in row.keys() else None) or "draft",
        plan_rev=int((row["plan_rev"] if "plan_rev" in row.keys() else 0) or 0),
        criteria_confirmed=int((row["criteria_confirmed"] if "criteria_confirmed" in row.keys() else 0) or 0),
        expert_workspace_id=(row["expert_workspace_id"] if "expert_workspace_id" in row.keys() else None) or "",
        expert_name=(row["expert_name"] if "expert_name" in row.keys() else None) or "",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


def _row_to_task(row, deps: list[str] | None = None) -> Task:
    return Task(
        id=row["id"],
        goal_id=row["goal_id"],
        parent_id=row["parent_id"] or "",
        title=row["title"],
        description=row["description"] or "",
        status=row["status"] or "pending",
        assigned_agent=row["assigned_agent"] or "",
        execution_spec=row["execution_spec"] or "{}",
        acceptance_type=row["acceptance_type"] or "auto",
        acceptance_result=row["acceptance_result"] or "",
        retry_count=row["retry_count"] or 0,
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
        depends_on=deps or [],
    )


class Store:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)

    # ---------------------------------------------------------------- goals
    def add_goal(
        self,
        title: str,
        description: str = "",
        priority: int = 0,
        deadline: str = "",
        success_criteria: str = "",
        expert_workspace_id: str = "",
        expert_name: str = "",
    ) -> Goal:
        now = dbmod.utcnow()
        gid = new_id("goal")
        conn = dbmod.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO goals (id,title,description,priority,deadline,"
                "success_criteria,status,plan_status,criteria_confirmed,"
                "expert_workspace_id,expert_name,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (gid, title, description, priority, deadline, success_criteria,
                 "active", "draft", 0, expert_workspace_id, expert_name, now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_goal(gid)  # type: ignore[return-value]

    def get_goal(self, goal_id: str) -> Goal | None:
        conn = dbmod.connect(self.db_path)
        try:
            row = conn.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
            return _row_to_goal(row) if row else None
        finally:
            conn.close()

    def list_goals(self) -> list[Goal]:
        conn = dbmod.connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM goals ORDER BY priority DESC, created_at DESC"
            ).fetchall()
            return [_row_to_goal(r) for r in rows]
        finally:
            conn.close()

    def set_goal_status(self, goal_id: str, status: str) -> None:
        conn = dbmod.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE goals SET status=?, updated_at=? WHERE id=?",
                (status, dbmod.utcnow(), goal_id),
            )
            conn.commit()
        finally:
            conn.close()

    def set_goal_plan_status(self, goal_id: str, plan_status: str) -> None:
        conn = dbmod.connect(self.db_path)
        try:
            if plan_status == "draft":
                # 进入 draft（初次拆解 / 重新拆解）→ plan_rev 自增，作为 notify 幂等键成分
                conn.execute(
                    "UPDATE goals SET plan_status=?, plan_rev=plan_rev+1, updated_at=? WHERE id=?",
                    (plan_status, dbmod.utcnow(), goal_id),
                )
            else:
                conn.execute(
                    "UPDATE goals SET plan_status=?, updated_at=? WHERE id=?",
                    (plan_status, dbmod.utcnow(), goal_id),
                )
            conn.commit()
        finally:
            conn.close()

    def delete_goal(self, goal_id: str) -> bool:
        """硬删除目标（tasks/task_deps/executions 级联删除）。返回是否删到。"""
        conn = dbmod.connect(self.db_path)
        try:
            cur = conn.execute("DELETE FROM goals WHERE id=?", (goal_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def set_goal_expert(self, goal_id: str, expert_workspace_id: str, expert_name: str = "") -> None:
        conn = dbmod.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE goals SET expert_workspace_id=?, expert_name=?, updated_at=? WHERE id=?",
                (expert_workspace_id, expert_name, dbmod.utcnow(), goal_id),
            )
            conn.commit()
        finally:
            conn.close()

    def update_goal(self, goal_id: str, **fields: object) -> None:
        allowed = {"title", "description", "priority", "deadline", "success_criteria",
                   "status", "plan_status", "criteria_confirmed",
                   "expert_workspace_id", "expert_name"}
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not sets:
            return
        cols = ", ".join(f"{k}=?" for k in sets)
        conn = dbmod.connect(self.db_path)
        try:
            conn.execute(
                f"UPDATE goals SET {cols}, updated_at=? WHERE id=?",
                (*sets.values(), dbmod.utcnow(), goal_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ---------------------------------------------------------------- tasks
    def add_task(
        self,
        goal_id: str,
        title: str,
        description: str = "",
        depends_on: list[str] | None = None,
        assigned_agent: str = "",
        acceptance_type: str = "auto",
        execution_spec: dict | None = None,
        parent_id: str = "",
    ) -> Task:
        now = dbmod.utcnow()
        tid = new_id("task")
        conn = dbmod.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO tasks (id,goal_id,parent_id,title,description,status,"
                "assigned_agent,execution_spec,acceptance_type,acceptance_result,"
                "retry_count,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, goal_id, parent_id, title, description, "pending",
                 assigned_agent, json.dumps(execution_spec or {}, ensure_ascii=False),
                 acceptance_type, "", 0, now, now),
            )
            for dep in depends_on or []:
                conn.execute(
                    "INSERT OR IGNORE INTO task_deps (task_id,depends_on) VALUES (?,?)",
                    (tid, dep),
                )
            conn.commit()
        finally:
            conn.close()
        return self.get_task(tid)  # type: ignore[return-value]

    def add_dependency(self, task_id: str, depends_on: str) -> None:
        conn = dbmod.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO task_deps (task_id,depends_on) VALUES (?,?)",
                (task_id, depends_on),
            )
            conn.commit()
        finally:
            conn.close()

    def get_task(self, task_id: str) -> Task | None:
        conn = dbmod.connect(self.db_path)
        try:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                return None
            deps = [
                r["depends_on"]
                for r in conn.execute(
                    "SELECT depends_on FROM task_deps WHERE task_id=?", (task_id,)
                ).fetchall()
            ]
            return _row_to_task(row, deps)
        finally:
            conn.close()

    def delete_tasks(self, goal_id: str) -> int:
        """删除目标下所有任务（task_deps/executions 级联删除）。返回删除数。"""
        conn = dbmod.connect(self.db_path)
        try:
            cur = conn.execute("DELETE FROM tasks WHERE goal_id=?", (goal_id,))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def list_tasks(self, goal_id: str) -> list[Task]:
        conn = dbmod.connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE goal_id=? ORDER BY created_at ASC",
                (goal_id,),
            ).fetchall()
            dep_rows = conn.execute(
                "SELECT task_id, depends_on FROM task_deps WHERE task_id IN "
                "(SELECT id FROM tasks WHERE goal_id=?)",
                (goal_id,),
            ).fetchall()
            deps: dict[str, list[str]] = {}
            for r in dep_rows:
                deps.setdefault(r["task_id"], []).append(r["depends_on"])
            return [_row_to_task(r, deps.get(r["id"], [])) for r in rows]
        finally:
            conn.close()

    def set_task_status(self, task_id: str, status: str, acceptance_result: str | None = None) -> None:
        conn = dbmod.connect(self.db_path)
        try:
            if acceptance_result is None:
                conn.execute(
                    "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                    (status, dbmod.utcnow(), task_id),
                )
            else:
                conn.execute(
                    "UPDATE tasks SET status=?, acceptance_result=?, updated_at=? WHERE id=?",
                    (status, acceptance_result, dbmod.utcnow(), task_id),
                )
            conn.commit()
        finally:
            conn.close()

    def inc_retry(self, task_id: str) -> int:
        conn = dbmod.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE tasks SET retry_count=retry_count+1, updated_at=? WHERE id=?",
                (dbmod.utcnow(), task_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT retry_count FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            return int(row["retry_count"]) if row else 0
        finally:
            conn.close()

    def pending_notifications(self) -> list[dict]:
        """计算当前"应发未发"的人工待办提醒（notify 边沿帧）。

        两类：
        - plan_approval：`active` 目标 `plan_status=draft` 且任务数 > 0；键 plan:<gid>:<plan_rev>
        - task_acceptance：`acceptance_type=manual` 的任务 status=waiting_human；键 accept:<tid>:<retry>
        已在 `notified` 表中的键跳过（保证处理前只提醒一次）。
        """
        now = dbmod.utcnow()
        out: list[dict] = []
        conn = dbmod.connect(self.db_path)
        try:
            notified = {r["key"] for r in conn.execute("SELECT key FROM notified").fetchall()}
            for g in conn.execute(
                "SELECT id,title,plan_status,plan_rev FROM goals WHERE status='active'"
            ).fetchall():
                if (g["plan_status"] or "draft") != "draft":
                    continue
                n = conn.execute(
                    "SELECT COUNT(*) AS n FROM tasks WHERE goal_id=?", (g["id"],)
                ).fetchone()["n"]
                if not n:
                    continue
                rev = int(g["plan_rev"] or 0)
                key = f"plan:{g['id']}:{rev}"
                if key in notified:
                    continue
                gtitle = g["title"] or ""
                out.append({
                    "kind": "plan_approval",
                    "key": key,
                    "goal_id": g["id"],
                    "goal_title": gtitle,
                    "plan_rev": rev,
                    "task_id": "",
                    "title": f"拆解待审批：{gtitle}",
                    "detail": f"共 {n} 个任务，等待人工『通过拆解』或『重新拆解』",
                    "created_at": now,
                })
            for t in conn.execute(
                "SELECT id,goal_id,title,retry_count FROM tasks "
                "WHERE status='waiting_human' AND acceptance_type='manual'"
            ).fetchall():
                attempt = int(t["retry_count"] or 0)
                key = f"accept:{t['id']}:{attempt}"
                if key in notified:
                    continue
                grows = conn.execute("SELECT title FROM goals WHERE id=?", (t["goal_id"],)).fetchone()
                gtitle = (grows["title"] if grows else "") or ""
                ttitle = t["title"] or ""
                out.append({
                    "kind": "task_acceptance",
                    "key": key,
                    "goal_id": t["goal_id"],
                    "goal_title": gtitle,
                    "task_id": t["id"],
                    "task_title": ttitle,
                    "attempt": attempt,
                    "title": f"人工验收待处理：{ttitle}",
                    "detail": f"目标《{gtitle}》 · 等待人工验收",
                    "created_at": now,
                })
            return out
        finally:
            conn.close()

    def mark_notified(self, key: str, kind: str = "", goal_id: str = "", task_id: str = "") -> None:
        """记录某待办通知已成功发出（幂等，成功 send 后调用）。"""
        conn = dbmod.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO notified (key,kind,goal_id,task_id,notified_at) "
                "VALUES (?,?,?,?,?)",
                (key, kind, goal_id, task_id, dbmod.utcnow()),
            )
            conn.commit()
        finally:
            conn.close()

    def add_execution(
        self,
        task_id: str,
        agent: str = "",
        input_: str = "",
        output: str = "",
        anchor: str = "",
        status: str = "done",
    ) -> str:
        now = dbmod.utcnow()
        eid = new_id("exec")
        conn = dbmod.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO executions (id,task_id,agent,input,output,anchor,status,"
                "started_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (eid, task_id, agent, input_, output, anchor, status, now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return eid

    def list_executions(self, task_id: str) -> list:
        conn = dbmod.connect(self.db_path)
        try:
            return conn.execute(
                "SELECT * FROM executions WHERE task_id=? ORDER BY started_at DESC",
                (task_id,),
            ).fetchall()
        finally:
            conn.close()

    # ---------------------------------------------------------------- 调度
    def refresh_ready(self, goal_id: str) -> list[str]:
        """把依赖已全部 done 的 pending 任务提升为 ready，返回新提升的 id 列表。"""
        tasks = {t.id: t for t in self.list_tasks(goal_id)}
        promoted: list[str] = []
        conn = dbmod.connect(self.db_path)
        try:
            for t in tasks.values():
                if t.status != "pending":
                    continue
                if all(tasks.get(d) and tasks[d].status == "done" for d in t.depends_on):
                    conn.execute(
                        "UPDATE tasks SET status='ready', updated_at=? WHERE id=?",
                        (dbmod.utcnow(), t.id),
                    )
                    promoted.append(t.id)
            conn.commit()
        finally:
            conn.close()
        return promoted

    # ---------------------------------------------------------------- 幂等
    def record_operation(self, op_id: str, type_: str, payload: dict | str) -> bool:
        """记录操作；若已存在返回 False（表示重复，应跳过）。payload 用作去重键 + 结果存储。"""
        conn = dbmod.connect(self.db_path)
        try:
            exists = conn.execute(
                "SELECT 1 FROM operations WHERE op_id=?", (op_id,)
            ).fetchone()
            if exists:
                return False
            conn.execute(
                "INSERT INTO operations (op_id,type,payload,processed_at) VALUES (?,?,?,?)",
                (
                    op_id,
                    type_,
                    payload if isinstance(payload, str)
                    else json.dumps(payload, ensure_ascii=False),
                    dbmod.utcnow(),
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def get_operation(self, op_id: str):
        conn = dbmod.connect(self.db_path)
        try:
            return conn.execute(
                "SELECT * FROM operations WHERE op_id=?", (op_id,)
            ).fetchone()
        finally:
            conn.close()

    def set_operation_result(self, op_id: str, result: dict | str) -> None:
        conn = dbmod.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE operations SET payload=?, processed_at=? WHERE op_id=?",
                (
                    result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                    dbmod.utcnow(),
                    op_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # ---------------------------------------------------------------- 桥接
    def link_platform_task(
        self,
        platform_task_id: str,
        local_kind: str,
        local_id: str,
        direction: str = "out",
        caller: str = "",
        status: str = "",
    ) -> None:
        conn = dbmod.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO platform_tasks "
                "(platform_task_id,local_kind,local_id,direction,caller,status,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (platform_task_id, local_kind, local_id, direction, caller, status,
                 dbmod.utcnow()),
            )
            conn.commit()
        finally:
            conn.close()

    def get_platform_task(self, platform_task_id: str):
        conn = dbmod.connect(self.db_path)
        try:
            return conn.execute(
                "SELECT * FROM platform_tasks WHERE platform_task_id=?",
                (platform_task_id,),
            ).fetchone()
        finally:
            conn.close()

    def update_platform_task_status(self, platform_task_id: str, status: str) -> None:
        conn = dbmod.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE platform_tasks SET status=? WHERE platform_task_id=?",
                (status, platform_task_id),
            )
            conn.commit()
        finally:
            conn.close()

    def platform_tasks_for_local(self, local_kind: str, local_id: str) -> list:
        conn = dbmod.connect(self.db_path)
        try:
            return conn.execute(
                "SELECT * FROM platform_tasks WHERE local_kind=? AND local_id=?",
                (local_kind, local_id),
            ).fetchall()
        finally:
            conn.close()
