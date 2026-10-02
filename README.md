# agent-swarm-planner

本地自治的**长期目标规划器**：把模糊目标拆解成任务树，调度 `agent_swarm` 平台上的其它
agent 执行，并追踪验收。作为平台上的一个特殊工作区接入。

> 设计原则：**确定性归 Python，智能归 agent**。本仓库的 Python 服务不调用任何 LLM；
> 拆解与重规划由 planner 工作区里"用户手动运行的任意 agent"（opencode / claude / dsh …）
> 用自身模型完成。

## 架构

```
agent_swarm 平台（目标/任务树 UI）
   ▲  A2A message/send + input-required 提问      │
   │                                              ▼
┌──────────────────────────────────────────────────────────┐
│ planner 工作区 = 用户手动运行的 agent（任意 harness）       │
│   └─ 收到 /a2a/{planner_wid} 注入的提示词 → 读状态 → 决策  │
│        → plan apply 写回任务树 → a2a_call 派其它 agent 干活 │
└───────────────────────────▲──────────────────────────────┘
                            │ POST /a2a/{planner_wid} (apikey)
                ┌───────────┴──────────────┐
                │ planner-core (Python 后台) │
                │  SQLite / DAG / 验收 / 注入 │
                └──────────────────────────┘
```

- planner-core 组装"当前 todo/任务树"提示词，经 **A2A 网关**投递给 planner 工作区。
  平台只在 MCP 工具 `a2a_call` 里禁止"发给自己"，原始网关不拦，因此非 agent 的
  Python 服务可以把任务发给自己的工作区。
- planner agent 的决策结果通过 `plan apply` 写回 SQLite；需要人类决策时发起
  `input-required` 提问，人类在 web/飞书/微信/桌宠应答。

## 快速开始

```powershell
# 1) 依赖（Python 3.11+）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest pytest-asyncio   # 开发

# 2) 配置：复制 .env.example 为 .env，填 server / api key
#    未填时自动读取 ~/.config/opencode/agent-swarm.json 与 .agent_swarm/workspace.md

# 3) 初始化
.\.venv\Scripts\python.exe -m planner_core info
.\.venv\Scripts\python.exe -m planner_core init
```

## 常用命令

| 命令 | 说明 |
|---|---|
| `planner info` | 打印解析后的配置（隐藏密钥） |
| `planner status` | 跨目标概览（进度/就绪/阻塞/待验收） |
| `planner ping` | 检查平台 MCP 与控制通道 `/ws/planner` 连通 |
| `planner init` | 初始化 SQLite |
| `planner goal add "标题" --desc ... --criteria ... --expert <wid>` | 创建目标（`--expert` 指定专家 agent 工作区） |
| `planner goal list` | 列出目标 |
| `planner goal set-expert <goal_id> <wid> [--name]` | 设置/更换目标的专家工作区 |
| `planner goal activate <goal_id>` | 恢复已归档目标为 active |
| `planner goal delete <goal_id> --yes` | 硬删除目标及其任务树/执行记录（级联） |
| `planner workspaces [--all]` | 列出平台可见工作区（选专家/派活用） |
| `planner task add <goal_id> "标题" --dep <task_id> --agent <wid> --acceptance auto` | 新增任务 |
| `planner task set <task_id> <status>` | 设置任务状态 |
| `planner plan show <goal_id>` | 显示任务树 |
| `planner plan export <goal_id>` | 导出目标+任务树 JSON |
| `planner plan apply <goal_id> --file plan.json [--replace]` | 写入拆解结果（乱序 temp_id 两趟解析 + DAG 校验；`--replace` 整树替换，专家调整用） |
| `planner plan recover <goal_id>` | 失败任务重试/阻塞策略（未超上限回 pending，超限 blocked） |
| `planner nudge <goal_id>` | 组装提示词（dry-run，只打印） |
| `planner nudge <goal_id> --send` | 经 A2A 网关投递给 planner 工作区 |
| `planner observe` | 订阅 `/ws/nexus` 观察事件 |
| `planner report <goal_id> [--task <id>]` | 生成验收情况报告（交专家 agent 裁决） |
| `planner dispatch <target_wid> "指令" [--task-id <id>] [--wait N]` | 经平台 `a2a_call` 派任务给目标工作区（自动加"先压缩上下文"前导；带 `--task-id` 时 worker 终态回写该任务） |
| `planner accept <task_id>` | 执行该任务的自动验收命令（`execution_spec.accept_command`） |
| `planner serve [--no-send] [--tick 30]` | 后台守护：订阅事件 + 提升就绪 + 按需注入 + 平台控制通道 |
| `planner ws` | 只启动平台控制通道（连 `WS /ws/planner`） |

