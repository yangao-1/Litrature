from __future__ import annotations

import io
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
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
    paper_excerpt, evidence_level = _fetch_paper_excerpt_with_level(row, timeout_seconds=timeout_seconds)
    if evidence_level in ("none", "metadata"):
        return _pending_fulltext_note_markdown(row=row, zotero_key=zotero_key, evidence_level=evidence_level)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _rule_note_markdown(row, template, zotero_key=zotero_key)

    model = os.getenv("OPENAI_MODEL", "gpt-4.1")
    abstract = str(row.get("abstract", "")).strip()

    prompt = (
        "你是严谨的电池机理论文分析助手。请严格按模板结构输出 Markdown，不要新增或删除标题。"
        "必须遵循：\n"
        "1) 只基于给定信息，不得编造未提供的数据或图号；\n"
        "2) 每个关键判断都要写证据来源（摘要/全文节选/推断）；\n"
        "3) 信息不足时明确写‘证据不足’；\n"
        "4) 用中文输出，术语可中英混排；\n"
        "5) 风格要具体、可执行，避免空话。\n\n"
        "[模板]\n"
        f"{template}\n\n"
        "[文章信息]\n"
        f"title: {title}\n"
        f"doi: {doi}\n"
        f"url: {url}\n"
        f"journal: {row.get('journal', '')}\n"
        f"year: {row.get('year', '')}\n"
        f"abstract: {abstract}\n\n"
        f"[证据等级]\n{evidence_level}\n\n"
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
    evidence_stats: dict[str, int] | None = None,
) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _rule_report_markdown(note_titles=note_titles, report_type=report_type)

    model = os.getenv("OPENAI_MODEL", "gpt-4.1")
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

    report_title = "自动文献日报" if report_type == "daily" else "自动文献周报"
    prompt = (
        "你是研究秘书助手，请输出高质量结构化 Markdown 报告。"
        "要求：\n"
        "1) 先结论后细节；\n"
        "2) 对每条判断标注依据（rows 字段）；\n"
        "3) 必须给出可执行行动清单；\n"
        "4) 信息不足处写明风险，不要凑字数。\n"
        f"report_type: {report_type}\n"
        f"today: {today}\n"
        f"week_tag: {week_tag}\n"
        f"notes_count: {len(note_titles)}\n"
        f"note_titles: {json.dumps(note_titles, ensure_ascii=False)}\n"
        f"rows: {json.dumps(rows_payload, ensure_ascii=False)}\n\n"
        f"evidence_stats: {json.dumps(evidence_stats or {}, ensure_ascii=False)}\n\n"
        "输出格式（标题必须一致）：\n"
        f"# {report_title}\n"
        "## 执行摘要\n"
        "## 本期新增与更新\n"
        "## 机制主线进展\n"
        "## 高价值论文卡片\n"
        "## 风险与证据空白\n"
        "## 下一步行动\n"
    )

    content = _call_chat_completion(prompt=prompt, api_key=api_key, model=model, timeout_seconds=timeout_seconds)
    if not content:
        return _rule_report_markdown(note_titles=note_titles, report_type=report_type, evidence_stats=evidence_stats)
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
        "### 🧭 阅读协议\n"
        "- 文本可读性：\n"
        "- 证据优先级：\n"
        "- 解析风险提示：\n\n"
        "### 📖 粗读筛选\n"
        "- 期刊影响力：\n"
        "- 研究问题重要性：\n"
        "- 方法新颖性：\n"
        "- 数据完整性：\n"
        "- 结论明确性：\n\n"
        "### 💡 创新点\n"
        "- 科学问题：\n"
        "- 研究工具/方法：\n"
        "- 研究思路：\n"
        "- 理论/机制：\n\n"
        "### 📝 笔记原子化\n"
        "#### ⚡ 性能\n"
        "-\n"
        "#### 🔬 机制\n"
        "-\n"
        "#### ✨ 理论\n"
        "-\n\n"
        "### 🤔 思考\n"
        "- 主要优点：\n"
        "- 主要缺点：\n"
        "- 疑问与争议：\n"
        "- 研究启发：\n\n"
        "### 🧮 严格评分\n"
        "- 总分（0-100）：\n"
        "- 一句话结论：\n"
    )
    path = Path("prompts/ai_note_template.md")
    if not path.exists():
        return default
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return default


def assess_evidence_level(row: dict[str, Any]) -> str:
    local_pdf_path = str(row.get("local_pdf_path", "")).strip()
    if local_pdf_path:
        return "fulltext-local"

    pdf_url = str(row.get("pdf_url", "")).strip()
    if pdf_url:
        return "fulltext-url"

    abstract = str(row.get("abstract", "")).strip()
    if len(abstract) >= 120:
        return "abstract"

    doi = str(row.get("doi", "")).strip()
    if doi:
        return "metadata"

    return "none"


