from __future__ import annotations

import json
import os
from typing import Any
from urllib.request import Request, urlopen


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
