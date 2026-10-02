# agent-swarm-planner

本地自治的**长期目标规划器**：把模糊目标拆解成任务树，调度 `agent_swarm` 平台上的其它
agent 执行，并追踪验收。作为平台上一个 `role=planner` 的特殊工作区接入。

> 设计原则：**确定性归 Python，智能归 agent**。本仓库的 Python 服务（planner-core）**不调用
> 任何 LLM / 厂商 SDK**；目标确认、拆解与重规划由 planner 工作区里"用户手动运行的任意 agent"
> （opencode / claude / dsh …）用自身模型完成。

## 架构

```
agent_swarm 平台（规划器页：目标/任务树/审批/验收）
   ▲  WS /ws/planner（core 主动外连：操作下发 + 状态快照回推）      │
   │                                                                │
┌──┴─────────────────────────┐        A2A message/send（注入规划请求）
│ planner-core (Python 后台)  │──────────────────────────────────────▶ planner 工作区
│  SQLite / DAG / 调度 / 验收 │◀──────────────────────────────────────  (用户手动运行的 agent)
│  控制通道 / 观察 / 派发      │        a2a_call（派 worker 干活）
└───────────────┬────────────┘
                │ A2A（经平台）
         其它 agent 工作区（worker）
```

- **planner-core**：确定性内核（目标/任务树真相、DAG、调度、三态验收、提示词注入）。
- **planner agent**：用户手动运行的 agent，读状态 → 决策（拆解/派发/汇总）→ 用 CLI 写回。
- **平台**：人机界面 + 转发 + 展示缓存，**不存任务真相**。因 planner 可能在用户内网，
  平台访问不到 core 端口，故由 **core 主动建立 WebSocket 长连接**（`/ws/planner`）。
- **专家工作区**（每个目标可选）：负责确认成功标准、拆解任务树并设专家验收点；
  **专家 = planner 自身时不走 A2A，由 planner agent 自行拆解 / 自评审**。

## 快速开始

```powershell
# 1) 依赖（Python 3.11+）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest pytest-asyncio   # 开发

# 2) 配置：复制 .env.example 为 .env，填 server / api key
#    未填时自动读取 ~/.config/opencode/agent-swarm.json 与 .agent_swarm/workspace.md

# 3) 初始化并常驻（含平台控制通道）
.\.venv\Scripts\python.exe -m planner_core info
.\.venv\Scripts\python.exe -m planner_core init
.\.venv\Scripts\python.exe -m planner_core serve      # 常驻：观察 + 调度 + 控制通道
```

`planner` 等价于 `.\.venv\Scripts\python.exe -m planner_core`。

## 常用命令

| 命令 | 说明 |
|---|---|
| `planner info` / `planner status` | 配置（隐藏密钥）/ 跨目标概览 |
| `planner ping` | 检查平台 MCP 与控制通道 `/ws/planner` 连通 |
| `planner workspaces [--all]` | 列出平台可见工作区（选专家/派活用） |
| `planner goal add "标题" --level 高\|中\|低 --criteria ... --expert <wid> [--deadline ...]` | 创建目标（`--level` 高=2/中=1/低=0；`--deadline` 不填=无截止；`--expert` 指定专家） |
| `planner goal list` / `set-expert` / `set-criteria --confirmed` / `activate` / `delete --yes` | 目标生命周期与专家/成功标准管理 |
| `planner task add <goal_id> "标题" --dep <id> --agent <wid> --acceptance auto\|manual\|expert` | 新增任务 |
| `planner task set <task_id> <status>` | 设置任务状态 |
| `planner plan show` / `export` / `markdown` | 任务树展示 / JSON 导出 / 回推快照 |
| `planner plan apply <goal_id> --file plan.json [--replace]` | 写入拆解结果（乱序 temp_id 两趟解析 + DAG 校验；`--replace` 整树替换） |
| `planner plan recover <goal_id>` | 失败重试 / 阻塞升级 |
| `planner report <goal_id> [--task <id>]` | 生成验收情况报告（交专家裁决） |
| `planner nudge <goal_id> [--send]` | 组装提示词（dry-run）/ 经 A2A 注入 planner agent |
| `planner dispatch <target_wid> "指令" [--task-id <id>]` | 经平台 `a2a_call` 派活（自动前置"先压缩上下文"；带 `--task-id` 时 worker 终态回写） |
| `planner accept <task_id>` | 执行任务的自动验收命令（`execution_spec.accept_command`） |
| `planner observe` / `ws` / `serve [--no-send] [--tick N]` | 只观察 / 只控制通道 / 常驻守护 |

`plan apply` 的 JSON 格式（`temp_id` 可乱序，依赖自动解析）：

