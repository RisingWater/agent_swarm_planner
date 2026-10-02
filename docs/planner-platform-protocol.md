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
| `goal.archive` | `{goal_id}` | 归档 |
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

## 3. core → 平台：状态快照

每次变更后、连接建立后、以及每 30s 周期推送：
```jsonc
← {"type":"state","payload":{
  "workspace_id":"<wid>",
  "updated_at":"<ISO>",
  "goals":[{"id","title","description","status","plan_status","priority","deadline",
            "success_criteria","progress":{"done":n,"total":m}}],
  "tasks":[{"id","goal_id","title","status","depends_on":[...],
            "assigned_agent","acceptance_type","acceptance_result","updated_at"}]
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
