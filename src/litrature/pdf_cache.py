from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def cache_pdf_for_row(
    row: dict[str, Any],
    pdf_url: str,
    out_dir: Path,
    index_path: Path | None = None,
    timeout_seconds: int = 30,
) -> tuple[bool, str]:
    pdf_url = str(pdf_url or "").strip()
    if not pdf_url:
        return False, ""

    out_dir.mkdir(parents=True, exist_ok=True)
    cache_key = _build_cache_key(row=row, pdf_url=pdf_url)
    if index_path:
        index = _load_index(index_path)
        cached = str(index.get(cache_key, "")).strip()
        if cached:
            cached_path = Path(cached)
            if cached_path.exists() and cached_path.stat().st_size > 0:
                return True, str(cached_path)

    target = out_dir / _build_pdf_filename(row=row, pdf_url=pdf_url)
    if target.exists() and target.stat().st_size > 0:
        if index_path:
            _save_index_entry(index_path=index_path, key=cache_key, value=str(target))
        return True, str(target)

    req = Request(pdf_url, method="GET", headers={"User-Agent": "litrature-bot/1.0"})
    with urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read(30 * 1024 * 1024)

    if not raw:
        return False, ""

    target.write_bytes(raw)
    if index_path:
        _save_index_entry(index_path=index_path, key=cache_key, value=str(target))
    return True, str(target)


def _build_pdf_filename(row: dict[str, Any], pdf_url: str) -> str:
    doi = str(row.get("doi", "")).strip().lower()
    title = str(row.get("title", "")).strip().lower()
    year = str(row.get("year", "")).strip()
    seed = f"{doi}|{title}|{year}|{pdf_url}".encode("utf-8")
    suffix = hashlib.sha1(seed).hexdigest()[:10]

    stem = _safe_stem(str(row.get("title", "")).strip())
    return f"{stem}-{suffix}.pdf"


def _build_cache_key(row: dict[str, Any], pdf_url: str) -> str:
    doi = str(row.get("doi", "")).strip().lower()
    title = str(row.get("title", "")).strip().lower()
    year = str(row.get("year", "")).strip()
    if doi:
        return f"doi:{doi}"
    seed = f"{title}|{year}|{pdf_url}".encode("utf-8")
    return f"title:{hashlib.sha1(seed).hexdigest()[:20]}"


def _load_index(index_path: Path) -> dict[str, str]:
    if not index_path.exists():
        return {}
    try:
        with index_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return {}
    return {}


def _save_index_entry(index_path: Path, key: str, value: str) -> None:
    index = _load_index(index_path)
    index[key] = value
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _safe_stem(text: str) -> str:
    text = text or "paper"
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[^a-zA-Z0-9 _-]", "", text)
    text = text.replace(" ", "_")
    return (text[:80] or "paper")
