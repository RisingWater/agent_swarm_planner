# agent-swarm-planner 安装脚本（Windows PowerShell）
#
# 在仓库里执行：
#   powershell -ExecutionPolicy Bypass -File .\deploy\install.ps1 `
#       [-Server http://127.0.0.1:8700] [-ApiKey as_xxx] [-WorkspaceId <WID>] `
#       [-Scope user|system] [-NoService] [-NoVerify] [-Offline]
#
# 做三件事：建 venv → pip install → 注册 python 守护开机自启；
# 最后提示你在 harness（opencode/claude/deepseek）里执行 /swarm-add-planner 完成注册。
param(
  [string]$Server = "",
  [string]$ApiKey = "",
  [string]$WorkspaceId = "",
  [ValidateSet("user", "system")][string]$Scope = "user",
  [switch]$NoService,
  [switch]$NoVerify,
  [switch]$Offline,
  [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$venv = Join-Path $root ".venv"
$py = Join-Path $venv "Scripts\python.exe"
$plannerExe = Join-Path $venv "Scripts\planner.exe"
$serveCmd = "`"$plannerExe`" serve"

Write-Host "==> 检查 Python"
& $Python -c "import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "需要 Python >= 3.11" }

Write-Host "==> 创建虚拟环境 $venv"
& $Python -m venv $venv

Write-Host "==> 安装依赖（pip install）"
& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install -r requirements.txt
& $py -m pip install -e . | Out-Null     # 生成 venv 内 planner 命令

Write-Host "==> 初始化配置（.env / 数据库 / 连通校验）"
$setupArgs = @("setup", "--yes")
if ($Server)      { $setupArgs += @("--server", $Server) }
if ($ApiKey)      { $setupArgs += @("--api-key", $ApiKey) }
if ($WorkspaceId) { $setupArgs += @("--workspace-id", $WorkspaceId) }
if ($NoVerify)    { $setupArgs += @("--no-verify") }
& $py -m planner_core @setupArgs

Write-Host "==> 自检"
$doctorArgs = @("doctor")
if ($Offline) { $doctorArgs += @("--offline") }
& $py -m planner_core @doctorArgs
if ($LASTEXITCODE -ne 0) { Write-Warning "doctor 有未通过项，请按提示修复" }

if (-not $NoService) {
  Write-Host "==> 注册 python 守护开机自启（scope=$Scope）"
  # 经环境变量传（PowerShell 5.1 直传内嵌引号会被吞，env 保留原样）
  $env:PLANNER_SERVE_CMD = $serveCmd
  & $py -m planner_core service install --scope $Scope --home $root
}

Write-Host ""
Write-Host "===================================================================="
Write-Host "安装完成。最后一步：在 harness 里把本目录注册为 planner 工作区"
Write-Host "--------------------------------------------------------------------"
Write-Host "1) 进入本目录并启动你的 agent harness（opencode / claude / deepseek 任一）："
Write-Host "     cd `"$root`""
Write-Host "     opencode        # 或 claude / dsh，按你已安装的 harness"
Write-Host "   （若尚未安装该 harness 的 agent-swarm 插件：在平台管理页复制`"插件安装`""
Write-Host "     一键命令执行，或跑平台仓库 deploy/install.ps1 -Only <harness>）"
Write-Host ""
Write-Host "2) 在 harness 的对话里输入："
Write-Host "     /swarm-add-planner"
Write-Host "   它会调用 workspace_add(role=`"planner`")，并把 WORKSPACE_ID 写入"
Write-Host "   .agent_swarm/workspace.md"
Write-Host ""
Write-Host "3) 完成后到平台「规划器」页即可建目标、审批拆解、验收。"
Write-Host "===================================================================="
