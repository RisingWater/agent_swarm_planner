# 安装 agent-swarm-planner

把本机变成 `agent_swarm` 平台上的一个**规划器工作区**。由三部分组成：

| 部件 | 是什么 | 谁来装 |
|---|---|---|
| **planner-core**（本仓库） | 确定性内核：SQLite/DAG/调度/验收/注入；主动外连平台 | **`deploy/install.sh\|ps1`**（建 venv + pip install + 注册服务） |
| **harness** | 在规划器工作区里跑的 agent 客户端（opencode / claude / deepseek）+ 其 agent-swarm 插件（负责心跳、收 A2A 任务） | 平台管理页的「插件安装」一键命令，或平台仓库 `deploy/install.*` |
| **平台** | agent_swarm 服务（含 `role=planner` + `WS /ws/planner` + 规划器页） | 平台自身部署（需含 planner 特性） |

> 设计原则：**确定性归 Python，智能归 agent**。planner-core 不调用任何 LLM；拆解/决策由 harness 里的 agent 完成。

## 0. 先决条件

| 项 | 要求 |
|---|---|
| Python | ≥ 3.11 |
| 平台 | 可访问的 `agent_swarm` 服务（默认 `http://127.0.0.1:8700`），且已含 **planner 特性**（`role=planner` + `WS /ws/planner` + 规划器页） |
| 账号 | 一个 API Key（平台「API Key」页复制，`as_...`） |
| harness | 一个 agent 客户端（opencode / claude code / deepseek harness 任一），并装好其 agent-swarm 插件 |

## 1. 安装 planner-core（deploy 脚本）

脚本做三件事：**建 venv → pip install → 注册 python 守护开机自启**，最后提示你去 harness 注册。

```bash
# Linux / macOS（在仓库根）
./deploy/install.sh --server http://127.0.0.1:8700 --api-key as_xxx
#   --workspace-id <WID>   可留空（随后由 /swarm-add-planner 写入 .agent_swarm/workspace.md）
#   --scope system         装成系统级服务（需 root；默认 user 级）
#   --no-service           不注册自启
#   --no-verify / --offline 跳过连通/联网校验
```

```powershell
# Windows（在仓库根）
powershell -ExecutionPolicy Bypass -File .\deploy\install.ps1 -Server http://127.0.0.1:8700 -ApiKey as_xxx
#   -WorkspaceId <WID>  -Scope user|system  -NoService  -NoVerify  -Offline
```

脚本内部等价于：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .          # 生成 .venv/bin/planner
.venv/bin/planner setup --server ... --api-key ... --yes
.venv/bin/planner doctor
.venv/bin/planner service install --serve-cmd '"<repo>/.venv/bin/planner" serve'
```

> 不依赖 pipx。安装即源码安装：仓库目录就是工作根，`.env`、`.agent_swarm/`、`data/planner.db` 都在此。

## 2. 配置

`planner setup`（脚本已调用）会写**工作根目录**的 `.env`、初始化数据库，并校验平台连通。
手动重配：

```bash
.venv/bin/planner setup --server http://127.0.0.1:8700 --api-key as_xxx --workspace-id <WID> --yes
```

- 配置解析优先级：进程环境变量 → `.env` → `~/.config/opencode/agent-swarm.json`（`serverUrl`/`apiKey`）→ `.agent_swarm/workspace.md` 的 `WORKSPACE_ID:`。
- 工作根默认＝仓库根；可用 `PLANNER_HOME` 覆盖（服务以该目录为 `WorkingDirectory`）。

## 3. 在 harness 里注册为 planner 工作区（必做最后一步）

harness 的 agent-swarm 插件装上后，进入**本目录**启动 harness：

```bash
cd <repo> && opencode      # 或 claude / dsh
```

在对话里输入：

```
/swarm-add-planner
```

它会调用 `workspace_add(role="planner")`，并把 `WORKSPACE_ID` 写入 `.agent_swarm/workspace.md`；
三个 harness（opencode / claude / deepseek）都支持。之后平台网页出现「规划器」页。

> 若还没装 harness 插件：在平台管理页复制「插件安装」一键命令执行，或跑平台仓库
> `deploy/install.sh -Only opencode`（Windows `deploy\install.ps1 -Only opencode`）。

## 4. 自检

```bash
.venv/bin/planner doctor            # Python/依赖/配置/DB/平台 MCP/控制通道
.venv/bin/planner doctor --offline  # 跳过联网
.venv/bin/planner ping              # 只测平台 MCP + WS
```

## 5. 常驻（开机自启）

`deploy/install.sh|ps1` 默认已注册；手动管理：

```bash
.venv/bin/planner service install [--scope user|system] [--serve-cmd '...']
.venv/bin/planner service status
.venv/bin/planner service print      # 只打印将写入的文件与命令（不落盘）
.venv/bin/planner service uninstall
```

- **Linux**：`~/.config/systemd/user/agent-swarm-planner.service` + `systemctl --user enable --now`；免登录常驻执行 `loginctl enable-linger $USER`。
- **Windows**：`.agent_swarm\serve.cmd` + 写入注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`（登录自启，当前用户、无需管理员；`--scope system` 写 `HKLM`）。
- **macOS**：`~/Library/LaunchAgents/agent-swarm-planner.plist` + `launchctl load`。

守护做的事：订阅 `/ws/nexus` 观察 worker 终态 → 回写本地任务 → tick 提升就绪/注入提示词 → 控制通道 `/ws/planner`（收平台操作、推状态快照、推人工待办 notify）。

> 关键：**守护和 harness 都要在线**（平台据此视为可派发/在线），否则注入的规划提示词没人接；也可把工作区设 `execution_mode=background`。

## 6. 命令速查

| 命令 | 说明 |
|---|---|
| `deploy/install.sh` \| `deploy\install.ps1` | 一键安装：venv + pip install + 注册服务 |
| `planner setup` | 配置向导（写 `.env`、建库、校验） |
| `planner doctor [--offline]` | 安装自检 |
| `planner service install\|status\|uninstall\|print` | 开机自启 |
| `planner ping` / `planner workspaces` | 平台连通 / 可见工作区 |
| `planner info` / `planner status` | 解析后的配置 / 跨目标概览 |
| `planner serve [--no-send]` | 前台运行守护（调试用） |

（`planner` ＝ `.venv/bin/planner`；Windows 为 `.venv\Scripts\planner.exe`。）

## 7. 排障

| 现象 | 处理 |
|---|---|
| `doctor` 里 `platform.mcp` FAIL | 检查 `AGENT_SWARM_SERVER` 可达、API Key 正确 |
| `control.ws` FAIL | 平台是否含 `/ws/planner`；反向代理放行 WebSocket |
| `workspace.role` 非 planner | 在 harness 重新执行 `/swarm-add-planner` |
| 平台显示工作区离线 | 守护没跑：`planner service status` / 看 `data/serve.*.log`；或 harness 不在 |
| 派发 409 | planner 工作区不可派发：开 harness 或设 `execution_mode=background` |
| 中文乱码（Windows） | `chcp 65001` + `$env:PYTHONUTF8=1` |

## 8. 卸载

```bash
.venv/bin/planner service uninstall
# 删除 .venv；按需删除 .env / data/ / .agent_swarm/
# harness 插件卸载见平台仓库对应 install 脚本
```
