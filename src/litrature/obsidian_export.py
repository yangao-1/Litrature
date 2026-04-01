from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .summarizer import summarize_row


def _safe_name(text: str) -> str:
    out = "".join(ch for ch in text if ch.isalnum() or ch in (" ", "-", "_"))
    out = " ".join(out.split())
    return out[:120] if out else "untitled"


def export_obsidian(
    rows: list[dict[str, Any]],
    vault_dir: Path,
    profile_name: str,
    summarize_timeout: int = 30,
) -> dict[str, Any]:
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

        summary = summarize_row(row, timeout_seconds=summarize_timeout)
        doi = str(row.get("doi", "")).strip()
        journal = str(row.get("journal", "")).strip()
        year = str(row.get("year", "")).strip()
        score = row.get("score", "")
        zotero_key = str(row.get("zotero_key", "")).strip()

        fname = f"{_safe_name(title)}.md"
        path = notes_dir / fname

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
            f"# {title}\n\n"
            "## 研究问题\n"
            f"{summary['研究问题']}\n\n"
            "## 方法证据\n"
            f"{summary['方法证据']}\n\n"
            "## 机制结论\n"
            f"{summary['机制结论']}\n\n"
            "## 局限与疑问\n"
            f"{summary['局限与疑问']}\n"
        )
        path.write_text(content, encoding="utf-8")
        written_notes.append(path)

    daily = reports_dir / f"日报-{today}.md"
    daily_lines = [
        f"# 自动文献日报 {today}",
        "",
        f"- 新增笔记数量: {len(written_notes)}",
        "- 今日重点: 需优先人工核查方法证据和 HER 抑制链路。",
        "",
        "## 新增条目",
    ]
    daily_lines.extend([f"- [[文献笔记/{p.name[:-3]}]]" for p in written_notes])
    daily.write_text("\n".join(daily_lines) + "\n", encoding="utf-8")

    weekly = reports_dir / f"周报-{week_tag}.md"
    weekly_lines = [
        f"# 自动文献周报 {week_tag}",
        "",
        f"- 本次汇总条目: {len(written_notes)}",
        "- 机制关注: Zn2+ 界面变化、HER 抑制路径、电解液作用步骤。",
        "",
        "## 建议下周跟进",
        "- 补充含原位/operando证据的论文。",
        "- 追踪 NH3 与 acetate 配位差异的直接对比研究。",
    ]
    weekly.write_text("\n".join(weekly_lines) + "\n", encoding="utf-8")

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
        "daily_report": str(daily),
        "weekly_report": str(weekly),
        "index": str(index),
    }
