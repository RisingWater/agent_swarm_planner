# agent-swarm-planner 需求与设计文档

## 1. 背景

`agent-swarm` 是一个 agent 管理平台，已具备：

- 工作区管理（接入不同 agent 的代码目录）
- 实时工作同步
- IM 推送
- A2A 通信（agent 之间互相调用）
- Nexus 指令下发
- 团队协作（共享工作区）

平台缺少一个**长期目标驱动层**：把模糊的长期目标拆解成任务树，自动调度 agent 执行，并追踪进度。

由于多用户 apikey 配置复杂、平台不宜内建 agent 运行时，决定将该能力做成一个**本地自治的独立项目** `agent-swarm-planner`，以特殊 agent 身份接入平台。

---

## 2. 目标

做一个本地运行的规划器项目 `agent-swarm-planner`：

- 本地存储目标与任务树（SQLite）
- 本地完成拆解、重规划、调度运算
- 通过 A2A 驱动平台上的其他 agent 执行任务
- 通过特殊指令注册为平台上一个特殊 agent
- 通过 WS 长连接与平台双向通信
- 平台负责人机接口（添加/编辑目标、查看任务树、人工验收）
- 平台不存储任务真相，只做输入与展示

---

## 3. 角色与职责划分

| 模块 | 职责 |
|---|---|
| `agent-swarm` 平台 | 人机接口、A2A 转发、WS 通道、IM 通知、任务视图展示 |
| `agent-swarm-planner`（本地） | 目标存储、任务拆解、重规划、调度、A2A 驱动执行、状态回推 |
| 其他 agent | 接收 planner 下发的任务并执行 |
| 人类 | 添加目标、审批拆解、硬件相关节点验收 |

---

## 4. 核心概念

- **Goal（目标）**：模糊的长期目标，如“把项目做成可上线 MVP”
- **Task Tree（任务树）**：由 Goal 拆解出的层级任务结构
- **Task（任务）**：可分配给 agent 执行的最小单元
- **Execution Spec（执行规格）**：任务对应的 agent、输入、预期输出、验收标准
- **Acceptance（验收）**：自动验收（测试/日志）或人工验收（硬件场景）
- **Anchor（锚点）**：让 AI 感知执行结果的数据，如日志、串口输出、人拍的照片/视频

---

## 5. 功能需求

### 5.1 目标管理（平台侧接口，planner 侧存储）

- 创建目标：标题、描述、截止时间、优先级、成功标准
- 编辑目标
- 查看目标列表与详情
- 归档/删除目标

### 5.2 任务拆解

- 输入 Goal + 工作区上下文，由 LLM 拆解为任务树
- 支持人工确认/调整拆解结果
- 支持执行中动态重规划

### 5.3 任务调度与执行

- 任务树转 DAG，识别依赖与并行
- 按依赖调度任务
- 通过 A2A 将任务下发给对应 agent
- 支持任务失败重试、阻塞上报

### 5.4 验收

- 自动验收：跑测试、lint、构建、抓日志
- 人工验收：硬件相关节点，人确认后放行
- 验收结果回写任务节点

### 5.5 状态同步与通知

- planner 通过 WS 将任务决策、状态变化推给平台
- 平台展示任务树、进度
- 关键节点通过 IM 推送给人

### 5.6 平台与 planner 通信

- planner 以特殊 agent 身份注册到平台
- 平台向 planner 发送：新建目标、编辑目标、人工验收、审批拆解等操作
- planner 向平台发送：任务树快照、状态更新、待验收请求、阻塞告警

### 5.7 幂等与重放

- 平台发往 planner 的每个操作带唯一 ID
- planner 幂等处理，避免 WS 重连导致重复建目标

---

## 6. 非功能需求

- 本地自治：平台不可用时 planner 仍能运行，仅 A2A/通知中断
- 数据本地：任务真相存本地 SQLite
- 可替换：换规划策略/模型只动本地项目
- 轻平台：平台不内建 agent 运行时
- 可观测：任务树、执行历史、决策日志可查

---

## 7. 系统架构

```
┌─────────────────────────────┐
│        agent-swarm 平台      │
│  ┌───────────┐  ┌─────────┐ │
│  │ 目标管理UI │  │ 任务视图 │ │
│  └───────────┘  └─────────┘ │
│  ┌───────────┐  ┌─────────┐ │
│  │ A2A 转发   │  │ IM 通知 │ │
│  └───────────┘  └─────────┘ │
│         │ WS 长连接          │
└─────────┼───────────────────┘
          │
┌─────────┼───────────────────┐
│  agent-swarm-planner（本地） │
│  ┌───────────────────────┐  │
│  │ WS 通信层              │  │
│  ├───────────────────────┤  │
│  │ 规划引擎（拆解/重规划） │  │
│  ├───────────────────────┤  │
│  │ 调度器（DAG）          │  │
│  ├───────────────────────┤  │
│  │ A2A 客户端             │  │
│  ├───────────────────────┤  │
│  │ SQLite（goal/task）    │  │
│  └───────────────────────┘  │
└─────────┬───────────────────┘
          │ A2A
┌─────────┼───────────────────┐
│      其他 agent（工作区）    │
└─────────────────────────────┘
```

