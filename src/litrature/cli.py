from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .config import build_app_config, load_profile
from .dedup import build_key
from .dedup import deduplicate_rows, save_index
from .io_utils import read_jsonl, write_jsonl
from .logging_utils import setup_logger
from .obsidian_export import export_obsidian
from .pdf_cache import cache_pdf_for_row
from .retry_queue import append_failure
from .screening import CandidateRecord, screen_candidate
from .search import SearchOptions, search_candidates
from .zotero import ZoteroConfig, create_item, dry_run_item, extract_success_key, resolve_pdf_url


def cmd_plan(args: argparse.Namespace) -> int:
    app_cfg = build_app_config(Path(args.workspace), args.profile)
    logger = setup_logger(app_cfg.logs_dir)
    profile = load_profile(app_cfg.profile_path)

    summary = {
        "画像名称": profile.name,
        "研究领域": profile.domain,
        "主题数量": len(profile.topics),
        "必含方法词数量": len(profile.must_have_terms),
        "排除词数量": len(profile.exclude_terms),
        "机制问题数量": len(profile.mechanism_questions),
        "核心检索式": profile.search_query_core,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    logger.info("已输出研究配置摘要")
    return 0


def cmd_init_sample(args: argparse.Namespace) -> int:
    app_cfg = build_app_config(Path(args.workspace), args.profile)
    logger = setup_logger(app_cfg.logs_dir)

    rows = [
        {
            "title": "Ammonia-coordinated electrolyte regulates Zn2+ desolvation and suppresses HER on zinc anode",
            "abstract": "We reveal solvation structure changes by XPS and EIS, and quantify nucleation overpotential with Zn plating/stripping tests.",
            "journal": "Nano Energy",
            "year": 2025,
        },
        {
            "title": "High capacity cathode design for zinc-ion batteries with carbon coating",
            "abstract": "This work focuses on full cell performance and energy density improvement.",
            "journal": "Chemical Engineering Journal",
            "year": 2024,
        },
    ]

    out = app_cfg.data_dir / "candidates.sample.jsonl"
    write_jsonl(out, rows)
    logger.info("已写入示例候选文献: %s", out)
    print(str(out))
    return 0


def cmd_screen(args: argparse.Namespace) -> int:
    app_cfg = build_app_config(Path(args.workspace), args.profile)
    logger = setup_logger(app_cfg.logs_dir)
    profile = load_profile(app_cfg.profile_path)

    in_path = app_cfg.workspace / args.input
    out_path = app_cfg.workspace / args.output

    rows = read_jsonl(in_path)
    if not rows:
        logger.warning("输入为空或不存在: %s", in_path)
        print("输入为空或不存在，请先准备候选文献 jsonl。")
        return 1

    screened: list[dict] = []
    kept = 0
    for row in rows:
        rec = CandidateRecord(
            title=str(row.get("title", "")),
            abstract=str(row.get("abstract", "")),
            journal=str(row.get("journal", "")),
            year=int(row["year"]) if row.get("year") is not None else None,
        )
        result = screen_candidate(rec, profile)
        out_row = {
            **row,
            "keep": result.keep,
            "score": result.score,
            "method_hits": result.method_hits,
            "exclude_hits": result.exclude_hits,
            "journal_tier": result.journal_tier,
            "reasons": result.reasons,
        }
        screened.append(out_row)
        if result.keep:
            kept += 1

    write_jsonl(out_path, screened)
    logger.info("筛选完成: 输入=%s, 输出=%s, 保留=%d/%d", in_path, out_path, kept, len(rows))
    print(
        json.dumps(
            {
                "输入条数": len(rows),
                "保留条数": kept,
                "输出文件": str(out_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    app_cfg = build_app_config(Path(args.workspace), args.profile)
    logger = setup_logger(app_cfg.logs_dir)
    profile = load_profile(app_cfg.profile_path)

    options = SearchOptions(
        source=args.source,
        limit=int(args.limit),
        max_total=int(args.max_total),
        timeout_seconds=int(args.timeout),
    )

    try:
        rows = search_candidates(profile, options)
    except Exception as e:
        logger.exception("检索失败")
        print(f"检索失败: {e}")
        return 1

    out_path = app_cfg.workspace / args.output
    write_jsonl(out_path, rows)
    logger.info("检索完成: 来源=%s, 条数=%d, 输出=%s", options.source, len(rows), out_path)
    print(
        json.dumps(
            {
                "来源": options.source,
                "条数": len(rows),
                "输出文件": str(out_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_dedup(args: argparse.Namespace) -> int:
    app_cfg = build_app_config(Path(args.workspace), args.profile)
    logger = setup_logger(app_cfg.logs_dir)

    in_path = app_cfg.workspace / args.input
    out_path = app_cfg.workspace / args.output
    dup_path = app_cfg.workspace / args.duplicates
    index_path = app_cfg.workspace / args.index

    rows = read_jsonl(in_path)
    if not rows:
        print("输入为空或不存在，无法去重。")
        return 1

    unique_rows, duplicate_rows, index = deduplicate_rows(rows, index_path=index_path)
    write_jsonl(out_path, unique_rows)
    write_jsonl(dup_path, duplicate_rows)
    save_index(index_path, index)

    logger.info(
        "去重完成: 输入=%d, 唯一=%d, 重复=%d",
        len(rows),
        len(unique_rows),
        len(duplicate_rows),
    )
    print(
        json.dumps(
            {
                "输入条数": len(rows),
                "唯一条数": len(unique_rows),
                "重复条数": len(duplicate_rows),
                "唯一输出": str(out_path),
                "重复输出": str(dup_path),
                "索引文件": str(index_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_zotero_sync(args: argparse.Namespace) -> int:
    app_cfg = build_app_config(Path(args.workspace), args.profile)
    logger = setup_logger(app_cfg.logs_dir)

    in_path = app_cfg.workspace / args.input
    queue_path = app_cfg.workspace / args.retry_queue
    out_path = app_cfg.workspace / args.output

    rows = read_jsonl(in_path)
    if not rows:
        write_jsonl(out_path, [])
        print("输入为空，本次无需同步 Zotero。")
        return 0

    candidates = [row for row in rows if bool(row.get("keep", True))]
    if not candidates:
        write_jsonl(out_path, [])
        print("没有需要同步的记录（keep=true）。")
        return 0

    execute = bool(args.execute)
    user_id = os.getenv("ZOTERO_USER_ID", "")
    api_key = os.getenv("ZOTERO_API_KEY", "")
    backend = str(args.zotero_backend).strip().lower()
    library_type = os.getenv("ZOTERO_LIBRARY_TYPE", "users").strip() or "users"
    library_id = os.getenv("ZOTERO_LIBRARY_ID", "").strip() or user_id

    cfg = ZoteroConfig(user_id=library_id, api_key=api_key, library_type=library_type, backend=backend)

    ok_count = 0
    fail_count = 0
    synced_rows: list[dict] = []
    fail_samples: list[dict[str, str | int]] = []
    pdf_cache_dir = app_cfg.workspace / args.local_pdf_dir
    use_local_pdf_cache = not bool(args.disable_local_pdf_cache)

    for row in candidates:
        local_pdf_ok = False
        local_pdf_path = ""
        resolved_pdf_url = resolve_pdf_url(row, timeout_seconds=int(args.pdf_timeout))
        if use_local_pdf_cache and resolved_pdf_url:
            try:
                local_pdf_ok, local_pdf_path = cache_pdf_for_row(
                    row=row,
                    pdf_url=resolved_pdf_url,
                    out_dir=pdf_cache_dir,
                    timeout_seconds=int(args.pdf_timeout),
                )
            except Exception:
                local_pdf_ok = False
                local_pdf_path = ""

        row_for_sync = dict(row)
        if resolved_pdf_url:
            row_for_sync["pdf_url"] = resolved_pdf_url
        if local_pdf_path:
            row_for_sync["local_pdf_path"] = local_pdf_path

        if execute:
            if backend == "api" and (not library_id or not api_key):
                print("缺少环境变量 ZOTERO_USER_ID/ZOTERO_LIBRARY_ID 或 ZOTERO_API_KEY，无法执行真实写入。")
                return 1
            result = create_item(cfg, row_for_sync)
        else:
            result = dry_run_item(row_for_sync)

        row_out = dict(row_for_sync)
        row_out["zotero_result"] = result
        row_out["zotero_key"] = ""
        row_out["zotero_attachment_ok"] = bool(result.get("attachment", {}).get("ok", False))
        row_out["zotero_note_ok"] = bool(result.get("note", {}).get("ok", False))
        row_out["local_pdf_cached"] = bool(local_pdf_ok)
        row_out["local_pdf_path"] = local_pdf_path

        if result.get("ok") and bool(args.execute):
            body = str(result.get("body", ""))
            row_out["zotero_key"] = extract_success_key(body)

        if result.get("ok"):
            ok_count += 1
            synced_rows.append(row_out)
            continue

        fail_count += 1
        if len(fail_samples) < 3:
            fail_samples.append(
                {
                    "title": str(row.get("title", ""))[:120],
                    "status": int(result.get("status", 0) or 0),
                    "body": str(result.get("body", ""))[:400],
                }
            )
        append_failure(
            queue_path,
            {
                "row": row,
                "error": result,
            },
        )
        synced_rows.append(row_out)

    write_jsonl(out_path, synced_rows)

    logger.info("Zotero 同步完成: 成功=%d, 失败=%d, 执行模式=%s, 后端=%s", ok_count, fail_count, execute, backend)
    print(
        json.dumps(
            {
                "执行模式": "真实写入" if execute else "演练",
                "写入后端": backend,
                "待同步条数": len(candidates),
                "成功条数": ok_count,
                "失败条数": fail_count,
                "失败重试队列": str(queue_path),
                "同步输出": str(out_path),
                "本地PDF目录": str(pdf_cache_dir),
                "失败示例": fail_samples,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_obsidian_sync(args: argparse.Namespace) -> int:
    app_cfg = build_app_config(Path(args.workspace), args.profile)
    logger = setup_logger(app_cfg.logs_dir)

    in_path = app_cfg.workspace / args.input
    rows = read_jsonl(in_path)
    rows = [r for r in rows if bool(r.get("keep", True))]

    vault = Path(args.vault_dir).expanduser()
    result = export_obsidian(
        rows=rows,
        vault_dir=vault,
        profile_name=args.profile_name,
        summarize_timeout=int(args.summary_timeout),
        require_openai_summary=bool(args.require_openai_summary),
    )
    logger.info("Obsidian 导出完成: 笔记=%d", result["notes"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_run_daily(args: argparse.Namespace) -> int:
    app_cfg = build_app_config(Path(args.workspace), args.profile)
    logger = setup_logger(app_cfg.logs_dir)

    base = argparse.Namespace(
        workspace=args.workspace,
        profile=args.profile,
    )

    if bool(args.reset_dedup_index):
        index_path = app_cfg.workspace / args.index_file
        if index_path.exists():
            index_path.unlink()
            logger.info("已清理去重索引: %s", index_path)

    fetch_args = argparse.Namespace(
        **base.__dict__,
        source=args.source,
        limit=args.limit,
        max_total=args.max_total,
        timeout=args.timeout,
        output=args.raw_output,
    )
    if cmd_fetch(fetch_args) != 0:
        return 1

    screen_args = argparse.Namespace(
        **base.__dict__,
        input=args.raw_output,
        output=args.screen_output,
    )
    if cmd_screen(screen_args) != 0:
        return 1

    dedup_args = argparse.Namespace(
        **base.__dict__,
        input=args.screen_output,
        output=args.unique_output,
        duplicates=args.duplicates_output,
        index=args.index_file,
    )
    if cmd_dedup(dedup_args) != 0:
        return 1

    zotero_args = argparse.Namespace(
        **base.__dict__,
        input=args.unique_output,
        retry_queue=args.retry_queue,
        execute=args.execute_zotero,
        zotero_backend=args.zotero_backend,
        local_pdf_dir=args.local_pdf_dir,
        pdf_timeout=args.pdf_timeout,
        disable_local_pdf_cache=args.disable_local_pdf_cache,
        output=args.zotero_output,
    )
    if cmd_zotero_sync(zotero_args) != 0:
        return 1

    unique_rows = read_jsonl(app_cfg.workspace / args.unique_output)
    zotero_rows = read_jsonl(app_cfg.workspace / args.zotero_output)

    if unique_rows and zotero_rows:
        zotero_map: dict[str, dict] = {}
        for row in zotero_rows:
            key = build_key(row)
            zotero_map[key] = row

        merged_rows: list[dict] = []
        for row in unique_rows:
            key = build_key(row)
            merged = dict(row)
            z_row = zotero_map.get(key)
            if z_row:
                for field in ("zotero_result", "zotero_key", "zotero_attachment_ok", "zotero_note_ok"):
                    if field in z_row:
                        merged[field] = z_row[field]
            merged_rows.append(merged)

        obsidian_input = "data/obsidian.input.jsonl"
        write_jsonl(app_cfg.workspace / obsidian_input, merged_rows)
    else:
        obsidian_input = args.unique_output
        if not unique_rows:
            logger.warning("去重输出为空，Obsidian 导出将无可用条目")
        elif not zotero_rows:
            logger.warning("Zotero 输出为空，Obsidian 导出使用去重输出: %s", obsidian_input)

    obsidian_args = argparse.Namespace(
        **base.__dict__,
        input=obsidian_input,
        vault_dir=args.vault_dir,
        profile_name=args.profile_name,
        summary_timeout=args.summary_timeout,
        require_openai_summary=args.require_openai_summary,
    )
    if cmd_obsidian_sync(obsidian_args) != 0:
        return 1

    logger.info("每日自动流程已完成")
    print("每日自动流程已完成。")
    return 0


def cmd_retry_failures(args: argparse.Namespace) -> int:
    app_cfg = build_app_config(Path(args.workspace), args.profile)
    logger = setup_logger(app_cfg.logs_dir)

    queue_path = app_cfg.workspace / args.retry_queue
    out_path = app_cfg.workspace / args.output
    max_items = int(args.max_items)

    rows = read_jsonl(queue_path)
    if not rows:
        print("重试队列为空。")
        write_jsonl(out_path, [])
        return 0

    user_id = os.getenv("ZOTERO_USER_ID", "")
    api_key = os.getenv("ZOTERO_API_KEY", "")
    backend = str(args.zotero_backend).strip().lower()
    library_type = os.getenv("ZOTERO_LIBRARY_TYPE", "users").strip() or "users"
    library_id = os.getenv("ZOTERO_LIBRARY_ID", "").strip() or user_id
    if backend == "api" and (not library_id or not api_key):
        print("缺少环境变量 ZOTERO_USER_ID/ZOTERO_LIBRARY_ID 或 ZOTERO_API_KEY，无法执行重试。")
        return 1

    cfg = ZoteroConfig(user_id=library_id, api_key=api_key, library_type=library_type, backend=backend)

    retried: list[dict] = []
    remain: list[dict] = []
    ok_count = 0
    fail_count = 0

    for i, payload in enumerate(rows):
        row = payload.get("row", {}) if isinstance(payload, dict) else {}
        if i < max_items:
            result = create_item(cfg, row)
            retried.append({"row": row, "retry_result": result})
            if result.get("ok"):
                ok_count += 1
            else:
                fail_count += 1
                remain.append({"row": row, "error": result})
        else:
            remain.append(payload)

    if bool(args.replace_queue):
        write_jsonl(queue_path, remain)

    write_jsonl(out_path, retried)
    logger.info("重试完成: 成功=%d, 失败=%d, 剩余=%d", ok_count, fail_count, len(remain))
    print(
        json.dumps(
            {
                "重试条数": len(retried),
                "成功条数": ok_count,
                "失败条数": fail_count,
                "队列剩余": len(remain),
                "结果输出": str(out_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Litrature 文献自动化工具（第一版）")
    parser.add_argument(
        "--workspace",
        default=".",
        help="工作区根目录，默认当前目录",
    )
    parser.add_argument(
        "--profile",
        default="configs/research_profile.yaml",
        help="研究画像配置文件相对路径",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="打印研究配置摘要")
    plan.set_defaults(func=cmd_plan)

    init_sample = sub.add_parser("init-sample", help="写入示例候选文献数据")
    init_sample.set_defaults(func=cmd_init_sample)

    screen = sub.add_parser("screen", help="执行规则筛选并输出打分结果")
    screen.add_argument(
        "--input",
        default="data/candidates.sample.jsonl",
        help="输入候选文献 jsonl 相对路径",
    )
    screen.add_argument(
        "--output",
        default="data/screened.latest.jsonl",
        help="输出筛选结果 jsonl 相对路径",
    )
    screen.set_defaults(func=cmd_screen)

    fetch = sub.add_parser("fetch", help="从检索源拉取候选文献")
    fetch.add_argument("--source", default="crossref", help="检索源，支持 crossref / google_scholar / mixed")
    fetch.add_argument("--limit", default=20, type=int, help="拉取条数上限")
    fetch.add_argument("--max-total", default=100, type=int, help="多查询合并后的总条数上限")
    fetch.add_argument("--timeout", default=20, type=int, help="网络超时（秒）")
    fetch.add_argument(
        "--output",
        default="data/candidates.raw.jsonl",
        help="候选文献输出 jsonl 相对路径",
    )
    fetch.set_defaults(func=cmd_fetch)

    dedup = sub.add_parser("dedup", help="按 DOI/标题哈希进行去重")
    dedup.add_argument("--input", default="data/candidates.raw.jsonl", help="输入 jsonl")
    dedup.add_argument("--output", default="data/candidates.unique.jsonl", help="唯一记录输出 jsonl")
    dedup.add_argument(
        "--duplicates",
        default="data/candidates.duplicates.jsonl",
        help="重复记录输出 jsonl",
    )
    dedup.add_argument("--index", default="data/dedup_index.json", help="去重索引文件路径")
    dedup.set_defaults(func=cmd_dedup)

    zotero_sync = sub.add_parser("zotero-sync", help="同步筛选结果到 Zotero")
    zotero_sync.add_argument("--input", default="data/screened.latest.jsonl", help="筛选结果输入 jsonl")
    zotero_sync.add_argument(
        "--retry-queue",
        default="data/retry_queue.jsonl",
        help="失败重试队列输出路径",
    )
    zotero_sync.add_argument(
        "--output",
        default="data/zotero.synced.jsonl",
        help="Zotero 同步结果输出路径",
    )
    zotero_sync.add_argument(
        "--execute",
        action="store_true",
        help="开启真实写入 Zotero（默认仅演练）",
    )
    zotero_sync.add_argument(
        "--zotero-backend",
        default=os.getenv("ZOTERO_BACKEND", "api"),
        choices=["api", "mcp"],
        help="Zotero 写入后端：api 或 mcp",
    )
    zotero_sync.add_argument("--local-pdf-dir", default="data/pdf_library", help="本地 PDF 数据库目录")
    zotero_sync.add_argument("--pdf-timeout", default=30, type=int, help="PDF 下载超时（秒）")
    zotero_sync.add_argument("--disable-local-pdf-cache", action="store_true", help="禁用本地 PDF 缓存")
    zotero_sync.set_defaults(func=cmd_zotero_sync)

    default_vault_dir = os.getenv("OBSIDIAN_VAULT_DIR", "obsidian_export")

    obsidian_sync = sub.add_parser("obsidian-sync", help="导出 Obsidian 笔记与日报周报")
    obsidian_sync.add_argument("--input", default="data/zotero.synced.jsonl", help="输入 jsonl")
    obsidian_sync.add_argument(
        "--vault-dir",
        default=default_vault_dir,
        help="Obsidian 库目录（可填你的 OneDrive 路径）",
    )
    obsidian_sync.add_argument("--profile-name", default="zn-anode-interface", help="写入笔记的配置名称")
    obsidian_sync.add_argument("--summary-timeout", default=30, type=int, help="摘要超时秒数")
    obsidian_sync.add_argument(
        "--require-openai-summary",
        action="store_true",
        help="要求必须配置 OPENAI_API_KEY；未配置则失败退出",
    )
    obsidian_sync.set_defaults(func=cmd_obsidian_sync)

    run_daily = sub.add_parser("run-daily", help="一键执行每日全流程")
    run_daily.add_argument("--source", default="crossref", help="检索源（crossref / google_scholar / mixed）")
    run_daily.add_argument("--limit", default=20, type=int, help="单查询拉取上限")
    run_daily.add_argument("--max-total", default=100, type=int, help="合并总条数上限")
    run_daily.add_argument("--timeout", default=20, type=int, help="网络超时")
    run_daily.add_argument("--raw-output", default="data/candidates.raw.jsonl", help="原始候选输出")
    run_daily.add_argument("--screen-output", default="data/screened.latest.jsonl", help="筛选输出")
    run_daily.add_argument("--unique-output", default="data/candidates.unique.jsonl", help="去重后输出")
    run_daily.add_argument("--duplicates-output", default="data/candidates.duplicates.jsonl", help="重复输出")
    run_daily.add_argument("--index-file", default="data/dedup_index.json", help="去重索引")
    run_daily.add_argument("--reset-dedup-index", action="store_true", help="运行前清理去重索引")
    run_daily.add_argument("--retry-queue", default="data/retry_queue.jsonl", help="重试队列")
    run_daily.add_argument("--zotero-output", default="data/zotero.synced.jsonl", help="Zotero 输出")
    run_daily.add_argument("--vault-dir", default=default_vault_dir, help="Obsidian 库目录")
    run_daily.add_argument("--profile-name", default="zn-anode-interface", help="配置名称")
    run_daily.add_argument("--summary-timeout", default=30, type=int, help="摘要超时秒数")
    run_daily.add_argument("--execute-zotero", action="store_true", help="执行真实 Zotero 写入")
    run_daily.add_argument(
        "--zotero-backend",
        default=os.getenv("ZOTERO_BACKEND", "api"),
        choices=["api", "mcp"],
        help="Zotero 写入后端：api 或 mcp",
    )
    run_daily.add_argument(
        "--require-openai-summary",
        action="store_true",
        help="要求必须配置 OPENAI_API_KEY；未配置则失败退出",
    )
    run_daily.add_argument("--local-pdf-dir", default="data/pdf_library", help="本地 PDF 数据库目录")
    run_daily.add_argument("--pdf-timeout", default=30, type=int, help="PDF 下载超时（秒）")
    run_daily.add_argument("--disable-local-pdf-cache", action="store_true", help="禁用本地 PDF 缓存")
    run_daily.set_defaults(func=cmd_run_daily)

    retry = sub.add_parser("retry-failures", help="重试 Zotero 失败队列")
    retry.add_argument("--retry-queue", default="data/retry_queue.jsonl", help="重试队列输入")
    retry.add_argument("--output", default="data/retry_results.jsonl", help="重试结果输出")
    retry.add_argument("--max-items", default=50, type=int, help="单次重试最大条数")
    retry.add_argument("--replace-queue", action="store_true", help="重试后回写剩余失败队列")
    retry.add_argument(
        "--zotero-backend",
        default=os.getenv("ZOTERO_BACKEND", "api"),
        choices=["api", "mcp"],
        help="Zotero 写入后端：api 或 mcp",
    )
    retry.set_defaults(func=cmd_retry_failures)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))
