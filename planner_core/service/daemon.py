"""后台守护：订阅平台事件 + 周期性调度（提升就绪 / 按需注入提示词）。

注意：默认会真的经 A2A 网关注入提示词；`send=False` 只观察不注入。
"""

from __future__ import annotations

import asyncio
import logging

from ..config import Settings
from ..platform import observer
from .orchestrator import PlannerService

log = logging.getLogger("planner.daemon")


class PlannerDaemon:
    def __init__(self, settings: Settings, send: bool = True, tick_interval: float = 30.0):
        self.settings = settings
        self.send = send
        self.tick_interval = tick_interval
        self.svc = PlannerService(settings)
        self._inflight: set[str] = set()

    async def run(self) -> None:
        self.svc.init()
        log.info("daemon 启动 send=%s tick=%ss ws=%s", self.send, self.tick_interval, self.settings.workspace_id)
        from ..platform import planner_ws

        await asyncio.gather(
            self._observe(),
            self._tick_loop(),
            planner_ws.run(self.settings, self.svc, state_interval=self.settings.ws_state_interval),
        )

    # ---------------------------------------------------------------- 观察
    async def _observe(self) -> None:
        # 通配订阅：planner 自己 + 派发出去的 worker 工作区都在本用户名下，
        # 这样才能收到 worker 任务的终态帧。
        async for msg in observer.stream(self.settings, workspace_id="*"):
            try:
                await asyncio.to_thread(self._handle_frame, msg)
            except Exception as e:  # noqa: BLE001
                log.warning("处理观察帧失败：%s", e)

    def _handle_frame(self, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype == "task":
            task = msg.get("task") or {}
            self._ingest(str(task.get("id") or ""), (task.get("status") or {}).get("state"))
        elif mtype == "event":
            payload = msg.get("payload") or {}
            if payload.get("kind") == "status-update":
                self._ingest(payload.get("taskId"), (payload.get("status") or {}).get("state"))

    def _ingest(self, platform_task_id: str | None, state: str | None) -> None:
        if not platform_task_id or not state:
            return
        row = self.svc.store.get_platform_task(platform_task_id)
        if row is None:
            return
        self.svc.store.update_platform_task_status(platform_task_id, state)
        # worker 任务终态 → 回写本地任务
        if row["local_kind"] != "task" or not row["local_id"]:
            return
        tid = row["local_id"]
        if state == "completed":
            self.svc.apply_acceptance(tid)
        elif state in ("failed", "canceled"):
            self.svc.store.set_task_status(tid, "failed")
            self.svc.store.add_execution(tid, agent="worker", anchor=f"platform_task={platform_task_id}", status="failed")
        elif state == "input-required":
            self.svc.store.set_task_status(tid, "waiting_human")

    # ---------------------------------------------------------------- 调度
    async def _tick_loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception as e:  # noqa: BLE001
                log.warning("tick 失败：%s", e)
            await asyncio.sleep(self.tick_interval)

    async def _tick(self) -> None:
        for goal in self.svc.list_goals():
            if goal.status != "active":
                continue
            self.svc.recover(goal.id)
            self.svc.refresh_ready(goal.id)
            if not self.send or goal.id in self._inflight:
                continue
            if self._needs_attention(goal.id):
                self._inflight.add(goal.id)
                asyncio.create_task(self._nudge(goal.id))

    def _needs_attention(self, goal_id: str) -> bool:
        tasks = self.svc.store.list_tasks(goal_id)
        if not tasks:
            return True  # 尚未拆解
        return any(t.status in ("ready", "blocked", "failed", "waiting_human") for t in tasks)

    async def _nudge(self, goal_id: str) -> None:
        try:
            result = await self.svc.nudge(goal_id, send=True)
            log.info("nudge %s -> sent=%s task_id=%s", goal_id, result.get("sent"), result.get("task_id"))
        except Exception as e:  # noqa: BLE001
            log.warning("nudge %s 失败：%s", goal_id, e)
        finally:
            self._inflight.discard(goal_id)
