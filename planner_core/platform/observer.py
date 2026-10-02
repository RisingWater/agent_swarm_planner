"""Nexus 观察者：连 `/ws/nexus`（apikey hello），订阅自己工作区的事件流。

用途：planner-core 作为"非 agent 的旁观者"感知任务/监控/状态帧，用于驱动调度与
判断何时再次注入提示词。断线自动重连。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Callable

import websockets

from ..config import Settings

log = logging.getLogger("planner.observer")


def _ws_nexus_url(server: str) -> str:
    base = server.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):] + "/ws/nexus"
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):] + "/ws/nexus"
    return base + "/ws/nexus"


async def stream(
    settings: Settings,
    workspace_id: str | None = None,
    ping_interval: float = 25.0,
) -> AsyncIterator[dict[str, Any]]:
    """持续 yield 服务端推送的帧；自动重连 + 心跳。"""
    url = _ws_nexus_url(settings.server)
    subscribe_id = workspace_id or settings.workspace_id
    while True:
        try:
            async with websockets.connect(url, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "hello", "apikey": settings.api_key}))
                hello = json.loads(await ws.recv())
                if hello.get("type") != "hello_ok":
                    raise RuntimeError(f"hello failed: {hello}")
                await ws.send(json.dumps({"type": "subscribe", "workspace_id": subscribe_id}))
                stop = asyncio.Event()

                async def _ping() -> None:
                    while not stop.is_set():
                        await asyncio.sleep(ping_interval)
                        try:
                            await ws.send(json.dumps({"type": "ping"}))
                        except Exception:  # noqa: BLE001
                            return

                pinger = asyncio.create_task(_ping())
                try:
                    async for raw in ws:
                        try:
                            yield json.loads(raw)
                        except ValueError:
                            continue
                finally:
                    stop.set()
                    pinger.cancel()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("nexus ws 断开，5s 后重连：%s", e)
            await asyncio.sleep(5)


async def run(settings: Settings, on_message: Callable[[dict[str, Any]], None]) -> None:
    async for msg in stream(settings):
        try:
            on_message(msg)
        except Exception as e:  # noqa: BLE001
            log.warning("处理观察帧失败：%s", e)
