"""极简 agent_swarm MCP 客户端（Streamable HTTP，stateless）。

实测：`POST /mcp/` 直接发 `tools/call` 即可（无需 initialize，服务端 stateless）。
工具结果在 `result.content[0].text`（JSON 字符串）。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from ..config import Settings


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None, timeout: float = 60.0):
        self.settings = settings
        self.url = settings.server.rstrip("/") + "/mcp/"
        self.headers = {
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self._client = client
        self.timeout = timeout

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        body = {
            "jsonrpc": "2.0",
            "id": f"planner-{uuid.uuid4().hex[:12]}",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        if self._client is not None:
            resp = self._client.post(self.url, headers=self.headers, json=body)
        else:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(self.url, headers=self.headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise MCPError(f"{name}: {data['error']}")
        result = data.get("result") or {}
        if result.get("isError"):
            raise MCPError(f"{name}: {_content_text(result)}")
        return _parse_content(result)

    # ---------------------------------------------------------------- 便捷封装
    def list_workspaces(self, include_offline: bool = False) -> list[dict[str, Any]]:
        return self.call_tool("list_workspaces", {"include_offline": include_offline}).get("workspaces", [])

    def a2a_call(self, target: str, message: str, from_workspace: str, wait_seconds: int = 0) -> dict[str, Any]:
        return self.call_tool("a2a_call", {
            "target": target,
            "message": message,
            "from_workspace": from_workspace,
            "wait_seconds": wait_seconds,
        })

    def a2a_task(self, task_id: str) -> dict[str, Any]:
        return self.call_tool("a2a_task", {"task_id": task_id})

    def set_role(self, workspace_id: str, role: str = "planner") -> dict[str, Any]:
        return self.call_tool("update_info", {"workspace_id": workspace_id, "role": role})


def _content_text(result: dict[str, Any]) -> str:
    parts = result.get("content") or []
    return " ".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))


def _parse_content(result: dict[str, Any]) -> Any:
    text = _content_text(result)
    if not text:
        return {}
    try:
        return json.loads(text)
    except ValueError:
        return {"text": text}
