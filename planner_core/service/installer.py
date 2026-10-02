"""安装/常驻/自检的纯逻辑 + 平台产物生成。

- `.env` 读写（保留注释与顺序，只改/追加指定键）
- 各平台开机自启产物：XDG autostart / systemd（Linux）、launchd（macOS）、注册表 Run 键 + 启动包装（Windows）
- `setup` 写配置、`doctor` 静态预检

CLI 侧（`planner setup|doctor|service`）调用本模块；产物生成是纯函数，便于单测。
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE_NAME = "agent-swarm-planner"
DEFAULT_SERVER = "http://127.0.0.1:8700"


# ---------------------------------------------------------------- 基础
def detect_os() -> str:
    p = platform.system().lower()
    if p.startswith("linux"):
        return "linux"
    if p == "darwin":
        return "macos"
    if p.startswith("windows"):
        return "windows"
    return p


def mask_key(key: str) -> str:
    return (key[:7] + "..." + key[-4:]) if len(key) > 12 else ("(未设置)" if not key else "(已设置)")


def resolve_serve_command() -> str:
    """返回用于自启的 serve 命令（优先 pipx 生成的 `planner`，否则 `python -m`）。"""
    exe = shutil.which("planner")
    if exe:
        return f'"{exe}" serve'
    return f'"{sys.executable}" -m planner_core serve'


def update_dotenv_text(text: str, updates: dict[str, str]) -> str:
    """就地更新 .env 文本：已有键改值，缺失键追加；保留注释与顺序。"""
    lines = text.splitlines()
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)
    if remaining:
        if out and out[-1].strip():
            out.append("")
        out.append("# 由 planner setup 写入")
        for k, v in remaining.items():
            out.append(f"{k}={v}")
    return "\n".join(out) + ("\n" if out else "")


def upsert_dotenv(path: Path | str, updates: dict[str, str]) -> Path:
    p = Path(path)
    existing = p.read_text(encoding="utf-8") if p.is_file() else ""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(update_dotenv_text(existing, updates), encoding="utf-8")
    return p


# ---------------------------------------------------------------- 产物生成
def systemd_unit(*, serve_cmd: str, workdir: str, env_file: str = "",
                 name: str = SERVICE_NAME, description: str = "agent-swarm planner-core daemon") -> str:
    lines = [
        "[Unit]",
        f"Description={description}",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={workdir}",
    ]
    if env_file:
        lines.append(f"EnvironmentFile={env_file}")
    lines += [
        f"ExecStart={serve_cmd}",
        "Restart=on-failure",
        "RestartSec=5",
        "",
        "[Install]",
        "WantedBy=default.target",
    ]
    return "\n".join(lines) + "\n"


def xdg_autostart(*, serve_cmd: str, workdir: str, name: str = SERVICE_NAME,
                  description: str = "agent-swarm planner-core daemon") -> str:
    """XDG 登录自启 .desktop（~/.config/autostart/）。"""
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={name}\n"
        f"Comment={description}\n"
        f"Exec={serve_cmd}\n"
        f"Path={workdir}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def launchd_plist(*, serve_cmd: str, workdir: str, name: str = SERVICE_NAME,
                  log_dir: str = "") -> str:
    argv = [part for part in serve_cmd.replace('"', "").split(" ") if part]
    args_xml = "\n".join(f"    <string>{a}</string>" for a in argv)
    log_out = f"{log_dir}/serve.out.log" if log_dir else "/tmp/agent-swarm-planner.out.log"
    log_err = f"{log_dir}/serve.err.log" if log_dir else "/tmp/agent-swarm-planner.err.log"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f"  <key>Label</key><string>{name}</string>\n"
        "  <key>ProgramArguments</key>\n  <array>\n"
        f"{args_xml}\n  </array>\n"
        f"  <key>WorkingDirectory</key><string>{workdir}</string>\n"
        "  <key>RunAtLoad</key><true/>\n"
        "  <key>KeepAlive</key><true/>\n"
        f"  <key>StandardOutPath</key><string>{log_out}</string>\n"
        f"  <key>StandardErrorPath</key><string>{log_err}</string>\n"
        "</dict>\n</plist>\n"
    )


def windows_wrapper_cmd(*, serve_cmd: str, workdir: str, out_log: str, err_log: str) -> str:
    """开机/登录自启用：切到工作目录、后台起 serve 并落日志。"""
    return (
        "@echo off\r\n"
        f'cd /d "{workdir}"\r\n'
        f'{serve_cmd} >> "{out_log}" 2>> "{err_log}"\r\n'
    )


def windows_run_key(scope: str = "user") -> str:
    """自启注册表位置：用户级 HKCU、系统级 HKLM 的 Run 键。"""
    hive = "HKLM" if scope == "system" else "HKCU"
    return f"{hive}\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"


def windows_run_add_args(*, name: str, command: str, scope: str = "user") -> list[str]:
    """reg add：把启动命令写入 Run 键（登录时自启）。"""
    return ["reg", "add", windows_run_key(scope), "/v", name, "/t", "REG_SZ", "/d", command, "/f"]


def windows_run_delete_args(*, name: str, scope: str = "user") -> list[str]:
    return ["reg", "delete", windows_run_key(scope), "/v", name, "/f"]


def windows_run_query_args(*, name: str, scope: str = "user") -> list[str]:
    return ["reg", "query", windows_run_key(scope), "/v", name]


# ---------------------------------------------------------------- 服务计划（纯）
def service_plan(root: Path | str, *, osname: str | None = None, scope: str = "user",
                 name: str = SERVICE_NAME, serve_cmd: str | None = None) -> dict:
    """计算自启所需的文件与命令（不落盘、不执行）。"""
    root = Path(root).resolve()
    osname = osname or detect_os()
    serve_cmd = serve_cmd or resolve_serve_command()
    workdir = str(root)
    env_file = str(root / ".env")
    files: dict[str, str] = {}
    commands: list[list[str]] = []
    uninstall_files: list[str] = []
    uninstall_commands: list[list[str]] = []
    status_command: list[str] = []
    primary = ""

    if osname == "linux":
        if scope == "system":
            # 系统级：systemd 系统服务（XDG autostart 无系统级等价物）
            unit_dir = Path("/etc/systemd/system")
            unit_path = unit_dir / f"{name}.service"
            primary = str(unit_path)
            files[str(unit_path)] = systemd_unit(serve_cmd=serve_cmd, workdir=workdir,
                                                 env_file=env_file, name=name)
            commands = [["systemctl", "daemon-reload"], ["systemctl", "enable", "--now", f"{name}.service"]]
            uninstall_files = [str(unit_path)]
            uninstall_commands = [["systemctl", "disable", "--now", f"{name}.service"],
                                  ["systemctl", "daemon-reload"]]
            status_command = ["systemctl", "is-active", f"{name}.service"]
        else:
            # 用户级：XDG autostart（登录桌面会话时由桌面环境拉起）
            desktop_path = Path.home() / ".config" / "autostart" / f"{name}.desktop"
            primary = str(desktop_path)
            files[str(desktop_path)] = xdg_autostart(serve_cmd=serve_cmd, workdir=workdir, name=name)
            commands = []          # 下次登录生效；无系统命令
            uninstall_files = [str(desktop_path)]
            uninstall_commands = []
            status_command = []    # 用文件是否存在判断
    elif osname == "macos":
        agent_dir = Path.home() / "Library" / "LaunchAgents"
        plist_path = agent_dir / f"{name}.plist"
        log_dir = str(Path.home() / "Library" / "Logs" / name)
        primary = str(plist_path)
        files[str(plist_path)] = launchd_plist(serve_cmd=serve_cmd, workdir=workdir,
                                               name=name, log_dir=log_dir)
        commands = [["launchctl", "load", "-w", str(plist_path)]]
        uninstall_files = [str(plist_path)]
        uninstall_commands = [["launchctl", "unload", "-w", str(plist_path)]]
        status_command = ["launchctl", "list", name]
    elif osname == "windows":
        wrapper = root / ".agent_swarm" / "serve.cmd"
        state = root / "data"
        primary = str(wrapper)
        files[str(wrapper)] = windows_wrapper_cmd(
            serve_cmd=serve_cmd, workdir=workdir,
            out_log=str(state / "serve.out.log"), err_log=str(state / "serve.err.log"),
        )
        commands = [windows_run_add_args(name=name, command=f'"{wrapper}"', scope=scope)]
        uninstall_commands = [windows_run_delete_args(name=name, scope=scope)]
        status_command = windows_run_query_args(name=name, scope=scope)
    else:
        raise RuntimeError(f"不支持的系统：{osname}")

    return {
        "os": osname, "scope": scope, "name": name,
        "primary": primary, "files": files, "commands": commands,
        "uninstall_files": uninstall_files, "uninstall_commands": uninstall_commands,
        "status_command": status_command,
        "serve_cmd": serve_cmd, "workdir": workdir,
    }


def _run(cmd: list[str]) -> dict:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
        return {"cmd": " ".join(cmd), "ok": p.returncode == 0,
                "out": (p.stdout or "").strip(), "err": (p.stderr or "").strip(),
                "returncode": p.returncode}
    except FileNotFoundError as e:
        return {"cmd": " ".join(cmd), "ok": False, "out": "", "err": str(e), "returncode": -1}


def install_service(root: Path | str, **kwargs) -> dict:
    plan = service_plan(root, **kwargs)
    written = []
    for path, content in plan["files"].items():
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        written.append(path)
    results = [_run(cmd) for cmd in plan["commands"]]
    return {"plan": plan, "written": written, "commands": results}


def uninstall_service(root: Path | str, **kwargs) -> dict:
    plan = service_plan(root, **kwargs)
    results = [_run(cmd) for cmd in plan["uninstall_commands"]]
    removed = []
    for path in plan["uninstall_files"]:
        p = Path(path)
        if p.exists():
            p.unlink()
            removed.append(path)
    return {"plan": plan, "removed": removed, "commands": results}


# ---------------------------------------------------------------- doctor 静态检查
def has_module(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def static_checks(settings) -> list[dict]:
    """不联网的预检：Python 版本、依赖、配置、DB 可写。每项 {name, ok, detail}。"""
    checks: list[dict] = []

    ok = sys.version_info >= (3, 11)
    checks.append({"name": "python", "ok": ok, "detail": platform.python_version()})

    for mod in ("httpx", "websockets"):
        checks.append({"name": f"dep.{mod}", "ok": has_module(mod),
                       "detail": "已安装" if has_module(mod) else "缺失（pip install -r requirements.txt）"})

    checks.append({"name": "config.server", "ok": bool(settings.server),
                   "detail": settings.server or "未设置（AGENT_SWARM_SERVER）"})
    checks.append({"name": "config.api_key", "ok": bool(settings.api_key),
                   "detail": mask_key(settings.api_key)})
    checks.append({"name": "config.workspace_id", "ok": bool(settings.workspace_id),
                   "detail": settings.workspace_id or "未设置（PLANNER_WORKSPACE_ID / .agent_swarm/workspace.md）"})

    db_ok, db_detail = True, str(settings.db_path)
    try:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        probe = settings.db_path.parent / ".planner_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:  # noqa: BLE001
        db_ok, db_detail = False, f"{settings.db_path}（不可写：{e}）"
    checks.append({"name": "db.writable", "ok": db_ok, "detail": db_detail})

    return checks


def format_checks(checks: list[dict]) -> str:
    lines = []
    for c in checks:
        mark = "OK  " if c["ok"] else "FAIL"
        lines.append(f"[{mark}] {c['name']:22} {c['detail']}")
    return "\n".join(lines)
