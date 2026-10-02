#!/usr/bin/env bash
# agent-swarm-planner 安装脚本（Linux / macOS）
#
# 在仓库里执行：./deploy/install.sh [选项]
#   --server URL         平台地址（缺省沿用 .env / 127.0.0.1:8700）
#   --api-key KEY        账号 API Key
#   --workspace-id WID   planner 工作区 ID（可留空，随后由 /swarm-add-planner 写入）
#   --scope user|system  开机自启级别（默认 user，system 需 root）
#   --no-service         不注册开机自启
#   --no-verify          跳过配置时的连通性校验
#   --offline            doctor 跳过联网项
#
# 做三件事：建 venv → pip install → 注册 python 守护开机自启；
# 最后提示你在 harness（opencode/claude/deepseek）里执行 /swarm-add-planner 完成注册。
set -euo pipefail

SERVER=""; API_KEY=""; WORKSPACE_ID=""
SCOPE="user"; DO_SERVICE=1; VERIFY=1; OFFLINE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --server) SERVER="$2"; shift 2;;
    --api-key) API_KEY="$2"; shift 2;;
    --workspace-id) WORKSPACE_ID="$2"; shift 2;;
    --scope) SCOPE="$2"; shift 2;;
    --no-service) DO_SERVICE=0; shift;;
    --no-verify) VERIFY=0; shift;;
    --offline) OFFLINE=1; shift;;
    -h|--help) sed -n '2,15p' "$0"; exit 0;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python3}"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
PLANNER="$VENV/bin/planner"
SERVE_CMD="\"$PLANNER\" serve"

echo "==> 检查 Python"
"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 11):
    sys.exit("需要 Python >= 3.11，当前 %s" % sys.version.split()[0])
print("Python", sys.version.split()[0], "OK")
PY

echo "==> 创建虚拟环境 $VENV"
"$PYTHON" -m venv "$VENV"

echo "==> 安装依赖（pip install）"
"$PY" -m pip install --upgrade pip >/dev/null
"$PY" -m pip install -r requirements.txt
"$PY" -m pip install -e . >/dev/null     # 生成 venv 内 planner 命令

echo "==> 初始化配置（.env / 数据库 / 连通校验）"
SETUP_ARGS=(setup --yes)
[ -n "$SERVER" ] && SETUP_ARGS+=(--server "$SERVER")
[ -n "$API_KEY" ] && SETUP_ARGS+=(--api-key "$API_KEY")
[ -n "$WORKSPACE_ID" ] && SETUP_ARGS+=(--workspace-id "$WORKSPACE_ID")
[ "$VERIFY" = 0 ] && SETUP_ARGS+=(--no-verify)
"$PY" -m planner_core "${SETUP_ARGS[@]}"

echo "==> 自检"
DOCTOR_ARGS=(doctor)
[ "$OFFLINE" = 1 ] && DOCTOR_ARGS+=(--offline)
"$PY" -m planner_core "${DOCTOR_ARGS[@]}" || true

if [ "$DO_SERVICE" = 1 ]; then
  echo "==> 注册 python 守护开机自启（scope=$SCOPE）"
  "$PY" -m planner_core service install --scope "$SCOPE" --home "$ROOT" --serve-cmd "$SERVE_CMD"
fi

cat <<EOF

====================================================================
安装完成。最后一步：在 harness 里把本目录注册为 planner 工作区
--------------------------------------------------------------------
1) 进入本目录并启动你的 agent harness（opencode / claude / deepseek 任一）：
     cd "$ROOT"
     opencode        # 或 claude / dsh，按你已安装的 harness
   （若尚未安装该 harness 的 agent-swarm 插件：在平台管理页复制"插件安装"
     一键命令执行，或跑平台仓库 deploy/install.sh -Only <harness>）

2) 在 harness 的对话里输入：
     /swarm-add-planner
   它会调用 workspace_add(role="planner")，并把 WORKSPACE_ID 写入
   .agent_swarm/workspace.md

3) 完成后到平台「规划器」页即可建目标、审批拆解、验收。
====================================================================
EOF

if [ "$DO_SERVICE" = 1 ] && command -v loginctl >/dev/null 2>&1; then
  echo "提示：免登录常驻可执行  loginctl enable-linger \$USER"
fi
