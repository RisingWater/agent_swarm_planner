# agent-swarm-planner 开发进度 TODO

> 持续更新的进度/交接文档。**只增不删**：新进展往下追加；已有条目只改勾选状态。
> 更新时间：2026-10-02 · 当前 HEAD：`994e142`（planner）/ `64f8b3c`（agent_swarm dev）

## 项目一句话

本地自治的**长期目标规划器**：把模糊目标拆成任务树，作为平台上一个 `role=planner` 的
特殊工作区接入 `agent_swarm`，调度其它 agent 执行并追踪验收。核心原则：**确定性归 Python，
智能归 agent**（本仓库 Python 不调任何 LLM；拆解/重规划由用户手动运行的 agent 用自身模型完成）。

## 进度快照

- ✅ planner-core（确定性内核）M0–M4 完成，**61 例单测通过**；worker 结果回写 + 三态验收 + 专家/自评审已接。
- ✅ agent 接口定为 **CLI**（零安装、harness 无关）；本地 MCP 已按决策移除。
- ✅ 平台侧：`role` + 控制通道 `/ws/planner` + 真实「规划器」页（建目标/任务树/审批验收/归档激活删除/隐藏归档/专家选择），服务端已重启。
- ✅ 两侧联调与**真实端到端业务闭环**跑通：两个目标已 `done`（见「六、真实端到端实测记录」）。
- ✅ `status`/`ping`/`workspaces`/`report`/`serve`/`ws` + CI 就绪；文档（README/AGENTS/协议/需求）已补齐。

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
- [x] **重规划闭环**：`plan apply --replace`（整树替换）+ `plan.revise`→draft + `plan recover`；已在真实目标中由守护触发验证

### M4 专家工作区（专家拆解 + 专家验收）
- [x] `goals.expert_workspace_id/expert_name` + 迁移；`goal.create` 可带专家
- [x] 新增 `acceptance_type=expert` 与状态 `waiting_expert`；`apply_acceptance` 专家点→`waiting_expert`
- [x] planner agent 全权沟通专家（提示词 + AGENTS playbook：专家拆解、专家验收 JSON 裁决）
- [x] CLI：`goal add --expert` / `goal set-expert` / `workspaces`
- [x] 专家调整 → `apply_plan` 回 `plan_status=draft` 等人工再审
- [x] **专家=planner 自身**：不走 A2A（自我派单会被拒），planner agent 自行拆解 + 自评审（提示词分支）
- [x] 平台：专家选择器允许选中 planner 工作区自身，并标注「本工作区（自评审）」（dev `20a12c4`）
- [x] `plan apply --replace` 整树替换（专家调整计划用）；`planner report` 验收情况报告
- [x] 回复 agent_swarm 的 4 个确认点（`goal.update` 支持改专家；auto/manual/expert 文案；编辑态放开）
- [x] 平台：建目标加**专家工作区选择器**、目标展示专家、任务树标 `expert` 验收点与 `waiting_expert`（dev `1fb374c`）
- [x] 平台：目标编辑可改专家（空串=清除）；验收类型文案 `auto/manual/expert` 统一（dev `20406a9`）
- [x] core：`goal.delete`（硬删除，级联任务树/执行）、`goal.activate`（归档恢复）；CLI `goal delete --yes` / `goal activate`
- [x] 优先级 `高/中/低`(2/1/0) 映射 + CLI `--level`；成功标准 `criteria_confirmed`（专家确认）+ CLI `goal set-criteria --confirmed`
- [x] 平台：目标列表/详情加「删除」（二次确认）与归档目标的「激活」按钮；**「隐藏已归档目标」checkbox 默认勾选**（dev `1b27cd1` + `006c4f8`）
- [x] 平台：目标列表「状态/拆解」列合并为状态 tag（dev `653bd37`）；目标编辑可改专家、验收文案统一（dev `20406a9`）
- [x] 平台：截止「不填=无截止」、优先级 高/中/低 下拉、成功标准「专家已确认/待确认」徽标（dev `b6863e6`）
- [x] 端到端实测（带专家/自评审）：建目标 →（自评审）确认成功标准 → 拆解 → 人工审批 → 派发 worker → 终态回写 → 三态验收 → 专家评审（见「六」）
- [x] core：`suggested_agent` 在 state 中作为 `assigned_agent` 别名，对齐平台任务详情弹窗（`180f9d9`）
- [x] core：目标全部任务 done 时守护自动置 `goals.status=done`（`92d231a`）
- [x] core：不再对 `waiting_human` 自动催促（避免刷屏）（`dd408e5`）

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
- [x] 规划器页展示 `plan_status` 徽标（草稿/已通过），`通过拆解` 仅 draft 显示（dev `3ee329a`）
- [x] 专家工作区可为 planner 自身（自评审）：选择器不再排除自身，标注「本工作区（自评审）」（dev `20a12c4`）
- [x] 任务树界面优化：任务列只显示可点击标题 + 详情弹窗（描述/依赖/建议与实际执行 agent/验收类型/状态/验收结果）、依赖列只显示标题；「实际执行 agent」暂显示 `-`（dev `7e0e3dd` + `aec36b6`）

