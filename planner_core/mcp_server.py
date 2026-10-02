"""本地 MCP 状态接口（stdio，零依赖手写 JSON-RPC）。

让 planner agent（任意 MCP 客户端）读写确定性状态，而不用 shell 调 CLI：
  planner_get_state / planner_next_ready / planner_save_plan /
  planner_set_task_status / planner_add_goal / planner_record_execution /
  planner_run_acceptance

传输：stdio，按行分隔 JSON-RPC（MCP stdio 约定）。日志走 stderr。
"""

from __future__ import annotations

import json
import sys
from typing import Any

from .config import Settings, load_settings
from .service.orchestrator import PlannerService

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "agent-swarm-planner"
SERVER_VERSION = "0.1.0"


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "planner_get_state",
        "description": "读取 planner 状态：目标与任务树（不传 goal_id 返回全部）。",
        "inputSchema": _schema({"goal_id": {"type": "string"}}),
    },
    {
        "name": "planner_next_ready",
        "description": "提升就绪任务并返回当前可派发的任务列表。",
        "inputSchema": _schema({"goal_id": {"type": "string"}}, ["goal_id"]),
    },
    {
        "name": "planner_save_plan",
        "description": "写入目标的任务树。tasks 为数组，每项含 title，可选 temp_id/description/depends_on/assigned_agent/acceptance_type/execution_spec。",
        "inputSchema": _schema(
            {"goal_id": {"type": "string"}, "tasks": {"type": "array"}}, ["goal_id", "tasks"]
        ),
    },
    {
        "name": "planner_set_task_status",
        "description": "设置任务状态（pending/ready/running/done/failed/blocked/waiting_human）。",
        "inputSchema": _schema(
            {"task_id": {"type": "string"}, "status": {"type": "string"}, "result": {"type": "string"}},
            ["task_id", "status"],
        ),
    },
    {
        "name": "planner_add_goal",
        "description": "创建目标。",
        "inputSchema": _schema(
            {"title": {"type": "string"}, "description": {"type": "string"},
             "success_criteria": {"type": "string"}, "priority": {"type": "integer"}},
            ["title"],
        ),
    },
    {
        "name": "planner_record_execution",
        "description": "记录一次任务执行并更新任务状态。",
        "inputSchema": _schema(
            {"task_id": {"type": "string"}, "agent": {"type": "string"},
             "output": {"type": "string"}, "anchor": {"type": "string"},
             "status": {"type": "string"}},
            ["task_id"],
        ),
    },
    {
        "name": "planner_run_acceptance",
        "description": "执行任务 execution_spec.accept_command 自动验收并回写。",
        "inputSchema": _schema({"task_id": {"type": "string"}}, ["task_id"]),
    },
]


class PlannerTools:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.svc = PlannerService(settings)
        self.svc.init()

    def call(self, name: str, args: dict[str, Any]) -> Any:
        args = args or {}
        if name == "planner_get_state":
            return self.svc.state(args.get("goal_id") or None)
        if name == "planner_next_ready":
            return {"ready": self.svc.next_ready(args["goal_id"])}
        if name == "planner_save_plan":
            created = self.svc.apply_plan(args["goal_id"], {"tasks": args.get("tasks") or []})
            return {"created": [{"id": t.id, "title": t.title} for t in created]}
        if name == "planner_set_task_status":
            self.svc.store.set_task_status(args["task_id"], args["status"], args.get("result"))
            return {"ok": True}
        if name == "planner_add_goal":
            goal = self.svc.create_goal(
                title=args["title"],
                description=args.get("description") or "",
                success_criteria=args.get("success_criteria") or "",
                priority=int(args.get("priority") or 0),
            )
            return goal.__dict__
        if name == "planner_record_execution":
            return self.svc.record_execution(
                task_id=args["task_id"],
                agent=args.get("agent") or "",
                output=args.get("output") or "",
                anchor=args.get("anchor") or "",
                status=args.get("status") or "done",
            )
        if name == "planner_run_acceptance":
            return self.svc.run_acceptance(args["task_id"])
        raise ValueError(f"未知工具: {name}")


def handle_request(tools: PlannerTools, req: dict[str, Any]) -> dict[str, Any] | None:
    """处理一条 JSON-RPC 请求；通知（无 id）返回 None。"""
    method = req.get("method")
    req_id = req.get("id")
    if req_id is None:
        return None  # notification
    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    if method == "ping":
        return _ok(req_id, {})
    if method == "tools/list":
        return _ok(req_id, {"tools": TOOL_SPECS})
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            result = tools.call(name, args)
            text = json.dumps(result, ensure_ascii=False, default=str)
            return _ok(req_id, {"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:  # noqa: BLE001
            text = f"{type(e).__name__}: {e}"
            return _ok(req_id, {"content": [{"type": "text", "text": text}], "isError": True})
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"method not supported: {method}"},
    }


def _ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _write(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve(settings: Settings | None = None) -> None:
    settings = settings or load_settings()
    tools = PlannerTools(settings)
    print(f"[planner-mcp] ready (ws={settings.workspace_id}, db={settings.db_path})", file=sys.stderr, flush=True)
    for line in sys.stdin:
        line = line.lstrip("\ufeff").strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        resp = handle_request(tools, req)
        if resp is not None:
            _write(resp)


if __name__ == "__main__":
    serve()