```json
{"tasks": [{"temp_id": "a", "title": "...", "depends_on": [], "assigned_agent": "", "acceptance_type": "auto"}]}
```

## 目标与任务语义

- **goals.status**：`active` / `archived` / `done`。归档=软隐藏可恢复（`goal.activate`）；删除=硬删除级联（`goal.delete`）；全部任务 done 时守护自动置 `done`。
- **priority**：`高=2 / 中=1 / 低=0`（排序数值大优先）。
- **plan_status**：`draft`（待人工审批，不派发）/ `approved`（放行派发）。
- **criteria_confirmed**：`1` 表示成功标准已经专家确认。
- **tasks.status**：`pending/ready/running/done/failed/blocked/waiting_human/waiting_expert`。
- **acceptance_type**：`auto`（可配 `accept_command` 跑测试/lint/构建抓日志作 anchor）/ `manual`（人验收）/ `expert`（专家验收点）。

## 专家工作区流程（含自评审）

1. 建目标时选**专家工作区**（任意可见工作区）；`plan_status=draft`。
2. planner agent 先与专家沟通：确认/修正**成功标准**（`goal set-criteria --confirmed`），取得任务树与**专家验收点**（`acceptance_type=expert`），用 `plan apply` 写回。
3. 平台人工「通过拆解」→ `approved` → agent 派发 ready 任务（验收点除外）。
4. 到专家验收点时，planner agent 用 `planner report` 汇总情况，请专家裁决 JSON `{accepted, reason, adjustments}`；
   `adjustments` → `plan apply --replace` 整树替换并回 `draft` 等人工再审；`accepted` → 任务 done。
5. **专家 = 本工作区**时不发 `a2a_call`（自我派单会被平台拒），由 planner agent **自行拆解 / 自评审**。

## agent 接口：CLI（无需安装）

planner agent（任意 harness）都有 shell，直接在本目录用 CLI 读写状态即可——零安装、harness 无关，
完整工作流见 [`AGENTS.md`](AGENTS.md) 的「Planner agent playbook」（claude 经 [`CLAUDE.md`](CLAUDE.md) 的 `@AGENTS.md` 导入）。

## 平台控制通道

core 主动连平台 `WS /ws/planner`：平台网页的「建目标/编辑/审批/验收/归档/激活/删除/催促」经该 WS
下发给 core，core 把目标+任务树快照从同一条 WS 推回展示。协议见
[`docs/planner-platform-protocol.md`](docs/planner-platform-protocol.md)；配置 `PLANNER_WS_PATH`（默认
`/ws/planner`）、`PLANNER_WS_STATE_INTERVAL`。

## 目录

```
planner_core/
├─ config.py                 # env / .env / opencode 配置 / .agent_swarm 解析
├─ db.py models.py store.py  # SQLite schema + 仓储（短连接）
├─ engine/dag.py             # 拓扑排序 / 就绪计算（纯函数）
├─ engine/prompt.py          # 注入提示词组装（含专家/自评审分支）
├─ engine/acceptance.py      # 自动验收（跑 accept_command 抓 anchor）
├─ platform/a2a_client.py    # POST /a2a/{wid} message/send | message/stream
├─ platform/observer.py      # /ws/nexus 订阅（通配观察 worker 终态）
├─ platform/planner_ws.py    # WS /ws/planner 控制通道（收 op / 推 state）
├─ platform/mcp_client.py    # 平台 MCP 客户端（workspace_add / a2a_call ...）
├─ service/orchestrator.py   # 目标/任务 CRUD、handle_op、apply_plan、nudge、report
├─ service/daemon.py         # planner serve：观察 + tick + 控制通道
└─ cli.py
```

## 状态

- ✅ M0–M4 完成：配置/存储、DAG、拆解与审批、平台通信、守护、三态验收、专家/自评审、目标生命周期、动态重规划。
- ✅ agent 接口 = **CLI**（本地 MCP 已移除）；工作流见 AGENTS.md / CLAUDE.md。
- ✅ 平台侧：`role=planner` + 控制通道 `/ws/planner` + 真实「规划器」页；两侧已联调。
- ✅ **真实端到端闭环已跑通**（两个目标均 100% 完成）；61 例 pytest；CI 就绪。
- 进度与历史见 [`TODO.md`](TODO.md)。

## 文档索引

- [`docs/requirement_v1.md`](docs/requirement_v1.md) — 原始需求与设计（含实现变更说明）
- [`docs/planner-platform-protocol.md`](docs/planner-platform-protocol.md) — core ↔ 平台控制通道协议
- [`TODO.md`](TODO.md) — 进度/交接（持续更新）
- [`AGENTS.md`](AGENTS.md) / [`CLAUDE.md`](CLAUDE.md) — agent 工作手册