---

## 三、待办（Next）

### P1 完成 worker 结果闭环（已完成 2026-10-02）
- [x] `dispatch(target, message, task_id)`：记录 `local_kind=task`、本地任务置 `running`
- [x] daemon 观察 worker 任务终态 → 回写本地任务 `done`/`failed` + execution；`input-required` → `waiting_human`
- [x] 观察者改**通配订阅 `*`**（worker 任务挂在目标工作区名下，必须订阅名下全部工作区）
- [x] 单测覆盖（`test_daemon.py` / `test_dispatch.py`）

### P2 人工/自动验收（已完成 2026-10-02）
- [x] `apply_acceptance`：manual → `waiting_human`；expert → `waiting_expert`；auto 配 `accept_command` → 执行；否则直接 done
- [x] daemon worker 终态自动调用 `apply_acceptance`（`asyncio.to_thread`，不阻塞事件循环）
- [x] 人工验收：`waiting_human` 在平台页显示「通过/拒绝」，`task.accept/reject` 仅对待验收任务生效（终态幂等）——已在真实目标上由人验收通过
- [x] 专家验收：`waiting_expert` → planner agent 用 `planner report` 汇总 → 专家裁决/自评审

### P3 守护端到端（已完成 2026-10-02）
- [x] 真实闭环：建目标 →（自评审/专家）确认成功标准 → 拆解 → 人工审批 → 守护 tick 注入 → 派发 worker → 终态回写 → 三态验收 → 专家评审 → 目标 done（两个目标均 100%）
- [x] `planner serve` 常驻上线（含 `/ws/planner` 控制通道 + `/ws/nexus` 通配观察 + tick），平台显示 planner `online`

### P4 平台页增强
- [x] 控制通道协议设计：`docs/planner-platform-protocol.md`（core↔平台 WS + REST 契约）
- [x] core 侧：`platform/planner_ws.py` + `PlannerService.handle_op`（幂等）+ `planner ws` 命令
- [x] 平台侧：`/ws/planner` + `/api/planner/{wid}/state|op|ops` + 快照缓存 + PlannerPage 重做（dev `614de2f`，已重启验证）
- [x] 联调：core 连 WS → 网页建目标（REST op）→ core 落库 → 快照回推 → 页面可显示任务树
- [x] core 配合修正：state 带 `progress:{done,total}`；`task.accept/reject` 仅限待验收（终态幂等成功）
- [x] 平台页展示 `plan_status`（draft/approved）徽标，并据此显示「通过拆解」（dev `3ee329a`）

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
| `c580cf6` | 平台控制通道（WS `/ws/planner`）+ `handle_op` 幂等 + 协议文档 |
| `ec65ff1` | state 带 progress；`task.accept/reject` 严格待验收；联调验证 |
| `7aef00e` | `status`/`ping`、serve 冒烟、CI |
| `8a77b25` | 拆解人工审批 `plan_status`（draft/approved）+ 守护门控 |
| `b5d51c9` | 专家工作区（expert 拆解 + 专家验收点） |
| `2e3def1` | `plan apply --replace` 整树替换 + `planner report` 验收报告 |
| `751416b` | `goal.delete`（硬删除级联）+ `goal.activate`（归档恢复） |
| `257ef39` | 优先级 高/中/低(2/1/0) + 成功标准 `criteria_confirmed`（专家确认） |
| `15fe63e` | 专家=自身（自评审）分支，绕开自我派单 |
| `dd408e5` | 不再自动催促 `waiting_human` |
| `180f9d9` | state 暴露 `suggested_agent` 别名（对齐平台弹窗） |
| `92d231a` | 目标全部任务 done → 自动置 `goals.status=done` |

