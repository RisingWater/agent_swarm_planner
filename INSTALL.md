# 安装 agent-swarm-planner

把本机变成 `agent_swarm` 平台上的一个**规划器工作区**：装 `planner-core`（确定性内核）→ 配置 →
注册 `role=planner` 工作区 → 常驻守护（开机自启）。

> 设计原则：**确定性归 Python，智能归 agent**。planner-core 不调用任何 LLM；拆解/决策由
> planner 工作区里运行的 agent（opencode / claude / dsh）完成。

## 0. 先决条件

| 项 | 要求 |
|---|---|
| Python | ≥ 3.11 |
| 平台 | 可访问的 `agent_swarm` 服务（默认 `http://127.0.0.1:8700`），且已含 **planner 特性**（`role=planner` + `WS /ws/planner` + 规划器页；目前在这些在平台 `dev` 分支） |
| 账号 | 一个 API Key（平台账号页可复制，`as_...`） |
| harness（可选但推荐） | 会在 planner 工作区里跑一个 agent（如 opencode）；否则把工作区设为 `execution_mode=background` |

## 1. 安装 planner-core

### 方式 A：pipx（推荐，隔离、跨平台）

```bash
# Linux / macOS
pipx install "git+https://<your-repo>/agent-swarm-planner.git"   # 或 pipx install /path/to/repo

# Windows PowerShell
python -m pip install --user pipx ; python -m pipx ensurepath
pipx install .
```

安装后得到全局命令 `planner`（入口 `planner_core.cli:main` 已在 `pyproject.toml` 声明）。

### 方式 B：源码 + venv（开发/调试）

```bash
git clone <repo> agent-swarm-planner && cd agent-swarm-planner
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt      # Windows: .\.venv\Scripts\python.exe
```

### 一键脚本

- Linux/macOS：`./install.sh [/path/to/repo]`（环境变量 `SERVER` / `API_KEY` / `WORKSPACE_ID` / `NO_SERVICE=1`）
- Windows：`powershell -ExecutionPolicy Bypass -File install.ps1 -Source <path-or-git> [-Server ...] [-ApiKey ...] [-WorkspaceId ...] [-NoService]`

## 2. 配置

```bash
planner setup            # 交互式：平台地址 / API Key / 工作区 ID，写 .env，建库，并校验连通
# 非交互：
planner setup --server http://127.0.0.1:8700 --api-key as_xxx --workspace-id <WID> --yes
planner setup --no-verify ...     # 跳过连通性校验
```

- 配置写入**工作根目录**的 `.env`（默认＝当前目录；源码仓库里＝仓库根）。
- `planner` 以“当前目录即项目”工作：`.env`、`.agent_swarm/workspace.md`、`data/planner.db` 都在当前目录下。
- 可用 `PLANNER_HOME=/path` 显式指定工作根目录。
- 配置解析优先级：进程环境变量 → `.env` → `~/.config/opencode/agent-swarm.json`（`serverUrl`/`apiKey`）→ `.agent_swarm/workspace.md` 的 `WORKSPACE_ID:`。

## 3. 注册为规划器工作区（role=planner）

在**planner 工作区目录**里用 harness 执行：

```
/swarm-add-planner
```

它会调用平台 MCP `workspace_add(role="planner")`，把 `WORKSPACE_ID` 写进
`.agent_swarm/workspace.md`（返回 `need_summary=true` 时还会生成 purpose/capabilities）。
也可用 CLI：`planner register --role planner`，然后把返回的 `workspace_id` 写入
`.agent_swarm/workspace.md` 的 `WORKSPACE_ID:` 行。

之后平台网页会出现「规划器」页，可建目标、审批拆解、验收任务。

## 4. 自检

```bash
planner doctor            # 全套：Python/依赖/配置/DB/平台 MCP/控制通道
planner doctor --offline  # 跳过联网
planner ping              # 只测平台 MCP + WS
```

逐项 `OK/FAIL`；全绿再继续。

## 5. 常驻（开机自启）

```bash
planner service install            # 默认 user 级（Linux systemd --user / Windows 登录计划任务 / macOS LaunchAgent）
planner service install --scope system   # Linux 系统级（需 root，写入 /etc/systemd/system）
planner service status             # 查看是否已安装/是否 active
planner service print              # 只打印将写入的文件与命令（不落盘，便于审查）
planner service uninstall          # 卸载自启
```

- **Linux**：写 `~/.config/systemd/user/agent-swarm-planner.service` 并 `systemctl --user enable --now`。
  免登录常驻需 `loginctl enable-linger $USER`。
- **Windows**：写 `.<root>/.agent_swarm/serve.cmd` 并注册登录触发的计划任务（`schtasks /SC ONLOGON`，当前用户、无需管理员）。
- **macOS**：写 `~/Library/LaunchAgents/agent-swarm-planner.plist` 并 `launchctl load`。

守护做的事：订阅 `/ws/nexus` 观察 worker 终态 → 回写本地任务 → tick 提升就绪/注入提示词 →
控制通道 `/ws/planner`（收平台操作、推状态快照、推人工待办 `notify`）。

> 关键：**守护必须在线**（平台据此把工作区视为可派发/在线）；**harness 也要在**，否则注入的规划
> 提示词没人接（或把工作区设 `execution_mode=background`）。

## 6. 命令速查

| 命令 | 说明 |
|---|---|
| `planner setup` | 配置向导（写 `.env`、建库、校验） |
| `planner doctor [--offline]` | 安装自检 |
| `planner service install\|status\|uninstall\|print` | 开机自启 |
| `planner ping` / `planner workspaces` | 平台连通 / 可见工作区 |
| `planner info` / `planner status` | 解析后的配置 / 跨目标概览 |
| `planner serve [--no-send]` | 前台运行守护（调试用） |

## 7. 排障

| 现象 | 处理 |
|---|---|
| `planner doctor` 里 `platform.mcp` FAIL | 检查 `AGENT_SWARM_SERVER` 是否可达、API Key 是否正确 |
| `control.ws` FAIL | 平台是否含 `/ws/planner`（需 planner 特性分支）；反向代理要放行 WebSocket |
| `workspace.role` 非 planner | 重新执行 `/swarm-add-planner` 或 `planner register` |
| 平台显示工作区离线 | 守护没在跑：`planner service status` / 看日志 `data/serve.*.log` |
| 派发 409 | planner 工作区不可派发：开 TUI 或设 `execution_mode=background` |
| 中文乱码（Windows） | `chcp 65001` + `$env:PYTHONUTF8=1` |

## 8. 卸载

```bash
planner service uninstall
pipx uninstall agent-swarm-planner        # 或删掉 venv
# 按需删除工作目录下的 .env / data/ / .agent_swarm/
```
