# Litrature

面向水系锌离子电池研究的自动化文献工作流。

## 当前状态

仓库已具备第一版可执行配置层：
- 研究画像配置（主题、必含机制词、排除词、期刊分层、质量门槛）。
- 多查询并行检索策略（不再依赖单条严格检索式）。
- GPT 关键词扩展与查询优化提示词模板。
- 每日/每周执行导向的自动化计划文档。

## 关键文件

- configs/research_profile.yaml
- configs/search_query.txt
- prompts/keyword_expansion_prompt.md
- docs/automation_plan.md

## 建议实施顺序

1. 实现检索适配器与候选文献采集。
2. 实现筛选门控与机制相关性评分。
3. 实现 PDF 下载、校验与去重索引。
4. 实现 Zotero 入库连接器。
5. 实现摘要与笔记生成。
6. 实现 Obsidian 同步与日报/周报输出。

## 运行方式（第一版 CLI）

1. 安装依赖：`pip install -r requirements.txt`
2. 初始化示例数据：`PYTHONPATH=src python -m litrature init-sample`
3. 查看研究配置摘要：`PYTHONPATH=src python -m litrature plan`
4. 执行筛选：`PYTHONPATH=src python -m litrature screen --input data/candidates.sample.jsonl`

## 第二阶段命令（已接入）

1. 拉取候选文献（Crossref / Google Scholar / 混合源，多查询合并）：`PYTHONPATH=src python -m litrature fetch --source mixed --limit 20 --max-total 120`
2. 去重并生成索引：`PYTHONPATH=src python -m litrature dedup --input data/candidates.raw.jsonl`
3. 同步到 Zotero（演练模式）：`PYTHONPATH=src python -m litrature zotero-sync --input data/screened.latest.jsonl`
4. 同步到 Zotero（真实写入）：`PYTHONPATH=src python -m litrature zotero-sync --execute`
5. 导出 Obsidian 笔记与日报周报：`PYTHONPATH=src python -m litrature obsidian-sync --input data/zotero.synced.jsonl --vault-dir obsidian_export`
6. 一键日跑（检索→筛选→去重→Zotero→Obsidian）：`PYTHONPATH=src python -m litrature run-daily --limit 20 --max-total 120 --vault-dir obsidian_export`
7. 重试失败队列：`PYTHONPATH=src python -m litrature retry-failures --max-items 50 --replace-queue`

如果你在 Windows 本机执行，可直接使用你的库目录：
`PYTHONPATH=src python -m litrature run-daily --vault-dir "C:\Users\yangao\OneDrive - UAB\Obsidian\自动文献汇总"`

如果你在当前 Linux 容器执行，需把该 OneDrive 目录挂载到容器可访问路径后再传入 `--vault-dir`。

真实写入前需要设置环境变量：
- `ZOTERO_USER_ID`
- `ZOTERO_API_KEY`
- `OPENAI_API_KEY`（可选；未配置时使用规则摘要）

建议先复制 `.env.example` 到 `.env` 并填写。

期刊策略可在 `configs/research_profile.yaml` 调整：
- `journal_policy.whitelist`：优先保留的期刊
- `journal_policy.blacklist`：直接过滤的期刊
- `journal_policy.require_whitelist_match`：设为 `true` 时仅保留白名单期刊

筛选结果默认输出到 data/screened.latest.jsonl，并写入 logs/litrature.log。

## 说明

- 默认摘要路径使用 GPT API。
- Zotero 插件生成笔记作为手动兜底与覆盖来源。
- 系统优先筛选具有机制证据的论文，而非仅性能堆砌论文。
- 对于 Crossref 无摘要条目，系统会按主题相关性低置信保留，避免漏掉潜在机制论文。

## VSCode 使用方式（推荐）

1. 打开命令面板，执行 `Tasks: Run Task`。
2. 先运行 `Litrature: 安装依赖`。
3. 首次建议运行 `Litrature: 一键日跑(演练)`。
4. 确认输出正常后，再运行 `Litrature: 一键日跑(真实Zotero)`。

任务文件位置：`.vscode/tasks.json`。

运行后重点查看：
- `data/candidates.raw.jsonl`（检索结果）
- `data/screened.latest.jsonl`（筛选结果）
- `data/zotero.synced.jsonl`（同步结果）
- `logs/litrature.log`（日志）

如果出现 Zotero 写入失败，可运行任务：
- `Litrature: 重试失败队列`

Obsidian 导出目录默认为 `obsidian_export`，也可在任务弹窗里输入你的目录：
`C:/Users/yangao/OneDrive - UAB/Obsidian/自动文献汇总`

## Windows 定时任务

你可以直接使用脚本：
- `scripts/windows/run_daily.ps1`
- `scripts/windows/run_daily.bat`

任务计划程序建议：
1. 程序/脚本：`powershell.exe`
2. 参数：`-ExecutionPolicy Bypass -File "<你的仓库路径>/scripts/windows/run_daily.ps1" -RepoDir "<你的仓库路径>" -VaultDir "C:/Users/yangao/OneDrive - UAB/Obsidian/自动文献汇总" -ExecuteZotero`
3. 触发器：每天早上（例如 07:30）

## Windows 模式说明（重要）

- `scripts/windows/run_daily.ps1`：默认真实模式，支持把 Zotero/OpenAI 凭据写在脚本参数默认值里，一次配置后直接运行。
- `scripts/windows/run_daily.bat`：默认真实模式，支持把 Zotero/OpenAI 凭据写在脚本头部变量里，一次配置后直接运行。
- 两个脚本默认后端为 `mcp`，即不依赖 Zotero Web API 即可运行（前提是本地 Zotero MCP 服务可用）。

