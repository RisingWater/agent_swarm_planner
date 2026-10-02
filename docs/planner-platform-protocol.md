# planner-core ↔ agent_swarm 平台 控制通道协议（v1）

> 背景：planner-core 在用户内网/本机，平台（可能部署在别处）**访问不到 core 的端口**。
> 因此由 **core 主动向平台建立 WebSocket 长连接**，平台的配置/操作经此 WS 下发；core 把
> 结构化状态（目标 + 任务树）也从同一条 WS 推回平台展示。平台只做 UI 与转发，**不存任务真相**。

## 1. 连接与鉴权

- 端点：`WS /ws/planner`（**平台新增**，与 `/ws/plugin`、`/ws/nexus` 并列）
- 握手：
  ```jsonc
  → {"type":"hello","apikey":"as_...","workspace_id":"<planner_wid>"}
  ← {"type":"hello_ok"}                    // 或 {"type":"hello_err","error":"..."}
  ```
- 心跳：`→ {"type":"ping"}` / `← {"type":"pong"}`（15~30s）
- core 断线自动重连；平台按 workspace_id 维护连接（一个 workspace 一条，新连接替换旧的）。

## 2. 平台 → core：操作帧

```jsonc
{"type":"op","op_id":"<唯一，幂等键>","op":"goal.create",
 "payload":{...}}
```

| op | payload | 语义 |
|---|---|---|
| `goal.create` | `{title, description?, priority?, deadline?, success_criteria?}` | 新建目标 |
| `goal.update` | `{goal_id, title?, description?, priority?, deadline?, success_criteria?}` | 编辑目标 |
| `goal.archive` | `{goal_id}` | 归档（软状态，保留数据、不参与调度） |
| `goal.activate` | `{goal_id}` | 恢复已归档目标为 `active` |
| `goal.delete` | `{goal_id}` | **硬删除**目标及其任务树/执行记录（级联，不可恢复） |
| `plan.approve` | `{goal_id}` | 审批拆解（置 `plan_status=approved`）→ 通知 agent 开始派发 |
| `plan.revise` | `{goal_id, note?}` | 要求重新拆解（置 `plan_status=draft`） |
| `task.accept` | `{task_id, result?}` | 人工验收通过 |
| `task.reject` | `{task_id, reason?}` | 人工验收拒绝 |
| `goal.nudge` | `{goal_id}` | 手动触发 planner agent 决策 |
| `state.get` | `{}` | 请求全量状态 |

core 回执：
```jsonc
← {"type":"op_result","op_id":"...","ok":true,"error":""}
```
幂等：core 用 `operations` 表按 `op_id` 去重，重复操作直接返回上一次结果（不重复执行）。

**专家工作区**：`goal.create` 可带 `expert_workspace_id` / `expert_name`。有专家时，任务树由
planner agent 与专家 agent 沟通后写入；专家验收点用 `acceptance_type=expert`，任务会进入
`waiting_expert` 状态，由 planner agent 汇总情况请专家裁决（平台不参与专家对话，只负责选择与展示）。
**专家可以与 planner 工作区相同**（`expert_workspace_id == planner wid`）：此时不走 A2A
（自我派单会被平台拒），planner agent 直接自行拆解与自评审；平台应允许选中 planner 工作区自身，
并标注「本工作区（自评审）」。

**字段约定**：`priority` 用 `高=2 / 中=1 / 低=0`（排序数值大优先）；`deadline` 为空字符串 =
无截止；`success_criteria` 由专家确认，`criteria_confirmed=1` 表示已确认（`goal.update` 可写
`success_criteria` + `criteria_confirmed`）。

## 3. core → 平台：状态快照

每次变更后、连接建立后、以及每 30s 周期推送：
```jsonc
← {"type":"state","payload":{
  "workspace_id":"<wid>",
  "updated_at":"<ISO>",
  "goals":[{"id","title","description","status","plan_status","priority","deadline",
            "success_criteria","criteria_confirmed","expert_workspace_id","expert_name",
            "progress":{"done":n,"total":m}}],
  "tasks":[{"id","goal_id","title","description","status","depends_on":[...],
            "assigned_agent","suggested_agent","acceptance_type","acceptance_result","updated_at"}]
}}
```
平台把最新快照按 workspace 存储并转发给前端；这是**展示缓存**，不作真相。

