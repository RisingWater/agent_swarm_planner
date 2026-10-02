# agent-swarm-planner 开发进度 TODO

> 持续更新的进度/交接文档。**只增不删**：新进展往下追加；已有条目只改勾选状态。
> 更新时间：2026-10-02 · 当前 HEAD：`7078431`（planner）/ `e8b224e`（agent_swarm dev）

## 项目一句话

本地自治的**长期目标规划器**：把模糊目标拆成任务树，作为平台上一个 `role=planner` 的
特殊工作区接入 `agent_swarm`，调度其它 agent 执行并追踪验收。核心原则：**确定性归 Python，
智能归 agent**（本仓库 Python 不调任何 LLM；拆解/重规划由用户手动运行的 agent 用自身模型完成）。

## 进度快照

- ✅ planner-core（确定性内核）M0–M3 主体完成，45 例单测通过；worker 结果回写 + 验收策略已接。
- ✅ agent 接口定为 **CLI**（零安装、harness 无关）；本地 MCP 已按决策移除。
- ✅ 平台侧：`role` + 控制通道 `/ws/planner` + 真实「规划器」页（建目标/任务树/审批验收），服务端已重启。
- ✅ 两侧联调通过；`status`/`ping`/`serve` 冒烟 + CI 就绪。
- ⏳ 未完成：真实浏览器端到端演示、agent 拆解+worker 派发业务闭环实测。

---

## 一、planner-core（本仓库）

### M0 配置与存储
- [x] 项目骨架：`pyproject.toml` / `requirements.txt` / `.env.example` / `.gitignore`（`419aaf1`）
- [x] `config.py`：env → `.env` → `~/.config/opencode/agent-swarm.json` → `.agent_swarm/workspace.md` 逐级解析
- [x] `db.py`：SQLite schema（goals/tasks/task_deps/executions/operations/platform_tasks/pending_inputs）、WAL、UTC
- [x] `store.py`：仓储层（目标/任务/依赖/执行/幂等 operation/平台桥接，短连接）
- [x] `models.py`：状态枚举（pending/ready/running/done/failed/blocked/waiting_human）

### M1 拆解与提示词
- [x] `engine/dag.py`：拓扑排序、环/缺失依赖校验、就绪计算（纯函数）
- [x] `engine/prompt.py`：组装注入提示词（目标 + todo + 目录 + DB 路径 + CLI 指引）
- [x] `service/orchestrator.py`：目标/任务 CRUD、`plan apply`（乱序 temp_id 两趟解析 + DAG 校验）、`export`、`markdown` 快照
- [x] `cli.py`：`info/init/goal/task/plan/nudge/observe` 等命令

### M2 平台通信与守护
- [x] `platform/a2a_client.py`：`POST /a2a/{wid}` 的 `message/send` / `message/stream`（apikey）
- [x] `platform/observer.py`：`/ws/nexus` 订阅（apikey、心跳、断线重连）
- [x] `service/daemon.py`：`planner serve`（观察 + tick 提升就绪 + 节流注入）
- [x] `engine/acceptance.py`：自动验收（跑 `execution_spec.accept_command` 抓日志）
- [x] `service/orchestrator.py`：`record_execution` / `run_acceptance`
- [x] `platform/mcp_client.py`：极简平台 MCP 客户端（stateless `tools/call`）
- [x] `planner dispatch`：经平台 `a2a_call` 派活，**机械前置"先压缩上下文"**（`PLANNER_DISPATCH_PREAMBLE`）
- [x] `planner register`：自注册 `role=planner` 并写 `.agent_swarm/workspace.md`

### M3 失败恢复
- [x] `planner plan recover`：失败任务未超上限回 pending、超限 blocked；接入守护 tick
- [x] `planner_dispatch` 前导规则 · `1e90e49`
- [x] **worker 结果回写**：派发时记录 `task_id`，worker 任务终态时把本地任务置 done/failed
- [x] **人工验收闭环**：`waiting_human` + 平台 `input-required` 提问/应答打通
- [x] **拆解人工审批**：`goals.plan_status`(draft/approved)，`apply_plan`→draft，`plan.approve`→approved；守护仅在 approved 后催派发
- [ ] **重规划闭环**：blocked / `plan.revise` → 重新注入让 agent 出子树替换（prompt 已含指引，待实测）

### 接口决策（已定，勿反复）
- [x] 设计往返：确定"Python 服务发给自己"+ planner 标志 + agent 决策/派活的整体架构
- [x] 派单规则：任何派活第一句先让对方压缩上下文（prompt 第 0 步 + `dispatch` 前导）
- [x] 先尝试本地 MCP（`mcp_server.py` + `guard.py`）→ **已按决策彻底删除**（`419aaf1`）
- [x] agent 接口定为 **CLI**；工作流写入 `AGENTS.md`「Planner agent playbook」+ `CLAUDE.md`（`@AGENTS.md`）
- [x] 出站平台 MCP 客户端保留（非本地 MCP）

### 测试
- [x] 32 例 pytest 通过（dag / store / prompt / plan_apply / config / acceptance / daemon / dispatch / register）

---

## 二、agent_swarm 平台侧（另一仓库，dev 分支，勿合 master）

