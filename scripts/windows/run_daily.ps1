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

if (-Not (Test-Path ".venv")) {
  python -m venv .venv
}

$pythonExe = Join-Path $PWD ".venv/Scripts/python.exe"
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
