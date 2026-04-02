from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def cache_pdf_for_row(
    row: dict[str, Any],
    pdf_url: str,
    out_dir: Path,
    timeout_seconds: int = 30,
) -> tuple[bool, str]:
    pdf_url = str(pdf_url or "").strip()
    if not pdf_url:
        return False, ""

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / _build_pdf_filename(row=row, pdf_url=pdf_url)
    if target.exists() and target.stat().st_size > 0:
        return True, str(target)

    req = Request(pdf_url, method="GET", headers={"User-Agent": "litrature-bot/1.0"})
    with urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read(30 * 1024 * 1024)

    if not raw:
        return False, ""

    target.write_bytes(raw)
    return True, str(target)


def _build_pdf_filename(row: dict[str, Any], pdf_url: str) -> str:
    doi = str(row.get("doi", "")).strip().lower()
    title = str(row.get("title", "")).strip().lower()
    year = str(row.get("year", "")).strip()
    seed = f"{doi}|{title}|{year}|{pdf_url}".encode("utf-8")
    suffix = hashlib.sha1(seed).hexdigest()[:10]

    stem = _safe_stem(str(row.get("title", "")).strip())
    return f"{stem}-{suffix}.pdf"


def _safe_stem(text: str) -> str:
    text = text or "paper"
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[^a-zA-Z0-9 _-]", "", text)
    text = text.replace(" ", "_")
    return (text[:80] or "paper")