- [x] `Workspace.role`（`agent`/`planner`，与 `agent_type` 解耦）+ 迁移（`380f206`）
- [x] MCP `workspace_add(role=)` / `update_info(role=)`；`list_workspaces` 与 REST 返回；`POST /api/workspaces/{wid}/role`
- [x] 前端 `PlannerPage`（只读：任务列表 + 最近成果 markdown）（`380f206`）
- [x] 三 harness `/swarm-add-planner`：opencode/claude md 命令、dsh 原生 `register("swarm-add-planner")`；`/swarm-add` 保持无参（`e8b224e`）
- [x] 服务端重启并验证 role 生效（本工作区已显示 `planner`）
- [x] 工作区页：规划器置顶 + 紫色「规划器」徽标；顶栏「规划器」入口仅在有 planner 工作区时显示（dev `653cca9`，前端即时生效）
- [x] 控制通道 `/ws/planner`（core 主动外连）+ 连接注册表（dev `614de2f`）
- [x] REST `/api/planner/{wid}/state`（最近快照+online）、`/api/planner/{wid}/op`、`/ops`
- [x] 快照缓存表 `planner_state`（展示用，非真相）
- [x] 「规划器」页重做：目标列表 + 新建/编辑/归档表单 + 任务树 + 催促/通过拆解/重新拆解/验收按钮
- [x] **两侧联调通过**：core 连 WS → `state online:true` → `POST op goal.create` → 快照回推 → `GET /ops` 显示 `ok:true`（`data/integration_smoke.py`）

---

## 三、待办（Next）

### P1 完成 worker 结果闭环（已完成 2026-10-02）
- [x] `dispatch(target, message, task_id)`：记录 `local_kind=task`、本地任务置 `running`
- [x] daemon 观察 worker 任务终态 → 回写本地任务 `done`/`failed` + execution；`input-required` → `waiting_human`
- [x] 观察者改**通配订阅 `*`**（worker 任务挂在目标工作区名下，必须订阅名下全部工作区）
- [x] 单测覆盖（`test_daemon.py` / `test_dispatch.py`）

### P2 人工/自动验收（已完成核心 2026-10-02）
- [x] `apply_acceptance`：manual → `waiting_human`；auto 配 `accept_command` → 执行；否则直接 done
- [x] daemon worker 终态自动调用 `apply_acceptance`（`asyncio.to_thread`，不阻塞事件循环）
- [x] 提示词 + AGENTS playbook 指引 agent 对 `waiting_human` 发起提问，按结果 `task set done/failed`
- [ ] 平台 `input-required` 提问/应答**端到端实测**（依赖独立会话，见 P3）

### P3 守护端到端
- [ ] 用独立 opencode 会话跑一次真实闭环：建目标 → 注入 → 拆解 → 派活 → 回写 → 页面展示
- [ ] `planner serve` 常驻冒烟（--no-send 先观察，再 send）

### P4 平台页增强
- [x] 控制通道协议设计：`docs/planner-platform-protocol.md`（core↔平台 WS + REST 契约）
- [x] core 侧：`platform/planner_ws.py` + `PlannerService.handle_op`（幂等）+ `planner ws` 命令
- [x] 平台侧：`/ws/planner` + `/api/planner/{wid}/state|op|ops` + 快照缓存 + PlannerPage 重做（dev `614de2f`，已重启验证）
- [x] 联调：core 连 WS → 网页建目标（REST op）→ core 落库 → 快照回推 → 页面可显示任务树
- [x] core 配合修正：state 带 `progress:{done,total}`；`task.accept/reject` 仅限 `waiting_human`（终态幂等成功）
- [ ] 平台页展示 `plan_status`（draft/approved）徽标，并据此显示「通过拆解」（新增字段，需平台侧小改）

### P5 工程化
- [x] `planner status` 跨目标概览；`planner ping` 检查平台 MCP + `/ws/planner` 连通
- [x] `serve` 常驻冒烟：daemon 启动 + `/ws/planner` 连接成功（`--no-send`，不改状态）
- [x] CI：`.github/workflows/tests.yml`（push/PR 跑 pytest）
- [x] `.agent_swarm/workspace.md` 的 `ROLE:` 行保留为本地标记（平台 role 仍以 `workspace_add` 为准）
- [x] `planner` 命令入口：`planner`（安装）或 `.venv\Scripts\python.exe -m planner_core`（免装）

---

## 四、已知状态 / 风险

- 平台运行在 `http://127.0.0.1:8700`；apikey 从 `~/.config/opencode/agent-swarm.json` 兜底读取。
- 平台服务重启后由 agent_swarm 工作区以隐藏进程方式拉起（PID 变更）；本仓库不负责部署。
- 自我派单禁令只在 MCP `a2a_call`，原始 `/a2a/{wid}` 网关不拦——这是"Python 服务发给自己"的依据。
- 平台侧任务 `YgdWAhjMXSJSTy4AuzN5QM`（纠正重复单）此前仍在 `working`，内容已被 `e8b224e` 覆盖。
- Windows/PowerShell：中文需 `chcp 65001` + `PYTHONUTF8=1`；PS 5.1 无 `&&`。

## 五、历史提交

| commit | 内容 |
|---|---|
| `0166c3c` | 需求文档 + AGENTS.md |
| `4922328` | planner-core v0（SQLite + DAG + A2A 自注入 + CLI） |
| `5be515d` | M2：本地 MCP、守护、自动验收 |
| `14bab04` | M3：失败重试/阻塞（plan recover） |
| `1e90e49` | 派单规则：先压缩上下文（prompt 第 0 步 + worker 指令） |
| `eb047a6` | 平台 MCP 客户端 + `planner_dispatch`（机械前导） |
| `8ba8b7c` | planner 自注册（`workspace_add(role=planner)`） |
| `8de9de9` | 本地 MCP guard（后被移除） |
| `419aaf1` | 移除本地 MCP；CLI 为接口；AGENTS.md playbook + CLAUDE.md |
| `7078431` | worker 结果回写本地任务 + 验收策略（manual→waiting_human / auto 命令）；新增 TODO.md |