`plan apply` 的 JSON 格式：

```json
{"tasks": [{"temp_id": "a", "title": "...", "depends_on": [], "assigned_agent": "", "acceptance_type": "auto"}]}
```

## 目录

```
planner_core/
├─ config.py              # env / .env / opencode 配置 / .agent_swarm 解析
├─ db.py models.py store.py
├─ engine/dag.py          # 拓扑排序 / 就绪计算（纯函数）
├─ engine/prompt.py       # 注入提示词组装
├─ platform/a2a_client.py # POST /a2a/{wid} message/send | message/stream
├─ platform/observer.py   # /ws/nexus 订阅（断线重连 + 心跳）
├─ service/orchestrator.py# 目标/任务 CRUD、apply_plan、nudge
└─ cli.py
```

## agent 接口：CLI（无需安装）

planner agent（opencode / claude / dsh 任意）都有 shell，直接在本目录用 CLI 读写状态即可——
**零安装、harness 无关**：

```
planner plan export <goal_id>                 # 读全量状态
planner plan show <goal_id>                   # 看任务树
planner plan apply <goal_id> --file plan.json # 写回拆解结果（两趟解析 + DAG 校验）
planner task set <task_id> <status>
planner plan recover <goal_id>                # 失败重试/阻塞升级
planner plan markdown <goal_id>               # 生成回推平台的任务树快照
planner dispatch <target_wid> "指令"           # 派活（自动前置"先压缩上下文"）
```

注入给 planner agent 的提示词已经写明了这些命令，不需要额外配置任何 MCP。

## 平台控制通道（内网友好）

平台访问不到 core 的端口，因此 **core 主动连平台的 WebSocket** 长连接：平台网页的
「建目标 / 审批 / 验收」等操作经该 WS 下发给 core，core 把目标 + 任务树快照从同一条 WS 推回
平台展示。平台只做 UI 与转发，不存任务真相。

- core 侧：`planner ws`（或 `planner serve` 一并启动），连 `WS /ws/planner`；
- 协议（双方契约）：[`docs/planner-platform-protocol.md`](docs/planner-platform-protocol.md)；
- 配置：`PLANNER_WS_PATH`（默认 `/ws/planner`）、`PLANNER_WS_STATE_INTERVAL`。

> 平台需新增 `/ws/planner` 端点、`/api/planner/{wid}/state|op` 与「规划器」页写操作。

## 任务验收

任务 `execution_spec` 里配 `accept_command`（可选 `cwd` / `timeout`），运行
`planner accept <task_id>` 会执行并把结果写入 `tasks.acceptance_result` 与 `executions`。
`acceptance_type=manual` 的任务由人类通过平台的 `input-required` 提问确认。

## 状态

- ✅ M0/M1：配置解析、SQLite schema、DAG、`plan apply/export`、提示词组装、A2A 投递、
  Nexus 观察者，含单测。
- ✅ M2：后台守护 `serve`（`/ws/nexus` 订阅 + 就绪提升 + 节流注入）、自动验收 `accept`；
  平台 MCP 客户端（出站调 `a2a_call`/`workspace_add`）。
- ✅ M3（部分）：失败任务重试/阻塞升级（`plan recover`，接入守护 tick）；
  `planner dispatch`（派单自动前置"先压缩上下文"）。
- ✅ agent 接口定为 **CLI**（零安装、harness 无关）；本地 MCP 已移除。
- ⏳ 下一步：平台侧 `role` + `PlannerPage`（`agent_swarm` 工作区已在做）、人工验收提问闭环。
