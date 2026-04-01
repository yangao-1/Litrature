@echo off
setlocal
set REPO_DIR=%~dp0\..\..
set VAULT_DIR=C:/Users/yangao/OneDrive - UAB/Obsidian/自动文献汇总
set SOURCE=crossref
set ZOTERO_BACKEND=api
set ZOTERO_USER_ID=REPLACE_WITH_YOUR_ZOTERO_USER_ID
set ZOTERO_API_KEY=REPLACE_WITH_YOUR_ZOTERO_API_KEY
set ZOTERO_MCP_ENDPOINT=http://127.0.0.1:8765/mcp
set ZOTERO_MCP_METHOD=zotero.create_item
set SERPAPI_API_KEY=REPLACE_WITH_YOUR_SERPAPI_API_KEY
set UNPAYWALL_EMAIL=REPLACE_WITH_YOUR_UNPAYWALL_EMAIL
set OPENAI_API_KEY=REPLACE_WITH_YOUR_OPENAI_API_KEY
set OPENAI_MODEL=gpt-4.1-mini

if /I "%ZOTERO_BACKEND%"=="api" (
  if "%ZOTERO_USER_ID%"=="REPLACE_WITH_YOUR_ZOTERO_USER_ID" (
    echo API 模式请先填写 ZOTERO_USER_ID
    exit /b 1
  )
  if "%ZOTERO_API_KEY%"=="REPLACE_WITH_YOUR_ZOTERO_API_KEY" (
    echo API 模式请先填写 ZOTERO_API_KEY
    exit /b 1
  )
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
if not exist .venv (
  python -m venv .venv
)

set PYTHONPATH=src
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m litrature run-daily --source "%SOURCE%" --limit 20 --max-total 120 --vault-dir "%VAULT_DIR%" --zotero-backend "%ZOTERO_BACKEND%" --execute-zotero --require-openai-summary

echo 完成：已执行每日流程（真实模式）。
endlocal
