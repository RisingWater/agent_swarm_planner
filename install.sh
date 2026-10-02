#!/usr/bin/env bash
# agent-swarm-planner 一键安装（Linux / macOS）
# 用法：./install.sh [/path/to/repo | git-url]
# 环境变量：SERVER / API_KEY / WORKSPACE_ID / NO_SERVICE=1 / PYTHON=python3
set -euo pipefail

SOURCE="${1:-.}"
PYTHON="${PYTHON:-python3}"
SERVER="${SERVER:-}"
API_KEY="${API_KEY:-}"
WORKSPACE_ID="${WORKSPACE_ID:-}"

echo "==> 检查 Python"
"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 11):
    sys.exit("需要 Python >= 3.11，当前 %s" % sys.version.split()[0])
print("Python", sys.version.split()[0], "OK")
PY

echo "==> 确保 pipx"
if ! command -v pipx >/dev/null 2>&1; then
  "$PYTHON" -m pip install --user pipx
  "$PYTHON" -m pipx ensurepath || true
fi

echo "==> 安装 planner-core（pipx）"
pipx install --force "$SOURCE"

echo "==> 配置（写 .env / 建库 / 校验）"
ARGS=(--yes)
[ -n "$SERVER" ] && ARGS+=(--server "$SERVER")
[ -n "$API_KEY" ] && ARGS+=(--api-key "$API_KEY")
[ -n "$WORKSPACE_ID" ] && ARGS+=(--workspace-id "$WORKSPACE_ID")
planner setup "${ARGS[@]}"

echo "==> 自检"
planner doctor || true

if [ "${NO_SERVICE:-0}" != "1" ]; then
  echo "==> 注册开机自启（user 级）"
  planner service install --scope user
fi

echo
echo "完成。下一步："
echo "  1) 在 planner 工作区目录用 harness 执行 /swarm-add-planner（拿到 WORKSPACE_ID）"
echo "  2) planner doctor        # 复检"
echo "  3) 打开平台「规划器」页建目标"
if [ "${NO_SERVICE:-0}" != "1" ] && command -v loginctl >/dev/null 2>&1; then
  echo "  提示：免登录常驻可执行 loginctl enable-linger $USER"
fi
