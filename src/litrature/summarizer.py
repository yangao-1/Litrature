from __future__ import annotations

import io
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def is_openai_enabled() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def generate_note_markdown(row: dict[str, Any], timeout_seconds: int = 30) -> str:
    title = str(row.get("title", "")).strip() or "Untitled"
    doi = str(row.get("doi", "")).strip()
    url = str(row.get("source_url", "")).strip()
    zotero_key = str(row.get("zotero_key", "")).strip()
    if not zotero_key:
        zotero_key = "N/A"

    template = _load_note_template()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _rule_note_markdown(row, template, zotero_key=zotero_key)

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    abstract = str(row.get("abstract", "")).strip()
    paper_excerpt = _fetch_paper_excerpt(row, timeout_seconds=timeout_seconds)

    prompt = (
        "你是锌负极/界面研究助手。请严格按模板结构输出 Markdown，不要新增或删除标题。"
        "要点必须具体、可验证，避免空话。\n\n"
        "[模板]\n"
        f"{template}\n\n"
        "[文章信息]\n"
        f"title: {title}\n"
        f"doi: {doi}\n"
        f"url: {url}\n"
        f"journal: {row.get('journal', '')}\n"
        f"year: {row.get('year', '')}\n"
        f"abstract: {abstract}\n\n"
        "[全文节选]\n"
        f"{paper_excerpt}\n\n"
        "[变量替换要求]\n"
        f"${{title}} => {title}\n"
        f"${{doi}} => {doi}\n"
        f"${{url}} => {url}\n"
        f"${{zotero_key}} => {zotero_key}\n\n"
        "请直接输出最终 Markdown。"
    )

    content = _call_chat_completion(prompt=prompt, api_key=api_key, model=model, timeout_seconds=timeout_seconds)
    if not content:
        return _rule_note_markdown(row, template, zotero_key=zotero_key)
    return content.strip()


def generate_report_markdown(
    rows: list[dict[str, Any]],
    note_titles: list[str],
    report_type: str,
    timeout_seconds: int = 30,
) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _rule_report_markdown(note_titles=note_titles, report_type=report_type)

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    today = datetime.now().strftime("%Y-%m-%d")
    week_tag = datetime.now().strftime("%Y-W%W")
    rows_payload = [
        {
            "title": r.get("title", ""),
            "journal": r.get("journal", ""),
            "year": r.get("year", ""),
            "score": r.get("score", ""),
            "reasons": r.get("reasons", []),
        }
        for r in rows
    ]

    prompt = (
        "你是研究秘书助手，请输出结构化 Markdown 报告。"
        "要求：简明但有洞察，必须给出可执行下一步。\n"
        f"report_type: {report_type}\n"
        f"today: {today}\n"
        f"week_tag: {week_tag}\n"
        f"notes_count: {len(note_titles)}\n"
        f"note_titles: {json.dumps(note_titles, ensure_ascii=False)}\n"
        f"rows: {json.dumps(rows_payload, ensure_ascii=False)}\n\n"
        "输出格式：\n"
        "# 标题\n"
        "## 本期概览\n"
        "## 机制主线\n"
        "## 重点论文\n"
        "## 风险与空白\n"
        "## 下一步行动\n"
    )

    content = _call_chat_completion(prompt=prompt, api_key=api_key, model=model, timeout_seconds=timeout_seconds)
    if not content:
        return _rule_report_markdown(note_titles=note_titles, report_type=report_type)
    return content.strip()


def summarize_row(row: dict[str, Any], timeout_seconds: int = 30) -> dict[str, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _rule_summary(row)

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    prompt = _build_prompt(row)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是电池机制论文摘要助手，仅输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }

    req = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"]
        parsed = json.loads(text)
        return {
            "研究问题": str(parsed.get("研究问题", "")),
            "方法证据": str(parsed.get("方法证据", "")),
            "机制结论": str(parsed.get("机制结论", "")),
            "局限与疑问": str(parsed.get("局限与疑问", "")),
        }
    except Exception:
        return _rule_summary(row)


def _call_chat_completion(prompt: str, api_key: str, model: str, timeout_seconds: int) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是严谨的科研写作助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }

    req = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data["choices"][0]["message"]["content"])
    except Exception:
        return ""