## 4. 平台 REST（给前端用）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/planner/{wid}/state` | 最近快照 + `online`（WS 是否在线） |
| `POST` | `/api/planner/{wid}/op` | `{op, payload}` → 生成 `op_id` 经 WS 下发；core 离线则 `409`/排队 |
| `GET` | `/api/planner/{wid}/ops?limit=` | 可选：最近操作/回执历史（平台实现采用 `/ops`） |

鉴权：JWT（属主校验）。

## 5. 前端「规划器」页

- 目标列表 + **新建目标表单**；
- 选中目标渲染**任务树**（表格：标题/状态/依赖/执行 agent/验收；可显示 DAG 层级或进度条）；
- 操作按钮：`nudge`（让 agent 干活）、`plan.approve/revise`、`task.accept/reject`；
- 通过 `POST /api/planner/{wid}/op` 下发，`GET .../state`（+ 2s 轮询或复用 /ws/nexus 触发刷新）渲染。

## 6. 职责分工

| 侧 | 工作 |
|---|---|
| planner-core（本仓库） | `platform/planner_ws.py`（连接/重连/op 处理/状态推送）、`PlannerService.handle_op`、幂等 |
| agent_swarm 平台 | `/ws/planner` 端点 + 连接注册表、`/api/planner/{wid}/state|op`、快照缓存表、`PlannerPage` 重做 |

## 7. 待办通知（notify）—— 人工介入跨渠道外推

> 目标：当 planner 出现两类**人工待办**时，把提醒外推到飞书/微信/桌宠。
> ① 拆解待审批（`active` 目标 `plan_status=draft` 且任务数 > 0）；② 人工验收待处理
> （`acceptance_type=manual` 的任务进入 `waiting_human`）。同一待办在处理前**只提醒一次**。
> 本节为**已冻结**规格（专家验收点 `task_41bba5ec0555`，专家=agent_swarm 裁决 accepted）。

### 7.1 core → 平台 `notify` 帧（新增，与 `state`/`pong` 并列同一 WS）

`notify` 是**边沿事件**（仅"进入态"时发一次），周期 `state` 快照**绝不**携带 notify。

```jsonc
// 通用外壳
{"type":"notify","payload":{ ... }}

// kind = "plan_approval"（拆解待审批）
{"type":"notify","payload":{
  "kind":"plan_approval",
  "key":"plan:<goal_id>:<plan_rev>",
  "workspace_id":"<planner_wid>",
  "goal_id":"<goal_id>",
  "goal_title":"...",
  "plan_rev":3,
  "task_id":"",
  "title":"拆解待审批：<goal_title>",
  "detail":"共 N 个任务，等待人工『通过拆解』或『重新拆解』",
  "created_at":"<UTC ISO8601>"
}}

// kind = "task_acceptance"（人工验收待处理）
{"type":"notify","payload":{
  "kind":"task_acceptance",
  "key":"accept:<task_id>:<attempt>",
  "workspace_id":"<planner_wid>",
  "goal_id":"<goal_id>",
  "goal_title":"...",
  "task_id":"<task_id>",
  "task_title":"...",
  "attempt":0,
  "title":"人工验收待处理：<task_title>",
  "detail":"目标《<goal_title>》· 验收说明：<execution_spec 摘要，可空>",
  "created_at":"<UTC ISO8601>"
}}
```

**字段约定（冻结）**
- `kind`：仅 `plan_approval` / `task_acceptance`（snake_case）。
- `key`：**必填**，core 计算的权威幂等键（见 §7.2）；平台以此去重，不自行拼接。
- `goal_id`：两个 kind 都必填。`task_id`：`task_acceptance` 必填；`plan_approval` 固定 `""`。
- `goal_title`/`task_title`/`plan_rev`/`attempt`：冗余的人类可读/键成分，平台可直接取用。
- `title`/`detail`：纯文本，`title` 非空；`detail` 可为 `""`。`created_at`：UTC ISO8601（`db.utcnow()`）。
- **触发时机（仅进入态发一次）**：
  - `plan_approval`：`goals.plan_status` 由任意值 → `draft`，且 `goal.status=="active"` 且任务数 > 0。
  - `task_acceptance`：`tasks.status` → `waiting_human` 且 `acceptance_type=="manual"`（**不含** `waiting_expert`）。

