"""自动验收：按任务的 execution_spec.accept_command 跑命令并抓日志（anchor）。

不调用 LLM；命令、工作目录、超时都来自任务自身。
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass

from ..models import Task


@dataclass
class AcceptanceResult:
    ok: bool
    output: str
    duration: float

    @property
    def status(self) -> str:
        return "done" if self.ok else "failed"


def run_command(
    command: str, cwd: str | None = None, timeout: int = 300
) -> AcceptanceResult:
    """执行验收命令，返回 (是否通过, 合并输出, 耗时秒)。"""
    start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        return AcceptanceResult(False, f"[验收超时 {timeout}s]\n{out}", time.monotonic() - start)
    except OSError as e:
        return AcceptanceResult(False, f"[验收命令启动失败] {e}", time.monotonic() - start)
    output = proc.stdout or ""
    if proc.stderr:
        output += ("\n" if output else "") + proc.stderr
    return AcceptanceResult(proc.returncode == 0, output, time.monotonic() - start)


def acceptance_spec(task: Task) -> dict:
    """从 execution_spec(JSON) 提取验收配置。"""
    import json

    try:
        spec = json.loads(task.execution_spec or "{}")
    except ValueError:
        return {}
    return spec if isinstance(spec, dict) else {}


def run_acceptance(task: Task, default_cwd: str | None = None) -> AcceptanceResult:
    spec = acceptance_spec(task)
    command = str(spec.get("accept_command") or spec.get("command") or "").strip()
    if not command:
        return AcceptanceResult(False, "[未配置验收命令 accept_command]", 0.0)
    return run_command(command, cwd=spec.get("cwd") or default_cwd, timeout=int(spec.get("timeout") or 300))
