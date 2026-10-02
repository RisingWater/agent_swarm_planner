"""配置加载。

优先级（高 → 低）：
1. 进程环境变量
2. 项目根 `.env`
3. `~/.config/opencode/agent-swarm.json`（serverUrl / apiKey）
4. `.agent_swarm/workspace.md` 的 `WORKSPACE_ID:` 行
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def project_root() -> Path:
    """本仓库根目录（planner_core 的上一级）。"""
    return Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> dict[str, str]:
    """极简 .env 解析（KEY=VALUE，忽略空行与 # 注释）。"""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _load_opencode_config() -> dict[str, str]:
    """读取 opencode 的 agent-swarm.json，作为 server/apikey 的兜底来源。"""
    cfg = Path.home() / ".config" / "opencode" / "agent-swarm.json"
    if not cfg.is_file():
        return {}
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return {
        "server": str(data.get("serverUrl") or ""),
        "api_key": str(data.get("apiKey") or ""),
    }


def _read_workspace_id(md_path: Path) -> str:
    """从 .agent_swarm/workspace.md 读取 WORKSPACE_ID: 行。"""
    if not md_path.is_file():
        return ""
    for raw in md_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.upper().startswith("WORKSPACE_ID:"):
            return line.split(":", 1)[1].strip()
    return ""


@dataclass
class Settings:
    server: str
    api_key: str
    workspace_id: str
    caller: str = "planner-core"
    db_path: Path = field(default_factory=lambda: project_root() / "data" / "planner.db")
    root: Path = field(default_factory=project_root)
    nudge_min_interval: int = 60
    max_retry: int = 3
    send_timeout: int = 600
    # 注入提示词的第 0 步：先压缩上下文，释放窗口再干活（可通过 env 覆盖）
    first_step: str = "先压缩/总结你自己的上下文（如 opencode 的 /compact），释放上下文窗口后再开始。"
    # 派给其它 agent 的固定前导（机械保证"先压缩上下文"这条派单规则）
    dispatch_preamble: str = "请先压缩/总结你的上下文，释放上下文窗口后再开始以下任务。"

    @property
    def a2a_url(self) -> str:
        return f"{self.server.rstrip('/')}/a2a/{self.workspace_id}"

    def validate(self) -> None:
        missing = []
        if not self.server:
            missing.append("AGENT_SWARM_SERVER")
        if not self.api_key:
            missing.append("AGENT_SWARM_API_KEY")
        if not self.workspace_id:
            missing.append("PLANNER_WORKSPACE_ID / .agent_swarm/workspace.md")
        if missing:
            raise SystemExit(
                "缺少配置：" + "、".join(missing) + "（见 .env.example）"
            )


def load_settings(root: Path | None = None) -> Settings:
    root = Path(root) if root else project_root()
    dotenv = _load_dotenv(root / ".env")
    oc = _load_opencode_config()

    def pick(*keys: str) -> str:
        for k in keys:
            v = os.environ.get(k) or dotenv.get(k)
            if v:
                return v
        return ""

    server = pick("AGENT_SWARM_SERVER") or oc.get("server", "")
    api_key = pick("AGENT_SWARM_API_KEY") or oc.get("api_key", "")
    workspace_id = pick("PLANNER_WORKSPACE_ID") or _read_workspace_id(
        root / ".agent_swarm" / "workspace.md"
    )
    db_path = pick("PLANNER_DB") or str(root / "data" / "planner.db")

    def as_int(key: str, default: int) -> int:
        raw = pick(key)
        try:
            return int(raw) if raw else default
        except ValueError:
            return default

    return Settings(
        server=server,
        api_key=api_key,
        workspace_id=workspace_id,
        caller=pick("PLANNER_CALLER") or "planner-core",
        db_path=Path(db_path),
        root=root,
        nudge_min_interval=as_int("PLANNER_NUDGE_MIN_INTERVAL", 60),
        max_retry=as_int("PLANNER_MAX_RETRY", 3),
        send_timeout=as_int("PLANNER_SEND_TIMEOUT", 600),
        first_step=pick("PLANNER_FIRST_STEP")
        or "先压缩/总结你自己的上下文（如 opencode 的 /compact），释放上下文窗口后再开始。",
        dispatch_preamble=pick("PLANNER_DISPATCH_PREAMBLE")
        or "请先压缩/总结你的上下文，释放上下文窗口后再开始以下任务。",
    )