### 7.2 幂等键与"只提醒一次"（冻结）

- 拆解键：`plan:<goal_id>:<plan_rev>`，**core 新增 `goals.plan_rev INTEGER DEFAULT 0`**；
  `set_goal_plan_status(gid,"draft")` 时 `plan_rev += 1`（`approved` 不自增）。效果：初次
  `apply_plan` 与每次 `plan.revise` 重回 draft 都得到**新键 → 重新提醒**；同一份 draft 的 30s
  重推不重复。
- 验收键：`accept:<task_id>:<attempt>`，`attempt` 取 `tasks.retry_count`（已存在，重试自增）。
- 发送时序：core 持久化 `notified(key, notified_at)`；**仅在成功 send 后**写 `notified_at`；
  send 失败（WS 断）不写，下个 tick / 重连可补发；**重连不重放**已 notified 的键（避免刷屏），
  故平台侧无需持久化。
- 平台清键（内存 `planner_pending`，命中任一即清除、不再提醒）：
  1. 收到对应 `op_result.ok==true`（`plan.approve|plan.revise|task.accept|task.reject`）；
  2. 后续 `state` 显示该目标 `plan_status!="draft"`，或该任务 `status!="waiting_human"`；
  3. 目标被 `goal.delete`/`goal.archive`（快照消失或 `status!="active"`）→ 清该 goal 下所有键；
  4. 平台重启丢失内存 pending 无妨（core 只在边沿发、不重放），最多漏推重启期间的待办。

### 7.3 op 语义与 `op_result`（冻结）

平台→core 沿用 §2 的 `op` 帧。`op_result` 外壳：
成功 `{"type":"op_result","op_id","ok":true}`（可带 `nudged`/`note`，平台忽略未知键）；
失败 `{"type":"op_result","op_id","ok":false,"error":"<人类可读>"}`。平台据自己记录的
`_ops[op_id].payload` 反查键清 pending，**无需 op_result 回带 payload**。

| op | payload（冻结） | core 语义 |
|---|---|---|
| `plan.approve` | `{goal_id}` | `plan_status=approved` + 触发 nudge；`ok:false`=`目标不存在` |
| `plan.revise` | `{goal_id, note?}` | `plan_status=draft`（`plan_rev+=1`）+ nudge |
| `task.accept` | `{task_id, result?}` | 要求 `status∈(waiting_human,waiting_expert)` → `done`，`acceptance_result=result或"人工验收通过"`；已终态 `ok:true,note=...`；否则 `ok:false` |
| `task.reject` | `{task_id, reason?}` | 同上 → `failed`，`acceptance_result=reason或"人工验收拒绝"` |

**IM 侧**：飞书卡两按钮 → `act:"planner_op"`，`value={workspace_id,op,payload}`；微信编号
1/2 → 映射上述 op。两者均调用平台已有 `planner_channel.dispatch_op(wid, op, payload)`
（core 离线 409 → 提示"规划器离线"）。**先答先算**：状态已变则 core 返回 `ok:false`，IM 侧
提示"已被处理/状态已变"并收起按钮。

### 7.4 平台待办事件（桌宠 `/ws/nexus`）形状（冻结）

平台用 `_push_web(planner_wid, payload, "planner")` 推送：

```jsonc
{"type":"planner","payload":{
  "kind":"plan_approval" | "task_acceptance",
  "workspace_id":"<planner_wid>",
  "goal_id":"<goal_id>",
  "task_id":"<task_id>" | "",
  "title":"拆解待审批：…" | "人工验收待处理：…",
  "detail":"<纯文本，可空>",
  "updated_at":"<平台收到 notify 的时间，UTC ISO>"
}}
```

桌宠**只读展示一条提醒**，无选项、无需回复；通配订阅 `{"workspace_id":"*"}` 者经 `_owns`
属主校验后同样收到（不跨用户）；不新增端点。

### 7.5 文档落点

- **全量规格唯一放本文件**（`agent-swarm-planner/docs/planner-platform-protocol.md`）。
- **平台仓库只随实现补"引用式"最小文档**（不复制字段表）：
  `docs/requirements.md`、`docs/desktop-client-nexus-integration.md`、`AGENTS.md`。
- 实现前置（非树变更）：core 新增 `goals.plan_rev`（进入 draft 自增）与 `notified` 表
  （发送成功后落键、重连不重放）。
