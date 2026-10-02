"""本地 MCP 的启动防护：只对 planner 工作区开放。

stdio MCP 拿不到调用方身份，所以只能做**进程启动级**校验：
1. 进程 cwd 必须在 planner 仓库内（防止把全局配置装到别的项目后被误用）；
2. 仓库 `.agent_swarm/workspace.md` 必须带 `ROLE: planner` 标志。

没有这两道，任何连上该 MCP 的 agent 都能读写 planner 的库、甚至向外派单。
"""

from __future__ import annotations

from pathlib import Path


def read_role(root: Path | str) -> str:
    f = Path(root) / ".agent_swarm" / "workspace.md"
    if not f.is_file():
        return ""
    for raw in f.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.upper().startswith("ROLE:"):
            return line.split(":", 1)[1].strip()
    return ""


def planner_marker_ok(root: Path | str) -> tuple[bool, str]:
    """检查 planner 标志；返回 (是否通过, 原因)。"""
    f = Path(root) / ".agent_swarm" / "workspace.md"
    if not f.is_file():
        return False, f"缺少标志文件 {f}（先运行 `planner register`）"
    role = read_role(root)
    if role.lower() != "planner":
        return False, f"ROLE 不是 planner（当前 {role or '未设置'}）"
    return True, ""


def cwd_within(root: Path | str, cwd: Path | str | None = None) -> bool:
    """cwd 是否在 root 目录内（含相等）。"""
    root_p = Path(root).resolve()
    cwd_p = (Path(cwd) if cwd else Path.cwd()).resolve()
    return cwd_p == root_p or root_p in cwd_p.parents


def guard(root: Path | str, cwd: Path | str | None = None) -> tuple[bool, str]:
    ok, why = planner_marker_ok(root)
    if not ok:
        return False, why
    if not cwd_within(root, cwd):
        return False, f"当前目录 {Path(cwd or Path.cwd()).resolve()} 不在 planner 仓库 {Path(root).resolve()} 内"
    return True, ""