---

## 六、真实端到端实测记录（2026-10-02）

两个真实目标在平台「规划器」页可见、core 常驻 `online` 的状态下跑通了完整闭环：

1. **规划器功能开发**（`goal_d304b35677ef`，专家=本工作区/自评审）：自评审确认成功标准 → 拆解 10 任务 → 人工「通过拆解」→ 守护 tick 逐层注入/执行/核对 → `端到端实测` 人工验收 → `专家评审` 自评审 **accepted** → **done 10/10**。
2. **规划器前端，任务树界面优化**（`goal_ae2593fa9ef5`，专家=本工作区/自评审）：拆解 3 任务 → 审批 → 派发给 `agent_swarm` 工作区（自动带"先压缩上下文"前导）→ worker 终态经 `/ws/nexus` 回写 → 构建/联调验证 → `专家评审` 自评审 **accepted** → **done 3/3**。

链路要点：建目标 →（专家/自评审）确认成功标准 + 拆解 → `plan_status=draft` 审批门控 → 平台「通过拆解」→ 守护按依赖逐层注入/派发 → worker 终态回写本地任务 → 自动/人工/专家三态验收 → 目标全部任务完成后自动 `done`。

---

## 七、安装与部署（2026-10-02）

面向"真实安装"补齐可安装/常驻/自检体验（`planner` 命令；`setup`/`doctor`/`service`）：

- [x] `planner setup`：交互/非交互写 `.env`（server/api key/workspace id）+ 建库 + 连通校验
- [x] `planner doctor [--offline]`：Python/依赖/配置/DB/平台 MCP/控制通道 逐项自检
- [x] `planner service install|uninstall|status|print`：开机自启产物生成——Linux systemd（user/system）、Windows 计划任务（ONLOGON）、macOS LaunchAgent
- [x] 配置根解析改为 `PLANNER_HOME` > 源码仓库根 > 当前目录（安装后以工作目录为根）
- [x] **源码安装（弃用 pipx）**：`deploy/` 目录 + `install.sh` / `install.ps1`——建 venv → pip install（`-r` + `-e .`）→ `planner setup`/`doctor` → `planner service install`（注册 python 守护开机自启）→ 末尾提示在 harness 执行 `/swarm-add-planner` 注册
- [x] `INSTALL.md` 重写为源码/deploy 流程，并说明 harness（opencode/claude/deepseek + 其 agent-swarm 插件）的角色；`.env.example` 补 `PLANNER_HOME`
- [x] `planner service` 增加 `--serve-cmd`（deploy 脚本精确指向 venv 内 launcher）
- [x] 单测 `tests/test_installer.py`（12 例；全套 **80 passed**）

> 关键约束：守护与 harness 都要在线；平台需含 planner 特性（`role=planner` + `/ws/planner` + notify，目前在平台 dev 分支，正式发布前需合入）。

## 八、历史提交（续）

| commit | 内容 |
|---|---|
| `528a0a3` | 冻结 planner 待办通知协议（`docs/planner-platform-protocol.md` §7，T1） |
| `994e142` | core 侧 notify：`goals.plan_rev` + `notified` 表 + `pending_notifications`/`flush_notifications`（T6） |
