"""命令行入口：planner <子命令>。

示例：
  planner info
  planner init
  planner goal add "做一版 MVP" --desc "..." --criteria "..."
  planner task add <goal_id> "搭骨架" --agent <wid> --acceptance auto
  planner task set <task_id> ready
  planner plan show <goal_id>
  planner nudge <goal_id>            # 只打印提示词（dry-run）
  planner nudge <goal_id> --send     # 经 A2A 网关投递给 planner 工作区
  planner observe                    # 订阅 /ws/nexus 观察事件
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import load_settings
from .models import TASK_STATUSES
from .service.orchestrator import PlannerService


def _svc(args: argparse.Namespace) -> PlannerService:
    settings = load_settings()
    return PlannerService(settings)


def cmd_info(args: argparse.Namespace) -> int:
    s = load_settings()
    masked = (s.api_key[:7] + "..." + s.api_key[-4:]) if len(s.api_key) > 12 else "(未设置)"
    print("server      :", s.server or "(未设置)")
    print("api_key     :", masked)
    print("workspace_id:", s.workspace_id or "(未设置)")
    print("caller      :", s.caller)
    print("db_path     :", s.db_path)
    print("a2a_url     :", s.a2a_url)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    print("已初始化数据库:", svc.settings.db_path)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    print(svc.overview())
    return 0


def cmd_goal_add(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    goal = svc.create_goal(
        title=args.title,
        description=args.desc or "",
        priority=args.priority,
        deadline=args.deadline or "",
        success_criteria=args.criteria or "",
        expert_workspace_id=args.expert or "",
        expert_name=args.expert_name or "",
    )
    print(json.dumps(goal.__dict__, ensure_ascii=False, indent=2))
    return 0


def cmd_goal_set_expert(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    result = svc.set_expert(args.goal_id, args.workspace_id, args.name or "")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_goal_list(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    goals = svc.list_goals()
    if not goals:
        print("（暂无目标）")
        return 0
    for g in goals:
        print(f"[{g.id}] {g.status:>8}  P{g.priority}  {g.title}")
    return 0


def cmd_task_add(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    task = svc.add_task(
        goal_id=args.goal_id,
        title=args.title,
        description=args.desc or "",
        depends_on=args.depends_on or [],
        assigned_agent=args.agent or "",
        acceptance_type=args.acceptance,
        parent_id=args.parent or "",
    )
    print(json.dumps(task.__dict__, ensure_ascii=False, indent=2))
    return 0


def cmd_task_set(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    if args.status not in TASK_STATUSES:
        print(f"非法状态: {args.status}；可选 {TASK_STATUSES}", file=sys.stderr)
        return 2
    svc.store.set_task_status(args.task_id, args.status, args.result)
    print(f"{args.task_id} -> {args.status}")
    return 0


def cmd_plan_show(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    print(svc.status_text(args.goal_id))
    return 0


def cmd_plan_export(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    print(json.dumps(svc.export_goal(args.goal_id), ensure_ascii=False, indent=2))
    return 0


def cmd_plan_apply(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    raw = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    try:
        plan = json.loads(raw)
    except ValueError as e:
        print(f"计划不是合法 JSON: {e}", file=sys.stderr)
        return 2
    created = svc.apply_plan(args.goal_id, plan, replace=args.replace)
    print(f"已写入 {len(created)} 个任务:")
    for t in created:
        print(f"  - [{t.id}] {t.title}")
    svc.refresh_ready(args.goal_id)
    return 0


def cmd_plan_recover(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    actions = svc.recover(args.goal_id)
    if not actions:
        print("（无需恢复）")
        return 0
    for a in actions:
        print(f"  - {a['task_id']}: {a['action']}")
    return 0


def cmd_plan_markdown(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    print(svc.markdown(args.goal_id))
    return 0


def cmd_nudge(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    promoted = svc.refresh_ready(args.goal_id)
    if args.send and promoted:
        print(f"（已提升为 ready: {', '.join(promoted)}）")
    if not args.send:
        print(svc.build_nudge(args.goal_id))
        return 0
    settings = svc.settings
    settings.validate()
    result = asyncio.run(svc.nudge(args.goal_id, send=True, force=args.force))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_ping(args: argparse.Namespace) -> int:
    import websockets

    from .platform.mcp_client import MCPClient
    from .platform.planner_ws import ws_url

    settings = load_settings()
    settings.validate()
    try:
        ws = MCPClient(settings).list_workspaces(include_offline=True)
        me = next((w for w in ws if w.get("workspace_id") == settings.workspace_id), None)
        print(f"platform MCP : OK ({len(ws)} workspaces)")
        print(f"my workspace : {me.get('name') if me else '(未找到)'} role={(me or {}).get('role')}")
    except Exception as e:  # noqa: BLE001
        print("platform MCP : FAIL", e)

    async def _ws() -> None:
        url = ws_url(settings.server, settings.ws_path)
        try:
            async with websockets.connect(url, ping_interval=None) as sock:
                await sock.send(json.dumps({"type": "hello", "apikey": settings.api_key,
                                            "workspace_id": settings.workspace_id}))
                hello = json.loads(await asyncio.wait_for(sock.recv(), timeout=5))
                print(f"control WS   : {hello.get('type')} ({settings.ws_path})")
        except Exception as e:  # noqa: BLE001
            print("control WS   : FAIL", e)

    asyncio.run(_ws())
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    print(svc.report(args.goal_id, args.task or ""))
    return 0


def cmd_workspaces(args: argparse.Namespace) -> int:
    from .platform.mcp_client import MCPClient

    settings = load_settings()
    settings.validate()
    for w in MCPClient(settings).list_workspaces(include_offline=args.all):
        print(f"{w.get('workspace_id')}  {str(w.get('role') or 'agent'):8} "
              f"{str(w.get('status') or ''):8} {w.get('name')}")
    return 0


def cmd_dispatch(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    svc.settings.validate()
    result = svc.dispatch(args.target, args.message, wait_seconds=args.wait, task_id=args.task_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    svc.settings.validate()
    result = svc.register(role=args.role, purpose=args.purpose or "", capabilities=args.capabilities or "")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_accept(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.init()
    result = svc.run_acceptance(args.task_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def cmd_ws(args: argparse.Namespace) -> int:
    from .platform import planner_ws

    settings = load_settings()
    settings.validate()
    try:
        asyncio.run(planner_ws.run(settings))
    except KeyboardInterrupt:
        print("\n已停止控制通道")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .service.daemon import PlannerDaemon

    settings = load_settings()
    settings.validate()
    daemon = PlannerDaemon(settings, send=not args.no_send, tick_interval=args.tick)
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        print("\n已停止守护")
    return 0


def cmd_observe(args: argparse.Namespace) -> int:
    from .platform import observer

    settings = load_settings()
    settings.validate()

    def on_message(msg: dict) -> None:
        t = msg.get("type")
        if t == "event":
            p = msg.get("payload") or {}
            print(f"[event] kind={p.get('kind')} state={(p.get('status') or {}).get('state')}")
        elif t == "monitor":
            print(f"[monitor] type={(msg.get('payload') or {}).get('type')}")
        elif t == "task":
            print(f"[task] {json.dumps(msg.get('task'), ensure_ascii=False)[:200]}")
        else:
            print(f"[{t}] {json.dumps(msg, ensure_ascii=False)[:200]}")

    try:
        asyncio.run(observer.run(settings, on_message))
    except KeyboardInterrupt:
        print("\n已停止观察")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="planner", description="agent-swarm-planner core")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="打印解析后的配置（隐藏密钥）").set_defaults(func=cmd_info)
    sub.add_parser("init", help="初始化 SQLite").set_defaults(func=cmd_init)
    sub.add_parser("status", help="跨目标概览").set_defaults(func=cmd_status)
    sub.add_parser("ping", help="检查平台 MCP + 控制通道连通").set_defaults(func=cmd_ping)
    wa = sub.add_parser("workspaces", help="列出平台可见工作区（选专家/派活用）")
    wa.add_argument("--all", action="store_true", help="包含离线工作区")
    wa.set_defaults(func=cmd_workspaces)

    g = sub.add_parser("goal", help="目标管理")
    gsub = g.add_subparsers(dest="goal_cmd", required=True)
    ga = gsub.add_parser("add", help="创建目标")
    ga.add_argument("title")
    ga.add_argument("--desc", default="")
    ga.add_argument("--criteria", default="")
    ga.add_argument("--priority", type=int, default=0)
    ga.add_argument("--deadline", default="")
    ga.add_argument("--expert", default="", help="专家 agent 工作区 ID（负责拆解与专家验收）")
    ga.add_argument("--expert-name", default="", help="专家工作区名称（展示用）")
    ga.set_defaults(func=cmd_goal_add)
    gse = gsub.add_parser("set-expert", help="设置/更换目标的专家工作区")
    gse.add_argument("goal_id")
    gse.add_argument("workspace_id")
    gse.add_argument("--name", default="")
    gse.set_defaults(func=cmd_goal_set_expert)
    gsub.add_parser("list", help="列出目标").set_defaults(func=cmd_goal_list)

    t = sub.add_parser("task", help="任务管理")
    tsub = t.add_subparsers(dest="task_cmd", required=True)
    ta = tsub.add_parser("add", help="新增任务")
    ta.add_argument("goal_id")
    ta.add_argument("title")
    ta.add_argument("--desc", default="")
    ta.add_argument("--dep", dest="depends_on", action="append", default=[])
    ta.add_argument("--agent", default="")
    ta.add_argument("--acceptance", choices=["auto", "manual"], default="auto")
    ta.add_argument("--parent", default="")
    ta.set_defaults(func=cmd_task_add)
    ts = tsub.add_parser("set", help="设置任务状态")
    ts.add_argument("task_id")
    ts.add_argument("status")
    ts.add_argument("--result", default=None)
    ts.set_defaults(func=cmd_task_set)

    pl = sub.add_parser("plan", help="任务树")
    plsub = pl.add_subparsers(dest="plan_cmd", required=True)
    ps = plsub.add_parser("show", help="显示任务树")
    ps.add_argument("goal_id")
    ps.set_defaults(func=cmd_plan_show)
    pe = plsub.add_parser("export", help="导出目标+任务树 JSON")
    pe.add_argument("goal_id")
    pe.set_defaults(func=cmd_plan_export)
    pa = plsub.add_parser("apply", help="从 JSON 写入任务树（agent 拆解结果）")
    pa.add_argument("goal_id")
    pa.add_argument("--file", default="", help="JSON 文件；留空从 stdin 读取")
    pa.add_argument("--replace", action="store_true", help="替换现有任务树（专家调整计划用）")
    pa.set_defaults(func=cmd_plan_apply)
    pr = plsub.add_parser("recover", help="失败任务重试/阻塞策略")
    pr.add_argument("goal_id")
    pr.set_defaults(func=cmd_plan_recover)
    pm = plsub.add_parser("markdown", help="输出任务树 markdown 快照")
    pm.add_argument("goal_id")
    pm.set_defaults(func=cmd_plan_markdown)

    n = sub.add_parser("nudge", help="组装并投递提示词")
    n.add_argument("goal_id")
    n.add_argument("--send", action="store_true", help="经 A2A 网关投递给 planner 工作区")
    n.add_argument("--force", action="store_true", help="忽略最小间隔限制")
    n.set_defaults(func=cmd_nudge)

    dp = sub.add_parser("dispatch", help="经平台 a2a_call 派任务给目标工作区（自动加压缩前导）")
    dp.add_argument("target", help="目标工作区 ID")
    dp.add_argument("message")
    dp.add_argument("--wait", type=int, default=0, help="同步等待终态秒数（默认 0）")
    dp.add_argument("--task-id", default="", help="关联的本地任务 ID；worker 终态时回写该任务")
    dp.set_defaults(func=cmd_dispatch)

    sub.add_parser("observe", help="订阅 /ws/nexus 观察事件").set_defaults(func=cmd_observe)

    rp = sub.add_parser("report", help="验收情况报告（交给专家 agent）")
    rp.add_argument("goal_id")
    rp.add_argument("--task", default="", help="聚焦某个验收点任务")
    rp.set_defaults(func=cmd_report)

    ac = sub.add_parser("accept", help="执行任务的自动验收命令")
    ac.add_argument("task_id")
    ac.set_defaults(func=cmd_accept)

    rg = sub.add_parser("register", help="把本目录注册/标记为 planner 工作区（MCP workspace_add）")
    rg.add_argument("--role", default="planner", help="默认 planner")
    rg.add_argument("--purpose", default="")
    rg.add_argument("--capabilities", default="")
    rg.set_defaults(func=cmd_register)
    sv = sub.add_parser("serve", help="启动后台守护（观察 + 调度 + 注入 + 平台控制通道）")
    sv.add_argument("--no-send", action="store_true", help="只观察/调度，不注入提示词")
    sv.add_argument("--tick", type=float, default=30.0, help="调度间隔秒（默认 30）")
    sv.set_defaults(func=cmd_serve)

    sub.add_parser("ws", help="只启动平台控制通道（WS /ws/planner）").set_defaults(func=cmd_ws)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
