from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .summarizer import assess_evidence_level, generate_note_markdown, generate_report_markdown, is_openai_enabled


def _safe_name(text: str) -> str:
    out = "".join(ch for ch in text if ch.isalnum() or ch in (" ", "-", "_"))
    out = " ".join(out.split())
    return out[:120] if out else "untitled"


def export_obsidian(
    rows: list[dict[str, Any]],
    vault_dir: Path,
    profile_name: str,
    summarize_timeout: int = 30,
    require_openai_summary: bool = False,
    only_pending: bool = False,
) -> dict[str, Any]:
    ai_enabled = is_openai_enabled()
    if require_openai_summary and not ai_enabled:
        raise RuntimeError("未检测到 OPENAI_API_KEY，无法生成 AI 总结。")

    notes_dir = vault_dir / "文献笔记"
    reports_dir = vault_dir / "自动报告"
    notes_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    week_tag = datetime.now().strftime("%Y-W%W")

    written_notes = []
    created_count = 0
    updated_count = 0
    readable_count = 0
    evidence_counts: dict[str, int] = {}
    skipped_non_pending = 0
    for row in rows:
        title = str(row.get("title", "")).strip()
        if not title:
            continue

        doi = str(row.get("doi", "")).strip()
        journal = str(row.get("journal", "")).strip()
        year = str(row.get("year", "")).strip()
        score = row.get("score", "")
        zotero_key = str(row.get("zotero_key", "")).strip()

        fname = f"{_safe_name(title)}.md"
        path = notes_dir / fname
        existed_before = path.exists()

        if only_pending:
            if not existed_before:
                skipped_non_pending += 1
                continue
            try:
                current_text = path.read_text(encoding="utf-8")
            except Exception:
                current_text = ""
            if "当前为待补全文短卡" not in current_text:
                skipped_non_pending += 1
                continue

        evidence_level = assess_evidence_level(row)
        evidence_counts[evidence_level] = evidence_counts.get(evidence_level, 0) + 1
        if evidence_level in ("fulltext-local", "fulltext-url", "abstract", "abstract-openalex", "abstract-crossref", "fulltext", "webpage", "doi-webpage"):
            readable_count += 1

        ai_note_markdown = generate_note_markdown(row, timeout_seconds=summarize_timeout)
        content = (
            "---\n"
            f"title: \"{title}\"\n"
            f"doi: \"{doi}\"\n"
            f"journal: \"{journal}\"\n"
            f"year: \"{year}\"\n"
            f"score: \"{score}\"\n"
            f"zotero_key: \"{zotero_key}\"\n"
            f"profile: \"{profile_name}\"\n"
            "tags: [自动文献, Zn负极, 机制]\n"
            "---\n\n"
            f"{ai_note_markdown}\n"
        )
        path.write_text(content, encoding="utf-8")
        written_notes.append(path)
        if existed_before:
            updated_count += 1
        else:
            created_count += 1

    daily = reports_dir / f"日报-{today}.md"
    note_titles = [p.name[:-3] for p in written_notes]
    evidence_stats = {
        "total": len(written_notes),
        "readable": readable_count,
        **{f"level_{k}": v for k, v in evidence_counts.items()},
    }
    daily_markdown = generate_report_markdown(
        rows=rows,
        note_titles=note_titles,
        report_type="daily",
        timeout_seconds=summarize_timeout,
        evidence_stats=evidence_stats,
    )
    daily_content = daily_markdown + "\n\n## 新增条目\n" + "\n".join(
        [f"- [[文献笔记/{title}]]" for title in note_titles]
    )
    daily.write_text(daily_content + "\n", encoding="utf-8")

    weekly = reports_dir / f"周报-{week_tag}.md"
    weekly_markdown = generate_report_markdown(
        rows=rows,
        note_titles=note_titles,
        report_type="weekly",
        timeout_seconds=summarize_timeout,
        evidence_stats=evidence_stats,
    )
    weekly_content = weekly_markdown + "\n\n## 本周文献链接\n" + "\n".join(
        [f"- [[文献笔记/{title}]]" for title in note_titles]
    )
    weekly.write_text(weekly_content + "\n", encoding="utf-8")

    index = vault_dir / "自动文献总览.md"
    index_lines = [
        "# 自动文献总览",
        "",
        "## 最近生成",
        f"- [[自动报告/{daily.name[:-3]}]]",
        f"- [[自动报告/{weekly.name[:-3]}]]",
        "",
        "## 文献笔记",
    ]
    index_lines.extend([f"- [[文献笔记/{p.name[:-3]}]]" for p in written_notes])
    index.write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    return {
        "notes": len(written_notes),
        "notes_created": created_count,
        "notes_updated": updated_count,
        "notes_skipped_non_pending": skipped_non_pending,
        "readable_notes": readable_count,
        "ai_summary_mode": "gpt" if ai_enabled else "rule-fallback",
        "daily_report": str(daily),
        "weekly_report": str(weekly),
        "index": str(index),
    }
