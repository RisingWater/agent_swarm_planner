# agent-swarm-planner 一键安装（Windows PowerShell）
# 用法：
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Source <repo-path-or-git> `
#       [-Server http://127.0.0.1:8700] [-ApiKey as_xxx] [-WorkspaceId <WID>] [-NoService]
param(
  [string]$Source = ".",
  [string]$Server = "",
  [string]$ApiKey = "",
  [string]$WorkspaceId = "",
  [switch]$NoService
)

$ErrorActionPreference = "Stop"
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

Write-Host "==> 检查 Python"
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { throw "未找到 python，请先安装 Python >= 3.11" }
& python -c "import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "需要 Python >= 3.11" }

Write-Host "==> 确保 pipx"
if (-not (Get-Command pipx -ErrorAction SilentlyContinue)) {
  & python -m pip install --user pipx
  & python -m pipx ensurepath
}

Write-Host "==> 安装 planner-core（pipx）"
& pipx install --force $Source

Write-Host "==> 配置（写 .env / 建库 / 校验）"
$setupArgs = @("setup", "--yes")
if ($Server)      { $setupArgs += @("--server", $Server) }
if ($ApiKey)      { $setupArgs += @("--api-key", $ApiKey) }
if ($WorkspaceId) { $setupArgs += @("--workspace-id", $WorkspaceId) }
& planner @setupArgs

Write-Host "==> 自检"
& planner doctor
if ($LASTEXITCODE -ne 0) { Write-Warning "doctor 有未通过项，请按提示修复" }

if (-not $NoService) {
  Write-Host "==> 注册登录自启（计划任务）"
  & planner service install
}

Write-Host ""
Write-Host "完成。下一步："
Write-Host "  1) 在 planner 工作区目录用 harness 执行 /swarm-add-planner（拿到 WORKSPACE_ID）"
Write-Host "  2) planner doctor        # 复检"
Write-Host "  3) 打开平台「规划器」页建目标"
