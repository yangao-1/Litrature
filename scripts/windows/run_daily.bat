@echo off
setlocal
set REPO_DIR=%~dp0\..\..
set VAULT_DIR=C:/Users/yangao/OneDrive - UAB/Obsidian/自动文献汇总

cd /d %REPO_DIR%
if not exist .venv (
  python -m venv .venv
)

set PYTHONPATH=src
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m litrature run-daily --limit 20 --max-total 120 --vault-dir "%VAULT_DIR%"

echo 完成：已执行每日流程（演练模式）。
endlocal
