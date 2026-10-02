"""平台控制通道：core 主动连 `WS /ws/planner`，接收平台操作、推送状态快照。

协议见 docs/planner-platform-protocol.md。内网环境下 core 主动外连，平台无需访问 core 端口。
断线自动重连；周期性推送状态。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets

from ..config import Settings
from ..service.orchestrator import PlannerService

log = logging.getLogger("planner.planner_ws")


def ws_url(server: str, path: str) -> str:
    base = server.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):] + path
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):] + path
    return base + path


async def _send(ws, obj: dict[str, Any]) -> None:
    await ws.send(json.dumps(obj, ensure_ascii=False))


async def push_state(ws, service: PlannerService) -> None:
    state = service.state()
    state["workspace_id"] = service.settings.workspace_id
    from ..db import utcnow

    state["updated_at"] = utcnow()
    await _send(ws, {"type": "state", "payload": state})


async def flush_notifications(ws, service: PlannerService) -> None:
    """把"应发未发"的人工待办以 `notify` 边沿帧发出去；成功后才落 `notified`（见协议 §7）。"""
    try:
        pending = service.store.pending_notifications()
    except Exception as e:  # noqa: BLE001
        log.warning("计算待办通知失败：%s", e)
        return
    for payload in pending:
        payload = dict(payload)
        payload["workspace_id"] = service.settings.workspace_id
        try:
            await _send(ws, {"type": "notify", "payload": payload})
        except Exception:  # noqa: BLE001
            return  # WS 断开：不落键，下个 tick / 重连后补发
        service.store.mark_notified(
            payload["key"], payload.get("kind", ""),
            payload.get("goal_id", ""), payload.get("task_id", ""),
        )
        log.info("已推送待办通知 %s (%s)", payload["key"], payload.get("kind"))


async def _handle_op(ws, service: PlannerService, msg: dict[str, Any]) -> None:
    op_id = str(msg.get("op_id") or "")
    op = str(msg.get("op") or "")
    payload = msg.get("payload") or {}
    try:
        result = await service.handle_op(op, payload, op_id=op_id)
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    await _send(ws, {"type": "op_result", "op_id": op_id, **result})


async def run(settings: Settings, service: PlannerService | None = None, state_interval: float = 30.0) -> None:
    service = service or PlannerService(settings)
    service.init()
    url = ws_url(settings.server, settings.ws_path)
    while True:
        try:
            async with websockets.connect(url, ping_interval=None) as ws:
                await _send(ws, {"type": "hello", "apikey": settings.api_key,
                                 "workspace_id": settings.workspace_id})
                hello = json.loads(await ws.recv())
                if hello.get("type") != "hello_ok":
                    raise RuntimeError(f"hello failed: {hello}")
                log.info("planner ws 已连接 %s", url)
                await push_state(ws, service)
                await flush_notifications(ws, service)
                stop = asyncio.Event()

                async def _ticker() -> None:
                    while not stop.is_set():
                        await asyncio.sleep(state_interval)
                        try:
                            await push_state(ws, service)
                            await flush_notifications(ws, service)
                            await _send(ws, {"type": "ping"})
                        except Exception:  # noqa: BLE001
                            return

                ticker = asyncio.create_task(_ticker())
                try:
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except ValueError:
                            continue
                        mtype = msg.get("type")
                        if mtype == "op":
                            await _handle_op(ws, service, msg)
                            await push_state(ws, service)
                            await flush_notifications(ws, service)
                        # pong / hello 忽略
                finally:
                    stop.set()
                    ticker.cancel()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("planner ws 断开，5s 后重连：%s", e)
            await asyncio.sleep(5)
