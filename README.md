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

1. 拉取候选文献（Crossref，多查询合并）：`PYTHONPATH=src python -m litrature fetch --source crossref --limit 20 --max-total 120`
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