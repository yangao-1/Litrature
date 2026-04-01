Param(
  [string]$RepoDir = ".",
  [string]$VaultDir = "C:/Users/yangao/OneDrive - UAB/Obsidian/自动文献汇总",
  [int]$Limit = 20,
  [int]$MaxTotal = 120,
  [switch]$ExecuteZotero
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $RepoDir

function Resolve-PythonLauncher {
  if (Get-Command py -ErrorAction SilentlyContinue) { return "py -3" }
  if (Get-Command python -ErrorAction SilentlyContinue) { return "python" }
  throw "未找到 Python。请先安装 Python 3，并勾选 Add python.exe to PATH。"
}

$pythonExe = Join-Path $PWD ".venv/Scripts/python.exe"
if (-Not (Test-Path $pythonExe)) {
  $launcher = Resolve-PythonLauncher
  if (Test-Path ".venv") {
    Remove-Item -Recurse -Force ".venv"
  }
  Invoke-Expression "$launcher -m venv .venv"
}

if (-Not (Test-Path $pythonExe)) {
  throw "虚拟环境创建失败：未找到 .venv/Scripts/python.exe"
}

& $pythonExe -m pip install -r requirements.txt

$argsList = @(
  "-m", "litrature", "run-daily",
  "--limit", "$Limit",
  "--max-total", "$MaxTotal",
  "--vault-dir", "$VaultDir"
)

if ($ExecuteZotero) {
  $argsList += "--execute-zotero"
}

$env:PYTHONPATH = "src"
& $pythonExe @argsList
Write-Host "完成：已执行每日流程。"