def _load_note_template() -> str:
    default = (
        "# ${title}\n\n"
        "## 研究核心 (Research Core)\n"
        "### 内容 (Content)\n\n"
        "### 创新点 (Innovations)\n\n"
        "### 不足 (Shortcomings)\n\n"
        "## 研究内容 (Research Content)\n"
        "### 数据 (Data)\n\n"
        "### 方法 (Method)\n\n"
        "### 实验 (Experiment)\n\n"
        "### 结论 (Conclusion)\n\n"
        "## AI 总结 (AI Summary)\n"
        "### 关键记录 (Key Records)\n\n"
        "### 待解决 (To be resolved)\n\n"
        "### 思想启发 (Thought Inspiration)\n"
    )
    path = Path("prompts/ai_note_template.md")
    if not path.exists():
        return default
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return default


def _fetch_paper_excerpt(row: dict[str, Any], timeout_seconds: int = 30) -> str:
    abstract = str(row.get("abstract", "")).strip()
    pdf_url = str(row.get("pdf_url", "")).strip()
    if not pdf_url:
        return abstract or "无摘要与全文节选。"

    try:
        raw = _download_pdf_bytes(pdf_url, timeout_seconds=timeout_seconds)
        text = _extract_pdf_text(raw)
        if text:
            text = " ".join(text.split())
            return text[:12000]
    except Exception:
        pass

    return abstract or "无摘要与全文节选。"


def _download_pdf_bytes(pdf_url: str, timeout_seconds: int) -> bytes:
    req = Request(pdf_url, method="GET", headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=timeout_seconds) as resp:
        return resp.read(10 * 1024 * 1024)


def _extract_pdf_text(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return ""

    reader = PdfReader(io.BytesIO(raw))
    texts: list[str] = []
    for page in reader.pages[:6]:
        try:
            texts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(texts).strip()


def _rule_note_markdown(row: dict[str, Any], template: str, zotero_key: str) -> str:
    title = str(row.get("title", "")).strip() or "Untitled"
    doi = str(row.get("doi", "")).strip()
    url = str(row.get("source_url", "")).strip()
    abstract = str(row.get("abstract", "")).strip() or "暂无摘要。"

    filled = template
    filled = filled.replace("${title}", title)
    filled = filled.replace("${doi}", doi)
    filled = filled.replace("${url}", url)
    filled = filled.replace("${zotero_key}", zotero_key)

    fallback_append = (
        "\n\n"
        "## AI 自动补充说明\n"
        "- 当前未配置 OPENAI_API_KEY 或模型调用失败，已使用规则兜底。\n"
        f"- 标题: {title}\n"
        f"- 摘要线索: {abstract[:300]}\n"
    )
    return filled + fallback_append


def _rule_report_markdown(note_titles: list[str], report_type: str) -> str:
    title = "自动文献日报" if report_type == "daily" else "自动文献周报"
    lines = [
        f"# {title}",
        "",
        "## 本期概览",
        f"- 新增笔记数量: {len(note_titles)}",
        "- 报告模式: 规则兜底（未调用 GPT）。",
        "",
        "## 机制主线",
        "- 关注 Zn2+ 溶剂化/去溶剂化、界面稳定层、HER 抑制协同机制。",
        "",
        "## 重点论文",
    ]
    lines.extend([f"- {name}" for name in note_titles] or ["- 无新增条目"]) 
    lines.extend(
        [
            "",
            "## 风险与空白",
            "- 缺少全文证据时，结论置信度偏低。",
            "",
            "## 下一步行动",
            "- 优先补抓可获取 PDF 的条目并二次总结。",
        ]
    )
    return "\n".join(lines)


def _build_prompt(row: dict[str, Any]) -> str:
    title = str(row.get("title", ""))
    abstract = str(row.get("abstract", ""))
    return (
        "请基于给定标题和摘要，输出 JSON，字段为：研究问题、方法证据、机制结论、局限与疑问。\\n"
        f"标题: {title}\\n摘要: {abstract}"
    )


def _rule_summary(row: dict[str, Any]) -> dict[str, str]:
    title = str(row.get("title", "")).strip()
    abstract = str(row.get("abstract", "")).strip()
    if not abstract:
        abstract = "暂无摘要，建议后续补抓全文或摘要。"

    return {
        "研究问题": f"该工作围绕 {title} 展开。",
        "方法证据": "需重点核对 EIS/XPS/LSV/Tafel/原位证据是否齐全。",
        "机制结论": "请结合原文判断 Zn2+ 溶剂化-去溶剂化、成核与 HER 抑制的因果链。",
        "局限与疑问": abstract[:180],
    }
