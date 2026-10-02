"""A2A 客户端：把提示词投递给 planner 工作区（自己发给自己）。

走原始 A2A 网关 `POST /a2a/{workspace_id}`（apikey 鉴权）——服务端只在 MCP 工具
`a2a_call` 里禁止自我派单，网关不拦，正好用于"Python 服务不是 agent 但能发给自己"。

- `message/send`  : 阻塞到任务终态，返回 A2A Task 对象
- `message/stream`: SSE 流式返回，逐帧 yield（可看 agent 的思考/工具/终态）
- `tasks/get`     : 查询任务
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..config import Settings


def _user_message(text: str) -> dict[str, Any]:
    return {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": f"msg-{uuid.uuid4().hex[:12]}",
    }


class A2AClient:
    def __init__(self, settings: Settings, timeout: float | None = None):
        self.settings = settings
        self.base = settings.server.rstrip("/")
        self.workspace_id = settings.workspace_id
        self.url = f"{self.base}/a2a/{self.workspace_id}"
        self.headers = {
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        }
        self.timeout = timeout if timeout is not None else float(settings.send_timeout)

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": f"planner-{uuid.uuid4().hex[:12]}",
            "method": method,
            "params": params,
        }

    async def send(self, text: str, caller: str | None = None) -> dict[str, Any]:
        """message/send：阻塞到终态，返回 task_obj。"""
        params = {
            "message": _user_message(text),
            "metadata": {"caller": caller or self.settings.caller},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(self.url, headers=self.headers, json=self._rpc("message/send", params))
            resp.raise_for_status()
            data = resp.json()
        if "error" in data:
            raise RuntimeError(f"A2A error: {data['error']}")
        return data.get("result") or {}

    async def send_stream(self, text: str, caller: str | None = None) -> AsyncIterator[dict[str, Any]]:
        """message/stream：SSE 逐帧 yield。"""
        params = {
            "message": _user_message(text),
            "metadata": {"caller": caller or self.settings.caller},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", self.url, headers=self.headers, json=self._rpc("message/stream", params)
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if not payload:
                        continue
                    try:
                        yield json.loads(payload)
                    except ValueError:
                        continue

    async def tasks_get(self, task_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.url, headers=self.headers, json=self._rpc("tasks/get", {"id": task_id})
            )
            resp.raise_for_status()
            data = resp.json()
        if "error" in data:
            raise RuntimeError(f"A2A error: {data['error']}")
        return data.get("result") or {}