def _fetch_paper_excerpt_with_level(row: dict[str, Any], timeout_seconds: int = 30) -> tuple[str, str]:
    abstract = str(row.get("abstract", "")).strip()
    base_level = assess_evidence_level(row)
    pdf_url = str(row.get("pdf_url", "")).strip()
    if not pdf_url:
        try:
            from .zotero import resolve_pdf_url

            pdf_url = resolve_pdf_url(row=row, timeout_seconds=min(timeout_seconds, 20))
        except Exception:
            pdf_url = ""

    if not pdf_url:
        if abstract:
            return abstract, "abstract"
        doi = str(row.get("doi", "")).strip()
        if doi:
            oa_abs = _fetch_openalex_abstract_by_doi(doi=doi, timeout_seconds=min(timeout_seconds, 15))
            if oa_abs:
                return oa_abs, "abstract-openalex"
        return "无摘要与全文节选。", base_level

    try:
        raw = _download_pdf_bytes(pdf_url, timeout_seconds=timeout_seconds)
        text = _extract_pdf_text(raw)
        if text:
            text = " ".join(text.split())
            return text[:12000], "fulltext"
    except Exception:
        pass

    if abstract:
        return abstract, "abstract"
    return "无摘要与全文节选。", base_level


def _pending_fulltext_note_markdown(row: dict[str, Any], zotero_key: str, evidence_level: str) -> str:
    title = str(row.get("title", "")).strip() or "Untitled"
    doi = str(row.get("doi", "")).strip()
    url = str(row.get("source_url", "")).strip()
    journal = str(row.get("journal", "")).strip()
    year = str(row.get("year", "")).strip()

    return (
        f"# AI分析 - {title}\n\n"
        f"**Zotero:** [Open in Zotero](zotero://select/library/items/{zotero_key})  \n"
        f"**DOI:** {doi}  \n"
        f"**URL:** {url}  \n"
        f"**Journal/Year:** {journal} / {year}\n\n"
        "## 状态\n"
        "- 当前为待补全文短卡，不输出深度机制分析。\n"
        f"- 证据等级: {evidence_level}\n"
        "- 原因: 未获取到可读全文或足够摘要。\n\n"
        "## 下一步\n"
        "- 在 Zotero 中确认附件是否已成功下载并可打开。\n"
        "- 若 DOI 可访问，补抓 PDF 后重跑生成笔记。\n"
        "- 对高优先级文献手动粘贴摘要/关键图注再二次总结。\n"
    )


def _fetch_openalex_abstract_by_doi(doi: str, timeout_seconds: int = 15) -> str:
    doi_path = quote(f"https://doi.org/{doi}", safe="")
    url = f"https://api.openalex.org/works/{doi_path}"
    req = Request(url, method="GET", headers={"User-Agent": "litrature-bot/1.0"})
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return ""

    abstract_index = data.get("abstract_inverted_index")
    if not isinstance(abstract_index, dict):
        return ""

    max_pos = -1
    for positions in abstract_index.values():
        if isinstance(positions, list) and positions:
            local_max = max((int(p) for p in positions if isinstance(p, int)), default=-1)
            if local_max > max_pos:
                max_pos = local_max

    if max_pos < 0:
        return ""

    words = [""] * (max_pos + 1)
    for token, positions in abstract_index.items():
        if not isinstance(token, str) or not isinstance(positions, list):
            continue
        for p in positions:
            if isinstance(p, int) and 0 <= p <= max_pos:
                words[p] = token

    text = " ".join(w for w in words if w).strip()
    return text[:6000]


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


def _rule_report_markdown(note_titles: list[str], report_type: str, evidence_stats: dict[str, int] | None = None) -> str:
    title = "自动文献日报" if report_type == "daily" else "自动文献周报"
    stats = evidence_stats or {}
    readable = int(stats.get("readable", 0))
    total = int(stats.get("total", len(note_titles) or 0))
    readability = 0.0 if total <= 0 else (readable / total * 100)
    lines = [
        f"# {title}",
        "",
        "## 执行摘要",
        f"- 本期处理条目: {len(note_titles)}",
        f"- 全文可读率: {readable}/{total} ({readability:.1f}%)",
        "- 报告模式: 规则兜底（未调用 GPT）。",
        "",
        "## 本期新增与更新",
        f"- 笔记条目数: {len(note_titles)}",
        "",
        "## 机制主线进展",
        "- 关注 Zn2+ 溶剂化/去溶剂化、界面稳定层、HER 抑制协同机制。",
        "",
        "## 高价值论文卡片",
    ]
    lines.extend([f"- {name}" for name in note_titles] or ["- 无新增条目"]) 
    lines.extend(
        [
            "",
            "## 风险与证据空白",
            "- 缺少全文证据时，结论置信度偏低。",
            "",
            "## 下一步行动",
            "- 优先补抓可获取 PDF 的条目并二次总结。",
            "- 对高相关条目补充对照实验与机制证据摘录。",
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
