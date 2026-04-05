@echo off
setlocal
set REPO_DIR=%~dp0\..\..
if "%OBSIDIAN_VAULT_DIR%"=="" (
  set "VAULT_DIR=obsidian_export"
) else (
  set "VAULT_DIR=%OBSIDIAN_VAULT_DIR%"
)
set SOURCE=google_scholar
set DAYS_BACK=90
set SEARCH_QUERY_LINE=
set ZOTERO_BACKEND=mcp
set ZOTERO_LIBRARY_TYPE=users
set ZOTERO_LIBRARY_ID=
set ZOTERO_USER_ID=REPLACE_WITH_YOUR_ZOTERO_USER_ID
set ZOTERO_API_KEY=REPLACE_WITH_YOUR_ZOTERO_API_KEY
set ZOTERO_MCP_ENDPOINT=http://127.0.0.1:23120/mcp
set ZOTERO_MCP_METHOD=auto
set ZOTERO_MCP_SESSION_ID=
set SERPAPI_API_KEY=REPLACE_WITH_YOUR_SERPAPI_API_KEY
set UNPAYWALL_EMAIL=REPLACE_WITH_YOUR_UNPAYWALL_EMAIL
set SCIHUB_BASE_URL=
set OPENAI_API_KEY=REPLACE_WITH_YOUR_OPENAI_API_KEY
set OPENAI_MODEL=gpt-4.1
set LOCAL_PDF_DIR=data/pdf_library

if /I "%ZOTERO_BACKEND%"=="api" (
  if "%ZOTERO_LIBRARY_ID%"=="" (
    set ZOTERO_LIBRARY_ID=%ZOTERO_USER_ID%
  )
  if "%ZOTERO_LIBRARY_ID%"=="REPLACE_WITH_YOUR_ZOTERO_USER_ID" (
    echo API 模式请先填写 ZOTERO_LIBRARY_ID 或 ZOTERO_USER_ID
    exit /b 1
  )
  if "%ZOTERO_API_KEY%"=="REPLACE_WITH_YOUR_ZOTERO_API_KEY" (
    echo API 模式请先填写 ZOTERO_API_KEY
    exit /b 1
  )
)

if /I "%ZOTERO_BACKEND%"=="mcp" (
  echo MCP mode enabled. Please ensure Zotero MCP service is running at %ZOTERO_MCP_ENDPOINT%
)

if /I "%SOURCE%"=="google_scholar" (
  if "%SERPAPI_API_KEY%"=="REPLACE_WITH_YOUR_SERPAPI_API_KEY" (
    echo google_scholar 模式请先填写 SERPAPI_API_KEY
    exit /b 1
  )
)

if /I "%SOURCE%"=="mixed" (
  if "%SERPAPI_API_KEY%"=="REPLACE_WITH_YOUR_SERPAPI_API_KEY" (
    echo mixed 模式请先填写 SERPAPI_API_KEY
    exit /b 1
  )
)

cd /d %REPO_DIR%
set /p SEARCH_QUERY_LINE=请输入检索关键词（多个用;分隔）: 
if not "%SCIHUB_BASE_URL%"=="" (
  echo DOI mirror enabled via SCIHUB_BASE_URL
)
if not exist "%VAULT_DIR%" mkdir "%VAULT_DIR%"
echo Obsidian 导出目录: %VAULT_DIR%
if not exist .venv (
  python -m venv .venv
)

set PYTHONPATH=src
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m litrature run-daily --source "%SOURCE%" --query-line "%SEARCH_QUERY_LINE%" --days-back %DAYS_BACK% --limit 20 --max-total 120 --vault-dir "%VAULT_DIR%" --zotero-backend "%ZOTERO_BACKEND%" --disable-local-pdf-cache --reset-dedup-index --execute-zotero --allow-zotero-zero-success --require-openai-summary
if errorlevel 1 (
  echo Daily workflow failed. Please check OPENAI_API_KEY/Zotero settings and logs.
  exit /b 1
)

echo 完成：已执行每日流程（真实模式，不单独缓存PDF）。
endlocal
