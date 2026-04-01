from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .summarizer import generate_note_markdown, generate_report_markdown, is_openai_enabled


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

    daily = reports_dir / f"日报-{today}.md"
    note_titles = [p.name[:-3] for p in written_notes]
    daily_markdown = generate_report_markdown(
        rows=rows,
        note_titles=note_titles,
        report_type="daily",
        timeout_seconds=summarize_timeout,
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
        "ai_summary_mode": "gpt" if ai_enabled else "rule-fallback",
        "daily_report": str(daily),
        "weekly_report": str(weekly),
        "index": str(index),
    }
