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
| `planner init` | 初始化 SQLite |
| `planner goal add "标题" --desc ... --criteria ...` | 创建目标 |
| `planner goal list` | 列出目标 |
| `planner task add <goal_id> "标题" --dep <task_id> --agent <wid> --acceptance auto` | 新增任务 |
| `planner task set <task_id> <status>` | 设置任务状态 |
| `planner plan show <goal_id>` | 显示任务树 |
| `planner plan export <goal_id>` | 导出目标+任务树 JSON |
| `planner plan apply <goal_id> --file plan.json` | 写入 agent 拆解出的任务树（支持乱序 temp_id 依赖） |
| `planner nudge <goal_id>` | 组装提示词（dry-run，只打印） |
| `planner nudge <goal_id> --send` | 经 A2A 网关投递给 planner 工作区 |
| `planner observe` | 订阅 `/ws/nexus` 观察事件 |

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

## 状态

- ✅ M0/M1：配置解析、SQLite schema、DAG、`plan apply/export`、提示词组装、A2A 投递、
  Nexus 观察者，含单测。
- ⏳ 下一步：本地 MCP 状态接口（`planner_get_state`/`planner_save_plan`/…）、自动调度循环、
  自动/人工验收、平台「目标/任务树」页。
