"""SQLite 连接与建表。

约定：一律使用短连接（每次操作开/关），避免长时间持有连接；时间统一 UTC。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    priority INTEGER DEFAULT 0,
    deadline TEXT DEFAULT '',
    success_criteria TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    plan_status TEXT DEFAULT 'draft',
    expert_workspace_id TEXT DEFAULT '',
    expert_name TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    parent_id TEXT DEFAULT '',
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    assigned_agent TEXT DEFAULT '',
    execution_spec TEXT DEFAULT '{}',
    acceptance_type TEXT DEFAULT 'auto',
    acceptance_result TEXT DEFAULT '',
    retry_count INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS task_deps (
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, depends_on)
);

CREATE TABLE IF NOT EXISTS executions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent TEXT DEFAULT '',
    input TEXT DEFAULT '',
    output TEXT DEFAULT '',
    anchor TEXT DEFAULT '',
    status TEXT DEFAULT '',
    started_at TEXT,
    finished_at TEXT
);

-- 幂等：平台操作 / 本地命令去重
CREATE TABLE IF NOT EXISTS operations (
    op_id TEXT PRIMARY KEY,
    type TEXT DEFAULT '',
    payload TEXT DEFAULT '',
    processed_at TEXT
);

-- A2A 平台任务 ↔ 本地实体 桥接
CREATE TABLE IF NOT EXISTS platform_tasks (
    platform_task_id TEXT PRIMARY KEY,
    local_kind TEXT DEFAULT '',   -- goal | task | nudge | ...
    local_id TEXT DEFAULT '',
    direction TEXT DEFAULT '',    -- in | out
    caller TEXT DEFAULT '',
    status TEXT DEFAULT '',
    created_at TEXT
);

-- input-required 路由（question/permission 应答）
CREATE TABLE IF NOT EXISTS pending_inputs (
    request_id TEXT PRIMARY KEY,
    platform_task_id TEXT DEFAULT '',
    local_task_id TEXT DEFAULT '',
    kind TEXT DEFAULT '',
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_goal ON tasks(goal_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_deps_task ON task_deps(task_id);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | str) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """轻量迁移：旧库补充新增列（幂等）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(goals)").fetchall()}
    if "plan_status" not in cols:
        conn.execute("ALTER TABLE goals ADD COLUMN plan_status TEXT DEFAULT 'draft'")
    if "expert_workspace_id" not in cols:
        conn.execute("ALTER TABLE goals ADD COLUMN expert_workspace_id TEXT DEFAULT ''")
    if "expert_name" not in cols:
        conn.execute("ALTER TABLE goals ADD COLUMN expert_name TEXT DEFAULT ''")