首次配置（只改一次）：
1. 打开 `scripts/windows/run_daily.ps1`，填写：
	- `Source`（`crossref` / `google_scholar` / `mixed`）
	- `ZoteroBackend`（`api` 或 `mcp`）
	- `ZoteroLibraryType`（`users` 或 `groups`，API 模式）
	- `ZoteroLibraryId`（可选；群组库请填 group id）
	- `ZoteroUserId`
	- `ZoteroApiKey`
	- `ZoteroMcpEndpoint` / `ZoteroMcpMethod`（仅 MCP 模式）
	- `SerpApiKey`（`google_scholar` 或 `mixed` 时必填）
	- `UnpaywallEmail`（可选；用于提升 PDF 命中率）
	- `OpenAIApiKey`（必填，用于 GPT 智能总结）
2. 或打开 `scripts/windows/run_daily.bat`，填写：
	- `SOURCE`（`crossref` / `google_scholar` / `mixed`）
	- `ZOTERO_BACKEND`（`api` 或 `mcp`）
	- `ZOTERO_LIBRARY_TYPE`（`users` 或 `groups`，API 模式）
	- `ZOTERO_LIBRARY_ID`（可选；群组库请填 group id）
	- `ZOTERO_USER_ID`
	- `ZOTERO_API_KEY`
	- `ZOTERO_MCP_ENDPOINT` / `ZOTERO_MCP_METHOD`（仅 MCP 模式）
	- `SERPAPI_API_KEY`（`google_scholar` 或 `mixed` 时必填）
	- `UNPAYWALL_EMAIL`（可选；用于提升 PDF 命中率）
	- `OPENAI_API_KEY`（必填）

真实模式示例（无需再手动设置环境变量）：
`powershell -ExecutionPolicy Bypass -File .\scripts\windows\run_daily.ps1 -RepoDir . -VaultDir "C:/Users/yangao/OneDrive - UAB/Obsidian/自动文献汇总"`

AI 笔记模板文件：
- `prompts/ai_note_template.md`
- 程序会调用 GPT 按该模板生成单篇笔记。
- 日报、周报也会调用 GPT 自动生成结构化总结。
- 智能总结依赖 `OPENAI_API_KEY`；自动脚本默认启用 `--require-openai-summary`，未配置会直接失败退出。

Zotero 同步增强（已启用）：
- 导入父条目后，会自动尝试添加 PDF 附件。
- 若 Crossref 未提供 `pdf_url`，会按顺序尝试 OpenAlex、Unpaywall（需 `UNPAYWALL_EMAIL`）、DOI 跳转页解析来补全 PDF 链接。
- 每条导入记录会自动创建一条 Zotero 子笔记（AI 结构化摘要）。
- 支持两种写入后端：`api`（官方 Web API）与 `mcp`（通过你本地的 Zotero MCP 服务）。
- API 模式下支持 `users` 与 `groups` 两种库类型；如果你写入群组库，请设置 `ZOTERO_LIBRARY_TYPE=groups` 和 `ZOTERO_LIBRARY_ID=<group_id>`。
- `api` 模式附件为 URL 链接型（linked_url）；若你希望 Zotero 内出现真实本地 PDF 文件，建议使用 `mcp` 后端由本地 Zotero 客户端下载/导入。

本地 PDF 数据库（新增）：
- 每次执行会尝试把可下载 PDF 缓存到 `data/pdf_library`。
- 同步结果 `data/zotero.synced.jsonl` 会记录 `local_pdf_cached` 与 `local_pdf_path`。
- 可通过参数 `--local-pdf-dir` 指定目录，便于你维护本地文献库。

Google Scholar 说明：
- 本项目通过 SerpAPI 访问 Google Scholar 结果（`source=google_scholar`）。
- 需要配置 `SERPAPI_API_KEY`。
- 直接抓取 Google Scholar 页面不稳定且易触发风控，默认不采用直连爬取。

混合检索说明：
- `source=mixed` 会按每个查询依次拉取 Crossref 与 Google Scholar，并在进入后续筛选前统一去重。

去重与 Obsidian 导出优化：
- Windows 一键脚本默认附带 `--reset-dedup-index`，避免历史索引导致“唯一条数=0”。
- 当 `data/zotero.synced.jsonl` 为空时，程序会自动回退使用 `data/candidates.unique.jsonl` 生成 Obsidian 笔记，确保 Obsidian 侧仍有输出。

如果运行后 Zotero 没有新增文献，按下面检查：
1. 查看 `data/zotero.synced.jsonl` 是否包含 `"body": "dry-run"`。若有，说明仍是演练模式。
2. 查看 `data/zotero.synced.jsonl` 是否包含 `"ok": false` 或 `"status": 4xx/5xx`。若有，说明写入失败，检查 API 凭据与权限。
3. 查看 `data/screened.latest.jsonl`/`data/candidates.unique.jsonl` 是否有 `keep=true` 记录。若没有，说明本轮没有可入库条目。
4. 若有失败记录，可执行 `PYTHONPATH=src python -m litrature retry-failures --max-items 50 --replace-queue` 重试。
5. 查看 `data/zotero.synced.jsonl` 的 `zotero_attachment_ok` 和 `zotero_note_ok` 字段，可快速判断 PDF 附件与子笔记是否写入成功。