---

## 8. 数据模型（SQLite）

### goals
| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | 目标 ID |
| title | TEXT | 标题 |
| description | TEXT | 描述 |
| priority | INTEGER | 优先级 |
| deadline | TEXT | 截止时间 |
| success_criteria | TEXT | 成功标准 |
| status | TEXT | active/archived/done |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

### tasks
| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | 任务 ID |
| goal_id | TEXT FK | 所属目标 |
| parent_id | TEXT FK | 父任务 |
| title | TEXT | 标题 |
| description | TEXT | 描述 |
| status | TEXT | pending/ready/running/done/failed/blocked/waiting_human |
| assigned_agent | TEXT | 目标 agent |
| execution_spec | TEXT(JSON) | 输入/输出/验收标准 |
| acceptance_type | TEXT | auto/manual |
| acceptance_result | TEXT | 验收结果 |
| retry_count | INTEGER | 重试次数 |
| created_at | TEXT | |
| updated_at | TEXT | |

### task_deps
| 字段 | 类型 | 说明 |
|---|---|---|
| task_id | TEXT FK | 任务 |
| depends_on | TEXT FK | 依赖任务 |

### executions
| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | 执行记录 ID |
| task_id | TEXT FK | 任务 |
| agent | TEXT | 执行 agent |
| input | TEXT(JSON) | 输入 |
| output | TEXT(JSON) | 输出 |
| anchor | TEXT | 锚点（日志/文件/人工反馈） |
| status | TEXT | 执行状态 |
| started_at | TEXT | |
| finished_at | TEXT | |

### operations
| 字段 | 类型 | 说明 |
|---|---|---|
| op_id | TEXT PK | 平台操作唯一 ID（幂等） |
| type | TEXT | create_goal/edit_goal/approve/… |
| payload | TEXT(JSON) | 操作内容 |
| processed_at | TEXT | 处理时间 |

---

## 9. 通信协议（WS 消息类型）

### 平台 → planner
| 类型 | 说明 |
|---|---|
| `goal.create` | 新建目标 |
| `goal.update` | 编辑目标 |
| `goal.archive` | 归档目标 |
| `plan.approve` | 审批拆解结果 |
| `plan.revise` | 要求重新拆解 |
| `task.accept` | 人工验收通过 |
| `task.reject` | 人工验收拒绝 |
| `task.note` | 添加备注 |

### planner → 平台
| 类型 | 说明 |
|---|---|
| `plan.snapshot` | 任务树全量快照 |
| `plan.update` | 任务树增量更新 |
| `task.status` | 任务状态变化 |
| `task.need_acceptance` | 请求人工验收 |
| `task.blocked` | 任务阻塞告警 |
| `goal.progress` | 目标进度更新 |

所有消息带 `op_id` / `msg_id`，保证幂等与可重放。

---

## 10. 关键流程

### 10.1 创建目标并拆解
1. 平台 UI 创建目标 → WS `goal.create`
2. planner 存 SQLite，调 LLM 拆解成任务树
3. planner 推 `plan.snapshot` 给平台展示
4. 人审批 → `plan.approve` 或 `plan.revise`

### 10.2 任务执行
1. 调度器找出 ready 任务
2. 通过 A2A 下发给 assigned_agent
3. agent 执行，结果回写
4. 自动验收或请求人工验收
5. 更新任务状态，推 `task.status`
6. 触发下游任务

### 10.3 硬件节点验收
1. 任务执行完，无自动锚点
2. planner 推 `task.need_acceptance`
3. 人在平台确认（拍照/填结果）
4. 平台发 `task.accept` / `task.reject`
5. planner 更新状态，继续或重规划

### 10.4 阻塞与重规划
1. 任务失败或阻塞
2. planner 推 `task.blocked`
3. IM 通知人
4. 触发重规划，更新任务树
5. 推 `plan.update`

---

## 11. 技术选型建议

- 语言：Python 或 TypeScript（看团队熟悉度）
- 存储：SQLite
- LLM：可配置 provider（本地/远程）
- 通信：WS 长连接 + A2A 客户端
- 调度：简单 DAG 拓扑排序即可，无需重型框架
- 幂等：op_id 去重表

---

## 12. MVP 范围

第一阶段：
1. 注册为特殊 agent，建立 WS 通道
2. 平台创建目标 → planner 存储
3. LLM 拆解成任务树 + 人工审批
4. 任务树推回平台展示
5. 手动/半自动触发任务，A2A 下发
6. 人工验收节点
7. 状态回推 + IM 通知

第二阶段：
- 自动调度 DAG
- 自动验收（测试/日志）
- 动态重规划
- 长期记忆与上下文管理

---

## 13. 交付物

- `agent-swarm-planner` 项目代码
- SQLite schema
- WS 消息协议定义
- A2A 注册与调用封装
- 平台侧：目标管理 UI、任务树视图、验收入口
- 本文档作为实现依据

---
