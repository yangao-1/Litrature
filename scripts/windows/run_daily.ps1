Param(
  [string]$RepoDir = ".",
  [string]$VaultDir = "",
  [ValidateSet("crossref", "google_scholar", "mixed")]
  [string]$Source = "google_scholar",
  [string]$SearchQueryLine = "",
  [int]$DaysBack = 90,
  [int]$Limit = 20,
  [int]$MaxTotal = 120,
  [bool]$ExecuteZotero = $true,
  [bool]$AllowZoteroZeroSuccess = $true,
  [ValidateSet("api", "mcp")]
  [string]$ZoteroBackend = "mcp",
  [ValidateSet("users", "groups")]
  [string]$ZoteroLibraryType = "users",
  [string]$ZoteroLibraryId = "",
  [string]$ZoteroUserId = "REPLACE_WITH_YOUR_ZOTERO_USER_ID",
  [string]$ZoteroApiKey = "REPLACE_WITH_YOUR_ZOTERO_API_KEY",
  [string]$ZoteroMcpEndpoint = "http://127.0.0.1:23120/mcp",
  [string]$ZoteroMcpMethod = "auto",
  [string]$ZoteroMcpSessionId = "",
  [string]$SerpApiKey = "REPLACE_WITH_YOUR_SERPAPI_API_KEY",
  [string]$UnpaywallEmail = "REPLACE_WITH_YOUR_UNPAYWALL_EMAIL",
  [string]$OpenAIApiKey = "REPLACE_WITH_YOUR_OPENAI_API_KEY",
  [string]$OpenAIModel = "gpt-4.1",
  [string]$LocalPdfDir = "data/pdf_library"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $RepoDir

# Prefer explicit parameter, then env var, then ASCII-safe fallback.
if (-not $VaultDir) {
  $VaultDir = $env:OBSIDIAN_VAULT_DIR
}
if (-not $VaultDir) {
  $VaultDir = "obsidian_export"
}

# Ensure Obsidian vault path exists and surface the exact destination in logs.
$resolvedVaultDir = $VaultDir
if (-not (Test-Path $resolvedVaultDir)) {
  New-Item -ItemType Directory -Path $resolvedVaultDir -Force | Out-Null
}
Write-Host "Obsidian output dir: $resolvedVaultDir"

function Test-McpEndpoint {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Endpoint
  )

  try {
    $probeBody = '{"jsonrpc":"2.0","id":"litrature-probe","method":"ping","params":{}}'
    Invoke-WebRequest -Uri $Endpoint -Method POST -ContentType "application/json" -Headers @{ "Accept" = "application/json, text/event-stream" } -Body $probeBody -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Resolve-PythonLauncher {
  if (Get-Command py -ErrorAction SilentlyContinue) { return "py -3" }
  if (Get-Command python -ErrorAction SilentlyContinue) { return "python" }
  throw "Python 3 not found. Please install Python 3 and add python.exe to PATH."
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
  throw "Virtual environment creation failed: .venv/Scripts/python.exe not found."
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

if (-not $SearchQueryLine) {
  $SearchQueryLine = Read-Host "请输入检索关键词（多个用;分隔）"
}
if ($SearchQueryLine) {
  $argsList += "--query-line"
  $argsList += "$SearchQueryLine"
}

if ($ExecuteZotero) {
  if ($ZoteroBackend -eq "api") {
    $effectiveLibraryId = $ZoteroLibraryId
    if (-not $effectiveLibraryId) {
      $effectiveLibraryId = $ZoteroUserId
    }
    if ($effectiveLibraryId -eq "REPLACE_WITH_YOUR_ZOTERO_USER_ID" -or $ZoteroApiKey -eq "REPLACE_WITH_YOUR_ZOTERO_API_KEY") {
      throw "In API mode, please set ZoteroUserId and ZoteroApiKey first."
    }
    $env:ZOTERO_USER_ID = $ZoteroUserId
    $env:ZOTERO_LIBRARY_TYPE = $ZoteroLibraryType
    $env:ZOTERO_LIBRARY_ID = $effectiveLibraryId
    $env:ZOTERO_API_KEY = $ZoteroApiKey
  } else {
    if (-not $ZoteroMcpEndpoint) {
      throw "In MCP mode, please set ZoteroMcpEndpoint."
    }
    if (-not (Test-McpEndpoint -Endpoint $ZoteroMcpEndpoint)) {
      throw "Cannot connect to Zotero MCP endpoint: $ZoteroMcpEndpoint . Please start Zotero and MCP service first, then retry."
    }
    $env:ZOTERO_MCP_ENDPOINT = $ZoteroMcpEndpoint
    $env:ZOTERO_MCP_METHOD = $ZoteroMcpMethod
    if ($ZoteroMcpSessionId) {
      $env:ZOTERO_MCP_SESSION_ID = $ZoteroMcpSessionId
    }
  }
  $argsList += "--execute-zotero"
  if ($AllowZoteroZeroSuccess) {
    $argsList += "--allow-zotero-zero-success"
  }
}

if ($Source -eq "google_scholar" -or $Source -eq "mixed") {
  if ($SerpApiKey -eq "REPLACE_WITH_YOUR_SERPAPI_API_KEY") {
    throw "SerpApiKey is required when source is google_scholar or mixed."
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

if (-not $env:OPENAI_API_KEY) {
  throw "OPENAI_API_KEY is missing. Pass -OpenAIApiKey or set environment variable OPENAI_API_KEY."
}

$env:OPENAI_MODEL = $OpenAIModel

$env:PYTHONPATH = "src"
& $pythonExe @argsList
if ($LASTEXITCODE -ne 0) {
  $logPath = Join-Path $PWD "logs/litrature.log"
  if (Test-Path $logPath) {
    Write-Host "--- litrature.log (last 80 lines) ---"
    Get-Content -Path $logPath -Tail 80
    Write-Host "--- end of litrature.log ---"
  }

  $zoteroOut = Join-Path $PWD "data/zotero.synced.jsonl"
  if (Test-Path $zoteroOut) {
    Write-Host "--- zotero failure samples ---"
    $failLines = @()
    foreach ($line in Get-Content -Path $zoteroOut) {
      if (-not $line) { continue }
      try {
        $obj = $line | ConvertFrom-Json
        if ($null -ne $obj.zotero_result -and -not [bool]$obj.zotero_result.ok) {
          $sample = [PSCustomObject]@{
            title  = [string]$obj.title
            status = [int]($obj.zotero_result.status)
            body   = ([string]$obj.zotero_result.body)
          }
          $failLines += $sample
          if ($failLines.Count -ge 3) { break }
        }
      } catch {
      }
    }

    if ($failLines.Count -gt 0) {
      $failLines | ForEach-Object {
        $body = $_.body
        if ($body.Length -gt 300) { $body = $body.Substring(0, 300) }
        Write-Host ("status=" + $_.status + " | title=" + $_.title)
        Write-Host ("body=" + $body)
      }
    }
    Write-Host "--- end of zotero failure samples ---"
  }

  throw "Daily workflow failed. Python exit code: $LASTEXITCODE"
}

Write-Host "Done: daily workflow finished (real Zotero write + Obsidian export, no standalone PDF cache)."
