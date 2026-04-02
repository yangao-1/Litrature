Param(
  [string]$RepoDir = ".",
  [string]$VaultDir = "C:/Users/yangao/OneDrive - UAB/Obsidian/自动文献汇总",
  [ValidateSet("crossref", "google_scholar", "mixed")]
  [string]$Source = "crossref",
  [int]$DaysBack = 90,
  [int]$Limit = 20,
  [int]$MaxTotal = 120,
  [bool]$ExecuteZotero = $true,
  [ValidateSet("api", "mcp")]
  [string]$ZoteroBackend = "mcp",
  [ValidateSet("users", "groups")]
  [string]$ZoteroLibraryType = "users",
  [string]$ZoteroLibraryId = "",
  [string]$ZoteroUserId = "REPLACE_WITH_YOUR_ZOTERO_USER_ID",
  [string]$ZoteroApiKey = "REPLACE_WITH_YOUR_ZOTERO_API_KEY",
  [string]$ZoteroMcpEndpoint = "http://127.0.0.1:8765/mcp",
  [string]$ZoteroMcpMethod = "zotero.create_item",
  [string]$SerpApiKey = "REPLACE_WITH_YOUR_SERPAPI_API_KEY",
  [string]$UnpaywallEmail = "REPLACE_WITH_YOUR_UNPAYWALL_EMAIL",
  [string]$OpenAIApiKey = "REPLACE_WITH_YOUR_OPENAI_API_KEY",
  [string]$OpenAIModel = "gpt-4.1",
  [string]$LocalPdfDir = "data/pdf_library"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $RepoDir

# Ensure Obsidian vault path exists and surface the exact destination in logs.
$resolvedVaultDir = $VaultDir
if (-not (Test-Path $resolvedVaultDir)) {
  New-Item -ItemType Directory -Path $resolvedVaultDir -Force | Out-Null
}
Write-Host "Obsidian 导出目录: $resolvedVaultDir"

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
  "--source", "$Source",
  "--days-back", "$DaysBack",
  "--limit", "$Limit",
  "--max-total", "$MaxTotal",
  "--vault-dir", "$resolvedVaultDir",
  "--zotero-backend", "$ZoteroBackend",
  "--disable-local-pdf-cache",
  "--reset-dedup-index",
  "--require-openai-summary"
)

if ($ExecuteZotero) {
  if ($ZoteroBackend -eq "api") {
    $effectiveLibraryId = $ZoteroLibraryId
    if (-not $effectiveLibraryId) {
      $effectiveLibraryId = $ZoteroUserId
    }
    if ($effectiveLibraryId -eq "REPLACE_WITH_YOUR_ZOTERO_USER_ID" -or $ZoteroApiKey -eq "REPLACE_WITH_YOUR_ZOTERO_API_KEY") {
      throw "API 模式下请先填写 ZoteroUserId 和 ZoteroApiKey。"
    }
    $env:ZOTERO_USER_ID = $ZoteroUserId
    $env:ZOTERO_LIBRARY_TYPE = $ZoteroLibraryType
    $env:ZOTERO_LIBRARY_ID = $effectiveLibraryId
    $env:ZOTERO_API_KEY = $ZoteroApiKey
  } else {
    if (-not $ZoteroMcpEndpoint) {
      throw "MCP 模式下请设置 ZoteroMcpEndpoint。"
    }
    $env:ZOTERO_MCP_ENDPOINT = $ZoteroMcpEndpoint
    $env:ZOTERO_MCP_METHOD = $ZoteroMcpMethod
  }
  $argsList += "--execute-zotero"
}

if ($Source -eq "google_scholar" -or $Source -eq "mixed") {
  if ($SerpApiKey -eq "REPLACE_WITH_YOUR_SERPAPI_API_KEY") {
    throw "使用 google_scholar 或 mixed 需要填写 SerpApiKey。"
  }
  $env:SERPAPI_API_KEY = $SerpApiKey
}

if ($UnpaywallEmail -ne "REPLACE_WITH_YOUR_UNPAYWALL_EMAIL") {
  $env:UNPAYWALL_EMAIL = $UnpaywallEmail
}

if ($OpenAIApiKey -ne "REPLACE_WITH_YOUR_OPENAI_API_KEY") {
  $env:OPENAI_API_KEY = $OpenAIApiKey
  $env:OPENAI_MODEL = $OpenAIModel
}

$env:PYTHONPATH = "src"
& $pythonExe @argsList
Write-Host "完成：已执行每日流程（Zotero真实写入 + Obsidian导出，不单独缓存PDF）。"
